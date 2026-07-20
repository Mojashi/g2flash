from ghidra.app.decompiler import DecompInterface
from ghidra.util.task import ConsoleTaskMonitor

out = open("/tmp/g2_ghidra_report3.txt", "w")
def w(s): out.write(s + "\n")

monitor = ConsoleTaskMonitor()
program = currentProgram
fm = program.getFunctionManager()
af = program.getAddressFactory()
mem = program.getMemory()

decomp = DecompInterface()
decomp.openProgram(program)

def a(h): return af.getAddress(h)

def find_string_addr(text):
    data = text.encode("ascii") + b"\x00"
    return mem.findBytes(program.getMinAddress(), data, None, True, monitor)

def dump_xrefs(addr, label):
    w("=" * 78)
    w("### xrefs TO %s (%s)" % (addr, label))
    refs = program.getReferenceManager().getReferencesTo(addr)
    fns = set()
    n = 0
    for ref in refs:
        n += 1
        frm = ref.getFromAddress()
        fn = fm.getFunctionContaining(frm)
        fname = fn.getName() if fn else "?"
        w("  ref from %s (in %s) type=%s" % (frm, fname, ref.getReferenceType()))
        if fn: fns.add(fn.getEntryPoint())
    if n == 0:
        w("  (no xrefs found)")
    return fns

def decompile_fn(entry_addr, label):
    w("=" * 78)
    w("### DECOMPILE %s @ %s" % (label, entry_addr))
    fn = fm.getFunctionAt(entry_addr)
    if fn is None:
        fn = fm.getFunctionContaining(entry_addr)
    if fn is None:
        w("  (no function)")
        return
    w("  function: %s  range=%s-%s" % (fn.getName(), fn.getEntryPoint(), fn.getBody().getMaxAddress()))
    res = decomp.decompileFunction(fn, 60, monitor)
    if res.decompileCompleted():
        w(res.getDecompiledFunction().getC())
    else:
        w("  decompile FAILED: %s" % res.getErrorMessage())

# ---- RX dispatcher: the central "phone -> glasses" message router for terminal mode ----
targets = [
    "APP_PbTerminalRxFrameDataProcess",
    "APP_PbTerminalTxEncodeQueryReply",
    "APP_PbTerminalTxEncodeVoiceInput",
    "APP_PbTerminalTxEncodeNewSessionRequest",
    "pb_service_terminal.c",
]
for t in targets:
    sa = find_string_addr(t)
    w("=" * 78)
    w("### string %r -> %s" % (t, sa))
    if sa is not None:
        fns = dump_xrefs(sa, t)
        for fentry in fns:
            decompile_fn(fentry, "caller referencing %r" % t)

out.close()
print("WROTE /tmp/g2_ghidra_report3.txt")
