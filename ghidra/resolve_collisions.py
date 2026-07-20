# -*- coding: utf-8 -*-
# Resolve BSim collisions using decompiler p-code struct offsets.
#
# Many LVGL getter/setter functions have identical BSim signatures because
# they all do `return *(base + OFFSET)` with different offsets.
# This script decompiles each collision group and matches by the offset constants.
#
# @category G2

import json as json_mod
import ghidra.features.bsim.query.FunctionDatabase as FunctionDatabase
import ghidra.features.bsim.query.GenSignatures as GenSignatures
import generic.lsh.vector.VectorCompare as VectorCompare
from ghidra.program.model.symbol import SourceType
from ghidra.app.decompiler import DecompInterface
from collections import defaultdict

program = currentProgram
fm = program.getFunctionManager()

# Open ref
project = state.getProject()
ref_file = None
for f in project.getProjectData().getRootFolder().getFiles():
    if f.getName() == "lvgl_ref.o":
        ref_file = f
        break
ref_prog = ref_file.getDomainObject(java.lang.Object(), True, True, monitor)
ref_fm = ref_prog.getFunctionManager()

# Load ref symbols
ref_syms = {}
with open('/Users/mojashi/repos/odd/lv_port_ambiq/build_ref/lvgl_symbols.txt', 'r') as fi:
    for line in fi:
        parts = line.strip().split('|')
        if len(parts) == 3:
            ref_syms[parts[0]] = int(parts[1], 16)

# Already named
already = set()
for func in fm.getFunctions(True):
    n = func.getName()
    if not n.startswith('FUN_'):
        already.add(n)

# BSim setup
vectorFactory = FunctionDatabase.generateLSHVectorFactory()
config = FunctionDatabase.loadConfigurationTemplate("medium_32")
vectorFactory.set(config.weightfactory, config.idflookup, config.info.settings)

# Generate ref sigs
gensig_ref = GenSignatures(True)
gensig_ref.setVectorFactory(vectorFactory)
repo = "ghidra://localhost/" + state.getProject().getName()
gensig_ref.openProgram(ref_prog, None, None, None, repo, GenSignatures.getPathFromDomainFile(ref_prog))
gensig_ref.scanFunctions(ref_fm.getFunctions(True), ref_fm.getFunctionCount(), monitor)
ref_mgr = gensig_ref.getDescriptionManager()
ref_vecs = {}
di = ref_mgr.listAllFunctions()
while di.hasNext():
    d = di.next()
    n = d.getFunctionName()
    if n not in already and n in ref_syms:
        sr = d.getSignatureRecord()
        if sr:
            v = sr.getLSHVector()
            if v:
                ref_vecs[n] = v

# Generate FW sigs
gensig_fw = GenSignatures(True)
gensig_fw.setVectorFactory(vectorFactory)
gensig_fw.openProgram(program, None, None, None, repo, GenSignatures.getPathFromDomainFile(program))
gensig_fw.scanFunctions(fm.getFunctions(True), fm.getFunctionCount(), monitor)
fw_mgr = gensig_fw.getDescriptionManager()
fw_vecs = {}
di2 = fw_mgr.listAllFunctions()
while di2.hasNext():
    d = di2.next()
    n = d.getFunctionName()
    if n.startswith('FUN_'):
        sr = d.getSignatureRecord()
        if sr:
            v = sr.getLSHVector()
            if v:
                fw_vecs[n] = v

print("resolve: %d unmatched ref, %d FW FUN_" % (len(ref_vecs), len(fw_vecs)))

# Find collision groups: multiple ref funcs -> same best FW func
ref_to_best = {}
vc = VectorCompare()
processed = 0
for ref_name, ref_vec in ref_vecs.items():
    processed += 1
    if processed % 100 == 0:
        print("resolve: BSim %d/%d..." % (processed, len(ref_vecs)))
    best_sim = 0
    best_fw = None
    for fw_name, fw_vec in fw_vecs.items():
        sim = ref_vec.compare(fw_vec, vc)
        if sim > best_sim:
            best_sim = sim
            best_fw = fw_name
    if best_fw and best_sim > 0.1:
        ref_to_best[ref_name] = (best_fw, best_sim)

# Group by FW function
fw_groups = defaultdict(list)
for ref_name, (fw_name, sim) in ref_to_best.items():
    fw_groups[fw_name].append((ref_name, sim))

# Collision groups: FW funcs with multiple ref candidates
collision_groups = {k: v for k, v in fw_groups.items() if len(v) > 1}
solo_matches = {k: v[0] for k, v in fw_groups.items() if len(v) == 1}

print("resolve: %d collision groups, %d solo matches" % (len(collision_groups), len(solo_matches)))

# ---- Extract struct offsets via decompiler ----
print("resolve: Decompiling to extract struct offsets...")

def setup_decompiler(prog):
    decomp = DecompInterface()
    decomp.openProgram(prog)
    return decomp

def get_offset_constants(decomp, func):
    """Extract offset constants from decompiled code.
    Returns set of integers that appear as struct offsets or array indices."""
    result = decomp.decompileFunction(func, 30, monitor)
    if not result or not result.decompileCompleted():
        return set()

    # Parse the decompiled C for offset patterns
    c_code = result.getDecompiledFunction().getC()
    if not c_code:
        return set()

    offsets = set()
    import re
    # Match patterns like: *(param + 0x1c), *(int *)(param + 0x20), etc
    for m in re.finditer(r'\+\s*(0x[0-9a-f]+|[0-9]+)\)', c_code):
        val_str = m.group(1)
        try:
            if val_str.startswith('0x'):
                val = int(val_str, 16)
            else:
                val = int(val_str)
            if 0 < val < 0x1000:  # reasonable struct offset range
                offsets.add(val)
        except:
            pass

    # Also match direct integer returns: return 0x1234
    for m in re.finditer(r'return\s+(0x[0-9a-f]+|[0-9]+)\s*;', c_code):
        val_str = m.group(1)
        try:
            if val_str.startswith('0x'):
                val = int(val_str, 16)
            else:
                val = int(val_str)
            if val > 0:
                offsets.add(val)
        except:
            pass

    return offsets

decomp_ref = setup_decompiler(ref_prog)
decomp_fw = setup_decompiler(program)

ref_func_map = {}
for func in ref_fm.getFunctions(True):
    ref_func_map[func.getName()] = func

fw_func_map = {}
for func in fm.getFunctions(True):
    fw_func_map[func.getName()] = func

# ---- Resolve collisions ----
print("resolve: Resolving %d collision groups..." % len(collision_groups))

resolved = 0
unresolvable = 0
applied_total = 0

for fw_name, ref_candidates in sorted(collision_groups.items()):
    # Get FW function's decompiled offsets
    fw_func = fw_func_map.get(fw_name)
    if not fw_func:
        continue
    fw_offsets = get_offset_constants(decomp_fw, fw_func)

    if not fw_offsets:
        unresolvable += 1
        continue

    # For each ref candidate, get its offsets
    best_match = None
    best_overlap = 0
    candidates_with_offsets = []

    for ref_name, sim in ref_candidates:
        ref_func = ref_func_map.get(ref_name)
        if not ref_func:
            continue
        ref_offsets = get_offset_constants(decomp_ref, ref_func)
        if not ref_offsets:
            continue

        overlap = len(fw_offsets & ref_offsets)
        jaccard = float(overlap) / len(fw_offsets | ref_offsets) if (fw_offsets | ref_offsets) else 0
        candidates_with_offsets.append((ref_name, sim, ref_offsets, overlap, jaccard))

    if not candidates_with_offsets:
        unresolvable += 1
        continue

    # Sort by offset overlap (Jaccard), then by BSim sim
    candidates_with_offsets.sort(key=lambda x: (-x[4], -x[1]))
    best = candidates_with_offsets[0]
    second = candidates_with_offsets[1] if len(candidates_with_offsets) > 1 else None

    # Only resolve if best is clearly better
    if best[4] > 0 and (second is None or best[4] > second[4]):
        ref_name = best[0]
        if ref_name not in already:
            # Check FW func is still unnamed
            if fw_func.getName().startswith('FUN_'):
                fw_func.setName(ref_name, SourceType.ANALYSIS)
                fw_func.setComment("LVGL collision resolved: offset_jaccard=%.2f bsim=%.3f offsets=%s" %
                                   (best[4], best[1], sorted(best[2])[:5]))
                applied_total += 1
                if applied_total <= 30:
                    print("resolve: %s -> %s (jaccard=%.2f bsim=%.3f fw_off=%s ref_off=%s)" %
                          (fw_name, ref_name, best[4], best[1],
                           sorted(fw_offsets)[:4], sorted(best[2])[:4]))
        resolved += 1
    else:
        unresolvable += 1

# Also handle the FW functions that now have NO collision (were claimed by only 1 ref after others got resolved elsewhere)

print("")
print("resolve: === RESULTS ===")
print("  Collision groups: %d" % len(collision_groups))
print("  Resolved: %d" % resolved)
print("  Unresolvable: %d" % unresolvable)
print("  Applied: %d" % applied_total)
print("  Solo matches (no collision): %d" % len(solo_matches))

# Apply solo matches too (these had no collision to begin with)
solo_applied = 0
for fw_name, (ref_name, sim) in solo_matches.items():
    if ref_name in already:
        continue
    fw_func = fw_func_map.get(fw_name)
    if not fw_func or not fw_func.getName().startswith('FUN_'):
        continue
    # Only if not already applied by collision resolution
    if not fw_func.getName().startswith('FUN_'):
        continue
    # Apply with comment
    fw_func.setName(ref_name, SourceType.ANALYSIS)
    fw_func.setComment("LVGL solo BSim: sim=%.3f" % sim)
    solo_applied += 1

print("  Solo applied: %d" % solo_applied)

decomp_ref.dispose()
decomp_fw.dispose()
ref_prog.release(java.lang.Object())
