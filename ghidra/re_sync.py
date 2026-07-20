# -*- coding: utf-8 -*-
from ghidra.app.decompiler import DecompInterface
from ghidra.util.task import ConsoleTaskMonitor
fm = currentProgram.getFunctionManager()
af = currentProgram.getAddressFactory()
def A(h): return af.getAddress(h)
dec = DecompInterface(); dec.openProgram(currentProgram); mon = ConsoleTaskMonitor()
# barrier + peer send + peer recv + role check
for addr in ("0x00572648", "0x00464c28", "0x0045ba68", "0x0045aab0"):
    f = fm.getFunctionContaining(A(addr))
    if f is None:
        print("== %s : no function ==" % addr); continue
    res = dec.decompileFunction(f, 90, mon)
    c = res.getDecompiledFunction().getC()
    print("\n========== %s @%s (%d chars) ==========" % (f.getName(), f.getEntryPoint(), len(c)))
    print(c[:2600])
