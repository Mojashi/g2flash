"""
Does terminal_action_session_status(status=1, id=current) actually fire the UI event
0xf (15 = SESSION_STATUS_UPDATE) that drives IDLE -> AGENT_PROCESSING?

fire_ui_event = FUN_005e535e(event_id, arg).  We stub it to record calls.
We first set current_session = 1 via promote_session(1,1), then feed a
{status=1, id=1} payload. If event 0xf is recorded, the RX logic works and the
hardware non-effect is downstream (FSM task / rendering). If not, we see which gate
(has_pending_notifications etc.) blocked it.
"""
from g2emu import G2Emu
from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R1

PROMOTE_SESSION = 0x005e92d2
GET_CUR_SESSION = 0x0058f870
SESSION_STATUS  = 0x005e9f44   # terminal_action_session_status(payload*)
FIRE_UI_EVENT   = 0x005e535e   # fire_ui_event(event_id, arg)  (also the sid=0x30 notif sender)
HAS_PENDING     = 0x005e9194

def make_emu_with_session(sid=1):
    e = G2Emu()
    events = []
    def fire(emu):
        evt = emu.uc.reg_read(UC_ARM_REG_R0)
        arg = emu.uc.reg_read(UC_ARM_REG_R1)
        events.append((evt, arg))
        emu.uc.reg_write(UC_ARM_REG_R0, 0)
    e.add_stub(FIRE_UI_EVENT, fire)
    e._events = events
    e.call(PROMOTE_SESSION, [sid, 1])
    assert e.call(GET_CUR_SESSION) == sid
    return e, events

def main():
    print("=== session_status(status=1, id=1) with current_session=1 ===")
    e, events = make_emu_with_session(1)
    # has_pending_notifications baseline (real code, RAM zeroed)
    hp = e.call(HAS_PENDING)
    print("has_pending_notifications() (RAM zeroed) = %d" % hp)

    p = e.malloc_scratch(8)
    e.w8(p+0, 1)     # status = 1 (thinking)
    e.w32(p+4, 1)    # id = 1
    r = e.call(SESSION_STATUS, [p])
    print("terminal_action_session_status returned 0x%x" % (r & 0xffffffff))
    print("fire_ui_event calls recorded: %s" % [("0x%x"%ev, arg) for ev,arg in events])
    if any(ev == 0xf for ev,_ in events):
        print(">>> event 0xf (SESSION_STATUS_UPDATE) FIRED -> IDLE should go AGENT_PROCESSING")
    else:
        print(">>> event 0xf NOT fired -- a gate blocked it (see externals below)")
    if e.ext_calls:
        print("externals hit:", ["0x%x"%a for a in sorted(e.ext_calls)])

    print("\n=== control: status=1 but id=2 (mismatched session) ===")
    e2, events2 = make_emu_with_session(1)
    p2 = e2.malloc_scratch(8); e2.w8(p2, 1); e2.w32(p2+4, 2)
    e2.call(SESSION_STATUS, [p2])
    print("fire_ui_event calls: %s (expect none / cached-for-inactive)" %
          [("0x%x"%ev, arg) for ev,arg in events2])

if __name__ == "__main__":
    main()
