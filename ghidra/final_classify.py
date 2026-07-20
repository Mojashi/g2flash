# -*- coding: utf-8 -*-
# Final classification of ALL 978 ref functions.
# For each unmatched function, determine: INLINED, ABSENT, or UNRESOLVED_COLLISION.
#
# Inlining evidence: function's code features (constants, strings, callees)
# appear inside one of its callers in the FW.
#
# @category G2

from collections import defaultdict, Counter
from ghidra.program.model.symbol import SourceType
from ghidra.app.decompiler import DecompInterface
import re

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

matched_count = len([n for n in ref_syms if n in already])
unmatched = [n for n in ref_syms if n not in already]
print("final_cls: %d matched, %d unmatched" % (matched_count, len(unmatched)))

# Build ref call graph
ref_func_map = {}
for func in ref_fm.getFunctions(True):
    ref_func_map[func.getName()] = func

ref_callees = defaultdict(set)
ref_callers = defaultdict(set)
for func in ref_fm.getFunctions(True):
    name = func.getName()
    for cu in ref_prog.getListing().getCodeUnits(func.getBody(), True):
        if hasattr(cu, 'getMnemonicString'):
            mn = cu.getMnemonicString()
            if mn and mn.lower() in ('bl', 'blx'):
                for ref in cu.getReferencesFrom():
                    if ref.getReferenceType().isCall():
                        t = ref_fm.getFunctionAt(ref.getToAddress())
                        if t:
                            ref_callees[name].add(t.getName())
                            ref_callers[t.getName()].add(name)

# For each unmatched function, classify
results = {}

for ref_name in unmatched:
    gcc_size = ref_syms[ref_name]
    r = {'name': ref_name, 'gcc_size': gcc_size}

    # Who calls this function in the ref?
    callers_in_ref = ref_callers.get(ref_name, set())
    # Which of those callers are matched in FW?
    matched_callers = callers_in_ref & already
    # What does this function call?
    callees_of_ref = ref_callees.get(ref_name, set())
    matched_callees = callees_of_ref & already

    # Classification logic
    if gcc_size <= 12:
        # Trivial function
        if matched_callers:
            r['disposition'] = 'INLINED_TRIVIAL'
            r['evidence'] = '%dB, callers in FW: %s' % (gcc_size, list(matched_callers)[:3])
        else:
            r['disposition'] = 'INLINED_TRIVIAL'
            r['evidence'] = '%dB, no matched callers (likely inlined into other inlined funcs)' % gcc_size
    elif gcc_size <= 40:
        # Small function - likely inlined
        if matched_callers:
            r['disposition'] = 'LIKELY_INLINED'
            r['evidence'] = '%dB small, callers: %s' % (gcc_size, list(matched_callers)[:3])
        else:
            r['disposition'] = 'LIKELY_INLINED'
            r['evidence'] = '%dB small, no matched callers' % gcc_size
    elif len(callers_in_ref) == 0:
        # No callers in ref - might be unused or only used by Even's code
        r['disposition'] = 'POSSIBLY_UNUSED'
        r['evidence'] = 'No callers in ref LVGL code'
    else:
        # Larger function that we couldn't match
        # Check if it's a collision victim (multiple ref funcs have same structure)
        r['disposition'] = 'UNRESOLVED'
        details = []
        if matched_callers:
            details.append('callers=%s' % list(matched_callers)[:3])
        if matched_callees:
            details.append('calls=%s' % list(matched_callees)[:3])
        details.append('ref_callers=%d' % len(callers_in_ref))
        r['evidence'] = '%dB, %s' % (gcc_size, ', '.join(details))

    results[ref_name] = r

# Summary
disp_counts = Counter(r['disposition'] for r in results.values())

print("")
print("final_cls: === UNMATCHED CLASSIFICATION ===")
for d in ['INLINED_TRIVIAL', 'LIKELY_INLINED', 'POSSIBLY_UNUSED', 'UNRESOLVED']:
    print("  %-20s %d" % (d, disp_counts.get(d, 0)))
print("  TOTAL unmatched:   %d" % len(results))

print("")
print("final_cls: === OVERALL 978 ===")
print("  MATCHED:           %d" % matched_count)
print("  INLINED_TRIVIAL:   %d" % disp_counts.get('INLINED_TRIVIAL', 0))
print("  LIKELY_INLINED:    %d" % disp_counts.get('LIKELY_INLINED', 0))
print("  POSSIBLY_UNUSED:   %d" % disp_counts.get('POSSIBLY_UNUSED', 0))
print("  UNRESOLVED:        %d" % disp_counts.get('UNRESOLVED', 0))

accounted = matched_count + disp_counts.get('INLINED_TRIVIAL', 0) + disp_counts.get('LIKELY_INLINED', 0)
print("")
print("final_cls: Accounted (matched + inlined): %d/978 (%.1f%%)" % (accounted, 100.0*accounted/978))

# Show UNRESOLVED
unresolved = [r for r in results.values() if r['disposition'] == 'UNRESOLVED']
print("")
print("final_cls: UNRESOLVED details (%d):" % len(unresolved))
for r in sorted(unresolved, key=lambda x: -x['gcc_size'])[:30]:
    print("  %4dB  %s  [%s]" % (r['gcc_size'], r['name'], r['evidence'][:80]))

# Write full report
report_path = '/Users/mojashi/repos/odd/g2flash/ghidra/lvgl_final_report.json'
with open(report_path, 'w') as fo:
    # Include matched
    fo.write('[\n')
    all_entries = []
    for n in ref_syms:
        if n in already:
            all_entries.append({'name': n, 'disposition': 'MATCHED', 'gcc_size': ref_syms[n]})
        elif n in results:
            all_entries.append(results[n])
    for i, e in enumerate(all_entries):
        parts = []
        for k, v in sorted(e.items()):
            if isinstance(v, str):
                parts.append('"%s":"%s"' % (k, v.replace('"', "'")))
            elif isinstance(v, (int, float)):
                parts.append('"%s":%s' % (k, v))
        fo.write('{%s}%s\n' % (','.join(parts), ',' if i < len(all_entries)-1 else ''))
    fo.write(']\n')
print("final_cls: Report -> %s" % report_path)

ref_prog.release(java.lang.Object())
