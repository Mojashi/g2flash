/* screenshot.c -- on-demand on-lens framebuffer screenshot for the G2 CFW.
 *
 * Captures the REAL panel framebuffer that LVGL renders the on-screen UI into
 * (terminal text, dashboard, menus -- whatever is actually on the lens), runs a
 * single-pass grayscale QOI codec over it (no malloc, bounded stack scratch), and
 * streams the compressed image to the phone as a sequence of aa21 no-ack frames on
 * a dedicated sid (0x7d), using the firmware's own send primitive FUN_0047398c --
 * the same primitive settings_ext.c / dbg_terminal.c reuse.
 *
 * This translation unit is ADDED alongside dbg_terminal.c (the debug CFW) and the
 * image/display glue (zlib_glue.c) via patches_main.c -- a superset build. It shares
 * no macro/typedef/function name with the other patch sources (everything here is
 * prefixed ss_ / SS_ / cfw_screenshot_).
 *
 * ---------------------------------------------------------------------------
 * FRAMEBUFFER (see patches/SCREENSHOT_CFW.md for the disassembly evidence):
 *   The panel is 576x288. LVGL v9.3 (Ambiq NemaGFX) renders the composited UI into
 *   a full-frame draw buffer; SS_FB_* below points the capture at that buffer and
 *   its pixel format. These constants are the ONLY placement-dependent knobs; the
 *   codec/protocol below are format-agnostic (they consume an 8bpp gray byte/pixel,
 *   unpacking 4bpp nibbles to gray = nibble*17 when SS_FB_BPP == 4).
 *
 * QOI grayscale variant (1 channel), ops (first byte):
 *   0x00..0x3F INDEX (idx=b&0x3F -> index[idx])
 *   0x40..0x7F DIFF  (d=(b&0x3F)-32 -> prev+d, d in -32..31)
 *   0xC0..0xFD RUN   (n=(b&0x3F)+1, repeat prev, n in 1..62)
 *   0xFE       GRAY  (literal: next byte is the raw gray value)
 *   index updated on DIFF/GRAY only; prev on INDEX/DIFF/GRAY; HASH(v)=(v*15)&63.
 *
 * Reassembled blob: "G2SS",ver,flags,w:u16,h:u16, QOI..., trailer{qoi_len:u32, crc32:u32}.
 * Fragment (sid 0x7d): {0xA5,ver,frag_index:u16, flags(bit0=LAST), 0, payload_len:u16, payload}.
 * CRC32 is the standard zlib/PNG CRC of the QOI stream bytes only.
 */
#include <stdint.h>

/* --- firmware entry point: aa21 no-ack send (type=1, sid, ptr, len). Same as the
 * primitive settings_ext.c / dbg_terminal.c use; self-gates on link readiness and
 * is a safe no-op off the transmitting side. Called by absolute Thumb address. --- */
typedef int (*ss_send_fn)(int type, int sid, void *ptr, int len);
#define SS_FW_SEND ((ss_send_fn)0x0047398dU)      /* FUN_0047398c | thumb bit */
typedef uint32_t (*ss_side_fn)(void);
#define SS_FW_SIDE ((ss_side_fn)0x0045a8edU)       /* FUN_0045a8ec -> 2=left, 1=right */
/* Universal inbound-frame dispatcher (FUN_00441c68): the single bl @0x0045aaa4 that
 * every sid-routed app frame passes through, before any per-UI handler. cap_rx_hook
 * replaces that bl, inspects the frame, then tail-calls this so all normal traffic is
 * unaffected (an unknown sid like 0x7d is a harmless no-op inside it). */
typedef int (*ss_disp_fn)(uint32_t sid, void *payload, uint32_t len, uint32_t subcode);
#define SS_FW_DISPATCH ((ss_disp_fn)0x00441c69U)   /* FUN_00441c68 | thumb bit */

/* Screenshot trigger: an inbound frame on the (otherwise unused) serviceID 0x7d whose
 * payload begins with the capture opcode. 0x7d is confirmed absent from the 41-entry
 * service table, so co-opting it disturbs no real handler. */
#define SS_TRIGGER_SID   0x7d
#define SS_TRIGGER_OP    0xC7    /* payload[0]: "please capture" opcode */

/* --- protocol constants (must match demos/screenshot.ts and scratchpad/qoi_ref.py) --- */
#define SS_SID              0x7d
#define SS_FRAG_MAGIC       0xA5
#define SS_VER              0x01
#define SS_FRAG_PAYLOAD_MAX 192      /* frame = 8 hdr + <=192 payload = <=200 B (< ~232 aa21 cap) */
#define SS_FLAG_LAST        0x01
#define SS_FLAG_UPFILTER    0x01     /* blob flags bit0 */

#define QOI_GRAY_HASH(v) (((uint32_t)(v) * 15u) & 63u)

/* --- FRAMEBUFFER placement (full disassembly evidence in patches/SCREENSHOT_CFW.md).
 * DEFAULT: the JBD4010 panel scan-out canvas -- the exact buffer the microLED QSPI DMA
 * reads, i.e. what the wearer physically sees. Confirmed by disassembling the panel
 * driver's PartialReflash (0x589290) and FullReflash (0x5893c6): the per-row source is
 *   canvas = *(uint32_t*)0x20074464;         // driver global, set by jbd4010 init
 *   src(x,y) = canvas + y*320 + (x>>1);       // stride 0x140 = 320, i.e. 4bpp, 640 wide
 * with the address space clamped to 640x480 (x2<=0x27f, y2<=0x1df). So the panel canvas
 * is 640x480, 4bpp (2 px/byte, high nibble = even/left x), stride 320, tightly packed
 * (307200 px / 2 = 153600 B). The firmware composites the 576x288 LVGL UI into this
 * larger canvas at offset ~(32,96); the surrounding border is cleared. Capturing the
 * full 640x480 needs no offset assumption and is exactly the physical panel image.
 * nibble n -> gray n*17 (0..255), the display's native 16-level depth.
 *
 * The pointer is read at runtime (SRAM-range-checked); if it is 0/invalid before the
 * driver is up, cfw_screenshot_run() safely does nothing.
 *
 * ALTERNATIVE (-DSS_FB_L8): the LVGL render target BEFORE down-conversion -- L8/8bpp,
 * 576x288, richer but one stage upstream of the panel. Deref *(*(u32*)0x200745cc+0x10)
 * (lv_draw_buf_t.data). Provided for completeness; the panel canvas is the true
 * "what's on the lens". */
#ifndef SS_UP_FILTER
#define SS_UP_FILTER 0        /* off by default (RUN already handles horizontal flats) */
#endif

#ifdef SS_FB_L8
#define SS_FB_W 576u
#define SS_FB_H 288u
#define SS_FB_BPP 8u
#define SS_FB_DRAWBUF_PTR 0x200745ccU  /* -> lv_draw_buf_t* (LVGL L8 render target) */
#define SS_FB_DATA_OFF    0x10U        /* lv_draw_buf_t.data */
#else
#define SS_FB_W 640u
#define SS_FB_H 480u
#define SS_FB_BPP 4u
#define SS_FB_CANVAS_PTR  0x20074464U  /* jbd4010 driver global -> panel canvas base */
#endif

static inline int ss_in_sram(uintptr_t p) { return (p - 0x20000000u) < 0x00800000u; }

/* Resolve the live framebuffer base pointer, range-checked to SRAM (returns 0 on any
 * out-of-range deref, so cfw_screenshot_run() then safely does nothing). The codec and
 * protocol are validated independently in the emulator via cfw_screenshot_capture()
 * with an explicit buffer, so this resolver is the only placement-dependent piece. */
static const uint8_t *ss_fb_ptr(void) {
#ifdef SS_FB_L8
    uintptr_t db = *(volatile uintptr_t *)(uintptr_t)SS_FB_DRAWBUF_PTR;
    if (!ss_in_sram(db)) return 0;
    uintptr_t data = *(volatile uintptr_t *)(db + SS_FB_DATA_OFF);
    if (!ss_in_sram(data)) return 0;
    return (const uint8_t *)data;
#else
    uintptr_t canvas = *(volatile uintptr_t *)(uintptr_t)SS_FB_CANVAS_PTR;
    if (!ss_in_sram(canvas)) return 0;
    return (const uint8_t *)canvas;
#endif
}

/* ---- streaming fragment emitter + QOI encoder state (all on the caller's stack) --- */
typedef struct {
    uint8_t  frag[8 + SS_FRAG_PAYLOAD_MAX];  /* current outbound aa21 frame */
    uint32_t fill;        /* payload bytes staged in frag[8..] */
    uint16_t frag_index;  /* next fragment index */
    uint32_t crc;         /* running CRC-32 (~0-seeded) over QOI-stream bytes only */
    uint32_t qoi_len;     /* count of QOI-stream bytes emitted (for the trailer) */
    /* QOI encoder running state */
    uint8_t  index[64];
    int32_t  prev;        /* previous pixel value; init 0 to match the decoder's base */
    uint32_t run;
} ss_emit;

/* Standard zlib/PNG CRC-32 (reflected poly 0xEDB88320), bitwise so no 1 KB table is
 * carried in the injected blob. State is the pre-final value (the caller XORs the
 * 0xFFFFFFFF init/final in). Matches Python zlib.crc32 and the client's table CRC. */
static uint32_t ss_crc_step(uint32_t crc, uint8_t b) {
    crc ^= b;
    for (int k = 0; k < 8; k++)
        crc = (crc >> 1) ^ (0xEDB88320u & (uint32_t)(-(int32_t)(crc & 1u)));
    return crc;
}

/* Send the staged fragment (header + payload) as one aa21 frame, then reset the
 * staging buffer and bump the index. `last` sets the LAST flag. */
static void ss_flush(ss_emit *e, int last) {
    e->frag[0] = SS_FRAG_MAGIC;
    e->frag[1] = SS_VER;
    e->frag[2] = (uint8_t)e->frag_index;
    e->frag[3] = (uint8_t)(e->frag_index >> 8);
    e->frag[4] = last ? SS_FLAG_LAST : 0;
    e->frag[5] = 0;
    e->frag[6] = (uint8_t)e->fill;
    e->frag[7] = (uint8_t)(e->fill >> 8);
#ifdef SS_SEND_HOOK
    /* let the includer route the fragment (e.g. relay the L/slave lens's frames to the R lens
     * over the inter-lens peer link, since only R can reach the phone). Default: direct aa21. */
    SS_SEND_HOOK(e->frag, (int)(8 + e->fill));
#else
    SS_FW_SEND(1, SS_SID, e->frag, (int)(8 + e->fill));
#endif
    e->fill = 0;
    e->frag_index++;
}

/* Stage one raw byte into the outbound stream (header/trailer bytes: no CRC). */
static void ss_put(ss_emit *e, uint8_t b) {
    e->frag[8 + e->fill] = b;
    e->fill++;
    if (e->fill == SS_FRAG_PAYLOAD_MAX) ss_flush(e, 0);
}

/* Stage one QOI-stream byte: same as ss_put but also folds it into the CRC/length. */
static void ss_put_qoi(ss_emit *e, uint8_t b) {
    e->crc = ss_crc_step(e->crc, b);
    e->qoi_len++;
    ss_put(e, b);
}

/* QOI ops (each writes into the QOI stream via ss_put_qoi). */
static void ss_op_run(ss_emit *e) {
    if (e->run) {
        ss_put_qoi(e, (uint8_t)(0xC0u | (e->run - 1)));  /* run already clamped <=62 */
        e->run = 0;
    }
}

/* Feed one 8bpp gray pixel through the QOI encoder. */
static void ss_qoi_pixel(ss_emit *e, uint8_t v) {
    if ((int32_t)v == e->prev) {
        e->run++;
        if (e->run == 62) ss_op_run(e);
        return;
    }
    ss_op_run(e);
    uint32_t h = QOI_GRAY_HASH(v);
    if (e->index[h] == v) {
        ss_put_qoi(e, (uint8_t)h);                        /* INDEX */
    } else {
        e->index[h] = v;
        int32_t d = (int32_t)v - e->prev;
        if (d >= -32 && d <= 31)
            ss_put_qoi(e, (uint8_t)(0x40u | (uint32_t)((d + 32) & 0x3f)));  /* DIFF */
        else {
            ss_put_qoi(e, 0xFE);                          /* GRAY literal */
            ss_put_qoi(e, v);
        }
    }
    e->prev = (int32_t)v;
}

/* Capture core: QOI-encode a w*h framebuffer (8bpp gray, or 4bpp packed nibbles when
 * bpp==4) and stream it to sid 0x7d. Single pass, no malloc, ~0.5 KB of stack scratch.
 * Non-static so it can be driven directly by the emulator against the compiled bytes.
 * `fb` may be 0 (no-op). Returns the number of fragments sent. */
int cfw_screenshot_capture(const uint8_t *fb, uint32_t w, uint32_t h, uint32_t bpp) {
    if (fb == 0 || w == 0 || h == 0) return 0;

    ss_emit e;
    e.fill = 0; e.frag_index = 0; e.crc = 0xFFFFFFFFu; e.qoi_len = 0;
    for (int i = 0; i < 64; i++) e.index[i] = 0;
    e.prev = 0;                  /* QOI base pixel; the decoder starts from 0 too */
    e.run = 0;

    /* blob header: "G2SS", ver, flags, w:u16, h:u16 (not part of the CRC) */
    uint8_t flags = SS_UP_FILTER ? SS_FLAG_UPFILTER : 0;
    ss_put(&e, 'G'); ss_put(&e, '2'); ss_put(&e, 'S'); ss_put(&e, 'S');
    ss_put(&e, SS_VER); ss_put(&e, flags);
    ss_put(&e, (uint8_t)w); ss_put(&e, (uint8_t)(w >> 8));
    ss_put(&e, (uint8_t)h); ss_put(&e, (uint8_t)(h >> 8));

#if SS_UP_FILTER
    /* Up filter (subtract previous row) as a streaming pre-pass. Needs one row of
     * history (SS_FB_W bytes), kept on the STACK (build.py has no .bss relocation, and
     * the injected blob carries no writable globals). Off by default; the reference
     * client reverses it when the blob's flags bit0 is set. */
    uint8_t prev_row[SS_FB_W];          /* row -1 is all zeros */
    for (uint32_t i = 0; i < w; i++) prev_row[i] = 0;
#endif

    for (uint32_t y = 0; y < h; y++) {
        for (uint32_t x = 0; x < w; x++) {
            uint8_t v;
            if (bpp == 4) {
                uint8_t byte = fb[(y * w + x) >> 1];
                uint8_t nib = (x & 1) ? (byte & 0x0f) : (uint8_t)(byte >> 4);
                v = (uint8_t)(nib * 17);
            } else {
                v = fb[y * w + x];
            }
#if SS_UP_FILTER
            uint8_t up = prev_row[x];
            prev_row[x] = v;
            v = (uint8_t)(v - up);
#endif
            ss_qoi_pixel(&e, v);
        }
    }
    ss_op_run(&e);               /* flush any trailing run */

    /* trailer: qoi_len:u32, crc32:u32 (not part of the CRC itself) */
    uint32_t crc = e.crc ^ 0xFFFFFFFFu;
    uint32_t n = e.qoi_len;
    ss_put(&e, (uint8_t)n); ss_put(&e, (uint8_t)(n >> 8));
    ss_put(&e, (uint8_t)(n >> 16)); ss_put(&e, (uint8_t)(n >> 24));
    ss_put(&e, (uint8_t)crc); ss_put(&e, (uint8_t)(crc >> 8));
    ss_put(&e, (uint8_t)(crc >> 16)); ss_put(&e, (uint8_t)(crc >> 24));

    ss_flush(&e, 1);             /* final fragment carries the LAST flag */
    return e.frag_index;
}

/* Trigger entry: capture the live framebuffer and stream it. Runs only on the
 * transmitting lens (FW_SIDE()==1) since only it can reach the phone; the other lens
 * would waste cycles. Safe no-op until the framebuffer address is wired (ss_fb_ptr()
 * returns 0). This is what the RX trigger hook calls. */
int cfw_screenshot_run(void) {
    if (SS_FW_SIDE() != 1) return 0;         /* right/transmitting lens only */
    const uint8_t *fb = ss_fb_ptr();
    if (fb == 0) return 0;
    return cfw_screenshot_capture(fb, SS_FB_W, SS_FB_H, SS_FB_BPP);
}

/* Replaces `bl FUN_00441c68` at 0x0045aaa4 (the universal inbound-frame dispatcher call
 * -- every sid-routed app frame passes through it, in any UI). If the frame is a capture
 * request on sid 0x7d, run the screenshot (which self-gates to the transmitting lens and
 * resolves the live framebuffer), THEN tail-call the real dispatcher so all normal
 * traffic -- including the unknown sid 0x7d, which the dispatcher cleanly no-ops + frees
 * -- behaves exactly as stock. Args arrive already in r0..r3 (verified at the call site).
 *
 * NOTE (hardware-unverified): the capture+multi-fragment send runs INLINE here, on the
 * sync-framework thread-pool worker task (a full task context, not an ISR, that already
 * runs the heavyweight dispatch chain). A worst-case incompressible frame is a few
 * hundred aa21 sends; FUN_0047398c self-paces on link readiness, but if a watchdog or
 * the ESS TX queue proves too tight on real hardware, split the send (set a RAM flag
 * here and drain it from a periodic display hook) -- see patches/SCREENSHOT_CFW.md. */
int cap_rx_hook(uint32_t sid, uint8_t *payload, uint32_t len, uint32_t subcode) {
    if (sid == SS_TRIGGER_SID && payload != 0 && len >= 1 && payload[0] == SS_TRIGGER_OP)
        cfw_screenshot_run();
    return SS_FW_DISPATCH(sid, payload, len, subcode);
}
