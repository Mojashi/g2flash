# -*- coding: utf-8 -*-
from ghidra.app.decompiler import DecompInterface
from ghidra.util.task import ConsoleTaskMonitor
fm = currentProgram.getFunctionManager()
af = currentProgram.getAddressFactory()
def A(h): return af.getAddress(h)
dec = DecompInterface(); dec.openProgram(currentProgram); mon = ConsoleTaskMonitor()
for addr in ("0x005792da", "0x00578f90", "0x005cfb8a"):
    f = fm.getFunctionContaining(A(addr))
    res = dec.decompileFunction(f, 60, mon)
    c = res.getDecompiledFunction().getC()
    print("\n===== %s @%s =====" % (f.getName(), f.getEntryPoint()))
    print(c[:1100])
