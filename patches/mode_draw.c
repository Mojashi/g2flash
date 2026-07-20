/*
 * mode_draw.c — hot-loaded PAYLOAD that actually PUTS PIXELS ON THE GLASS.
 *
 * The loader's api->present() only dcache-cleans; the JBD micro-LED panel self-refreshes
 * from on-chip GRAM, so a SRAM-canvas write is invisible until it is BURST into GRAM by the
 * firmware flush. This payload does the real burst itself (it can call any fw address):
 *   1. draw 4bpp pixels into the live panel canvas  (*(u32*)0x20074464, 640x480, stride 320)
 *   2. neutralize the pre-compose clear callback     (*(u32*)0x20074468 = 0)
 *   3. call the firmware JBD flush                    ((void(*)(int))0x588c91)(1)
 * (Addresses from the display-pipeline RE, fw 2.2.4.34.) One-shot "appear": the frame shows
 * until the next foreground-app invalidation re-bursts. Persistence is a later step.
 */
#include <stdint.h>

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

#define MODE_CTX_SLOT   0x20053404u
#define FB_CANVAS_PTR   0x20074464u   /* live 4bpp panel canvas base (deref) */
#define FB_CLEAR_CB     0x20074468u   /* pre-compose clear/fill callback fn-ptr */
#define FW_JBD_FLUSH    0x00588c91u   /* jbd flush(r0): wake -> JBD cmds -> compose/burst -> sleep (Thumb) */
#define LV_DISP_PTR     0x200745d0u   /* -> lv_display_t* */
#define FLUSH_CB_OFF    0x28u         /* lv_display_t.flush_cb (from lv_display_set_flush_cb: str r4,[r0,#0x28]) */
#define NOOP_FN         0x00438503u   /* a firmware 'bx lr' (0x438502|thumb) — no-op flush_cb => UI freeze */

#define PW 640u
#define PH 480u
#define STRIDE (PW/2u)

typedef void (*flush_fn)(int);
static inline int in_sram(uint32_t p){ return (uint32_t)(p - 0x20000000u) < 0x00800000u; }

mode_vtable_t* payload_entry(rt_api_t* api);
__attribute__((naked, used)) void _start(void){ __asm__ volatile ("b.w payload_entry"); }
/* ctx also remembers the original flush_cb so exit() un-freezes the native UI. */
typedef struct ctx { mode_vtable_t vt; rt_api_t* api; volatile uint32_t* cbslot; uint32_t orig_cb; } ctx_t;
static inline ctx_t* ctx_get(void){ return *(ctx_t* volatile*)MODE_CTX_SLOT; }

/* freeze the compositor: point lv_display.flush_cb at a no-op so no app render re-bursts. */
static void freeze(ctx_t* c){
    uint32_t disp = *(volatile uint32_t*)LV_DISP_PTR;
    if (!in_sram(disp)) { c->cbslot = 0; return; }
    c->cbslot = (volatile uint32_t*)(disp + FLUSH_CB_OFF);
    c->orig_cb = *c->cbslot;                 /* save to restore on exit */
    *c->cbslot = NOOP_FN;                     /* install no-op */
    { uint32_t t0 = c->api->tick_ms(); while (c->api->tick_ms() - t0 < 50u) { } }  /* let any in-flight flush drain */
}
static void unfreeze(ctx_t* c){ if (c->cbslot && in_sram(c->orig_cb)) *c->cbslot = c->orig_cb; }

static inline void put_px(uint8_t* fb, uint32_t x, uint32_t y, uint8_t lvl){
    uint8_t* b = fb + y*STRIDE + (x>>1);
    if (x & 1u) *b = (uint8_t)((*b & 0xF0u) | (lvl & 0x0Fu));
    else        *b = (uint8_t)((*b & 0x0Fu) | (uint8_t)(lvl << 4));
}

/* draw an unmistakable pattern into the LIVE canvas, then burst it to GRAM */
static void draw_and_burst(rt_api_t* api){
    uint8_t* fb = *(uint8_t* volatile*)FB_CANVAS_PTR;
    if (!fb || !in_sram((uint32_t)fb)) { uint8_t e[3]={0xA7,0xDC,0}; api->reply(e,3); return; }
    for (uint32_t y = 0; y < PH; y++){
        for (uint32_t x = 0; x < PW; x++){
            uint8_t lvl = (uint8_t)((x * 15u) / (PW - 1u));          /* column gradient 0..15 */
            if (y < 8u || y >= PH-8u || x < 8u || x >= PW-8u) lvl = 0x0Fu;   /* bright border */
            if (x >= 256u && x < 384u && y >= 176u && y < 304u) lvl = 0x0Fu; /* centered bright box */
            put_px(fb, x, y, lvl);
        }
    }
    api->present();                                    /* dcache-clean the canvas (loader stub) */
    *(volatile uint32_t*)FB_CLEAR_CB = 0u;             /* stop the pre-compose full-canvas clear */
    ((flush_fn)FW_JBD_FLUSH)(1);                        /* THE burst: SRAM canvas -> panel GRAM */
    { uint8_t ok[3]={0xA7,0xDC,1}; api->reply(ok,3); } /* {A7 DC 01} = drew+bursted */
}

static void d_init(rt_api_t* api){ ctx_t* c = ctx_get(); if (c) freeze(c); draw_and_burst(api); }
static void d_tick(uint32_t dt){ (void)dt; }
static void d_input(void* e){ (void)e; }
static void d_data(uint8_t* b, int n){ (void)n; (void)b; ctx_t* c=ctx_get(); if(c) draw_and_burst(c->api); } /* re-burst on SEND */
static void d_exit(void){ ctx_t* c = ctx_get(); if (c){ unfreeze(c); c->api->mem_free(c); *(ctx_t* volatile*)MODE_CTX_SLOT = 0; } }

mode_vtable_t* payload_entry(rt_api_t* api){
    ctx_t* c = (ctx_t*)api->mem_alloc(sizeof(ctx_t));
    if (!c) return 0;
    c->vt.init = d_init; c->vt.tick = d_tick; c->vt.on_input = d_input; c->vt.on_data = d_data; c->vt.exit = d_exit;
    c->api = api; c->cbslot = 0; c->orig_cb = 0;
    *(ctx_t* volatile*)MODE_CTX_SLOT = c;
    return &c->vt;
}
