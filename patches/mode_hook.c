/*
 * mode_hook.c — inject our own animated overlay into the LVGL compositor's per-frame output by
 * HOOKING the display flush callback. This is the architecturally-correct injection: no fighting
 * the compositor, no extra jbd_flush (no flash), no re-entrant refr (no crash).
 *
 * lvgl_flush_cb (fw 0x4716c4) is a function pointer at *(lv_display + 0x28). LVGL calls it every
 * frame with (disp, area, px_map) where px_map is the freshly-rendered L8 buffer covering `area`
 * (an lv_area_t {x1,y1,x2,y2}). We replace it with our wrapper which:
 *   1. draws our overlay (text + bouncing box) into px_map, clipped to `area` (so partial flushes
 *      are safe; full-frame flushes show the whole overlay),
 *   2. calls the ORIGINAL flush_cb -> the firmware blits px_map (dashboard + our overlay) to the panel,
 *   3. advances the animation frame and invalidates the active screen so the NEXT frame is a full
 *      redraw -> the overlay is present every frame. Free-running, compositor-paced, stable while worn.
 *
 * Runs entirely in the display thread (that is who calls flush_cb), so LVGL access is safe.
 * On exit / reset we restore the original pointer. A crash only costs a watchdog reboot, after
 * which the firmware re-inits lv_display with the stock flush_cb (recoverable).
 *
 *   'g' = install hook + start.   'x' = uninstall.   text bytes = set overlay text.
 */
#include <stdint.h>
#include "font8.h"

typedef struct rt_api {
    uint32_t abi_version; void* (*mem_alloc)(uint32_t); void (*mem_free)(void*);
    int (*send)(int,void*,int); void (*reply)(void*,int); int (*lens_side)(void);
    uint32_t (*tick_ms)(void); uint8_t* (*fb_canvas)(void); void (*present)(void);
    void (*dcache_clean)(void*,uint32_t); uint32_t fb_w, fb_h;
} rt_api_t;
typedef struct mode_vtable {
    void (*init)(rt_api_t*); void (*tick)(uint32_t); void (*on_input)(void*);
    void (*on_data)(uint8_t*,int); void (*exit)(void);
} mode_vtable_t;

#define LV_DISPLAY_PP     0x200745d0u   /* -> lv_display_t*                                  */
#define FLUSHCB_OFF       0x28u         /* lv_display_t.flush_cb                              */
#define FW_LV_OBJ_INVAL   0x004405f7u   /* lv_obj_invalidate(obj)                            */
#define FW_LV_SCR_ACTIVE  0x0044eb97u   /* lv_obj_t* lv_display_get_screen_active(disp)       */
#define MODE_CTX_SLOT     0x20053404u
#define SCALE 3u
#define GLYPH_W (8u*SCALE)

typedef void (*flushcb_fn)(void* disp, void* area, void* px_map);
typedef void (*obj1_fn)(void* o);
typedef void* (*scr_fn)(void* disp);

mode_vtable_t* payload_entry(rt_api_t* api);
__attribute__((naked, used)) void _start(void){ __asm__ volatile ("b.w payload_entry"); }

typedef struct ctx {
    mode_vtable_t vt; rt_api_t* api;
    volatile uint32_t* cbslot;  /* &(lv_display->flush_cb) */
    uint32_t orig_cb;           /* saved original flush_cb (Thumb ptr) */
    uint32_t frame; uint8_t installed;
    char text[40]; int len;
} ctx_t;
static inline ctx_t* ctx_get(void){ return *(ctx_t* volatile*)MODE_CTX_SLOT; }

/* write an L8 pixel at screen (sx,sy)=val into px_map, clipped to the flushed area [x1,y1,x2,y2]. */
static inline void put_l8(uint8_t* pm, int x1,int y1,int x2,int y2, int sx,int sy, uint8_t v){
    if(sx<x1||sx>x2||sy<y1||sy>y2) return;
    int aw = x2 - x1 + 1;
    pm[(sy - y1)*aw + (sx - x1)] = v;
}
static void blit_char(uint8_t* pm,int x1,int y1,int x2,int y2, int ox,int oy, char ch, uint8_t v){
    unsigned i=(unsigned)(uint8_t)ch; if(i<0x20u||i>0x7Fu) i=0x20u;
    const uint8_t* g=FONT8[i-0x20u];
    for(int r=0;r<8;r++){ uint8_t rw=g[r];
        for(int c=0;c<8;c++) if(rw&(0x80u>>c))
            for(uint32_t dy=0;dy<SCALE;dy++) for(uint32_t dx=0;dx<SCALE;dx++)
                put_l8(pm,x1,y1,x2,y2, ox+c*(int)SCALE+(int)dx, oy+r*(int)SCALE+(int)dy, v); }
}
static void fill(uint8_t* pm,int x1,int y1,int x2,int y2, int rx,int ry,int rw,int rh, uint8_t v){
    for(int y=ry;y<ry+rh;y++) for(int x=rx;x<rx+rw;x++) put_l8(pm,x1,y1,x2,y2,x,y,v);
}

/* OUR replacement flush_cb — runs in the display thread every frame. */
static void our_flush(void* disp, void* area, void* px_map){
    ctx_t* c = ctx_get();
    if(c && px_map && area){
        int32_t* a = (int32_t*)area;
        int x1=a[0], y1=a[1], x2=a[2], y2=a[3];
        uint8_t* pm = (uint8_t*)px_map;
        uint32_t f = c->frame;
        /* bouncing box in the visible 576x288 window (screen coords; clipped to `area`) */
        int spanx = 576-60, spany = 288-60;
        int px = (int)((f*4u) % (uint32_t)(2*spanx)); if(px>spanx) px=2*spanx-px;
        int py = (int)((f*3u) % (uint32_t)(2*spany)); if(py>spany) py=2*spany-py;
        fill(pm,x1,y1,x2,y2, px, py, 40,40, 0xFF);
        /* overlay text near the top */
        int ox=90;
        for(int i=0;i<c->len;i++){ blit_char(pm,x1,y1,x2,y2, ox, 20, c->text[i], 0xFF); ox+=GLYPH_W+2; }
    }
    /* hand off to the real flush_cb so the firmware blits px_map (dashboard + our overlay). */
    if(c && c->orig_cb) ((flushcb_fn)c->orig_cb)(disp, area, px_map);
    /* force a full redraw next frame so our overlay is refreshed every frame */
    if(c){
        c->frame++;
        if((c->frame & 31u)==1u){ uint32_t f=c->frame; uint8_t r[6]={0xA7,0x48,(uint8_t)f,(uint8_t)(f>>8),(uint8_t)(f>>16),(uint8_t)(f>>24)}; c->api->reply(r,6); }
        void* scr = ((scr_fn)FW_LV_SCR_ACTIVE)(disp);
        if(scr) ((obj1_fn)FW_LV_OBJ_INVAL)(scr);
    }
}

static void install(ctx_t* c){
    uint32_t disp = *(volatile uint32_t*)LV_DISPLAY_PP;
    if(!disp || (uint32_t)(disp-0x20000000u)>=0x0a000000u){ uint8_t e[3]={0xA7,0x48,0}; c->api->reply(e,3); return; }
    c->cbslot = (volatile uint32_t*)(disp + FLUSHCB_OFF);
    c->orig_cb = *c->cbslot;
    *c->cbslot = (uint32_t)&our_flush;   /* &fn carries the Thumb bit */
    c->installed = 1;
    { uint8_t r[3]={0xA7,0x48,1}; c->api->reply(r,3); }
    /* kick a first redraw */
    void* scr = ((scr_fn)FW_LV_SCR_ACTIVE)((void*)disp);
    if(scr) ((obj1_fn)FW_LV_OBJ_INVAL)(scr);
}
static void uninstall(ctx_t* c){ if(c->installed && c->cbslot){ *c->cbslot = c->orig_cb; c->installed=0; } }

static void set_text(ctx_t* c,const char* s,int n){ if(n>39)n=39; c->len=n; for(int i=0;i<n;i++)c->text[i]=s[i]; }
static void h_init(rt_api_t* api){ ctx_t* c=ctx_get(); set_text(c,"HELLO G2 CFW",12); uint8_t r[3]={0xA7,0x48,'I'}; api->reply(r,3); }
static void h_data(uint8_t* b,int n){ ctx_t* c=ctx_get(); if(!c) return;
    if(n>=1&&b[0]=='g'){ install(c); return; } if(n>=1&&b[0]=='x'){ uninstall(c); return; }
    set_text(c,(const char*)b,n); }
static void h_tick(uint32_t d){(void)d;} static void h_input(void* e){(void)e;}
static void h_exit(void){ ctx_t* c=ctx_get(); if(!c) return; uninstall(c); c->api->mem_free(c); *(ctx_t* volatile*)MODE_CTX_SLOT=0; }

mode_vtable_t* payload_entry(rt_api_t* api){
    ctx_t* c=(ctx_t*)api->mem_alloc(sizeof(ctx_t)); if(!c) return 0;
    for(unsigned i=0;i<sizeof(ctx_t);i++) ((uint8_t*)c)[i]=0;
    c->vt.init=h_init; c->vt.tick=h_tick; c->vt.on_input=h_input; c->vt.on_data=h_data; c->vt.exit=h_exit;
    c->api=api; *(ctx_t* volatile*)MODE_CTX_SLOT=c; return &c->vt;
}
