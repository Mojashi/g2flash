/*
 * mode_showcap.c — self-contained SHOW + CAPTURE payload. Solves the idle-panel problem and
 * lets the host verify the result, all from the display thread.
 *
 * Our uiCb runs in the display thread (only LVGL-safe place). Each tick it:
 *   - creates our lv_label on the top layer once,
 *   - forces a synchronous render of the default display (_lv_display_refr_timer(0)) so the
 *     label lands in the panel canvas EVEN WHILE THE PANEL IS IDLE (the firmware's own
 *     compositor isn't running then), and
 *   - bursts the canvas to the panel (jbd_flush) which also wakes the panel — so the label is
 *     visible without wearing the glasses, and the repeated burst keeps the panel awake.
 * When the host asks (RT_OP_SEND 's'), the SAME tick — right after the render, before any
 * clear — QOI-encodes the live canvas and streams it on sid 0x7d (screenshot-rt.ts decodes).
 * Because capture happens in-thread immediately after the render, it captures exactly what we
 * drew, not a cleared canvas caught by a separate async payload.
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

mode_vtable_t* payload_entry(rt_api_t* api);
__attribute__((naked, used)) void _start(void){ __asm__ volatile ("b.w payload_entry"); }

#include "screenshot.c"   /* ss_* encoder + cfw_screenshot_capture(fb,w,h,bpp) + ss_fb_ptr() */

/* ---- fw / LVGL v9.3 entry points (Thumb bit set) ---- */
#define FW_LV_DISP_GET_DEF    0x0044e94fu
#define FW_LV_DISP_LAYER_TOP  0x0044ebf3u
#define FW_LV_LABEL_CREATE    0x004b1c97u
#define FW_LV_LABEL_SET_TEXT  0x004b1cafu
#define FW_LV_OBJ_SET_POS     0x0043f03bu
#define FW_LV_OBJ_INVALIDATE  0x004405f7u
#define FW_LV_DISP_EN_INVAL   0x0044edc3u  /* lv_display_enable_invalidation(disp, en) */
#define FW_LV_REFR_TIMER      0x00452541u  /* _lv_display_refr_timer(0) = force render default */
#define FW_JBD_FLUSH          0x00588c91u  /* jbd_flush(1): wake MSPI -> burst canvas -> panel */
#define FW_DISPLAY_STARTUP    0x00443905u
#define FB_CLEAR_CB           0x20074468u
#define REG_BASE   0x20066210u
#define REG_COUNT  0x20074410u
#define OUR_APPID  0x00C5u
#define OUR_PAGEID 0x00C5u
#define MODE_CTX_SLOT 0x20053404u

typedef void* (*getptr_fn)(void);
typedef void* (*layer_fn)(void* d);
typedef void* (*create_fn)(void* p);
typedef void  (*settext_fn)(void* o, const char* t);
typedef void  (*setxy_fn)(void* o, int32_t a, int32_t b);
typedef void  (*obj1_fn)(void* o);
typedef void  (*eninv_fn)(void* d, int en);
typedef void  (*refr_fn)(void* t);
typedef void  (*flush_fn)(int a);
typedef int   (*startup_fn)(unsigned id, void* d, unsigned l);

typedef struct ctx {
    mode_vtable_t vt;
    rt_api_t* api;
    uint8_t cfg[32];
    volatile uint32_t* entry;
    void* label;
    uint8_t active, capreq;
    char text[64];
} ctx_t;
static inline ctx_t* ctx_get(void){ return *(ctx_t* volatile*)MODE_CTX_SLOT; }

static void mark(rt_api_t* api, uint8_t s, uint32_t info){
    uint8_t r[7]={0xA7,0x55,s,(uint8_t)info,(uint8_t)(info>>8),(uint8_t)(info>>16),(uint8_t)(info>>24)};
    api->reply(r,7);
}

static int our_uiCb(unsigned event, unsigned a2, unsigned a3, void* sctx){
    (void)a2;(void)a3;(void)sctx;
    ctx_t* c = ctx_get(); if(!c || !c->active) return 0;
    void* disp = ((getptr_fn)FW_LV_DISP_GET_DEF)();
    if(!c->label){
        mark(c->api,'U',event);
        void* top = ((layer_fn)FW_LV_DISP_LAYER_TOP)(disp);
        void* lbl = ((create_fn)FW_LV_LABEL_CREATE)(top);
        mark(c->api,'L',(uint32_t)lbl);
        if(lbl){ ((settext_fn)FW_LV_LABEL_SET_TEXT)(lbl,c->text); ((setxy_fn)FW_LV_OBJ_SET_POS)(lbl,150,150); c->label=lbl; }
        else { c->label=(void*)1u; }
    }
    if(c->label && c->label!=(void*)1u){
        ((eninv_fn)FW_LV_DISP_EN_INVAL)(disp, 1);        /* idle disables invalidation; re-enable */
        ((obj1_fn)FW_LV_OBJ_INVALIDATE)(c->label);
        *(volatile uint32_t*)FB_CLEAR_CB = 0u;
        ((refr_fn)FW_LV_REFR_TIMER)(0);                  /* render label into the canvas NOW */
        if(c->capreq){                                    /* capture the freshly-rendered canvas */
            c->capreq = 0;
            const uint8_t* fb = ss_fb_ptr();
            if(fb) cfw_screenshot_capture(fb, 640u, 480u, 4u);
        }
        ((flush_fn)FW_JBD_FLUSH)(1);                      /* burst -> panel (wake + show) */
    }
    return 0;
}
static int our_dataCb(unsigned a,unsigned b,unsigned d,unsigned e){(void)a;(void)b;(void)d;(void)e;return 0;}

static void do_open(ctx_t* c){
    for(int i=0;i<32;i++) c->cfg[i]=0;
    *(uint32_t*)(c->cfg+0)=OUR_PAGEID; c->cfg[0x0b]=0;
    uint32_t count=*(volatile uint32_t*)REG_COUNT;
    if(count>=120u){ mark(c->api,'E',count); return; }
    volatile uint32_t* e=(volatile uint32_t*)(REG_BASE+count*16u);
    e[0]=OUR_APPID; e[1]=(uint32_t)&our_dataCb; e[2]=(uint32_t)&our_uiCb; e[3]=(uint32_t)c->cfg;
    __asm__ volatile("dsb sy":::"memory");
    *(volatile uint32_t*)REG_COUNT=count+1u; c->entry=e; c->active=1;
    mark(c->api,'R',count+1u);
    ((startup_fn)FW_DISPLAY_STARTUP)(OUR_APPID,0,0);
}

static void sh_init(rt_api_t* api){
    ctx_t* c=ctx_get();
    const char* d="HELLO G2 CFW"; int i=0; for(;d[i]&&i<63;i++) c->text[i]=d[i]; c->text[i]=0;
    mark(api,'I',0);
}
static void sh_data(uint8_t* b,int n){
    ctx_t* c=ctx_get(); if(!c) return;
    if(n>=1 && b[0]=='g'){ do_open(c); return; }
    if(n>=1 && b[0]=='s'){ c->capreq=1; return; }         /* request in-thread capture next tick */
    int i=0; for(;i<n&&i<63;i++) c->text[i]=(char)b[i]; c->text[i]=0; c->label=0; /* re-render new text */
}
static void sh_tick(uint32_t d){(void)d;}
static void sh_input(void* e){(void)e;}
static void sh_exit(void){ ctx_t* c=ctx_get(); if(!c) return; if(c->entry){c->entry[0]=0;c->entry[2]=0;} c->api->mem_free(c); *(ctx_t* volatile*)MODE_CTX_SLOT=0; }

mode_vtable_t* payload_entry(rt_api_t* api){
    ctx_t* c=(ctx_t*)api->mem_alloc(sizeof(ctx_t));
    if(!c) return 0;
    for(unsigned i=0;i<sizeof(ctx_t);i++) ((uint8_t*)c)[i]=0;
    c->vt.init=sh_init; c->vt.tick=sh_tick; c->vt.on_input=sh_input; c->vt.on_data=sh_data; c->vt.exit=sh_exit;
    c->api=api;
    *(ctx_t* volatile*)MODE_CTX_SLOT=c;
    return &c->vt;
}
