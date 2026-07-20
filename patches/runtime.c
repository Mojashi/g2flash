/*
 * runtime.c — mode-runtime loader CFW for Even Realities G2 firmware 2.2.4.34.
 *
 * Flashed ONCE. Thereafter it receives arbitrary "mode" code payloads over BLE into RAM
 * and executes them, exposing an API table of firmware primitives. Every feature becomes
 * a hot-loaded payload — no re-flash, safe iteration, firmware-version-independent.
 *
 * Cortex-M55, Thumb-2. A malloc'd SRAM buffer holds+runs payload code after cache
 * maintenance. (If the MPU marks the heap execute-never, the jump faults into a
 * recoverable watchdog reset — NOT a brick; see the safety note below.)
 *
 * WHY 2.2.4.34 (the safe base): single app code component, so runtime addr = file
 * off + 0x39E680 across the whole image — no multi-component base correction (the
 * 2.2.6.10 brick risk). See fw_2.2.4.34.h.
 *
 * SAFETY (flashed to real hardware; brick-obsessed after an adversarial review):
 *  - The ONLY brick-critical step is the container assembly (patch_loader.py), which
 *    reuses the proven append/preamble/CRC path the currently-flashed CFW was built with.
 *  - The ONLY MRAM code patch is the RX-hook bl-redirect at 0x0045aaa4 (the same proven
 *    site + idiom the screenshot CFW used). Everything else the loader does is at runtime.
 *  - The loader is DORMANT unless a frame arrives on RUNTIME_SID; for every other sid it
 *    tail-calls the stock dispatcher, so the glasses boot and behave byte-for-byte stock
 *    and OTA re-flash is always reachable (not soft-brickable).
 *  - All firmware pointers come from the binary-confirmed map in fw_2.2.4.34.h.
 *  - FW_FREE is the verified malloc-pool partner (shared mutex + heap desc; also the RX
 *    wrapper's own free target), not a foreign pool.
 *  - ACTIVATE verifies expected length + CRC32 of the loaded blob before it EVER jumps in.
 *  - The active mode is torn down (mode=0) BEFORE any buffer is freed, inside a PRIMASK
 *    critical section; buffers are DEFERRED-freed one generation later so a concurrent
 *    input/data callback never executes freed code.
 *  - A range guard (rt_in_sram) gates the jump target.
 *  - Cache maintenance is fully inline (DCCMVAC clean-by-MVA + ICIALLU) — no dependency
 *    on a derived firmware cache function, and no global cache-disable window.
 *  - No writable statics: all mutable state lives in a malloc'd rt_state_t anchored at one
 *    fixed RAM word (see runtime_state.h). Crash recovery is by reboot (watchdog/power).
 *  - v1 installs NO timer and NO input hook (minimal surface); on-device tick/input are a
 *    later loader revision. Payloads animate via host-driven RT_OP_SEND frames for now.
 *  - V2 CAVEAT (adversarial review 2026-07-18): the concurrency machinery below (PRIMASK
 *    guards, busy flag, one-generation deferred-free via prev_buf) is DORMANT-safe in v1
 *    because nothing calls a mode callback concurrently with RX. Before a v2 arms a timer
 *    or input hook, two latent issues must be closed: (1) deferred-free is only ONE
 *    generation deep, so a burst of reloads could free a buffer an in-flight callback is
 *    still executing (needs a quiescence gate, not just prev_buf); and (2) S->mode is
 *    published before vt->init() finishes, so a callback could see a half-initialized mode.
 */
#include <stdint.h>
#include "fw_2.2.4.34.h"

/* struct tags are forward-declared in runtime_state.h; define them before including it. */
typedef struct rt_api rt_api_t;
typedef struct mode_vtable mode_vtable_t;
#include "runtime_state.h"

/* ---- firmware primitive fn-ptr typedefs ---- */
typedef void*   (*fw_malloc_t)(uint32_t);
typedef void    (*fw_free_t)(void*);
typedef int     (*fw_send_t)(int type, int sid, void* ptr, int len);
typedef int     (*fw_side_t)(void);
typedef uint32_t(*fw_tick_t)(void);
typedef int     (*fw_dispatch_t)(int sid, void* ptr, int len, int subcode);

#define FW_MALLOC   ((fw_malloc_t)FW_MALLOC_A)
#define FW_FREE     ((fw_free_t)FW_FREE_A)
#define FW_SEND     ((fw_send_t)FW_SEND_A)
#define FW_SIDE     ((fw_side_t)FW_SIDE_A)
#define FW_TICK     ((fw_tick_t)FW_TICK_A)
#define FW_DISPATCH ((fw_dispatch_t)FW_DISPATCH_A)

/* ---- API table handed to every payload (append-only; never reorder for ABI stability) ---- */
struct rt_api {
    uint32_t abi_version;                            /* = RT_API_VERSION */
    void*    (*mem_alloc)(uint32_t n);
    void     (*mem_free)(void* p);
    int      (*send)(int sid, void* ptr, int len);   /* aa21 no-ack, gated to the transmit lens */
    void     (*reply)(void* ptr, int len);           /* send on RUNTIME_SID */
    int      (*lens_side)(void);                      /* 2=left,1=right */
    uint32_t (*tick_ms)(void);
    uint8_t* (*fb_canvas)(void);                      /* 640x480 4bpp panel canvas (2px/byte) */
    void     (*present)(void);                        /* dcache-clean the whole canvas so panel DMA sees new pixels */
    void     (*dcache_clean)(void* p, uint32_t len);  /* dcache-clean an arbitrary range to PoC */
    uint32_t fb_w, fb_h;
};
#define RT_API_VERSION 1u

/* ---- mode vtable a payload returns from its entry point ---- */
struct mode_vtable {
    void (*init)(rt_api_t* api);          /* once, after load */
    void (*tick)(uint32_t dt_ms);         /* ~30Hz; render via framebuffer + present (not LVGL objects) */
    void (*on_input)(void* event_record); /* gesture: {u16 source, u32 subtype, u32 data} */
    void (*on_data)(uint8_t* buf, int len);
    void (*exit)(void);                   /* before switching away */
};
typedef mode_vtable_t* (*payload_entry_t)(rt_api_t* api);

#define RT_MAX_PAYLOAD (16u*1024u)   /* upfront malloc on frag idx 0; modes are small.
                                      * If the heap can't satisfy it, buf=0 and the loader
                                      * stays safe (no load, PING reports mode=0). */

/* ---- tiny primitives (no dependency on fw memcpy/arg-order) ---- */
static void rt_memcpy(uint8_t* d, const uint8_t* s, int n){ while(n-->0) *d++=*s++; }
static uint32_t rd32(const uint8_t* p){ return (uint32_t)p[0]|((uint32_t)p[1]<<8)|((uint32_t)p[2]<<16)|((uint32_t)p[3]<<24); }
static uint32_t crc32b(const uint8_t* p, uint32_t n){
    uint32_t c=0xFFFFFFFFu;
    for(uint32_t i=0;i<n;i++){ c^=p[i]; for(int k=0;k<8;k++) c=(c&1u)?(c>>1)^0xEDB88320u:(c>>1); }
    return ~c;
}
/* PRIMASK critical section (threads are preempted by SysTick/PendSV; IRQ-off = brief mutex) */
static inline uint32_t irq_off(void){ uint32_t p; __asm volatile("mrs %0, primask\n\tcpsid i":"=r"(p)::"memory"); return p; }
static inline void     irq_on(uint32_t p){ __asm volatile("msr primask, %0"::"r"(p):"memory"); }

/* ---- inline Cortex-M55 cache maintenance (no derived firmware cache fn needed) ----
 * D-cache clean by MVA to point-of-coherency over [addr, addr+len): pushes freshly
 * written bytes out of the (possibly write-back) D-cache so the I-cache refill / panel
 * DMA sees them. Iterating by CACHE_LINE covers every line the range touches (aligning
 * the start down to a line boundary). DCCMVAC is a no-op if the D-cache is disabled, so
 * this is always safe. */
static inline void dcache_clean_range(uint32_t addr, uint32_t len){
    if(!len) return;
    uint32_t p   = addr & ~(CACHE_LINE - 1u);
    uint32_t end = addr + len;
    __asm volatile("dsb sy":::"memory");
    for(; (int32_t)(end - p) > 0; p += CACHE_LINE) *(volatile uint32_t*)REG_DCCMVAC = p;
    __asm volatile("dsb sy\n\tisb sy":::"memory");
}
/* I-cache invalidate all (ICIALLU) — after a dcache_clean_range, makes freshly-written
 * code fetchable. Avoids the global disable/enable window. */
static inline void icache_invalidate(void){
    __asm volatile("dsb sy\n\tisb sy":::"memory");
    *(volatile uint32_t*)REG_ICIALLU = 0u;
    __asm volatile("dsb sy\n\tisb sy":::"memory");
}

/* ---- API implementations (all state via S) ---- */
static int   api_send(int sid, void* p, int len){ if(FW_SIDE()!=1) return -1; return FW_SEND(1, sid, p, len); }
static void  api_reply(void* p, int len){ if(FW_SIDE()==1) FW_SEND(1, RUNTIME_SID, p, len); }
static int   api_side(void){ return FW_SIDE(); }
static void* api_alloc(uint32_t n){ return FW_MALLOC(n); }
static void  api_free(void* p){ FW_FREE(p); }
static uint32_t api_tick(void){ return FW_TICK(); }
static uint8_t* api_fb(void){ return *(uint8_t* volatile*)RAM_FB_CANVAS_PTR; }
static void  api_present(void){ dcache_clean_range((uint32_t)(*(uint8_t* volatile*)RAM_FB_CANVAS_PTR), 640u*480u/2u); }
static void  api_dcache_clean(void* p, uint32_t len){ dcache_clean_range((uint32_t)p, len); }

static void init_api(rt_state_t* S){
    rt_api_t* a=(rt_api_t*)S->api;
    a->abi_version=RT_API_VERSION;
    a->mem_alloc=api_alloc; a->mem_free=api_free;
    a->send=api_send; a->reply=api_reply; a->lens_side=api_side;
    a->tick_ms=api_tick; a->fb_canvas=api_fb; a->present=api_present; a->dcache_clean=api_dcache_clean;
    a->fb_w=640; a->fb_h=480;
}

/* verify integrity, cache-maintain, tear down old mode, then jump into the loaded blob. */
static void activate_payload(rt_state_t* S, uint32_t expect_len, uint32_t expect_crc){
    if(!S->buf || S->buf_len==0) return;
    if(S->buf_len!=expect_len) return;                       /* incomplete/over-budget */
    if(crc32b(S->buf, S->buf_len)!=expect_crc) return;       /* corrupt / dropped fragment */
    if(!rt_in_sram((uint32_t)S->buf)) return;                /* exec range guard */
    /* push code out of D-cache to unified memory, then invalidate I-cache (inline) */
    dcache_clean_range((uint32_t)S->buf, S->buf_len);
    icache_invalidate();
    /* retire the previous mode BEFORE anyone can call into freed/replaced code */
    uint32_t pm=irq_off(); mode_vtable_t* old=S->mode; S->mode=0; S->busy=1; irq_on(pm);
    if(old && old->exit) old->exit();
    /* run the new payload's entry (offset 0, thumb) -> returns its vtable */
    init_api(S);
    payload_entry_t entry=(payload_entry_t)((uint32_t)S->buf | 1u);
    mode_vtable_t* vt=entry((rt_api_t*)S->api);
    uint32_t pm2=irq_off(); S->mode=vt; S->busy=0; irq_on(pm2);
    if(vt && vt->init) vt->init((rt_api_t*)S->api);
    S->last_tick=FW_TICK();
}

static void retire_mode(rt_state_t* S){
    uint32_t pm=irq_off(); mode_vtable_t* old=S->mode; S->mode=0; irq_on(pm);
    if(old && old->exit) old->exit();
}

/* ---- runtime command handler (sid==RUNTIME_SID) ---- */
static void handle_runtime_cmd(rt_state_t* S, uint8_t* p, int len){
    if(len<1) return;
    switch(p[0]){
    case RT_OP_LOAD_FRAG: {                                    /* [op][mode][idx u16][last u8][bytes] */
        if(len<5) return;
        uint32_t idx=(uint32_t)p[2]|((uint32_t)p[3]<<8);
        uint8_t* data=p+5; int dlen=len-5;
        if(idx==0){
            retire_mode(S);                                   /* stop tick/input using old buf */
            if(S->prev_buf){ FW_FREE(S->prev_buf); S->prev_buf=0; } /* 2-gens old = quiescent */
            S->prev_buf=S->buf;                               /* defer-free current */
            S->buf=(uint8_t*)FW_MALLOC(RT_MAX_PAYLOAD); S->buf_len=0;
            /* fragments must arrive in order from idx 0; a gap is caught by the ACTIVATE CRC */
        }
        if(S->buf && dlen>0 && S->buf_len+(uint32_t)dlen<=RT_MAX_PAYLOAD){
            rt_memcpy(S->buf+S->buf_len, data, dlen); S->buf_len+=(uint32_t)dlen;
        }
        break;
    }
    case RT_OP_ACTIVATE: {                                     /* [op][mode][len u32][crc32 u32] */
        if(len<10){ uint8_t r[2]={RT_MAGIC,0xE0}; api_reply(r,2); return; }
        activate_payload(S, rd32(p+2), rd32(p+6));
        { uint8_t r[3]={RT_MAGIC,RT_OP_ACTIVATE,(uint8_t)(S->mode?1:0)}; api_reply(r,3); }
        break;
    }
    case RT_OP_SEND:                                           /* [op][mode][data] */
        if(len>2){ uint32_t pm=irq_off(); mode_vtable_t* m=S->busy?0:S->mode; irq_on(pm);
                   if(m && m->on_data) m->on_data(p+2, len-2); }
        break;
    case RT_OP_RESET:
        retire_mode(S);
        break;
    case RT_OP_PING: {
        uint8_t r[3]={RT_MAGIC,RT_OP_PING,(uint8_t)(S->mode?1:0)}; api_reply(r,3);
        break;
    }
    default: break;
    }
}

/* ---- RX intake: the patched bl at 0x0045aaa4 lands here with the stock dispatcher's
 * args. Handle RUNTIME_SID commands, then ALWAYS tail-call the stock dispatcher so every
 * sid (incl. our own) keeps identical firmware behavior and the wrapper frees the payload. ---- */
int rt_rx_hook(int sid, void* payload, int len, int subcode){
    /* TRUE dormancy: touch NOTHING (no malloc, no anchor store) unless a frame actually
     * arrives on our private sid. A device that never uses the loader sees zero RAM
     * effect — it boots + behaves byte-for-byte stock. Only a real 0x7b command brings
     * the state up (rt_state_init: lazy alloc; 0 on OOM -> we still fall through to stock). */
    if(sid==(int)RUNTIME_SID && payload && len>=1){
        rt_state_t* S = rt_state_init();
        if(S) handle_runtime_cmd(S, (uint8_t*)payload, len);
    }
    return FW_DISPATCH(sid, payload, len, subcode);
}

/* ---- input forwarding: called from rt_input_tramp with r0 = event record ---- */
void rt_on_input(void* event_record){
    rt_state_t* S=rt_state(); if(!S) return;
    uint32_t pm=irq_off(); mode_vtable_t* m=S->busy?0:S->mode; irq_on(pm);
    if(m && m->on_input) m->on_input(event_record);
}

/* ---- tick: CFW osTimer callback (~30Hz). buf is deferred-freed so a mode pointer read
 * here always refers to still-mapped code. ---- */
void rt_tick(void){
    rt_state_t* S=rt_state(); if(!S) return;
    uint32_t pm=irq_off(); mode_vtable_t* m=S->busy?0:S->mode; irq_on(pm);
    if(m && m->tick){ uint32_t now=FW_TICK(), dt=now-S->last_tick; S->last_tick=now; m->tick(dt); }
}
