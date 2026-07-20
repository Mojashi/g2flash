# -*- coding: utf-8 -*-
# Ghidra headless: final readability measurement + show the health handler after name+type fixes.
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
print("MEASURE: %d funcs; %d named (%.0f%%); %d still FUN_; %d garbled"
      % (n, n - fun_, 100.0*(n-fun_)/n, fun_, garbled))
dec = DecompInterface(); dec.openProgram(currentProgram); mon = ConsoleTaskMonitor()
f = fm.getFunctionContaining(A("0x00578d88"))
res = dec.decompileFunction(f, 60, mon)
print("\n===== %s @%s (after name + pb-type fixes) =====" % (f.getName(), f.getEntryPoint()))
print(res.getDecompiledFunction().getC()[:1500])
