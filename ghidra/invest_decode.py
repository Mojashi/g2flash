# -*- coding: utf-8 -*-
# Ghidra headless: investigate the pb encode/decode call pattern. For each <Name>_msgdesc global,
# find CALLs that pass it as an argument, and report the callee + which arg is the msgdesc + the
# "struct" argument (dest) and whether it resolves to a global address or a stack local. @category CFW
from ghidra.app.decompiler import DecompInterface
from ghidra.util.task import ConsoleTaskMonitor
from ghidra.program.model.pcode import PcodeOp

fm = currentProgram.getFunctionManager()
af = currentProgram.getAddressFactory()
rm = currentProgram.getReferenceManager()
st = currentProgram.getSymbolTable()
di = DecompInterface(); di.openProgram(currentProgram); mon = ConsoleTaskMonitor()

# msgdesc addr -> name
descs = {}
for s in st.getAllSymbols(False):
    if s.getName().endswith("_msgdesc"):
        descs[s.getAddress().getOffset()] = s.getName()

def const_addr(vn):
    if vn is None: return None
    if vn.isConstant(): return vn.getOffset()
    if vn.isAddress():
        try: return vn.getAddress().getOffset()
        except: return None
    return None

def vn_desc(vn):
    if vn is None: return "None"
    if vn.isConstant(): return "const:0x%x" % vn.getOffset()
    if vn.isAddress():
        o = vn.getAddress().getOffset()
        sp = "ram" if 0x400000 <= o < 0x20000000 else ("stack/reg" if o >= 0x20000000 else "?")
        return "addr:0x%x(%s)" % (o, sp)
    if vn.isUnique(): return "unique"
    if vn.isRegister(): return "reg"
    hv = vn.getHigh()
    if hv is not None:
        sym = hv.getSymbol()
        if sym is not None:
            return "local:%s(%s)" % (sym.getName(), hv.getDataType().getName())
    return "var"

# collect callee -> arg-position stats, and sample sites
callee_stats = {}
samples = []
funcs_seen = set()
for m, nm in descs.items():
    for r in rm.getReferencesTo(af.getAddress("0x%x" % m)):
        f = fm.getFunctionContaining(r.getFromAddress())
        if f is None or f.getEntryPoint() in funcs_seen: continue
        funcs_seen.add(f.getEntryPoint())
        try: res = di.decompileFunction(f, 45, mon)
        except: continue
        if res is None or res.getHighFunction() is None: continue
        for op in res.getHighFunction().getPcodeOps():
            if op.getOpcode() != PcodeOp.CALL: continue
            # is any input this msgdesc?
            midx = None
            for i in range(1, op.getNumInputs()):
                if const_addr(op.getInput(i)) == m:
                    midx = i; break
            if midx is None: continue
            callee = const_addr(op.getInput(0))
            key = (callee, midx)
            callee_stats[key] = callee_stats.get(key, 0) + 1
            if len(samples) < 22:
                args = [vn_desc(op.getInput(i)) for i in range(1, min(op.getNumInputs(), 6))]
                samples.append("%s: %s(msgdesc@arg%d) in %s | args=%s" % (
                    nm, ("0x%x" % callee) if callee else "?", midx, f.getName(), args))

print("INVEST: callee/msgdesc-arg-position histogram (callee_addr, msgdesc_argidx) -> count:")
for (c, mi), n in sorted(callee_stats.items(), key=lambda x: -x[1]):
    cf = fm.getFunctionContaining(af.getAddress("0x%x" % c)) if c else None
    cn = cf.getName() if cf else "?"
    print("   callee 0x%x (%s)  msgdesc@arg%d  x%d" % (c or 0, cn, mi, n))
print("\nINVEST: sample sites:")
for s in samples: print("  " + s)
