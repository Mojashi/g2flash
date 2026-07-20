# -*- coding: utf-8 -*-
# Ghidra headless: deep-trace the SPI/I2C bus used by IMU chip driver.
# Starting from FUN_0052c544 and FUN_0052c55c, trace down to the actual
# peripheral register writes to identify SPI vs I2C, and find the DMA/IRQ handler
# that reads data and invokes the callback.
# Also search for the IMU chip model by looking at WHO_AM_I register reads.
# @category CFW
from ghidra.app.decompiler import DecompInterface
from ghidra.util.task import ConsoleTaskMonitor

args = getScriptArgs()
outfile = args[0] if len(args) > 0 else "/tmp/imu_spi_trace.txt"

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

# === Part 1: Deep decompile of FUN_0052c544 and FUN_0052c55c and ALL their callees ===
out.write("=" * 80 + "\n")
out.write("PART 1: Deep call tree decompilation from chip I/O functions\n")
out.write("=" * 80 + "\n")

seen = set()
def deep_decompile(fn, depth=0, max_depth=4):
    key = str(fn.getEntryPoint())
    if key in seen or depth > max_depth:
        return
    seen.add(key)
    indent = "  " * depth
    out.write("\n%s===== %s @ %s (depth %d) =====\n" % (indent, fn.getName(), fn.getEntryPoint(), depth))
    try:
        res = di.decompileFunction(fn, 90, mon)
        if res and res.getDecompiledFunction():
            c = res.getDecompiledFunction().getC()
            out.write(c)
        else:
            out.write("%s  FAILED\n" % indent)
    except Exception as e:
        out.write("%s  ERROR: %s\n" % (indent, e))
    out.write("\n")
    # Recurse into callees
    for cf in fn.getCalledFunctions(mon):
        deep_decompile(cf, depth + 1, max_depth)

for addr_hex in ["0x52c544", "0x52c55c"]:
    f = fm.getFunctionAt(A(addr_hex))
    if f is None:
        f = fm.getFunctionContaining(A(addr_hex))
    if f:
        deep_decompile(f, 0, 4)

# === Part 2: Search for SPI/I2C peripheral base addresses ===
# nRF52840 SPI peripheral addresses:
# SPIM0/SPIS0/TWIM0/TWIS0: 0x40003000
# SPIM1/SPIS1/TWIM1/TWIS1: 0x40004000
# SPIM2/SPIS2: 0x40023000
# SPIM3: 0x4002F000
# Look for these in the decompiled code and in memory references
out.write("\n" + "=" * 80 + "\n")
out.write("PART 2: SPI/I2C peripheral base addresses in code\n")
out.write("=" * 80 + "\n")

spi_bases = {
    0x40003000: "SPIM0/TWIM0",
    0x40004000: "SPIM1/TWIM1",
    0x40023000: "SPIM2",
    0x4002F000: "SPIM3",
}

for base, name in spi_bases.items():
    refs = refmgr.getReferencesTo(A("0x%x" % base))
    out.write("\nRefs to %s (0x%x):\n" % (name, base))
    for ref in refs:
        fa = ref.getFromAddress()
        fn = fm.getFunctionContaining(fa)
        fn_info = "%s @ %s" % (fn.getName(), fn.getEntryPoint()) if fn else "???"
        out.write("  from %s at %s\n" % (fn_info, fa))
    # Also check some register offsets
    for reg_off, reg_name in [(0x108, "EVENTS_END"), (0x148, "EVENTS_ENDRX"),
                               (0x110, "EVENTS_DONE"), (0x508, "FREQUENCY"),
                               (0x534, "TXD.PTR"), (0x538, "TXD.MAXCNT"),
                               (0x544, "RXD.PTR"), (0x548, "RXD.MAXCNT"),
                               (0x010, "TASKS_START"), (0x01C, "TASKS_STOP"),
                               (0x524, "CONFIG"), (0x500, "ENABLE")]:
        reg_addr = base + reg_off
        refs = refmgr.getReferencesTo(A("0x%x" % reg_addr))
        for ref in refs:
            fa = ref.getFromAddress()
            fn = fm.getFunctionContaining(fa)
            fn_info = "%s @ %s" % (fn.getName(), fn.getEntryPoint()) if fn else "???"
            out.write("  %s.%s (0x%x) from %s at %s\n" % (name, reg_name, reg_addr, fn_info, fa))

# === Part 3: Find the DMA completion handler / SPI event handler ===
# Look for functions that:
# 1. Read EVENTS_END or EVENTS_ENDRX
# 2. Call through a function pointer (the callback)
out.write("\n" + "=" * 80 + "\n")
out.write("PART 3: Search for SPI/I2C interrupt handlers\n")
out.write("=" * 80 + "\n")

# Check vector table or NVIC handlers
# nRF52840 IRQ numbers: SPIM0=3, SPIM1=4, SPIM2=35, SPIM3=47
# Vector table entries would be at addresses:
# In Cortex-M, vectors start at address 0 (or wherever VTOR points)
# Let's search for functions that reference SPI event registers AND have indirect calls

# Search for functions that reference the IMU driver context AND SPI peripherals
out.write("Looking for functions referencing both SPI and IMU driver context...\n")
imu_ctx_refs = set()
for addr_off in range(0x4bbea0, 0x4bbf20, 4):
    refs = refmgr.getReferencesTo(A("0x%x" % addr_off))
    for ref in refs:
        fn = fm.getFunctionContaining(ref.getFromAddress())
        if fn:
            imu_ctx_refs.add(str(fn.getEntryPoint()))

spi_refs = set()
for base in spi_bases:
    for reg_off in [0x108, 0x148, 0x010, 0x500]:
        refs = refmgr.getReferencesTo(A("0x%x" % (base + reg_off)))
        for ref in refs:
            fn = fm.getFunctionContaining(ref.getFromAddress())
            if fn:
                spi_refs.add(str(fn.getEntryPoint()))

overlap = imu_ctx_refs & spi_refs
out.write("Functions referencing BOTH IMU ctx and SPI: %s\n" % overlap)
for fn_addr in overlap:
    fn = fm.getFunctionAt(A(fn_addr))
    if fn:
        out.write("\n--- %s @ %s ---\n" % (fn.getName(), fn.getEntryPoint()))
        try:
            res = di.decompileFunction(fn, 90, mon)
            if res and res.getDecompiledFunction():
                out.write(res.getDecompiledFunction().getC())
        except:
            pass

# === Part 4: Decompile the callers of FUN_0052c544/0052c55c ===
out.write("\n" + "=" * 80 + "\n")
out.write("PART 4: Callers of FUN_0052c544 and FUN_0052c55c\n")
out.write("=" * 80 + "\n")

for addr_hex in ["0x52c544", "0x52c55c"]:
    f = fm.getFunctionAt(A(addr_hex))
    if not f:
        continue
    refs = refmgr.getReferencesTo(f.getEntryPoint())
    for ref in refs:
        fa = ref.getFromAddress()
        cfn = fm.getFunctionContaining(fa)
        if cfn:
            out.write("\n--- Caller of %s: %s @ %s ---\n" % (addr_hex, cfn.getName(), cfn.getEntryPoint()))
            try:
                res = di.decompileFunction(cfn, 90, mon)
                if res and res.getDecompiledFunction():
                    out.write(res.getDecompiledFunction().getC())
            except:
                pass
            out.write("\n")

out.close()
print("Output -> " + outfile)
