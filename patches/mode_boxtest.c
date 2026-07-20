/*
 * mode_boxtest.c — minimal SAFE display test. No LVGL, no refr (which re-enters + faults),
 * no flush_cb freeze. Just what mode_draw proved safe: write our own pixels into the panel
 * canvas and burst them with jbd_flush. On an IDLE panel there is no compositor to fight, so
 * a full-canvas pattern shows cleanly and persists via the panel's GRAM self-refresh.
 *
 *   RT_OP_SEND "d" (or init) -> clear canvas, draw a border + centered filled box + gradient,
 *   neutralize the pre-compose clear cb, jbd_flush(1). Reply {A7 0xDC 01}.
 * Then mode_screenshot can read the canvas back to confirm.
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
#define FB_CANVAS_PTR 0x20074464u
#define FB_CLEAR_CB   0x20074468u
#define FW_JBD_FLUSH  0x00588c91u
#define PW 640u
#define PH 480u
#define STRIDE (PW/2u)

typedef void (*flush_fn)(int);
static inline int in_sram(uint32_t p){ return (uint32_t)(p - 0x20000000u) < 0x00800000u; }

mode_vtable_t* payload_entry(rt_api_t* api);
__attribute__((naked, used)) void _start(void){ __asm__ volatile ("b.w payload_entry"); }
typedef struct ctx { mode_vtable_t vt; rt_api_t* api; } ctx_t;
static inline ctx_t* ctx_get(void){ return *(ctx_t* volatile*)MODE_CTX_SLOT; }

static inline void put_px(uint8_t* fb, uint32_t x, uint32_t y, uint8_t lvl){
    uint8_t* b = fb + y*STRIDE + (x>>1);
    if (x & 1u) *b = (uint8_t)((*b & 0xF0u) | (lvl & 0x0Fu));
    else        *b = (uint8_t)((*b & 0x0Fu) | (uint8_t)(lvl << 4));
}

static void draw(rt_api_t* api){
    uint8_t* fb = *(uint8_t* volatile*)FB_CANVAS_PTR;
    if(!fb || !in_sram((uint32_t)fb)){ uint8_t e[3]={0xA7,0xDC,0}; api->reply(e,3); return; }
    for(uint32_t y=0;y<PH;y++){
        for(uint32_t x=0;x<PW;x++){
            uint8_t lvl = 0;                                       /* black background */
            if (y<8u || y>=PH-8u || x<8u || x>=PW-8u) lvl = 0x0Fu;  /* full bright border */
            if (x>=200u && x<440u && y>=180u && y<300u) lvl=0x0Fu;  /* centered bright box */
            if (x>=210u && x<430u && y>=200u && y<280u) lvl=0x06u;  /* dim inner box (contrast) */
            put_px(fb,x,y,lvl);
        }
    }
    api->present();                                    /* dcache-clean canvas */
    *(volatile uint32_t*)FB_CLEAR_CB = 0u;
    ((flush_fn)FW_JBD_FLUSH)(1);
    { uint8_t ok[3]={0xA7,0xDC,1}; api->reply(ok,3); }
}

static void b_init(rt_api_t* api){ draw(api); }
static void b_data(uint8_t* buf, int n){ (void)buf;(void)n; ctx_t* c=ctx_get(); if(c) draw(c->api); }
static void b_tick(uint32_t d){ (void)d; }
static void b_input(void* e){ (void)e; }
static void b_exit(void){ ctx_t* c=ctx_get(); if(c){ c->api->mem_free(c); *(ctx_t* volatile*)MODE_CTX_SLOT=0; } }

mode_vtable_t* payload_entry(rt_api_t* api){
    ctx_t* c=(ctx_t*)api->mem_alloc(sizeof(ctx_t));
    if(!c) return 0;
    c->vt.init=b_init; c->vt.tick=b_tick; c->vt.on_input=b_input; c->vt.on_data=b_data; c->vt.exit=b_exit;
    c->api=api;
    *(ctx_t* volatile*)MODE_CTX_SLOT=c;
    return &c->vt;
}
