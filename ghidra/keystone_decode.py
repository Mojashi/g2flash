"""
KEYSTONE EXPERIMENT: resolve the wire-tag <-> discriminant contradiction definitively.

Feed real wire bytes into the actual firmware RX decode+dispatch chain
(terminal_rx_wrapper -> RxFrameDataProcess[decode into 0x2010d9ac] -> FUN_005e5590[dispatch])
and observe:
  * the decoded struct: discriminant@0, magic@1, union@4
  * which of the 13 action functions actually runs (watchpoints on each entry)
  * any fire_ui_event / BLE-send side effects

If the known-working mode_sync bytes (outer wire tag=3) land on terminal_action_mode_sync,
then wire tag 3 == mode_sync is ground truth, and we can read off the whole mapping.
"""
from g2emu import G2Emu

RX_WRAPPER   = 0x005e5414   # terminal_rx_wrapper(param1=0, payload, len)
RX_LOCK      = 0x005e531a
RX_UNLOCK    = 0x005e534a
COMMRESP     = 0x005cfa04
FIRE_UI      = 0x005e535e
DECODE_BUF   = 0x2010d9ac   # DAT_005e5720

ACTIONS = {
    0x005e97d2: "mode_sync",       0x005e9b0c: "host_status",
    0x005e9d40: "asr_result",      0x005e9f44: "session_status",
    0x005ea25c: "agent_content",   0x005ea7cc: "query",
    0x005ea9d4: "error_msg",       0x005eab40: "session_list",
    0x005ead30: "session_switch_result", 0x005eae40: "session_id_changed",
    0x005ead94: "new_session_result",    0x005ea984: "heart_beat",
}

def new_emu():
    e = G2Emu()
    e.add_stub(RX_LOCK, lambda em: None)
    e.add_stub(RX_UNLOCK, lambda em: None)
    fires = []
    def fire(em):
        from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R1
        fires.append((em.uc.reg_read(UC_ARM_REG_R0), em.uc.reg_read(UC_ARM_REG_R1)))
        em.uc.reg_write(UC_ARM_REG_R0, 0)
    e.add_stub(FIRE_UI, fire)
    commresps = []
    def commresp(em):
        from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R1
        commresps.append((em.uc.reg_read(UC_ARM_REG_R0), em.uc.reg_read(UC_ARM_REG_R1)))
        em.uc.reg_write(UC_ARM_REG_R0, 0)
    e.add_stub(COMMRESP, commresp)
    for addr, name in ACTIONS.items():
        e.add_watch(addr, name)
    e._fires = fires
    e._commresps = commresps
    return e

def run_frame(label, hexbytes):
    e = new_emu()
    raw = bytes.fromhex(hexbytes.replace(" ", ""))
    p = e.malloc_scratch(len(raw) + 16)
    e.wr(p, raw)
    print("\n=== %s ===\n  wire bytes: %s" % (label, raw.hex()))
    try:
        e.call(RX_WRAPPER, [0, p, len(raw)])
    except Exception as ex:
        print("  emu error: %s" % ex)
        print("  hits so far:", e.hits)
        if e.ext_calls:
            print("  externals:", ["0x%x" % a for a in sorted(e.ext_calls)])
        return
    disc = e.u8(DECODE_BUF + 0)
    magic = e.u8(DECODE_BUF + 1)
    union0 = e.u32(DECODE_BUF + 4)
    print("  decoded struct: discriminant=%d  magic=%d  union[0]=0x%x" % (disc, magic, union0))
    print("  ACTION fired: %s" % ([h[0] for h in e.hits] or "(none)"))
    print("  fire_ui_event: %s" % [("0x%x" % ev, arg) for ev, arg in e._fires])
    if e.ext_calls:
        print("  externals hit:", ["0x%x" % a for a in sorted(e.ext_calls)])

if __name__ == "__main__":
    # The confirmed-working mode_sync payload: outer{ f1(varint)=1(magic), f3(submsg)={f1=2} }
    run_frame("mode_sync via OUTER wire tag=3 (hardware-confirmed)", "08 01 1a 02 08 02")
    # Counter-test: what does OUTER wire tag=1 do (RX agent's claim: discriminant 1 = mode_sync)?
    run_frame("OUTER wire tag=1 submessage {f1=2}", "08 01 0a 02 08 02")
    # session_status candidates: outer tag 6 (my +2 hypothesis) vs outer tag 4 (disc directly)
    run_frame("OUTER wire tag=6 {f1=1,f2=1}", "08 01 32 04 08 01 10 01")
    run_frame("OUTER wire tag=4 {f1=1,f2=1}", "08 01 22 04 08 01 10 01")
