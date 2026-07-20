"""Keystone v2: call decode + dispatch explicitly, dump raw struct, capture rc."""
from g2emu import G2Emu

RX_FRAME_PROC = 0x005cf8a8   # RxFrameDataProcess(payload, len, out_buf) -> rc
DISPATCH      = 0x005e5590   # FUN_005e5590(decoded_struct) -> action rc
RX_LOCK = 0x005e531a; RX_UNLOCK = 0x005e534a; COMMRESP = 0x005cfa04; FIRE_UI = 0x005e535e

ACTIONS = {
    0x005e97d2: "mode_sync",  0x005e9b0c: "host_status", 0x005e9d40: "asr_result",
    0x005e9f44: "session_status", 0x005ea25c: "agent_content", 0x005ea7cc: "query",
    0x005ea9d4: "error_msg", 0x005eab40: "session_list", 0x005ead30: "session_switch_result",
    0x005eae40: "session_id_changed", 0x005ead94: "new_session_result", 0x005ea984: "heart_beat",
}

def new_emu():
    e = G2Emu()
    for a in (RX_LOCK, RX_UNLOCK):
        e.add_stub(a, lambda em: None)
    fires = []
    from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R1
    def fire(em):
        fires.append((em.uc.reg_read(UC_ARM_REG_R0), em.uc.reg_read(UC_ARM_REG_R1)))
        em.uc.reg_write(UC_ARM_REG_R0, 0)
    e.add_stub(FIRE_UI, fire)
    e.add_stub(COMMRESP, lambda em: None)
    for addr, name in ACTIONS.items():
        e.add_watch(addr, name)
    e._fires = fires
    return e

def run(label, hexbytes):
    e = new_emu()
    raw = bytes.fromhex(hexbytes.replace(" ", ""))
    payload = e.malloc_scratch(len(raw) + 16); e.wr(payload, raw)
    out = e.malloc_scratch(64); e.wr(out, b"\xEE" * 64)  # poison so we see what's written
    print("\n=== %s ===  bytes=%s" % (label, raw.hex()))
    try:
        rc = e.call(RX_FRAME_PROC, [payload, len(raw), out])
    except Exception as ex:
        print("  decode emu error: %s" % ex); return
    print("  RxFrameDataProcess rc=%d (0=ok,5=decodefail,6=null,0xd=dup)" % (rc & 0xffffffff))
    print("  decoded struct[0:16] = %s" % e.rd(out, 16).hex())
    print("    byte0=%d byte1=%d byte2(which?)=%d  u16@2=%d  union@4=0x%x" %
          (e.u8(out), e.u8(out+1), e.u8(out+2),
           int.from_bytes(e.rd(out+2,2),"little"), e.u32(out+4)))
    if rc & 0xffffffff == 0:
        e.hits = []
        try:
            drc = e.call(DISPATCH, [out])
        except Exception as ex:
            print("  dispatch emu error: %s" % ex); return
        print("  dispatch rc=%d  ACTION=%s  fire_ui=%s" %
              (drc & 0xffffffff, [h[0] for h in e.hits] or "(none)",
               [("0x%x"%ev,arg) for ev,arg in e._fires]))

if __name__ == "__main__":
    run("mode_sync outer tag=3 (HW-confirmed)", "08 01 1a 02 08 02")
    run("outer tag=1 {f1=2}", "08 01 0a 02 08 02")
    run("outer tag=6 {f1=1,f2=1}", "08 01 32 04 08 01 10 01")
    run("outer tag=4 {f1=1,f2=1}", "08 01 22 04 08 01 10 01")
    run("outer tag=5 {f1=1,f2=1}", "08 01 2a 04 08 01 10 01")
