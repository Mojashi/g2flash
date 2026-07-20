from ghidra.app.decompiler import DecompInterface
from ghidra.util.task import ConsoleTaskMonitor

out = open("/tmp/g2_ghidra_report6.txt", "w")
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

def dump_bytes(addr_hex, n, label):
    w("=" * 78)
    w("### RAW BYTES %s @ %s (%d bytes)" % (label, addr_hex, n))
    addr = a(addr_hex)
    try:
        b = bytearray(n)
        mem.getBytes(addr, b)
        bs = bytes(x & 0xff for x in b)
        for i in range(0, n, 16):
            row = bs[i:i+16]
            hexs = " ".join("%02x" % c for c in row)
            asc = "".join(chr(c) if 0x20 <= c < 0x7f else "." for c in row)
            w("  %08x: %-48s %s" % (addr.getOffset() + i, hexs, asc))
    except Exception as e:
        w("  ERROR reading bytes: %s" % e)

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

# ---- 1. the generic encode/decode functions -- their logic IS the schema format spec ----
decompile_fn(a("004a896a"), "generic TX encode (FUN_004a896a)")
decompile_fn(a("004aa564"), "generic RX decode (FUN_004aa564)")

# ---- 2. the schema descriptor blob itself ----
dump_bytes("005d00e0", 512, "schema descriptor DAT_005d00e0")
dump_xrefs(a("005d00e0"), "DAT_005d00e0 (schema descriptor)")

# ---- 3. the decoded-RX-struct buffer -- who else touches it? (the real async consumer) ----
dump_xrefs(a("005e5720"), "DAT_005e5720 (decoded RX struct buffer)")

out.close()
print("WROTE /tmp/g2_ghidra_report6.txt")
