/*
 * mode_peek.c — READ-ONLY diagnostic PAYLOAD. Draws NOTHING, changes NOTHING on the
 * display or in firmware state. Its whole job is to let the host read arbitrary device
 * memory over BLE so we can learn the live display-framework layout (page-manager struct,
 * the two layer screens, lv_display, the app cfg structs) without guessing.
 *
 *   host -> RT_OP_SEND: [addr u32 LE][nwords u8]        (bun runtime.ts send 1 hex:<addr LE><nn>)
 *   payload reply     : [0xA7 0x50 addr(4) nwords(1) word0(4) word1(4) ...]   words are LE u32
 *
 * Only SRAM (0x2000_0000..0x2080_0000) and code flash (0x0040_0000..0x0080_0000) are
 * readable; anything else replies nwords=0 (never dereferenced) so a bad address can't
 * fault a peripheral. init() replies a {A7 50 'R' 'D' 'Y'} liveness marker.
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
#define MAX_WORDS 40u

static inline int readable(uint32_t a){
    return ((uint32_t)(a - 0x20000000u) < 0x00800000u)   /* SRAM (TCM/system)  */
        || ((uint32_t)(a - 0x28000000u) < 0x00800000u)   /* extended SRAM bank (LVGL heap/drawbuf) */
        || ((uint32_t)(a - 0x00400000u) < 0x00400000u);  /* code flash (MRAM) */
}

mode_vtable_t* payload_entry(rt_api_t* api);
__attribute__((naked, used)) void _start(void){ __asm__ volatile ("b.w payload_entry"); }

typedef struct ctx { mode_vtable_t vt; rt_api_t* api; } ctx_t;
static inline ctx_t* ctx_get(void){ return *(ctx_t* volatile*)MODE_CTX_SLOT; }

static void pk_init(rt_api_t* api){ uint8_t r[5]={0xA7,0x50,'R','D','Y'}; api->reply(r,5); }

static void pk_data(uint8_t* buf, int len){
    ctx_t* c = ctx_get(); if(!c) return;
    if(len < 5){ uint8_t e[3]={0xA7,0x50,0}; c->api->reply(e,3); return; }
    uint32_t addr = (uint32_t)buf[0] | ((uint32_t)buf[1]<<8) | ((uint32_t)buf[2]<<16) | ((uint32_t)buf[3]<<24);
    uint32_t n = buf[4]; if(n > MAX_WORDS) n = MAX_WORDS;
    uint8_t out[2 + 4 + 1 + MAX_WORDS*4];
    out[0]=0xA7; out[1]=0x50;
    out[2]=(uint8_t)addr; out[3]=(uint8_t)(addr>>8); out[4]=(uint8_t)(addr>>16); out[5]=(uint8_t)(addr>>24);
    uint32_t got = 0;
    for(uint32_t i=0;i<n;i++){
        uint32_t a = addr + i*4u;
        if(!readable(a)) break;
        uint32_t w = *(volatile uint32_t*)a;
        out[7 + got*4]   = (uint8_t)w;
        out[7 + got*4+1] = (uint8_t)(w>>8);
        out[7 + got*4+2] = (uint8_t)(w>>16);
        out[7 + got*4+3] = (uint8_t)(w>>24);
        got++;
    }
    out[6]=(uint8_t)got;
    c->api->reply(out, 7 + (int)got*4);
}

static void pk_noop1(uint32_t d){ (void)d; }
static void pk_noop2(void* e){ (void)e; }
static void pk_exit(void){ ctx_t* c = ctx_get(); if(c){ c->api->mem_free(c); *(ctx_t* volatile*)MODE_CTX_SLOT = 0; } }

mode_vtable_t* payload_entry(rt_api_t* api){
    ctx_t* c = (ctx_t*)api->mem_alloc(sizeof(ctx_t));
    if(!c) return 0;
    c->vt.init = pk_init; c->vt.tick = pk_noop1; c->vt.on_input = pk_noop2; c->vt.on_data = pk_data; c->vt.exit = pk_exit;
    c->api = api;
    *(ctx_t* volatile*)MODE_CTX_SLOT = c;
    return &c->vt;
}
