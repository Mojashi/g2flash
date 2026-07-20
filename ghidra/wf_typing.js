export const meta = {
  name: 'type-fw',
  description: 'Assign C parameter/return types to named G2 firmware functions for RE documentation',
  phases: [{ title: 'Type', detail: 'one agent per subsystem file, in parallel' }],
}

const DIR = '/private/tmp/claude-501/-Users-mojashi-repos-odd/70e4d562-4b1b-41ba-9eac-bd869645bc38/scratchpad/typing'

// constrained type vocabulary so the apply step maps deterministically to Ghidra data types.
const VOCAB =
  `Use ONLY these type strings (so they map to the Ghidra type DB): ` +
  `void, bool, char, u8, u16, u32, i8, i16, i32, size_t, ` +
  `void*, u8*, u16*, u32*, char*, ` +
  `lv_obj_t*, lv_display_t*, lv_image_dsc_t*, lv_area_t*, lv_point_t*, lv_event_t*, lv_anim_t*, lv_style_t*, lv_timer_t*, ` +
  `app_cfg_t*, app_entry_t*, peer_pkt_hdr_t*. ` +
  `For a pointer to a struct you cannot identify, use void*. For an integer of unknown signedness use u32. ` +
  `For a param you truly cannot reason about, use "u32" and name it argN.`

const COMMON =
  `Reverse-engineering-documentation task: assign a correct C SIGNATURE (return type + typed, named params) to ` +
  `each function in ONE decompiled subsystem file of Even Realities G2 firmware 2.2.4.34 (stock LVGL v9.3 + the ` +
  `Even display/app framework). Functions are already NAMED (from their embedded __func__). Infer types from: the ` +
  `function name, its body/call-graph, struct-offset accesses (e.g. *(int*)(x+0x2c)), and — for LVGL functions — your ` +
  `knowledge of the exact stock LVGL v9.3 public API. The Ghidra DB already has these struct types: lv_image_dsc_t ` +
  `{magic,cf,flags,w,h,stride,reserved,data_size,data}, app_cfg_t {page_id,root,align,type@0xb,width@0xc,height@0x10,` +
  `visible_base@0x17}, app_entry_t {app_id,dataCb,uiCb,cfg}, lv_area_t {x1,y1,x2,y2}, peer_pkt_hdr_t. ` +
  VOCAB + ` Read the file with the Read tool. Return the structured signatures; your output IS the data.`

const FILES = [
  { file: 'lvgl_obj_pos.c', hint: 'stock LVGL v9.3 lv_obj_pos.c: lv_obj_set_pos/x/y/size/width/height/align, get_coords/x/y/width/height, invalidate, etc. Apply the exact known v9.3 prototypes (lv_obj_t* obj, int32_t x, ...).' },
  { file: 'lvgl_label.c',   hint: 'stock LVGL v9.3 lv_label.c: lv_label_create(lv_obj_t* parent), lv_label_set_text(lv_obj_t*, const char*), set_long_mode, get_text, plus the static constructor/event/draw. Known prototypes.' },
  { file: 'lvgl_display.c', hint: 'stock LVGL v9.3 lv_display.c: lv_display_get_default(void), get_screen_active(lv_display_t*), get_layer_top, set_flush_cb, get/set resolution/offset, etc. Known prototypes.' },
  { file: 'disp_fw.c',      hint: 'Even display-app framework: display_startup(u16 appID, void* data, u32 len), dispatch_ui_event(u16 appID, u32 event, void* p3, void* p4), ui_display_thread_handler, page_manager_*, register_all_foreground_ui_pages. Infer from behaviour + the app_cfg_t/app_entry_t structs.' },
  { file: 'sync_peer.c',    hint: 'Even sync.module.api inter-lens peer messaging: send_data_to_peer(u16 appID, void* data, u16 len, void* ctx, u16 eventType), send_input_event_to_peers, post_app_command, the alloc/queue helpers. Infer from the packet-building code.' },
  { file: 'power_flush.c',  hint: 'display power (displaydrvmgr) + LVGL->panel flush glue: display_power_up_sequence(void), post_display_power_up_msg(void), display_power_down_*, lvgl_flush_cb(lv_display_t*, lv_area_t*, void* px_map), buffer_sync, post_fullscreen_refresh_msg. Infer.' },
  { file: 'jbd.c',          hint: 'JBD micro-LED panel driver: jbd_flush(char do_powercycle), jbd_present, jbd_compose, jbd_reg_write(u8 reg, void* data, u8 len), jbd_send_frame, panel init. Infer from register-write patterns.' },
]

const SCHEMA = {
  type: 'object',
  properties: {
    file: { type: 'string' },
    functions: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          addr: { type: 'string', description: 'hex runtime addr from the // ===== name @ 0xADDR header' },
          name: { type: 'string' },
          ret: { type: 'string', description: 'return type from the vocab' },
          params: {
            type: 'array',
            items: { type: 'object', properties: { type: { type: 'string' }, name: { type: 'string' } }, required: ['type', 'name'] },
          },
          confidence: { type: 'string', enum: ['high', 'med', 'low'] },
        },
        required: ['addr', 'ret', 'params'],
      },
    },
  },
  required: ['file', 'functions'],
}

const typed = await parallel(FILES.map((f) => () =>
  agent(`${COMMON}\n\nFILE: ${DIR}/${f.file}\nHINT: ${f.hint}`,
        { label: `type:${f.file}`, phase: 'Type', schema: SCHEMA })
))
return { typed: typed.filter(Boolean) }
