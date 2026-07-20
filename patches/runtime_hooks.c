/*
 * runtime_hooks.c — the assembly/glue that WIRES runtime.c into 2.2.6.10.
 *
 * This is the only translation unit that touches firmware call/return conventions.
 * runtime.c stays pure C (its rt_rx_hook / rt_on_input / rt_tick are ordinary AAPCS
 * functions). Here we provide:
 *
 *   (A) rt_state_init()  — lazy one-time allocation of rt_state_t + arming of the
 *                          ~30 Hz osTimer whose callback is rt_tick_cb (item 3).
 *   (B) rt_tick_cb()     — the osTimer callback thunk -> rt_tick() (item 3).
 *   (C) rt_input_tramp   — the naked entry-detour trampoline for the input dispatcher
 *                          at 0x0046728c: run rt_on_input(record), then replay the
 *                          stolen prologue and fall into the dispatcher body (item 2).
 *
 * The RX-site hook (item 1) needs NO glue here: the redirected `bl` at 0x0047ec26 calls
 * runtime.c's rt_rx_hook(sid,payload,len,subcode) directly. AAPCS preserves r4 (=payload)
 * across the call, so the stock wrapper tail (`movs r0,r4; bl free; pop {r0,r1,r4,pc}`)
 * still frees the right buffer, and rt_rx_hook's int return is discarded by the wrapper's
 * `movs r0,r4`. That is exactly screenshot.c's cap_rx_hook idiom — a plain C call.
 *
 * SAFETY: every firmware pointer is from patches/fw_2.2.6.10.h. The trampoline steals
 * EXACTLY the two 16-bit prologue instrs (4 bytes) and replays them byte-for-byte;
 * it enters via B.W (not BL) so lr still holds the real caller's return; it preserves
 * r0-r3 across the rt_on_input call so the dispatcher body (and the caller's r3, which
 * the stolen push/pop round-trips) sees identical register state.
 */
#include <stdint.h>
#include "fw_2.2.6.10.h"
#include "runtime_state.h"

/* ---- firmware primitives used only by the glue ---- */
typedef void* (*fw_malloc_t)(uint32_t);
typedef void* (*fw_timer_new_t)(void* func, int type, void* arg, void* attr);
typedef int   (*fw_timer_start_t)(void* handle, uint32_t ms);
#define GLUE_MALLOC      ((fw_malloc_t)FW_MALLOC_A)
#define GLUE_TIMER_NEW   ((fw_timer_new_t)FW_TIMER_NEW_A)
#define GLUE_TIMER_START ((fw_timer_start_t)FW_TIMER_START_A)

/* runtime.c exports these (ordinary C, no glue): */
void rt_tick(void);
void rt_on_input(void* event_record);

/*
 * (3) TICK SOURCE + lazy init.
 *
 * Injected CFW blobs have no natural init entry, so the first rt_rx_hook() call arms
 * everything. osTimerNew(func, type, arg, attr) wants an absolute Thumb fn-ptr for the
 * callback — and `&rt_tick_cb` supplies exactly that: under -fropi clang materializes an
 * in-blob function address as a PC-relative movw/movt PREL pair (`add rX, pc`), which
 * build.py resolves, so at runtime it evaluates to the callback's real absolute address.
 * No -D baking / 2nd build pass is needed for the runtime blob (unlike zlib_glue.c, whose
 * callbacks are stored by firmware-side initializers rather than our own C).
 */

/* osTimer callback thunk. CMSIS osTimerFunc_t is void(*)(void*). */
void rt_tick_cb(void* arg){ (void)arg; rt_tick(); }

rt_state_t* rt_state_init(void){
    rt_state_t* S = RT_ANCHOR;
    if (rt_in_sram((uint32_t)S) && S->magic == RT_STATE_MAGIC)
        return S;                                  /* already up */

    S = (rt_state_t*)GLUE_MALLOC(sizeof(rt_state_t));
    if (!rt_in_sram((uint32_t)S)) return 0;        /* OOM -> caller falls through to stock */
    for (uint32_t i = 0; i < sizeof(rt_state_t); i++) ((uint8_t*)S)[i] = 0;
    S->magic = RT_STATE_MAGIC;
    RT_ANCHOR = S;                                 /* publish before arming the timer */

    /* Arm the ~30 Hz periodic tick exactly once (PC-relative &rt_tick_cb, see above). */
    void* h = GLUE_TIMER_NEW((void*)rt_tick_cb, RT_TIMER_PERIODIC, 0, 0);
    S->timer = h;
    if (h) GLUE_TIMER_START(h, RT_TICK_HZ_MS);
    return S;
}

/*
 * (2) INPUT TRAMPOLINE — entry detour at 0x0046728c.
 *
 * The dispatcher is invoked through a function pointer (no `bl` call site exists to
 * redirect), and rt_on_input needs r0 = the event record, which is live only at the
 * entry. So we steal the entry's first 4 bytes with a B.W to this naked shim. We do
 * NOT relocate a mid-function jump target beyond the two stolen instrs, and we replay
 * those two instrs verbatim, so this is a minimal, reversible, register-faithful detour.
 *
 * Entry state (reached by B.W, so unchanged from the fn-ptr call):
 *     r0 = event record ptr;  lr = real caller's return;  r3-r7 = caller values.
 * Stolen bytes @0x0046728c: `push {r3,r4,r5,r6,r7,lr}` (f8b5) + `sub sp,#0x28` (8ab0).
 * Continue at 0x00467290 (INPUT_DISPATCH_CONT_A = 0x00467291 with Thumb bit).
 *
 * `bl rt_on_input` is an intra-blob R_ARM_THM_CALL — build.py's mini-linker resolves it
 * by name. The movw/movt load an integer immediate (no symbol/reloc). 0x467291 =>
 * lower16 0x7291, upper16 0x0046 (== INPUT_DISPATCH_CONT_A).
 */
__attribute__((naked, used))
void rt_input_tramp(void){
    __asm volatile(
        "push  {r0, r1, r2, r3, r4, lr}   \n"  /* save arg regs (+r4 filler for 8B align) + caller lr */
        "bl    rt_on_input                \n"  /* r0 already = record; preserves r4-r11 */
        "pop   {r0, r1, r2, r3, r4, lr}   \n"  /* restore: r0=record, r3=orig, lr=caller return */
        "push  {r3, r4, r5, r6, r7, lr}   \n"  /* == stolen `push {r3,r4,r5,r6,r7,lr}` */
        "sub   sp, #0x28                  \n"  /* == stolen `sub sp,#0x28`               */
        "movw  r1, #0x7291                \n"  /* lower16(INPUT_DISPATCH_CONT_A) */
        "movt  r1, #0x0046                \n"  /* upper16(INPUT_DISPATCH_CONT_A) */
        "bx    r1                         \n"  /* fall into dispatcher body @0x00467290 */
    );
}
