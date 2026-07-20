"""
Full happy-path validation in the emulator, using the CORRECTED understanding:
  * the dispatcher selects the action by struct-offset-0 (= outer protobuf field1 value)
  * payload sits at offset 4 (decoded from the oneof submessage, tag = disc+2)

Sequence to drive an external "hijack" from cold terminal mode to rendered agent text:
  1. mode_sync(D=1, mode=2)              -> enter terminal mode (state BOOTSTRAP->CLOSED)
  2. session_id_changed(D=10, id=1)      -> promote_session(1); fires event 35 -> CLOSED->IDLE
  3. session_status(D=4, status=1, id=1) -> id matches current; fires event 15 -> IDLE->AGENT_PROCESSING
  4. agent_content(D=5, ..., event=4, session_id=1) -> fsm_state==7; fires event 0x13 (render)

Each RX action runs for real against the shared terminal state struct @ 0x2006e0b0.
Fired UI events are pumped through the REAL terminal_ui_fsm_handler to advance fsm_state
(ctx+0x275), modelling the two-task (RX task posts event, UI task consumes) design.
"""
from g2emu import G2Emu
from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R1

# actions
A_MODE_SYNC = 0x005e97d2
A_HOST_STATUS = 0x005e9b0c
A_SESSION_STATUS = 0x005e9f44
A_AGENT_CONTENT = 0x005ea25c
A_SESSION_ID_CHANGED = 0x005eae40
PROMOTE_SESSION = 0x005e92d2
GET_CUR_SESSION = 0x0058f870
FIRE_UI = 0x005e535e
FSM_HANDLER = 0x005e8b00       # terminal_ui_fsm_handler(event_id)
CTX = 0x2006e0b0
CTX_STATE = CTX + 0x275
LINK_GLOBAL_LIT = 0x47aa28     # flash literal -> RAM byte read by link_check

STATE_NAMES = ["BOOTSTRAP","CLOSED","IDLE","BLOCKED","VOICE_CAPTURING","ASR_STREAMING",
               "ASR_FINAL","AGENT_PROCESSING","AGENT_INTERRUPT_CONFIRM","QUERY_PENDING",
               "QUERY_NOTIFICATION","SESSION_LIST","NEW_SESSION_PENDING"]

def sname(i):
    return STATE_NAMES[i] if i < len(STATE_NAMES) else "?%d" % i

class Sim:
    def __init__(self):
        e = G2Emu()
        self.e = e
        self.fires = []
        def fire(em):
            self.fires.append((em.uc.reg_read(UC_ARM_REG_R0), em.uc.reg_read(UC_ARM_REG_R1)))
            em.uc.reg_write(UC_ARM_REG_R0, 0)
        e.add_stub(FIRE_UI, fire)
        # spoof host link "up": link_check reads (*global & 0xc)==0xc
        e.w8(e.u32(LINK_GLOBAL_LIT), 0x0C)

    def state(self):
        return self.e.u8(CTX_STATE)

    def set_state(self, s):
        self.e.w8(CTX_STATE, s)

    def run_action(self, addr, payload, label):
        e = self.e
        p = e.malloc_scratch(max(len(payload), 4) + 16)
        e.wr(p, b"\x00" * (len(payload) + 16))
        if payload:
            e.wr(p, payload)
        self.fires = []
        st_before = self.state()
        try:
            rc = e.call(addr, [p], count=1_000_000)
            rcs = "0x%x" % (rc & 0xffffffff)
        except Exception as ex:
            rcs = "EMU-FAULT(%s)" % str(ex)[:60]
        fired = [(ev, arg) for ev, arg in self.fires]
        print("  [%s] rc=%s  state %d(%s)  fired=%s" %
              (label, rcs, st_before, sname(st_before),
               [("evt0x%x" % ev, arg) for ev, arg in fired]))
        # pump each fired event through the real FSM handler
        for ev, arg in fired:
            self.pump(ev)
        return fired

    def pump(self, event_id):
        e = self.e
        before = self.state()
        try:
            e.call(FSM_HANDLER, [event_id], count=1_000_000)
            after = self.state()
            if after != before:
                print("      FSM: event 0x%x : %d(%s) -> %d(%s)" %
                      (event_id, before, sname(before), after, sname(after)))
        except Exception as ex:
            # UI handler faulted deep; fall back to static table default
            cell = 0x0064fd78 + before * 0x140 + event_id * 8
            dn = e.u8(cell)
            print("      FSM: event 0x%x handler faulted (%s); table default -> %d(%s)" %
                  (event_id, str(ex)[:40], dn, sname(dn)))
            self.set_state(dn)

def main():
    s = Sim()
    print("initial state = %d(%s)" % (s.state(), sname(s.state())))

    print("\nStep 1: mode_sync(mode=2)")
    s.run_action(A_MODE_SYNC, bytes([2, 0]), "mode_sync")
    print("   -> state now %d(%s)" % (s.state(), sname(s.state())))

    # ensure we're in CLOSED(1) to model post-mode-switch (BOOTSTRAP fires event1->CLOSED)
    if s.state() == 0:
        s.set_state(1)
        print("   (modelling BOOTSTRAP->CLOSED auto-transition; state=1)")

    print("\nStep 1b: host_status(status=2 streaming)")
    s.run_action(A_HOST_STATUS, bytes([2, 0]), "host_status")
    print("   -> state now %d(%s)" % (s.state(), sname(s.state())))

    print("\nStep 2: session_id_changed(id=1)")
    import struct
    s.run_action(A_SESSION_ID_CHANGED, struct.pack("<I", 1), "session_id_changed")
    cur = s.e.call(GET_CUR_SESSION)
    print("   -> state now %d(%s); get_current_session_id()=%d" % (s.state(), sname(s.state()), cur))

    print("\nStep 3: session_status(status=1 thinking, id=1)")
    s.run_action(A_SESSION_STATUS, bytes([1,0,0,0]) + struct.pack("<I", 1), "session_status")
    print("   -> state now %d(%s)" % (s.state(), sname(s.state())))

    print("\nStep 4: agent_content(style=1, text='HELLO', op=1, id=1, event=4, session_id=1)")
    # struct: style@0(u8), text_len@2(u16), text@4[0x200], op@0x204(u8), id@0x208(u32),
    #         event@0x20c(u8), session_id@0x210(u32)   -- total 0x214
    txt = b"HELLO"
    payload = bytearray(0x214)
    payload[0] = 1                                   # style
    payload[2:4] = struct.pack("<H", len(txt))       # text_len
    payload[4:4+len(txt)] = txt                      # text
    payload[0x204] = 1                                # op
    payload[0x208:0x20c] = struct.pack("<I", 1)      # id
    payload[0x20c] = 4                                # event = 4 (final/refresh)
    payload[0x210:0x214] = struct.pack("<I", 1)      # session_id
    fired = s.run_action(A_AGENT_CONTENT, bytes(payload), "agent_content")
    print("   -> state now %d(%s)" % (s.state(), sname(s.state())))
    if any(ev == 0x13 for ev, _ in fired):
        print("\n>>> SUCCESS: agent_content fired event 0x13 (CONTENT render trigger)!")
    else:
        print("\n>>> agent_content did NOT fire 0x13; fires=%s" % fired)

if __name__ == "__main__":
    main()
