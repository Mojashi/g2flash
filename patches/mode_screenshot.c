/*
 * mode_screenshot.c — hot-loaded PAYLOAD wrapper around the proven grayscale-QOI screenshot
 * encoder (screenshot.c). Lets the operator SEE the lens without wearing the glasses: on an
 * RT_OP_SEND "s", it QOI-encodes the live panel canvas and streams it on sid 0x7d in the exact
 * fragment format demos/screenshot.ts (and screenshot-rt.ts) reassembles + decodes to PNG.
 *
 * Reuses screenshot.c verbatim (its encoder is malloc-free, calls FW_SEND by absolute address,
 * and self-gates to the transmitting lens) — we only add the loader vtable + trigger.
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

/* _start MUST be at blob offset 0 (loader jumps there). Define it before pulling in
 * screenshot.c so it stays the first function in .text; payload_entry is a forward ref
 * (build.py resolves intra-.text branches). */
mode_vtable_t* payload_entry(rt_api_t* api);
__attribute__((naked, used)) void _start(void){ __asm__ volatile ("b.w payload_entry"); }

#include "screenshot.c"   /* ss_* encoder + cfw_screenshot_run() (canvas 0x20074464, 640x480 4bpp) */

#define MODE_CTX_SLOT 0x20053404u
typedef struct ctx { mode_vtable_t vt; rt_api_t* api; } ctx_t;
static inline ctx_t* ctx_get(void){ return *(ctx_t* volatile*)MODE_CTX_SLOT; }

static void sc_init(rt_api_t* api){ uint8_t r[4]={0xA7,0x53,'R','Y'}; api->reply(r,4); }
static void sc_data(uint8_t* b, int n){
    ctx_t* c=ctx_get(); if(!c) return;
    if(n>=1 && b[0]=='s'){
        int nf = cfw_screenshot_run();                        /* QOI-stream the canvas on sid 0x7d */
        uint8_t r[4]={0xA7,0x53,(uint8_t)nf,(uint8_t)(nf>>8)}; /* {A7 53 nfrags} = done trigger-side */
        c->api->reply(r,4);
    }
}
static void sc_tick(uint32_t d){ (void)d; }
static void sc_input(void* e){ (void)e; }
static void sc_exit(void){ ctx_t* c=ctx_get(); if(c){ c->api->mem_free(c); *(ctx_t* volatile*)MODE_CTX_SLOT=0; } }

mode_vtable_t* payload_entry(rt_api_t* api){
    ctx_t* c=(ctx_t*)api->mem_alloc(sizeof(ctx_t));
    if(!c) return 0;
    c->vt.init=sc_init; c->vt.tick=sc_tick; c->vt.on_input=sc_input; c->vt.on_data=sc_data; c->vt.exit=sc_exit;
    c->api=api;
    *(ctx_t* volatile*)MODE_CTX_SLOT=c;
    return &c->vt;
}
