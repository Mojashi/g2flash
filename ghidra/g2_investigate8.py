from ghidra.app.decompiler import DecompInterface
from ghidra.util.task import ConsoleTaskMonitor

out = open("/tmp/g2_ghidra_report8.txt", "w")
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

# the real schema/field-iterator core -- where does the field-descriptor table
# pointer actually come from?
decompile_fn(a("004fe436"), "schema iterator core (FUN_004fe436)")
decompile_fn(a("004fe520"), "schema iterator (FUN_004fe520)")
decompile_fn(a("004fe3bc"), "schema iterator advance (FUN_004fe3bc)")
decompile_fn(a("004fe220"), "schema iterator advance2 (FUN_004fe220)")
decompile_fn(a("004a9ab0"), "read next wire tag/len (FUN_004a9ab0)")
decompile_fn(a("004aa028"), "decode one field (FUN_004aa028)")

out.close()
print("WROTE /tmp/g2_ghidra_report8.txt")
