/*
 * mode_fbdump.c — READ-ONLY screenshot PAYLOAD. Streams the live panel canvas (what LVGL last
 * composited onto the lens) back to the host so the operator can SEE the display without wearing
 * the glasses. Changes nothing on-device.
 *
 * Source buffer: *(u32*)0x20074464 = 640x480 4bpp panel canvas, stride 320 B (2 px/byte; even x =
 * high nibble, odd x = low nibble). We 2x-downsample to 320x240, then RLE-encode the 4-bit gray
 * (mostly-black UI => tiny) and stream RLE entries in RUNTIME_SID frames the host reassembles.
 *
 *   host: RT_OP_SEND "s"  -> payload streams:
 *     data frame : [0xA7 0x53 seq_u16LE  (val_u8 count_u16LE){n}]     n entries, seq 0..
 *     done  frame: [0xA7 0x53 0xFF 0xFF]                              end sentinel
 *   RLE covers the 320*240 downsampled nibbles in raster order; sum(count)=76800.
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
#define SRC_W 640u
#define SRC_H 480u
#define SRC_STRIDE 320u
#define DS 2u
#define OUT_W (SRC_W/DS)   /* 320 */
#define OUT_H (SRC_H/DS)   /* 240 */
#define FRAME_ENTRIES 72u  /* 72*3=216 bytes payload -> fits one aa21 chunk */

mode_vtable_t* payload_entry(rt_api_t* api);
__attribute__((naked, used)) void _start(void){ __asm__ volatile ("b.w payload_entry"); }
typedef struct ctx { mode_vtable_t vt; rt_api_t* api; } ctx_t;
static inline ctx_t* ctx_get(void){ return *(ctx_t* volatile*)MODE_CTX_SLOT; }

static inline uint8_t px4(const uint8_t* fb, uint32_t x, uint32_t y){
    uint8_t b = fb[y*SRC_STRIDE + (x>>1)];
    return (x & 1u) ? (b & 0x0Fu) : (uint8_t)(b >> 4);
}

static void pace(rt_api_t* api, uint32_t ms){ uint32_t t0=api->tick_ms(); while(api->tick_ms()-t0 < ms){} }

static void dump(rt_api_t* api){
    const uint8_t* fb = *(const uint8_t* volatile*)FB_CANVAS_PTR;
    if(!fb || (uint32_t)(( (uint32_t)fb) - 0x20000000u) >= 0x00800000u){ uint8_t e[4]={0xA7,0x53,0xDE,0xAD}; api->reply(e,4); return; }
    uint8_t frame[4 + FRAME_ENTRIES*3];
    uint32_t seq = 0, ne = 0, fi;
    int runval = -1; uint32_t runlen = 0;

    for(uint32_t y=0; y<OUT_H; y++){
        for(uint32_t x=0; x<OUT_W; x++){
            uint8_t v = px4(fb, x*DS, y*DS);
            if((int)v == runval && runlen < 0xFFFFu){ runlen++; continue; }
            if(runval >= 0){
                fi = 4 + ne*3;
                frame[fi]=(uint8_t)runval; frame[fi+1]=(uint8_t)runlen; frame[fi+2]=(uint8_t)(runlen>>8);
                if(++ne == FRAME_ENTRIES){
                    frame[0]=0xA7; frame[1]=0x53; frame[2]=(uint8_t)seq; frame[3]=(uint8_t)(seq>>8);
                    api->reply(frame, 4 + (int)ne*3); seq++; ne=0; pace(api, 6u);
                }
            }
            runval = v; runlen = 1;
        }
    }
    /* flush the final run + any partial frame */
    if(runval >= 0){
        fi = 4 + ne*3;
        frame[fi]=(uint8_t)runval; frame[fi+1]=(uint8_t)runlen; frame[fi+2]=(uint8_t)(runlen>>8); ne++;
    }
    if(ne){
        frame[0]=0xA7; frame[1]=0x53; frame[2]=(uint8_t)seq; frame[3]=(uint8_t)(seq>>8);
        api->reply(frame, 4 + (int)ne*3); pace(api, 6u);
    }
    { uint8_t done[4]={0xA7,0x53,0xFF,0xFF}; api->reply(done,4); }
}

static void fb_init(rt_api_t* api){ uint8_t r[4]={0xA7,0x53,'R','Y'}; api->reply(r,4); }
static void fb_data(uint8_t* b, int n){ ctx_t* c=ctx_get(); if(!c) return; if(n>=1 && b[0]=='s') dump(c->api); }
static void fb_tick(uint32_t d){ (void)d; }
static void fb_input(void* e){ (void)e; }
static void fb_exit(void){ ctx_t* c=ctx_get(); if(c){ c->api->mem_free(c); *(ctx_t* volatile*)MODE_CTX_SLOT=0; } }

mode_vtable_t* payload_entry(rt_api_t* api){
    ctx_t* c=(ctx_t*)api->mem_alloc(sizeof(ctx_t));
    if(!c) return 0;
    c->vt.init=fb_init; c->vt.tick=fb_tick; c->vt.on_input=fb_input; c->vt.on_data=fb_data; c->vt.exit=fb_exit;
    c->api=api;
    *(ctx_t* volatile*)MODE_CTX_SLOT=c;
    return &c->vt;
}
