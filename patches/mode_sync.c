/*
 * mode_sync.c — inject our pixels into the compositor's OWN frame. We register an app whose
 * uiCb the firmware calls every display-thread tick. There we write raw pixels straight into
 * the panel canvas but DO NOT flush — the firmware's compositor bursts the canvas itself right
 * after, so (if our tick lands after its compose) our pixels ride its single burst: no flicker
 * (one burst/frame), no crash (we never call jbd_flush from the display thread), stable while worn.
 *
 * We deliberately do NOT clear the canvas (overlay on top of whatever the compositor drew) so a
 * failure mode is "our block is under the dashboard", not "black". 'g' starts it; markers report.
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

#define FW_DISPLAY_STARTUP 0x00443905u
#define REG_BASE  0x20066210u
#define REG_COUNT 0x20074410u
#define OUR_APPID 0x00C7u
#define OUR_PAGEID 0x00C7u
#define MODE_CTX_SLOT 0x20053404u
#define FB_CANVAS_PTR 0x20074464u
#define PW 640u
#define PH 480u
#define STRIDE (PW/2u)
#define SCALE 3u
#define GLYPH_W (8u*SCALE)

typedef int (*startup_fn)(unsigned,void*,unsigned);
static inline int in_sram(uint32_t p){ return (uint32_t)(p-0x20000000u) < 0x00800000u; }

mode_vtable_t* payload_entry(rt_api_t* api);
__attribute__((naked, used)) void _start(void){ __asm__ volatile ("b.w payload_entry"); }
typedef struct ctx { mode_vtable_t vt; rt_api_t* api; uint8_t cfg[32]; volatile uint32_t* entry;
                     uint8_t running; uint32_t ticks; char text[48]; int len; } ctx_t;
static inline ctx_t* ctx_get(void){ return *(ctx_t* volatile*)MODE_CTX_SLOT; }

static inline void px(uint8_t* fb,uint32_t x,uint32_t y,uint8_t lvl){
    if(x>=PW||y>=PH) return; uint8_t* b=fb+y*STRIDE+(x>>1);
    if(x&1u)*b=(uint8_t)((*b&0xF0u)|(lvl&0x0Fu)); else *b=(uint8_t)((*b&0x0Fu)|(uint8_t)(lvl<<4));
}
static void fillrect(uint8_t* fb,uint32_t x0,uint32_t y0,uint32_t w,uint32_t h,uint8_t lvl){
    for(uint32_t y=y0;y<y0+h;y++) for(uint32_t x=x0;x<x0+w;x++) px(fb,x,y,lvl);
}
static void draw_char(uint8_t* fb,uint32_t x0,uint32_t y0,char ch,uint8_t lvl){
    unsigned i=(unsigned)(uint8_t)ch; if(i<0x20u||i>0x7Fu) i=0x20u;
    const uint8_t* g=FONT8[i-0x20u];
    for(uint32_t r=0;r<8;r++){ uint8_t rw=g[r];
        for(uint32_t c=0;c<8;c++) if(rw&(0x80u>>c))
            for(uint32_t dy=0;dy<SCALE;dy++) for(uint32_t dx=0;dx<SCALE;dx++) px(fb,x0+c*SCALE+dx,y0+r*SCALE+dy,lvl); }
}
static void paint(ctx_t* c){
    uint8_t* fb=*(uint8_t* volatile*)FB_CANVAS_PTR;
    if(!fb||!in_sram((uint32_t)fb)) return;
    /* a solid bright bar + text near the top of the visible window; NO clear, NO flush */
    fillrect(fb,120,150,300,SCALE*8+8,0x00u);     /* black plate behind text for contrast */
    uint32_t x=128;
    for(int i=0;i<c->len;i++){ draw_char(fb,x,154,c->text[i],0x0Fu); x+=GLYPH_W+2u; }
    /* the firmware's own present/burst (right after this tick) carries these pixels */
}

static int our_uiCb(unsigned ev,unsigned a2,unsigned a3,void* sc){
    (void)ev;(void)a2;(void)a3;(void)sc;
    ctx_t* c=ctx_get(); if(!c||!c->running) return 0;
    paint(c); c->ticks++;
    if((c->ticks&63u)==1u){ uint32_t t=c->ticks; uint8_t r[6]={0xA7,0x53,(uint8_t)t,(uint8_t)(t>>8),(uint8_t)(t>>16),(uint8_t)(t>>24)}; c->api->reply(r,6); }
    return 0;
}
static int our_dataCb(unsigned a,unsigned b,unsigned d,unsigned e){(void)a;(void)b;(void)d;(void)e;return 0;}

static void set_text(ctx_t* c,const char* s,int n){ if(n>47)n=47; c->len=n; for(int i=0;i<n;i++)c->text[i]=s[i]; }
static void do_open(ctx_t* c){
    for(int i=0;i<32;i++) c->cfg[i]=0; *(uint32_t*)(c->cfg+0)=OUR_PAGEID; c->cfg[0x0b]=0;
    uint32_t count=*(volatile uint32_t*)REG_COUNT; if(count>=120u) return;
    volatile uint32_t* e=(volatile uint32_t*)(REG_BASE+count*16u);
    e[0]=OUR_APPID; e[1]=(uint32_t)&our_dataCb; e[2]=(uint32_t)&our_uiCb; e[3]=(uint32_t)c->cfg;
    __asm__ volatile("dsb sy":::"memory");
    *(volatile uint32_t*)REG_COUNT=count+1u; c->entry=e; c->running=1;
    { uint8_t r[3]={0xA7,0x53,(uint8_t)(count+1u)}; c->api->reply(r,3); }
    ((startup_fn)FW_DISPLAY_STARTUP)(OUR_APPID,0,0);
}
static void s_init(rt_api_t* api){ ctx_t* c=ctx_get(); set_text(c,"HELLO G2 CFW",12); uint8_t r[3]={0xA7,0x53,'I'}; api->reply(r,3); }
static void s_data(uint8_t* b,int n){ ctx_t* c=ctx_get(); if(!c) return;
    if(n>=1&&b[0]=='g'){ do_open(c); return; } if(n>=1&&b[0]=='x'){ c->running=0; return; }
    set_text(c,(const char*)b,n); }
static void s_tick(uint32_t d){(void)d;} static void s_input(void* e){(void)e;}
static void s_exit(void){ ctx_t* c=ctx_get(); if(!c) return; c->running=0; if(c->entry){c->entry[0]=0;c->entry[2]=0;} c->api->mem_free(c); *(ctx_t* volatile*)MODE_CTX_SLOT=0; }

mode_vtable_t* payload_entry(rt_api_t* api){
    ctx_t* c=(ctx_t*)api->mem_alloc(sizeof(ctx_t)); if(!c) return 0;
    for(unsigned i=0;i<sizeof(ctx_t);i++) ((uint8_t*)c)[i]=0;
    c->vt.init=s_init; c->vt.tick=s_tick; c->vt.on_input=s_input; c->vt.on_data=s_data; c->vt.exit=s_exit;
    c->api=api; *(ctx_t* volatile*)MODE_CTX_SLOT=c; return &c->vt;
}
