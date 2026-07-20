# -*- coding: utf-8 -*-
# Ghidra headless: export every NAMED (non-FUN_/non-DAT_) function to a reusable C header of
# absolute Thumb addresses, so hot-loaded payloads can call firmware by name. Also dumps a sample.
# @category CFW
from ghidra.program.model.symbol import SourceType

fm = currentProgram.getFunctionManager()
args = getScriptArgs()
outfile = args[0] if args else "/tmp/fw_syms.h"

rows = []
for f in fm.getFunctions(True):
    nm = f.getName()
    if nm.startswith("FUN_") or nm.startswith("thunk_") or nm.startswith("_"):
        continue
    a = f.getEntryPoint().getOffset()
    if a < 0x400000 or a >= 0x800000:
        continue
    rows.append((nm, a))

# de-dup by name (keep first)
seen = set(); uniq = []
for nm, a in rows:
    if nm in seen: continue
    seen.add(nm); uniq.append((nm, a))
uniq.sort(key=lambda x: x[1])

out = open(outfile, "w")
out.write("/* fw 2.2.4.34 mainapp - named firmware entry points (Thumb bit set). Auto-generated.\n")
out.write(" * %d functions. Call from a PIC payload via ((fn_t)FW_name)(...). */\n#pragma once\n\n" % len(uniq))
ASCII = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_")
for nm, a in uniq:
    ident = "FW_" + "".join((c if c in ASCII else '_') for c in nm)
    out.write("#define %-52s 0x%08xu\n" % (ident, a | 1))
out.close()
print("exported %d named functions -> %s" % (len(uniq), outfile))
# sample: print 30 spread out
step = max(1, len(uniq)//30)
print("--- sample ---")
for i in range(0, len(uniq), step):
    nm, a = uniq[i]
    print("  0x%08x  %s" % (a, nm))
