from ghidra.app.decompiler import DecompInterface
from ghidra.util.task import ConsoleTaskMonitor
from ghidra.program.model.data import Undefined4DataType
from ghidra.program.model.listing import ParameterImpl, Function
from ghidra.program.model.symbol import SourceType

out = open("/tmp/g2_ghidra_report7.txt", "w")
def w(s): out.write(s + "\n")

monitor = ConsoleTaskMonitor()
program = currentProgram
fm = program.getFunctionManager()
af = program.getAddressFactory()
mem = program.getMemory()

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
    return fn

def force_params(fn, n):
    """Force `fn` to have n undefined4 params (SourceType.USER_DEFINED) so the
    decompiler stops guessing a too-narrow prototype from local analysis alone."""
    tid = program.startTransaction("force params")
    ok = False
    try:
        params = [ParameterImpl("p%d" % i, Undefined4DataType.dataType, program) for i in range(n)]
        fn.replaceParameters(Function.FunctionUpdateType.DYNAMIC_STORAGE_ALL_PARAMS, True, SourceType.USER_DEFINED, params)
        ok = True
    except Exception as e:
        w("  (force_params failed: %s)" % e)
    finally:
        program.endTransaction(tid, ok)

def dump_bytes(addr_hex, n, label):
    w("=" * 78)
    w("### RAW BYTES %s @ %s (%d bytes)" % (label, addr_hex, n))
    addr = a(addr_hex)
    try:
        vals = []
        for i in range(n):
            bv = mem.getByte(addr.add(i))
            vals.append(bv & 0xff)
        for i in range(0, n, 16):
            row = vals[i:i+16]
            hexs = " ".join("%02x" % c for c in row)
            asc = "".join(chr(c) if 0x20 <= c < 0x7f else "." for c in row)
            w("  %08x: %-48s %s" % (addr.getOffset() + i, hexs, asc))
    except Exception as e:
        w("  ERROR reading bytes: %s" % e)

# 1. dump the schema descriptor raw bytes (fixed)
dump_bytes("005d00e0", 512, "schema descriptor DAT_005d00e0")

# 2. the REAL decode entry (FUN_004aa564 was a 1-line passthrough to this)
decompile_fn(a("004aa2dc"), "REAL generic RX decode (FUN_004aa2dc)")

# 3. re-decompile FUN_004a896a with a forced 3-param signature (call site had 3 args)
fn = fm.getFunctionAt(a("004a896a"))
if fn:
    force_params(fn, 3)
decompile_fn(a("004a896a"), "generic TX encode, forced 3-param sig")

# 4. the schema iterator helpers -- these define the 22-byte field-record layout
decompile_fn(a("004fe56c"), "schema iterator: get-first-field")
decompile_fn(a("004fe48a"), "schema iterator: get-next-field")

out.close()
print("WROTE /tmp/g2_ghidra_report7.txt")
