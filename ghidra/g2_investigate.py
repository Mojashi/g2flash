# Ghidra headless post-script (Jython). Run after auto-analysis via -postScript.
# Dumps decompiled C for our targets of interest to a report file, using Ghidra's
# real reference/decompiler engine instead of manual capstone tracing.
from ghidra.app.decompiler import DecompInterface
from ghidra.util.task import ConsoleTaskMonitor

out_path = "/tmp/g2_ghidra_report.txt"
out = open(out_path, "w")
def w(s):
    out.write(s + "\n")

monitor = ConsoleTaskMonitor()
program = currentProgram
fm = program.getFunctionManager()
listing = program.getListing()
addr_factory = program.getAddressFactory()

decomp = DecompInterface()
decomp.openProgram(program)

def a(hexstr):
    return addr_factory.getAddress(hexstr)

def decompile_at(addr, label):
    w("=" * 78)
    w("### %s @ %s" % (label, addr))
    fn = fm.getFunctionContaining(addr)
    if fn is None:
        w("  (no function contains this address)")
        return None
    w("  function: %s  range=%s-%s" % (fn.getName(), fn.getEntryPoint(), fn.getBody().getMaxAddress()))
    res = decomp.decompileFunction(fn, 60, monitor)
    if res.decompileCompleted():
        w(res.getDecompiledFunction().getC())
    else:
        w("  decompile FAILED: %s" % res.getErrorMessage())
    return fn

def find_string_addr(text):
    """Find a defined/undefined string's address by scanning memory for the bytes."""
    mem = program.getMemory()
    data = text.encode("ascii") + b"\x00"
    found = mem.findBytes(program.getMinAddress(), data, None, True, monitor)
    return found

def dump_xrefs(addr, label):
    w("=" * 78)
    w("### xrefs TO %s (%s)" % (addr, label))
    refs = program.getReferenceManager().getReferencesTo(addr)
    n = 0
    for ref in refs:
        n += 1
        frm = ref.getFromAddress()
        fn = fm.getFunctionContaining(frm)
        w("  ref from %s (in %s) type=%s" % (frm, fn.getName() if fn else "?", ref.getReferenceType()))
    if n == 0:
        w("  (no xrefs found by Ghidra's reference manager)")
    return n

# ---- 1. input dispatcher: full decompile, to see every [r4]==0xNN app-id branch ----
decompile_at(a("004424a2"), "input dispatcher FUN_004424a2")

# ---- 2. the lv_layer-ish cluster around 0x44ed80-0x44ee40: let Ghidra resolve real
#         function boundaries + decompile each, instead of my manual capstone read ----
for addr_hex, label in [
    ("0044edb2", "candidate A (reads +0x300, no warn)"),
    ("0044edc2", "candidate B (warn path, near lv_layer_top string)"),
    ("0044ee06", "candidate C (2nd warn-shaped function)"),
]:
    decompile_at(a(addr_hex), label)

# ---- 3. find the actual lv_layer_top / lv_layer_sys / lv_layer_bottom strings via
#         Ghidra's own memory search, then use ITS reference manager (catches xrefs my
#         manual movw/movt scan might miss, e.g. via constant-pool tables Ghidra
#         resolves automatically during auto-analysis) ----
for s in [
    "lv_layer_top: no display registered to get its top layer",
    "lv_layer_sys: no display registered to get its sys. layer",
    "lv_layer_bottom: no display registered to get its bottom layer",
]:
    sa = find_string_addr(s)
    w("=" * 78)
    w("### string %r -> %s" % (s, sa))
    if sa is not None:
        dump_xrefs(sa, s)

# ---- 4. OverlayFocus / terminal-related name strings: real xrefs ----
for s in [
    "APP_PbTerminalTxEncodeOverlayFocus",
    "APP_PbTerminalTxEncodeDisplayStateNotify",
    "terminal_input_event_handler",
    "terminal_ui_action_interrupt_confirm_show",
    "terminal_ui_fsm_handler",
]:
    sa = find_string_addr(s)
    w("=" * 78)
    w("### string %r -> %s" % (s, sa))
    if sa is not None:
        dump_xrefs(sa, s)

# ---- 5. who calls the input dispatcher itself? (how does mode routing happen upstream) ----
disp_fn = fm.getFunctionContaining(a("004424a2"))
if disp_fn is not None:
    w("=" * 78)
    w("### callers of input dispatcher %s" % disp_fn.getEntryPoint())
    dump_xrefs(disp_fn.getEntryPoint(), "FUN_004424a2")

out.close()
print("WROTE " + out_path)
