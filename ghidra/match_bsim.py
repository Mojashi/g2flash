# -*- coding: utf-8 -*-
# Ghidra headless script: BSim decompiler-based similarity matching.
#
# Uses Ghidra's BSim engine to compare functions between the FW and the
# LVGL reference program. BSim operates on the decompiler's abstract syntax
# tree (p-code), making it robust across different compilers (IAR vs GCC).
#
# @category G2

import java.io.File as File
import ghidra.features.bsim.query.FunctionDatabase as FunctionDatabase
import ghidra.features.bsim.query.GenSignatures as GenSignatures
import generic.lsh.vector.VectorCompare as VectorCompare
from ghidra.program.model.symbol import SourceType

program = currentProgram
fm = program.getFunctionManager()

# ---- Step 1: Open reference program ----
print("match_bsim: Step 1 - Opening reference program...")

project = state.getProject()
ref_file = None
for f in project.getProjectData().getRootFolder().getFiles():
    if f.getName() == "lvgl_ref.o":
        ref_file = f
        break

if not ref_file:
    print("match_bsim: ERROR - lvgl_ref.o not found")
    import sys
    sys.exit(1)

ref_prog = ref_file.getDomainObject(java.lang.Object(), True, True, monitor)
ref_fm = ref_prog.getFunctionManager()

print("match_bsim:   FW: %d functions, Ref: %d functions" %
      (fm.getFunctionCount(), ref_fm.getFunctionCount()))

# ---- Step 2: Initialize BSim vector factory ----
print("match_bsim: Step 2 - Initializing BSim engine...")

vectorFactory = FunctionDatabase.generateLSHVectorFactory()
config = FunctionDatabase.loadConfigurationTemplate("medium_32")
vectorFactory.set(config.weightfactory, config.idflookup, config.info.settings)

# ---- Step 3: Generate signatures for reference ----
print("match_bsim: Step 3 - Generating reference signatures...")

gensig_ref = GenSignatures(True)
gensig_ref.setVectorFactory(vectorFactory)
repo = "ghidra://localhost/" + state.getProject().getName()
path_ref = GenSignatures.getPathFromDomainFile(ref_prog)
gensig_ref.openProgram(ref_prog, None, None, None, repo, path_ref)
ref_iter = ref_fm.getFunctions(True)
gensig_ref.scanFunctions(ref_iter, ref_fm.getFunctionCount(), monitor)
ref_manager = gensig_ref.getDescriptionManager()

# Collect reference function signatures
ref_sigs = {}  # name -> (desc, LSHVector)
ref_desc_iter = ref_manager.listAllFunctions()
while ref_desc_iter.hasNext():
    desc = ref_desc_iter.next()
    sig_rec = desc.getSignatureRecord()
    if sig_rec is not None:
        vec = sig_rec.getLSHVector()
        if vec is not None:
            name = desc.getFunctionName()
            ref_sigs[name] = (desc, vec)

print("match_bsim:   Generated %d reference signatures" % len(ref_sigs))

# ---- Step 4: Generate signatures for FW ----
print("match_bsim: Step 4 - Generating FW signatures...")

gensig_fw = GenSignatures(True)
gensig_fw.setVectorFactory(vectorFactory)
path_fw = GenSignatures.getPathFromDomainFile(program)
gensig_fw.openProgram(program, None, None, None, repo, path_fw)
fw_iter = fm.getFunctions(True)
gensig_fw.scanFunctions(fw_iter, fm.getFunctionCount(), monitor)
fw_manager = gensig_fw.getDescriptionManager()

# Collect FW function signatures (only FUN_ functions)
fw_sigs = {}  # name -> (desc, LSHVector)
fw_desc_iter = fw_manager.listAllFunctions()
while fw_desc_iter.hasNext():
    desc = fw_desc_iter.next()
    sig_rec = desc.getSignatureRecord()
    if sig_rec is not None:
        vec = sig_rec.getLSHVector()
        if vec is not None:
            name = desc.getFunctionName()
            fw_sigs[name] = (desc, vec)

print("match_bsim:   Generated %d FW signatures" % len(fw_sigs))

# ---- Step 5: Compare all FW FUN_ against all ref ----
print("match_bsim: Step 5 - Comparing signatures...")

already_named = set()
for func in fm.getFunctions(True):
    n = func.getName()
    if not n.startswith('FUN_'):
        already_named.add(n)

# Pre-filter: only compare FUN_ functions
fw_unnamed = {k: v for k, v in fw_sigs.items() if k.startswith('FUN_')}
ref_unmatched = {k: v for k, v in ref_sigs.items() if k not in already_named}

print("match_bsim:   Comparing %d FW unnamed x %d ref unmatched..." %
      (len(fw_unnamed), len(ref_unmatched)))

SIMILARITY_THRESHOLD = 0.5
matches = []  # (fw_name, ref_name, similarity, significance)
processed = 0

for fw_name, (fw_desc, fw_vec) in fw_unnamed.items():
    processed += 1
    if processed % 500 == 0:
        print("match_bsim:   ... %d/%d processed, %d matches" %
              (processed, len(fw_unnamed), len(matches)))

    best_sim = 0
    best_ref = None
    second_sim = 0
    best_signif = 0

    # Skip low self-significance functions (too simple to match reliably)
    self_sig = vectorFactory.getSelfSignificance(fw_vec)
    if self_sig < 10.0:
        continue

    veccompare = VectorCompare()
    for ref_name, (ref_desc, ref_vec) in ref_unmatched.items():
        sim = fw_vec.compare(ref_vec, veccompare)
        signif = vectorFactory.calculateSignificance(veccompare)
        if sim > best_sim:
            second_sim = best_sim
            best_sim = sim
            best_ref = ref_name
            best_signif = signif
        elif sim > second_sim:
            second_sim = sim

    if best_ref and best_sim >= SIMILARITY_THRESHOLD:
        gap = best_sim - second_sim
        matches.append((fw_name, best_ref, best_sim, gap, best_signif))

print("match_bsim:   Raw matches: %d" % len(matches))

# ---- Step 6: Deduplicate ----
matches.sort(key=lambda x: -x[2])
used_ref = set()
used_fw = set()
final = []

for fw_name, ref_name, sim, gap, sig in matches:
    if ref_name in used_ref or fw_name in used_fw:
        continue
    used_ref.add(ref_name)
    used_fw.add(fw_name)
    final.append((fw_name, ref_name, sim, gap, sig))

print("match_bsim:   After dedup: %d" % len(final))

# ---- Step 7: Apply ----
print("match_bsim: Step 7 - Applying matches...")

HIGH_SIM = 0.7
high_count = 0
medium_count = 0

fw_func_by_name = {}
for f in fm.getFunctions(True):
    fw_func_by_name[f.getName()] = f

for fw_name, ref_name, sim, gap, sig in final:
    func = fw_func_by_name.get(fw_name)
    if not func:
        continue

    if sim >= HIGH_SIM and gap >= 0.05:
        func.setName(ref_name, SourceType.ANALYSIS)
        func.setComment("BSim match: sim=%.3f gap=%.3f" % (sim, gap))
        high_count += 1
        if high_count <= 50:
            print("match_bsim:   HIGH  %.3f gap=%.3f %s -> %s" %
                  (sim, gap, fw_name, ref_name))
    elif sim >= SIMILARITY_THRESHOLD:
        from ghidra.program.model.listing import CodeUnit
        cu = program.getListing().getCodeUnitAt(func.getEntryPoint())
        if cu:
            existing = cu.getComment(CodeUnit.PLATE_COMMENT) or ""
            cu.setComment(CodeUnit.PLATE_COMMENT,
                         (existing + "\n" if existing else "") +
                         "BSim candidate: %s sim=%.3f gap=%.3f" % (ref_name, sim, gap))
        medium_count += 1

print("match_bsim: === DONE: %d HIGH (renamed), %d MEDIUM (commented) ===" %
      (high_count, medium_count))

ref_prog.release(java.lang.Object())
