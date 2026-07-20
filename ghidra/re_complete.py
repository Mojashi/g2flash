# -*- coding: utf-8 -*-
from ghidra.app.decompiler import DecompInterface
from ghidra.util.task import ConsoleTaskMonitor
fm = currentProgram.getFunctionManager()
af = currentProgram.getAddressFactory()
def A(h): return af.getAddress(h)
dec = DecompInterface(); dec.openProgram(currentProgram); mon = ConsoleTaskMonitor()
# FW_COMPLETE_EMIT emitter, and the function containing the completion site 0x500a04, and deferred 0x4ae9cc
for addr in ("0x004ff44a", "0x00500a04", "0x004ae9cc"):
    f = fm.getFunctionContaining(A(addr))
    if f is None: print("== %s: no function ==" % addr); continue
    res = dec.decompileFunction(f, 90, mon)
    c = res.getDecompiledFunction().getC()
    print("\n========== %s  (contains %s, %d chars) ==========" % (f.getName(), addr, len(c)))
    print(c[:2400])
