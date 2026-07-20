/*
 * runtime_state.h — the mode-runtime's mutable state, moved OFF C file-scope statics
 * and INTO a single malloc'd struct anchored at one fixed RAM word.
 *
 * WHY: patches/build.py is a PIC mini-linker that lays out ONLY .text + .rodata and
 * hard-errors on any relocation into writable data (.data/.bss). runtime.c's original
 * `static uint8_t* g_buf; ... static rt_api_t g_api;` block therefore cannot be
 * compiled by this toolchain (each access is an absolute MOVW/MOVT into .bss with no
 * linker to bake the address). Screenshot.c/dbg_terminal.c sidestepped this by keeping
 * ALL state on the stack; the runtime cannot (its state must persist across BLE frames,
 * input events and timer ticks). So instead we keep exactly ONE absolute address — a
 * fixed RAM word, expressed as an integer constant (an immediate, NOT a symbol, so
 * build.py needs no relocation for it) — and hang everything off a pointer stored there.
 *
 * All of runtime.c's `g_*` file statics become `S->*` where `rt_state_t* S` is obtained
 * from rt_state()/rt_state_init(). See the runtime.c delta in the deliverable.
 */
#ifndef RUNTIME_STATE_H
#define RUNTIME_STATE_H
#include <stdint.h>
#include "fw_2.2.4.34.h"

typedef struct mode_vtable mode_vtable_t;   /* fwd (defined in runtime.c) */
typedef struct rt_api rt_api_t;             /* fwd (defined in runtime.c) */

/* Everything that used to be a file-scope static in runtime.c. Append-only. */
typedef struct rt_state {
    uint32_t       magic;        /* == RT_STATE_MAGIC once initialized */
    uint8_t*       buf;          /* malloc'd payload code buffer (executable) */
    uint32_t       buf_len;
    uint8_t*       prev_buf;     /* previous generation's buf, freed one reload later
                                    (deferred-free: never free a buf a concurrent
                                    tick/input might still be executing) */
    mode_vtable_t* mode;         /* active mode's vtable (0 while transitioning) */
    uint32_t       last_tick;
    void*          timer;        /* reserved: osTimer handle (v1 arms none; kept for a v2
                                    that adds an on-device tick without an ABI change) */
    uint32_t       busy;         /* transition-in-progress flag (belt-and-suspenders) */
    uint8_t        api[128];     /* storage for rt_api_t (opaque here; cast in runtime.c) */
} rt_state_t;

/* The one fixed absolute RAM word holding the rt_state_t*. Integer-constant address =>
 * compiles to a MOVW/MOVT immediate, no symbol, no relocation (build.py is happy). */
#define RT_ANCHOR (*(rt_state_t* volatile*)RT_STATE_ANCHOR_A)

static inline int rt_in_sram(uint32_t p){ return (uint32_t)(p - 0x20000000u) < 0x00800000u; }

/* Read-only fetch: returns the live state, or 0 if not yet initialized. Safe to call
 * from ANY context (timer thread, input dispatcher) — it never allocates. */
static inline rt_state_t* rt_state(void){
    rt_state_t* S = RT_ANCHOR;
    if (!rt_in_sram((uint32_t)S) || S->magic != RT_STATE_MAGIC) return 0;
    return S;
}

/* Allocate-and-publish: called ONLY from rt_rx_hook (a full task context where malloc is
 * safe). First call mallocs the state, zeroes it, sets the magic, and publishes the
 * pointer at the anchor. Idempotent thereafter. (v1 installs no timer, so there is
 * nothing to arm.) Defined in runtime_hooks_22434.c. Returns 0 if allocation failed
 * (rt_rx_hook then falls straight through to the stock dispatcher, so the glasses behave
 * exactly as stock). */
rt_state_t* rt_state_init(void);

#endif /* RUNTIME_STATE_H */
