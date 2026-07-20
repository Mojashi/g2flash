# -*- coding: utf-8 -*-
# Ghidra headless: define the FIRMWARE-EXACT protobuf message structs (from pb_layout.json,
# reconstructed directly from on-device pb_msgdesc_t descriptors) in category /pb, with real
# unions for oneofs and named fields, and label each descriptor global <Name>_msgdesc so the
# DB is navigable. Every struct is created at its exact total size first, so embedded
# submessages resolve correctly regardless of fill order. @category CFW
import json
from ghidra.program.model.data import (StructureDataType, UnionDataType, PointerDataType,
    ArrayDataType, CategoryPath, DataTypeConflictHandler, BooleanDataType, CharDataType,
    ByteDataType, SignedByteDataType, UnsignedShortDataType, ShortDataType,
    UnsignedIntegerDataType, IntegerDataType, UnsignedLongLongDataType, LongLongDataType)
from ghidra.program.model.symbol import SourceType
from ghidra.program.model.listing import CodeUnit
from java.lang import Throwable

dtm = currentProgram.getDataTypeManager()
af = currentProgram.getAddressFactory()
st = currentProgram.getSymbolTable()
listing = currentProgram.getListing()
PB = CategoryPath("/pb")
REPLACE = DataTypeConflictHandler.REPLACE_HANDLER
def A(h): return af.getAddress(h if str(h).startswith("0x") else "0x" + h)

BASE = {
    "bool": BooleanDataType.dataType, "char": CharDataType.dataType,
    "uint8_t": ByteDataType.dataType, "int8_t": SignedByteDataType.dataType,
    "uint16_t": UnsignedShortDataType.dataType, "int16_t": ShortDataType.dataType,
    "uint32_t": UnsignedIntegerDataType.dataType, "int32_t": IntegerDataType.dataType,
    "uint64_t": UnsignedLongLongDataType.dataType, "int64_t": LongLongDataType.dataType,
    "void": ByteDataType.dataType,
}

args = getScriptArgs()
layouts = json.load(open(args[0]))

# ---- Pass A: create every struct at exact total size ----
structs = {}   # name -> resolved DataType
for L in layouts.values():
    nm = L["name"]; tot = max(1, L["total"])
    s = StructureDataType(PB, nm, tot)
    structs[nm] = dtm.addDataType(s, REPLACE)
print("apply_pb: created %d struct stubs" % len(structs))

def resolve(nm):
    if nm in BASE: return BASE[nm]
    d = dtm.getDataType("/pb/" + nm)
    return d if d is not None else structs.get(nm, ByteDataType.dataType)

def place(s, off, dt, name, comment):
    # grow first so there are always enough undefined bytes at the target offset
    need = off + dt.getLength()
    if s.getLength() < need:
        s.growStructure(need - s.getLength())
    try:
        s.replaceAtOffset(off, dt, dt.getLength(), name, comment)
        return True
    except Throwable as e:
        print("  place fail %s.%s @%d (%s len=%d): %s" % (s.getName(), name, off, dt.getName(), dt.getLength(), e))
        return False

# ---- Pass B: fill fields + build unions ----
nfields = 0; nunions = 0
for L in layouts.values():
    s = structs[L["name"]]
    for m in L["metas"]:
        place(s, m["off"], resolve(m["ctype"]), m["name"], m["kind"])
        nfields += 1
    for f in L["fields"]:
        if f["kind"] == "oneof":
            u = UnionDataType(PB, L["name"] + "__u")
            for mem in f["members"]:
                base = resolve(mem["ctype"]) if mem["ctype"] else UnsignedIntegerDataType.dataType
                dt = PointerDataType(base) if mem["ptr"] else base
                try:
                    u.add(dt, dt.getLength(), mem["name"], "tag %d" % mem["tag"])
                except Throwable as e:
                    print("  union add fail %s.%s: %s" % (L["name"], mem["name"], e))
            udt = dtm.addDataType(u, REPLACE)
            place(s, f["off"], udt, "u", "oneof")   # place() grows the struct if needed
            nunions += 1
        else:
            base = resolve(f["ctype"])
            if f["ptr"]:
                dt = PointerDataType(base)
            elif f["kind"] == "string":
                dt = ArrayDataType(CharDataType.dataType, f["ds"], 1)
            elif f["kind"] == "bytes":
                dt = ArrayDataType(ByteDataType.dataType, f["ds"], 1)
            elif f["rep"]:
                dt = ArrayDataType(base, max(1, f["arr"]), base.getLength())
            else:
                dt = base
            place(s, f["off"], dt, f["name"], "tag %d" % f["tag"])
        nfields += 1
print("apply_pb: placed %d fields, %d unions" % (nfields, nunions))

# ---- label each descriptor global <Name>_msgdesc + comment ----
nlbl = 0
for hexaddr, L in layouts.items():
    try:
        a = A(hexaddr)
        st.createLabel(a, L["name"] + "_msgdesc", SourceType.USER_DEFINED)
        listing.setComment(a, CodeUnit.EOL_COMMENT, "pb_msgdesc_t for struct %s (%d fields, %s)"
                           % (L["name"], L["field_count"], L["conf"]))
        nlbl += 1
    except Exception as e:
        print("  label fail %s: %s" % (hexaddr, e))
print("apply_pb: labeled %d descriptor globals" % nlbl)
