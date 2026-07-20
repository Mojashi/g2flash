# -*- coding: utf-8 -*-
# Deep trace: hub_send_message dispatch, FIFO wrapper function, sensor_enable chain
# @category CFW
from ghidra.app.decompiler import DecompInterface
from ghidra.util.task import ConsoleTaskMonitor
import codecs

args = getScriptArgs()
outfile = args[0] if len(args) > 0 else "/tmp/trace_fifo_deep.txt"

fm = currentProgram.getFunctionManager()
af = currentProgram.getAddressFactory()
mem = currentProgram.getMemory()
refmgr = currentProgram.getReferenceManager()
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
    return f

# === PART 1: hub_send_message and the message dispatch chain ===
out.write(u"=" * 80 + u"\n")
out.write(u"PART 1: hub_send_message -> message dispatch -> bhi260_full_sensor_reconfig\n")
out.write(u"=" * 80 + u"\n")

decompile_at("0x4bf0d2", "hub_send_message")

# Now find what hub_send_message calls
f = fm.getFunctionAt(A("0x4bf0d2"))
if f:
    out.write(u"\nhub_send_message callees:\n")
    for cf in f.getCalledFunctions(mon):
        out.write(u"  -> %s @ %s\n" % (cf.getName(), cf.getEntryPoint()))

# Decompile hub_send_message callers to understand the message types
out.write(u"\nhub_send_message callers:\n")
refs = refmgr.getReferencesTo(A("0x4bf0d2"))
callers = set()
for ref in refs:
    if ref.getReferenceType().isCall():
        fn = fm.getFunctionContaining(ref.getFromAddress())
        if fn:
            out.write(u"  <- %s @ %s\n" % (fn.getName(), fn.getEntryPoint()))
            callers.add(str(fn.getEntryPoint()))

# === PART 2: Find the function that wraps bhi260_fifo_read + batch_dispatch ===
# Look at functions around 0x529032-0x529300 (after the FIFO code)
out.write(u"\n\n" + u"=" * 80 + u"\n")
out.write(u"PART 2: Functions around FIFO code (0x529032-0x529400)\n")
out.write(u"=" * 80 + u"\n")

fn_iter = fm.getFunctions(A("0x529032"), True)
count = 0
while fn_iter.hasNext() and count < 30:
    fn = fn_iter.next()
    ep = fn.getEntryPoint().getOffset()
    if ep > 0x529a00:
        break
    count += 1
    out.write(u"\n%s @ 0x%x (size %d)\n" % (fn.getName(), ep, fn.getBody().getNumAddresses()))
    # Show callees
    for cf in fn.getCalledFunctions(mon):
        out.write(u"  -> %s @ %s\n" % (cf.getName(), cf.getEntryPoint()))
    # Show callers
    refs = refmgr.getReferencesTo(fn.getEntryPoint())
    for ref in refs:
        if ref.getReferenceType().isCall():
            caller = fm.getFunctionContaining(ref.getFromAddress())
            if caller:
                out.write(u"  <- %s @ %s\n" % (caller.getName(), caller.getEntryPoint()))

# Also check before the FIFO functions (0x527e00-0x528000)
out.write(u"\n\nFunctions 0x527e00-0x528000:\n")
fn_iter = fm.getFunctions(A("0x527e00"), True)
count = 0
while fn_iter.hasNext() and count < 10:
    fn = fn_iter.next()
    ep = fn.getEntryPoint().getOffset()
    if ep > 0x528000:
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

# === PART 3: Decompile driver_ctx function pointers (Thumb-adjusted) ===
out.write(u"\n\n" + u"=" * 80 + u"\n")
out.write(u"PART 3: Driver context function pointers\n")
out.write(u"=" * 80 + u"\n")

decompile_at("0x4bbc68", "driver_ctx[0] bus_read")
decompile_at("0x4bbca2", "driver_ctx[1] bus_write")
decompile_at("0x4a7124", "driver_ctx[3] task_submit")

# === PART 4: Find ALL callers of bhi260_full_sensor_reconfig ===
# It has no direct callers per xref, but maybe it's called from an unanalyzed region
# Let's search for BL instructions that target 0x52918a
out.write(u"\n\n" + u"=" * 80 + u"\n")
out.write(u"PART 4: Search for callers of bhi260_full_sensor_reconfig\n")
out.write(u"=" * 80 + u"\n")

# Look at all functions in the 0x529000-0x52a000 range for the wrapper
fn_iter = fm.getFunctions(A("0x529100"), True)
count = 0
wrapper_candidates = []
while fn_iter.hasNext() and count < 30:
    fn = fn_iter.next()
    ep = fn.getEntryPoint().getOffset()
    if ep > 0x52a000:
        break
    count += 1
    callees = list(fn.getCalledFunctions(mon))
    callee_names = [c.getName() for c in callees]
    # Check if it calls bhi260_full_sensor_reconfig or related
    interesting = any("bhi260" in n or "fifo" in n.lower() or "sensor" in n.lower() for n in callee_names)
    if interesting or len(callees) > 2:
        out.write(u"\n%s @ 0x%x (size %d)\n" % (fn.getName(), ep, fn.getBody().getNumAddresses()))
        for cf in callees:
            out.write(u"  -> %s @ %s\n" % (cf.getName(), cf.getEntryPoint()))
        refs = refmgr.getReferencesTo(fn.getEntryPoint())
        for ref in refs:
            caller = fm.getFunctionContaining(ref.getFromAddress())
            if caller:
                out.write(u"  <- %s @ %s\n" % (caller.getName(), caller.getEntryPoint()))
        wrapper_candidates.append(fn)

# Decompile the wrapper candidates
for fn in wrapper_candidates[:5]:
    out.write(u"\n\n--- CANDIDATE: %s @ %s ---\n" % (fn.getName(), fn.getEntryPoint()))
    try:
        res = di.decompileFunction(fn, 120, mon)
        if res and res.getDecompiledFunction():
            out.write(res.getDecompiledFunction().getC()[:6000])
    except Exception as e:
        out.write(u"error: %s\n" % e)

# === PART 5: bhi260_sensor_enable - what does it configure? ===
out.write(u"\n\n" + u"=" * 80 + u"\n")
out.write(u"PART 5: bhi260_sensor_enable and its callers\n")
out.write(u"=" * 80 + u"\n")

# Find bhi260_sensor_enable
fn_iter = fm.getFunctions(True)
for fn in fn_iter:
    if "sensor_enable" in fn.getName().lower():
        out.write(u"\n%s @ %s\n" % (fn.getName(), fn.getEntryPoint()))
        refs = refmgr.getReferencesTo(fn.getEntryPoint())
        for ref in refs:
            if ref.getReferenceType().isCall():
                caller = fm.getFunctionContaining(ref.getFromAddress())
                if caller:
                    out.write(u"  <- %s @ %s\n" % (caller.getName(), caller.getEntryPoint()))

# === PART 6: The hub_open message handler - look at what processes the message ===
out.write(u"\n\n" + u"=" * 80 + u"\n")
out.write(u"PART 6: Functions in hub area (0x4bf000-0x4bfa00) - message processing\n")
out.write(u"=" * 80 + u"\n")

fn_iter = fm.getFunctions(A("0x4bf000"), True)
count = 0
while fn_iter.hasNext() and count < 40:
    fn = fn_iter.next()
    ep = fn.getEntryPoint().getOffset()
    if ep > 0x4bfa00:
        break
    count += 1
    callees = list(fn.getCalledFunctions(mon))
    callee_names = [c.getName() for c in callees]
    has_bhi = any("bhi260" in n or "sensor" in n.lower() or "fifo" in n.lower() or "reconfig" in n.lower() for n in callee_names)
    # Show all functions but only decompile interesting ones
    out.write(u"\n%s @ 0x%x (size %d)" % (fn.getName(), ep, fn.getBody().getNumAddresses()))
    if has_bhi:
        out.write(u" ** CALLS BHI260/SENSOR **")
    out.write(u"\n")
    for cf in callees:
        out.write(u"  -> %s @ %s\n" % (cf.getName(), cf.getEntryPoint()))
    if has_bhi:
        try:
            res = di.decompileFunction(fn, 120, mon)
            if res and res.getDecompiledFunction():
                out.write(res.getDecompiledFunction().getC()[:5000])
        except:
            pass
        out.write(u"\n")

out.close()
print("done -> " + outfile)
