# -*- coding: utf-8 -*-
# Trace: FUN_004bcb54 (caller of bhi260_full_sensor_reconfig),
# hub message queue consumer, FIFO read timer/interrupt.
# @category CFW
from ghidra.app.decompiler import DecompInterface
from ghidra.util.task import ConsoleTaskMonitor
import codecs

args = getScriptArgs()
outfile = args[0] if len(args) > 0 else "/tmp/trace_hub_dispatch.txt"

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
    # Show callees and callers
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

# === PART 1: FUN_004bcb54 - the DIRECT caller of bhi260_full_sensor_reconfig ===
out.write(u"=" * 80 + u"\n")
out.write(u"PART 1: FUN_004bcb54 - direct caller of bhi260_full_sensor_reconfig\n")
out.write(u"=" * 80 + u"\n")
decompile_func("0x4bcb54", "hub_reconfig_handler")

# Now trace UP from FUN_004bcb54 - who calls it?
# Check its callers' callers too
f = fm.getFunctionAt(A("0x4bcb54"))
if f:
    refs = refmgr.getReferencesTo(f.getEntryPoint())
    for ref in refs:
        if ref.getReferenceType().isCall():
            caller = fm.getFunctionContaining(ref.getFromAddress())
            if caller:
                decompile_func(str(caller.getEntryPoint()), "caller_of_004bcb54")

# === PART 2: Find the hub message queue CONSUMER ===
# xQueueSend is at 0x448b0e. The receiver would call xQueueReceive.
# Let's find xQueueReceive and its callers.
out.write(u"\n\n" + u"=" * 80 + u"\n")
out.write(u"PART 2: xQueue consumer side - find the hub task that processes messages\n")
out.write(u"=" * 80 + u"\n")

# Search for functions named xQueueReceive or similar
fn_iter = fm.getFunctions(True)
queue_recv_funcs = []
for fn in fn_iter:
    name = fn.getName().lower()
    if "queue" in name and ("recv" in name or "receive" in name or "get" in name):
        queue_recv_funcs.append(fn)
        out.write(u"\nQueue recv function: %s @ %s\n" % (fn.getName(), fn.getEntryPoint()))

# If no named functions, look for callers of the FreeRTOS queue receive
# The queue receive is typically near xQueueSend (0x448b0e)
out.write(u"\nFunctions around xQueueSend (0x448b0e):\n")
fn_iter = fm.getFunctions(A("0x448a00"), True)
count = 0
while fn_iter.hasNext() and count < 20:
    fn = fn_iter.next()
    ep = fn.getEntryPoint().getOffset()
    if ep > 0x448d00:
        break
    count += 1
    out.write(u"  %s @ 0x%x (size %d)\n" % (fn.getName(), ep, fn.getBody().getNumAddresses()))
    # Check callers
    refs = refmgr.getReferencesTo(fn.getEntryPoint())
    caller_count = 0
    for ref in refs:
        if ref.getReferenceType().isCall():
            caller_count += 1
    out.write(u"    (%d callers)\n" % caller_count)

# FUN_00448b8c is called by worker_thread - that's the queue receive!
# Let's look at what queue the hub messages go to
# The queue handle is at *(DAT_004bf584 + 0xc)
# Let's look at DAT_004bf584
out.write(u"\nDAT_004bf584 value:\n")
try:
    val = mem.getInt(A("0x4bf584"))
    out.write(u"  0x4bf584 = 0x%08x\n" % (val & 0xffffffff))
except:
    out.write(u"  unreadable\n")

# === PART 3: Search for the hub_task / sensor_hub_task that processes messages ===
out.write(u"\n\n" + u"=" * 80 + u"\n")
out.write(u"PART 3: Hub task / sensor hub message processor\n")
out.write(u"=" * 80 + u"\n")

# The hub_send_message sends to a queue at *(DAT_004bf584 + 0xc)
# Something else reads from this same queue. Let's find functions that
# reference DAT_004bf584 (the hub context pointer)
refs = refmgr.getReferencesTo(A("0x4bf584"))
hub_ctx_users = set()
for ref in refs:
    fn = fm.getFunctionContaining(ref.getFromAddress())
    if fn:
        hub_ctx_users.add(str(fn.getEntryPoint()))
        out.write(u"  0x4bf584 referenced by %s @ %s\n" % (fn.getName(), fn.getEntryPoint()))

# Decompile functions that reference hub ctx but aren't hub_open/hub_close/hub_send
for addr in sorted(hub_ctx_users):
    f = fm.getFunctionAt(A(addr))
    if f and f.getName() not in ["hub_open", "hub_close", "hub_send_message", "hub_parameter_config"]:
        decompile_func(addr, "hub_ctx_user")

# === PART 4: Look at functions between 0x4bf05e-0x4bf0d2 and 0x4bf13e-0x4bf400 ===
out.write(u"\n\n" + u"=" * 80 + u"\n")
out.write(u"PART 4: Hub message handler area\n")
out.write(u"=" * 80 + u"\n")

fn_iter = fm.getFunctions(A("0x4bf05e"), True)
count = 0
while fn_iter.hasNext() and count < 15:
    fn = fn_iter.next()
    ep = fn.getEntryPoint().getOffset()
    if ep >= 0x4bf408:
        break
    count += 1
    out.write(u"\n%s @ 0x%x (size %d)\n" % (fn.getName(), ep, fn.getBody().getNumAddresses()))
    for cf in fn.getCalledFunctions(mon):
        out.write(u"  -> %s @ %s\n" % (cf.getName(), cf.getEntryPoint()))
    refs = refmgr.getReferencesTo(fn.getEntryPoint())
    for ref in refs:
        if ref.getReferenceType().isCall():
            caller = fm.getFunctionContaining(ref.getFromAddress())
            if caller:
                out.write(u"  <- %s @ %s\n" % (caller.getName(), caller.getEntryPoint()))

# === PART 5: Find who calls bhi260_fifo_read indirectly ===
# Look at ALL functions in the 0x4bbc00-0x4be000 range that call BHI260 functions
out.write(u"\n\n" + u"=" * 80 + u"\n")
out.write(u"PART 5: IMU driver layer functions (0x4bbc00-0x4be000) calling BHI260\n")
out.write(u"=" * 80 + u"\n")

fn_iter = fm.getFunctions(A("0x4bbc00"), True)
count = 0
while fn_iter.hasNext() and count < 80:
    fn = fn_iter.next()
    ep = fn.getEntryPoint().getOffset()
    if ep > 0x4be000:
        break
    count += 1
    callees = list(fn.getCalledFunctions(mon))
    callee_names = [c.getName() for c in callees]
    has_bhi = any("bhi260" in n or "528f" in str(c.getEntryPoint()) for n, c in zip(callee_names, callees))
    has_fifo = any("fifo" in n.lower() for n in callee_names)
    if has_bhi or has_fifo or len(callees) > 3:
        out.write(u"\n%s @ 0x%x (size %d)\n" % (fn.getName(), ep, fn.getBody().getNumAddresses()))
        for cf in callees:
            marker = " **" if "bhi260" in cf.getName() or "fifo" in cf.getName().lower() else ""
            out.write(u"  -> %s @ %s%s\n" % (cf.getName(), cf.getEntryPoint(), marker))
        refs = refmgr.getReferencesTo(fn.getEntryPoint())
        for ref in refs:
            if ref.getReferenceType().isCall():
                caller = fm.getFunctionContaining(ref.getFromAddress())
                if caller:
                    out.write(u"  <- %s @ %s\n" % (caller.getName(), caller.getEntryPoint()))

out.close()
print("done -> " + outfile)
