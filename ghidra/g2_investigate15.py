from ghidra.app.decompiler import DecompInterface
from ghidra.util.task import ConsoleTaskMonitor

out = open("/tmp/g2_ghidra_report15.txt", "w")
def w(s): out.write(s + "\n")

monitor = ConsoleTaskMonitor()
program = currentProgram
fm = program.getFunctionManager()
af = program.getAddressFactory()
mem = program.getMemory()

decomp = DecompInterface()
decomp.openProgram(program)

def a(h): return af.getAddress(h)

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

# who ELSE (besides the validate/ack wrapper FUN_005e5414) touches DAT_005e5720,
# the decoded-RX-struct buffer? this is the real dispatcher we're after.
fns = dump_xrefs(a("005e5720"), "DAT_005e5720 decoded RX struct")
for fentry in fns:
    decompile_fn(fentry, "fn referencing DAT_005e5720")

out.close()
print("WROTE /tmp/g2_ghidra_report15.txt")
