from ghidra.app.decompiler import DecompInterface
from ghidra.util.task import ConsoleTaskMonitor

out = open("/tmp/g2_ghidra_report12.txt", "w")
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
    w("  function: %s  range=%s-%s" % (fn.getName(), fn.getEntryPoint(), fn.getBody().getMaxAddress()))
    res = decomp.decompileFunction(fn, 60, monitor)
    if res.decompileCompleted():
        w(res.getDecompiledFunction().getC())
    else:
        w("  decompile FAILED: %s" % res.getErrorMessage())

# RX-direction action names (things the PHONE sends TO the glasses) --
# these are what the debug CLI's "terminal <subcommand>" simulates.
names = [
    "terminal_action_mode_sync",
    "terminal_action_query",
    "terminal_action_agent_content",
    "terminal_action_host_status",
    "terminal_action_session_list",
    "terminal_action_session_status",
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
print("WROTE /tmp/g2_ghidra_report12.txt")
