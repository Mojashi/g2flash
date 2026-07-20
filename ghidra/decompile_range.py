# Ghidra headless: decompile EVERY function whose entry lies in the given runtime ranges.
# IAR lays a .c file's functions contiguously, so a range that spans one source file yields
# that file's whole API. Emits decompiled C with a per-func header (addr, name, size).
# Usage: -postScript decompile_range.py "0x4b0f00-0x4b1cae,0x4b1cae-0x4b3400" /tmp/corpus.c
# @category CFW
from ghidra.app.decompiler import DecompInterface
from ghidra.util.task import ConsoleTaskMonitor

fm = currentProgram.getFunctionManager()
af = currentProgram.getAddressFactory()

args = getScriptArgs()
ranges_csv = args[0]
outfile = args[1] if len(args) > 1 else "/tmp/corpus.c"

def A(h): return af.getAddress(h)

ranges = []
for tok in ranges_csv.split(","):
    tok = tok.strip()
    if not tok:
        continue
    lo, hi = tok.split("-")
    ranges.append((int(lo, 16), int(hi, 16)))

di = DecompInterface()
di.openProgram(currentProgram)
mon = ConsoleTaskMonitor()

out = open(outfile, "w")
n = 0
funcs = fm.getFunctions(True)  # in address order
for f in funcs:
    ep = f.getEntryPoint().getOffset()
    inr = False
    for lo, hi in ranges:
        if lo <= ep < hi:
            inr = True
            break
    if not inr:
        continue
    n += 1
    sz = f.getBody().getNumAddresses()
    try:
        res = di.decompileFunction(f, 90, mon)
        c = res.getDecompiledFunction().getC() if (res and res.getDecompiledFunction()) else "// decompile failed\n"
    except Exception as e:
        c = "// exception %s\n" % e
    out.write("// ===== %s @ 0x%x  (%dB) =====\n" % (f.getName(), ep, sz))
    out.write(c)
    out.write("\n")
out.close()
print("decompiled %d funcs -> %s" % (n, outfile))
