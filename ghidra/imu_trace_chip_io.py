# -*- coding: utf-8 -*-
# Ghidra headless: decompile FUN_0052c544, FUN_0052c55c, FUN_00529c44
# and trace the bus (SPI/I2C) they use for IMU chip register I/O.
# Also decompile surrounding functions to understand the full call chain.
# @category CFW
from ghidra.app.decompiler import DecompInterface
from ghidra.util.task import ConsoleTaskMonitor

args = getScriptArgs()
outfile = args[0] if len(args) > 0 else "/tmp/imu_chip_io.txt"

fm = currentProgram.getFunctionManager()
af = currentProgram.getAddressFactory()
mem = currentProgram.getMemory()
refmgr = currentProgram.getReferenceManager()
di = DecompInterface()
di.openProgram(currentProgram)
mon = ConsoleTaskMonitor()
def A(h): return af.getAddress(h)

out = open(outfile, "w")

# Key functions to decompile
targets = [
    ("FUN_0052c544", "0x52c544", "chip register write? (called by sensor enable)"),
    ("FUN_0052c55c", "0x52c55c", "chip register read? (called by sensor enable)"),
    ("FUN_00529c44", "0x529c44", "sensor enable function (sets gyro flags)"),
    ("DRV_IMUAccelConfig", "0x4bd95a", "accel rate configuration"),
    ("DRV_IMUDataParserCallback", "0x4bdd8c", "IMU data parser callback"),
    ("HUB_Open", "0x4bf410", "sensor hub open"),
    ("HUB_Close", "0x4bf482", "sensor hub close"),
    ("HUB_ParameterConfig", "0x4bf4f4", "sensor hub config"),
    ("HUB_SendMessage", "0x4bf0d2", "post message to sensor hub queue"),
    ("StartIMUCompassFunc", "0x564e4c", "enable gyro+compass"),
    ("StopIMUCompassFunc", "0x564ed4", "disable gyro+compass"),
]

for name, addr_hex, desc in targets:
    out.write("=" * 80 + "\n")
    out.write("%s @ %s -- %s\n" % (name, addr_hex, desc))
    out.write("=" * 80 + "\n")

    a = A(addr_hex)
    f = fm.getFunctionAt(a)
    if f is None:
        f = fm.getFunctionContaining(a)
    if f is None:
        try:
            disassemble(a)
            f = createFunction(a, None)
        except:
            pass
    if f is None:
        out.write("  NO FUNCTION at %s\n\n" % addr_hex)
        continue

    # List callers
    out.write("Callers:\n")
    refs = refmgr.getReferencesTo(f.getEntryPoint())
    caller_count = 0
    for ref in refs:
        if ref.getReferenceType().isCall() or ref.getReferenceType().isJump():
            fa = ref.getFromAddress()
            cfn = fm.getFunctionContaining(fa)
            if cfn:
                out.write("  called from %s @ %s (instr at %s)\n" % (cfn.getName(), cfn.getEntryPoint(), fa))
            else:
                out.write("  called from ??? at %s\n" % fa)
            caller_count += 1
    if caller_count == 0:
        out.write("  (no direct callers found)\n")

    # List callees
    out.write("Callees:\n")
    called = f.getCalledFunctions(mon)
    for cf in called:
        out.write("  calls %s @ %s\n" % (cf.getName(), cf.getEntryPoint()))

    # Decompile
    out.write("\nDecompilation:\n")
    try:
        res = di.decompileFunction(f, 90, mon)
        if res and res.getDecompiledFunction():
            out.write(res.getDecompiledFunction().getC())
        else:
            msg = res.getErrorMessage() if res else "no result"
            out.write("  FAILED: %s\n" % msg)
    except Exception as e:
        out.write("  ERROR: %s\n" % e)
    out.write("\n\n")

# === Also decompile functions called by FUN_0052c544 and FUN_0052c55c ===
out.write("=" * 80 + "\n")
out.write("CALLEES OF FUN_0052c544 AND FUN_0052c55c (chip I/O inner functions)\n")
out.write("=" * 80 + "\n")

for addr_hex in ["0x52c544", "0x52c55c"]:
    f = fm.getFunctionAt(A(addr_hex))
    if f is None:
        continue
    for cf in f.getCalledFunctions(mon):
        out.write("\n--- %s @ %s (called by %s) ---\n" % (cf.getName(), cf.getEntryPoint(), addr_hex))
        try:
            res = di.decompileFunction(cf, 90, mon)
            if res and res.getDecompiledFunction():
                out.write(res.getDecompiledFunction().getC())
            else:
                out.write("  FAILED\n")
        except Exception as e:
            out.write("  ERROR: %s\n" % e)
        out.write("\n")

# === Trace deeper: what does FUN_00529c44 call that might set sample rate? ===
out.write("=" * 80 + "\n")
out.write("FULL CALL TREE FROM FUN_00529c44 (2 levels deep)\n")
out.write("=" * 80 + "\n")

seen = set()
def trace_calls(fn, depth=0, max_depth=2):
    if depth > max_depth:
        return
    key = str(fn.getEntryPoint())
    if key in seen:
        return
    seen.add(key)
    indent = "  " * depth
    out.write("%s%s @ %s\n" % (indent, fn.getName(), fn.getEntryPoint()))
    for cf in fn.getCalledFunctions(mon):
        trace_calls(cf, depth + 1, max_depth)

f = fm.getFunctionAt(A("0x529c44"))
if f:
    trace_calls(f)

out.close()
print("Output -> " + outfile)
