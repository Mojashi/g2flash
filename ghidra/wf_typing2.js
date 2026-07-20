export const meta = {
  name: 'type-fw-all',
  description: 'Assign C signatures to every named G2 firmware function, one agent per source-file bin',
  phases: [{ title: 'Type', detail: 'one agent per ~60KB bin of decompiled modules, in parallel' }],
}

// args = [{bin, path, modules:[...], bytes}]  (the bins.json produced by the binning step)
const BINS = args

const VOCAB =
  `Use ONLY these type strings so they map to the Ghidra type DB: ` +
  `void, bool, char, u8, u16, u32, i8, i16, i32, size_t, void*, u8*, u16*, u32*, char*, ` +
  `lv_obj_t*, lv_display_t*, lv_image_dsc_t*, lv_area_t*, lv_point_t*, lv_event_t*, lv_anim_t*, lv_style_t*, lv_timer_t*, ` +
  `app_cfg_t*, app_entry_t*, peer_pkt_hdr_t*. ` +
  `ALSO: for a function that handles a protobuf message, use the firmware-exact struct name from the /pb ` +
  `category as a pointer, e.g. HealthDataPackage*, TerminalDataPackage*, EvenAIDataPackage*, ` +
  `DashboardDataPackage*, NotificationDataPackage*, etc. — the decompilation already shows some of these ` +
  `applied (e.g. "HealthDataPackage *pHVar2"); reuse the exact struct name you see referenced. ` +
  `For a pointer to a struct you cannot identify, use void*. For an integer of unknown signedness use u32. ` +
  `For a param you truly cannot reason about use "u32" and name it argN.`

const COMMON =
  `Reverse-engineering-documentation task. Assign a correct C SIGNATURE (return type + typed, named params) to ` +
  `EACH function in one bin of decompiled Even Realities G2 firmware 2.2.4.34 (stock LVGL v9.3 + the Even app/` +
  `service framework). Functions are already NAMED from their embedded __func__ and grouped by their source ` +
  `file (marked "// ##### MODULE: xxx.c #####" and "// ===== name @ 0xADDR ====="). Infer types from: the ` +
  `function + module name, the body, struct-offset accesses (*(int*)(x+0x2c)), call-graph, log format strings, ` +
  `and — for LVGL functions — the exact stock LVGL v9.3 public API. Known struct types in the DB: lv_image_dsc_t ` +
  `{magic,cf,flags,w,h,stride,data_size,data}, app_cfg_t {page_id,root,align,type@0xb,width,height,visible_base@0x17}, ` +
  `app_entry_t {app_id,dataCb,uiCb,cfg}, lv_area_t {x1,y1,x2,y2}, and 244 /pb protobuf message structs. ` +
  VOCAB +
  ` Read the bin FILE with the Read tool. Return a signature for EVERY function that has a "// ===== name @ 0xADDR" ` +
  `header (use that hex ADDR verbatim). Your output IS the data; do not summarize.`

const SCHEMA = {
  type: 'object',
  properties: {
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
  required: ['functions'],
}

const results = await parallel(BINS.map((b) => () =>
  agent(`${COMMON}\n\nBIN FILE: ${b.path}\nMODULES IN THIS BIN: ${b.modules.join(', ')}`,
        { label: `type:bin_${b.bin}`, phase: 'Type', schema: SCHEMA })
))

const all = []
for (const r of results) {
  if (r && r.functions) all.push(...r.functions)
}
log(`typed ${all.length} function signatures across ${results.filter(Boolean).length}/${BINS.length} bins`)
return { functions: all }
