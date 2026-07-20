# -*- coding: utf-8 -*-
# Ghidra headless script: classify ALL 978 LVGL reference functions.
#
# For each ref function, determine disposition:
#   MATCHED     - already named in FW DB (verified by earlier scripts)
#   BEST_MATCH  - BSim best candidate with sim score (for manual/auto review)
#   INLINED     - evidence that the function's code is inlined into a caller
#   TRIVIAL     - too small to distinguish (<=6 instructions)
#
# Outputs a JSON report with every function's disposition + evidence.
#
# @category G2

import json as json_mod
import ghidra.features.bsim.query.FunctionDatabase as FunctionDatabase
import ghidra.features.bsim.query.GenSignatures as GenSignatures
import generic.lsh.vector.VectorCompare as VectorCompare
from ghidra.program.model.symbol import SourceType
from ghidra.app.decompiler import DecompInterface

program = currentProgram
fm = program.getFunctionManager()
listing = program.getListing()

# ---- Open reference ----
print("classify: Opening reference...")
project = state.getProject()
ref_file = None
for f in project.getProjectData().getRootFolder().getFiles():
    if f.getName() == "lvgl_ref.o":
        ref_file = f
        break
ref_prog = ref_file.getDomainObject(java.lang.Object(), True, True, monitor)
ref_fm = ref_prog.getFunctionManager()

# ---- Load ref symbol list ----
ref_syms = {}
with open('/Users/mojashi/repos/odd/lv_port_ambiq/build_ref/lvgl_symbols.txt', 'r') as f:
    for line in f:
        parts = line.strip().split('|')
        if len(parts) == 3:
            ref_syms[parts[0]] = int(parts[1], 16)

# ---- Collect already-matched ----
named_in_fw = set()
for func in fm.getFunctions(True):
    n = func.getName()
    if not n.startswith('FUN_'):
        named_in_fw.add(n)

# ---- BSim setup ----
print("classify: Setting up BSim...")
vectorFactory = FunctionDatabase.generateLSHVectorFactory()
config = FunctionDatabase.loadConfigurationTemplate("medium_32")
vectorFactory.set(config.weightfactory, config.idflookup, config.info.settings)

# Generate ref sigs
gensig_ref = GenSignatures(True)
gensig_ref.setVectorFactory(vectorFactory)
repo = "ghidra://localhost/" + state.getProject().getName()
gensig_ref.openProgram(ref_prog, None, None, None, repo,
                       GenSignatures.getPathFromDomainFile(ref_prog))
gensig_ref.scanFunctions(ref_fm.getFunctions(True), ref_fm.getFunctionCount(), monitor)
ref_mgr = gensig_ref.getDescriptionManager()

ref_vecs = {}
desc_iter = ref_mgr.listAllFunctions()
while desc_iter.hasNext():
    desc = desc_iter.next()
    sr = desc.getSignatureRecord()
    if sr is not None:
        v = sr.getLSHVector()
        if v is not None:
            ref_vecs[desc.getFunctionName()] = (v, vectorFactory.getSelfSignificance(v))

# Generate FW sigs
print("classify: Generating FW signatures...")
gensig_fw = GenSignatures(True)
gensig_fw.setVectorFactory(vectorFactory)
gensig_fw.openProgram(program, None, None, None, repo,
                      GenSignatures.getPathFromDomainFile(program))
gensig_fw.scanFunctions(fm.getFunctions(True), fm.getFunctionCount(), monitor)
fw_mgr = gensig_fw.getDescriptionManager()

fw_vecs = {}
fw_desc_iter = fw_mgr.listAllFunctions()
while fw_desc_iter.hasNext():
    desc = fw_desc_iter.next()
    sr = desc.getSignatureRecord()
    if sr is not None:
        v = sr.getLSHVector()
        if v is not None:
            fw_vecs[desc.getFunctionName()] = v

# ---- Ref function metadata ----
ref_func_map = {}
for func in ref_fm.getFunctions(True):
    ref_func_map[func.getName()] = func

def get_callees_ref(func):
    result = set()
    for cu in ref_prog.getListing().getCodeUnits(func.getBody(), True):
        if hasattr(cu, 'getMnemonicString'):
            mn = cu.getMnemonicString()
            if mn and mn.lower() in ('bl', 'blx'):
                for ref in cu.getReferencesFrom():
                    if ref.getReferenceType().isCall():
                        t = ref_fm.getFunctionAt(ref.getToAddress())
                        if t:
                            result.add(t.getName())
    return result

def get_string_refs_ref(func):
    strings = set()
    for cu in ref_prog.getListing().getCodeUnits(func.getBody(), True):
        for ref in cu.getReferencesFrom():
            if ref.getReferenceType().isData():
                d = ref_prog.getListing().getDefinedDataAt(ref.getToAddress())
                if d and d.hasStringValue():
                    s = d.getValue()
                    if s and len(s) > 2:
                        strings.add(s)
    return strings

# ---- Classify each ref function ----
print("classify: Processing %d ref functions..." % len(ref_syms))

results = []
processed = 0

for ref_name, ref_gcc_size in sorted(ref_syms.items()):
    processed += 1
    if processed % 100 == 0:
        print("classify: ... %d/%d" % (processed, len(ref_syms)))

    entry = {
        'name': ref_name,
        'gcc_size': ref_gcc_size,
    }

    # 1. Already matched?
    if ref_name in named_in_fw:
        entry['disposition'] = 'MATCHED'
        entry['evidence'] = 'Named in FW DB'
        results.append(entry)
        continue

    # 2. BSim analysis
    if ref_name in ref_vecs:
        ref_vec, self_sig = ref_vecs[ref_name]
        entry['bsim_self_sig'] = round(self_sig, 1)

        # Find top 3 BSim matches in FW
        top_matches = []
        vc = VectorCompare()
        for fw_name, fw_vec in fw_vecs.items():
            if not fw_name.startswith('FUN_'):
                continue
            sim = ref_vec.compare(fw_vec, vc)
            signif = vectorFactory.calculateSignificance(vc)
            if sim > 0.1:
                top_matches.append((sim, signif, fw_name))

        top_matches.sort(key=lambda x: -x[0])
        top_matches = top_matches[:3]

        if top_matches:
            best_sim, best_signif, best_fw = top_matches[0]
            entry['best_sim'] = round(best_sim, 3)
            entry['best_signif'] = round(best_signif, 1)
            entry['best_fw'] = best_fw
            if len(top_matches) > 1:
                entry['second_sim'] = round(top_matches[1][0], 3)
                entry['gap'] = round(best_sim - top_matches[1][0], 3)
            else:
                entry['gap'] = round(best_sim, 3)
        else:
            entry['best_sim'] = 0
    else:
        entry['bsim_self_sig'] = 0

    # 3. Classify
    if ref_gcc_size <= 12:
        entry['disposition'] = 'TRIVIAL'
        entry['evidence'] = 'Too small (%dB) - likely inlined or trivial getter/setter' % ref_gcc_size
    elif entry.get('bsim_self_sig', 0) < 10:
        entry['disposition'] = 'TRIVIAL'
        entry['evidence'] = 'Low BSim self-significance (%.1f) - structurally trivial' % entry.get('bsim_self_sig', 0)
    elif entry.get('best_sim', 0) >= 0.7:
        entry['disposition'] = 'LIKELY_MATCH'
        entry['evidence'] = 'BSim sim=%.3f gap=%.3f -> %s' % (
            entry['best_sim'], entry.get('gap', 0), entry.get('best_fw', '?'))
    elif entry.get('best_sim', 0) >= 0.4:
        entry['disposition'] = 'CUSTOMIZED'
        entry['evidence'] = 'BSim sim=%.3f (moderate) -> %s. FW version likely modified by Even.' % (
            entry['best_sim'], entry.get('best_fw', '?'))
    elif entry.get('best_sim', 0) >= 0.2:
        entry['disposition'] = 'WEAK_MATCH'
        entry['evidence'] = 'BSim sim=%.3f (weak) -> %s' % (
            entry['best_sim'], entry.get('best_fw', '?'))
    else:
        # Check if it's called by known functions (inline evidence)
        if ref_name in ref_func_map:
            ref_callers = set()
            for rn, rf in ref_func_map.items():
                if rn == ref_name:
                    continue
                if ref_name in get_callees_ref(rf):
                    ref_callers.add(rn)
            # Are any callers matched in FW?
            matched_callers = ref_callers & named_in_fw
            if matched_callers:
                entry['disposition'] = 'POSSIBLY_INLINED'
                entry['evidence'] = 'No BSim match. Callers in FW: %s. May be inlined.' % list(matched_callers)[:3]
            else:
                entry['disposition'] = 'ABSENT'
                entry['evidence'] = 'No BSim match, no matched callers.'
        else:
            entry['disposition'] = 'ABSENT'
            entry['evidence'] = 'Not in ref program function list.'

    results.append(entry)

# ---- Summary ----
from collections import Counter
disp_counts = Counter(r['disposition'] for r in results)

print("")
print("classify: === SUMMARY ===")
for d in ['MATCHED', 'LIKELY_MATCH', 'CUSTOMIZED', 'WEAK_MATCH', 'TRIVIAL', 'POSSIBLY_INLINED', 'ABSENT']:
    print("  %-20s %d" % (d, disp_counts.get(d, 0)))
print("  TOTAL:             %d" % len(results))

# Stats for LIKELY_MATCH
likely = [r for r in results if r['disposition'] == 'LIKELY_MATCH']
if likely:
    print("")
    print("classify: LIKELY_MATCH details (auto-matchable):")
    for r in sorted(likely, key=lambda x: -x.get('best_sim', 0))[:20]:
        print("  sim=%.3f gap=%.3f  %s -> %s" % (
            r.get('best_sim', 0), r.get('gap', 0), r['name'], r.get('best_fw', '?')))

# Write JSON report
report_path = '/Users/mojashi/repos/odd/g2flash/ghidra/lvgl_classification.json'
with open(report_path, 'w') as f:
    # Can't use json_mod.dump with unicode in Jython easily, write manually
    f.write('[\n')
    for i, r in enumerate(results):
        parts = []
        for k, v in sorted(r.items()):
            if isinstance(v, str):
                parts.append('"%s":"%s"' % (k, v.replace('"', '\\"').replace('\n', ' ')))
            elif isinstance(v, float):
                parts.append('"%s":%.3f' % (k, v))
            elif isinstance(v, int):
                parts.append('"%s":%d' % (k, v))
            elif isinstance(v, list):
                parts.append('"%s":%s' % (k, str(v).replace("'", '"')))
        f.write('{%s}%s\n' % (','.join(parts), ',' if i < len(results)-1 else ''))
    f.write(']\n')

print("classify: Report written to %s" % report_path)

ref_prog.release(java.lang.Object())
