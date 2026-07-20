"""
High-value probe: does session_id_changed's promote_session(id) actually make
get_current_session_id() return that id, or is a session_list required first?
Also statically dump the FSM transition grid to verify RECONSTRUCTED_fsm.md.
"""
import struct
from g2emu import G2Emu

PROMOTE_SESSION      = 0x005e92d2   # FUN_005e92d2 promote_session(id, flag)
GET_CUR_SESSION      = 0x0058f870   # FUN_0058f870 get_current_session_id()
SESSION_ID_CHANGED   = 0x005eae40   # terminal_action_session_id_changed(u32* p)
FSM_TABLE_BASE       = 0x0064fd78
STATE_NAMES = ["BOOTSTRAP","CLOSED","IDLE","BLOCKED","VOICE_CAPTURING","ASR_STREAMING",
               "ASR_FINAL","AGENT_PROCESSING","AGENT_INTERRUPT_CONFIRM","QUERY_PENDING",
               "QUERY_NOTIFICATION","SESSION_LIST","NEW_SESSION_PENDING"]

def dump_fsm_cell(e, state, event):
    cell = FSM_TABLE_BASE + state*0x140 + event*8
    default_next = e.u8(cell)
    handler = e.u32(cell+4)
    return default_next, handler

def main():
    e = G2Emu()

    print("=== Q1: is get_current_session_id() controllable / what does it read? ===")
    cur = e.call(GET_CUR_SESSION)
    print("initial get_current_session_id() = %d (RAM zeroed)" % cur)

    print("\n=== Q2: does promote_session(1,1) set the current session? ===")
    try:
        r = e.call(PROMOTE_SESSION, [1, 1])
        cur = e.call(GET_CUR_SESSION)
        print("promote_session(1,1) returned %d; get_current_session_id() = %d" % (r, cur))
        if e.ext_calls:
            print("  external (below-image) calls hit during promote_session:")
            for a, c in sorted(e.ext_calls.items()):
                print("    0x%x x%d" % (a, c))
    except Exception as ex:
        print("promote_session raised: %s" % ex)
        print("  mem log tail:", e.log[-6:])

    print("\n=== Q3: full session_id_changed RX action (id=1) then get_current_session_id ===")
    e2 = G2Emu()
    pid = e2.malloc_scratch(4); e2.w32(pid, 1)
    try:
        r = e2.call(SESSION_ID_CHANGED, [pid])
        cur = e2.call(GET_CUR_SESSION)
        print("session_id_changed(id=1) returned 0x%x; get_current_session_id() = %d" % (r, cur))
        if e2.ext_calls:
            print("  externals hit:", ["0x%x" % a for a in sorted(e2.ext_calls)])
    except Exception as ex:
        print("session_id_changed raised: %s" % ex)
        print("  mem log tail:", e2.log[-6:])

    print("\n=== Q4: static FSM grid sanity (IDLE row, key events) ===")
    e3 = G2Emu()
    for ev in (8, 15, 35):  # voice_start, session_status_update, session_id_changed
        dn, h = dump_fsm_cell(e3, 2, ev)  # state 2 = IDLE
        tgt = STATE_NAMES[dn] if dn < len(STATE_NAMES) else "?"
        print("  IDLE  event %2d -> default_next=%d(%s) handler=0x%x" % (ev, dn, tgt, h))
    print("  (expect: event8 voice_start->VOICE_CAPTURING, event15 status->AGENT_PROCESSING, event35->IDLE self)")

if __name__ == "__main__":
    main()
