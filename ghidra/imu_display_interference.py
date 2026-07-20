# -*- coding: utf-8 -*-
# Ghidra headless: investigate if display_startup or foreground mode interferes with IMU.
# Check: task creation, priority changes, queue operations, mutexes shared between
# display compositor and IMU driver.
# @category CFW
from ghidra.app.decompiler import DecompInterface
from ghidra.util.task import ConsoleTaskMonitor

args = getScriptArgs()
outfile = args[0] if len(args) > 0 else "/tmp/imu_display_interference.txt"

fm = currentProgram.getFunctionManager()
af = currentProgram.getAddressFactory()
mem = currentProgram.getMemory()
refmgr = currentProgram.getReferenceManager()
st = currentProgram.getSymbolTable()
di = DecompInterface()
di.openProgram(currentProgram)
mon = ConsoleTaskMonitor()
def A(h): return af.getAddress(h)

out = open(outfile, "w")

# === Part 1: Find display_startup and decompile it ===
out.write("=" * 80 + "\n")
out.write("PART 1: Find and decompile display_startup\n")
out.write("=" * 80 + "\n")

# Search for function name containing "display_startup" or "display_init"
display_fns = []
fn_iter = fm.getFunctions(True)
while fn_iter.hasNext():
    fn = fn_iter.next()
    name = fn.getName().lower()
    if any(kw in name for kw in ["display_startup", "display_init", "display_start",
                                   "foreground", "compositor", "ui_task",
                                   "display_open", "display_create"]):
        display_fns.append(fn)

out.write("Display-related functions found:\n")
for fn in display_fns:
    out.write("  %s @ %s\n" % (fn.getName(), fn.getEntryPoint()))

# Decompile each
for fn in display_fns[:10]:
    out.write("\n--- %s @ %s ---\n" % (fn.getName(), fn.getEntryPoint()))
    try:
        res = di.decompileFunction(fn, 90, mon)
        if res and res.getDecompiledFunction():
            out.write(res.getDecompiledFunction().getC())
        else:
            out.write("  FAILED\n")
    except Exception as e:
        out.write("  ERROR: %s\n" % e)
    out.write("\n")

# === Part 2: Search for symbols/functions related to tasks and priorities ===
out.write("=" * 80 + "\n")
out.write("PART 2: Task/thread related functions\n")
out.write("=" * 80 + "\n")

task_fns = []
fn_iter = fm.getFunctions(True)
while fn_iter.hasNext():
    fn = fn_iter.next()
    name = fn.getName().lower()
    if any(kw in name for kw in ["task_create", "xTaskCreate", "vTaskSuspend",
                                   "vTaskPrioritySet", "xQueueSend", "xQueueReceive",
                                   "hub_task", "imu_task", "sensor_task",
                                   "spi_task", "i2c_task", "drv_imu",
                                   "hub_send", "hub_recv", "hub_process"]):
        task_fns.append(fn)

out.write("Task/IMU-related functions:\n")
for fn in task_fns:
    out.write("  %s @ %s\n" % (fn.getName(), fn.getEntryPoint()))

# === Part 3: Decompile HUB_SendMessage and trace the queue ===
out.write("\n" + "=" * 80 + "\n")
out.write("PART 3: HUB_SendMessage (0x4bf0d2) and sensor hub task\n")
out.write("=" * 80 + "\n")

hub_addrs = ["0x4bf0d2", "0x4bf410", "0x4bf482", "0x4bf4f4"]
for addr_hex in hub_addrs:
    f = fm.getFunctionAt(A(addr_hex))
    if f:
        out.write("\n--- %s @ %s ---\n" % (f.getName(), f.getEntryPoint()))
        try:
            res = di.decompileFunction(f, 90, mon)
            if res and res.getDecompiledFunction():
                out.write(res.getDecompiledFunction().getC())
        except:
            pass
        out.write("\n")

# === Part 4: Find the sensor hub task function ===
# The queue is at *DAT_004bf584+0xc. Find what reads from this queue.
out.write("\n" + "=" * 80 + "\n")
out.write("PART 4: References to sensor hub globals (0x4bf580-0x4bf600)\n")
out.write("=" * 80 + "\n")

for addr_off in range(0x4bf580, 0x4bf600, 4):
    refs = refmgr.getReferencesTo(A("0x%x" % addr_off))
    for ref in refs:
        fa = ref.getFromAddress()
        fn = fm.getFunctionContaining(fa)
        if fn:
            out.write("  0x%x referenced by %s @ %s (from %s)\n" % (addr_off, fn.getName(), fn.getEntryPoint(), fa))

# === Part 5: Decompile functions in the sensor hub area (0x4bf000-0x4bf600) ===
out.write("\n" + "=" * 80 + "\n")
out.write("PART 5: ALL functions in sensor hub area (0x4bf000-0x4bf600)\n")
out.write("=" * 80 + "\n")

fn_iter = fm.getFunctions(A("0x4bf000"), True)
while fn_iter.hasNext():
    fn = fn_iter.next()
    if fn.getEntryPoint().getOffset() > 0x4bf600:
        break
    out.write("\n--- %s @ %s ---\n" % (fn.getName(), fn.getEntryPoint()))
    try:
        res = di.decompileFunction(fn, 90, mon)
        if res and res.getDecompiledFunction():
            c_code = res.getDecompiledFunction().getC()
            out.write(c_code[:4000])
        else:
            out.write("  FAILED\n")
    except Exception as e:
        out.write("  ERROR: %s\n" % e)
    out.write("\n")

# === Part 6: IMU driver functions in 0x4bbd00-0x4be000 area ===
out.write("\n" + "=" * 80 + "\n")
out.write("PART 6: IMU driver area functions (0x4bbd00-0x4be000)\n")
out.write("=" * 80 + "\n")

fn_iter = fm.getFunctions(A("0x4bbd00"), True)
while fn_iter.hasNext():
    fn = fn_iter.next()
    if fn.getEntryPoint().getOffset() > 0x4be000:
        break
    out.write("\n--- %s @ %s (size %d) ---\n" % (fn.getName(), fn.getEntryPoint(), fn.getBody().getNumAddresses()))
    # Just list, don't decompile all - too many
    called = fn.getCalledFunctions(mon)
    for cf in called:
        out.write("  calls %s @ %s\n" % (cf.getName(), cf.getEntryPoint()))

# === Part 7: Check the IMU chip driver area (0x529000-0x52d000) for task/interrupt patterns ===
out.write("\n" + "=" * 80 + "\n")
out.write("PART 7: IMU chip driver area functions (0x529000-0x52d000)\n")
out.write("=" * 80 + "\n")

fn_iter = fm.getFunctions(A("0x529000"), True)
while fn_iter.hasNext():
    fn = fn_iter.next()
    if fn.getEntryPoint().getOffset() > 0x52d000:
        break
    out.write("  %s @ %s (size %d)\n" % (fn.getName(), fn.getEntryPoint(), fn.getBody().getNumAddresses()))
    # List callees briefly
    called = fn.getCalledFunctions(mon)
    for cf in called:
        cfname = cf.getName()
        if any(kw in cfname.lower() for kw in ["spi", "i2c", "dma", "irq", "interrupt",
                "task", "queue", "sema", "mutex", "timer", "imu", "hub", "drv"]):
            out.write("    -> %s @ %s\n" % (cfname, cf.getEntryPoint()))

out.close()
print("Output -> " + outfile)
