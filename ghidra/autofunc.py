# Ghidra headless: auto-name functions from their embedded __func__ string.
# The firmware logger is log_printf(level, module_tag, file, __func__, line, fmt, ...) at 0x43d514
# (and a second logger FUN_0043ce46(mask, __func__, ...) whose 2nd arg is also __func__). We
# decompile each still-FUN_ function, find those CALLs, read the __func__ constant string, and if
# it's a clean C identifier we rename the function to it (SourceType.ANALYSIS so our hand names win).
# Also stamps the module tag as a plate comment. @category CFW
from ghidra.app.decompiler import DecompInterface
from ghidra.util.task import ConsoleTaskMonitor
from ghidra.program.model.symbol import SourceType
from ghidra.program.model.pcode import PcodeOp

fm = currentProgram.getFunctionManager()
af = currentProgram.getAddressFactory()
mem = currentProgram.getMemory()
listing = currentProgram.getListing()
di = DecompInterface(); di.openProgram(currentProgram); mon = ConsoleTaskMonitor()

# (target_addr, func_arg_index, tag_arg_index or -1)   arg indices are pcode CALL inputs (0=target)
LOGGERS = { 0x43d514: (4, 2), 0x43ce46: (2, -1) }

# PREREQUISITE: the logger functions MUST exist as functions in the DB for the decompiler to emit
# CALL pcode ops targeting them. On a fresh import they may not be auto-discovered. Create them here.
for addr in LOGGERS:
    a = af.getAddress("0x%x" % addr)
    if fm.getFunctionAt(a) is None:
        try:
            fm.createFunction(None, a, None, SourceType.ANALYSIS)
        except:
            pass  # may fail if the address is inside an existing function body; that's fine

def read_cstr(addr_long, mx=64):
    if not (0x400000 <= addr_long < 0x800000 or 0x20000000 <= addr_long < 0x20800000):
        return None
    try:
        a = af.getAddress("0x%x" % addr_long)
        bs = bytearray()
        for i in range(mx):
            b = mem.getByte(a.add(i)) & 0xff
            if b == 0: break
            bs.append(b)
        else:
            return None
        return bs.decode("latin1")
    except:
        return None

def rd32(addr_long):
    try:
        a = af.getAddress("0x%x" % addr_long)
        return ((mem.getByte(a) & 0xff) | ((mem.getByte(a.add(1)) & 0xff) << 8)
                | ((mem.getByte(a.add(2)) & 0xff) << 16) | ((mem.getByte(a.add(3)) & 0xff) << 24))
    except:
        return None

def is_ident(s):
    # ASCII-only: rejects the mojibake that arises from reading a char* pointer's raw bytes as text
    if not s or not (s[0].isalpha() or s[0] == '_'):
        return False
    if len(s) < 3 or len(s) > 63:
        return False
    return all((ord(c) < 128 and (c.isalnum() or c == '_')) for c in s)

def resolve_str(sa):
    # sa is either the string address (movw/movt immediate) OR the address of a char* loaded from a
    # literal pool. Collect the direct read and the one-level deref; prefer the LONGER valid ident,
    # because pointer-bytes-as-text garbage is short (<=3 chars, e.g. "PVw" = ptr 0x7756xx low bytes)
    # while real __func__ names are long. This also catches ASCII-but-garbage 3-char names.
    cands = []
    direct = read_cstr(sa)
    if is_ident(direct): cands.append(direct)
    p = rd32(sa)
    if p is not None and 0x400000 <= p < 0x800000:
        deref = read_cstr(p)
        if is_ident(deref): cands.append(deref)
    if not cands: return None
    return max(cands, key=len)

def resolve_tag(ta):
    # module tag like "pb.health" (allow . / -), same direct-or-deref resolution
    def ok(t): return bool(t) and 2 <= len(t) <= 40 and all(32 < ord(c) < 127 for c in t) and any(c.isalpha() for c in t)
    t = read_cstr(ta)
    if ok(t): return t
    p = rd32(ta)
    if p is not None:
        t2 = read_cstr(p)
        if ok(t2): return t2
    return None

def const_addr(vn):
    if vn is None: return None
    if vn.isConstant(): return vn.getOffset()
    if vn.isAddress():
        try: return vn.getAddress().getOffset()
        except: return None
    return None

def is_ascii(s):
    return all(ord(c) < 128 for c in s)

def needs_name(f):
    nm = f.getName()
    # still-default, garbled name, short pointer-byte garble (<=4 chars like "PVw"), or ANY existing
    # module tag (re-derive it: old runs left tags that are the low bytes of the tag POINTER).
    if nm.startswith("FUN_") or not is_ascii(nm) or len(nm) <= 4:
        return True
    c = listing.getComment(3, f.getEntryPoint())     # 3 = PLATE_COMMENT
    return c is not None and (not is_ascii(c) or c.startswith("module: "))

named = 0; fixed = 0; scanned = 0
funcs = list(fm.getFunctions(True))
for f in funcs:
    was_garbled = not is_ascii(f.getName())
    if not needs_name(f):
        continue
    scanned += 1
    try:
        res = di.decompileFunction(f, 45, mon)
    except:
        continue
    if res is None: continue
    hf = res.getHighFunction()
    if hf is None: continue
    cand = None; tag = None
    for op in hf.getPcodeOps():
        if op.getOpcode() != PcodeOp.CALL: continue
        t = const_addr(op.getInput(0))
        if t not in LOGGERS: continue
        fi, ti = LOGGERS[t]
        if op.getNumInputs() <= fi: continue
        sa = const_addr(op.getInput(fi))
        if sa is None: continue
        s = resolve_str(sa)
        if not s: continue
        thistag = None
        if ti >= 0 and op.getNumInputs() > ti:
            ta = const_addr(op.getInput(ti))
            if ta is not None: thistag = resolve_tag(ta)
        if cand is None:
            cand = s; tag = thistag
        if thistag:                       # prefer the logger call that also carries the module tag
            cand = s; tag = thistag; break
    if cand:
        try:
            ep = f.getEntryPoint()
            sym = f.getSymbol()
            is_user = sym is not None and sym.getSource() == SourceType.USER_DEFINED
            curname = f.getName()
            if not is_user and cand != curname:        # never clobber a hand (USER_DEFINED) name
                f.setName(cand, SourceType.ANALYSIS)
                named += 1
                if was_garbled or len(curname) <= 4: fixed += 1
            old = listing.getComment(3, ep)               # 3 = PLATE_COMMENT
            if tag:
                listing.setComment(ep, 3, "module: " + tag)
            elif old is not None and not is_ascii(old):
                listing.setComment(ep, 3, None)           # clear stale garbled comment
        except Exception as e:
            pass

print("autofunc: scanned %d funcs, named %d from __func__ (%d were garbled -> fixed)" % (scanned, named, fixed))

# cleanup: clear garbled "module: X" plate comments where X is not a valid tag (e.g. "<gx" = the low
# bytes of the tag pointer left by the old bug). A missing comment beats a misleading one.
import re as _re
TAGRE = _re.compile(r'^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z0-9_]+)*$')
cleared = 0
for f in fm.getFunctions(True):
    ep = f.getEntryPoint()
    c = listing.getComment(3, ep)
    if c and c.startswith("module: ") and not TAGRE.match(c[8:].strip()):
        listing.setComment(ep, 3, None); cleared += 1
print("autofunc: cleared %d garbled module comments" % cleared)
