# -*- coding: utf-8 -*-
# Ghidra headless: find who invokes the DRV_IMUDataParserCallback via indirect call.
# The callback is at slot [6] of the driver context (offset +0x18 bytes from ctx base).
# The driver context pointer is stored at 0x4bbeb8.
# We search for:
#   1. Any code that loads from driver_ctx + 0x18 (byte offset 24) and calls through it
#   2. Any code that references 0x4bbec8 (the actual address holding the callback pointer)
#   3. Any code that references 0x4bbeb8 (the driver context base pointer)
#   4. Any reference to 0x4bdd8c (the callback function address) beyond the table write
# Also decompile any functions found.
# @category CFW
from ghidra.app.decompiler import DecompInterface
from ghidra.util.task import ConsoleTaskMonitor
from ghidra.program.model.symbol import RefType
import struct

args = getScriptArgs()
outfile = args[0] if len(args) > 0 else "/tmp/imu_callback_trace.txt"

fm = currentProgram.getFunctionManager()
af = currentProgram.getAddressFactory()
mem = currentProgram.getMemory()
listing = currentProgram.getListing()
refmgr = currentProgram.getReferenceManager()
di = DecompInterface()
di.openProgram(currentProgram)
mon = ConsoleTaskMonitor()
def A(h): return af.getAddress(h)

out = open(outfile, "w")

# === Part 1: Find all references to 0x4bbeb8 (driver context pointer global) ===
out.write("=" * 80 + "\n")
out.write("PART 1: References to g_imu_driver_ctx_ptr (0x4bbeb8)\n")
out.write("=" * 80 + "\n")
target_addrs = [0x4bbeb8, 0x4bbec8, 0x4bdd8c]
for tgt in target_addrs:
    refs = refmgr.getReferencesTo(A("0x%x" % tgt))
    out.write("\nRefs to 0x%x:\n" % tgt)
    count = 0
    for ref in refs:
        fa = ref.getFromAddress()
        fn = fm.getFunctionContaining(fa)
        fn_name = fn.getName() if fn else "???"
        fn_entry = fn.getEntryPoint() if fn else "???"
        out.write("  from 0x%s in %s (entry 0x%s), type=%s\n" % (fa, fn_name, fn_entry, ref.getReferenceType()))
        count += 1
        # Decompile the containing function
        if fn:
            try:
                res = di.decompileFunction(fn, 90, mon)
                if res and res.getDecompiledFunction():
                    out.write("  --- decompilation of %s ---\n" % fn.getName())
                    out.write(res.getDecompiledFunction().getC())
                    out.write("\n  --- end ---\n")
            except Exception as e:
                out.write("  decompile error: %s\n" % e)
    if count == 0:
        out.write("  (none)\n")

# === Part 2: Search for LDR instructions that load from [reg + 0x18] ===
# This is more of a pattern search. In ARM Thumb, loading from [reg, #0x18]
# would be encoded with specific bits. Let's scan for BLX/BL to indirect targets
# after loading from +0x18 offset.
out.write("\n" + "=" * 80 + "\n")
out.write("PART 2: Searching for indirect calls via driver_ctx+0x18\n")
out.write("=" * 80 + "\n")

# Actually, let's search for code that reads from the memory around the callback table.
# The table is at *(0x4bbeb8), and the callback is at offset +0x18 from that.
# But let's also check: is 0x4bbec8 = 0x4bbeb8 + 0x10? No, 0x4bbec8 - 0x4bbeb8 = 0x10.
# Wait, the user said "callback table base is at *(u32*)0x4bbeb8 (= driver context)"
# and "callback is at slot [6] (offset +0x18 in int* arithmetic = byte offset +24)".
# So the callback address is at *(*(u32*)0x4bbeb8 + 24).
# But also says "registered as a callback at address 0x4bbec8 in a static table".
# 0x4bbec8 = 0x4bbeb8 + 0x10 (16 bytes). So the static table at 0x4bbeb8 has
# the callback pointer at offset 0x10?
# Actually, let me just read the memory around 0x4bbeb8 to understand the layout.

out.write("\nMemory dump around 0x4bbeb8 (callback table area):\n")
for off in range(0, 0x40, 4):
    addr = 0x4bbeb8 + off
    try:
        val = mem.getInt(A("0x%x" % addr))
        out.write("  0x%x: 0x%08x\n" % (addr, val & 0xffffffff))
    except:
        out.write("  0x%x: (unreadable)\n" % addr)

# === Part 3: Search for all functions that reference addresses in range 0x4bbeb0-0x4bbf00 ===
out.write("\n" + "=" * 80 + "\n")
out.write("PART 3: All references to addresses in 0x4bbeb0-0x4bbf00 range\n")
out.write("=" * 80 + "\n")
seen_fns = set()
for addr_off in range(0x4bbeb0, 0x4bbf00, 4):
    refs = refmgr.getReferencesTo(A("0x%x" % addr_off))
    for ref in refs:
        fa = ref.getFromAddress()
        fn = fm.getFunctionContaining(fa)
        if fn:
            fn_key = str(fn.getEntryPoint())
            if fn_key not in seen_fns:
                seen_fns.add(fn_key)
                out.write("\nFunction %s @ %s references 0x%x\n" % (fn.getName(), fn.getEntryPoint(), addr_off))

# === Part 4: Decompile the function at 0x4bdd8c to see its full code ===
out.write("\n" + "=" * 80 + "\n")
out.write("PART 4: Decompile DRV_IMUDataParserCallback (0x4bdd8c)\n")
out.write("=" * 80 + "\n")
f = fm.getFunctionAt(A("0x4bdd8c"))
if f:
    res = di.decompileFunction(f, 90, mon)
    if res and res.getDecompiledFunction():
        out.write(res.getDecompiledFunction().getC())
    else:
        out.write("decompile failed\n")

# === Part 5: Search ENTIRE code for references to the callback function address ===
# The callback 0x4bdd8c might be stored as a constant in code (e.g., MOV reg, #0x4bdd8c)
# In Thumb2, this would be MOVW/MOVT pair or LDR from literal pool.
# Search for the 32-bit value 0x004bdd8c (little-endian: 8c dd 4b 00) in .text and .rodata
out.write("\n" + "=" * 80 + "\n")
out.write("PART 5: Binary search for 0x4bdd8c in code/rodata\n")
out.write("=" * 80 + "\n")
target_bytes = bytearray([0x8c, 0xdd, 0x4b, 0x00])  # little-endian
# But wait - with base 0x39E680, the actual runtime address would be different.
# Ghidra addresses are already rebased. Let's search for the value as it appears.
# In Ghidra, addresses are as loaded. The base is 0x39E680, meaning the binary's
# load address is 0x39E680. But functions at 0x4bdd8c means that's already the
# rebased address. Let's search for this value in memory.
search_val = 0x004bdd8d  # Thumb bit set for function pointer
out.write("Searching for 0x%08x (Thumb pointer to callback)...\n" % search_val)
import struct as st_mod
needle = st_mod.pack("<I", search_val)
# Also search without thumb bit
needle2 = st_mod.pack("<I", 0x004bdd8c)

blocks = mem.getBlocks()
for block in blocks:
    if not block.isInitialized():
        continue
    start = block.getStart()
    end = block.getEnd()
    size = end.subtract(start) + 1
    if size > 0x200000:
        size = 0x200000  # cap at 2MB per block
    try:
        data = bytearray(size)
        got = block.getBytes(start, data)
        for n_bytes in [needle, needle2]:
            pos = 0
            while True:
                idx = bytes(data).find(bytes(n_bytes), pos)
                if idx < 0:
                    break
                found_addr = start.add(idx)
                fn = fm.getFunctionContaining(found_addr)
                fn_info = "%s @ %s" % (fn.getName(), fn.getEntryPoint()) if fn else "no function"
                out.write("  Found at 0x%s (block %s) -> %s\n" % (found_addr, block.getName(), fn_info))
                pos = idx + 1
    except Exception as e:
        out.write("  Error scanning block %s: %s\n" % (block.getName(), e))

# === Part 6: Look for the SPI/I2C DMA interrupt handler that would call through the table ===
# Common pattern: interrupt reads driver_ctx, then calls ctx->callback(ctx->callback_data)
# Let's find all functions that have indirect calls (BLX reg) and also reference 0x4bbeb8
out.write("\n" + "=" * 80 + "\n")
out.write("PART 6: Functions with both indirect calls and IMU driver context refs\n")
out.write("=" * 80 + "\n")

# Get all functions that reference anything in the driver context area
driver_ctx_refs = set()
for addr_off in range(0x4bbea0, 0x4bbf20, 4):
    refs = refmgr.getReferencesTo(A("0x%x" % addr_off))
    for ref in refs:
        fn = fm.getFunctionContaining(ref.getFromAddress())
        if fn:
            driver_ctx_refs.add(str(fn.getEntryPoint()))

out.write("Functions referencing driver context area (0x4bbea0-0x4bbf20):\n")
for fn_addr in sorted(driver_ctx_refs):
    fn = fm.getFunctionAt(A(fn_addr))
    if fn:
        out.write("  %s @ %s\n" % (fn.getName(), fn.getEntryPoint()))
        # Decompile each
        try:
            res = di.decompileFunction(fn, 90, mon)
            if res and res.getDecompiledFunction():
                c_code = res.getDecompiledFunction().getC()
                # Check if the decompiled code contains indirect call patterns
                if "(*" in c_code or "call" in c_code.lower():
                    out.write("    [HAS INDIRECT CALL PATTERN]\n")
                    out.write(c_code[:3000])
                    out.write("\n")
        except:
            pass

out.close()
print("Output -> " + outfile)
