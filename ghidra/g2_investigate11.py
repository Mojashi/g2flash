from ghidra.app.decompiler import DecompInterface
from ghidra.util.task import ConsoleTaskMonitor

out = open("/tmp/g2_ghidra_report11.txt", "w")
def w(s): out.write(s + "\n")

monitor = ConsoleTaskMonitor()
program = currentProgram
fm = program.getFunctionManager()
af = program.getAddressFactory()

decomp = DecompInterface()
decomp.openProgram(program)

def a(h): return af.getAddress(h)

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

# how does the generic encoder decide WHICH oneof branch (tag) is "active" and
# should actually be emitted, given the msgBuf built by FUN_005cf6dc?
decompile_fn(a("004a8930"), "encode submessage/oneof field (FUN_004a8930)")
decompile_fn(a("004a8856"), "encode scalar field (FUN_004a8856)")

out.close()
print("WROTE /tmp/g2_ghidra_report11.txt")
