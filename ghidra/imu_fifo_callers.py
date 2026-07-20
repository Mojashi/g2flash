# -*- coding: utf-8 -*-
# Ghidra headless: Find who calls the three FIFO frame parsers and trace
# up to the FIFO reading loop / interrupt handler.
# @category CFW
from ghidra.app.decompiler import DecompInterface
from ghidra.util.task import ConsoleTaskMonitor

args = getScriptArgs()
outfile = args[0] if len(args) > 0 else "/tmp/imu_fifo_callers.txt"

fm = currentProgram.getFunctionManager()
af = currentProgram.getAddressFactory()
refmgr = currentProgram.getReferenceManager()
di = DecompInterface()
di.openProgram(currentProgram)
mon = ConsoleTaskMonitor()
def A(h): return af.getAddress(h)

out = open(outfile, "w")

# === Find callers of the 3 FIFO frame parsers ===
parser_addrs = ["0x527fd4", "0x528414", "0x528dba"]
all_callers = set()

for addr in parser_addrs:
    f = fm.getFunctionAt(A(addr))
    if not f:
        continue
    out.write("=== Callers of %s @ %s ===\n" % (f.getName(), addr))
    refs = refmgr.getReferencesTo(f.getEntryPoint())
    for ref in refs:
        if ref.getReferenceType().isCall():
            fn = fm.getFunctionContaining(ref.getFromAddress())
            if fn:
                out.write("  <- %s @ %s (from %s)\n" % (fn.getName(), fn.getEntryPoint(), ref.getFromAddress()))
                all_callers.add(str(fn.getEntryPoint()))
    out.write("\n")

# === Decompile each unique caller ===
for fn_addr in sorted(all_callers):
    fn = fm.getFunctionAt(A(fn_addr))
    if fn:
        out.write("\n--- %s @ %s (size %d) ---\n" % (fn.getName(), fn.getEntryPoint(), fn.getBody().getNumAddresses()))
        try:
            res = di.decompileFunction(fn, 90, mon)
            if res and res.getDecompiledFunction():
                out.write(res.getDecompiledFunction().getC())
        except Exception as e:
            out.write("ERROR: %s\n" % e)
        out.write("\n")

        # Also find callers of THIS function (one more level up)
        out.write("  Callers of %s:\n" % fn.getName())
        refs2 = refmgr.getReferencesTo(fn.getEntryPoint())
        for ref2 in refs2:
            if ref2.getReferenceType().isCall():
                fn2 = fm.getFunctionContaining(ref2.getFromAddress())
                if fn2:
                    out.write("    <- %s @ %s\n" % (fn2.getName(), fn2.getEntryPoint()))
        out.write("\n")

# === Also find the worker_thread and decompile it ===
out.write("\n=== worker_thread @ 004a712c ===\n")
f = fm.getFunctionAt(A("0x4a712c"))
if f:
    try:
        res = di.decompileFunction(f, 90, mon)
        if res and res.getDecompiledFunction():
            out.write(res.getDecompiledFunction().getC()[:5000])
    except:
        pass
    out.write("\n\n  Callers:\n")
    refs = refmgr.getReferencesTo(f.getEntryPoint())
    for ref in refs:
        fn = fm.getFunctionContaining(ref.getFromAddress())
        if fn:
            out.write("    <- %s @ %s\n" % (fn.getName(), fn.getEntryPoint()))

# === Also decompile FUN_00528f70 which calls FUN_0052c544 ===
out.write("\n\n=== FUN_00528f70 (potential FIFO reader) ===\n")
f = fm.getFunctionAt(A("0x528f70"))
if f:
    try:
        res = di.decompileFunction(f, 90, mon)
        if res and res.getDecompiledFunction():
            out.write(res.getDecompiledFunction().getC()[:5000])
    except:
        pass
    out.write("\n  Callers:\n")
    refs = refmgr.getReferencesTo(f.getEntryPoint())
    for ref in refs:
        fn = fm.getFunctionContaining(ref.getFromAddress())
        if fn:
            out.write("    <- %s @ %s\n" % (fn.getName(), fn.getEntryPoint()))

# === Check area between 0x528d00-0x528f70 for FIFO control ===
out.write("\n\n=== Functions in 0x528d00-0x529000 ===\n")
fn_iter = fm.getFunctions(A("0x528d00"), True)
while fn_iter.hasNext():
    fn = fn_iter.next()
    if fn.getEntryPoint().getOffset() > 0x529032:
        break
    out.write("%s @ %s (size %d)\n" % (fn.getName(), fn.getEntryPoint(), fn.getBody().getNumAddresses()))
    # List callees
    for cf in fn.getCalledFunctions(mon):
        out.write("  -> %s @ %s\n" % (cf.getName(), cf.getEntryPoint()))

out.close()
print("Output -> " + outfile)
