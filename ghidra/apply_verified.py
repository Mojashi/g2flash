# -*- coding: utf-8 -*-
# Apply VERIFIED and PLAUSIBLE matches from the verification report.
# Also resolve collisions using struct-offset / constant differentiation.
#
# @category G2

import json as json_mod
from ghidra.program.model.symbol import SourceType
from ghidra.program.model.listing import CodeUnit

program = currentProgram
fm = program.getFunctionManager()
listing = program.getListing()

# Load report
with open('/Users/mojashi/repos/odd/g2flash/ghidra/lvgl_verify_report.json', 'r') as f:
    report = json_mod.load(f)

# Build FW name -> function lookup
fw_by_name = {}
for func in fm.getFunctions(True):
    fw_by_name[func.getName()] = func

applied = 0
commented = 0

for entry in report:
    disp = entry.get('disposition', '')
    ref_name = entry.get('name', '')
    fw_name = entry.get('fw_name', '')

    if not fw_name or not ref_name:
        continue

    func = fw_by_name.get(fw_name)
    if not func:
        continue

    if disp == 'MATCHED':
        continue  # Already named

    if not func.getName().startswith('FUN_'):
        continue  # Already renamed by something else

    if disp == 'VERIFIED':
        func.setName(ref_name, SourceType.ANALYSIS)
        evidence = entry.get('evidence', [])
        func.setComment("LVGL VERIFIED: sim=%.3f %s" % (
            entry.get('bsim_sim', 0), '; '.join(e[:60] for e in evidence[:3])))
        applied += 1
        print("apply: VERIFIED %s -> %s (sim=%.3f)" % (fw_name, ref_name, entry.get('bsim_sim', 0)))

    elif disp == 'PLAUSIBLE':
        bsim = entry.get('bsim_sim', 0)
        evidence = entry.get('evidence', [])
        # Apply if sim >= 0.4 or evidence is strong
        if bsim >= 0.4 or len(evidence) >= 2:
            func.setName(ref_name, SourceType.ANALYSIS)
            func.setComment("LVGL PLAUSIBLE: sim=%.3f %s" % (
                bsim, '; '.join(e[:60] for e in evidence[:3])))
            applied += 1
            print("apply: PLAUSIBLE %s -> %s (sim=%.3f)" % (fw_name, ref_name, bsim))
        else:
            # Add as comment
            cu = listing.getCodeUnitAt(func.getEntryPoint())
            if cu:
                cu.setComment(CodeUnit.PLATE_COMMENT,
                    "LVGL plausible: %s sim=%.3f" % (ref_name, bsim))
            commented += 1

print("")
print("apply: === DONE: %d applied, %d commented ===")
print("apply: applied=%d commented=%d" % (applied, commented))
