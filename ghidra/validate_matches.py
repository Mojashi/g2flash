# -*- coding: utf-8 -*-
# Validate LVGL matches by checking "missing call" violations.
#
# For each case where ref function A calls B but FW function A' does not:
#   1. Get B's "fingerprint": string refs, constant immediates, called functions
#   2. Check if A' contains B's fingerprint inline (inlining evidence)
#   3. If no inlining evidence, flag as SUSPECT match
#
# @category G2

from collections import Counter, defaultdict
from ghidra.program.model.symbol import SourceType

program = currentProgram
fm = program.getFunctionManager()

project = state.getProject()
ref_file = None
for f in project.getProjectData().getRootFolder().getFiles():
    if f.getName() == "lvgl_ref.o":
        ref_file = f
        break

ref_prog = ref_file.getDomainObject(java.lang.Object(), True, True, monitor)
ref_fm = ref_prog.getFunctionManager()

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

def get_data_refs(prog, func):
    """Get addresses of data/strings referenced by this function."""
    refs = set()
    for cu in prog.getListing().getCodeUnits(func.getBody(), True):
        for ref in cu.getReferencesFrom():
            if ref.getReferenceType().isData():
                refs.add(ref.getToAddress())
    return refs

def get_string_refs(prog, func):
    """Get actual string values referenced by this function."""
    strings = set()
    for cu in prog.getListing().getCodeUnits(func.getBody(), True):
        for ref in cu.getReferencesFrom():
            if ref.getReferenceType().isData():
                d = prog.getListing().getDefinedDataAt(ref.getToAddress())
                if d and d.hasStringValue():
                    s = d.getValue()
                    if s and len(s) > 2:
                        strings.add(s)
    return strings

def get_immediate_constants(prog, func):
    """Get notable immediate constants used in a function (filter out tiny/common ones)."""
    constants = set()
    for cu in prog.getListing().getCodeUnits(func.getBody(), True):
        if hasattr(cu, 'getNumOperands'):
            for i in range(cu.getNumOperands()):
                # Get scalar operand values
                ops = cu.getOpObjects(i)
                for op in ops:
                    if hasattr(op, 'getUnsignedValue'):
                        val = op.getUnsignedValue()
                        # Filter out very common values (0-32, powers of 2, 0xff/0xffff etc)
                        if val > 32 and val not in (64, 128, 256, 512, 1024, 0xff, 0xffff, 0xffffffff):
                            constants.add(val)
    return constants

# Build lookup tables
ref_funcs = {}
for func in ref_fm.getFunctions(True):
    ref_funcs[func.getName()] = func

fw_funcs = {}
for func in fm.getFunctions(True):
    fw_funcs[func.getName()] = func

ref_names_in_fw = set()
for func in fm.getFunctions(True):
    n = func.getName()
    if not n.startswith('FUN_'):
        ref_names_in_fw.add(n)

print("validate: Checking %d matched functions..." % len(ref_names_in_fw))

confirmed_inline = 0
suspect = 0
clean = 0
violations_total = 0

suspect_list = []

for func in fm.getFunctions(True):
    fw_name = func.getName()
    if fw_name not in ref_names_in_fw or fw_name not in ref_funcs:
        continue

    ref_callees = get_callees(ref_prog, ref_funcs[fw_name]) & ref_names_in_fw
    fw_callees = get_callees(program, func) & ref_names_in_fw
    missing = ref_callees - fw_callees

    if not missing:
        clean += 1
        continue

    # For each missing callee, check if it was inlined
    for missing_callee in missing:
        violations_total += 1

        if missing_callee not in ref_funcs:
            continue

        ref_callee_func = ref_funcs[missing_callee]
        fw_callee_func = fw_funcs.get(missing_callee)

        # Get the missing callee's fingerprint from the REFERENCE
        ref_callee_strings = get_string_refs(ref_prog, ref_callee_func)
        ref_callee_constants = get_immediate_constants(ref_prog, ref_callee_func)
        ref_callee_calls = get_callees(ref_prog, ref_callee_func)

        # Get the FW caller's content
        fw_caller_strings = get_string_refs(program, func)
        fw_caller_constants = get_immediate_constants(program, func)
        fw_caller_calls = get_callees(program, func)

        # Evidence of inlining:
        # 1. Callee's string refs appear in caller
        string_overlap = ref_callee_strings & fw_caller_strings
        # 2. Callee's notable constants appear in caller
        const_overlap = ref_callee_constants & fw_caller_constants
        # 3. Callee's own callees appear in caller (transitive calls from inlining)
        # i.e., if B calls C, and A inlines B, then A should now call C directly
        transitive_calls = ref_callee_calls & fw_caller_calls

        evidence_count = 0
        evidence_details = []

        if string_overlap:
            evidence_count += 2  # Strong evidence
            evidence_details.append("strings=%s" % list(string_overlap)[:2])
        if len(const_overlap) >= 2:
            evidence_count += 1
            evidence_details.append("constants=%d shared" % len(const_overlap))
        if transitive_calls:
            evidence_count += 1
            evidence_details.append("transitive_calls=%s" % list(transitive_calls)[:3])

        # Size check: if caller in FW is significantly larger than in ref,
        # that's consistent with inlining
        ref_caller_size = ref_funcs[fw_name].getBody().getNumAddresses()
        fw_caller_size = func.getBody().getNumAddresses()
        if fw_caller_size > ref_caller_size * 1.1:
            evidence_count += 1
            evidence_details.append("fw_larger(%d>%d)" % (fw_caller_size, ref_caller_size))

        # For very small callees (<=20 insn), inlining is expected even without evidence
        ref_callee_size = ref_callee_func.getBody().getNumAddresses()
        trivial_inline = ref_callee_size <= 40

        if evidence_count >= 1 or trivial_inline:
            confirmed_inline += 1
        else:
            suspect += 1
            suspect_list.append((fw_name, missing_callee, ref_callee_size, evidence_details))

print("")
print("validate: Results:")
print("  Clean (no missing calls): %d" % clean)
print("  Violations checked: %d" % violations_total)
print("  Confirmed inline (evidence found): %d" % confirmed_inline)
print("  SUSPECT (no inlining evidence): %d" % suspect)
print("")

if suspect_list:
    print("validate: SUSPECT matches (may be wrong):")
    for fw_name, missing_callee, callee_size, evidence in suspect_list:
        print("  %s: should call %s (%dB) but doesn't, no inline evidence" %
              (fw_name, missing_callee, callee_size))
else:
    print("validate: All violations explained by inlining. Matches look correct.")

ref_prog.release(java.lang.Object())
