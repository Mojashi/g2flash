/*
 * runtime_hooks_22434.c — glue that wires runtime.c into firmware 2.2.4.34.
 *
 * v1 is deliberately MINIMAL: the loader's only firmware entanglement is the RX-site
 * bl-redirect at 0x0045aaa4 (handled entirely by runtime.c's rt_rx_hook — a plain AAPCS
 * call, no glue needed). So this file provides ONLY the state allocator.
 *
 * NOT here (deferred to a later loader revision, to keep the first-flash surface tiny):
 *   - a periodic osTimer tick source (runtime.c's rt_tick() is compiled but never armed;
 *     payloads animate via host-driven RT_OP_SEND frames), and
 *   - an input-dispatcher trampoline (runtime.c's rt_on_input() is compiled but no MRAM
 *     site is patched to call it).
 * Both are pure additions later — no ABI change — via runtime_state_t.timer and the
 * dispatcher entry-detour, once their firmware addresses are derived + verified.
 */
#include <stdint.h>
#include "fw_2.2.4.34.h"
#include "runtime_state.h"

/* firmware primitive used only by the glue */
typedef void* (*fw_malloc_t)(uint32_t);
#define GLUE_MALLOC ((fw_malloc_t)FW_MALLOC_A)

/*
 * Injected CFW blobs have no natural init entry, so the first rt_rx_hook() call brings
 * the state up. rt_rx_hook runs on the sync-framework worker task (a full task context,
 * where malloc is safe), so allocating here is fine. Idempotent: once RT_STATE_MAGIC is
 * published at the anchor, later calls just return the live state.
 */
rt_state_t* rt_state_init(void){
    rt_state_t* S = RT_ANCHOR;
    if (rt_in_sram((uint32_t)S) && S->magic == RT_STATE_MAGIC)
        return S;                                  /* already up */

    S = (rt_state_t*)GLUE_MALLOC(sizeof(rt_state_t));
    if (!rt_in_sram((uint32_t)S)) return 0;        /* OOM / bad ptr -> caller falls through to stock */
    for (uint32_t i = 0; i < sizeof(rt_state_t); i++) ((uint8_t*)S)[i] = 0;
    S->magic = RT_STATE_MAGIC;
    RT_ANCHOR = S;                                 /* publish */
    return S;
}
