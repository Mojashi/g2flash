# -*- coding: utf-8 -*-
# Final chain trace:
# 1) Function BEFORE 0x4bcb54 (likely the real entry that contains DRV_IMUSetSensorParameters)
# 2) FUN_0048b7be (hub context init at 0x20003640)
# 3) FUN_00533b2a (queue consumer - potential sensor hub task)
# 4) Decompile range 0x4bc800-0x4bcc54 to find the real function boundary
# 5) Look for function containing bhi260_fifo_read call via decompile range
# @category CFW
from ghidra.app.decompiler import DecompInterface
from ghidra.util.task import ConsoleTaskMonitor
import codecs

args = getScriptArgs()
outfile = args[0] if len(args) > 0 else "/tmp/trace_final_chain.txt"

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

def decompile_at(addr_str, label=""):
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
    # Show callees
    out.write(u"  Callees:\n")
    for cf in f.getCalledFunctions(mon):
        out.write(u"    -> %s @ %s\n" % (cf.getName(), cf.getEntryPoint()))
    out.write(u"  Callers:\n")
    refs = refmgr.getReferencesTo(f.getEntryPoint())
    for ref in refs:
        if ref.getReferenceType().isCall():
            caller = fm.getFunctionContaining(ref.getFromAddress())
            if caller:
                out.write(u"    <- %s @ %s\n" % (caller.getName(), caller.getEntryPoint()))
    out.write(u"\n")
    return f

# === PART 1: Function BEFORE 0x4bcb54 ===
out.write(u"=" * 80 + u"\n")
out.write(u"PART 1: Functions immediately before 0x4bcb54\n")
out.write(u"=" * 80 + u"\n")

# Find the function that ends just before 0x4bcb54
fn_iter = fm.getFunctions(A("0x4bba00"), True)
prev_fn = None
while fn_iter.hasNext():
    fn = fn_iter.next()
    ep = fn.getEntryPoint().getOffset()
    if ep >= 0x4bcb54:
        break
    prev_fn = fn

if prev_fn:
    out.write(u"\nFunction just before 0x4bcb54: %s @ %s (size %d, ends at ~0x%x)\n" % (
        prev_fn.getName(), prev_fn.getEntryPoint(), prev_fn.getBody().getNumAddresses(),
        prev_fn.getEntryPoint().getOffset() + prev_fn.getBody().getNumAddresses()))
    decompile_at(str(prev_fn.getEntryPoint()), "prev_func")

# Also check: is there undefined code between prev_fn end and 0x4bcb54?
if prev_fn:
    end_offset = prev_fn.getEntryPoint().getOffset() + prev_fn.getBody().getNumAddresses()
    out.write(u"\nGap between prev function end (0x%x) and FUN_004bcb54 (0x4bcb54): %d bytes\n" % (
        end_offset, 0x4bcb54 - end_offset))
    # Try to create/find functions in the gap
    for addr in range(end_offset, 0x4bcb54, 2):
        f = fm.getFunctionAt(A("0x%x" % addr))
        if f:
            out.write(u"  Function at 0x%x: %s\n" % (addr, f.getName()))
            break
        f = fm.getFunctionContaining(A("0x%x" % addr))
        if f:
            out.write(u"  0x%x is inside %s @ %s\n" % (addr, f.getName(), f.getEntryPoint()))
            break

# === PART 2: FUN_0048b7be - hub context init ===
out.write(u"\n\n" + u"=" * 80 + u"\n")
out.write(u"PART 2: FUN_0048b7be (references hub context 0x20003640)\n")
out.write(u"=" * 80 + u"\n")

decompile_at("0x48b7be", "hub_ctx_init")

# Also trace its callers
f = fm.getFunctionAt(A("0x48b7be"))
if f is None:
    f = fm.getFunctionContaining(A("0x48b7be"))
if f:
    refs = refmgr.getReferencesTo(f.getEntryPoint())
    for ref in refs:
        if ref.getReferenceType().isCall():
            caller = fm.getFunctionContaining(ref.getFromAddress())
            if caller:
                decompile_at(str(caller.getEntryPoint()), "caller_of_hub_ctx_init")

# === PART 3: FUN_00533b2a (queue consumer) ===
out.write(u"\n\n" + u"=" * 80 + u"\n")
out.write(u"PART 3: FUN_00533b2a (queue consumer)\n")
out.write(u"=" * 80 + u"\n")

decompile_at("0x533b2a", "queue_consumer")

# === PART 4: Decompile ALL functions in 0x4bc800-0x4bcc54 range ===
# To understand the real boundary of the function containing bhi260_full_sensor_reconfig call
out.write(u"\n\n" + u"=" * 80 + u"\n")
out.write(u"PART 4: All functions in 0x4bc800-0x4bcc54\n")
out.write(u"=" * 80 + u"\n")

fn_iter = fm.getFunctions(A("0x4bc800"), True)
count = 0
while fn_iter.hasNext() and count < 20:
    fn = fn_iter.next()
    ep = fn.getEntryPoint().getOffset()
    if ep > 0x4bcc54:
        break
    count += 1
    decompile_at("0x%x" % ep, "range_4bc8xx")

# === PART 5: Look at 0x4bf05e area for hub message receiver/dispatcher ===
out.write(u"\n\n" + u"=" * 80 + u"\n")
out.write(u"PART 5: Hub area 0x4bf05e-0x4bf0d2 (between queue init and hub_send_message)\n")
out.write(u"=" * 80 + u"\n")

fn_iter = fm.getFunctions(A("0x4bf000"), True)
count = 0
while fn_iter.hasNext() and count < 10:
    fn = fn_iter.next()
    ep = fn.getEntryPoint().getOffset()
    if ep >= 0x4bf0d2:
        break
    count += 1
    decompile_at("0x%x" % ep, "hub_msg_area")

# === PART 6: Decompile FUN_0052bf50 and FUN_0052c03c (BHI260 high-level functions) ===
out.write(u"\n\n" + u"=" * 80 + u"\n")
out.write(u"PART 6: BHI260 high-level control functions\n")
out.write(u"=" * 80 + u"\n")

decompile_at("0x52bf50", "bhi260_high_level_1")
decompile_at("0x52c03c", "bhi260_high_level_2")

# Also check FUN_0052b7e2 and FUN_0052af88 called from FUN_004bcb54
decompile_at("0x52b7e2", "fusion_config_1")
decompile_at("0x52af88", "fusion_config_2")

out.close()
print("done -> " + outfile)
