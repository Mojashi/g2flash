# -*- coding: utf-8 -*-
# Ghidra headless: Deep trace of the IMU callback invocation chain.
# The callback DRV_IMUDataParserCallback is stored at runtime in SRAM (driver_ctx+0x18).
# We need to find code that loads from [ctx_reg + 0x18] and calls through it.
# Strategy:
# 1. Decompile FUN_004bbcc6 (references driver context)
# 2. Decompile FUN_00527e6c (chip init, called during IMU driver init)
# 3. Decompile FUN_0052918a (large 908-byte function - likely main driver routine)
# 4. Decompile all functions in 0x529000-0x529e00 that have indirect calls
# 5. Search for the display_thread task function and its queue processing
# 6. Trace what happens when display_startup's queue message is received
# @category CFW
from ghidra.app.decompiler import DecompInterface
from ghidra.util.task import ConsoleTaskMonitor

args = getScriptArgs()
outfile = args[0] if len(args) > 0 else "/tmp/imu_deep_trace.txt"

fm = currentProgram.getFunctionManager()
af = currentProgram.getAddressFactory()
mem = currentProgram.getMemory()
refmgr = currentProgram.getReferenceManager()
listing = currentProgram.getListing()
di = DecompInterface()
di.openProgram(currentProgram)
mon = ConsoleTaskMonitor()
def A(h): return af.getAddress(h)

out = open(outfile, "w")

# === Part 1: FUN_004bbcc6 (references driver context area) ===
out.write("=" * 80 + "\n")
out.write("PART 1: FUN_004bbcc6 (called after callback registration)\n")
out.write("=" * 80 + "\n")
for addr in ["0x4bbcc6", "0x527e6c"]:
    f = fm.getFunctionAt(A(addr))
    if f is None:
        f = fm.getFunctionContaining(A(addr))
    if f:
        out.write("\n--- %s @ %s ---\n" % (f.getName(), f.getEntryPoint()))
        try:
            res = di.decompileFunction(f, 90, mon)
            if res and res.getDecompiledFunction():
                out.write(res.getDecompiledFunction().getC())
        except Exception as e:
            out.write("ERROR: %s\n" % e)
    else:
        out.write("No function at %s\n" % addr)
    out.write("\n")

# === Part 2: Large functions in IMU chip driver area ===
out.write("=" * 80 + "\n")
out.write("PART 2: Key chip driver functions (0x529000-0x529e00)\n")
out.write("=" * 80 + "\n")

# Decompile the largest/most interesting functions
key_fns = [
    "0x529032", "0x5290a8", "0x52918a",  # large early functions
    "0x529516", "0x529590", "0x5295d4", "0x5295f8",
    "0x52960a", "0x5296b4", "0x5296f0",
    "0x5298e0", "0x5299b0", "0x529a22", "0x529a64",
    "0x529b82", "0x529c44", "0x529cb4",
    "0x529d76", "0x529d9e", "0x529dd6",
]

for addr in key_fns:
    f = fm.getFunctionAt(A(addr))
    if f is None:
        continue
    size = f.getBody().getNumAddresses()
    out.write("\n--- %s @ %s (size %d) ---\n" % (f.getName(), f.getEntryPoint(), size))
    try:
        res = di.decompileFunction(f, 90, mon)
        if res and res.getDecompiledFunction():
            c = res.getDecompiledFunction().getC()
            out.write(c)
        else:
            out.write("  FAILED\n")
    except Exception as e:
        out.write("  ERROR: %s\n" % e)
    out.write("\n")

# === Part 3: Display thread queue receiver ===
# display_startup sends to *DAT_00443adc queue. Find who reads from this queue.
out.write("=" * 80 + "\n")
out.write("PART 3: Display thread - queue receiver (refs to 0x443adc)\n")
out.write("=" * 80 + "\n")

refs = refmgr.getReferencesTo(A("0x443adc"))
seen = set()
for ref in refs:
    fn = fm.getFunctionContaining(ref.getFromAddress())
    if fn and str(fn.getEntryPoint()) not in seen:
        seen.add(str(fn.getEntryPoint()))
        out.write("\n--- %s @ %s ---\n" % (fn.getName(), fn.getEntryPoint()))
        try:
            res = di.decompileFunction(fn, 90, mon)
            if res and res.getDecompiledFunction():
                c = res.getDecompiledFunction().getC()
                out.write(c[:5000])
        except Exception as e:
            out.write("ERROR: %s\n" % e)
        out.write("\n")

# Also check DAT_00443ae0 (the mutex used in display_startup)
out.write("\n--- Refs to display mutex 0x443ae0 ---\n")
refs = refmgr.getReferencesTo(A("0x443ae0"))
for ref in refs:
    fn = fm.getFunctionContaining(ref.getFromAddress())
    if fn:
        out.write("  %s @ %s\n" % (fn.getName(), fn.getEntryPoint()))

# === Part 4: Find the display thread task entry point ===
# Search for functions named with "thread" or "task" that contain display logic
out.write("\n" + "=" * 80 + "\n")
out.write("PART 4: Find display_thread task entry\n")
out.write("=" * 80 + "\n")

fn_iter = fm.getFunctions(True)
while fn_iter.hasNext():
    fn = fn_iter.next()
    name = fn.getName().lower()
    if "display" in name and ("thread" in name or "task" in name or "main" in name or "loop" in name):
        out.write("  %s @ %s\n" % (fn.getName(), fn.getEntryPoint()))

# Check what FUN_004bbcc6 calls and what it does with the param (0x200730c0)
out.write("\n" + "=" * 80 + "\n")
out.write("PART 5: FUN_004bbcc6 deep trace (called after callback set)\n")
out.write("=" * 80 + "\n")
f = fm.getFunctionAt(A("0x4bbcc6"))
if f:
    out.write("Callees of FUN_004bbcc6:\n")
    for cf in f.getCalledFunctions(mon):
        out.write("  -> %s @ %s\n" % (cf.getName(), cf.getEntryPoint()))
        try:
            res = di.decompileFunction(cf, 90, mon)
            if res and res.getDecompiledFunction():
                c = res.getDecompiledFunction().getC()
                out.write(c[:3000])
        except:
            pass
        out.write("\n")

# === Part 6: Trace the sensor hub task that processes HUB_SendMessage ===
# The queue is at *(DAT_004bf584+0xc). Find who reads from this.
out.write("\n" + "=" * 80 + "\n")
out.write("PART 6: Sensor hub task (reads from hub queue)\n")
out.write("=" * 80 + "\n")

# Read DAT_004bf584 value
try:
    hub_ctx = mem.getInt(A("0x4bf584"))
    out.write("DAT_004bf584 = 0x%08x\n" % (hub_ctx & 0xffffffff))
    out.write("Hub queue at *(0x%x + 0xc) = *(0x%x)\n" % (hub_ctx & 0xffffffff, (hub_ctx + 0xc) & 0xffffffff))
except:
    out.write("Cannot read DAT_004bf584\n")

# Find functions in the hub area that call xQueueReceive
fn_iter = fm.getFunctions(A("0x4bf000"), True)
while fn_iter.hasNext():
    fn = fn_iter.next()
    if fn.getEntryPoint().getOffset() > 0x4bfa00:
        break
    for cf in fn.getCalledFunctions(mon):
        if "queue" in cf.getName().lower() and "receive" in cf.getName().lower():
            out.write("\n%s @ %s calls %s\n" % (fn.getName(), fn.getEntryPoint(), cf.getName()))
            try:
                res = di.decompileFunction(fn, 90, mon)
                if res and res.getDecompiledFunction():
                    out.write(res.getDecompiledFunction().getC()[:5000])
            except:
                pass
            out.write("\n")

# Also find ALL functions calling xQueueReceive that reference hub globals
fn_iter = fm.getFunctions(True)
hub_task_fns = []
while fn_iter.hasNext():
    fn = fn_iter.next()
    calls_qrecv = False
    refs_hub = False
    for cf in fn.getCalledFunctions(mon):
        if "queue" in cf.getName().lower() and "receiv" in cf.getName().lower():
            calls_qrecv = True
            break
    if calls_qrecv:
        # Check if this function references hub globals
        body = fn.getBody()
        for addr_off in range(0x4bf580, 0x4bf5a0, 4):
            refs = refmgr.getReferencesFrom(fn.getEntryPoint())
            # Too complex - just check function name or decompile
            hub_task_fns.append(fn)
            break

out.write("\nFunctions calling xQueueReceive:\n")
for fn in hub_task_fns[:20]:
    out.write("  %s @ %s\n" % (fn.getName(), fn.getEntryPoint()))

# === Part 7: Decompile FUN_0052ac5e and FUN_0052acbe (near fusion lib) ===
out.write("\n" + "=" * 80 + "\n")
out.write("PART 7: Functions near fusion library\n")
out.write("=" * 80 + "\n")

for addr in ["0x52ac5e", "0x52acbe", "0x52ad7c", "0x52b2f8", "0x52bf50", "0x52bfa6",
             "0x52bff8", "0x52c03c", "0x52c136"]:
    f = fm.getFunctionAt(A(addr))
    if f:
        out.write("\n--- %s @ %s ---\n" % (f.getName(), f.getEntryPoint()))
        try:
            res = di.decompileFunction(f, 90, mon)
            if res and res.getDecompiledFunction():
                out.write(res.getDecompiledFunction().getC()[:3000])
        except:
            pass
        out.write("\n")

out.close()
print("Output -> " + outfile)
