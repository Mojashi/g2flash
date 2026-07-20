/*
 * fw_2.2.4.34.h — firmware primitive addresses for Even Realities G2 firmware
 * 2.2.4.34, for the mode-runtime loader CFW (the SAFE base — see below).
 *
 * WHY 2.2.4.34 (not 2.2.6.10): the 2.2.4.34 OTA container has a SINGLE Apollo510
 * app code component (ota/s200_firmware_ota.bin). Its 32-byte preamble programs
 * payload[0x20:] to load address 0x00438000, so a payload byte at file offset K
 * maps linearly to runtime address K + 0x39E680 across the WHOLE component — the
 * disassembler base and the runtime base are identical. 2.2.6.10 split the app
 * into TWO code components at different load bases, so a single disassembler base
 * no longer equals the runtime base and every derived address needs a per-component
 * correction (the source of the 2.2.6.10 brick risk we backed away from). None of
 * that exists here.
 *
 * MAPPING (verified against g2_2.2.4.34.bin): runtime = file_off + 0x39E680.
 * To BYTE-PATCH a site: file_off = A - 0x39E680 (do NOT clear the low Thumb bit).
 * All *_A values below are the RUNTIME THUMB FUNCTION POINTER (even_entry | 1) so
 * they are usable directly as C function pointers.
 *
 * Every address in the "core primitives" and "hook site" blocks was CONFIRMED by
 * disassembling the prologue in g2_2.2.4.34.bin (valid push {..,lr} etc.), and the
 * RX hook site was cross-checked against the stock `bl 0x441c68 ; movs r0,r4 ;
 * bl 0x472bb2(free) ; pop {r0,r1,r4,pc}` wrapper idiom (which also re-confirms free).
 */
#ifndef FW_2_2_4_34_H
#define FW_2_2_4_34_H
#include <stdint.h>

/* ---- core primitives (call via fn-ptr typedefs in runtime.c) — all CONFIRMED ---- */
#define FW_MALLOC_A    0x00472b6fu  /* void* malloc(size)  — FUN_00472b6e (push {r4,r5,r6,lr}) */
#define FW_FREE_A      0x00472bb3u  /* void free(void*)    — FUN_00472bb2, SAME pool as malloc
                                     * (shared mutex *0x2007480c, heap desc *0x200749c0; also the
                                     * free target of the RX wrapper tail at 0x45aaaa). */
#define FW_SEND_A      0x0047398du  /* int aa21_send(int type=1, int sid, void* ptr, int len) — no-ack */
#define FW_SIDE_A      0x0045a8edu  /* int lens_side(void) -> 2=left, 1=right (transmit lens) */
#define FW_TICK_A      0x00448139u  /* uint32_t get_tick_ms(void) — monotonic ms */
#define FW_DISPATCH_A  0x00441c69u  /* int dispatch(int sid, void* ptr, int len, int subcode)
                                     * — universal inbound aa21 frame service dispatcher */

/* ---- RAM globals (CONFIRMED via the existing 2.2.4.34 patches) ---- */
#define RAM_FB_CANVAS_PTR 0x20074464u /* -> jbd4010 panel scan-out canvas base (640x480 4bpp, 2px/byte) */

/* ---- inline Cortex-M55 cache-maintenance registers (SCB; architectural on Armv8-M
 * with L1 cache — same map as Cortex-M7). We do cache maintenance ENTIRELY inline so
 * the loader needs NO derived dcache-clean firmware function. The firmware itself uses
 * these ops (2.2.6.10 had a DCCMVAC-based flush), so they are known-good on this SoC. */
#define REG_ICIALLU    0xE000EF50u  /* I-cache invalidate all: write 0 */
#define REG_DCCMVAC    0xE000EF68u  /* D-cache clean by MVA to PoC: write line address */
#define CACHE_LINE     32u          /* Cortex-M55 L1 line size (bytes) */

/* ---- BLE RX hook site (byte-patch target; file_off = A - 0x39E680) ----
 * The single `bl FUN_00441c68` at 0x0045aaa4 — the universal inbound-frame service
 * dispatcher call every sid-routed app frame passes through, in any UI. Redirect it
 * (stock 4 bytes below) to rt_rx_hook, which handles RUNTIME_SID then tail-calls the
 * real dispatcher. This is the exact site + idiom the screenshot CFW's cap_rx_hook
 * used, so it is a proven-safe hook. After rt_rx_hook returns, the wrapper does
 * `movs r0,r4 ; bl free ; pop {r0,r1,r4,pc}` (r4 = payload) — so rt_rx_hook must be a
 * plain AAPCS call whose return value is discarded (AAPCS preserves r4). */
#define HOOK_RX_SITE_A     0x0045aaa4u
#define HOOK_RX_SITE_STOCK {0xe7,0xf7,0xe0,0xf8}   /* bl 0x441c68 */

/* ---- fault recovery (available to payloads via inline; not used by the loader) ---- */
#define REG_AIRCR      0xE000ED0Cu  /* write 0x05FA0004 = VECTKEY|SYSRESETREQ -> system reset */
#define AIRCR_SYSRESET 0x05FA0004u

/* ---- runtime protocol ---- */
#define RUNTIME_SID    0x7bu        /* dedicated inbound sid (free on 2.2.4.34: 0x7d=screenshot,
                                     * 0x7e=debug are separate CFWs; this loader is a fresh base). */
/* opcode = payload[0] */
#define RT_OP_LOAD_FRAG  0x01u      /* [op][mode_id][frag_idx u16][last u8][bytes...] (in order from idx 0) */
#define RT_OP_ACTIVATE   0x02u      /* [op][mode_id][total_len u32 LE][crc32 u32 LE] -> verify+cache+jump */
#define RT_OP_SEND       0x03u      /* [op][mode_id][data...] -> mode.on_data */
#define RT_OP_RESET      0x04u      /* [op] -> exit active mode, free buffers */
#define RT_OP_PING       0x05u      /* [op] -> reply on RUNTIME_SID (liveness) */
#define RT_MAGIC         0xA7u      /* reply frames start with this */

/* ---- runtime state anchor: build.py has no .data/.bss, so ALL mutable loader state
 * lives in a malloc'd rt_state_t whose pointer is stored at this ONE fixed RAM word.
 *
 * 0x20053304 was chosen by scanning the main-app for referenced SRAM addresses, then
 * CONFIRMED safe by tracing the firmware's actual allocator descriptors (adversarial
 * review, 2026-07-18):
 *   - FW_MALLOC's pool (via *0x200749c0) is created at 0x5ee948 with base 0x2020f330,
 *     size 0x70800 (arena 0x2020f330..0x2027fb30). The other region pools have bases
 *     0x20142330, 0x2027fb30, 0x2037b23c. EVERY firmware arena lives at >= 0x20142330 —
 *     ~950 KB ABOVE the anchor. So firmware malloc/free can never allocate over, nor
 *     free-list-manage, this word (rules out the only real heap-collision crash path).
 *   - The main stack top is MSP init 0x2007fb00 (~182 KB above the anchor); task stacks
 *     come from the 0x20142330 region. The anchor is below every stack too.
 *   - Across the whole image the 0x20053xxx page contains exactly ONE 32-bit word that
 *     matches an SRAM pattern (0x2005341c) and NO ldr loads it — coincidental data, not a
 *     live pointer. (So "no literal-pool POINTER references", not literally zero matches.)
 * The loader also validates RT_STATE_MAGIC + SRAM-range before trusting the word, so even
 * a hypothetical collision degrades to "cold boot" (state re-init) rather than a crash.
 * ANCHOR IS RUNTIME-ONLY: a wrong value can at worst cause a recoverable watchdog reset —
 * it is NOT brick-critical (only the container assembly is). */
#define RT_STATE_ANCHOR_A 0x20053304u
#define RT_STATE_MAGIC    0x52544d31u /* "RTM1" — tags a live rt_state_t */

/* Payload scratch word (mode_selftest stashes its ctx* here between vtable calls).
 * DISTINCT from RT_STATE_ANCHOR_A — a payload must never touch the loader's anchor.
 * Also in the verified clean gap, 256 B above the anchor. */
#define RT_MODE_CTX_SLOT_A 0x20053404u

#endif /* FW_2_2_4_34_H */
