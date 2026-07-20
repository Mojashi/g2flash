# -*- coding: utf-8 -*-
# Ghidra headless: Find and create functions in the unanalyzed gap 0x4bbdb4-0x4bcb54.
# Strategy: disassemble from likely entry points, create functions, decompile them.
# Also check for Thumb PUSH.W instructions as function prologues.
# @category CFW
from ghidra.app.decompiler import DecompInterface
from ghidra.util.task import ConsoleTaskMonitor
from ghidra.app.cmd.function import CreateFunctionCmd
from ghidra.program.model.address import AddressSet
import codecs

args = getScriptArgs()
outfile = args[0] if len(args) > 0 else "/tmp/gap_funcs.txt"

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

GAP_START = 0x4bbdb4
GAP_END = 0x4bcb54

# === Step 1: Scan for Thumb PUSH patterns (function prologues) ===
out.write(u"=== Scanning for PUSH prologues in 0x%x-0x%x ===\n" % (GAP_START, GAP_END))

# In ARM Thumb-2, PUSH.W {r4-r11, lr} is encoded as 2DE9 xx4F (big-endian)
# Common Thumb-2 PUSH.W patterns:
#   E92D xxxx  (32-bit: PUSH.W {reglist})
#   B5xx       (16-bit: PUSH {reglist, lr})
# Let's scan for both patterns

push_addrs = []
addr = GAP_START
while addr < GAP_END:
    try:
        a = A("0x%x" % addr)
        b0 = mem.getByte(a) & 0xff
        b1 = mem.getByte(A("0x%x" % (addr + 1))) & 0xff

        # 16-bit PUSH {Rlist, LR}: B5xx
        if b0 >= 0x00 and b1 == 0xb5:
            push_addrs.append(addr)
            out.write(u"  16-bit PUSH at 0x%x: %02x%02x\n" % (addr, b1, b0))
            addr += 2
            continue

        # 32-bit PUSH.W {Rlist}: E92D xxxx (little-endian: 2D E9 xx xx)
        if b0 == 0x2d and b1 == 0xe9:
            b2 = mem.getByte(A("0x%x" % (addr + 2))) & 0xff
            b3 = mem.getByte(A("0x%x" % (addr + 3))) & 0xff
            push_addrs.append(addr)
            out.write(u"  32-bit PUSH.W at 0x%x: E92D %02x%02x\n" % (addr, b3, b2))
            addr += 4
            continue

        # Also check for STMDB SP!, which is another PUSH.W encoding
        # F84D xxxx pattern
        if b0 == 0x4d and b1 == 0xf8:
            push_addrs.append(addr)
            out.write(u"  STMDB PUSH at 0x%x\n" % addr)
            addr += 4
            continue

        addr += 2
    except:
        addr += 2

out.write(u"\nFound %d potential function prologues\n\n" % len(push_addrs))

# === Step 2: Try to disassemble and create functions at each PUSH location ===
out.write(u"=== Creating functions at PUSH locations ===\n")
created_funcs = []

for pa in push_addrs:
    a = A("0x%x" % pa)
    # Check if already in a function
    existing = fm.getFunctionContaining(a)
    if existing:
        out.write(u"  0x%x: already in %s @ %s\n" % (pa, existing.getName(), existing.getEntryPoint()))
        continue

    # Try to disassemble
    try:
        disassemble(a)
    except:
        pass

    # Try to create function
    try:
        cmd = CreateFunctionCmd(a)
        cmd.applyTo(currentProgram)
        f = fm.getFunctionAt(a)
        if f:
            out.write(u"  CREATED: %s @ 0x%x (size %d)\n" % (f.getName(), pa, f.getBody().getNumAddresses()))
            created_funcs.append(f)
        else:
            out.write(u"  0x%x: createFunction returned None\n" % pa)
    except Exception as e:
        out.write(u"  0x%x: error: %s\n" % (pa, e))

out.write(u"\nCreated %d new functions\n\n" % len(created_funcs))

# === Step 3: Decompile all functions in the gap (including newly created) ===
out.write(u"=== Decompile all functions in gap ===\n")

fn_iter = fm.getFunctions(A("0x%x" % GAP_START), True)
count = 0
while fn_iter.hasNext() and count < 30:
    fn = fn_iter.next()
    ep = fn.getEntryPoint().getOffset()
    if ep >= GAP_END:
        break
    count += 1
    out.write(u"\n--- %s @ 0x%x (size %d) ---\n" % (fn.getName(), ep, fn.getBody().getNumAddresses()))

    # Decompile
    try:
        res = di.decompileFunction(fn, 120, mon)
        if res and res.getDecompiledFunction():
            out.write(res.getDecompiledFunction().getC()[:5000])
        else:
            msg = res.getErrorMessage() if res else "null"
            out.write(u"decompile failed: %s\n" % msg)
    except Exception as e:
        out.write(u"exception: %s\n" % e)

    # Callees
    out.write(u"\n  Callees:\n")
    for cf in fn.getCalledFunctions(mon):
        out.write(u"    -> %s @ %s\n" % (cf.getName(), cf.getEntryPoint()))
    # Callers
    out.write(u"  Callers:\n")
    refs = refmgr.getReferencesTo(fn.getEntryPoint())
    for ref in refs:
        if ref.getReferenceType().isCall():
            caller = fm.getFunctionContaining(ref.getFromAddress())
            if caller:
                out.write(u"    <- %s @ %s\n" % (caller.getName(), caller.getEntryPoint()))
    out.write(u"\n")

# === Step 4: Also scan the range just before the gap for context ===
# Look at the listing/disassembly between drv_imu_init end and the first PUSH
out.write(u"\n=== Listing scan: 0x4bbdb4-0x4bbe00 ===\n")
a = A("0x%x" % GAP_START)
end_a = A("0x4bbe00")
instr = listing.getInstructionAt(a)
while instr is not None and instr.getAddress().compareTo(end_a) < 0:
    out.write(u"  %s: %s %s\n" % (instr.getAddress(), instr.getMnemonicString(),
                                    instr.toString().split(' ', 1)[-1] if ' ' in instr.toString() else ''))
    instr = instr.getNext()
    if instr is None:
        # Try the next address
        next_addr = a.add(2)
        instr = listing.getInstructionAt(next_addr)
        if instr is None:
            break
        a = instr.getAddress()

out.close()
print("done -> " + outfile)
