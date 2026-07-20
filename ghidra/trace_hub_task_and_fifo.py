# -*- coding: utf-8 -*-
# Trace: 1) hub task that dequeues messages (consumer of xQueue at 0x20003640+0xc)
# 2) ALL functions in IMU driver range 0x4bc000-0x4bcc00 (to find FIFO read wrapper)
# 3) Functions at/near 0x4bbc68 (driver bus functions)
# 4) The interrupt handler for BHI260 (GPIO/EXTI interrupt that triggers FIFO read)
# @category CFW
from ghidra.app.decompiler import DecompInterface
from ghidra.util.task import ConsoleTaskMonitor
import struct as st_mod
import codecs

args = getScriptArgs()
outfile = args[0] if len(args) > 0 else "/tmp/trace_hub_task_fifo.txt"

fm = currentProgram.getFunctionManager()
af = currentProgram.getAddressFactory()
mem = currentProgram.getMemory()
refmgr = currentProgram.getReferenceManager()
di = DecompInterface()
di.openProgram(currentProgram)
mon = ConsoleTaskMonitor()
def A(h): return af.getAddress(h)

out = codecs.open(outfile, "w", "utf-8")

def decompile_func(addr_str, label=""):
    a = A(addr_str)
    f = fm.getFunctionAt(a)
    if f is None:
        f = fm.getFunctionContaining(a)
    if f is None:
        out.write(u"\n--- %s %s: no function ---\n" % (label, addr_str))
        return None
    out.write(u"\n--- %s %s @ %s (size %d) ---\n" % (label, f.getName(), f.getEntryPoint(), f.getBody().getNumAddresses()))
    try:
        res = di.decompileFunction(f, 120, mon)
        if res and res.getDecompiledFunction():
            out.write(res.getDecompiledFunction().getC())
        else:
            msg = res.getErrorMessage() if res else "null"
            out.write(u"decompile failed: %s\n" % msg)
    except Exception as e:
        out.write(u"exception: %s\n" % e)
    out.write(u"\n")
    return f

# === PART 1: Enumerate ALL functions in 0x4bc000-0x4bcc00 (IMU driver mid-layer) ===
out.write(u"=" * 80 + u"\n")
out.write(u"PART 1: All functions 0x4bc000-0x4bcc54 with callee/caller info\n")
out.write(u"=" * 80 + u"\n")

fn_iter = fm.getFunctions(A("0x4bc000"), True)
count = 0
interesting_fns = []
while fn_iter.hasNext() and count < 100:
    fn = fn_iter.next()
    ep = fn.getEntryPoint().getOffset()
    if ep > 0x4bcc54:
        break
    count += 1
    callees = list(fn.getCalledFunctions(mon))
    callee_names = [c.getName() for c in callees]
    callers = []
    refs = refmgr.getReferencesTo(fn.getEntryPoint())
    for ref in refs:
        if ref.getReferenceType().isCall():
            caller = fm.getFunctionContaining(ref.getFromAddress())
            if caller:
                callers.append(caller)

    has_bhi = any("bhi260" in n or "fifo" in n.lower() for n in callee_names)
    no_callers = len(callers) == 0

    marker = ""
    if has_bhi:
        marker += " [CALLS_BHI]"
    if no_callers:
        marker += " [NO_CALLERS]"

    out.write(u"\n%s @ 0x%x (size %d)%s\n" % (fn.getName(), ep, fn.getBody().getNumAddresses(), marker))
    for cf in callees:
        out.write(u"  -> %s @ %s\n" % (cf.getName(), cf.getEntryPoint()))
    for caller in callers:
        out.write(u"  <- %s @ %s\n" % (caller.getName(), caller.getEntryPoint()))

    if has_bhi or (no_callers and fn.getBody().getNumAddresses() > 50):
        interesting_fns.append(fn)

# === PART 2: Decompile interesting functions (BHI260-calling or no-caller large) ===
out.write(u"\n\n" + u"=" * 80 + u"\n")
out.write(u"PART 2: Decompile interesting functions\n")
out.write(u"=" * 80 + u"\n")

for fn in interesting_fns[:10]:
    out.write(u"\n--- %s @ %s ---\n" % (fn.getName(), fn.getEntryPoint()))
    try:
        res = di.decompileFunction(fn, 120, mon)
        if res and res.getDecompiledFunction():
            out.write(res.getDecompiledFunction().getC()[:4000])
    except Exception as e:
        out.write(u"error: %s\n" % e)
    out.write(u"\n")

# === PART 3: Functions near bus read (0x4bbc00-0x4bbcc6) ===
out.write(u"\n\n" + u"=" * 80 + u"\n")
out.write(u"PART 3: Functions in 0x4bbc00-0x4bbcc6 (bus layer)\n")
out.write(u"=" * 80 + u"\n")

fn_iter = fm.getFunctions(A("0x4bbc00"), True)
count = 0
while fn_iter.hasNext() and count < 10:
    fn = fn_iter.next()
    ep = fn.getEntryPoint().getOffset()
    if ep >= 0x4bbcc6:
        break
    count += 1
    decompile_func("0x%x" % ep, "bus_area")

# === PART 4: FUN_00448b8c callers (xQueueReceive callers = queue consumers) ===
out.write(u"\n\n" + u"=" * 80 + u"\n")
out.write(u"PART 4: Callers of FUN_00448b8c (xQueueReceive) - queue consumers\n")
out.write(u"=" * 80 + u"\n")

refs = refmgr.getReferencesTo(A("0x448b8c"))
for ref in refs:
    if ref.getReferenceType().isCall():
        fn = fm.getFunctionContaining(ref.getFromAddress())
        if fn:
            out.write(u"  %s @ %s\n" % (fn.getName(), fn.getEntryPoint()))

# === PART 5: Search for 0x20003640 (hub context base) to find hub task ===
out.write(u"\n\n" + u"=" * 80 + u"\n")
out.write(u"PART 5: References to hub context (0x20003640)\n")
out.write(u"=" * 80 + u"\n")

# Direct refs
refs = refmgr.getReferencesTo(A("0x20003640"))
for ref in refs:
    fn = fm.getFunctionContaining(ref.getFromAddress())
    fn_name = fn.getName() if fn else "???"
    out.write(u"  direct ref from %s in %s\n" % (ref.getFromAddress(), fn_name))

# Binary search
needle = st_mod.pack("<I", 0x20003640)
blocks = mem.getBlocks()
for block in blocks:
    if not block.isInitialized():
        continue
    start = block.getStart()
    end = block.getEnd()
    size = end.subtract(start) + 1
    if size > 0x400000:
        size = 0x400000
    try:
        data = bytearray(size)
        block.getBytes(start, data)
        pos = 0
        while True:
            idx = bytes(data).find(bytes(needle), pos)
            if idx < 0:
                break
            found_addr = start.add(idx)
            fn = fm.getFunctionContaining(found_addr)
            fn_info = u"%s @ %s" % (fn.getName(), fn.getEntryPoint()) if fn else u"(data/literal pool)"
            out.write(u"  binary: 0x%s in %s\n" % (found_addr, fn_info))
            pos = idx + 4
    except:
        pass

# === PART 6: Search for "hub_task" or "sensor_task" by looking at function names ===
out.write(u"\n\n" + u"=" * 80 + u"\n")
out.write(u"PART 6: Functions with 'hub' or 'sensor' in name (task entry points)\n")
out.write(u"=" * 80 + u"\n")

fn_iter = fm.getFunctions(True)
for fn in fn_iter:
    name = fn.getName().lower()
    if "hub" in name or "sensor_task" in name or "imu_task" in name:
        out.write(u"  %s @ %s (size %d)\n" % (fn.getName(), fn.getEntryPoint(), fn.getBody().getNumAddresses()))

# === PART 7: Find who starts the FIFO read via BHI260 INT pin ===
# Look for GPIO/EXTI interrupt handlers and BHI260-related interrupt config
out.write(u"\n\n" + u"=" * 80 + u"\n")
out.write(u"PART 7: Look for BHI260 interrupt handler (GPIO/EXTI)\n")
out.write(u"=" * 80 + u"\n")

# Search for functions with "imu" or "int" or "exti" or "gpio_irq" in name
fn_iter = fm.getFunctions(True)
for fn in fn_iter:
    name = fn.getName().lower()
    if ("imu" in name and ("int" in name or "irq" in name or "isr" in name)) or \
       ("bhi" in name and "int" in name) or \
       name.startswith("exti") or \
       ("gpio" in name and "irq" in name):
        out.write(u"  %s @ %s\n" % (fn.getName(), fn.getEntryPoint()))

# Also look for the I2C DMA interrupt handler
fn_iter = fm.getFunctions(True)
for fn in fn_iter:
    name = fn.getName().lower()
    if "i2c" in name and ("dma" in name or "irq" in name or "handler" in name):
        out.write(u"  %s @ %s\n" % (fn.getName(), fn.getEntryPoint()))

out.close()
print("done -> " + outfile)
