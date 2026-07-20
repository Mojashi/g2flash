# -*- coding: utf-8 -*-
# Force-disassemble and create functions at 0x4bbc00-0x4bbcc6 (bus layer + FIFO wrapper)
# Also look at 0x4bbcc6 to 0x4bbdb4 for more handlers
# @category CFW
from ghidra.app.decompiler import DecompInterface
from ghidra.util.task import ConsoleTaskMonitor
from ghidra.app.cmd.function import CreateFunctionCmd
import codecs

args = getScriptArgs()
outfile = args[0] if len(args) > 0 else "/tmp/bus_fifo_wrapper.txt"

fm = currentProgram.getFunctionManager()
af = currentProgram.getAddressFactory()
mem = currentProgram.getMemory()
listing = currentProgram.getListing()
refmgr = currentProgram.getReferenceManager()
di = DecompInterface()
di.openProgram(currentProgram)
mon = ConsoleTaskMonitor()
def A(h): return af.getAddress(h)

out = codecs.open(outfile, "w", "utf-8")

# === Force-disassemble known function entry points in 0x4bbc00-0x4bbcc6 ===
out.write(u"=== Force-disassemble bus functions and find FIFO wrapper ===\n\n")

# Known entry points from the driver_ctx table:
# driver_ctx[0] = 0x4bbc69 -> actual entry at 0x4bbc68
# driver_ctx[1] = 0x4bbca3 -> actual entry at 0x4bbca2

known_entries = [0x4bbc68, 0x4bbca2]

# Also try to find PUSH patterns in 0x4bbc00-0x4bbcc6
for addr in range(0x4bbc00, 0x4bbcc6, 2):
    try:
        a = A("0x%x" % addr)
        b0 = mem.getByte(a) & 0xff
        b1 = mem.getByte(A("0x%x" % (addr + 1))) & 0xff
        # 16-bit PUSH: B5xx
        if b1 == 0xb5:
            if addr not in known_entries:
                known_entries.append(addr)
                out.write(u"  Found 16-bit PUSH at 0x%x\n" % addr)
        # 32-bit PUSH.W: 2D E9 xx xx
        elif b0 == 0x2d and b1 == 0xe9:
            if addr not in known_entries:
                known_entries.append(addr)
                out.write(u"  Found 32-bit PUSH.W at 0x%x\n" % addr)
    except:
        pass

# Also scan 0x4bbcc6 to 0x4bbed8 (after register_fifo_handlers, before big init)
for addr in range(0x4bbcc6, 0x4bbed8, 2):
    try:
        a = A("0x%x" % addr)
        b0 = mem.getByte(a) & 0xff
        b1 = mem.getByte(A("0x%x" % (addr + 1))) & 0xff
        if b1 == 0xb5:
            known_entries.append(addr)
            out.write(u"  Found 16-bit PUSH at 0x%x (post-register area)\n" % addr)
        elif b0 == 0x2d and b1 == 0xe9:
            known_entries.append(addr)
            out.write(u"  Found 32-bit PUSH.W at 0x%x (post-register area)\n" % addr)
    except:
        pass

known_entries.sort()
out.write(u"\nAll potential function entries: %s\n\n" % ["0x%x" % a for a in known_entries])

# Force-create functions at each entry
for entry in known_entries:
    a = A("0x%x" % entry)
    existing = fm.getFunctionAt(a)
    if existing:
        out.write(u"  Already exists: %s @ 0x%x\n" % (existing.getName(), entry))
        continue
    try:
        disassemble(a)
        cmd = CreateFunctionCmd(a)
        cmd.applyTo(currentProgram)
        f = fm.getFunctionAt(a)
        if f:
            out.write(u"  CREATED: %s @ 0x%x (size %d)\n" % (f.getName(), entry, f.getBody().getNumAddresses()))
        else:
            out.write(u"  Failed to create at 0x%x\n" % entry)
    except Exception as e:
        out.write(u"  Error at 0x%x: %s\n" % (entry, e))

# === Decompile all functions in 0x4bbc00-0x4bbed8 ===
out.write(u"\n\n=== Decompile all functions in 0x4bbc00-0x4bbed8 ===\n")

fn_iter = fm.getFunctions(A("0x4bbc00"), True)
count = 0
while fn_iter.hasNext() and count < 30:
    fn = fn_iter.next()
    ep = fn.getEntryPoint().getOffset()
    if ep >= 0x4bbed8:
        break
    count += 1
    out.write(u"\n--- %s @ 0x%x (size %d) ---\n" % (fn.getName(), ep, fn.getBody().getNumAddresses()))
    try:
        res = di.decompileFunction(fn, 120, mon)
        if res and res.getDecompiledFunction():
            out.write(res.getDecompiledFunction().getC())
        else:
            msg = res.getErrorMessage() if res else "null"
            out.write(u"decompile failed: %s\n" % msg)
    except Exception as e:
        out.write(u"exception: %s\n" % e)
    out.write(u"\n  Callees:\n")
    for cf in fn.getCalledFunctions(mon):
        out.write(u"    -> %s @ %s\n" % (cf.getName(), cf.getEntryPoint()))
    out.write(u"  Callers:\n")
    refs = refmgr.getReferencesTo(fn.getEntryPoint())
    for ref in refs:
        if ref.getReferenceType().isCall():
            caller = fm.getFunctionContaining(ref.getFromAddress())
            if caller:
                out.write(u"    <- %s @ %s\n" % (caller.getName(), caller.getEntryPoint()))
    out.write(u"\n")

out.close()
print("done -> " + outfile)
