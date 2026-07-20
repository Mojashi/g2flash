# -*- coding: utf-8 -*-
# Ghidra headless: Decompile SVC_Settings_AutoBrightnessOpen and the sensor hub
# task processing chain. Critical: display_startup calls AutoBrightnessOpen which
# calls HUB_Open, potentially reconfiguring IMU.
# @category CFW
from ghidra.app.decompiler import DecompInterface
from ghidra.util.task import ConsoleTaskMonitor

args = getScriptArgs()
outfile = args[0] if len(args) > 0 else "/tmp/imu_autobrightness.txt"

fm = currentProgram.getFunctionManager()
af = currentProgram.getAddressFactory()
mem = currentProgram.getMemory()
refmgr = currentProgram.getReferenceManager()
di = DecompInterface()
di.openProgram(currentProgram)
mon = ConsoleTaskMonitor()
def A(h): return af.getAddress(h)

out = open(outfile, "w")

# === Part 1: SVC_Settings_AutoBrightnessOpen/Close ===
out.write("=" * 80 + "\n")
out.write("PART 1: AutoBrightness Open/Close\n")
out.write("=" * 80 + "\n")

for addr in ["0x46b7c4", "0x46b890"]:
    f = fm.getFunctionAt(A(addr))
    if f:
        out.write("\n--- %s @ %s ---\n" % (f.getName(), f.getEntryPoint()))
        try:
            res = di.decompileFunction(f, 90, mon)
            if res and res.getDecompiledFunction():
                out.write(res.getDecompiledFunction().getC())
        except Exception as e:
            out.write("ERROR: %s\n" % e)
        out.write("\n  Callees:\n")
        for cf in f.getCalledFunctions(mon):
            out.write("    -> %s @ %s\n" % (cf.getName(), cf.getEntryPoint()))
        out.write("\n")

# === Part 2: Trace the ENTIRE sensor hub open flow ===
# HUB_Open(role) -> HUB_SendMessage(msg) -> xQueueSend to hub queue
# Then the hub task reads from the queue and processes
# Find: who reads from the hub queue (*(0x20003640+0xc))
out.write("\n" + "=" * 80 + "\n")
out.write("PART 2: Sensor hub task (the queue consumer)\n")
out.write("=" * 80 + "\n")

# The hub context is at DAT_004bf584 = 0x20003640
# The queue handle is at offset +0xc from that context
# Let's find ALL functions that reference DAT_004bf584
refs = refmgr.getReferencesTo(A("0x4bf584"))
hub_fns = set()
for ref in refs:
    fn = fm.getFunctionContaining(ref.getFromAddress())
    if fn:
        hub_fns.add(str(fn.getEntryPoint()))

out.write("Functions referencing DAT_004bf584 (hub context ptr):\n")
for fn_addr in sorted(hub_fns):
    fn = fm.getFunctionAt(A(fn_addr))
    if fn:
        out.write("  %s @ %s\n" % (fn.getName(), fn.getEntryPoint()))

# Decompile each one
for fn_addr in sorted(hub_fns):
    fn = fm.getFunctionAt(A(fn_addr))
    if fn:
        out.write("\n--- %s @ %s ---\n" % (fn.getName(), fn.getEntryPoint()))
        try:
            res = di.decompileFunction(fn, 90, mon)
            if res and res.getDecompiledFunction():
                out.write(res.getDecompiledFunction().getC()[:4000])
        except Exception as e:
            out.write("ERROR: %s\n" % e)
        out.write("\n")

# === Part 3: Find what creates the hub context struct ===
# Something calls FreeRTOS task create with the hub task function
# Search for functions that store into *0x4bf584 (= 0x20003640)
out.write("\n" + "=" * 80 + "\n")
out.write("PART 3: Who creates the hub context (writes to DAT_004bf584)\n")
out.write("=" * 80 + "\n")

# Also search broader area
for addr_off in range(0x4bf580, 0x4bf5a0, 4):
    refs = refmgr.getReferencesTo(A("0x%x" % addr_off))
    for ref in refs:
        if ref.getReferenceType().isWrite() or ref.getReferenceType() == ref.getReferenceType():
            fn = fm.getFunctionContaining(ref.getFromAddress())
            if fn:
                out.write("  0x%x %s from %s @ %s\n" % (addr_off,
                    ref.getReferenceType(), fn.getName(), fn.getEntryPoint()))

# === Part 4: The sensor hub's process function ===
# When the hub task receives a message, it dispatches based on message type
# Look for functions in the hub area (0x4bf000-0x4bfa00) that have switch/case patterns
out.write("\n" + "=" * 80 + "\n")
out.write("PART 4: ALL functions in hub area 0x4bf060-0x4bf400\n")
out.write("=" * 80 + "\n")

fn_iter = fm.getFunctions(A("0x4bf060"), True)
while fn_iter.hasNext():
    fn = fn_iter.next()
    if fn.getEntryPoint().getOffset() > 0x4bf400:
        break
    out.write("\n--- %s @ %s (size %d) ---\n" % (fn.getName(), fn.getEntryPoint(),
              fn.getBody().getNumAddresses()))
    try:
        res = di.decompileFunction(fn, 90, mon)
        if res and res.getDecompiledFunction():
            out.write(res.getDecompiledFunction().getC()[:4000])
    except Exception as e:
        out.write("ERROR: %s\n" % e)
    out.write("\n")

# === Part 5: Check DRV_IMUStartRawDataCollection and DRV_IMUStopRawDataCollection ===
out.write("\n" + "=" * 80 + "\n")
out.write("PART 5: IMU raw data collection start/stop\n")
out.write("=" * 80 + "\n")

for addr in ["0x4be7a0", "0x4be928", "0x4beb0e", "0x4bd9c0", "0x4be504"]:
    f = fm.getFunctionAt(A(addr))
    if f:
        out.write("\n--- %s @ %s ---\n" % (f.getName(), f.getEntryPoint()))
        try:
            res = di.decompileFunction(f, 90, mon)
            if res and res.getDecompiledFunction():
                out.write(res.getDecompiledFunction().getC()[:3000])
        except:
            pass
        out.write("\n  Callers:\n")
        refs = refmgr.getReferencesTo(f.getEntryPoint())
        for ref in refs:
            cfn = fm.getFunctionContaining(ref.getFromAddress())
            if cfn:
                out.write("    <- %s @ %s\n" % (cfn.getName(), cfn.getEntryPoint()))
        out.write("\n")

# === Part 6: Check the common_imu_setting_cmd function ===
out.write("\n" + "=" * 80 + "\n")
out.write("PART 6: common_imu_setting_cmd @ 0x4ff7e8\n")
out.write("=" * 80 + "\n")

f = fm.getFunctionAt(A("0x4ff7e8"))
if f:
    try:
        res = di.decompileFunction(f, 90, mon)
        if res and res.getDecompiledFunction():
            out.write(res.getDecompiledFunction().getC())
    except:
        pass

out.close()
print("Output -> " + outfile)
