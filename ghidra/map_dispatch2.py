"""
Corrected dispatch map: FUN_005e5590 reads the discriminant from struct OFFSET 0
(= outer protobuf field1/tag1's VALUE), and the payload sits at OFFSET 4.
Build {disc@0, payload@4} and dispatch each discriminant 1..11 to confirm the action.
"""
from g2emu import G2Emu

DISPATCH = 0x005e5590
FIRE_UI  = 0x005e535e
ACTIONS = {
    0x005e97d2: "mode_sync",  0x005e9b0c: "host_status", 0x005e9d40: "asr_result",
    0x005e9f44: "session_status", 0x005ea25c: "agent_content", 0x005ea7cc: "query",
    0x005ea9d4: "error_msg", 0x005eab40: "session_list", 0x005ead30: "session_switch_result",
    0x005eae40: "session_id_changed", 0x005ead94: "new_session_result", 0x005ea984: "heart_beat",
}

def probe(disc, payload=b""):
    e = G2Emu()
    from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R1
    fires = []
    def fire(em):
        fires.append((em.uc.reg_read(UC_ARM_REG_R0), em.uc.reg_read(UC_ARM_REG_R1)))
        em.uc.reg_write(UC_ARM_REG_R0, 0)
    e.add_stub(FIRE_UI, fire)
    for a, n in ACTIONS.items():
        e.add_watch(a, n)
    st = e.malloc_scratch(0x900); e.wr(st, b"\x00" * 0x900)
    e.w8(st, disc)                       # discriminant at offset 0
    if payload:
        e.wr(st + 4, payload)            # payload at offset 4
    try:
        e.call(DISPATCH, [st], count=300000)
    except Exception:
        pass
    return (e.hits[0][0] if e.hits else None), fires

if __name__ == "__main__":
    print("discriminant(=outer field1 value) -> action")
    for d in range(1, 12):
        a, _ = probe(d)
        print("  field1=%2d -> %s" % (d, a or "(none)"))
    for d in (0xa3, 0xff):
        a, _ = probe(d)
        print("  field1=0x%x -> %s" % (d, a or "(none)"))
