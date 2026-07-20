/*
 * mode_selftest.c -- minimal "mode" PAYLOAD for the G2 mode-runtime loader
 * (runtime.c / fw_2.2.4.34). Proof-of-execution test mode: NOT flashed; it is
 * hot-loaded over BLE into a malloc'd RAM buffer and run by activate_payload().
 *
 * It proves the runtime works end to end:
 *   init()    -> sends a 3-byte marker {0xA7,0xEE,lens_side} on RUNTIME_SID so the
 *                client sees the payload actually executed, then fills the 640x480
 *                4bpp panel canvas with a column gradient + a bright rectangle and
 *                present()s it (visible proof on the lens).
 *   tick()    -> slides the rectangle horizontally and re-present()s (animation proof).
 *   on_data() -> echoes the received bytes back on RUNTIME_SID (round-trip proof).
 *
 * ---------------------------------------------------------------------------
 * POSITION-INDEPENDENCE (this is the whole point of a payload):
 *   The blob is compiled by build.py (clang --target=thumbv7em-none-eabi -O2
 *   -ffreestanding -fropi ...), which acts as a mini-linker and HARD-ERRORS on any
 *   relocation that isn't (a) an intra-.text BL/B.W or (b) a PC-relative -fropi
 *   rodata/code ref (MOVW_PREL/MOVT_PREL). So this file must contain:
 *     - ZERO calls to absolute firmware addresses  (we call ONLY via rt_api_t*),
 *     - ZERO writable globals (.data/.bss are NOT carried in the blob and would
 *       produce absolute relocations), and
 *     - ZERO statically-initialised function-pointer tables (a `static const vtable
 *       = {init,tick,...}` needs ABS32 data relocations -> build error). The vtable
 *       is therefore FILLED AT RUNTIME in payload_entry(): taking &md_init etc. under
 *       -fropi emits PC-relative MOVW/MOVT that build.py resolves in-blob, so the
 *       result relocates with the blob wherever it is loaded.
 *
 * ENTRY AT OFFSET 0:
 *   activate_payload() calls (g_buf|1) blindly -- offset 0 of the blob MUST be the
 *   entry. `_start` (naked, defined first) is a bare `b.w payload_entry` tail-branch
 *   (an intra-.text JUMP24 that build.py fixes up), so the entry is at offset 0 no
 *   matter how clang orders the rest. `b` preserves r0, so payload_entry's returned
 *   vtable* propagates as _start's return value.
 *
 * PERSISTENT STATE WITHOUT WRITABLE GLOBALS:
 *   The vtable ABI passes no `self`/context pointer to tick()/on_data(), yet those
 *   need the api pointer (and the rectangle x) across calls. With no writable globals
 *   allowed, we allocate a ctx block from api->mem_alloc() in payload_entry() and
 *   stash its pointer in ONE fixed scratch RAM word (RT_MODE_CTX_SLOT_A, the payload
 *   slot the loader reserves — distinct from the loader's own state anchor). That word
 *   is a fixed HARDWARE address -> a plain
 *   immediate, NOT a relocation and NOT a self-reference, so the blob stays PIC. It
 *   is the ONLY absolute constant in the file. (A cleaner v2 would add a ctx*
 *   parameter to the vtable callbacks and delete this line.)
 */
#include <stdint.h>

/* ---- mirror of the loader's ABI struct (MUST match runtime.c's rt_api field-for-field:
 * present, then dcache_clean(void*,uint32_t), then fb_w, fb_h) ---- */
typedef struct rt_api {
    uint32_t abi_version;
    void*    (*mem_alloc)(uint32_t n);
    void     (*mem_free)(void* p);
    int      (*send)(int sid, void* ptr, int len);
    void     (*reply)(void* ptr, int len);
    int      (*lens_side)(void);
    uint32_t (*tick_ms)(void);
    uint8_t* (*fb_canvas)(void);
    void     (*present)(void);
    void     (*dcache_clean)(void* p, uint32_t len);
    uint32_t fb_w, fb_h;
} rt_api_t;

typedef struct mode_vtable {
    void (*init)(rt_api_t* api);
    void (*tick)(uint32_t dt_ms);
    void (*on_input)(void* event_record);
    void (*on_data)(uint8_t* buf, int len);
    void (*exit)(void);
} mode_vtable_t;

/* ---- the single fixed hardware constant (see header comment): a spare RAM word the
 * loader reserves for MODE context. Holds our ctx* between vtable calls. This is an
 * immediate, not a relocation; the blob remains position-independent.
 *
 * CRITICAL: this MUST be distinct from the loader's own state anchor (RT_STATE_ANCHOR_A
 * = 0x20053304). A payload that stashed its ctx at the loader's anchor would clobber the
 * loader's rt_state pointer. So we use RT_MODE_CTX_SLOT_A (0x20053404), the dedicated
 * payload slot the loader reserves in the same verified clean RAM gap. ---- */
#define MODE_CTX_SLOT 0x20053404u   /* == RT_MODE_CTX_SLOT_A in fw_2.2.4.34.h (NOT the anchor) */

/* panel geometry (from the loader / fw header: 640x480 4bpp, 2 px/byte, stride 320,
 * high nibble = even/left pixel). Passed also in api->fb_w/h but pinned here so the
 * fill loop needs no runtime multiply-by-variable. */
#define PW   640u
#define PH   480u
#define STRIDE (PW/2u)              /* 320 bytes/row */
#define FB_BYTES (STRIDE*PH)        /* 153600 */

/* per-mode persistent state, heap-allocated in payload_entry(). The vtable lives
 * inside it so returning &ctx->vt keeps the whole block reachable via the loader's
 * g_mode; the ctx* is recovered in every callback from MODE_CTX_SLOT. */
typedef struct ctx {
    mode_vtable_t vt;      /* offset 0: what payload_entry returns (&ctx->vt == ctx) */
    rt_api_t*     api;     /* stashed so tick()/on_data() can reach the loader API   */
    int32_t       rx;      /* rectangle left x (animated)                            */
    int32_t       dir;     /* animation direction/step in px                         */
} ctx_t;

/* forward decl so the offset-0 trampoline can branch to the real entry */
mode_vtable_t* payload_entry(rt_api_t* api);

/* offset-0 entry trampoline: DEFINED FIRST so it is at blob offset 0 (clang emits
 * functions in definition order within the single .text). A bare tail-branch to
 * payload_entry -- an intra-.text JUMP24 that build.py fixes up; `b` preserves r0 so
 * payload_entry's returned vtable* becomes _start's return value. This makes the
 * "entry at offset 0" contract hold regardless of how clang orders the rest. */
__attribute__((naked, used))
void _start(void){ __asm__ volatile ("b.w payload_entry"); }

static inline ctx_t* ctx_get(void){ return *(ctx_t* volatile*)MODE_CTX_SLOT; }

/* Write pixel (x,y) = 4-bit level (0..15) into the packed 4bpp canvas. */
static inline void put_px(uint8_t* fb, uint32_t x, uint32_t y, uint8_t lvl){
    uint8_t* b = fb + y*STRIDE + (x>>1);
    if (x & 1u) *b = (uint8_t)((*b & 0xF0u) | (lvl & 0x0Fu));      /* low nibble = odd/right */
    else        *b = (uint8_t)((*b & 0x0Fu) | (uint8_t)(lvl << 4)); /* high nibble = even/left */
}

/* Render one frame: a left->right column gradient with a bright filled rectangle at
 * x=[rx, rx+RW), y=[RY, RY+RH). Pure framebuffer writes (no LVGL), then present(). */
#define RW  96u
#define RH  96u
#define RY  192u
static void draw_frame(rt_api_t* api, int32_t rx){
    uint8_t* fb = api->fb_canvas();
    if (!fb) return;
    for (uint32_t y = 0; y < PH; y++){
        for (uint32_t x = 0; x < PW; x++){
            uint8_t lvl = (uint8_t)((x * 15u) / (PW - 1u));   /* 0..15 gradient */
            if ((int32_t)x >= rx && (int32_t)x < rx + (int32_t)RW
                && y >= RY && y < RY + RH)
                lvl = 0x0Fu;                                   /* rectangle: full bright */
            put_px(fb, x, y, lvl);
        }
    }
    api->present();
}

/* ---- vtable callbacks (recover ctx/api from the scratch slot) ---- */
static void md_init(rt_api_t* api){
    /* proof-of-execution marker: {RT_MAGIC=0xA7, 0xEE, lens_side} on RUNTIME_SID.
     * api->reply() self-gates to the transmit lens, so the client sees it once. */
    uint8_t marker[3] = { 0xA7u, 0xEEu, (uint8_t)api->lens_side() };
    api->reply(marker, 3);
    draw_frame(api, ctx_get()->rx);
}

static void md_tick(uint32_t dt_ms){
    (void)dt_ms;
    ctx_t* c = ctx_get();
    c->rx += c->dir;
    if (c->rx < 0){ c->rx = 0; c->dir = -c->dir; }
    if (c->rx > (int32_t)(PW - RW)){ c->rx = (int32_t)(PW - RW); c->dir = -c->dir; }
    draw_frame(c->api, c->rx);
}

static void md_on_data(uint8_t* buf, int len){
    ctx_t* c = ctx_get();
    if (!buf || len <= 0) return;
    /* echo the bytes back with a 2-byte tag {0xA7,0xEC} so the client can tell an echo
     * apart from a loader PING reply on the shared RUNTIME_SID. Bounded stack buffer. */
    uint8_t out[2 + 200];
    int n = len; if (n > 200) n = 200;
    out[0] = 0xA7u; out[1] = 0xECu;
    for (int i = 0; i < n; i++) out[2 + i] = buf[i];
    c->api->reply(out, 2 + n);
}

static void md_on_input(void* event_record){ (void)event_record; }

/* Free the ctx WE allocated in payload_entry (the loader frees only the CODE buffer, never
 * a payload's own api->mem_alloc blocks). exit() runs while MODE_CTX_SLOT still holds this
 * mode's ctx (the loader calls old->exit() before the next payload_entry overwrites the
 * slot), so we recover the pointer, free it, and clear the slot to avoid a dangling ref. */
static void md_exit(void){
    ctx_t* c = ctx_get();
    if (c){ c->api->mem_free(c); *(ctx_t* volatile*)MODE_CTX_SLOT = 0; }
}

/* Entry: offset 0 reaches here via _start's tail-branch. Allocate ctx, fill the
 * vtable at RUNTIME (PC-relative &fn -> resolved in-blob), stash ctx*, return &vt. */
mode_vtable_t* payload_entry(rt_api_t* api){
    ctx_t* c = (ctx_t*)api->mem_alloc(sizeof(ctx_t));
    if (!c) return 0;                       /* loader tolerates a null vtable */
    c->vt.init     = md_init;
    c->vt.tick     = md_tick;
    c->vt.on_input = md_on_input;
    c->vt.on_data  = md_on_data;
    c->vt.exit     = md_exit;
    c->api = api;
    c->rx  = 0;
    c->dir = 8;                             /* 8 px/tick */
    *(ctx_t* volatile*)MODE_CTX_SLOT = c;   /* the one fixed-address store */
    return &c->vt;
}
