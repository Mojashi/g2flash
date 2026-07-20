/*
 * mode_ownapp.c — hot-loaded PAYLOAD that displays cleanly via the SANCTIONED display path.
 *
 * The lesson from mode_draw/mode_drawterm: writing raw pixels into the panel canvas fights the
 * LVGL compositor (garbled), and doing it from the BLE-RX context is a cross-thread LVGL hazard.
 * The clean way: get our code to run INSIDE the display thread (the only place LVGL is
 * thread-safe), then use LVGL itself to put a widget on the ALWAYS-COMPOSITED top layer —
 * no page-manager opacity/slide-in mechanics to fight.
 *
 * Mechanism (all fw 2.2.4.34 addresses binary-confirmed; LVGL is stock v9.3):
 *   1. Register our own app in the RAM UI registry (append {appID,dataCb,uiCb,cfg}; bump count).
 *      Our uiCb pointer is into this payload's PIC blob (alive while the loader holds the buffer).
 *   2. display_startup(appID,0,0) posts a STARTUP msg to the display queue (thread-safe FreeRTOS
 *      queue). The display thread later invokes dispatch_ui_event(appID, 2=STARTUP) -> our uiCb.
 *   3. our uiCb runs IN the display thread: lv_label_create(lv_display_get_layer_top(default)),
 *      set text + position. The top layer composites above everything -> guaranteed visible,
 *      no opacity gate, no animation. (screen_ctx arg is ignored on purpose.)
 *
 * Instrumentation: every stage emits an api->reply marker {A7 0x55 <stage> <info...>} so the host
 * sees exactly how far it got — 'R'=registered(+count), 'U'=uiCb entered(+event), 'L'=label made(+ptr).
 * If 'U' never arrives, display_startup did NOT route to our uiCb (dashboard-active open path) and
 * we pivot to the overlay-open API. Failure mode is benign: nothing renders, no canvas touched.
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

/* ---- firmware / LVGL v9.3 entry points (Thumb bit set) ---- */
#define FW_DISPLAY_STARTUP    0x00443905u  /* display_startup(appID, data, len)            */
#define FW_LV_DISP_GET_DEF    0x0044e94fu  /* lv_display_t* lv_display_get_default(void)    */
#define FW_LV_DISP_LAYER_TOP  0x0044ebf3u  /* lv_obj_t* lv_display_get_layer_top(disp)      */
#define FW_LV_SCREEN_ACTIVE   0x0044ee6du  /* lv_obj_t* lv_screen_active(void)              */
#define FW_LV_LABEL_CREATE    0x004b1c97u  /* lv_obj_t* lv_label_create(lv_obj_t* parent)   */
#define FW_LV_LABEL_SET_TEXT  0x004b1cafu  /* lv_label_set_text(lv_obj_t*, const char*)     */
#define FW_LV_OBJ_SET_POS     0x0043f03bu  /* lv_obj_set_pos(lv_obj_t*, int32, int32)       */
#define FW_LV_OBJ_SET_SIZE    0x0043f461u  /* lv_obj_set_size(lv_obj_t*, int32, int32)      */
#define FW_LV_OBJ_INVALIDATE  0x004405f7u  /* lv_obj_invalidate(lv_obj_t*)                  */
#define FW_LV_REFR_TIMER      0x00452541u  /* _lv_display_refr_timer(0)=force render default */
#define FW_JBD_FLUSH          0x00588c91u  /* jbd_flush(1): wake MSPI -> burst canvas -> panel */
#define FB_CLEAR_CB           0x20074468u  /* pre-compose full-canvas clear cb-ptr (0 = skip) */

/* ---- RAM UI registry ---- */
#define REG_BASE   0x20066210u   /* app_entry_t[]: {u32 appID, u32 dataCb, u32 uiCb, u32 cfg} */
#define REG_COUNT  0x20074410u   /* u32 live entry count                                      */
#define OUR_APPID  0x00C5u
#define OUR_PAGEID 0x00C5u

typedef void* (*getptr_fn)(void);
typedef void* (*layer_fn)(void* disp);
typedef void* (*create_fn)(void* parent);
typedef void  (*settext_fn)(void* obj, const char* txt);
typedef void  (*setxy_fn)(void* obj, int32_t a, int32_t b);
typedef int   (*startup_fn)(unsigned appID, void* data, unsigned len);
typedef void  (*obj1_fn)(void* obj);
typedef void  (*refr_fn)(void* tmr);
typedef void  (*flush_fn)(int arg);

#define MODE_CTX_SLOT 0x20053404u

mode_vtable_t* payload_entry(rt_api_t* api);
__attribute__((naked, used)) void _start(void){ __asm__ volatile ("b.w payload_entry"); }

/* cfg + a stable text buffer live in ctx (heap; alive as long as the payload buffer is) */
typedef struct ctx {
    mode_vtable_t vt;
    rt_api_t* api;
    uint8_t  cfg[32];            /* app page cfg (kept minimal: page_id + type)   */
    volatile uint32_t* entry;    /* our registry entry (or 0 if not registered)   */
    void* label;                 /* the LVGL label we created                      */
    char text[64];
} ctx_t;
/* No writable statics allowed (PIC blob is .text+.rodata only): reach ctx via the fixed slot. */
static inline ctx_t* ctx_get(void){ return *(ctx_t* volatile*)MODE_CTX_SLOT; }

static void mark(rt_api_t* api, uint8_t stage, uint32_t info){
    uint8_t r[7]={0xA7,0x55,stage,(uint8_t)info,(uint8_t)(info>>8),(uint8_t)(info>>16),(uint8_t)(info>>24)};
    api->reply(r,7);
}

/* THE display-thread callback (invoked by dispatch_ui_event via the display queue).
 * We get repeated event==4 ticks in the display thread (proven on-device). STARTUP(2) is
 * NOT delivered to a freshly-registered app while the dashboard owns the base, so we create
 * our widget LAZILY on the FIRST tick we receive — that already runs us in the display thread,
 * the only requirement for safe LVGL access. Guarded so it happens exactly once. */
static int our_uiCb(unsigned event, unsigned a2, unsigned a3, void* screen_ctx){
    (void)a2; (void)a3; (void)screen_ctx;
    ctx_t* c = ctx_get(); if(!c) return 0;
    if(!c->label){                                     /* one-shot create */
        mark(c->api, 'U', event);                      /* which event first reached us */
        void* disp = ((getptr_fn)FW_LV_DISP_GET_DEF)();
        void* top  = ((layer_fn)FW_LV_DISP_LAYER_TOP)(disp);
        void* lbl  = ((create_fn)FW_LV_LABEL_CREATE)(top);
        mark(c->api, 'L', (uint32_t)lbl);
        if(lbl){
            ((settext_fn)FW_LV_LABEL_SET_TEXT)(lbl, c->text);
            ((setxy_fn)FW_LV_OBJ_SET_POS)(lbl, 150, 150);
            c->label = lbl;
            *(uint32_t*)(c->cfg + 4) = (uint32_t)lbl;   /* cfg[1]=root (in case page-mgr reparents) */
        } else {
            c->label = (void*)1u;                       /* creation failed: don't retry/flood */
        }
    }
    /* Each display-thread tick: force a synchronous render of our label into the panel canvas,
     * then burst it to the panel GRAM (which also wakes the MSPI/panel). This makes the label
     * visible WITHOUT wearing the glasses AND keeps the panel awake despite the idle power-down,
     * since the firmware's own compositor isn't flushing while idle. All in the display thread. */
    /* NO manual refr/flush: when the glasses are worn the firmware's own compositor loop is
     * running and renders the top layer every frame, so our label composites on top of the
     * dashboard STABLY. Calling _lv_display_refr_timer ourselves nests a refr inside the
     * event dispatch and faults; we just leave the object in the tree and let the loop draw it. */
    return 0;
}
static int our_dataCb(unsigned a,unsigned b,unsigned d,unsigned e){ (void)a;(void)b;(void)d;(void)e; return 0; }

static void do_register_and_open(ctx_t* c){
    /* build a minimal overlay-less cfg: page_id set, type=base(0). page-mgr mostly no-ops. */
    for(int i=0;i<32;i++) c->cfg[i]=0;
    *(uint32_t*)(c->cfg+0) = OUR_PAGEID;
    c->cfg[0x0b] = 0;                                  /* type 0: base branch (no slide-in) */

    uint32_t count = *(volatile uint32_t*)REG_COUNT;
    if(count >= 120u){ mark(c->api,'E',count); return; }
    volatile uint32_t* e = (volatile uint32_t*)(REG_BASE + count*16u);
    e[0] = OUR_APPID;
    e[1] = (uint32_t)&our_dataCb;                      /* &fn carries the Thumb bit */
    e[2] = (uint32_t)&our_uiCb;
    e[3] = (uint32_t)c->cfg;
    __asm__ volatile("dsb sy":::"memory");
    *(volatile uint32_t*)REG_COUNT = count + 1u;       /* publish AFTER the entry is written */
    c->entry = e;
    mark(c->api,'R', count + 1u);

    ((startup_fn)FW_DISPLAY_STARTUP)(OUR_APPID, 0, 0); /* async -> display thread -> our uiCb */
}

static void oa_init(rt_api_t* api){
    ctx_t* c = ctx_get();
    /* default text; can be overridden by on_data before/after */
    const char* d = "HELLO G2 CFW";
    int i=0; for(; d[i] && i<63; i++) c->text[i]=d[i]; c->text[i]=0;
    mark(api,'I',0);
}
/* on_data: byte0 op. 'g'(0x67)=register+open. otherwise treat as UTF-8 label text (before opening). */
static void oa_data(uint8_t* b, int n){
    ctx_t* c = ctx_get(); if(!c) return;
    if(n>=1 && b[0]=='g'){ do_register_and_open(c); return; }
    int i=0; for(; i<n && i<63; i++) c->text[i]=(char)b[i]; c->text[i]=0;
    mark(c->api,'T',(uint32_t)n);
}
static void oa_tick(uint32_t d){ (void)d; }
static void oa_input(void* e){ (void)e; }
static void oa_exit(void){
    ctx_t* c = ctx_get(); if(!c) return;
    if(c->entry){ c->entry[0]=0; c->entry[2]=0; }      /* neutralize our registry entry */
    c->api->mem_free(c); *(ctx_t* volatile*)MODE_CTX_SLOT = 0;
}

mode_vtable_t* payload_entry(rt_api_t* api){
    ctx_t* c = (ctx_t*)api->mem_alloc(sizeof(ctx_t));
    if(!c) return 0;
    for(unsigned i=0;i<sizeof(ctx_t);i++) ((uint8_t*)c)[i]=0;
    c->vt.init=oa_init; c->vt.tick=oa_tick; c->vt.on_input=oa_input; c->vt.on_data=oa_data; c->vt.exit=oa_exit;
    c->api = api;
    *(ctx_t* volatile*)MODE_CTX_SLOT = c;
    return &c->vt;
}
