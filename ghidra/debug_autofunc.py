# -*- coding: utf-8 -*-
# Debug: decompile one known function that calls log_printf, print all CALL pcode ops
# with their target addresses, to see if 0x43d514 is what the decompiler resolves.
from ghidra.app.decompiler import DecompInterface
from ghidra.util.task import ConsoleTaskMonitor
from ghidra.program.model.pcode import PcodeOp

fm = currentProgram.getFunctionManager()
af = currentProgram.getAddressFactory()
di = DecompInterface(); di.openProgram(currentProgram); mon = ConsoleTaskMonitor()

# Try a function we know calls log_printf: DRV_IMUAccelConfig at 0x4bd95a
f = fm.getFunctionAt(af.getAddress("0x4bd95a"))
if f is None:
    # If the function doesn't exist at that exact address, find the one containing it
    f = fm.getFunctionContaining(af.getAddress("0x4bd95a"))
print("target function: %s @ %s" % (f.getName() if f else "NONE", f.getEntryPoint() if f else "?"))

if f:
    res = di.decompileFunction(f, 60, mon)
    if res and res.getHighFunction():
        hf = res.getHighFunction()
        calls = []
        for op in hf.getPcodeOps():
            if op.getOpcode() == PcodeOp.CALL:
                inp0 = op.getInput(0)
                if inp0.isConstant():
                    calls.append("CONST:0x%x (ninputs=%d)" % (inp0.getOffset(), op.getNumInputs()))
                elif inp0.isAddress():
                    calls.append("ADDR:0x%x (ninputs=%d)" % (inp0.getAddress().getOffset(), op.getNumInputs()))
                else:
                    calls.append("OTHER:%s (ninputs=%d)" % (inp0, op.getNumInputs()))
        print("CALL targets in %s:" % f.getName())
        for c in calls: print("  " + c)
    else:
        print("decompile failed: %s" % (res.getErrorMessage() if res else "null"))

# Also: how many FUN_ functions exist?
fun_count = sum(1 for fn in fm.getFunctions(True) if fn.getName().startswith("FUN_"))
total = sum(1 for fn in fm.getFunctions(True))
print("\ntotal functions: %d, FUN_: %d, named: %d" % (total, fun_count, total - fun_count))

# Check if 0x43d514 is recognized as a function
logf = fm.getFunctionAt(af.getAddress("0x43d514"))
print("log_printf @ 0x43d514: %s" % (logf.getName() if logf else "NOT A FUNCTION"))
logf2 = fm.getFunctionAt(af.getAddress("0x43ce46"))
print("FUN_0043ce46 @ 0x43ce46: %s" % (logf2.getName() if logf2 else "NOT A FUNCTION"))
