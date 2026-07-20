export const meta = {
  name: 'design-ownmode',
  description: 'Design a hot-loaded payload that enters our OWN full-screen G2 mode (dashboard hidden) & controls the whole display',
  phases: [
    { title: 'Analyze', detail: 'four dimensions of the display/foreground/power path in parallel' },
    { title: 'Synthesize', detail: 'concrete payload implementation plan' },
  ],
}

const DIR = '/private/tmp/claude-501/-Users-mojashi-repos-odd/70e4d562-4b1b-41ba-9eac-bd869645bc38/scratchpad'
const COMMON =
  `Context: reverse-engineering Even Realities G2 firmware 2.2.4.34 (single Apollo510 mainapp, ARM Thumb-2, ` +
  `statically-linked stock LVGL v9.3). We run hot-loaded position-independent payloads via a flashed loader; a payload ` +
  `can call ANY firmware address (absolute fn-ptr, Thumb bit set) and read/write SRAM. GOAL: a payload that enters our ` +
  `OWN clean FULL-SCREEN mode — like the built-in EvenHub/terminal foreground apps DO — so the DASHBOARD is hidden and ` +
  `WE control the entire lens (draw arbitrary graphics/text, animate). We do NOT want to overlay/fight the dashboard. ` +
  `\n\nKey already-known facts: display_startup(appID,data,len)=0x443904 posts a STARTUP(cmd2) msg to the display queue; ` +
  `the display thread ui_display_thread_handler=0x442f00 processes it and calls dispatch_ui_event(appID,event,..)=0x4419ce ` +
  `which invokes the app's uiCb (registry at 0x20066210, 16B entries {appID,dataCb,uiCb,cfg}; count at *0x20074410). ` +
  `page_manager_init built two child containers of a 576x288 root: base=mgr+0x1c (opaque, visible), overlay=mgr+0x20 ` +
  `(transparent until activated); mgr ptr at *0x2007440c. FUN_00463f1a(appID,data,len,x,cmd,arg,0) is the central ` +
  `app-command poster (EvenHub uses cmd=5; REQ_DISPLAY_STARTUP uses cmd=1). LVGL addrs: lv_image_create=0x4b0ee8, ` +
  `lv_image_set_src=0x4b0f00 (lv_image_t has an EXTRA word at obj+0x30 vs upstream: src@0x2c, w@0x3c, h@0x40, cf-bitfield@0x58), ` +
  `lv_obj_set_pos=0x43f03a, lv_obj_set_size=0x43f460, lv_label_create=0x4b1c96, lv_label_set_text=0x4b1cae, ` +
  `lv_obj_invalidate=0x4405f6, lv_display_get_default=0x44e94e. Reading files: use the Read tool on absolute paths under ${DIR}. ` +
  `Your final output IS the structured data.`

const DIMS = [
  {
    key: 'foreground-open',
    files: ['g2_clean.c', 'open_path.c', 'open_power.c', 'pm_init.c', 'pm_activate.c'],
    ask:
      `DIMENSION: how to make OUR registered app the FOREGROUND (dashboard hidden). Read ${DIR}/g2_clean.c (display_startup, ` +
      `dispatch_ui_event, ui_display_thread_handler, register_all_foreground_ui_pages, terminal_uiCb, evenhub_uiCb), ` +
      `${DIR}/open_path.c (FUN_0045b178 app-command dispatcher, FUN_00441d92, FUN_0045f910 set-active-core), ` +
      `${DIR}/open_power.c (FUN_00463f1a, FUN_0050d9e8 dashboard fade-out, FUN_00464c28). ` +
      `Determine the EXACT minimal reliable call sequence + cfg (page_id, type byte cfg[0xb]=0 base vs 1 overlay, other cfg fields) ` +
      `for our own app to become the active foreground page so the compositor renders OURS and the dashboard is hidden/faded out. ` +
      `Which entry (display_startup vs FUN_00463f1a vs posting a display-queue msg directly) reliably reaches dispatch_ui_event(ourID,2) ` +
      `when the dashboard is the current base? What hides the dashboard (fade-out FUN_0050d9e8 — who calls it, on what transition)? ` +
      `Give concrete addresses + the cfg byte layout + the call order.`,
  },
  {
    key: 'render-page',
    files: ['g2_clean.c', 'lvsplit/lv_image.c', 'lvsplit/lv_display.c', 'bufsync.c'],
    ask:
      `DIMENSION: once foreground, how our uiCb builds a FULL-SCREEN page the compositor renders, showing ARBITRARY pixels. ` +
      `Read ${DIR}/g2_clean.c (terminal_uiCb, evenhub_uiCb — how they build their page + store the root in cfg[1]), ` +
      `${DIR}/lvsplit/lv_image.c (lv_image_create/set_src + the lv_image_t/lv_image_dsc_t layout, noting obj+0x30 extra word), ` +
      `${DIR}/lvsplit/lv_display.c, ${DIR}/bufsync.c (buffer_sync/flush path, the 576x288 window). ` +
      `Produce the minimal LVGL call sequence our uiCb should run on STARTUP(event 2): create a full-screen lv_image as child ` +
      `of the ctx (the screen arg passed to uiCb), point it at an lv_image_dsc_t we fill with our own pixels, set size/pos, ` +
      `store the root object into cfg[1] (as terminal/evenhub do). Give the EXACT lv_image_dsc_t / lv_image_header_t byte layout ` +
      `for THIS build (magic, cf value for a grayscale/L8 or the panel's native format, w,h,stride, data ptr, data_size), the ` +
      `color-format constant to use, and whether an lv_canvas alternative exists (it is NOT compiled in — confirm). If lv_image is ` +
      `impractical, give the lv_label path for text. Concrete addresses + struct offsets + call order.`,
  },
  {
    key: 'wake-power',
    files: ['disp_power.c', 'open_power.c', 'burst.c'],
    ask:
      `DIMENSION: how to WAKE the display from software so our mode is visible, and keep it on while our app is foreground. ` +
      `Read ${DIR}/disp_power.c and ${DIR}/open_power.c (the functions referencing ASYNC_DISPLAY_DEVICE_POWER_UP/DOWN_COMMAND: ` +
      `FUN_00471ee2, FUN_004720d0 = power up senders; FUN_00471f54, FUN_004722fc = power down; the head-up IMU handler FUN_004bd5b6; ` +
      `the screen on/off gesture handlers FUN_00465d36/FUN_0046594e; dashboard fade-out FUN_0050d9e8), and ${DIR}/burst.c (jbd_flush ` +
      `power cycle). Determine: which function, callable from a payload, sends the DISPLAY_POWER_UP command to turn the panel on ` +
      `(and its args); whether opening a foreground app auto-powers-up the display; what triggers the idle POWER_DOWN and how to ` +
      `prevent it (so the panel stays on while our mode runs). Give concrete addresses + call args + the power-up/down state.`,
  },
  {
    key: 'animate-update',
    files: ['g2_clean.c', 'lvsplit/lv_image.c', 'burst.c', 'bufsync.c'],
    ask:
      `DIMENSION: how to UPDATE our content and get the compositor to re-render it (for animation), from a safe context, WITHOUT ` +
      `the _lv_display_refr_timer re-entrancy fault we already hit (calling refr from within an event/flush dispatch reboots). ` +
      `Read ${DIR}/g2_clean.c (how apps get event 3=DATA and event 4=tick; how terminal/evenhub update + re-render on data), ` +
      `${DIR}/lvsplit/lv_image.c (invalidate on set_src), ${DIR}/burst.c, ${DIR}/bufsync.c. ` +
      `Determine the safe update path: e.g. our dataCb/uiCb(event=3) updates the lv_image's pixel buffer + calls lv_obj_invalidate ` +
      `(NOT refr) and lets the compositor's own loop redraw; the driving cadence (host RT_OP_SEND frames vs a firmware tick). ` +
      `Is the compositor loop running continuously while a foreground app is active (so invalidate suffices), or event-driven ` +
      `(so we must post something each frame)? Give the concrete mechanism + addresses.`,
  },
]

const DSCHEMA = {
  type: 'object',
  properties: {
    dimension: { type: 'string' },
    mechanism_summary: { type: 'string', description: 'the mechanism in 3-6 sentences' },
    steps: { type: 'array', items: { type: 'string' }, description: 'ordered concrete steps (with fw addresses) a payload would do' },
    addresses: { type: 'array', items: { type: 'object', properties: { name: { type: 'string' }, addr: { type: 'string' }, sig: { type: 'string' } }, required: ['name', 'addr'] } },
    structs: { type: 'array', items: { type: 'object', properties: { name: { type: 'string' }, fields: { type: 'string' } }, required: ['name', 'fields'] } },
    risks: { type: 'array', items: { type: 'string' } },
    confidence: { type: 'string', enum: ['high', 'med', 'low'] },
    open_questions: { type: 'array', items: { type: 'string' } },
  },
  required: ['dimension', 'mechanism_summary', 'steps', 'confidence'],
}

const results = await parallel(DIMS.map((d) => () =>
  agent(`${COMMON}\n\n${d.ask}`, { label: `analyze:${d.key}`, phase: 'Analyze', schema: DSCHEMA })
))
const found = results.filter(Boolean)

const plan = await agent(
  `${COMMON}\n\nYou are the SYNTHESIS lead. Below are four dimension analyses (foreground-open, render-page, wake-power, animate-update) ` +
  `of the G2 display path, each as JSON. Produce ONE concrete, implementable plan for a hot-loaded C payload (like our existing ones: ` +
  `an rt_api vtable with init/on_data/exit, calling firmware by absolute Thumb addr, no writable statics — state in a heap ctx anchored ` +
  `at *0x20053404) that: (1) registers our own app + reliably becomes the FOREGROUND (dashboard hidden), (2) wakes the display, ` +
  `(3) its uiCb draws a full-screen image/text we control, (4) can animate via host-sent frames. Give: the exact call sequence with ` +
  `addresses; the cfg + lv_image_dsc byte layouts; what to build vs what to reuse; the top RISKS + how the payload stays reboot-recoverable; ` +
  `and a concrete first-milestone (simplest thing to try on hardware that proves foreground+visible). Be specific and address-level. ` +
  `\n\nDIMENSION ANALYSES:\n${JSON.stringify(found, null, 1)}`,
  { label: 'synthesize:plan', phase: 'Synthesize' }
)

return { dimensions: found, plan }
