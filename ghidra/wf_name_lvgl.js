export const meta = {
  name: 'name-lvgl',
  description: 'Map decompiled stock-LVGL-v9.3 functions to their real API names + struct offsets',
  phases: [
    { title: 'Name', detail: 'one agent per LVGL source file' },
    { title: 'Verify', detail: 'cross-check the high-value display targets' },
  ],
}

const DIR = '/private/tmp/claude-501/-Users-mojashi-repos-odd/70e4d562-4b1b-41ba-9eac-bd869645bc38/scratchpad/lvsplit'

// Each file, with the specific v9.3 API we most want pinned to an address.
const FILES = [
  { file: 'lv_image', targets: 'lv_image_create, lv_image_set_src, lv_image_set_inner_align, lv_image_set_rotation, lv_image_constructor/destructor/event; and the lv_image_dsc_t / lv_image_header_t byte layout (magic,cf,flags,w,h,stride) as used here.' },
  { file: 'lv_label', targets: 'lv_label_create, lv_label_set_text, lv_label_set_text_static, lv_label_set_long_mode, lv_label_get_text, lv_label_constructor/destructor/event; lv_label_t field offsets (text ptr, flags/long_mode byte).' },
  { file: 'lv_obj', targets: 'lv_obj_create, lv_obj_class (struct), lv_obj_add_flag, lv_obj_remove_flag, lv_obj_add_style, lv_obj_invalidate, lv_obj_constructor; lv_obj_t base field offsets (parent, coords, style list, flags).' },
  { file: 'lv_obj_pos', targets: 'lv_obj_set_pos, lv_obj_set_x, lv_obj_set_y, lv_obj_set_size, lv_obj_set_width, lv_obj_set_height, lv_obj_align, lv_obj_set_align, lv_obj_center, lv_obj_get_width/height, lv_obj_refr_size/pos, lv_obj_update_layout.' },
  { file: 'lv_obj_tree', targets: 'lv_obj_set_parent, lv_obj_get_screen, lv_obj_get_parent, lv_obj_get_child, lv_obj_delete/lv_obj_del, lv_obj_clean, lv_obj_get_index, lv_obj_get_child_count.' },
  { file: 'lv_obj_class', targets: 'lv_obj_class_create_obj (allocate obj of a class + link to parent) and lv_obj_class_init_obj (run constructors). The single function here is almost certainly one of these — decide which by behaviour.' },
  { file: 'lv_display', targets: 'lv_display_get_default, lv_display_get_screen_active (aka lv_screen_active / lv_display_get_screen_act), lv_display_set_flush_cb, lv_display_get_horizontal_resolution, lv_display_get_vertical_resolution, lv_display_get_layer_top/sys, lv_screen_load. The flush_cb field is stored at display+0x28.' },
  { file: 'lv_ambiq_display', targets: 'The Ambiq/Apollo porting: the flush_cb that hands the rendered buffer to the JBD/MSPI panel path, buffer setup, and any resolution/rotation glue. Identify which func is registered as the lv_display flush_cb.' },
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
          addr: { type: 'string', description: 'hex runtime addr e.g. 0x4b1cae' },
          lvgl_name: { type: 'string', description: 'exact LVGL v9.3 symbol, or best-guess with (?) if unsure' },
          signature: { type: 'string', description: 'C prototype with real param names/types' },
          kind: { type: 'string', enum: ['public', 'static', 'unknown'] },
          confidence: { type: 'string', enum: ['high', 'med', 'low'] },
          evidence: { type: 'string', description: 'assert line#, call pattern, or struct-offset reasoning' },
        },
        required: ['addr', 'lvgl_name', 'confidence'],
      },
    },
    structs: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          name: { type: 'string' },
          fields: {
            type: 'array',
            items: {
              type: 'object',
              properties: {
                off: { type: 'string' }, name: { type: 'string' }, type: { type: 'string' }, note: { type: 'string' },
              },
              required: ['off', 'name'],
            },
          },
        },
        required: ['name', 'fields'],
      },
    },
    notes: { type: 'string' },
  },
  required: ['file', 'functions'],
}

const named = await pipeline(
  FILES,
  (f) => agent(
    `You are reverse-engineering an ARM Thumb-2 firmware that statically links **stock LVGL v9.3** (confirmed: __FILE__ assert strings show D:\\...\\lvgl_v9.3\\LVGL\\src\\...). ` +
    `Read the decompiled functions from ONE source file at ${DIR}/${f.file}.c — these are ALL/most functions compiled from LVGL's ${f.file}.c, in address order (IAR keeps a file's functions contiguous). ` +
    `Your job: map each FUN_xxxxxx to its real LVGL v9.3 symbol name and a correct C signature, using your knowledge of the LVGL v9.3 public+static source for this exact file. ` +
    `KEY DECODING AID: the assert/log helper is FUN_0044c190(level, FILE_str, LINE, FUNC_str, ...). Its 3rd argument (a hex constant) is the SOURCE LINE NUMBER of that LV_ASSERT/LV_LOG — use it to pin the containing function to an exact line in ${f.file}.c and thus its name. ` +
    `Also use call-graph shape, struct offsets, and arg counts. ` +
    `PRIORITY TARGETS to pin with addresses (high confidence if at all possible): ${f.targets} ` +
    `Report struct field offsets you can infer. Be honest with confidence: 'high' only when the assert line or an unmistakable pattern nails it. Return the structured result; your final output IS the data, not prose.`,
    { label: `name:${f.file}`, phase: 'Name', schema: SCHEMA }
  )
)

const flat = named.filter(Boolean)

// Verify the handful of functions we will actually CALL from a hot-loaded payload.
const CRITICAL = [
  'lv_image_create', 'lv_image_set_src', 'lv_label_create', 'lv_label_set_text',
  'lv_obj_class_create_obj', 'lv_obj_set_pos', 'lv_obj_set_size', 'lv_obj_set_parent',
  'lv_display_get_default', 'lv_display_get_screen_active', 'lv_obj_invalidate',
]
const found = {}
for (const r of flat) for (const fn of (r.functions || [])) {
  const key = (fn.lvgl_name || '').replace(/\s*\(\?\)\s*/g, '').trim()
  if (CRITICAL.includes(key) && (!found[key] || fn.confidence === 'high')) found[key] = { ...fn, file: r.file }
}

const VSCHEMA = {
  type: 'object',
  properties: {
    target: { type: 'string' },
    addr: { type: 'string' },
    verdict: { type: 'string', enum: ['confirmed', 'wrong', 'uncertain'] },
    corrected_addr: { type: 'string' },
    signature: { type: 'string' },
    reasoning: { type: 'string' },
  },
  required: ['target', 'verdict'],
}

const verified = await parallel(CRITICAL.map((t) => () => {
  const cand = found[t]
  const addr = cand ? cand.addr : '(none proposed)'
  return agent(
    `Adversarially verify one address claim about stock LVGL v9.3. Claim: **${t}** is at ${addr}` +
    (cand ? ` with signature "${cand.signature || '?'}" (from ${cand.file}.c, evidence: ${cand.evidence || 'n/a'}).` : ' (no candidate was proposed — try to locate it).') +
    ` Read ${DIR}/${(cand && cand.file) || 'lv_obj'}.c and any sibling file in that dir you need. ` +
    `Decide: does the decompiled body at that address actually match what LVGL v9.3's ${t} does? Check arg count, the exact operations, and struct offsets. ` +
    `If wrong, give the corrected_addr from the same file if you can find it. Default to 'uncertain' if you cannot be sure. Return structured verdict.`,
    { label: `verify:${t}`, phase: 'Verify', schema: VSCHEMA }
  )
}))

return { named: flat, verified: verified.filter(Boolean) }
