/* dbg_terminal.c -- "printf-debug" CFW instrumentation for the terminal-mode UI
 * finite-state machine. Surfaces the firmware's INTERNAL terminal FSM state over
 * BLE so we can watch, on real hardware, exactly what the terminal UI state
 * machine is doing (and why injected agent text never binds to the content view).
 *
 * WHAT IT EMITS -- two compact 14-byte binary records, sent as aa21 no-ack frames
 * on a distinctive sid (0x7e) that our external BLE client reads via onRawFrame:
 *
 *   (1) DBG_REC_FSM  (type 1) -- every terminal_ui_fsm_handler dispatch:
 *          old_state, event_id, new_state, arg   (the ACTUAL transition, UI task)
 *   (2) DBG_REC_FIRE (type 2) -- every UI event enqueued via fire_ui_event:
 *          live fsm_state, event_id, arg         (what was posted + the state the
 *          RX-task handler OBSERVED when it decided to post it)
 *
 * Together these answer the debug objectives directly:
 *   - deliverable "every fsm transition (old,event,new)"  -> DBG_REC_FSM
 *   - "agent_content's observed fsm_state + did it fire the content-bind" ->
 *        DBG_REC_FIRE: agent_content posts 0x12 (append) always and 0x13 (content
 *        trigger / bind) ONLY when it observed fsm_state==7 at RX time. So a FIRE
 *        record with ev=0x13 == content-bind fired; a FIRE ev=0x12 with NO
 *        following ev=0x13 == bind dropped, and state_a is the state it observed.
 *   - "session_status gate outcomes" -> DBG_REC_FIRE shows session_status posting
 *        0x0f/0x10/0x11; DBG_REC_FSM then shows whether the UI handler actually
 *        advanced (e.g. IDLE(2) --ev15--> 7) or stayed put (stale/mismatched id).
 *
 * Both records carry a get_tick() millisecond timestamp so the phone can
 * reconstruct the RX-task (FIRE) / UI-task (FSM) interleaving -- i.e. the timing
 * race that drops the content bind.
 *
 * MECHANISM -- reuse the firmware's own aa21 send primitive FUN_0047398c(type=1,
 * sid, ptr, len), the SAME primitive settings_ext.c hooks. It self-gates on
 * link-readiness (returns 8 and sends nothing when this lens is not the
 * transmitting side / BLE is down), so calling it from any task/context is a safe
 * no-op when it cannot send. The record is built on the STACK because the appended
 * blob lands in MRAM (XIP code region) which is not writable with a normal store.
 *
 * HOOKS (see patch_compress.py DBG_* sites) -- all are call-site `bl` redirects,
 * the same length-preserving idiom as gesture_fwd.c / settings_ext.c (no prologue
 * relocation, callee-saved regs preserved by the C ABI):
 *   - bl terminal_ui_fsm_handler @0x5e5536 (UI-task dispatch)   -> dbg_fsm
 *   - bl terminal_ui_fsm_handler @0x5e5500 (DISPLAY_ENTER 1,0)  -> dbg_fsm
 *   - bl <rtos queue_send>       @0x5e53d0 (inside fire_ui_event)-> dbg_enqueue
 *
 * All names are prefixed dbg_/DBG_ so this TU shares no macro/typedef/function
 * name with the other patch sources #included by patches_main.c.
 */
#include <stdint.h>

typedef void     (*dbg_fsm_fn)(uint32_t event_id, uint32_t arg);
typedef int      (*dbg_enqueue_fn)(int qid, void *msg, int len, int timeout);
typedef int      (*dbg_send_fn)(int type, int sid, void *ptr, int len);
typedef uint32_t (*dbg_tick_fn)(void);

#define DBG_FW_FSM     ((dbg_fsm_fn)0x005e8b01u)      /* FUN_005e8b00 terminal_ui_fsm_handler */
#define DBG_FW_ENQUEUE ((dbg_enqueue_fn)0x0046435bu)  /* FUN_0046435a rtos queue_send         */
#define DBG_FW_SEND    ((dbg_send_fn)0x0047398du)     /* FUN_0047398c aa21 send (no-ack)      */
#define DBG_FW_TICK    ((dbg_tick_fn)0x00448139u)     /* FUN_00448138 monotonic ms tick       */

/* FSM ctx singleton pointer is a flash const @0x5e8d98 (holds 0x2006e0b0); the
 * current-state byte is ctx+0x275. Read indirectly to mirror the firmware exactly
 * (rather than hardcoding 0x2006e325) so it stays correct if the singleton moves. */
#define DBG_FSM_CTX  (*(void *const volatile *)0x005e8d98u)
#define DBG_STATE()  (*((volatile uint8_t *)DBG_FSM_CTX + 0x275))

#define DBG_SID       0x7e   /* distinctive sid our external client filters on */
#define DBG_MAGIC     0xE7   /* leading marker for robustness on the raw frame  */
#define DBG_REC_FSM   0x01   /* transition: state_a=old_state, state_b=new_state */
#define DBG_REC_FIRE  0x02   /* event post: state_a=live_state, state_b=0xff     */
#define DBG_UI_QID    0x30   /* terminal UI event queue id (fire_ui_event target) */

/* 14-byte fixed record (little-endian):
 *   [0]      magic 0xE7
 *   [1]      record type (1=fsm, 2=fire)
 *   [2]      state_a
 *   [3]      event_id
 *   [4]      state_b
 *   [5]      reserved (0)
 *   [6..9]   arg  (u32)
 *   [10..13] tick (u32, ms)
 */
static void dbg_emit(uint8_t type, uint8_t sa, uint8_t ev, uint8_t sb, uint32_t arg)
{
    uint8_t rec[14];
    uint32_t t = DBG_FW_TICK();
    rec[0]  = DBG_MAGIC;
    rec[1]  = type;
    rec[2]  = sa;
    rec[3]  = ev;
    rec[4]  = sb;
    rec[5]  = 0;
    rec[6]  = (uint8_t)arg;         rec[7]  = (uint8_t)(arg >> 8);
    rec[8]  = (uint8_t)(arg >> 16); rec[9]  = (uint8_t)(arg >> 24);
    rec[10] = (uint8_t)t;           rec[11] = (uint8_t)(t >> 8);
    rec[12] = (uint8_t)(t >> 16);   rec[13] = (uint8_t)(t >> 24);
    DBG_FW_SEND(1, DBG_SID, rec, (int)sizeof rec);
}

/* Replaces `bl terminal_ui_fsm_handler` at the UI-task dispatch + DISPLAY_ENTER
 * sites. Runs on the UI task. Reads the state before and after the real handler,
 * so it captures the ACTUAL (old_state -> new_state) transition for this event. */
void dbg_fsm(uint32_t event_id, uint32_t arg)
{
    uint8_t old_state = DBG_STATE();
    DBG_FW_FSM(event_id, arg);
    uint8_t new_state = DBG_STATE();
    dbg_emit(DBG_REC_FSM, old_state, (uint8_t)event_id, new_state, arg);
}

/* Replaces the `bl queue_send` INSIDE fire_ui_event (FUN_005e535e). Runs on the
 * task that posts the event (the RX task for agent_content / session_status).
 * The message is {event_id:u8 @0, arg:u32 @4}. Guard on qid==0x30 so no other
 * queue user is disturbed, then tail-return the real enqueue's result (which
 * fire_ui_event returns to its own caller). */
int dbg_enqueue(int qid, void *msg, int len, int timeout)
{
    if (qid == DBG_UI_QID && len >= 8) {
        const uint8_t *m = (const uint8_t *)msg;
        uint32_t arg = (uint32_t)m[4] | ((uint32_t)m[5] << 8)
                     | ((uint32_t)m[6] << 16) | ((uint32_t)m[7] << 24);
        dbg_emit(DBG_REC_FIRE, DBG_STATE(), m[0], 0xff, arg);
    }
    return DBG_FW_ENQUEUE(qid, msg, len, timeout);
}
