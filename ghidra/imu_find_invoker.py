# -*- coding: utf-8 -*-
# Ghidra headless: Find the function that INVOKES DRV_IMUDataParserCallback
# by searching for all functions that call through function pointers at
# offset +0x18 (or [param+6] in int* arithmetic) from a pointer.
# Also find the sensor hub task and FIFO reading code.
# @category CFW
from ghidra.app.decompiler import DecompInterface
from ghidra.util.task import ConsoleTaskMonitor

args = getScriptArgs()
outfile = args[0] if len(args) > 0 else "/tmp/imu_find_invoker.txt"

fm = currentProgram.getFunctionManager()
af = currentProgram.getAddressFactory()
mem = currentProgram.getMemory()
refmgr = currentProgram.getReferenceManager()
di = DecompInterface()
di.openProgram(currentProgram)
mon = ConsoleTaskMonitor()
def A(h): return af.getAddress(h)

out = open(outfile, "w")

# === Part 1: Search for indirect calls through offset +0x18 from context ===
# Decompile all functions in the BHI260 driver area and look for "(param_1 + 0x18)"
# or "param_1[6]" patterns indicating callback invocation through ctx[6]
out.write("=" * 80 + "\n")
out.write("PART 1: Search for callback invocation via ctx[6] / offset +0x18\n")
out.write("=" * 80 + "\n")

# Search in two areas:
# 1. BHI260 driver: 0x527e00 - 0x52d000
# 2. Sensor hub: 0x4bf000 - 0x4c0000
# 3. IMU wrapper: 0x4bbc00 - 0x4bf000

search_ranges = [
    (0x527e00, 0x52d000, "BHI260 driver"),
    (0x4bbc00, 0x4bf000, "IMU wrapper"),
    (0x4bf000, 0x4c0000, "Sensor hub"),
    (0x579c00, 0x57a200, "BHI260 extended"),
    (0x4cbf00, 0x4cc200, "TWIM1 I2C area"),
]

for start, end, desc in search_ranges:
    out.write("\n--- Scanning %s (0x%x - 0x%x) ---\n" % (desc, start, end))
    fn_iter = fm.getFunctions(A("0x%x" % start), True)
    while fn_iter.hasNext():
        fn = fn_iter.next()
        if fn.getEntryPoint().getOffset() > end:
            break
        try:
            res = di.decompileFunction(fn, 60, mon)
            if res and res.getDecompiledFunction():
                c = res.getDecompiledFunction().getC()
                # Search for callback-through-offset patterns
                # Look for: + 0x18, [6], + 6], +6), + 24
                # Specifically: indirect calls through offset 0x18 or slot [6]
                indicators = [
                    "param_1 + 0x18",
                    "param_1[6]",
                    "+ 0x18)",
                    "* 0x18)",
                    "_1 + 6]",
                    "code *)",
                    "*(code **)",
                ]
                has_indirect = any(ind in c for ind in indicators)
                if has_indirect and ("(*" in c):
                    out.write("\n[MATCH] %s @ %s\n" % (fn.getName(), fn.getEntryPoint()))
                    out.write(c)
                    out.write("\n")
        except:
            pass

# === Part 2: Find FUN_00448b8c (xQueueReceive?) callers that reference hub globals ===
out.write("\n" + "=" * 80 + "\n")
out.write("PART 2: Find xQueueReceive (FUN_00448b8c) callers that use hub queue\n")
out.write("=" * 80 + "\n")

# First, verify FUN_00448b8c is xQueueReceive
qrecv = fm.getFunctionAt(A("0x448b8c"))
if qrecv:
    out.write("FUN_00448b8c = %s\n" % qrecv.getName())
    refs = refmgr.getReferencesTo(qrecv.getEntryPoint())
    out.write("\nAll callers of FUN_00448b8c:\n")
    seen = set()
    for ref in refs:
        if ref.getReferenceType().isCall():
            fn = fm.getFunctionContaining(ref.getFromAddress())
            if fn and str(fn.getEntryPoint()) not in seen:
                seen.add(str(fn.getEntryPoint()))
                out.write("  %s @ %s\n" % (fn.getName(), fn.getEntryPoint()))

# === Part 3: Find the sensor hub task entry by looking for queue readers ===
# The hub context is at 0x20003640. Queue at *(0x20003640+0xc).
# Search for functions that load from 0x4bf584 and then access +0xc
out.write("\n" + "=" * 80 + "\n")
out.write("PART 3: Sensor hub task - find queue consumer\n")
out.write("=" * 80 + "\n")

# Check all callers of FUN_00448b8c (xQueueReceive) and check which ones
# also reference addresses near 0x4bf584
for fn_addr_str in seen:
    fn = fm.getFunctionAt(A(fn_addr_str))
    if fn:
        # Check if function references any hub globals
        body_refs = set()
        for addr in fn.getBody().getAddresses(True):
            for ref in refmgr.getReferencesFrom(addr):
                body_refs.add(ref.getToAddress().getOffset())
        hub_refs = [r for r in body_refs if 0x4bf580 <= r < 0x4bfa00]
        if hub_refs:
            out.write("\n[HUB TASK CANDIDATE] %s @ %s refs: %s\n" %
                     (fn.getName(), fn.getEntryPoint(),
                      ["0x%x" % r for r in hub_refs]))
            try:
                res = di.decompileFunction(fn, 90, mon)
                if res and res.getDecompiledFunction():
                    out.write(res.getDecompiledFunction().getC()[:5000])
            except:
                pass
            out.write("\n")

# === Part 4: Decompile FUN_00529590 (called by config function at end) ===
out.write("\n" + "=" * 80 + "\n")
out.write("PART 4: FUN_00529590 and FIFO control functions\n")
out.write("=" * 80 + "\n")

for addr in ["0x529590", "0x5295d4", "0x5295f8"]:
    f = fm.getFunctionAt(A(addr))
    if f:
        out.write("\n--- %s @ %s ---\n" % (f.getName(), f.getEntryPoint()))
        try:
            res = di.decompileFunction(f, 90, mon)
            if res and res.getDecompiledFunction():
                out.write(res.getDecompiledFunction().getC())
        except:
            pass
        out.write("\n")

# === Part 5: Search for ALL functions with indirect calls through ctx+0x18 ===
# Use a broader decompilation search
out.write("\n" + "=" * 80 + "\n")
out.write("PART 5: Broader search for (*...+0x18) or [6]) pattern in ALL code\n")
out.write("=" * 80 + "\n")

# Search the entire firmware for functions that call through offset 0x18
fn_iter = fm.getFunctions(True)
count = 0
while fn_iter.hasNext() and count < 5000:
    fn = fn_iter.next()
    count += 1
    addr_off = fn.getEntryPoint().getOffset()
    # Only check functions in code sections (not in RAM)
    if addr_off < 0x400000 or addr_off > 0x600000:
        continue
    try:
        res = di.decompileFunction(fn, 30, mon)
        if res and res.getDecompiledFunction():
            c = res.getDecompiledFunction().getC()
            # Very specific pattern: call through offset +0x18 from first param
            if ("+ 0x18)" in c or "param_1[6]" in c) and ("(code" in c or "(*" in c):
                # Check if it's actually an indirect call (not just address arithmetic)
                if "(*(code" in c or "(*(" in c:
                    out.write("\n[CANDIDATE] %s @ %s\n" % (fn.getName(), fn.getEntryPoint()))
                    out.write(c[:2000])
                    out.write("\n")
    except:
        pass

# === Part 6: Decompile I2C bus functions at 0x4bbc69 and 0x4bbca3 ===
out.write("\n" + "=" * 80 + "\n")
out.write("PART 6: I2C bus primitives (ctx[0]=0x4bbc69, ctx[1]=0x4bbca3)\n")
out.write("=" * 80 + "\n")

for addr in ["0x4bbc69", "0x4bbca3", "0x4a7125", "0x4cbf3c"]:
    f = fm.getFunctionAt(A(addr))
    if f is None:
        f = fm.getFunctionContaining(A(addr))
    if f:
        out.write("\n--- %s @ %s ---\n" % (f.getName(), f.getEntryPoint()))
        try:
            res = di.decompileFunction(f, 90, mon)
            if res and res.getDecompiledFunction():
                out.write(res.getDecompiledFunction().getC()[:3000])
        except:
            pass
        # Also list callees
        out.write("\n  Callees:\n")
        for cf in f.getCalledFunctions(mon):
            out.write("    -> %s @ %s\n" % (cf.getName(), cf.getEntryPoint()))
        out.write("\n")

# === Part 7: Decompile ALL callers of FUN_004bbd66 (IMU driver init) ===
# This tells us who sets up the IMU and when
out.write("\n" + "=" * 80 + "\n")
out.write("PART 7: Callers of IMU driver init (FUN_004bbd66)\n")
out.write("=" * 80 + "\n")

f = fm.getFunctionAt(A("0x4bbd66"))
if f:
    refs = refmgr.getReferencesTo(f.getEntryPoint())
    for ref in refs:
        if ref.getReferenceType().isCall():
            fn = fm.getFunctionContaining(ref.getFromAddress())
            if fn:
                out.write("\n--- Caller: %s @ %s ---\n" % (fn.getName(), fn.getEntryPoint()))
                try:
                    res = di.decompileFunction(fn, 90, mon)
                    if res and res.getDecompiledFunction():
                        out.write(res.getDecompiledFunction().getC()[:3000])
                except:
                    pass
                out.write("\n")

out.close()
print("Output -> " + outfile)
