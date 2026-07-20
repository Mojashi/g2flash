# -*- coding: utf-8 -*-
# Ghidra headless: apply corrections to earlier (now-invalidated) RE claims, so the DB doesn't keep
# carrying a wrong plate comment forward. Each entry documents WHAT was claimed, WHAT was actually
# found on re-verification, and the evidence. Per feedback_re_into_db: corrections belong in the DB
# too, not just in a memory file. @category CFW
from ghidra.program.model.listing import CodeUnit
from java.lang import Throwable
af = currentProgram.getAddressFactory(); listing = currentProgram.getListing()
def A(h): return af.getAddress(h)

CORRECTIONS = {
 "0x572648": ("anim_gate_sync_tick: decompiles as a per-gate lens_side()-branched wait/release barrier for an "
    "lv_anim (module tag 'even_ai.animation'). CORRECTED 2026-07-19: 0 references of ANY kind found to this "
    "address (no direct BL, no movw/movt register load of 0x2648/0x57, no raw literal-pool word anywhere in "
    "0x438000-0x78f188). Cannot confirm this is ever invoked -- may be dead/vestigial code, or reached via an "
    "addressing idiom not yet found. Do NOT assume this backs list/menu scroll sync: that is separately "
    "CONFIRMED (traced) to be menu_inject_event -> send_input_event_to_peers (type3/op7) -> "
    "SlaveInputEventReplyListener -> FUN_00443cb8, which just xQueueSend's the raw input event into the LOCAL "
    "queue (no anim/render call) -- i.e. a one-shot input-forward, then each lens runs its own independent "
    "deterministic LVGL scroll physics. See reference_g2_interlens_transmit memory."),
}
n = 0
for addr, txt in CORRECTIONS.items():
    try:
        listing.setComment(A(addr), CodeUnit.PLATE_COMMENT, txt); n += 1
    except Throwable as e:
        print("  fail %s: %s" % (addr, e))
print("apply_corrections: applied %d correction(s)" % n)
