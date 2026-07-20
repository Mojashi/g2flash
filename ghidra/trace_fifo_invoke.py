# -*- coding: utf-8 -*-
# Ghidra headless: Find who invokes bhi260_fifo_read and bhi260_fifo_batch_dispatch.
# These have no direct callers so must be invoked via function pointers.
# Search: 1) binary for their Thumb addresses 2) decompile the containing functions
# Also trace hub_open->hub_send_message->bhi260_full_sensor_reconfig chain.
# @category CFW
from ghidra.app.decompiler import DecompInterface
from ghidra.util.task import ConsoleTaskMonitor
import struct as st_mod
import codecs

args = getScriptArgs()
outfile = args[0] if len(args) > 0 else "/tmp/trace_fifo_invoke.txt"

fm = currentProgram.getFunctionManager()
af = currentProgram.getAddressFactory()
mem = currentProgram.getMemory()
refmgr = currentProgram.getReferenceManager()
listing = currentProgram.getListing()
di = DecompInterface()
di.openProgram(currentProgram)
mon = ConsoleTaskMonitor()
def A(h): return af.getAddress(h)

out = codecs.open(outfile, "w", "utf-8")

# === PART 1: Search for bhi260_fifo_read (0x528f70) and bhi260_fifo_batch_dispatch (0x528f9a) ===
# as stored function pointers (with Thumb bit set: 0x528f71, 0x528f9b)
targets = {
    "bhi260_fifo_read": 0x00528f71,
    "bhi260_fifo_batch_dispatch": 0x00528f9b,
    "bhi260_full_sensor_reconfig": 0x0052918b,
    "bhi260_parse_fifo_standard": 0x00527fd5,
    "bhi260_parse_fifo_fullres": 0x00528dbb,
    "DRV_IMUDataParserCallback": 0x004bdd8d,
}

out.write(u"=" * 80 + u"\n")
out.write(u"PART 1: Binary search for function pointer storage\n")
out.write(u"=" * 80 + u"\n")

blocks = mem.getBlocks()
block_data = {}
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
        block_data[block.getName()] = (start, data)
    except Exception as e:
        out.write(u"  Error reading block %s: %s\n" % (block.getName(), e))

for name, addr in targets.items():
    needle = st_mod.pack("<I", addr)
    out.write(u"\n--- %s (0x%08x) ---\n" % (name, addr))
    found_any = False
    for bname, (bstart, bdata) in block_data.items():
        pos = 0
        while True:
            idx = bytes(bdata).find(bytes(needle), pos)
            if idx < 0:
                break
            found_addr = bstart.add(idx)
            fn = fm.getFunctionContaining(found_addr)
            fn_info = u"%s @ %s" % (fn.getName(), fn.getEntryPoint()) if fn else u"(no function)"
            out.write(u"  Found at 0x%s (block %s) in %s\n" % (found_addr, bname, fn_info))
            found_any = True
            pos = idx + 4
    if not found_any:
        # Also try without Thumb bit
        needle2 = st_mod.pack("<I", addr & 0xFFFFFFFE)
        for bname, (bstart, bdata) in block_data.items():
            pos = 0
            while True:
                idx = bytes(bdata).find(bytes(needle2), pos)
                if idx < 0:
                    break
                found_addr = bstart.add(idx)
                fn = fm.getFunctionContaining(found_addr)
                fn_info = u"%s @ %s" % (fn.getName(), fn.getEntryPoint()) if fn else u"(no function)"
                out.write(u"  Found (no-thumb) at 0x%s (block %s) in %s\n" % (found_addr, bname, fn_info))
                found_any = True
                pos = idx + 4
    if not found_any:
        out.write(u"  NOT FOUND in any block\n")

# === PART 2: Decompile functions that store bhi260_fifo_read/batch_dispatch ===
# Based on Part 1 results, decompile containing functions
out.write(u"\n\n" + u"=" * 80 + u"\n")
out.write(u"PART 2: Decompile key functions in FIFO management area\n")
out.write(u"=" * 80 + u"\n")

# Decompile functions near the FIFO code (0x527e00-0x529300)
key_addrs = [
    "0x527e6c",   # called in drv_imu_init (likely bhi260_chip_init)
    "0x4bbc69",   # driver_ctx[0] - bus read
    "0x4bbca3",   # driver_ctx[1] - bus write
    "0x4a7125",   # driver_ctx[3] - thread/task posting
    "0x4bf408",   # called at start of hub_open
]

for addr_str in key_addrs:
    a = A(addr_str)
    f = fm.getFunctionAt(a)
    if f is None:
        f = fm.getFunctionContaining(a)
    if f is None:
        out.write(u"\n--- %s: no function ---\n" % addr_str)
        continue
    out.write(u"\n--- %s @ %s (size %d) ---\n" % (f.getName(), f.getEntryPoint(), f.getBody().getNumAddresses()))
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

# === PART 3: hub_send_message and what it does ===
out.write(u"\n\n" + u"=" * 80 + u"\n")
out.write(u"PART 3: hub_send_message and hub task handling\n")
out.write(u"=" * 80 + u"\n")

# Find hub_send_message by looking at what hub_open calls
hub_open_f = fm.getFunctionAt(A("0x4bf410"))
if hub_open_f:
    out.write(u"\nhub_open callees:\n")
    for cf in hub_open_f.getCalledFunctions(mon):
        out.write(u"  -> %s @ %s\n" % (cf.getName(), cf.getEntryPoint()))

# Search for references to bhi260_full_sensor_reconfig (0x52918a)
out.write(u"\n\nCallers of bhi260_full_sensor_reconfig (0x52918a):\n")
f_reconfig = fm.getFunctionAt(A("0x52918a"))
if f_reconfig:
    refs = refmgr.getReferencesTo(f_reconfig.getEntryPoint())
    for ref in refs:
        if ref.getReferenceType().isCall():
            fn = fm.getFunctionContaining(ref.getFromAddress())
            if fn:
                out.write(u"  <- %s @ %s (from %s)\n" % (fn.getName(), fn.getEntryPoint(), ref.getFromAddress()))
                # Decompile the caller
                try:
                    res = di.decompileFunction(fn, 120, mon)
                    if res and res.getDecompiledFunction():
                        out.write(res.getDecompiledFunction().getC()[:4000])
                except Exception as e:
                    out.write(u"  decompile error: %s\n" % e)
                out.write(u"\n")
    # Also look for indirect references via Thumb address
    out.write(u"\n  Also: indirect refs:\n")
    refs2 = refmgr.getReferencesTo(A("0x52918b"))
    for ref in refs2:
        fn = fm.getFunctionContaining(ref.getFromAddress())
        fn_name = fn.getName() if fn else "???"
        out.write(u"    from %s in %s\n" % (ref.getFromAddress(), fn_name))

# === PART 4: Look for the IMU timer/periodic FIFO read mechanism ===
out.write(u"\n\n" + u"=" * 80 + u"\n")
out.write(u"PART 4: IMU FIFO periodic read mechanism\n")
out.write(u"=" * 80 + u"\n")

# The sensor state struct at 0x200730c0 - search for refs to it
out.write(u"\nReferences to 0x200730c0 (sensor state struct):\n")
refs = refmgr.getReferencesTo(A("0x200730c0"))
for ref in refs:
    fn = fm.getFunctionContaining(ref.getFromAddress())
    fn_name = fn.getName() if fn else "???"
    out.write(u"  from %s in %s type=%s\n" % (ref.getFromAddress(), fn_name, ref.getReferenceType()))

# Also search for 0x200730c0 as a 32-bit value in memory
out.write(u"\nBinary search for 0x200730c0 as stored constant:\n")
needle = st_mod.pack("<I", 0x200730c0)
for bname, (bstart, bdata) in block_data.items():
    pos = 0
    while True:
        idx = bytes(bdata).find(bytes(needle), pos)
        if idx < 0:
            break
        found_addr = bstart.add(idx)
        fn = fm.getFunctionContaining(found_addr)
        fn_info = u"%s @ %s" % (fn.getName(), fn.getEntryPoint()) if fn else u"(no function / data)"
        out.write(u"  0x%s (%s) -> %s\n" % (found_addr, bname, fn_info))
        pos = idx + 4

# Also look for 0x20072fb0 (the driver_ctx base)
out.write(u"\nBinary search for 0x20072fb0 (driver_ctx base):\n")
needle = st_mod.pack("<I", 0x20072fb0)
for bname, (bstart, bdata) in block_data.items():
    pos = 0
    while True:
        idx = bytes(bdata).find(bytes(needle), pos)
        if idx < 0:
            break
        found_addr = bstart.add(idx)
        fn = fm.getFunctionContaining(found_addr)
        fn_info = u"%s @ %s" % (fn.getName(), fn.getEntryPoint()) if fn else u"(no function / data)"
        out.write(u"  0x%s (%s) -> %s\n" % (found_addr, bname, fn_info))
        pos = idx + 4

out.close()
print("done -> " + outfile)
