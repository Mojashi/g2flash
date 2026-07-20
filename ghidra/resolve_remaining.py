# -*- coding: utf-8 -*-
# Resolve remaining 313 LVGL functions by searching FW-wide callers.
#
# For POSSIBLY_UNUSED (no callers in ref LVGL): check if the BSim best-match
# FW candidate is called by ANY FW function. If yes -> evidence it exists.
# If the candidate has callers AND passes constraint checks -> VERIFIED.
# If nobody calls it -> DEAD_CODE (linked but unused).
#
# For UNRESOLVED: use FW-side caller context to disambiguate collisions.
#
# @category G2

import json as json_mod
import ghidra.features.bsim.query.FunctionDatabase as FunctionDatabase
import ghidra.features.bsim.query.GenSignatures as GenSignatures
import generic.lsh.vector.VectorCompare as VectorCompare
from ghidra.program.model.symbol import SourceType
from collections import defaultdict, Counter
import re as re_mod

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

# Load report
with open('/Users/mojashi/repos/odd/g2flash/ghidra/lvgl_final_report.json', 'r') as fi:
    report = json_mod.load(fi)

# Get targets
targets = set()
for entry in report:
    if entry.get('disposition') in ('POSSIBLY_UNUSED', 'UNRESOLVED'):
        targets.add(entry['name'])

ref_syms = {}
with open('/Users/mojashi/repos/odd/lv_port_ambiq/build_ref/lvgl_symbols.txt', 'r') as fi:
    for line in fi:
        parts = line.strip().split('|')
        if len(parts) == 3:
            ref_syms[parts[0]] = int(parts[1], 16)

already = set()
for func in fm.getFunctions(True):
    n = func.getName()
    if not n.startswith('FUN_'):
        already.add(n)

targets -= already
print("remaining: %d targets" % len(targets))

# BSim: find best FW match for each target
vectorFactory = FunctionDatabase.generateLSHVectorFactory()
config = FunctionDatabase.loadConfigurationTemplate("medium_32")
vectorFactory.set(config.weightfactory, config.idflookup, config.info.settings)

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
    if n in targets:
        sr = d.getSignatureRecord()
        if sr:
            v = sr.getLSHVector()
            if v:
                ref_vecs[n] = v

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

# Build FULL FW call graph (callers of every function)
print("remaining: Building FW call graph...")
fw_callers = defaultdict(set)
fw_callees = defaultdict(set)
for func in fm.getFunctions(True):
    name = func.getName()
    for cu in program.getListing().getCodeUnits(func.getBody(), True):
        if hasattr(cu, 'getMnemonicString'):
            mn = cu.getMnemonicString()
            if mn and mn.lower() in ('bl', 'blx'):
                for ref in cu.getReferencesFrom():
                    if ref.getReferenceType().isCall():
                        t = fm.getFunctionAt(ref.getToAddress())
                        if t:
                            fw_callees[name].add(t.getName())
                            fw_callers[t.getName()].add(name)

print("remaining:   %d functions with callers" % len(fw_callers))

# Extract constants from FW functions (for verification)
def get_imm_constants(func):
    consts = set()
    for cu in program.getListing().getCodeUnits(func.getBody(), True):
        if hasattr(cu, 'getNumOperands'):
            for i in range(cu.getNumOperands()):
                for op in cu.getOpObjects(i):
                    if hasattr(op, 'getUnsignedValue'):
                        val = op.getUnsignedValue()
                        if 32 < val < 0x10000 and val not in (64, 128, 256, 512, 1024, 0xff, 0xffff):
                            consts.add(val)
    return consts

def get_string_refs_fw(func):
    strings = set()
    for cu in program.getListing().getCodeUnits(func.getBody(), True):
        for ref in cu.getReferencesFrom():
            if ref.getReferenceType().isData():
                d = program.getListing().getDefinedDataAt(ref.getToAddress())
                if d and d.hasStringValue():
                    s = d.getValue()
                    if s and len(s) > 3:
                        strings.add(s)
    return strings

# Same for ref
ref_func_map = {}
for func in ref_fm.getFunctions(True):
    ref_func_map[func.getName()] = func

def get_imm_constants_ref(func):
    consts = set()
    for cu in ref_prog.getListing().getCodeUnits(func.getBody(), True):
        if hasattr(cu, 'getNumOperands'):
            for i in range(cu.getNumOperands()):
                for op in cu.getOpObjects(i):
                    if hasattr(op, 'getUnsignedValue'):
                        val = op.getUnsignedValue()
                        if 32 < val < 0x10000 and val not in (64, 128, 256, 512, 1024, 0xff, 0xffff):
                            consts.add(val)
    return consts

def get_string_refs_ref(func):
    strings = set()
    for cu in ref_prog.getListing().getCodeUnits(func.getBody(), True):
        for ref in cu.getReferencesFrom():
            if ref.getReferenceType().isData():
                d = ref_prog.getListing().getDefinedDataAt(ref.getToAddress())
                if d and d.hasStringValue():
                    s = d.getValue()
                    if s and len(s) > 3:
                        strings.add(s)
    return strings

# Process each target
print("remaining: Processing %d targets..." % len(targets))

fw_func_map = {}
for func in fm.getFunctions(True):
    fw_func_map[func.getName()] = func

results = {}
processed = 0
matched_new = 0
inlined_confirmed = 0
dead_code = 0

for ref_name in sorted(targets):
    processed += 1
    if processed % 50 == 0:
        print("remaining: %d/%d (matched=%d inlined=%d dead=%d)" %
              (processed, len(targets), matched_new, inlined_confirmed, dead_code))

    gcc_size = ref_syms.get(ref_name, 0)
    r = {'name': ref_name, 'gcc_size': gcc_size}

    # Find BSim best match
    if ref_name not in ref_vecs:
        r['disposition'] = 'NO_BSIM_SIG'
        r['evidence'] = 'No BSim signature'
        results[ref_name] = r
        continue

    ref_vec = ref_vecs[ref_name]
    best_sim = 0
    best_fw = None
    second_sim = 0
    vc = VectorCompare()
    for fw_name, fw_vec in fw_vecs.items():
        sim = ref_vec.compare(fw_vec, vc)
        if sim > best_sim:
            second_sim = best_sim
            best_sim = sim
            best_fw = fw_name
        elif sim > second_sim:
            second_sim = sim

    if not best_fw or best_sim < 0.05:
        if gcc_size <= 40:
            r['disposition'] = 'INLINED'
            r['evidence'] = '%dB, no BSim candidate' % gcc_size
            inlined_confirmed += 1
        else:
            r['disposition'] = 'ABSENT'
            r['evidence'] = '%dB, no BSim match at all' % gcc_size
        results[ref_name] = r
        continue

    r['best_fw'] = best_fw
    r['bsim_sim'] = best_sim
    r['bsim_gap'] = best_sim - second_sim

    fw_func = fw_func_map.get(best_fw)
    if not fw_func:
        r['disposition'] = 'ERROR'
        results[ref_name] = r
        continue

    # Check if the FW candidate is already named (collision with existing match)
    if not fw_func.getName().startswith('FUN_'):
        r['disposition'] = 'COLLISION_WITH_NAMED'
        r['evidence'] = 'Best match %s already named as %s' % (best_fw, fw_func.getName())
        if gcc_size <= 40:
            r['disposition'] = 'INLINED'
            r['evidence'] += ' (small enough to be inlined)'
            inlined_confirmed += 1
        results[ref_name] = r
        continue

    # Verification constraints
    evidence = []
    violations = []

    # V1: Does the FW candidate have callers?
    fw_caller_set = fw_callers.get(best_fw, set())
    if fw_caller_set:
        evidence.append('V1_HAS_CALLERS: %d callers' % len(fw_caller_set))
    else:
        # No callers = dead code
        if gcc_size > 100:
            violations.append('V1_NO_CALLERS: %dB function with 0 callers (dead code?)' % gcc_size)

    # V2: Constants
    ref_func = ref_func_map.get(ref_name)
    if ref_func:
        ref_consts = get_imm_constants_ref(ref_func)
        fw_consts = get_imm_constants(fw_func)
        if len(ref_consts) >= 2:
            shared = ref_consts & fw_consts
            overlap = float(len(shared)) / len(ref_consts)
            if overlap >= 0.3:
                evidence.append('V2_CONST: %d/%d shared (%.0f%%)' % (len(shared), len(ref_consts), overlap*100))
            else:
                violations.append('V2_CONST: %d/%d shared (%.0f%%)' % (len(shared), len(ref_consts), overlap*100))

    # V3: Strings
    if ref_func:
        ref_strs = get_string_refs_ref(ref_func)
        fw_strs = get_string_refs_fw(fw_func)
        if ref_strs:
            shared_strs = ref_strs & fw_strs
            if shared_strs:
                evidence.append('V3_STRING: %d/%d shared' % (len(shared_strs), len(ref_strs)))
            else:
                violations.append('V3_STRING: 0/%d shared' % len(ref_strs))

    # V4: Size ratio
    fw_size = fw_func.getBody().getNumAddresses()
    ratio = float(max(gcc_size, fw_size)) / max(min(gcc_size, fw_size), 1)
    if ratio <= 3.0:
        evidence.append('V4_SIZE: ratio=%.1f (%d/%d)' % (ratio, gcc_size, fw_size))
    elif ratio > 5.0:
        violations.append('V4_SIZE: ratio=%.1f (%d/%d)' % (ratio, gcc_size, fw_size))

    # V5: Callees that are anchors
    fw_callee_set = fw_callees.get(best_fw, set())
    anchor_callees = fw_callee_set & already
    if anchor_callees:
        evidence.append('V5_CALLEES: calls %d anchors' % len(anchor_callees))

    # Determine disposition
    n_ev = len(evidence)
    n_viol = len(violations)

    if n_viol == 0 and n_ev >= 2:
        r['disposition'] = 'VERIFIED'
        matched_new += 1
    elif n_viol == 0 and n_ev >= 1:
        r['disposition'] = 'PLAUSIBLE'
        matched_new += 1
    elif n_viol <= 1 and n_ev >= 2:
        r['disposition'] = 'PLAUSIBLE_CAVEAT'
        matched_new += 1
    elif not fw_caller_set and gcc_size <= 200:
        r['disposition'] = 'DEAD_CODE'
        r['evidence_detail'] = 'No callers, size %dB' % gcc_size
        dead_code += 1
    elif gcc_size <= 40:
        r['disposition'] = 'INLINED'
        inlined_confirmed += 1
    else:
        r['disposition'] = 'UNRESOLVED'

    r['evidence'] = evidence
    r['violations'] = violations
    results[ref_name] = r

# Apply VERIFIED and PLAUSIBLE
applied = 0
for ref_name, r in results.items():
    if r.get('disposition') not in ('VERIFIED', 'PLAUSIBLE', 'PLAUSIBLE_CAVEAT'):
        continue
    fw_name = r.get('best_fw')
    if not fw_name:
        continue
    func = fw_func_map.get(fw_name)
    if not func or not func.getName().startswith('FUN_'):
        continue
    func.setName(ref_name, SourceType.ANALYSIS)
    func.setComment("LVGL %s: sim=%.3f" % (r['disposition'], r.get('bsim_sim', 0)))
    applied += 1

# Summary
disp_counts = Counter(r['disposition'] for r in results.values())

print("")
print("remaining: === RESULTS ===")
for d in ['VERIFIED', 'PLAUSIBLE', 'PLAUSIBLE_CAVEAT', 'DEAD_CODE', 'INLINED',
          'COLLISION_WITH_NAMED', 'ABSENT', 'UNRESOLVED', 'NO_BSIM_SIG', 'ERROR']:
    if disp_counts.get(d, 0) > 0:
        print("  %-25s %d" % (d, disp_counts[d]))
print("  Applied: %d" % applied)

# Final overall count
all_matched = len(already) + applied
all_inlined = disp_counts.get('INLINED', 0) + disp_counts.get('COLLISION_WITH_NAMED', 0)
all_dead = disp_counts.get('DEAD_CODE', 0)
all_absent = disp_counts.get('ABSENT', 0) + disp_counts.get('NO_BSIM_SIG', 0)
all_unresolved = disp_counts.get('UNRESOLVED', 0)

# Also count prior inlined from final_report
prior_inlined = 0
for entry in report:
    if entry.get('disposition') in ('INLINED_TRIVIAL', 'LIKELY_INLINED'):
        if entry['name'] not in results:
            prior_inlined += 1

print("")
print("remaining: === FULL 978 ACCOUNTING ===")
print("  MATCHED (named in DB):     %d" % all_matched)
print("  INLINED (this round):      %d" % all_inlined)
print("  INLINED (prior):           %d" % prior_inlined)
print("  DEAD_CODE (linked unused): %d" % all_dead)
print("  ABSENT/NO_SIG:             %d" % all_absent)
print("  UNRESOLVED:                %d" % all_unresolved)
print("  TOTAL:                     %d" % (all_matched + all_inlined + prior_inlined + all_dead + all_absent + all_unresolved))
accounted = all_matched + all_inlined + prior_inlined + all_dead + all_absent
print("  ACCOUNTED: %d/978 (%.1f%%)" % (accounted, 100.0 * accounted / 978))

# Write report
rp = '/Users/mojashi/repos/odd/g2flash/ghidra/lvgl_remaining_report.json'
with open(rp, 'w') as fo:
    fo.write('[\n')
    items = sorted(results.values(), key=lambda x: x.get('disposition', 'Z'))
    for i, r in enumerate(items):
        parts = []
        for k in ['name', 'disposition', 'best_fw', 'bsim_sim', 'bsim_gap', 'gcc_size']:
            v = r.get(k)
            if v is None: continue
            if isinstance(v, str): parts.append('"%s":"%s"' % (k, v.replace('"', "'")))
            elif isinstance(v, float): parts.append('"%s":%.3f' % (k, v))
            elif isinstance(v, int): parts.append('"%s":%d' % (k, v))
        if r.get('evidence') and isinstance(r['evidence'], list):
            es = ','.join(['"%s"' % e.replace('"', "'")[:100] for e in r['evidence']])
            parts.append('"evidence":[%s]' % es)
        if r.get('violations') and isinstance(r['violations'], list):
            vs = ','.join(['"%s"' % v.replace('"', "'")[:100] for v in r['violations']])
            parts.append('"violations":[%s]' % vs)
        fo.write('{%s}%s\n' % (','.join(parts), ',' if i < len(items)-1 else ''))
    fo.write(']\n')
print("remaining: Report -> %s" % rp)

ref_prog.release(java.lang.Object())
