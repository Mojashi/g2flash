# Ghidra headless script: decompile function at given address
# Usage: -postScript decompile_func.py 0xADDRESS
# @category CFW
from ghidra.app.decompiler import DecompInterface
from ghidra.util.task import ConsoleTaskMonitor
import sys

args = getScriptArgs()
if not args:
    print("ERROR: pass hex address as argument")
else:
    addr_str = args[0]
    af = currentProgram.getAddressFactory()
    fm = currentProgram.getFunctionManager()
    
    addr = af.getAddress(addr_str)
    func = fm.getFunctionAt(addr)
    if func is None:
        func = fm.getFunctionContaining(addr)
    if func is None:
        # try to create function
        from ghidra.app.cmd.function import CreateFunctionCmd
        cmd = CreateFunctionCmd(addr)
        cmd.applyTo(currentProgram)
        func = fm.getFunctionAt(addr)
    
    if func is None:
        print("ERROR: no function at %s" % addr_str)
    else:
        decomp = DecompInterface()
        decomp.openProgram(currentProgram)
        mon = ConsoleTaskMonitor()
        res = decomp.decompileFunction(func, 60, mon)
        if res and res.decompileCompleted():
            print("=== DECOMPILED: %s @ %s ===" % (func.getName(), func.getEntryPoint()))
            print(res.getDecompiledFunction().getC())
        else:
            print("ERROR: decompile failed for %s" % func.getName())
        decomp.dispose()
