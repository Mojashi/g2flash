# -*- coding: utf-8 -*-
# Ghidra headless: validate the applied pb structs. For a few descriptors, list the functions
# that reference them (the encode/decode/handler sites), then decompile one handler and, where a
# pb_decode(stream, &msgdesc, dest) call is present, retype the dest local to the struct and show
# the field-named decompilation. @category CFW
from ghidra.app.decompiler import DecompInterface
from ghidra.util.task import ConsoleTaskMonitor

fm = currentProgram.getFunctionManager()
af = currentProgram.getAddressFactory()
rm = currentProgram.getReferenceManager()
dtm = currentProgram.getDataTypeManager()
def A(h): return af.getAddress(h)

TARGETS = {"0x772c80": "HealthDataPackage", "0x772398": "EvenAIDataPackage", "0x777840": "TerminalDataPackage"}

for hx, nm in TARGETS.items():
    a = A(hx)
    refs = list(rm.getReferencesTo(a))
    funcs = []
    for r in refs:
        f = fm.getFunctionContaining(r.getFromAddress())
        if f and f not in funcs: funcs.append(f)
    print("== %s (%s): %d refs in %d funcs ==" % (nm, hx, len(refs), len(funcs)))
    for f in funcs[:8]:
        print("   %s @%s" % (f.getName(), f.getEntryPoint()))

# decompile the first handler of HealthDataPackage and show it
dec = DecompInterface(); dec.openProgram(currentProgram); mon = ConsoleTaskMonitor()
a = A("0x772398")   # EvenAI: 11-field oneof, clear structure
refs = list(rm.getReferencesTo(a))
seen = set()
for r in refs:
    f = fm.getFunctionContaining(r.getFromAddress())
    if not f or f.getEntryPoint() in seen: continue
    seen.add(f.getEntryPoint())
    res = dec.decompileFunction(f, 60, mon)
    if not res.decompileCompleted(): continue
    code = res.getDecompiledFunction().getC()
    print("\n===== %s @%s (%d chars) =====" % (f.getName(), f.getEntryPoint(), len(code)))
    print(code[:1600])
    break
