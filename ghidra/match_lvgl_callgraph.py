# -*- coding: utf-8 -*-
# Ghidra headless script: call-graph based matching of FW functions against LVGL reference.
#
# Uses the already-named lv_* functions as anchors. For each unnamed FUN_,
# looks at which named lv_* functions it calls, and matches against reference
# functions that call the same set.
#
# This is compiler-agnostic: the call TARGETS are the same regardless of
# whether IAR or GCC compiled the code.
#
# @category G2
# @author Claude

from collections import defaultdict
from ghidra.program.model.symbol import SourceType
from ghidra.program.model.listing import CodeUnit

program = currentProgram
listing = program.getListing()
fm = program.getFunctionManager()
refmgr = program.getReferenceManager()

# ---- Step 1: Open reference program ----
print("match_cg: Step 1 - Opening reference program...")

project = state.getProject()
pd = project.getProjectData()
root = pd.getRootFolder()

ref_file = None
for f in root.getFiles():
    if f.getName() == "lvgl_ref.o":
        ref_file = f
        break

if not ref_file:
    print("match_cg: ERROR - lvgl_ref.o not found")
    import sys
    sys.exit(1)

ref_prog = ref_file.getDomainObject(java.lang.Object(), True, True, monitor)
ref_fm = ref_prog.getFunctionManager()
ref_listing = ref_prog.getListing()

print("match_cg:   Reference has %d functions" % ref_fm.getFunctionCount())

# ---- Step 2: Build call signatures for reference functions ----
print("match_cg: Step 2 - Building reference call signatures...")

def get_called_functions(prog, func):
    """Get set of function names called by this function."""
    called = []
    body = func.getBody()
    code_units = prog.getListing().getCodeUnits(body, True)
    for cu in code_units:
        if hasattr(cu, 'getMnemonicString'):
            mn = cu.getMnemonicString()
            if mn and mn.lower() in ('bl', 'blx'):
                refs = cu.getReferencesFrom()
                for ref in refs:
                    if ref.getReferenceType().isCall():
                        target = prog.getFunctionManager().getFunctionAt(ref.getToAddress())
                        if target:
                            called.append(target.getName())
    return called

def get_called_names_set(prog, func):
    """Get deduplicated set of called function names."""
    return set(get_called_functions(prog, func))

def get_called_names_ordered(prog, func):
    """Get ordered list of called function names (preserves call order)."""
    return get_called_functions(prog, func)

# Build ref call signatures
ref_sigs = {}  # ref_name -> {called_set, called_ordered, size}
ref_count = 0

for func in ref_fm.getFunctions(True):
    name = func.getName()
    if name.startswith('_') and not name.startswith('_lv_'):
        continue

    called_set = get_called_names_set(ref_prog, func)
    called_ordered = get_called_names_ordered(ref_prog, func)

    # Only consider functions that call at least 1 other named function
    if len(called_set) < 1:
        continue

    ref_sigs[name] = {
        'called_set': called_set,
        'called_ordered': called_ordered,
        'size': func.getBody().getNumAddresses(),
    }
    ref_count += 1

print("match_cg:   %d reference functions with call signatures" % ref_count)

# ---- Step 3: Build FW call signatures ----
print("match_cg: Step 3 - Building FW call signatures...")

# Collect already-named functions for anchoring
already_named = set()
for func in fm.getFunctions(True):
    n = func.getName()
    if not n.startswith('FUN_'):
        already_named.add(n)

print("match_cg:   %d named functions as anchors" % len(already_named))

# Build FW call signatures for unnamed functions
fw_sigs = {}  # fw_func_name -> {called_set, called_ordered, size, func}
fw_count = 0

for func in fm.getFunctions(True):
    name = func.getName()
    if not name.startswith('FUN_'):
        continue

    called_set = get_called_names_set(program, func)
    called_ordered = get_called_names_ordered(program, func)

    # Filter to only named callees (anchors)
    named_called_set = called_set & already_named
    named_called_ordered = [c for c in called_ordered if c in already_named]

    if len(named_called_set) < 1:
        continue

    fw_sigs[name] = {
        'called_set': named_called_set,
        'called_ordered': named_called_ordered,
        'size': func.getBody().getNumAddresses(),
        'func': func,
    }
    fw_count += 1

print("match_cg:   %d FW functions with named callees" % fw_count)

# ---- Step 4: Match by call signature ----
print("match_cg: Step 4 - Matching by call graph...")

def call_similarity(fw_sig, ref_sig):
    """Compute call-graph similarity score."""
    fw_set = fw_sig['called_set']
    ref_set = ref_sig['called_set']

    # Jaccard similarity on called function sets
    if len(fw_set) == 0 and len(ref_set) == 0:
        return 0.0
    intersection = fw_set & ref_set
    union = fw_set | ref_set
    jaccard = float(len(intersection)) / len(union) if len(union) > 0 else 0.0

    if jaccard < 0.3:
        return 0.0

    # Ordered call sequence similarity (longest common subsequence ratio)
    fw_ord = fw_sig['called_ordered']
    ref_ord = ref_sig['called_ordered']

    # Filter ref_ord to only include names that exist in FW anchors
    ref_ord_filtered = [c for c in ref_ord if c in already_named]

    if len(fw_ord) > 0 and len(ref_ord_filtered) > 0:
        # LCS length
        m, n = len(fw_ord), len(ref_ord_filtered)
        if m > 100 or n > 100:
            # Too large, skip LCS
            lcs_ratio = jaccard
        else:
            dp = [[0] * (n + 1) for _ in range(m + 1)]
            for i in range(1, m + 1):
                for j in range(1, n + 1):
                    if fw_ord[i-1] == ref_ord_filtered[j-1]:
                        dp[i][j] = dp[i-1][j-1] + 1
                    else:
                        dp[i][j] = max(dp[i-1][j], dp[i][j-1])
            lcs_len = dp[m][n]
            lcs_ratio = float(lcs_len) / max(m, n)
    else:
        lcs_ratio = 0.0

    # Size ratio
    size_ratio = min(fw_sig['size'], ref_sig['size']) / float(max(fw_sig['size'], ref_sig['size'])) \
                 if max(fw_sig['size'], ref_sig['size']) > 0 else 0.0

    # Combined score
    score = jaccard * 0.40 + lcs_ratio * 0.40 + size_ratio * 0.20

    return score

# Pre-index ref by called function names for fast lookup
ref_by_callee = defaultdict(list)
for ref_name, ref_sig in ref_sigs.items():
    for callee in ref_sig['called_set']:
        ref_by_callee[callee].append(ref_name)

matches = []
processed = 0

for fw_name, fw_sig in fw_sigs.items():
    processed += 1
    if processed % 200 == 0:
        print("match_cg:   ... processed %d/%d, %d matches" % (processed, len(fw_sigs), len(matches)))

    # Find candidate refs that share at least one callee
    candidate_refs = set()
    for callee in fw_sig['called_set']:
        for ref_name in ref_by_callee.get(callee, []):
            if ref_name not in already_named:
                candidate_refs.add(ref_name)

    if not candidate_refs:
        continue

    best_score = 0
    best_ref = None
    second_score = 0

    for ref_name in candidate_refs:
        ref_sig = ref_sigs[ref_name]
        score = call_similarity(fw_sig, ref_sig)

        if score > best_score:
            second_score = best_score
            best_score = score
            best_ref = ref_name
        elif score > second_score:
            second_score = score

    if best_ref and best_score >= 0.50:
        gap = best_score - second_score
        confidence = 'HIGH' if best_score >= 0.70 and gap >= 0.10 else \
                     'HIGH' if best_score >= 0.85 else 'MEDIUM'
        matches.append((fw_name, best_ref, best_score, confidence, gap,
                        fw_sig['called_set'], ref_sigs[best_ref]['called_set']))

print("match_cg:   Raw matches: %d" % len(matches))

# ---- Step 5: Deduplicate ----
matches.sort(key=lambda x: -x[2])
used_ref = set()
used_fw = set()
final = []

for fw_name, ref_name, score, confidence, gap, fw_calls, ref_calls in matches:
    if ref_name in used_ref or ref_name in already_named:
        continue
    if fw_name in used_fw:
        continue
    used_ref.add(ref_name)
    used_fw.add(fw_name)
    final.append((fw_name, ref_name, score, confidence, gap, fw_calls, ref_calls))

print("match_cg:   After dedup: %d" % len(final))

# ---- Step 6: Apply ----
print("match_cg: Step 6 - Applying matches...")

high_count = 0
medium_count = 0

for fw_name, ref_name, score, confidence, gap, fw_calls, ref_calls in final:
    func = fw_sigs[fw_name]['func']
    shared = fw_calls & ref_calls
    shared_str = ','.join(sorted(shared)[:5])
    if len(shared) > 5:
        shared_str += '...(+%d)' % (len(shared) - 5)

    if confidence == 'HIGH':
        func.setName(ref_name, SourceType.ANALYSIS)
        func.setComment("LVGL callgraph match: score=%.3f gap=%.3f shared=[%s]" % (score, gap, shared_str))
        high_count += 1
        print("match_cg:   HIGH  %.3f gap=%.3f %s -> %s  shared=[%s]" %
              (score, gap, fw_name, ref_name, shared_str))
    else:
        cu = listing.getCodeUnitAt(func.getEntryPoint())
        if cu:
            existing = cu.getComment(CodeUnit.PLATE_COMMENT)
            new_comment = "LVGL callgraph candidate: %s score=%.3f gap=%.3f shared=[%s]" % \
                          (ref_name, score, gap, shared_str)
            if existing:
                cu.setComment(CodeUnit.PLATE_COMMENT, existing + "\n" + new_comment)
            else:
                cu.setComment(CodeUnit.PLATE_COMMENT, new_comment)
        medium_count += 1

print("match_cg: === DONE: %d HIGH (renamed), %d MEDIUM (commented) ===" % (high_count, medium_count))

ref_prog.release(java.lang.Object())
