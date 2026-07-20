from ghidra.app.decompiler import DecompInterface
from ghidra.util.task import ConsoleTaskMonitor

out = open("/tmp/g2_ghidra_report9.txt", "w")
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

# the REAL "seek field by wire tag" function used by the decode loop
decompile_fn(a("004fe4aa"), "seek field by wire tag (FUN_004fe4aa)")
# and the scalar-field decoder (used for atype==0/simple fields) to see what it reads as "tag"
decompile_fn(a("004a9dac"), "decode scalar field (FUN_004a9dac)")

out.close()
print("WROTE /tmp/g2_ghidra_report9.txt")
