export const meta = {
  name: 'name-fw-funcs',
  description: 'Assign descriptive names to decompiled G2 firmware functions for RE documentation',
  phases: [{ title: 'Name', detail: 'one agent per decompiled subsystem file' }],
}

const DIR = '/private/tmp/claude-501/-Users-mojashi-repos-odd/70e4d562-4b1b-41ba-9eac-bd869645bc38/scratchpad'
const COMMON =
  `Reverse-engineering-for-documentation task on Even Realities G2 firmware 2.2.4.34 (ARM Thumb-2 Apollo510). ` +
  `You are given a file of Ghidra-decompiled C for ONE firmware subsystem. Assign a concise, descriptive snake_case name and ` +
  `a best-effort C signature to EACH FUN_xxxxxx function, inferred from: its behaviour/call-graph, struct offsets, and — most ` +
  `usefully — the embedded diagnostic LOG-FORMAT STRINGS. Logging goes through helpers FUN_0043d514(level, file, LINE, func, fmt, ...) ` +
  `and FUN_0043d072/FUN_0043ce46; the module tag + message often literally name the operation (e.g. "[sync.module.api]SEND_DATA_TO_PEER", ` +
  `"jdb4010 power up done", "REQUEST_DISPLAY_START_UP"). Read the file with the Read tool at the given absolute path. ` +
  `Return the structured mapping; your final output IS the data (no prose).`

const FILES = [
  { file: 'syncmodule.c',  hint: 'sync.module.api / inter-lens BLE peer messaging. KNOWN: 0x464c28=send_data_to_peer(appID,data,len,arg4,eventType), 0x464ef0=send_input_event_to_peers, 0x463f1a=post_app_command(appID,data,len,x,cmd,arg,0), 0x464c28 packs a peer packet + posts to a queue. Name the alloc helper (0x463e98), the queue posters, and every other func.' },
  { file: 'open_power.c',  hint: 'app-open + display device power. KNOWN: 0x463f1a=post_app_command, 0x4720d0=display_power_up_fsm (posts cmds 0,1,3), 0x471ee2=display_power_up_cmd0, 0x4722fc=display_power_down_fsm (cmds 2,5), 0x471f54=display_power_down_cmd5, 0x50d9e8=dashboard_fadeout, 0x464c28=send_data_to_peer.' },
  { file: 'disp_power.c',  hint: 'display power / gesture / IMU head-up. KNOWN: 0x4bd5b6=imu_headup_detector (fires screen on/off), 0x4bd58c=screen_onoff_event_poster(6=on,7=off), 0x4642d6=request_display_startup, 0x46594e/0x465d36/0x466ab0=screen on/off gesture config. Name the power up/down senders 0x471ee2/0x4720d0/0x471f54/0x4722fc too.' },
  { file: 'burst.c',       hint: 'JBD micro-LED panel driver. KNOWN: 0x588c90=jbd_flush(powercycle if arg!=0), 0x588c5c=jbd_present, 0x5893c6=jbd_compose, 0x589290=jbd_plot, 0x588da6=jbd_panel_init_seq, 0x5894ea=jbd_send_frame. Name every func + the FUN_00588cca (jbd register write) helper.' },
  { file: 'bufsync.c',     hint: 'LVGL->panel flush. KNOWN: 0x4716c4=lvgl_flush_cb, 0x47163c=buffer_sync (L8->working buffer + GPU blit), 0x472036=post_fullscreen_refresh_msg, 0x5f9a84=gpu_blit_l8, 0x4c8f4e/0x4c947a=gpu_submit. Name the rest.' },
  { file: 'open_path.c',   hint: 'app-open dispatch. KNOWN: 0x45b178=app_command_dispatch(cmd 1=startup,3=refresh,5=close,0x10=close_all), 0x441d92=switch_active_page_core, 0x45f910=page_set_active_core, 0x4643de=evenhub_open. Name every func.' },
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
          addr: { type: 'string', description: 'hex e.g. 0x464c28' },
          name: { type: 'string', description: 'snake_case descriptive name' },
          signature: { type: 'string' },
          confidence: { type: 'string', enum: ['high', 'med', 'low'] },
          evidence: { type: 'string', description: 'the log string or behaviour that justifies the name' },
        },
        required: ['addr', 'name', 'confidence'],
      },
    },
  },
  required: ['file', 'functions'],
}

const named = await parallel(FILES.map((f) => () =>
  agent(`${COMMON}\n\nFILE: ${DIR}/${f.file}\nSUBSYSTEM HINT: ${f.hint}`,
        { label: `name:${f.file}`, phase: 'Name', schema: SCHEMA })
))
return { named: named.filter(Boolean) }
