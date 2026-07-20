/*
 * fw_2.2.6.10.h — validated firmware primitive addresses for Even Realities G2
 * firmware 2.2.6.10, for the mode-runtime loader CFW.
 *
 * All values are the RUNTIME THUMB FUNCTION POINTER (entry|1) as produced by the
 * 2.2.6.10 address-map (patches/addrmap_2.2.6.10.json) — usable directly as C
 * function pointers. Parity note: the 2.2.6.10 main app sits at an ODD file offset
 * (a bootloader OTA component was added), real load base 0x39E67F; these pointers
 * = file_off + 0x39E680 = even_entry|thumb. To PATCH bytes: file_off = ptr - 0x39E680
 * (do NOT clear the low bit). Verified 40/40 via an adversarial derive->verify workflow.
 */
#ifndef FW_2_2_6_10_H
#define FW_2_2_6_10_H
#include <stdint.h>

/* ---- core primitives (call via these fn-ptr typedefs) ---- */
#define FW_MALLOC_A    0x004991d9u  /* void* malloc(size) */
#define FW_FREE_A      0x0049921du  /* void free(void*) — malloc-pool partner (same lock 0x46dcbc as FW_MALLOC; verified). WAS 0x43d549 = WRONG pool (brick). */
#define FW_SEND_A      0x0049a01bu  /* int aa21_send(int type=1, int sid, void* ptr, int len) — no-ack */
#define FW_SIDE_A      0x0047ea6fu  /* int lens_side(void) -> 2=left, 1=right (transmit lens) */
#define FW_TICK_A      0x0043e0d9u  /* uint32_t get_tick_ms(void) */
#define FW_FLUSH_A     0x00499615u  /* void dcache_clean(void* p) — p==0: full clean(DCCSW); else {addr,len} range(DCCMVAC); DSB+ISB */

/* ---- cache maintenance (make freshly-written RAM code executable) ---- */
#define FW_ICACHE_ENABLE_A   0x004461d9u /* SCB_EnableICache (ICIALLU=0 ONLY if IC was disabled; sets CCR.IC) */
#define FW_ICACHE_DISABLE_A  0x0044621fu /* SCB_DisableICache (clears CCR.IC; ICIALLU=0; DSB; ISB) */
#define FW_DCACHE_ENABLE_A   0x00446257u /* SCB_EnableDCache */
#define FW_DCACHE_INV_A      0x00446339u /* combined: r0=0 set/way|&{addr,len} range; r1=0 inval-only|!=0 clean+inval */
/* I-cache full invalidate template = call DISABLE then ENABLE (ENABLE runs ICIALLU=0 because IC was just cleared) */
#define REG_ICIALLU    0xE000EF50u  /* write 0 to invalidate entire I-cache (inline option) */

/* ---- inflate (zlib, for compressed payloads/images) ---- */
#define FW_INFLATE_A   0x005e3097u  /* int inflate(z_streamp, int flush) */
#define FW_INFLATEINIT2_A 0x005e2fc9u
#define FW_INFLATEEND_A 0x005e2f8du

/* ---- display / LVGL ---- */
#define FW_LOADBMP_A   0x00500ab5u  /* BMP decoder */
#define FW_SETSRC_A    0x004bcb87u  /* lv_image_set_src(obj, src) */
#define FW_INVAL_A     0x00464b5du  /* lv_obj_invalidate(obj) */

/* ---- input / UI event ---- */
#define FW_POST_UI_EVENT_A 0x00483e03u /* post_ui_event(ctx, code, data) */
#define FW_FOREGROUND_CTX_A 0x00483dedu /* foreground_mode_ctx() */
#define FW_SYSEVT_A    0x004fe671u  /* send EvenHub SysEvent(0,0,0,EventType,0,0) */

/* ---- rtos timers (for the tick source) ---- */
#define FW_TIMER_NEW_A   0x0043e3a3u /* osTimerNew(cb, type, arg, attr) */
#define FW_TIMER_START_A 0x0043e48bu /* osTimerStart(handle, ms) */
#define FW_TIMER_STOP_A  0x0046d9dfu /* osTimerStop(handle) */

/* ---- BLE inbound dispatcher (fall-through for non-runtime sids) ---- */
#define FW_DISPATCH_A  0x00466a2bu  /* universal aa21 frame dispatcher (find_ui_DataHandler_by_id) */

/* ---- RAM globals (re-derived from 2.2.6.10 literal pools — some moved regions!) ---- */
#define RAM_FB_CANVAS_PTR   0x20074528u /* -> jbd4010 panel scan-out canvas base (640x480 4bpp) */
#define RAM_FB_DRAWBUF_PTR  0x200746b4u /* -> lv_draw_buf_t* (LVGL L8 render target) */
#define RAM_UI_CTX          0x200744d0u /* foreground UI ctx pointer */
#define RAM_EVT_SRC         0x2034dc30u /* current input event record; byte0=source (0/1=L/R pad,4=ring) */
#define RAM_TERMINAL_STATE  0x2006e0d0u /* terminal state singleton (fsm_state at +0x275) */
#define RAM_CFW_CTX_SLOT    0x20003ffcu /* ble_msgrx spare ctx field the CFW may reuse */

/* ---- hook sites (byte-patch targets; file_off = A - 0x39E680) ---- */
/* RX intake: redirect the bl at this site (stock 4 bytes: e7 f7 00 ff = bl 0x466a2a) to rx_hook. */
#define HOOK_RX_SITE_A       0x0047ec27u /* site pointer (even entry 0x0047ec26, file off 0xE05A7) */
#define HOOK_RX_SITE_STOCK   {0xe7,0xf7,0x00,0xff}
/* Input dispatcher: trampoline at entry (r0 = event record {u16 source, u32 subtype, u32 data}). */
#define INPUT_DISPATCH_ENTRY_A 0x0046728du /* entry 0x0046728c */
/* Entry detour steals the first 4 bytes (push {r3-r7,lr}=f8b5, sub sp,#0x28=8ab0). The
 * trampoline replicates those two stolen instrs then continues into the dispatcher body
 * at 0x00467290 (the instruction after them). This is the tail-jump target (Thumb bit set). */
#define INPUT_DISPATCH_CONT_A  0x00467291u /* continue at 0x00467290 | thumb */
#define INPUT_DISPATCH_STOLEN  {0xf8,0xb5,0x8a,0xb0} /* stock 4 bytes at 0x0046728c */
#define INPUT_SLIDE_SITE_A   0x004675cbu /* bl at 0x4675ca posts slide (dx=sxth r4, dy=sxth r7) */
#define INPUT_LONGPRESS_SITE_A 0x00467399u /* bl at 0x467398 (subtype 3 long-press) */
#define INPUT_RING_SITE_A    0x004676c9u /* bl at 0x4676c8 (subtype 0xe ring release-long-press) */

/* ---- fault recovery / reset ---- */
#define REG_VTOR       0xE000ED08u  /* vector table offset; stock = 0x438000 */
#define REG_AIRCR      0xE000ED0Cu  /* write 0x05FA0004 = VECTKEY|SYSRESETREQ -> system reset */
#define AIRCR_SYSRESET 0x05FA0004u
#define VTOR_STOCK     0x00438000u
/* Apollo510 hardware watchdog */
#define WDT_CFG        0x40024000u
#define WDT_RSTRT      0x40024004u  /* pet: write 0xB2 */
#define WDT_LOCK       0x40024008u

/* ---- runtime protocol ---- */
#define RUNTIME_SID    0x7bu        /* dedicated inbound sid for runtime control */
/* opcode = payload[0] */
#define RT_OP_LOAD_FRAG  0x01u      /* [op][mode_id][frag_idx u16][last u8][bytes...] (frags in order from idx 0) */
#define RT_OP_ACTIVATE   0x02u      /* [op][mode_id][total_len u32 LE][crc32 u32 LE] -> verify len+CRC, cache-maintain, jump */
#define RT_OP_SEND       0x03u      /* [op][mode_id][data...] -> mode.on_data */
#define RT_OP_RESET      0x04u      /* [op] -> exit active mode, free buffers */
#define RT_OP_PING       0x05u      /* [op] -> reply on RUNTIME_SID (liveness) */
#define RT_MAGIC         0xA7u      /* reply frames start with this */

/* ---- runtime state anchor (build.py has no .data/.bss: all mutable state lives in a
 * malloc'd rt_state_t whose pointer is stored at this one fixed RAM word) ---- */
#define RT_STATE_ANCHOR_A 0x20003ffcu /* == RAM_CFW_CTX_SLOT; holds rt_state_t* (0 at cold boot) */
#define RT_STATE_MAGIC    0x52544d31u /* "RTM1" — tags a live rt_state_t */
#define RT_TICK_HZ_MS     33u         /* ~30 Hz osTimer period */
#define RT_TIMER_PERIODIC 1           /* osTimerType_t osTimerPeriodic */

#endif /* FW_2_2_6_10_H */
