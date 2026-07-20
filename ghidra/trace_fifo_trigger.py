# -*- coding: utf-8 -*-
# Final trace: find the FIFO read trigger mechanism.
# 1) Decompile FUN_005290a8 (called by the big init, near FIFO code)
# 2) Get FULL decompile of FUN_004bbed8 (the 3178-byte init function)
# 3) Find all callers of FUN_004bf040/FUN_004484ea (timer start) near IMU code
# 4) Search for FUN_0047e018 callers (thread pool post) in BHI260 area
# 5) Look at the IMU data flow: who reads from the sensor_state_struct at 0x200730c0
# @category CFW
from ghidra.app.decompiler import DecompInterface
from ghidra.util.task import ConsoleTaskMonitor
import codecs

args = getScriptArgs()
outfile = args[0] if len(args) > 0 else "/tmp/trace_fifo_trigger.txt"

fm = currentProgram.getFunctionManager()
af = currentProgram.getAddressFactory()
mem = currentProgram.getMemory()
refmgr = currentProgram.getReferenceManager()
di = DecompInterface()
di.openProgram(currentProgram)
mon = ConsoleTaskMonitor()
def A(h): return af.getAddress(h)

out = codecs.open(outfile, "w", "utf-8")

# === PART 1: FUN_005290a8 ===
out.write(u"=" * 80 + u"\n")
out.write(u"PART 1: FUN_005290a8 (near FIFO code, called by big init)\n")
out.write(u"=" * 80 + u"\n")

f = fm.getFunctionAt(A("0x5290a8"))
if f:
    try:
        res = di.decompileFunction(f, 120, mon)
        if res and res.getDecompiledFunction():
            out.write(res.getDecompiledFunction().getC())
    except Exception as e:
        out.write(u"error: %s\n" % e)
    out.write(u"\n\n  Callees:\n")
    for cf in f.getCalledFunctions(mon):
        out.write(u"    -> %s @ %s\n" % (cf.getName(), cf.getEntryPoint()))
    out.write(u"  Callers:\n")
    refs = refmgr.getReferencesTo(f.getEntryPoint())
    for ref in refs:
        if ref.getReferenceType().isCall():
            caller = fm.getFunctionContaining(ref.getFromAddress())
            if caller:
                out.write(u"    <- %s @ %s\n" % (caller.getName(), caller.getEntryPoint()))

# === PART 2: FULL decompile of FUN_004bbed8 ===
out.write(u"\n\n" + u"=" * 80 + u"\n")
out.write(u"PART 2: FUN_004bbed8 FULL decompilation (3178 bytes)\n")
out.write(u"=" * 80 + u"\n")

f = fm.getFunctionAt(A("0x4bbed8"))
if f is None:
    # Need to create it
    from ghidra.app.cmd.function import CreateFunctionCmd
    disassemble(A("0x4bbed8"))
    cmd = CreateFunctionCmd(A("0x4bbed8"))
    cmd.applyTo(currentProgram)
    f = fm.getFunctionAt(A("0x4bbed8"))

if f:
    try:
        res = di.decompileFunction(f, 300, mon)
        if res and res.getDecompiledFunction():
            out.write(res.getDecompiledFunction().getC())
    except Exception as e:
        out.write(u"error: %s\n" % e)

# === PART 3: Callers of FUN_004484ea (timer create) and FUN_004bf040 (timer start) ===
out.write(u"\n\n" + u"=" * 80 + u"\n")
out.write(u"PART 3: All callers of FUN_004484ea (timer) in IMU-related code\n")
out.write(u"=" * 80 + u"\n")

for timer_addr in ["0x4484ea", "0x4bf040"]:
    f = fm.getFunctionAt(A(timer_addr))
    if f:
        out.write(u"\nCallers of %s @ %s:\n" % (f.getName(), timer_addr))
        refs = refmgr.getReferencesTo(f.getEntryPoint())
        for ref in refs:
            if ref.getReferenceType().isCall():
                caller = fm.getFunctionContaining(ref.getFromAddress())
                if caller:
                    ep = caller.getEntryPoint().getOffset()
                    # Filter to IMU-related range (0x4bb000-0x4c0000 and 0x527000-0x530000)
                    if (0x4bb000 <= ep <= 0x4c0000) or (0x527000 <= ep <= 0x530000):
                        out.write(u"  IMU: %s @ %s\n" % (caller.getName(), caller.getEntryPoint()))
                    else:
                        out.write(u"  other: %s @ %s\n" % (caller.getName(), caller.getEntryPoint()))

# === PART 4: FUN_0047e018 callers in BHI260 area ===
out.write(u"\n\n" + u"=" * 80 + u"\n")
out.write(u"PART 4: FUN_0047e018 (thread pool post) callers in sensor area\n")
out.write(u"=" * 80 + u"\n")

f = fm.getFunctionAt(A("0x47e018"))
if f:
    refs = refmgr.getReferencesTo(f.getEntryPoint())
    for ref in refs:
        if ref.getReferenceType().isCall():
            caller = fm.getFunctionContaining(ref.getFromAddress())
            if caller:
                ep = caller.getEntryPoint().getOffset()
                if (0x4a7000 <= ep <= 0x4a8000) or (0x4bb000 <= ep <= 0x4c1000) or (0x527000 <= ep <= 0x530000):
                    out.write(u"  %s @ %s\n" % (caller.getName(), caller.getEntryPoint()))

# === PART 5: Look at bhi260_reg_read (0x52c544) and bhi260_reg_write (0x52c55c) ===
# These are the bus primitives. Decompile them to understand bus access mechanism.
out.write(u"\n\n" + u"=" * 80 + u"\n")
out.write(u"PART 5: bhi260_reg_read and bhi260_reg_write bus primitives\n")
out.write(u"=" * 80 + u"\n")

for addr in ["0x52c544", "0x52c55c"]:
    f = fm.getFunctionAt(A(addr))
    if f:
        out.write(u"\n--- %s @ %s ---\n" % (f.getName(), f.getEntryPoint()))
        try:
            res = di.decompileFunction(f, 120, mon)
            if res and res.getDecompiledFunction():
                out.write(res.getDecompiledFunction().getC())
        except Exception as e:
            out.write(u"error: %s\n" % e)
        out.write(u"\n")

# === PART 6: Look for the interrupt/timer setup in IMU code ===
# Check if FUN_004bbed8 or any nearby function starts a periodic timer
out.write(u"\n\n" + u"=" * 80 + u"\n")
out.write(u"PART 6: Functions that create timers or register interrupts\n")
out.write(u"=" * 80 + u"\n")

# Look for FUN_004483c8 which is called by FUN_004bbed8
f = fm.getFunctionAt(A("0x4483c8"))
if f:
    out.write(u"\n--- FUN_004483c8 (called by big init) ---\n")
    try:
        res = di.decompileFunction(f, 120, mon)
        if res and res.getDecompiledFunction():
            out.write(res.getDecompiledFunction().getC())
    except Exception as e:
        out.write(u"error: %s\n" % e)
    out.write(u"\n  Callers:\n")
    refs = refmgr.getReferencesTo(f.getEntryPoint())
    for ref in refs:
        if ref.getReferenceType().isCall():
            caller = fm.getFunctionContaining(ref.getFromAddress())
            if caller:
                out.write(u"    <- %s @ %s\n" % (caller.getName(), caller.getEntryPoint()))

out.close()
print("done -> " + outfile)
