# -*- coding: utf-8 -*-
# Ghidra headless: fold the inter-lens peer-comms RE (docs/peer_comms_map.md) back into the DB —
# define the peer wire structs, set signatures on the peer send/recv primitives, and stamp the
# type->direction / behaviour findings as comments so future decompilation carries the knowledge.
# @category CFW
from ghidra.program.model.data import (StructureDataType, PointerDataType, CategoryPath,
    DataTypeConflictHandler, VoidDataType, ByteDataType, UnsignedShortDataType,
    UnsignedIntegerDataType, IntegerDataType)
from ghidra.program.model.listing import ParameterImpl, Function
from ghidra.program.model.symbol import SourceType
from ghidra.program.model.listing import CodeUnit
from java.lang import Throwable

dtm = currentProgram.getDataTypeManager(); fm = currentProgram.getFunctionManager()
af = currentProgram.getAddressFactory(); listing = currentProgram.getListing()
def A(h): return af.getAddress(h)
U8=ByteDataType.dataType; U16=UnsignedShortDataType.dataType; U32=UnsignedIntegerDataType.dataType
I32=IntegerDataType.dataType; V=VoidDataType.dataType
def P(dt): return PointerDataType(dt)
REPLACE=DataTypeConflictHandler.REPLACE_HANDLER

# ---- peer wire structs ----
def mkstruct(name, fields):
    ex=dtm.getDataType("/"+name)
    if ex is not None: return ex
    s=StructureDataType(CategoryPath("/"),name,0)
    for (dt,n,fn) in fields: s.add(dt, dt.getLength(), fn, n)
    return dtm.addDataType(s, REPLACE)
mkstruct("peer_msg_hdr_t",[(U8,"TinyFrame type (0-4): 1=bidir userdata,2=R->L appcmd,3=R->L input,4=L->R data","msgType"),
    (U8,"RX dispatch opcode: 9=userdata,1=startup,3=reflash,5=evenhub,7=input,0xc=data,0x10=ctrl","opcode"),
    (U16,"service/app id (routing key on peer)","appID"),(U16,"eventType/flags (0 for _noevent)","eventType"),
    (U16,"payload length (<=10240)","payloadLen")])
mkstruct("peer_tx_desc_t",[(P(V),"reply/callback token","ctx"),(U16,"= msgType (TF type)","type"),
    (U16,"total = payloadLen+8","totalLen"),(P(V),"ptr to peer_msg_hdr_t+payload","payload")])
print("apply_peer: defined peer_msg_hdr_t, peer_tx_desc_t")

# ---- signatures: [addr, ret, [(type,name)...]] ----
SIGS=[
 ("0x463f1a",I32,[(U16,"appID"),(P(V),"data"),(U16,"len"),(P(V),"ctx"),(U8,"opcode"),(U8,"msgType"),(U16,"eventType")]), # post_app_command
 ("0x4644c4",I32,[(U16,"appID"),(P(V),"data"),(U16,"len"),(P(V),"ctx")]),      # send_app_command_to_peer type1/op9 (bidir)
 ("0x46435a",V,[(U16,"appID"),(P(V),"data"),(U16,"len"),(P(V),"ctx")]),         # send_peer_app_cmd_op3 type2/op3 reflash R->L
 ("0x4642d6",I32,[(U16,"appID"),(P(V),"data"),(U16,"len"),(P(V),"ctx")]),       # request_display_startup type2/op1 R->L
 ("0x464462",V,[(P(V),"handle"),(U32,"a2"),(U32,"a3"),(P(V),"a4")]),            # send_peer_app_ctrl_op16 type2/op0x10
 ("0x46471e",I32,[(U16,"msg_id"),(P(V),"data"),(U16,"len"),(P(V),"ctx"),(U16,"sub_id")]), # SendDataToBothExt type1/op9
 ("0x464c28",I32,[(U16,"appID"),(P(V),"data"),(U32,"len"),(P(V),"ctx"),(U16,"eventType")]), # send_data_to_peer type4/op0xc L->R
 ("0x464988",I32,[(U16,"appID"),(P(V),"data"),(U16,"len"),(P(V),"ctx")]),       # send_data_to_peer_noevent type4/op0xc
 ("0x464ef0",V,[(U16,"msg_id"),(U32,"event_a"),(U32,"event_b"),(P(V),"ctx")]),  # send_input_event_to_peers type3/op7 R->L
 ("0x463e98",P(V),[(U32,"size")]),                                              # sync_alloc_retry
 ("0x45c024",U32,[(U32,"timeoutMs")]),                                          # DispStartBlockingEn master-only
 ("0x45c1f0",V,[]),                                                             # DispStartBlockingCancel
 ("0x4652b8",I32,[(U32,"a1"),(U32,"a2"),(U32,"a3"),(P(V),"ctx")]),              # SendIdleCommandtoScheduleManager
 ("0x465524",I32,[(U16,"app_id"),(U32,"a2"),(U32,"a3"),(P(V),"ctx")]),          # SendStartUpCommandtoScheduleManager
]
nsig=0
for addr,ret,ps in SIGS:
    try:
        f=fm.getFunctionAt(A(addr))
        if f is None: print("  no fn @%s"%addr); continue
        params=[ParameterImpl(n,dt,currentProgram) for (dt,n) in ps]
        f.replaceParameters(Function.FunctionUpdateType.DYNAMIC_STORAGE_ALL_PARAMS,True,SourceType.USER_DEFINED,params)
        f.setReturnType(ret,SourceType.USER_DEFINED); nsig+=1
    except Throwable as e: print("  sig fail %s: %s"%(addr,e))
print("apply_peer: set %d peer signatures"%nsig)

# ---- key behaviour comments (plate) ----
CMT={
 "0x463f1a":"post_app_command(appID,data,len,ctx,opcode,msgType,eventType): core peer poster. Builds 8B peer_msg_hdr_t+payload (len<0x2800=10240). msgType=TinyFrame type -> direction (see peer_msg_hdr_t). Alloc 12B peer_tx_desc via sync_alloc_retry; SyncModuleSendDataHandler dequeues + TinyFrame-sends by type.",
 "0x4644c4":"send_app_command_to_peer: type1/op9 BIDIRECTIONAL user-data -> peer app's dataCb (find_ui_DataHandler_by_id). Cleanest R<->L data channel for a custom app.",
 "0x464c28":"send_data_to_peer: type4/op0xc = L->R data channel (master-only listener sched_recv_peer_sync_data). Used by dashboard.ext + our EVT_LCHUNK L-capture relay.",
 "0x46435a":"send_peer_app_cmd_op3: type2/op3 'reflash/present' R->L. The native cross-lens present-forward op.",
 "0x45c024":"DispStartBlockingEn(timeoutMs): MASTER-ONLY gate (real flag @RAM 0x20074e1c, via ptr *0x45c378). CORRECTED 2026-07-19 (traced sched_exec_display_startup 0x45c3dc): this flag ONLY defers opcode==1 (AsyncRequestDisplayStartUp/app-LAUNCH) messages. The opcode==3 (send_peer_app_cmd_op3 reflash/present) dispatch branch @0x45d01e does NOT check this flag -- reflash is never gated by it. So this is an 'open the same app together' lock, NOT a per-frame present barrier. Do not use for delta->0 animation sync.",
 "0x45c1f0":"DispStartBlockingCancel: releases the flag @0x20074e1c set by DispStartBlockingEn. See DispStartBlockingEn comment -- this only affects the opcode==1 (app-launch) gate, not reflash/present.",
 "0x45ba68":"sched_recv_peer_sync_data: RX of type4/op0xc L->R data (opcode check >>8==0xc) -> SendUserDataToThreadPool -> target appID's dataCb.",
 "0x45c3dc":"sched_exec_display_startup: the sync-schedule-manager's message-queue worker thread. Dispatches on (msg>>8)&0xff: op1=AsyncRequestDisplayStartUp (checks the DispStartBlockingEn gate flag @0x20074e1c, defers if set), op3=send_peer_app_cmd_op3/reflash (0x45d01e, NO gate check, unconditionally queues via FUN_00448b0e/2000ms), op5,op7,op0xf,op0x10 also dispatched here.",
}
ncmt=0
for addr,txt in CMT.items():
    try: listing.setComment(A(addr),CodeUnit.PLATE_COMMENT,txt); ncmt+=1
    except Throwable as e: print("  cmt fail %s: %s"%(addr,e))
print("apply_peer: set %d behaviour comments"%ncmt)
