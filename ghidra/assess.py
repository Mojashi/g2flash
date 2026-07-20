# -*- coding: utf-8 -*-
# Ghidra headless: honest readability assessment of the current DB.
# Counts naming/typing coverage and dumps a typical pb handler (structs NOT applied) so we can
# see the real state, not the one demo function. @category CFW
from ghidra.app.decompiler import DecompInterface
from ghidra.util.task import ConsoleTaskMonitor

fm = currentProgram.getFunctionManager()
af = currentProgram.getAddressFactory()
rm = currentProgram.getReferenceManager()
def A(h): return af.getAddress(h)

funcs = list(fm.getFunctions(True))
n = len(funcs)
fun_ = sum(1 for f in funcs if f.getName().startswith("FUN_"))
def is_ascii(s):
    try: s.encode("ascii"); return True
    except Exception: return False
garbled = [f for f in funcs if not is_ascii(f.getName())]
default_sig = 0
for f in funcs:
    rt = f.getReturnType().getName()
    ps = f.getParameters()
    if rt.startswith("undefined") and all(p.getDataType().getName().startswith("undefined") for p in ps):
        default_sig += 1
print("ASSESS: %d funcs; %d still FUN_ (%.0f%% named); %d garbled/non-ascii names; %d fully-undefined sigs"
      % (n, fun_, 100.0*(n-fun_)/n, len(garbled), default_sig))
print("ASSESS: sample garbled names:", [f.getName() for f in garbled[:10]])

# how many descriptor globals are referenced (auto-apply opportunity)
import re
sym = currentProgram.getSymbolTable()
descs = [s for s in sym.getAllSymbols(False) if s.getName().endswith("_msgdesc")]
tot_ref = 0; tot_fn = set()
for s in descs:
    for r in rm.getReferencesTo(s.getAddress()):
        tot_ref += 1
        fn = fm.getFunctionContaining(r.getFromAddress())
        if fn: tot_fn.add(fn.getEntryPoint())
print("ASSESS: %d pb descriptors, %d total refs across %d distinct functions (auto-apply targets)"
      % (len(descs), tot_ref, len(tot_fn)))

# dump a TYPICAL pb handler with structs NOT applied (health handler @0x578d88 from earlier)
dec = DecompInterface(); dec.openProgram(currentProgram); mon = ConsoleTaskMonitor()
f = fm.getFunctionContaining(A("0x00578d88"))
res = dec.decompileFunction(f, 60, mon)
print("\n===== TYPICAL handler %s @%s (pb structs NOT applied) =====" % (f.getName(), f.getEntryPoint()))
print(res.getDecompiledFunction().getC()[:1400])
