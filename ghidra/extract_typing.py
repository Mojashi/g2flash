# -*- coding: utf-8 -*-
# Ghidra headless: prepare the signature-typing workflow input. Decompile every NAMED function that
# still has an undefined signature, group by the source FILE the firmware embeds in its log strings
# (log_printf arg3 = "...\\pb_service_health.c"), and write one .c dump per module + a manifest.
# @category CFW
import json, os
from ghidra.app.decompiler import DecompInterface
from ghidra.util.task import ConsoleTaskMonitor
from ghidra.program.model.symbol import SourceType
from ghidra.program.model.pcode import PcodeOp

fm = currentProgram.getFunctionManager()
af = currentProgram.getAddressFactory()
mem = currentProgram.getMemory()
di = DecompInterface(); di.openProgram(currentProgram); mon = ConsoleTaskMonitor()
OUT = "/private/tmp/claude-501/-Users-mojashi-repos-odd/70e4d562-4b1b-41ba-9eac-bd869645bc38/scratchpad/typing2"
try: os.makedirs(OUT)
except: pass

LOG_FILE_ARG = {0x43d514: 3}   # log_printf(level, module, FILE, __func__, ...) -> input(3)=file

def read_cstr(a_long, mx=160):
    if not (0x400000 <= a_long < 0x800000): return None
    try:
        a = af.getAddress("0x%x" % a_long); bs = bytearray()
        for i in range(mx):
            b = mem.getByte(a.add(i)) & 0xff
            if b == 0: break
            bs.append(b)
        else: return None
        return bs.decode("latin1")
    except: return None

def rd32(a_long):
    try:
        a = af.getAddress("0x%x" % a_long)
        return ((mem.getByte(a)&0xff)|((mem.getByte(a.add(1))&0xff)<<8)
                |((mem.getByte(a.add(2))&0xff)<<16)|((mem.getByte(a.add(3))&0xff)<<24))
    except: return None

def const_addr(vn):
    if vn is None: return None
    if vn.isConstant(): return vn.getOffset()
    if vn.isAddress():
        try: return vn.getAddress().getOffset()
        except: return None
    return None

def resolve_path(sa):
    s = read_cstr(sa)
    if s and ("\\" in s or "/" in s or s.endswith(".c")): return s
    p = rd32(sa)
    if p is not None:
        s2 = read_cstr(p)
        if s2 and ("\\" in s2 or "/" in s2 or s2.endswith(".c")): return s2
    return None

def basename(p):
    b = p.replace("\\", "/").split("/")[-1]
    return b

def is_ascii(s): return all(ord(c) < 128 for c in s)
def undefined_sig(f):
    rt = f.getReturnType().getName()
    return rt.startswith("undefined") or any(p.getDataType().getName().startswith("undefined") for p in f.getParameters())

groups = {}   # file -> [(addr,name,code)]
n = 0
for f in fm.getFunctions(True):
    nm = f.getName()
    if nm.startswith("FUN_") or not is_ascii(nm): continue
    if not undefined_sig(f): continue
    try:
        res = di.decompileFunction(f, 45, mon)
    except: continue
    if res is None or res.getHighFunction() is None: continue
    hf = res.getHighFunction()
    fpath = None
    for op in hf.getPcodeOps():
        if op.getOpcode() != PcodeOp.CALL: continue
        if const_addr(op.getInput(0)) not in LOG_FILE_ARG: continue
        idx = LOG_FILE_ARG[const_addr(op.getInput(0))]
        if op.getNumInputs() <= idx: continue
        fa = const_addr(op.getInput(idx))
        if fa is not None:
            fpath = resolve_path(fa)
            if fpath: break
    key = basename(fpath) if fpath else "_nofile"
    code = res.getDecompiledFunction().getC()
    groups.setdefault(key, []).append((str(f.getEntryPoint()), nm, code))
    n += 1

# write per-file dumps for modules with >=3 functions (skip the giant _nofile bucket for now)
manifest = {}
big = sorted(((k, v) for k, v in groups.items() if k != "_nofile" and len(v) >= 3),
             key=lambda kv: -len(kv[1]))
for key, fns in big:
    safe = key.replace(".", "_")
    path = os.path.join(OUT, safe + ".c")
    with open(path, "wb") as fh:
        for addr, nm, code in fns:
            chunk = "// ===== %s @ 0x%s =====\n%s\n\n" % (nm, addr.lstrip("0") or "0", code)
            fh.write(chunk.encode("utf-8"))    # decompiled code may hold non-ASCII callee names
    manifest[key] = [{"addr": "0x" + a.lstrip("0"), "name": nm} for a, nm, _ in fns]
json.dump(manifest, open(os.path.join(OUT, "manifest.json"), "w"), indent=1)

print("EXTRACT: %d named+undefined funcs; %d modules (>=3 funcs) written" % (n, len(big)))
print("EXTRACT: top modules:")
for key, fns in big[:30]:
    print("   %-40s %d" % (key, len(fns)))
print("EXTRACT: _nofile bucket = %d funcs (no embedded path)" % len(groups.get("_nofile", [])))
