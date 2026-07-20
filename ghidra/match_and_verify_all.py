# -*- coding: utf-8 -*-
# Ghidra headless script: aggressive BSim matching + multi-constraint verification.
#
# Phase 1: Create candidate mapping for ALL ref functions (best BSim match, no threshold)
# Phase 2: Extract necessary conditions (call edges, constants, strings, struct offsets)
# Phase 3: Verify each mapping against all constraints
# Phase 4: Accept verified matches, classify rest as INLINED/ABSENT
#
# @category G2

import ghidra.features.bsim.query.FunctionDatabase as FunctionDatabase
import ghidra.features.bsim.query.GenSignatures as GenSignatures
import generic.lsh.vector.VectorCompare as VectorCompare
from ghidra.program.model.symbol import SourceType
from ghidra.program.model.listing import CodeUnit
from collections import defaultdict

program = currentProgram
fm = program.getFunctionManager()
listing = program.getListing()

# ---- Setup ----
print("verify_all: Opening reference...")
project = state.getProject()
ref_file = None
for f in project.getProjectData().getRootFolder().getFiles():
    if f.getName() == "lvgl_ref.o":
        ref_file = f
        break
ref_prog = ref_file.getDomainObject(java.lang.Object(), True, True, monitor)
ref_fm = ref_prog.getFunctionManager()

ref_syms = {}
with open('/Users/mojashi/repos/odd/lv_port_ambiq/build_ref/lvgl_symbols.txt', 'r') as fi:
    for line in fi:
        parts = line.strip().split('|')
        if len(parts) == 3:
            ref_syms[parts[0]] = int(parts[1], 16)

# ---- Phase 1: BSim candidate mapping ----
print("verify_all: Phase 1 - BSim candidate mapping for all %d ref functions..." % len(ref_syms))

vectorFactory = FunctionDatabase.generateLSHVectorFactory()
config = FunctionDatabase.loadConfigurationTemplate("medium_32")
vectorFactory.set(config.weightfactory, config.idflookup, config.info.settings)

# Ref signatures
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
    sr = d.getSignatureRecord()
    if sr:
        v = sr.getLSHVector()
        if v:
            ref_vecs[d.getFunctionName()] = v

# FW signatures
gensig_fw = GenSignatures(True)
gensig_fw.setVectorFactory(vectorFactory)
gensig_fw.openProgram(program, None, None, None, repo, GenSignatures.getPathFromDomainFile(program))
gensig_fw.scanFunctions(fm.getFunctions(True), fm.getFunctionCount(), monitor)
fw_mgr = gensig_fw.getDescriptionManager()
fw_vecs = {}
di2 = fw_mgr.listAllFunctions()
while di2.hasNext():
    d = di2.next()
    sr = d.getSignatureRecord()
    if sr:
        v = sr.getLSHVector()
        if v:
            fw_vecs[d.getFunctionName()] = v

# Already-matched: these are fixed anchors
anchors = {}  # ref_name -> fw_name
for func in fm.getFunctions(True):
    n = func.getName()
    if not n.startswith('FUN_') and n in ref_syms:
        anchors[n] = n

print("verify_all:   %d already-matched anchors" % len(anchors))

# For unmatched: find best BSim candidate (NO threshold)
candidates = {}  # ref_name -> (fw_name, sim, gap)
processed = 0
for ref_name in ref_syms:
    if ref_name in anchors:
        continue
    processed += 1
    if processed % 100 == 0:
        print("verify_all:   BSim %d/%d..." % (processed, len(ref_syms) - len(anchors)))

    if ref_name not in ref_vecs:
        continue

    ref_vec = ref_vecs[ref_name]
    best_sim = 0
    best_fw = None
    second_sim = 0
    vc = VectorCompare()

    for fw_name, fw_vec in fw_vecs.items():
        if not fw_name.startswith('FUN_'):
            continue
        sim = ref_vec.compare(fw_vec, vc)
        if sim > best_sim:
            second_sim = best_sim
            best_sim = sim
            best_fw = fw_name
        elif sim > second_sim:
            second_sim = sim

    if best_fw and best_sim > 0.1:
        candidates[ref_name] = (best_fw, best_sim, best_sim - second_sim)

print("verify_all:   %d candidates found" % len(candidates))

# ---- Phase 2: Extract features for verification ----
print("verify_all: Phase 2 - Extracting features...")

def extract_features(prog, func):
    """Extract necessary-condition features from a function."""
    callees = []
    strings = set()
    constants = set()
    data_offsets = set()

    body = func.getBody()
    for cu in prog.getListing().getCodeUnits(body, True):
        if not hasattr(cu, 'getMnemonicString'):
            continue
        mn = cu.getMnemonicString()
        if not mn:
            continue

        # Callees
        if mn.lower() in ('bl', 'blx'):
            for ref in cu.getReferencesFrom():
                if ref.getReferenceType().isCall():
                    t = prog.getFunctionManager().getFunctionAt(ref.getToAddress())
                    if t:
                        callees.append(t.getName())

        # Data references -> strings
        for ref in cu.getReferencesFrom():
            if ref.getReferenceType().isData():
                d = prog.getListing().getDefinedDataAt(ref.getToAddress())
                if d and d.hasStringValue():
                    s = d.getValue()
                    if s and len(s) > 3:
                        strings.add(s)

        # Immediate constants (filter common)
        if hasattr(cu, 'getNumOperands'):
            for i in range(cu.getNumOperands()):
                for op in cu.getOpObjects(i):
                    if hasattr(op, 'getUnsignedValue'):
                        val = op.getUnsignedValue()
                        if 32 < val < 0x10000 and val not in (64, 128, 256, 512, 1024, 2048, 4096,
                            0xff, 0xffff, 0x100, 0x200, 0x400, 0x800, 0x1000):
                            constants.add(val)

    return {
        'callees': callees,
        'callee_set': set(callees),
        'strings': strings,
        'constants': constants,
        'size': func.getBody().getNumAddresses(),
    }

# Extract features for ref functions
ref_features = {}
ref_func_map = {}
for func in ref_fm.getFunctions(True):
    ref_func_map[func.getName()] = func

for ref_name in ref_syms:
    if ref_name in ref_func_map:
        ref_features[ref_name] = extract_features(ref_prog, ref_func_map[ref_name])

print("verify_all:   Extracted features for %d ref functions" % len(ref_features))

# Extract features for FW candidates (only the ones we need)
fw_candidates_set = set(v[0] for v in candidates.values())
fw_func_map = {}
for func in fm.getFunctions(True):
    if func.getName() in fw_candidates_set or func.getName() in anchors.values():
        fw_func_map[func.getName()] = func

fw_features = {}
count = 0
for fw_name, func in fw_func_map.items():
    fw_features[fw_name] = extract_features(program, func)
    count += 1
    if count % 200 == 0:
        print("verify_all:   FW features %d/%d..." % (count, len(fw_func_map)))

# Also extract for already-named functions
for func in fm.getFunctions(True):
    n = func.getName()
    if not n.startswith('FUN_') and n not in fw_features:
        fw_features[n] = extract_features(program, func)

print("verify_all:   Extracted features for %d FW functions" % len(fw_features))

# ---- Phase 3: Verify each mapping ----
print("verify_all: Phase 3 - Verifying mappings...")

# Build full mapping: ref_name -> fw_name
full_map = dict(anchors)  # start with anchors
for ref_name, (fw_name, sim, gap) in candidates.items():
    full_map[ref_name] = fw_name

# Reverse map
fw_to_ref = defaultdict(list)
for rn, fn in full_map.items():
    fw_to_ref[fn].append(rn)

# Check constraints for each mapping
results = {}  # ref_name -> {disposition, violations, evidence}

for ref_name in sorted(ref_syms.keys()):
    gcc_size = ref_syms[ref_name]
    r = {'name': ref_name, 'gcc_size': gcc_size, 'violations': [], 'evidence': []}

    if ref_name in anchors:
        r['disposition'] = 'MATCHED'
        r['fw_name'] = ref_name
        r['bsim_sim'] = 1.0
    elif ref_name in candidates:
        fw_name, sim, gap = candidates[ref_name]
        r['fw_name'] = fw_name
        r['bsim_sim'] = sim
        r['bsim_gap'] = gap
    else:
        # No BSim vector at all
        if gcc_size <= 12:
            r['disposition'] = 'TRIVIAL_INLINED'
            r['evidence'].append('Size %dB, no BSim signature - trivial function likely inlined' % gcc_size)
        else:
            r['disposition'] = 'NO_SIGNATURE'
            r['evidence'].append('No BSim signature generated')
        results[ref_name] = r
        continue

    fw_name = r['fw_name']

    # Skip verification for anchors (already verified)
    if ref_name in anchors:
        results[ref_name] = r
        continue

    ref_feat = ref_features.get(ref_name)
    fw_feat = fw_features.get(fw_name)
    if not ref_feat or not fw_feat:
        r['disposition'] = 'UNVERIFIABLE'
        r['evidence'].append('Missing features')
        results[ref_name] = r
        continue

    # --- Constraint checks ---

    # C1: String references must be preserved
    shared_strings = ref_feat['strings'] & fw_feat['strings']
    ref_only_strings = ref_feat['strings'] - fw_feat['strings']
    if ref_feat['strings']:
        if shared_strings:
            r['evidence'].append('C1_STRING: PASS (%d/%d shared: %s)' % (
                len(shared_strings), len(ref_feat['strings']), list(shared_strings)[:2]))
        elif len(ref_feat['strings']) > 0:
            r['violations'].append('C1_STRING: ref has strings %s not in FW func' % list(ref_feat['strings'])[:2])

    # C2: Constants must be preserved
    shared_consts = ref_feat['constants'] & fw_feat['constants']
    if len(ref_feat['constants']) >= 2:
        overlap = len(shared_consts) / float(len(ref_feat['constants']))
        if overlap >= 0.3:
            r['evidence'].append('C2_CONST: PASS (%d/%d shared, %.0f%%)' % (
                len(shared_consts), len(ref_feat['constants']), overlap * 100))
        else:
            r['violations'].append('C2_CONST: only %d/%d constants shared (%.0f%%)' % (
                len(shared_consts), len(ref_feat['constants']), overlap * 100))

    # C3: Call graph edges (callee names that are in the mapping)
    ref_mapped_callees = set()
    for callee in ref_feat['callee_set']:
        if callee in full_map:
            ref_mapped_callees.add(full_map[callee])
        elif callee in anchors:
            ref_mapped_callees.add(anchors[callee])

    fw_callee_set = fw_feat['callee_set']

    # Named callees that should appear
    expected_in_fw = set()
    for callee in ref_feat['callee_set']:
        if callee in anchors:  # only check anchored callees (high confidence)
            expected_in_fw.add(callee)

    found_anchored = expected_in_fw & fw_callee_set
    missing_anchored = expected_in_fw - fw_callee_set

    if expected_in_fw:
        if len(found_anchored) >= len(expected_in_fw) * 0.5:
            r['evidence'].append('C3_CALLGRAPH: PASS (%d/%d anchored callees found)' % (
                len(found_anchored), len(expected_in_fw)))
        elif missing_anchored:
            # Check if missing callees are small enough to be inlined
            small_missing = set()
            for mc in missing_anchored:
                mc_size = ref_syms.get(mc, 999)
                if mc_size <= 80:
                    small_missing.add(mc)
            real_missing = missing_anchored - small_missing
            if real_missing:
                r['violations'].append('C3_CALLGRAPH: missing anchored callees %s' % list(real_missing)[:3])
            else:
                r['evidence'].append('C3_CALLGRAPH: PASS (missing callees %s are small enough to inline)' % list(small_missing)[:3])

    # C4: Reverse edges (who calls this function)
    # Check: if ref function X is called by anchored function Y,
    # then FW candidate should be called by anchored Y too
    ref_callers_anchored = set()
    for rn, rf in ref_features.items():
        if rn in anchors and ref_name in rf['callee_set']:
            ref_callers_anchored.add(rn)

    if ref_callers_anchored:
        fw_callers = set()
        for fn, ff in fw_features.items():
            if fw_name in ff['callee_set']:
                fw_callers.add(fn)
        found_callers = ref_callers_anchored & fw_callers
        if found_callers:
            r['evidence'].append('C4_CALLERS: PASS (%d/%d anchored callers found)' % (
                len(found_callers), len(ref_callers_anchored)))
        else:
            if len(ref_callers_anchored) <= 2:
                r['violations'].append('C4_CALLERS: anchored callers %s dont call FW candidate' % list(ref_callers_anchored))

    # C5: Size ratio
    size_ratio = float(max(gcc_size, fw_feat['size'])) / max(min(gcc_size, fw_feat['size']), 1)
    if size_ratio <= 3.0:
        r['evidence'].append('C5_SIZE: PASS (ratio=%.1f, ref=%d fw=%d)' % (size_ratio, gcc_size, fw_feat['size']))
    elif size_ratio <= 5.0:
        pass  # neutral
    else:
        r['violations'].append('C5_SIZE: ratio=%.1f (ref=%d fw=%d)' % (size_ratio, gcc_size, fw_feat['size']))

    # C6: Collision check - is this FW func claimed by multiple ref funcs?
    collision_refs = fw_to_ref.get(fw_name, [])
    if len(collision_refs) > 1:
        r['violations'].append('C6_COLLISION: FW func %s also matched by %s' % (fw_name, [x for x in collision_refs if x != ref_name]))

    # --- Determine disposition ---
    n_violations = len(r['violations'])
    n_evidence = len(r['evidence'])

    if n_violations == 0 and n_evidence >= 2 and r.get('bsim_sim', 0) >= 0.3:
        r['disposition'] = 'VERIFIED'
    elif n_violations == 0 and n_evidence >= 1:
        r['disposition'] = 'PLAUSIBLE'
    elif n_violations == 0 and r.get('bsim_sim', 0) >= 0.5:
        r['disposition'] = 'PLAUSIBLE'
    elif n_violations <= 1 and n_evidence >= 2:
        r['disposition'] = 'PLAUSIBLE_WITH_CAVEAT'
    elif n_violations > 0:
        r['disposition'] = 'REJECTED'
    else:
        if gcc_size <= 40:
            r['disposition'] = 'LIKELY_INLINED'
        else:
            r['disposition'] = 'UNCERTAIN'

    results[ref_name] = r

# ---- Phase 4: Summary ----
print("")
print("verify_all: === RESULTS ===")
from collections import Counter
disp_counts = Counter(r['disposition'] for r in results.values())
for d in ['MATCHED', 'VERIFIED', 'PLAUSIBLE', 'PLAUSIBLE_WITH_CAVEAT', 'REJECTED',
          'LIKELY_INLINED', 'TRIVIAL_INLINED', 'UNCERTAIN', 'NO_SIGNATURE', 'UNVERIFIABLE']:
    if disp_counts.get(d, 0) > 0:
        print("  %-25s %d" % (d, disp_counts[d]))
print("  TOTAL:                  %d" % len(results))

resolved = disp_counts.get('MATCHED', 0) + disp_counts.get('VERIFIED', 0) + \
           disp_counts.get('PLAUSIBLE', 0) + disp_counts.get('LIKELY_INLINED', 0) + \
           disp_counts.get('TRIVIAL_INLINED', 0)
print("")
print("verify_all: Resolved: %d/%d (%.1f%%)" % (resolved, len(results), 100.0 * resolved / len(results)))

# Show some VERIFIED matches
verified = [r for r in results.values() if r['disposition'] == 'VERIFIED']
print("")
print("verify_all: Sample VERIFIED matches:")
for r in sorted(verified, key=lambda x: -x.get('bsim_sim', 0))[:15]:
    print("  sim=%.3f %s -> %s  evidence=%d violations=%d" % (
        r.get('bsim_sim', 0), r['name'], r.get('fw_name', '?'),
        len(r.get('evidence', [])), len(r.get('violations', []))))

# Show REJECTED
rejected = [r for r in results.values() if r['disposition'] == 'REJECTED']
print("")
print("verify_all: REJECTED (violations found): %d" % len(rejected))
for r in sorted(rejected, key=lambda x: -x.get('bsim_sim', 0))[:10]:
    print("  sim=%.3f %s -> %s  violations=%s" % (
        r.get('bsim_sim', 0), r['name'], r.get('fw_name', '?'), r['violations'][:2]))

# Write detailed JSON report
report_path = '/Users/mojashi/repos/odd/g2flash/ghidra/lvgl_verify_report.json'
with open(report_path, 'w') as fo:
    fo.write('[\n')
    items = sorted(results.values(), key=lambda x: x.get('disposition', 'Z'))
    for i, r in enumerate(items):
        parts = []
        for k in ['name', 'disposition', 'fw_name', 'bsim_sim', 'bsim_gap', 'gcc_size']:
            v = r.get(k)
            if v is None:
                continue
            if isinstance(v, str):
                parts.append('"%s":"%s"' % (k, v.replace('"', "'")))
            elif isinstance(v, float):
                parts.append('"%s":%.3f' % (k, v))
            elif isinstance(v, int):
                parts.append('"%s":%d' % (k, v))
        # violations and evidence as arrays
        if r.get('violations'):
            viol_str = ','.join(['"%s"' % v.replace('"', "'")[:100] for v in r['violations']])
            parts.append('"violations":[%s]' % viol_str)
        if r.get('evidence'):
            ev_str = ','.join(['"%s"' % v.replace('"', "'")[:120] for v in r['evidence']])
            parts.append('"evidence":[%s]' % ev_str)
        fo.write('{%s}%s\n' % (','.join(parts), ',' if i < len(items) - 1 else ''))
    fo.write(']\n')
print("verify_all: Report -> %s" % report_path)

ref_prog.release(java.lang.Object())
