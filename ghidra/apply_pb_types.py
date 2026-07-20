# -*- coding: utf-8 -*-
# Ghidra headless: auto-apply the /pb message structs to the service ENCODER functions. Each encoder
# allocates its tx buffer with FUN_0043c0e4(gbuf, sizeof(struct), 0) right where it references the
# message descriptor; we match that alloc by (a) being in a function that references <Name>_msgdesc
# and (b) alloc-size == struct total, then type the buffer global as <Struct>*. This is the exact
# pattern validated on EvenAIDataPackage (@0x508942, alloc 0x20c). @category CFW
import json
from ghidra.app.decompiler import DecompInterface
from ghidra.util.task import ConsoleTaskMonitor
from ghidra.program.model.pcode import PcodeOp
from ghidra.program.model.data import PointerDataType
from java.lang import Throwable

fm = currentProgram.getFunctionManager()
af = currentProgram.getAddressFactory()
rm = currentProgram.getReferenceManager()
dtm = currentProgram.getDataTypeManager()
listing = currentProgram.getListing()
di = DecompInterface(); di.openProgram(currentProgram); mon = ConsoleTaskMonitor()
def A(h): return af.getAddress(h if str(h).startswith("0x") else "0x" + h)

ALLOC = 0x43c0e4
args = getScriptArgs()
layouts = json.load(open(args[0]))

def const_addr(vn):
    if vn is None: return None
    if vn.isConstant(): return vn.getOffset()
    if vn.isAddress():
        try: return vn.getAddress().getOffset()
        except: return None
    return None

# size -> list of (struct_name) ; and addr -> (name,total)
applied = 0; funcs_hit = 0
seen_globals = {}
for hx, L in layouts.items():
    total = L["total"]; name = L["name"]
    sdt = dtm.getDataType("/pb/" + name)
    if sdt is None: continue
    a = A(hx)
    fns = set()
    for r in rm.getReferencesTo(a):
        f = fm.getFunctionContaining(r.getFromAddress())
        if f: fns.add(f)
    for f in fns:
        try:
            res = di.decompileFunction(f, 45, mon)
        except Throwable:
            continue
        if res is None: continue
        hf = res.getHighFunction()
        if hf is None: continue
        hit = False
        for op in hf.getPcodeOps():
            if op.getOpcode() != PcodeOp.CALL: continue
            if const_addr(op.getInput(0)) != ALLOC: continue
            if op.getNumInputs() <= 2: continue
            sz = const_addr(op.getInput(2))
            if sz != total: continue
            gbuf = const_addr(op.getInput(1))
            if gbuf is None: continue
            # buffer is a global holding the struct pointer -> type it as Struct*
            if 0x20000000 <= gbuf < 0x20800000 or 0x400000 <= gbuf < 0x800000:
                if gbuf in seen_globals: continue
                seen_globals[gbuf] = name
                try:
                    ga = A("0x%x" % gbuf)
                    listing.clearCodeUnits(ga, ga.add(3), False)
                    listing.createData(ga, PointerDataType(sdt))
                    applied += 1; hit = True
                except Throwable as e:
                    print("  type fail 0x%x (%s): %s" % (gbuf, name, e))
        if hit: funcs_hit += 1
print("apply_pb_types: typed %d encoder buffer globals across %d functions" % (applied, funcs_hit))
