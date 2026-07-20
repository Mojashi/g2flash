# Ghidra headless: dump ROM table at given address range as 32-bit pointers,
# then find xrefs to the sensor state struct fields.
# Usage: -postScript dump_rom_table_and_xrefs.py "0x4bbe98,0x4bbeb4,0x200730c0" /tmp/rom_table.txt
# @category CFW
from ghidra.program.model.symbol import ReferenceManager
import codecs

args = getScriptArgs()
params = args[0].split(",")
table_start = int(params[0], 16)
table_end = int(params[1], 16)
sensor_state = int(params[2], 16) if len(params) > 2 else None
outfile = args[1] if len(args) > 1 else "/tmp/rom_table.txt"

mem = currentProgram.getMemory()
af = currentProgram.getAddressFactory()
fm = currentProgram.getFunctionManager()
rm = currentProgram.getReferenceManager()
listing = currentProgram.getListing()

out = codecs.open(outfile, "w", "utf-8")

# 1. Dump ROM table as 32-bit little-endian values
out.write(u"=== ROM TABLE 0x%x - 0x%x ===\n" % (table_start, table_end))
addr = table_start
idx = 0
func_ptrs = []
while addr < table_end:
    a = af.getAddress("0x%x" % addr)
    b0 = mem.getByte(a) & 0xff
    b1 = mem.getByte(af.getAddress("0x%x" % (addr+1))) & 0xff
    b2 = mem.getByte(af.getAddress("0x%x" % (addr+2))) & 0xff
    b3 = mem.getByte(af.getAddress("0x%x" % (addr+3))) & 0xff
    val = b0 | (b1 << 8) | (b2 << 16) | (b3 << 24)
    # ARM Thumb: clear bit 0 for display
    val_clean = val & 0xFFFFFFFE
    f = fm.getFunctionAt(af.getAddress("0x%x" % val_clean))
    fname = f.getName() if f else "???"
    out.write(u"  [%d] 0x%08x -> 0x%08x  %s\n" % (idx, addr, val_clean, fname))
    func_ptrs.append(val_clean)
    addr += 4
    idx += 1

# 2. For each function pointer, find all callers (xrefs TO)
out.write(u"\n=== XREFS TO FIFO HANDLER FUNCTIONS ===\n")
for ptr in func_ptrs:
    a = af.getAddress("0x%x" % ptr)
    f = fm.getFunctionAt(a)
    fname = f.getName() if f else "0x%x" % ptr
    out.write(u"\n--- %s (0x%x) ---\n" % (fname, ptr))
    refs = rm.getReferencesTo(a)
    count = 0
    for ref in refs:
        src = ref.getFromAddress()
        src_func = fm.getFunctionContaining(src)
        src_name = src_func.getName() if src_func else "???"
        out.write(u"  from 0x%s in %s  type=%s\n" % (src, src_name, ref.getReferenceType()))
        count += 1
    if count == 0:
        out.write(u"  (no xrefs found)\n")

# 3. Find references to the sensor state struct address
if sensor_state:
    out.write(u"\n=== XREFS TO SENSOR STATE 0x%x ===\n" % sensor_state)
    a = af.getAddress("0x%x" % sensor_state)
    refs = rm.getReferencesTo(a)
    count = 0
    for ref in refs:
        src = ref.getFromAddress()
        src_func = fm.getFunctionContaining(src)
        src_name = src_func.getName() if src_func else "???"
        out.write(u"  from 0x%s in %s  type=%s\n" % (src, src_name, ref.getReferenceType()))
        count += 1
    if count == 0:
        out.write(u"  (no direct xrefs found - may be loaded via pointer chain)\n")

out.close()
print("done -> " + outfile)
