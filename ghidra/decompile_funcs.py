# Ghidra headless post-script: decompile functions at given runtime addresses to C.
# Usage (headless):
#   analyzeHeadless <proj> g2fw -process g2_mainapp.bin -noanalysis \
#     -postScript decompile_funcs.py "0x4422c4,0x4716c4,0x588c90" /tmp/out.c
# @category CFW
from ghidra.app.decompiler import DecompInterface
from ghidra.util.task import ConsoleTaskMonitor

args = getScriptArgs()
addrs_csv = args[0]
outfile = args[1] if len(args) > 1 else "/tmp/ghidra_decomp.c"

fm = currentProgram.getFunctionManager()
af = currentProgram.getAddressFactory()
di = DecompInterface()
di.openProgram(currentProgram)
mon = ConsoleTaskMonitor()

import codecs
out = codecs.open(outfile, "w", "utf-8")
for h in addrs_csv.split(","):
    h = h.strip()
    if not h:
        continue
    a = af.getAddress(h)
    f = fm.getFunctionAt(a)
    if f is None:
        f = fm.getFunctionContaining(a)
    if f is None:
        try:
            disassemble(a)          # honors the TMode (Thumb) context from analysis
            f = createFunction(a, None)
        except Exception as e:
            out.write(u"// %s: could not create function (%s)\n\n" % (h, e))
            continue
    if f is None:
        out.write(u"// %s: no function\n\n" % h)
        continue
    try:
        res = di.decompileFunction(f, 90, mon)
        if res is not None and res.getDecompiledFunction() is not None:
            out.write(u"// ===== %s @ %s =====\n" % (f.getName(), f.getEntryPoint()))
            c_text = res.getDecompiledFunction().getC()
            out.write(c_text)
            out.write(u"\n\n")
        else:
            msg = res.getErrorMessage() if res is not None else "no result"
            out.write(u"// %s (%s): decompile failed: %s\n\n" % (f.getName(), h, msg))
    except Exception as e:
        out.write(u"// %s: exception %s\n\n" % (h, e))
out.close()
print("decompiled -> " + outfile)
