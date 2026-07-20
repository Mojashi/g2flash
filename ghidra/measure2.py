# -*- coding: utf-8 -*-
from ghidra.app.decompiler import DecompInterface
from ghidra.util.task import ConsoleTaskMonitor
fm = currentProgram.getFunctionManager()
af = currentProgram.getAddressFactory()
def A(h): return af.getAddress(h)
def is_ascii(s):
    return all(ord(c) < 128 for c in s)
funcs = list(fm.getFunctions(True))
n = len(funcs)
fun_ = sum(1 for f in funcs if f.getName().startswith("FUN_"))
garbled = sum(1 for f in funcs if not is_ascii(f.getName()))
shortish = sum(1 for f in funcs if len(f.getName()) <= 4 and not f.getName().startswith("FUN_"))
undef = 0
for f in funcs:
    rt = f.getReturnType().getName()
    if rt.startswith("undefined") or any(p.getDataType().getName().startswith("undefined") for p in f.getParameters()):
        undef += 1
print("MEASURE2: %d funcs | named %d (%.0f%%) | FUN_ %d | garbled %d | <=4char %d | undefined-sig %d (%.0f%%)"
      % (n, n-fun_, 100.0*(n-fun_)/n, fun_, garbled, shortish, undef, 100.0*undef/n))
dec = DecompInterface(); dec.openProgram(currentProgram); mon = ConsoleTaskMonitor()
for addr in ("0x00508942", "0x00578d88"):
    f = fm.getFunctionContaining(A(addr))
    res = dec.decompileFunction(f, 60, mon)
    print("\n===== %s @%s =====" % (f.getName(), f.getEntryPoint()))
    print(res.getDecompiledFunction().getC()[:900])
