# -*- coding: utf-8 -*-
# Ghidra headless: apply function signatures from the typing-workflow output (sigs.json:
# [{addr,name,ret,params:[{type,name}]}]). Maps the constrained type vocabulary to Ghidra data
# types (defining opaque LVGL structs so pointer types show by name). @category CFW
import json
from ghidra.program.model.data import (StructureDataType, PointerDataType, CategoryPath,
    VoidDataType, BooleanDataType, CharDataType, UnsignedIntegerDataType, UnsignedShortDataType,
    ByteDataType, IntegerDataType, ShortDataType, SignedByteDataType)
from ghidra.program.model.listing import ParameterImpl, Function
from ghidra.program.model.symbol import SourceType

dtm = currentProgram.getDataTypeManager()
fm = currentProgram.getFunctionManager()
af = currentProgram.getAddressFactory()
def A(h): return af.getAddress(h if h.startswith("0x") else "0x" + h)

def opaque(name):
    ex = dtm.getDataType("/" + name)
    if ex is not None: return ex
    s = StructureDataType(CategoryPath("/"), name, 0)
    s.add(ByteDataType.dataType, 1, "opaque", None)   # 1-byte placeholder so pointers resolve
    return dtm.addDataType(s, None)

def get(name):
    return dtm.getDataType("/" + name)

for n in ("lv_obj_t","lv_display_t","lv_point_t","lv_event_t","lv_anim_t","lv_style_t","lv_timer_t"):
    if get(n) is None: opaque(n)

BASE = {
    "void": VoidDataType.dataType, "bool": BooleanDataType.dataType, "char": CharDataType.dataType,
    "u8": ByteDataType.dataType, "u16": UnsignedShortDataType.dataType, "u32": UnsignedIntegerDataType.dataType,
    "i8": SignedByteDataType.dataType, "i16": ShortDataType.dataType, "i32": IntegerDataType.dataType,
    "size_t": UnsignedIntegerDataType.dataType,
}
def get_any(name):
    # search / first, then the /pb category (firmware-exact protobuf message structs)
    d = dtm.getDataType("/" + name)
    if d is None: d = dtm.getDataType("/pb/" + name)
    return d

def resolve(ts):
    ts = (ts or "u32").strip()
    if ts in BASE: return BASE[ts]
    if ts.endswith("*"):
        inner = ts[:-1].strip()
        if inner in BASE: return PointerDataType(BASE[inner])
        dt = get_any(inner)
        if dt is None: dt = opaque(inner) if inner.startswith("lv_") or inner.endswith("_t") else None
        return PointerDataType(dt) if dt is not None else PointerDataType(VoidDataType.dataType)
    dt = get_any(ts)
    return dt if dt is not None else UnsignedIntegerDataType.dataType

args = getScriptArgs()
sigs = json.load(open(args[0]))
applied = 0; fail = 0
for s in sigs:
    try:
        f = fm.getFunctionAt(A(s["addr"]))
        if f is None: continue
        ps = []
        for p in s.get("params", []):
            ps.append(ParameterImpl(p.get("name", "a"), resolve(p.get("type")), currentProgram))
        f.replaceParameters(Function.FunctionUpdateType.DYNAMIC_STORAGE_ALL_PARAMS, True,
                            SourceType.USER_DEFINED, ps)
        f.setReturnType(resolve(s.get("ret", "u32")), SourceType.USER_DEFINED)
        applied += 1
    except Exception as e:
        fail += 1
print("apply_sigs: applied %d signatures, %d failed" % (applied, fail))
