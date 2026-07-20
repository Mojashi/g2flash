# -*- coding: utf-8 -*-
from ghidra.app.decompiler import DecompInterface
from ghidra.util.task import ConsoleTaskMonitor
fm=currentProgram.getFunctionManager(); af=currentProgram.getAddressFactory()
dec=DecompInterface(); dec.openProgram(currentProgram); mon=ConsoleTaskMonitor()
# FUN_004bbd66 = IMU init (references the callback table)
f=fm.getFunctionAt(af.getAddress("0x4bbd66"))
res=dec.decompileFunction(f,90,mon)
print("===== %s @%s ====="%( f.getName(),f.getEntryPoint()))
print(res.getDecompiledFunction().getC())
# Also: FUN_004bbc68 and FUN_004bbca2 (the two other callbacks in the table)
for addr in ["0x4bbc68","0x4bbca2"]:
    f2=fm.getFunctionAt(af.getAddress(addr))
    if not f2: f2=fm.getFunctionContaining(af.getAddress(addr))
    if not f2: print("no fn @%s"%addr); continue
    res2=dec.decompileFunction(f2,60,mon)
    print("\n===== %s @%s ====="%(f2.getName(),f2.getEntryPoint()))
    print(res2.getDecompiledFunction().getC()[:1500])
