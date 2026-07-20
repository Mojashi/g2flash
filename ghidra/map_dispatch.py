"""
Definitive wire-tag -> action map: build the decoded struct by hand
(magic@0, seq@1, which_msg@2:u16, union@4) and call the dispatcher FUN_005e5590
directly for each which_msg value 1..25. Record which of the 13 action functions
runs (watchpoint on entry, captured even if the action later faults deep in UI code).
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

def probe_which(which):
    e = G2Emu()
    e.add_stub(FIRE_UI, lambda em: None)
    for a, n in ACTIONS.items():
        e.add_watch(a, n)
    st = e.malloc_scratch(0x900)
    e.wr(st, b"\x00" * 0x900)
    e.w8(st + 0, 1)              # magic
    e.w8(st + 1, 1)              # seq
    e.wr(st + 2, bytes([which & 0xff, (which >> 8) & 0xff]))  # which_msg u16
    # leave union (st+4..) zeroed
    action = None
    try:
        e.call(DISPATCH, [st], count=200000)
    except Exception:
        pass
    if e.hits:
        action = e.hits[0][0]
    return action

if __name__ == "__main__":
    print("which_msg -> action (via real dispatcher FUN_005e5590)")
    print("(recall: on the wire this which_msg IS the outer protobuf field tag)")
    for w in range(1, 26):
        a = probe_which(w)
        print("  which/wiretag %2d -> %s" % (w, a or "(no action / unmapped)"))
