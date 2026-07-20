"""
With fsm_state forced to AGENT_PROCESSING(7), run terminal_action_agent_content for
various (op, event) and see which fire the text-render UI event 0x12 (append/show) and
the content-trigger 0x13. Tells us the exact op/event to make text actually appear.
"""
import struct
from g2emu import G2Emu
from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R1

A_AGENT_CONTENT = 0x005ea25c
FIRE_UI = 0x005e535e
CLASSIFY_TEXT_REFRESH = 0x0058ff2a
CTX = 0x2006e0b0
CTX_STATE = CTX + 0x275
GET_CUR_SESSION = 0x0058f870
PROMOTE_SESSION = 0x005e92d2

def build_payload(style, text, op, cid, event, sid):
    b = bytearray(0x214)
    b[0] = style
    b[2:4] = struct.pack("<H", len(text))
    b[4:4+len(text)] = text.encode()
    b[0x204] = op
    b[0x208:0x20c] = struct.pack("<I", cid)
    b[0x20c] = event
    b[0x210:0x214] = struct.pack("<I", sid)
    return bytes(b)

def run(op, event, style=1, text="HELLO"):
    e = G2Emu()
    fires = []
    def fire(em):
        fires.append((em.uc.reg_read(UC_ARM_REG_R0), em.uc.reg_read(UC_ARM_REG_R1)))
        em.uc.reg_write(UC_ARM_REG_R0, 0)
    e.add_stub(FIRE_UI, fire)
    e.call(PROMOTE_SESSION, [1, 1])          # current session = 1
    e.w8(CTX_STATE, 7)                         # AGENT_PROCESSING
    p = e.malloc_scratch(0x300)
    e.wr(p, build_payload(style, text, op, 1, event, 1))
    try:
        rc = e.call(A_AGENT_CONTENT, [p], count=1_000_000)
        rcs = "0x%x" % (rc & 0xffffffff)
    except Exception as ex:
        rcs = "FAULT:%s" % str(ex)[:40]
    evs = ["0x%x" % ev for ev, _ in fires]
    tag = ""
    if any(ev == 0x12 for ev, _ in fires): tag += " TEXT-RENDER(0x12)"
    if any(ev == 0x13 for ev, _ in fires): tag += " CONTENT-TRIG(0x13)"
    print("  op=%d event=%d style=%d -> rc=%s fires=%s%s" % (op, event, style, rcs, evs, tag))

def check_classify():
    """directly probe classify_text_refresh(p,&idx) return for each op."""
    print("classify_text_refresh(FUN_0058ff2a) return by op (nonzero => text accepted):")
    for op in range(0, 5):
        e = G2Emu()
        p = e.malloc_scratch(0x300)
        e.wr(p, build_payload(1, "HELLO", op, 1, 1, 1))
        idx = e.malloc_scratch(4); e.w32(idx, 0)
        try:
            r = e.call(CLASSIFY_TEXT_REFRESH, [p, idx], count=500000)
            print("    op=%d -> refresh=0x%x idx=%d" % (op, r & 0xffffffff, e.u32(idx)))
        except Exception as ex:
            print("    op=%d -> FAULT %s" % (op, str(ex)[:50]))

if __name__ == "__main__":
    check_classify()
    print("\nagent_content fires (state=AGENT_PROCESSING, session matched):")
    for op in (0, 1, 2):
        for event in (0, 1, 2, 3, 4):
            run(op, event)
