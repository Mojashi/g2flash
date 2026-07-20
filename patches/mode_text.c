/*
 * mode_text.c — draw arbitrary TEXT onto the lens via the proven safe raw-canvas path
 * (no LVGL, no refr re-entrancy). Uses an embedded 8x8 bitmap font, scaled up. Works on the
 * idle panel (nothing to fight) and persists via GRAM self-refresh.
 *
 *   RT_OP_SEND <utf8 text>  -> clear canvas, render the text, jbd_flush(1). Reply {A7 0xD7 nchars}.
 *   (empty send or "d")     -> redraw current text.
 * Verify with mode_screenshot / screenshot-rt.ts.
 */
#include <stdint.h>
#include "font8.h"   /* static const uint8_t FONT8[96][8] */

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
/* Visible panel window is ~576x288 at offset (32,96); keep text inside it. */
#define SCALE 3u
#define GLYPH_W (8u*SCALE)
#define GAP 2u
#define ORIGIN_X 120u
#define ORIGIN_Y 200u

typedef void (*flush_fn)(int);
static inline int in_sram(uint32_t p){ return (uint32_t)(p - 0x20000000u) < 0x00800000u; }

mode_vtable_t* payload_entry(rt_api_t* api);
__attribute__((naked, used)) void _start(void){ __asm__ volatile ("b.w payload_entry"); }
typedef struct ctx { mode_vtable_t vt; rt_api_t* api; char text[96]; int len; } ctx_t;
static inline ctx_t* ctx_get(void){ return *(ctx_t* volatile*)MODE_CTX_SLOT; }

static inline void put_px(uint8_t* fb, uint32_t x, uint32_t y, uint8_t lvl){
    if(x>=PW || y>=PH) return;
    uint8_t* b = fb + y*STRIDE + (x>>1);
    if (x & 1u) *b = (uint8_t)((*b & 0xF0u) | (lvl & 0x0Fu));
    else        *b = (uint8_t)((*b & 0x0Fu) | (uint8_t)(lvl << 4));
}

static void draw_char(uint8_t* fb, uint32_t x0, uint32_t y0, char ch, uint8_t lvl){
    unsigned idx = (unsigned)(uint8_t)ch;
    if(idx < 0x20u || idx > 0x7Fu) idx = 0x20u;
    const uint8_t* g = FONT8[idx - 0x20u];
    for(uint32_t r=0;r<8u;r++){
        uint8_t row = g[r];
        for(uint32_t c=0;c<8u;c++){
            if(row & (0x80u >> c)){
                for(uint32_t dy=0;dy<SCALE;dy++)
                    for(uint32_t dx=0;dx<SCALE;dx++)
                        put_px(fb, x0 + c*SCALE + dx, y0 + r*SCALE + dy, lvl);
            }
        }
    }
}

static void render(ctx_t* c){
    uint8_t* fb = *(uint8_t* volatile*)FB_CANVAS_PTR;
    if(!fb || !in_sram((uint32_t)fb)){ uint8_t e[3]={0xA7,0xD7,0}; c->api->reply(e,3); return; }
    /* clear canvas to black */
    for(uint32_t i=0;i<STRIDE*PH;i++) fb[i]=0;
    /* draw text, wrapping to a new line if it runs past the visible right edge */
    uint32_t x = ORIGIN_X, y = ORIGIN_Y;
    for(int i=0;i<c->len;i++){
        char ch = c->text[i];
        if(ch=='\n' || x + GLYPH_W > 600u){ x = ORIGIN_X; y += GLYPH_W + 4u; if(ch=='\n') continue; }
        draw_char(fb, x, y, ch, 0x0Fu);
        x += GLYPH_W + GAP;
    }
    c->api->present();
    *(volatile uint32_t*)FB_CLEAR_CB = 0u;
    ((flush_fn)FW_JBD_FLUSH)(1);
    { uint8_t ok[3]={0xA7,0xD7,(uint8_t)c->len}; c->api->reply(ok,3); }
}

static void set_text(ctx_t* c, const char* s, int n){
    if(n>95) n=95; c->len=n; for(int i=0;i<n;i++) c->text[i]=s[i]; c->text[n]=0;
}
static void t_init(rt_api_t* api){ ctx_t* c=ctx_get(); set_text(c,"HELLO G2 CFW",12); render(c); }
static void t_data(uint8_t* buf, int n){
    ctx_t* c=ctx_get(); if(!c) return;
    if(n>=1 && !(n==1 && buf[0]=='d')) set_text(c,(const char*)buf,n);
    render(c);
}
static void t_tick(uint32_t d){ (void)d; }
static void t_input(void* e){ (void)e; }
static void t_exit(void){ ctx_t* c=ctx_get(); if(c){ c->api->mem_free(c); *(ctx_t* volatile*)MODE_CTX_SLOT=0; } }

mode_vtable_t* payload_entry(rt_api_t* api){
    ctx_t* c=(ctx_t*)api->mem_alloc(sizeof(ctx_t));
    if(!c) return 0;
    c->vt.init=t_init; c->vt.tick=t_tick; c->vt.on_input=t_input; c->vt.on_data=t_data; c->vt.exit=t_exit;
    c->api=api; c->len=0;
    *(ctx_t* volatile*)MODE_CTX_SLOT=c;
    return &c->vt;
}
