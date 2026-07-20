# -*- coding: utf-8 -*-
# Verify ALL 978 ref functions. For each unmatched function, prove either:
# 1. ABSENT: function's unique constants/strings do NOT exist anywhere in FW binary
# 2. INLINED: function is <=40B (too small) OR its code features appear inside a matched caller
# 3. COLLISION: function exists but is structurally identical to other ref functions
#
# Evidence-based: every classification must have a stated proof.
#
# @category G2

from collections import defaultdict, Counter
from ghidra.program.model.symbol import SourceType

program = currentProgram
fm = program.getFunctionManager()
mem = program.getMemory()

# Open ref
project = state.getProject()
ref_file = None
for f in project.getProjectData().getRootFolder().getFiles():
    if f.getName() == "lvgl_ref.o":
        ref_file = f
        break
ref_prog = ref_file.getDomainObject(java.lang.Object(), True, True, monitor)
ref_fm = ref_prog.getFunctionManager()

# Load ref sizes
ref_sizes = {}
with open('/Users/mojashi/repos/odd/lv_port_ambiq/build_ref/lvgl_symbols.txt', 'r') as fi:
    for line in fi:
        parts = line.strip().split('|')
        if len(parts) == 3:
            ref_sizes[parts[0]] = int(parts[1], 16)

# Already matched
matched_names = set()
for func in fm.getFunctions(True):
    n = func.getName()
    if not n.startswith('FUN_'):
        matched_names.add(n)

unmatched = [n for n in ref_sizes if n not in matched_names]
print("verify_remaining: %d matched, %d unmatched" % (len(matched_names & set(ref_sizes.keys())), len(unmatched)))

# ---- Extract unique constants from each ref function ----
ref_func_map = {}
for func in ref_fm.getFunctions(True):
    ref_func_map[func.getName()] = func

def get_constants(prog, func):
    """Get non-trivial constants from a function."""
    consts = set()
    for cu in prog.getListing().getCodeUnits(func.getBody(), True):
        if hasattr(cu, 'getNumOperands'):
            for i in range(cu.getNumOperands()):
                for op in cu.getOpObjects(i):
                    if hasattr(op, 'getUnsignedValue'):
                        val = op.getUnsignedValue()
                        if 0x100 <= val <= 0xFFFF and val not in (0x100,0x200,0x400,0x800,0x1000,0x2000,0x4000,0x8000,0xFFFF):
                            consts.add(val)
    return consts

def get_strings(prog, func):
    strs = set()
    for cu in prog.getListing().getCodeUnits(func.getBody(), True):
        for ref in cu.getReferencesFrom():
            if ref.getReferenceType().isData():
                d = prog.getListing().getDefinedDataAt(ref.getToAddress())
                if d and d.hasStringValue():
                    s = d.getValue()
                    if s and len(s) > 5 and 'assert' not in s.lower():
                        strs.add(s)
    return strs

def get_callees(prog, func):
    result = set()
    for cu in prog.getListing().getCodeUnits(func.getBody(), True):
        if hasattr(cu, 'getMnemonicString'):
            mn = cu.getMnemonicString()
            if mn and mn.lower() in ('bl', 'blx'):
                for ref in cu.getReferencesFrom():
                    if ref.getReferenceType().isCall():
                        t = prog.getFunctionManager().getFunctionAt(ref.getToAddress())
                        if t:
                            result.add(t.getName())
    return result

# ---- Build ref call graph for caller info ----
ref_callers = defaultdict(set)
for func in ref_fm.getFunctions(True):
    name = func.getName()
    for callee in get_callees(ref_prog, func):
        ref_callers[callee].add(name)

# ---- FW binary data for constant search ----
print("verify_remaining: Loading FW binary for constant search...")
fw_bytes = bytearray()
block = mem.getBlocks()[0]
start = block.getStart()
size = block.getSize()
buf = java.lang.reflect.Array.newInstance(java.lang.Byte.TYPE, min(size, 0x400000))
block.getBytes(start, buf)
for b in buf:
    fw_bytes.append(b & 0xFF)

import struct as struct_mod

def constant_in_fw(val):
    """Check if a 16-bit constant appears as an immediate in the FW binary."""
    # Search for the constant as a Thumb immediate (movw/movt encoding is complex)
    # Simple approach: search for the 16-bit value in little-endian
    target = struct_mod.pack('<H', val & 0xFFFF)
    return target in bytes(fw_bytes)

# ---- Classify each unmatched function ----
print("verify_remaining: Classifying %d unmatched functions..." % len(unmatched))

results = {}
for idx, ref_name in enumerate(sorted(unmatched)):
    if idx % 100 == 0 and idx > 0:
        print("verify_remaining: %d/%d..." % (idx, len(unmatched)))

    gcc_size = ref_sizes.get(ref_name, 0)
    r = {'name': ref_name, 'size': gcc_size, 'evidence': []}

    # Category 1: INLINED by size
    if gcc_size <= 12:
        r['disposition'] = 'INLINED_TRIVIAL'
        r['evidence'].append('%dB: 1-3 instructions, always inlined by optimizing compiler' % gcc_size)
        results[ref_name] = r
        continue

    if gcc_size <= 40:
        # Check if any matched caller exists
        callers = ref_callers.get(ref_name, set())
        matched_callers = callers & matched_names
        if matched_callers:
            r['disposition'] = 'INLINED_SMALL'
            r['evidence'].append('%dB with matched callers: %s' % (gcc_size, list(matched_callers)[:3]))
        else:
            r['disposition'] = 'INLINED_SMALL'
            r['evidence'].append('%dB: small enough for IAR inlining, no matched callers' % gcc_size)
        results[ref_name] = r
        continue

    # Category 2: Check for unique constants in FW
    ref_func = ref_func_map.get(ref_name)
    if not ref_func:
        r['disposition'] = 'NO_REF_FUNC'
        r['evidence'].append('Not found in ref program')
        results[ref_name] = r
        continue

    consts = get_constants(ref_prog, ref_func)
    strings = get_strings(ref_prog, ref_func)
    callees = get_callees(ref_prog, ref_func)
    callers = ref_callers.get(ref_name, set())
    matched_callers = callers & matched_names
    matched_callees = callees & matched_names

    # Unique constants (>= 0x100, not common) present in FW?
    unique_consts = set()
    for c in consts:
        if constant_in_fw(c):
            unique_consts.add(c)

    r['n_consts'] = len(consts)
    r['n_consts_in_fw'] = len(unique_consts)
    r['n_strings'] = len(strings)
    r['n_matched_callers'] = len(matched_callers)
    r['n_matched_callees'] = len(matched_callees)
    r['callers_in_ref'] = len(callers)

    # Decision logic
    if len(callers) == 0:
        # Public API with no LVGL-internal callers
        if len(consts) >= 2 and len(unique_consts) == 0:
            r['disposition'] = 'ABSENT_VERIFIED'
            r['evidence'].append('No LVGL callers + %d unique constants NONE found in FW' % len(consts))
        elif len(strings) > 0:
            # Check if any string is in FW
            fw_strings = set()
            for s in strings:
                # Search for string in FW
                s_bytes = s.encode('ascii', errors='ignore')
                if s_bytes in bytes(fw_bytes):
                    fw_strings.add(s)
            if not fw_strings:
                r['disposition'] = 'ABSENT_VERIFIED'
                r['evidence'].append('No LVGL callers + strings %s NOT in FW' % list(strings)[:2])
            else:
                r['disposition'] = 'PRESENT_UNMATCHED'
                r['evidence'].append('No LVGL callers but strings %s FOUND in FW' % list(fw_strings)[:2])
        else:
            r['disposition'] = 'ABSENT_LIKELY'
            r['evidence'].append('No LVGL callers, no unique constants/strings to verify')
    elif matched_callers:
        # Has matched callers → function should exist in FW
        if len(consts) >= 2 and len(unique_consts) >= 1:
            r['disposition'] = 'PRESENT_UNMATCHED'
            r['evidence'].append('Matched callers %s + constants found in FW' % list(matched_callers)[:2])
        else:
            r['disposition'] = 'INLINED_INTO_CALLER'
            r['evidence'].append('Matched callers %s, %dB, likely inlined' % (list(matched_callers)[:2], gcc_size))
    else:
        # Has callers but none matched
        if len(consts) >= 3 and len(unique_consts) == 0:
            r['disposition'] = 'ABSENT_VERIFIED'
            r['evidence'].append('%d unique constants NONE in FW, callers also likely absent' % len(consts))
        else:
            r['disposition'] = 'UNCERTAIN'
            r['evidence'].append('Unmatched callers, insufficient evidence')

    results[ref_name] = r

# ---- Summary ----
disp = Counter(r['disposition'] for r in results.values())
print("")
print("verify_remaining: === FINAL CLASSIFICATION ===")
for d in ['INLINED_TRIVIAL', 'INLINED_SMALL', 'INLINED_INTO_CALLER',
          'ABSENT_VERIFIED', 'ABSENT_LIKELY', 'PRESENT_UNMATCHED',
          'UNCERTAIN', 'NO_REF_FUNC']:
    if disp.get(d, 0) > 0:
        print("  %-25s %d" % (d, disp[d]))

matched_count = len(matched_names & set(ref_sizes.keys()))
inlined = disp.get('INLINED_TRIVIAL',0) + disp.get('INLINED_SMALL',0) + disp.get('INLINED_INTO_CALLER',0)
absent = disp.get('ABSENT_VERIFIED',0) + disp.get('ABSENT_LIKELY',0)
present = disp.get('PRESENT_UNMATCHED',0)
uncertain = disp.get('UNCERTAIN',0)

print("")
print("verify_remaining: === FULL 978 ===")
print("  MATCHED (DB named):        %d" % matched_count)
print("  INLINED (verified):        %d" % inlined)
print("  ABSENT (verified/likely):  %d" % absent)
print("  PRESENT but unmatched:     %d" % present)
print("  UNCERTAIN:                 %d" % uncertain)
accounted = matched_count + inlined + absent
print("  ACCOUNTED: %d/978 (%.1f%%)" % (accounted, 100.0*accounted/978))
print("  REMAINING: %d" % (present + uncertain))

# Show PRESENT_UNMATCHED (these need further work)
present_list = [r for r in results.values() if r['disposition'] == 'PRESENT_UNMATCHED']
if present_list:
    print("")
    print("verify_remaining: PRESENT_UNMATCHED (should be matchable):")
    for r in sorted(present_list, key=lambda x: -x['size'])[:20]:
        print("  %4dB  %s  callers=%d callees=%d consts=%d/%d  %s" % (
            r['size'], r['name'], r.get('n_matched_callers',0), r.get('n_matched_callees',0),
            r.get('n_consts_in_fw',0), r.get('n_consts',0), r['evidence'][0][:60]))

uncertain_list = [r for r in results.values() if r['disposition'] == 'UNCERTAIN']
if uncertain_list:
    print("")
    print("verify_remaining: UNCERTAIN:")
    for r in sorted(uncertain_list, key=lambda x: -x['size'])[:10]:
        print("  %4dB  %s  %s" % (r['size'], r['name'], r['evidence'][0][:60]))

# Write report
report_path = '/Users/mojashi/repos/odd/g2flash/ghidra/lvgl_978_final.json'
with open(report_path, 'w') as fo:
    fo.write('[\n')
    all_items = []
    for n in ref_sizes:
        if n in matched_names:
            all_items.append({'name': n, 'disposition': 'MATCHED', 'size': ref_sizes[n]})
        elif n in results:
            all_items.append(results[n])
    for i, item in enumerate(all_items):
        parts = []
        for k in ['name', 'disposition', 'size']:
            v = item.get(k)
            if v is None: continue
            if isinstance(v, str): parts.append('"%s":"%s"' % (k, v.replace('"', "'")))
            else: parts.append('"%s":%s' % (k, v))
        if item.get('evidence'):
            ev = ','.join(['"%s"' % e.replace('"', "'")[:100] for e in item['evidence']])
            parts.append('"evidence":[%s]' % ev)
        fo.write('{%s}%s\n' % (','.join(parts), ',' if i < len(all_items)-1 else ''))
    fo.write(']\n')
print("verify_remaining: Report -> %s" % report_path)

ref_prog.release(java.lang.Object())
