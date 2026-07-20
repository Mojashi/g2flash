# -*- coding: utf-8 -*-
# Re-run BSim matching for VERIFIED/PLAUSIBLE functions and apply.
# Uses the classification report to know WHICH ref functions to match,
# then finds the best FW candidate via BSim and applies.
#
# @category G2

import json as json_mod
import ghidra.features.bsim.query.FunctionDatabase as FunctionDatabase
import ghidra.features.bsim.query.GenSignatures as GenSignatures
import generic.lsh.vector.VectorCompare as VectorCompare
from ghidra.program.model.symbol import SourceType

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

# Load report
with open('/Users/mojashi/repos/odd/g2flash/ghidra/lvgl_verify_report.json', 'r') as fi:
    report = json_mod.load(fi)

# Targets: VERIFIED + PLAUSIBLE with sim >= 0.3
targets = set()
for entry in report:
    d = entry.get('disposition', '')
    if d in ('VERIFIED', 'PLAUSIBLE'):
        targets.add(entry['name'])
    elif d == 'PLAUSIBLE_WITH_CAVEAT' and entry.get('bsim_sim', 0) >= 0.5:
        # Only non-collision caveats
        violations = entry.get('violations', [])
        if not any('COLLISION' in v for v in violations):
            targets.add(entry['name'])

# Already named in FW
already = set()
for func in fm.getFunctions(True):
    n = func.getName()
    if not n.startswith('FUN_'):
        already.add(n)

targets -= already
print("apply2: %d targets to match" % len(targets))

if not targets:
    print("apply2: Nothing to do")
    ref_prog.release(java.lang.Object())
    import sys
    sys.exit(0)

# BSim setup
vectorFactory = FunctionDatabase.generateLSHVectorFactory()
config = FunctionDatabase.loadConfigurationTemplate("medium_32")
vectorFactory.set(config.weightfactory, config.idflookup, config.info.settings)

# Ref sigs
gensig_ref = GenSignatures(True)
gensig_ref.setVectorFactory(vectorFactory)
repo = "ghidra://localhost/" + state.getProject().getName()
gensig_ref.openProgram(ref_prog, None, None, None, repo, GenSignatures.getPathFromDomainFile(ref_prog))
gensig_ref.scanFunctions(ref_prog.getFunctionManager().getFunctions(True),
                        ref_prog.getFunctionManager().getFunctionCount(), monitor)
ref_mgr = gensig_ref.getDescriptionManager()

ref_vecs = {}
di = ref_mgr.listAllFunctions()
while di.hasNext():
    d = di.next()
    n = d.getFunctionName()
    if n in targets:
        sr = d.getSignatureRecord()
        if sr:
            v = sr.getLSHVector()
            if v:
                ref_vecs[n] = v

print("apply2: %d ref vectors for targets" % len(ref_vecs))

# FW sigs
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

print("apply2: %d FW vectors" % len(fw_vecs))

# Match each target
applied = 0
fw_func_map = {}
for func in fm.getFunctions(True):
    fw_func_map[func.getName()] = func

used_fw = set()
matches = []

for ref_name, ref_vec in ref_vecs.items():
    best_sim = 0
    best_fw = None
    vc = VectorCompare()
    for fw_name, fw_vec in fw_vecs.items():
        if fw_name in used_fw:
            continue
        sim = ref_vec.compare(fw_vec, vc)
        if sim > best_sim:
            best_sim = sim
            best_fw = fw_name
    if best_fw:
        matches.append((best_sim, ref_name, best_fw))

# Sort by sim descending, apply greedily
matches.sort(key=lambda x: -x[0])
for sim, ref_name, fw_name in matches:
    if fw_name in used_fw:
        continue
    func = fw_func_map.get(fw_name)
    if not func or not func.getName().startswith('FUN_'):
        continue
    used_fw.add(fw_name)
    func.setName(ref_name, SourceType.ANALYSIS)
    func.setComment("LVGL verified/plausible: BSim sim=%.3f" % sim)
    applied += 1
    print("apply2: %s -> %s (sim=%.3f)" % (fw_name, ref_name, sim))

print("apply2: === DONE: %d applied ===" % applied)

ref_prog.release(java.lang.Object())
