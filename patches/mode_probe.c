/*
 * mode_probe.c — diagnostic PAYLOAD for the flashed loader. Not flashed; hot-loaded.
 * Its init() does NOT draw — it just reports, over RUNTIME_SID, what the display API
 * actually returns on the real device so we can see why a framebuffer write isn't visible:
 *   reply = { 0xA7, 0xDB, fb_canvas_ptr[4 LE], fb_w[2], fb_h[2], lens_side[1],
 *             canvas[0..7] (8 bytes at *fb_canvas, or zeros if the ptr isn't SRAM) }
 * A zero/invalid ptr => the panel canvas isn't resolved while idle (need a display ctx);
 * a valid ptr + plausible pixel bytes => the write path works but the compositor/scan-out
 * isn't showing our buffer (timing / wrong buffer / needs continuous redraw).
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

#define MODE_CTX_SLOT 0x20053404u
static inline int in_sram(uint32_t p){ return (uint32_t)(p - 0x20000000u) < 0x00800000u; }

mode_vtable_t* payload_entry(rt_api_t* api);
__attribute__((naked, used)) void _start(void){ __asm__ volatile ("b.w payload_entry"); }

typedef struct ctx { mode_vtable_t vt; rt_api_t* api; } ctx_t;
static inline ctx_t* ctx_get(void){ return *(ctx_t* volatile*)MODE_CTX_SLOT; }

static void p_init(rt_api_t* api){
    uint8_t* fb = api->fb_canvas();
    uint32_t p = (uint32_t)fb;
    uint8_t out[2 + 4 + 2 + 2 + 1 + 8];
    out[0] = 0xA7u; out[1] = 0xDBu;
    out[2] = (uint8_t)p; out[3] = (uint8_t)(p >> 8); out[4] = (uint8_t)(p >> 16); out[5] = (uint8_t)(p >> 24);
    out[6] = (uint8_t)api->fb_w; out[7] = (uint8_t)(api->fb_w >> 8);
    out[8] = (uint8_t)api->fb_h; out[9] = (uint8_t)(api->fb_h >> 8);
    out[10] = (uint8_t)api->lens_side();
    for (int i = 0; i < 8; i++) out[11 + i] = (fb && in_sram(p)) ? fb[i] : 0u;
    api->reply(out, 2 + 4 + 2 + 2 + 1 + 8);
}
static void p_noop1(uint32_t d){ (void)d; }
static void p_noop2(void* e){ (void)e; }
static void p_ondata(uint8_t* b, int n){ (void)b; (void)n; }
static void p_exit(void){ ctx_t* c = ctx_get(); if (c){ c->api->mem_free(c); *(ctx_t* volatile*)MODE_CTX_SLOT = 0; } }

mode_vtable_t* payload_entry(rt_api_t* api){
    ctx_t* c = (ctx_t*)api->mem_alloc(sizeof(ctx_t));
    if (!c) return 0;
    c->vt.init = p_init; c->vt.tick = p_noop1; c->vt.on_input = p_noop2; c->vt.on_data = p_ondata; c->vt.exit = p_exit;
    c->api = api;
    *(ctx_t* volatile*)MODE_CTX_SLOT = c;
    return &c->vt;
}
