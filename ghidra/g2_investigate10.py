from ghidra.app.decompiler import DecompInterface
from ghidra.util.task import ConsoleTaskMonitor

out = open("/tmp/g2_ghidra_report10.txt", "w")
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

def dump_xrefs(addr):
    refs = program.getReferenceManager().getReferencesTo(addr)
    fns = set()
    for ref in refs:
        frm = ref.getFromAddress()
        fn = fm.getFunctionContaining(frm)
        if fn: fns.add(fn.getEntryPoint())
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
    res = decomp.decompileFunction(fn, 60, monitor)
    if res.decompileCompleted():
        w(res.getDecompiledFunction().getC())
    else:
        w("  decompile FAILED: %s" % res.getErrorMessage())

names = [
    "APP_PbTerminalTxEncodeCommResp",
    "APP_PbTerminalTxEncodeStatusReply",
    "APP_PbTerminalTxEncodeAgentInterrupt",
    "APP_PbTerminalTxEncodeSessionSwitchRequest",
    "APP_PbTerminalTxEncodeNewSessionCancel",
    "APP_PbTerminalTxEncodeDisplayStateNotify",
    "APP_PbTerminalTxEncodeListFocus",
    "APP_PbTerminalTxEncodeOverlayFocus",
]
for name in names:
    sa = find_string_addr(name)
    w("=" * 78)
    w("### string %r -> %s" % (name, sa))
    if sa is None:
        continue
    fns = dump_xrefs(sa)
    for fentry in fns:
        decompile_fn(fentry, "caller referencing %r" % name)

out.close()
print("WROTE /tmp/g2_ghidra_report10.txt")
