# -*- coding: utf-8 -*-
# Ghidra headless script: iterative call-graph matching with bidirectional edges.
#
# Uses BOTH callee (who does this function call?) AND caller (who calls this function?)
# edges for matching. Iterates until convergence — each round's new matches become
# anchors for the next round.
#
# This is a practical approximation of subgraph isomorphism, seeded by known anchors.
#
# @category G2
# @author Claude

from collections import defaultdict
from ghidra.program.model.symbol import SourceType
from ghidra.program.model.listing import CodeUnit

program = currentProgram
listing = program.getListing()
fm = program.getFunctionManager()

# ---- Step 1: Open reference program ----
print("match_iter: Step 1 - Opening reference program...")

project = state.getProject()
ref_file = None
for f in project.getProjectData().getRootFolder().getFiles():
    if f.getName() == "lvgl_ref.o":
        ref_file = f
        break

if not ref_file:
    print("match_iter: ERROR - lvgl_ref.o not found")
    import sys
    sys.exit(1)

ref_prog = ref_file.getDomainObject(java.lang.Object(), True, True, monitor)
ref_fm = ref_prog.getFunctionManager()

print("match_iter:   Reference: %d functions" % ref_fm.getFunctionCount())

# ---- Step 2: Build full call graphs ----
print("match_iter: Step 2 - Building call graphs...")

def build_call_graph(prog):
    """Build bidirectional call graph: callees and callers for each function."""
    func_mgr = prog.getFunctionManager()
    callees = defaultdict(list)   # func_name -> [callee_names]
    callers = defaultdict(list)   # func_name -> [caller_names]
    func_sizes = {}               # func_name -> size

    for func in func_mgr.getFunctions(True):
        name = func.getName()
        func_sizes[name] = func.getBody().getNumAddresses()
        body = func.getBody()
        code_units = prog.getListing().getCodeUnits(body, True)
        for cu in code_units:
            if hasattr(cu, 'getMnemonicString'):
                mn = cu.getMnemonicString()
                if mn and mn.lower() in ('bl', 'blx'):
                    for ref in cu.getReferencesFrom():
                        if ref.getReferenceType().isCall():
                            target = func_mgr.getFunctionAt(ref.getToAddress())
                            if target:
                                callee_name = target.getName()
                                callees[name].append(callee_name)
                                callers[callee_name].append(name)

    return callees, callers, func_sizes

print("match_iter:   Building reference graph...")
ref_callees, ref_callers, ref_sizes = build_call_graph(ref_prog)
print("match_iter:   Reference: %d nodes with edges" % len(ref_callees))

print("match_iter:   Building FW graph...")
fw_callees, fw_callers, fw_sizes = build_call_graph(program)
print("match_iter:   FW: %d nodes with edges" % len(fw_callees))

# ---- Step 3: Collect initial anchors ----
print("match_iter: Step 3 - Collecting initial anchors...")

# anchor = mapping from ref_name -> fw_name (confirmed matches)
anchors = {}
fw_to_ref = {}

for func in fm.getFunctions(True):
    fw_name = func.getName()
    if fw_name.startswith('FUN_'):
        continue
    # Check if this name exists in the reference
    if fw_name in ref_sizes:
        anchors[fw_name] = fw_name  # ref_name -> fw_name (same name = already matched)
        fw_to_ref[fw_name] = fw_name

print("match_iter:   Initial anchors: %d" % len(anchors))

# ---- Step 4: Iterative matching ----
print("match_iter: Step 4 - Iterative matching...")

def compute_signature(name, callees_map, callers_map, anchors_set):
    """Compute a matching signature based on anchor neighbors."""
    # Callee anchors (functions this one calls that are anchored)
    callee_anchors = tuple(sorted(set(
        c for c in callees_map.get(name, []) if c in anchors_set
    )))
    # Caller anchors (functions that call this one that are anchored)
    caller_anchors = tuple(sorted(set(
        c for c in callers_map.get(name, []) if c in anchors_set
    )))
    return (callee_anchors, caller_anchors)

total_new = 0
round_num = 0

while True:
    round_num += 1
    anchor_ref_names = set(anchors.keys())
    anchor_fw_names = set(anchors.values())

    # Compute signatures for unmatched reference functions
    ref_sigs = {}
    for func in ref_fm.getFunctions(True):
        name = func.getName()
        if name in anchor_ref_names:
            continue
        sig = compute_signature(name, ref_callees, ref_callers, anchor_ref_names)
        if len(sig[0]) + len(sig[1]) == 0:
            continue  # No anchor neighbors, can't match
        ref_sigs[name] = sig

    # Compute signatures for unmatched FW functions
    fw_sigs = {}
    for func in fm.getFunctions(True):
        name = func.getName()
        if not name.startswith('FUN_'):
            continue
        sig = compute_signature(name, fw_callees, fw_callers, anchor_fw_names)
        if len(sig[0]) + len(sig[1]) == 0:
            continue
        fw_sigs[name] = sig

    # Index ref by signature
    ref_by_sig = defaultdict(list)
    for name, sig in ref_sigs.items():
        ref_by_sig[sig].append(name)

    # Find matches: FW function with same signature as exactly one ref function
    new_matches = []
    used_ref = set()
    used_fw = set()

    for fw_name, fw_sig in fw_sigs.items():
        if fw_name in used_fw:
            continue

        # Find ref functions with the same signature
        candidates = ref_by_sig.get(fw_sig, [])
        candidates = [c for c in candidates if c not in used_ref]

        if len(candidates) != 1:
            continue  # Ambiguous or no match

        ref_name = candidates[0]

        # Check that this ref signature is also unique among FW functions
        fw_with_same_sig = [f for f, s in fw_sigs.items() if s == fw_sig and f not in used_fw]
        if len(fw_with_same_sig) != 1:
            continue  # Multiple FW functions have same signature

        # Size sanity check (within 4x)
        ref_size = ref_sizes.get(ref_name, 0)
        fw_size = fw_sizes.get(fw_name, 0)
        if ref_size > 0 and fw_size > 0:
            ratio = float(max(ref_size, fw_size)) / min(ref_size, fw_size)
            if ratio > 4.0:
                continue

        new_matches.append((fw_name, ref_name, fw_sig))
        used_ref.add(ref_name)
        used_fw.add(fw_name)

    if not new_matches:
        print("match_iter:   Round %d: 0 new matches. Converged." % round_num)
        break

    # Add new matches as anchors
    for fw_name, ref_name, sig in new_matches:
        anchors[ref_name] = fw_name
        fw_to_ref[fw_name] = ref_name

    total_new += len(new_matches)
    n_callee = sum(1 for _,_,s in new_matches if len(s[0]) > 0 and len(s[1]) == 0)
    n_caller = sum(1 for _,_,s in new_matches if len(s[0]) == 0 and len(s[1]) > 0)
    n_both = sum(1 for _,_,s in new_matches if len(s[0]) > 0 and len(s[1]) > 0)
    print("match_iter:   Round %d: %d new matches (callee-only=%d, caller-only=%d, both=%d). Total anchors: %d" %
          (round_num, len(new_matches), n_callee, n_caller, n_both, len(anchors)))

    if round_num > 20:
        print("match_iter:   Safety limit reached.")
        break

# ---- Step 5: Apply new matches (exclude initial anchors) ----
print("match_iter: Step 5 - Applying %d new matches..." % total_new)

applied = 0

# Build fw_name -> function lookup
fw_func_by_name = {}
for f in fm.getFunctions(True):
    fw_func_by_name[f.getName()] = f

for ref_name, fw_name in anchors.items():
    if ref_name == fw_name:
        continue  # Was already named before this script

    func = fw_func_by_name.get(fw_name)
    if func and func.getName().startswith('FUN_'):
        old_name = func.getName()
        func.setName(ref_name, SourceType.ANALYSIS)
        sig = compute_signature(ref_name, ref_callees, ref_callers, set(anchors.keys()))
        func.setComment("LVGL iterative graph match: callees=[%s] callers=[%s]" %
                        (','.join(sig[0][:5]), ','.join(sig[1][:5])))
        applied += 1
        if applied <= 50:
            print("match_iter:   %s -> %s  (callees=%d callers=%d)" %
                  (old_name, ref_name, len(sig[0]), len(sig[1])))

print("match_iter: === DONE: %d rounds, %d new matches, %d applied ===" %
      (round_num, total_new, applied))

ref_prog.release(java.lang.Object())
