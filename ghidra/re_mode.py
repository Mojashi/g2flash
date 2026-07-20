# -*- coding: utf-8 -*-
from ghidra.app.decompiler import DecompInterface
from ghidra.util.task import ConsoleTaskMonitor
fm=currentProgram.getFunctionManager(); af=currentProgram.getAddressFactory()
dec=DecompInterface(); dec.openProgram(currentProgram); mon=ConsoleTaskMonitor()
# FUN_00529c44 = IMU library config/enable
# FUN_004bd578 = what HUB_ParameterConfig(2,...) calls
# FUN_00527e6c = IMU library init
for addr in ["0x529c44","0x4bd578","0x527e6c"]:
    f=fm.getFunctionAt(af.getAddress(addr))
    if not f: f=fm.getFunctionContaining(af.getAddress(addr))
    if not f: print("no fn @%s"%addr); continue
    res=dec.decompileFunction(f,90,mon)
    print("\n===== %s @%s (%d chars) ====="%(f.getName(),f.getEntryPoint(),len(res.getDecompiledFunction().getC())))
    print(res.getDecompiledFunction().getC()[:2500])
