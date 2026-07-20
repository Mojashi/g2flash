# -*- coding: utf-8 -*-
# Ghidra headless: define the RE'd struct types in the DB and apply the concrete ones (app_cfg_t at
# the known cfg globals, lv_image_dsc_t as a usable type) so decompilation shows named fields, and
# set signatures on a few hot functions so their params are typed. @category CFW
from ghidra.program.model.data import (StructureDataType, PointerDataType, UnsignedIntegerDataType,
    UnsignedShortDataType, ByteDataType, IntegerDataType, ArrayDataType, CategoryPath, VoidDataType)
from ghidra.program.model.listing import ParameterImpl
from ghidra.program.model.symbol import SourceType

dtm = currentProgram.getDataTypeManager()
fm = currentProgram.getFunctionManager()
af = currentProgram.getAddressFactory()
listing = currentProgram.getListing()
U32 = UnsignedIntegerDataType.dataType
U16 = UnsignedShortDataType.dataType
U8 = ByteDataType.dataType
I32 = IntegerDataType.dataType
def A(h): return af.getAddress("0x%x" % h)
def P(dt): return PointerDataType(dt)

def mkstruct(name, fields):
    ex = dtm.getDataType("/" + name)
    if ex is not None: return ex
    s = StructureDataType(CategoryPath("/"), name, 0)
    for (dt, n, fn) in fields:
        s.add(dt, dt.getLength() if n == 0 else n, fn, None)
    return dtm.addDataType(s, None)

# ---- struct definitions ----
lv_area = mkstruct("lv_area_t", [(I32,0,"x1"),(I32,0,"y1"),(I32,0,"x2"),(I32,0,"y2")])
lv_img_dsc = mkstruct("lv_image_dsc_t", [
    (U8,0,"magic"),(U8,0,"cf"),(U16,0,"flags"),(U16,0,"w"),(U16,0,"h"),
    (U16,0,"stride"),(U16,0,"reserved"),(U32,0,"data_size"),(P(U8),0,"data")])
app_cfg = mkstruct("app_cfg_t", [
    (U32,0,"page_id"),(U32,0,"root"),(U8,0,"align"),(U8,0,"_p9"),(U8,0,"_pA"),(U8,0,"type"),
    (U32,0,"width"),(U32,0,"height"),(U16,0,"f14"),(U8,0,"f16"),(U8,0,"visible_base"),
    (ArrayDataType(U8,8,1),0,"rest")])
peer_hdr = mkstruct("peer_pkt_hdr_t", [
    (U8,0,"msg_class"),(U8,0,"msg_id"),(U16,0,"app_id"),(U16,0,"event_type"),(U16,0,"len")])
print("types: defined lv_area_t, lv_image_dsc_t, app_cfg_t, peer_pkt_hdr_t")

# ---- apply app_cfg_t at the known cfg globals ----
ncfg = 0
for addr in (0x200005bc, 0x20000b38, 0x20003e30):
    try:
        a = A(addr)
        listing.clearCodeUnits(a, a.add(app_cfg.getLength() - 1), False)
        listing.createData(a, app_cfg); ncfg += 1
    except Exception as e:
        print("cfg apply @0x%x fail: %s" % (addr, e))
print("types: applied app_cfg_t at %d cfg globals" % ncfg)

# ---- set signatures for a few hot functions (return + typed params) ----
def setsig(addr, ret, params):
    try:
        f = fm.getFunctionAt(A(addr))
        if f is None: return 0
        ps = [ParameterImpl(n, dt, currentProgram) for (dt, n) in params]
        from ghidra.program.model.listing import Function
        f.replaceParameters(Function.FunctionUpdateType.DYNAMIC_STORAGE_ALL_PARAMS, True,
                            SourceType.USER_DEFINED, ps)
        f.setReturnType(ret, SourceType.USER_DEFINED)
        return 1
    except Exception as e:
        print("sig @0x%x fail: %s" % (addr, e)); return 0

nsig = 0
nsig += setsig(0x464c28, I32, [(U16,"app_id"),(P(VoidDataType.dataType),"data"),(U32,"len"),(P(VoidDataType.dataType),"ctx"),(U16,"event_type")])   # send_data_to_peer
nsig += setsig(0x4b0f00, VoidDataType.dataType, [(P(VoidDataType.dataType),"obj"),(P(lv_img_dsc),"src")])  # lv_image_set_src
nsig += setsig(0x443904, I32, [(U16,"app_id"),(P(VoidDataType.dataType),"data"),(U32,"len")])              # display_startup
nsig += setsig(0x45f74c, I32, [(P(VoidDataType.dataType),"mgr"),(P(app_cfg),"cfg")])                        # page_manager_register
print("types: set %d hot-function signatures" % nsig)
