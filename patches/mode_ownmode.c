/*
 * mode_ownmode.c — enter our OWN full-screen foreground mode (dashboard hidden), the sanctioned
 * way (like EvenHub/terminal), per the wf_ownmode analysis. NO raw-canvas, NO refr, NO fighting.
 *
 * 'g' => wake the panel (FUN_004720d0), block the IMU idle power-down, register our app as a
 * VISIBLE BASE page (cfg[0x17]=1 is make-or-break), and display_startup() it. The stock display
 * thread tears the dashboard down, rebuilds the 576x288 containers, and dispatches STARTUP(event2)
 * to our uiCb, which builds a full-screen lv_label and stores it in cfg[4] (mandatory — page_manager
 * reparents+activates it). We then own the whole lens and receive event-4 ticks.
 *
 * Milestone 1: label only (zero pixel-format risk). Markers: I=init, F=fg|pwr, R=registered+count,
 * S=startup posted, U=uiCb STARTUP+root, T=tick(every 64), X=close.
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

#define FW_DISPLAY_STARTUP 0x00443905u
#define FW_WAKE_FSM        0x004720d1u   /* FUN_004720d0() full power-up FSM */
#define FW_WAKE_BARE       0x00471ee3u   /* FUN_00471ee2() bare cmd0 power-up */
#define FW_PWRDOWN_FSM     0x004722fdu   /* FUN_004722fc() graceful power-down (teardown) */
#define FW_LV_LABEL_CREATE 0x004b1c97u
#define FW_LV_LABEL_SETTEXT 0x004b1cafu
#define FW_LV_OBJ_SET_POS  0x0043f03bu
#define FW_LV_OBJ_SET_SIZE 0x0043f461u
#define FW_LV_OBJ_INVAL    0x004405f7u

#define REG_BASE     0x20066210u
#define REG_COUNT    0x20074410u
#define FG_STATE     0x20074e00u   /* byte: 0=idle/dashboard, 1=fg app up, 2=teardown */
#define IMU_HEADDOWN 0x20074eafu   /* byte: 0 blocks idle head-down power-off */
#define PANEL_PWR    0x20074428u   /* byte: 0=panel off, nonzero=on */
#define MODE_CTX_SLOT 0x20053404u
#define OUR_APPID  0x0077u

typedef void  (*voidfn)(void);
typedef int   (*startupfn)(unsigned,void*,unsigned);
typedef void* (*create_fn)(void*);
typedef void  (*settext_fn)(void*,const char*);
typedef void  (*setxy_fn)(void*,int32_t,int32_t);
typedef void  (*obj1_fn)(void*);

mode_vtable_t* payload_entry(rt_api_t* api);
__attribute__((naked, used)) void _start(void){ __asm__ volatile ("b.w payload_entry"); }

typedef struct ctx { mode_vtable_t vt; rt_api_t* api; uint8_t cfg[32];
                     volatile uint32_t* entry; void* root; uint32_t ticks; uint8_t started; } ctx_t;
static inline ctx_t* ctx_get(void){ return *(ctx_t* volatile*)MODE_CTX_SLOT; }
static void mark(rt_api_t* a, uint8_t s, uint32_t v){ uint8_t r[6]={0xA7,0x4d,s,(uint8_t)v,(uint8_t)(v>>8),(uint8_t)(v>>16)}; a->reply(r,6); }

/* display-thread uiCb: build our page on STARTUP, keep it, count ticks. NO refr/flush. */
static int our_uiCb(unsigned event, unsigned a2, unsigned a3, void* container){
    (void)a2;(void)a3;
    ctx_t* c = ctx_get(); if(!c) return 0;
    if(event==2u){
        void* root = ((create_fn)FW_LV_LABEL_CREATE)(container);
        if(root){
            ((settext_fn)FW_LV_LABEL_SETTEXT)(root, "HELLO  G2  CFW\n\nOMORI2 OWN MODE");
            ((setxy_fn)FW_LV_OBJ_SET_POS)(root, 60, 90);
            *(uint32_t*)(c->cfg + 4) = (uint32_t)root;   /* MANDATORY: page_manager activates cfg[4] */
            c->root = root;
        }
        mark(c->api, 'U', (uint32_t)root);
    } else if(event==5u){
        c->root = 0; mark(c->api, 'X', 5);
    } else if(event==4u){
        c->ticks++; if((c->ticks & 63u)==1u) mark(c->api, 'T', c->ticks);
    }
    return 0;
}
static int our_dataCb(unsigned a,unsigned b,unsigned d,unsigned e){(void)a;(void)b;(void)d;(void)e;return 0;}

static void go(ctx_t* c){
    uint8_t fg  = *(volatile uint8_t*)FG_STATE;
    uint8_t pwr = *(volatile uint8_t*)PANEL_PWR;
    mark(c->api, 'F', (uint32_t)fg | ((uint32_t)pwr<<8));
    /* wake the panel + block idle power-down */
    ((voidfn)FW_WAKE_FSM)();
    if(*(volatile uint8_t*)PANEL_PWR == 0) ((voidfn)FW_WAKE_BARE)();
    *(volatile uint8_t*)IMU_HEADDOWN = 0;
    /* build the page cfg: BASE + VISIBLE */
    for(int i=0;i<32;i++) c->cfg[i]=0;
    *(uint32_t*)(c->cfg+0)    = OUR_APPID;   /* page_id */
    c->cfg[0x0b]              = 0;            /* type: base */
    c->cfg[0x17]              = 1;            /* visible_base (or we get LV_OBJ_FLAG_HIDDEN) */
    *(uint32_t*)(c->cfg+0x0c) = 576u;
    *(uint32_t*)(c->cfg+0x10) = 288u;
    /* register our app */
    uint32_t count = *(volatile uint32_t*)REG_COUNT;
    if(count >= 120u){ mark(c->api,'E',count); return; }
    volatile uint32_t* e = (volatile uint32_t*)(REG_BASE + count*16u);
    e[0]=OUR_APPID; e[1]=(uint32_t)&our_dataCb; e[2]=(uint32_t)&our_uiCb; e[3]=(uint32_t)c->cfg;
    __asm__ volatile("dsb sy":::"memory");
    *(volatile uint32_t*)REG_COUNT = count+1u; c->entry=e;
    mark(c->api,'R',count+1u);
    /* enter foreground */
    ((startupfn)FW_DISPLAY_STARTUP)(OUR_APPID, 0, 0);
    c->started = 1;
    mark(c->api,'S',(uint32_t)OUR_APPID);
}

static void m_init(rt_api_t* api){ uint8_t r[6]={0xA7,0x4d,'I',0,0,0}; api->reply(r,6); }
static void m_data(uint8_t* b,int n){ ctx_t* c=ctx_get(); if(!c) return;
    if(n>=1 && b[0]=='g'){ go(c); return; }
    if(n>=1 && b[0]=='q'){ /* panic: make entry inert */ if(c->entry){c->entry[0]=0;c->entry[2]=0;} mark(c->api,'Q',0); return; } }
static void m_tick(uint32_t d){(void)d;} static void m_input(void* e){(void)e;}
static void m_exit(void){ ctx_t* c=ctx_get(); if(!c) return; if(c->entry){c->entry[0]=0;c->entry[2]=0;} c->api->mem_free(c); *(ctx_t* volatile*)MODE_CTX_SLOT=0; }

mode_vtable_t* payload_entry(rt_api_t* api){
    ctx_t* c=(ctx_t*)api->mem_alloc(sizeof(ctx_t)); if(!c) return 0;
    for(unsigned i=0;i<sizeof(ctx_t);i++) ((uint8_t*)c)[i]=0;
    c->vt.init=m_init; c->vt.tick=m_tick; c->vt.on_input=m_input; c->vt.on_data=m_data; c->vt.exit=m_exit;
    c->api=api; *(ctx_t* volatile*)MODE_CTX_SLOT=c; return &c->vt;
}
