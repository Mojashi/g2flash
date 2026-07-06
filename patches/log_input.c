/* log_input.c — TEMPORARY DIAGNOSTIC (remove after gesture->subtype mapping).
 *
 * Hooks the single `bl FUN_004424a2` @0x004436c8 inside the display-thread
 * message loop FUN_00442f00 (the msg-type==7 "input event" case). We log the
 * raw event record, then tail-call the real dispatcher so behavior is
 * unchanged. Purpose: observe which internal gesture SUBTYPE each physical
 * ring/touch gesture produces (esp. long-press vs release-long-press), since
 * the ring's own protobuf codes (TAP/LONG_PRESS/LONG_PRESS_RELEASE/...) are
 * translated to these subtypes somewhere we haven't pinned.
 *
 * Event record layout (r0 = &DAT_00443bbc buffer @ RAM 0x2034e130), as read by
 * FUN_004424a2:  u16 @+0 (field0);  u32 @+2 = SUBTYPE;  u32 @+6 (field2).
 *
 * Logging goes through the compact EasyLogger FUN_0043ce46, which writes
 * unconditionally once logging is initialized (no level gate) into the
 * compress_log ring buffer. The log "word" packs level<<26 | argcount<<22; the
 * logger itself ORs in (fmt & 0x3fffff). A 3-arg call at level 3 == 0x0cc00000,
 * matching the firmware's own 3-vararg log calls. The format-string ADDRESS is
 * passed in as a compile-time constant (FMT_ADDR) so the code stays
 * relocation-free (build.py rejects any .text relocation); patch_input_log.py
 * appends the string to the blob and defines FMT_ADDR to its absolute address.
 */

typedef long long (*logfn_t)(unsigned, const char *, const char *,
                             unsigned, unsigned, unsigned);
typedef int (*dispfn_t)(void *, unsigned);

#define FW_LOG  ((logfn_t)0x0043ce47u)   /* FUN_0043ce46 compact logger (Thumb bit set) */
#define FW_DISP ((dispfn_t)0x004424a3u)  /* FUN_004424a2 input dispatcher (Thumb bit set) */

#ifndef FMT_ADDR
#define FMT_ADDR 0u          /* pass-1 placeholder; real address defined in pass 2 */
#endif

int log_input(unsigned char *evt, unsigned a2)
{
    unsigned f0  = (unsigned)evt[0] | ((unsigned)evt[1] << 8);
    unsigned sub = (unsigned)evt[2] | ((unsigned)evt[3] << 8)
                 | ((unsigned)evt[4] << 16) | ((unsigned)evt[5] << 24);
    unsigned f2  = (unsigned)evt[6] | ((unsigned)evt[7] << 8)
                 | ((unsigned)evt[8] << 16) | ((unsigned)evt[9] << 24);

    FW_LOG((3u << 26) | (3u << 22), (const char *)FMT_ADDR, (const char *)FMT_ADDR,
           f0, sub, f2);

    return FW_DISP(evt, a2);
}
