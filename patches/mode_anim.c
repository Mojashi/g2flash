/*
 * mode_anim.c — HOST-DRIVEN program-based animation. Each RT_OP_SEND 'n' advances one frame:
 * draw it straight into the panel canvas (raw pixels, no LVGL) and jbd_flush(1). All from the
 * BLE-RX context — the ONLY context where jbd_flush is safe (the display-thread uiCb runs inside
 * the firmware's own flush cycle and re-enters -> fault). The host (anim-drive.ts) keeps one
 * connection open and paces the 'n' frames, so each on_data returns fast (watchdog-safe).
 *
 *   'n' -> next frame.   'r' -> reset frame to 0.   's' -> QOI-capture current frame (sid 0x7d).
 */
#include <stdint.h>

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

mode_vtable_t* payload_entry(rt_api_t* api);
__attribute__((naked, used)) void _start(void){ __asm__ volatile ("b.w payload_entry"); }

#include "screenshot.c"

#define FW_JBD_FLUSH  0x00588c91u
#define FB_CANVAS_PTR 0x20074464u
#define FB_CLEAR_CB   0x20074468u
#define CLEAR_CB_VAL  0x004d508du   /* the real pre-compose clear cb (fw 2.2.4.34); restore it */
#define MODE_CTX_SLOT 0x20053404u
#define PW 640u
#define PH 480u
#define STRIDE (PW/2u)
#define VX0 40u
#define VX1 600u
#define VY0 110u
#define VY1 370u
#define BOX 44u

typedef void (*flush_fn)(int);
static inline int in_sram(uint32_t p){ return (uint32_t)(p-0x20000000u) < 0x00800000u; }

typedef struct ctx { mode_vtable_t vt; rt_api_t* api; uint32_t frame; uint8_t capreq; } ctx_t;
static inline ctx_t* ctx_get(void){ return *(ctx_t* volatile*)MODE_CTX_SLOT; }

static void fillrect(uint8_t* fb,uint32_t x0,uint32_t y0,uint32_t w,uint32_t h,uint8_t lvl){
    for(uint32_t y=y0;y<y0+h && y<PH;y++)
        for(uint32_t x=x0;x<x0+w && x<PW;x++){
            uint8_t* b=fb+y*STRIDE+(x>>1);
            if(x&1u)*b=(uint8_t)((*b&0xF0u)|(lvl&0x0Fu)); else *b=(uint8_t)((*b&0x0Fu)|(uint8_t)(lvl<<4));
        }
}

static void draw_frame(ctx_t* c){
    uint8_t* fb=*(uint8_t* volatile*)FB_CANVAS_PTR;
    if(!fb||!in_sram((uint32_t)fb)) return;
    for(uint32_t i=0;i<STRIDE*PH;i++) fb[i]=0;
    uint32_t f=c->frame;
    /* border */
    fillrect(fb,VX0-6,VY0-6,(VX1-VX0)+12,4,0x0Fu);
    fillrect(fb,VX0-6,VY1+2,(VX1-VX0)+12,4,0x0Fu);
    fillrect(fb,VX0-6,VY0-6,4,(VY1-VY0)+12,0x0Fu);
    fillrect(fb,VX1+2,VY0-6,4,(VY1-VY0)+12,0x0Fu);
    /* bouncing ball (triangle wave in x and y) */
    uint32_t spanx=(VX1-VX0)-BOX, spany=(VY1-VY0)-BOX;
    uint32_t px=(f*9u)%(2u*spanx); if(px>spanx) px=2u*spanx-px;
    uint32_t py=(f*5u)%(2u*spany); if(py>spany) py=2u*spany-py;
    fillrect(fb,VX0+px,VY0+py,BOX,BOX,0x0Fu);
    /* moving scan line */
    uint32_t sx=VX0+((f*13u)%(VX1-VX0));
    fillrect(fb,sx,VY0,2,(VY1-VY0),0x09u);
    c->api->present();
    *(volatile uint32_t*)FB_CLEAR_CB=0u;      /* skip the pre-compose wipe for THIS burst only */
    ((flush_fn)FW_JBD_FLUSH)(1);
    *(volatile uint32_t*)FB_CLEAR_CB=CLEAR_CB_VAL;  /* restore so the firmware never calls a null cb */
}

static void a_init(rt_api_t* api){
    *(volatile uint32_t*)FB_CLEAR_CB = CLEAR_CB_VAL;   /* repair clear-cb if a prior payload zeroed it */
    uint8_t r[3]={0xA7,0x41,'I'}; api->reply(r,3);
}
static void a_data(uint8_t* b,int n){
    ctx_t* c=ctx_get(); if(!c) return;
    if(n>=1 && b[0]=='r'){ c->frame=0; draw_frame(c); return; }
    if(n>=1 && b[0]=='s'){ const uint8_t* fb=ss_fb_ptr(); if(fb) cfw_screenshot_capture(fb,640u,480u,4u); return; }
    /* 'n' (or anything else) = next frame */
    c->frame++; draw_frame(c);
}
static void a_tick(uint32_t d){(void)d;}
static void a_input(void* e){(void)e;}
static void a_exit(void){ ctx_t* c=ctx_get(); if(c){ c->api->mem_free(c); *(ctx_t* volatile*)MODE_CTX_SLOT=0; } }

mode_vtable_t* payload_entry(rt_api_t* api){
    ctx_t* c=(ctx_t*)api->mem_alloc(sizeof(ctx_t)); if(!c) return 0;
    for(unsigned i=0;i<sizeof(ctx_t);i++) ((uint8_t*)c)[i]=0;
    c->vt.init=a_init; c->vt.tick=a_tick; c->vt.on_input=a_input; c->vt.on_data=a_data; c->vt.exit=a_exit;
    c->api=api;
    *(ctx_t* volatile*)MODE_CTX_SLOT=c;
    return &c->vt;
}
