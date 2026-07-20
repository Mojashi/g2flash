# Even Realities G2 firmware 2.2.4.34 — architecture map (RE asset)

Single-component mainapp (`s200_firmware_ota.bin` code), Apollo510B Cortex-M55 Thumb-2, statically
linked **stock LVGL v9.3**. Ghidra project `scratchpad/ghidra_proj` (program `g2_mainapp.bin` loaded
@ 0x438000; file_off + 0x438000 = runtime addr). **~1100 functions named** (825 auto from `__func__`,
276 hand/workflow). Reusable payload headers: `patches/fw_2.2.4.34_syms.h` (1046 addrs) +
`patches/fw_2.2.4.34_structs.h` (structs+globals). Rebuild the named DB with `scratchpad/rebuild_db.sh`.

## Two-lens hardware
Two independent Apollo510 MCUs linked by **BLE master/slave**. **R = MASTER = transmit lens**
(`lens_side()`==1, connected to phone); **L = SLAVE** (`lens_side()`==2). Only R sends to the phone;
both receive (address a lens with `runtime.ts ARM=L|R`). Inter-lens: `send_data_to_peer` (0x464c28) /
`SendInputEventToPeers` (0x464ef0); received by `sched_recv_peer_sync_data` (0x45ba68) ->
`FUN_0045aab0` -> target app's dataCb (event = the peer event_type). Native L/R animation sync =
**gate barrier** `anim_gate_sync_tick` (0x572648, "even_ai.animation"): shared lv_anim, slave waits
at gates, master releases via peer, timeout fallback. Naive flood-push desyncs (BLE peer latency).

## Display pipeline
- **Foreground app framework**: registry (app_entry_t[] @0x20066210, count @0x20074410) -> `display_startup`
  (0x443904) posts to the display queue -> `ui_display_thread_handler` (0x442f00) -> `dispatch_ui_event`
  (0x4419ce) -> app uiCb(event, .., container). Events: 2=STARTUP 3=DATA 4=TICK(~16 ticks) 5=CLOSE.
  `display_startup` only tears down the dashboard + runs our STARTUP builder when `G_FG_STATE`(0x20074e00)==0.
  cfg needs `visible_base`(+0x17)=1 and the uiCb must set `cfg.root`(+4). page containers built by
  `page_manager_init` (0x45f4de): mgr+0x18 = 576x288 root, +0x1c = base (opaque), +0x20 = overlay.
- **Render**: the ONLY safe render point is the display thread's own `lv_timer_handler` (0x46fcd4) after
  each event dispatch; it runs `_lv_display_refr_timer` (0x452540/timer 0x452fa8). NEVER call refr from a
  callback (re-entrancy -> `buffer_sync`/`FUN_00488430` while(true) asserts -> watchdog reboot). To animate:
  mutate pixels + `lv_obj_invalidate` (0x4405f6), return, let the loop redraw.
- **Flush/burst**: `lvgl_flush_cb` (0x4716c4) -> `buffer_sync` (0x47163c) [L8 -> working buf -> NemaGFX
  `gpu_blit_l8` 0x5f9a84] -> `post_fullscreen_refresh_msg` (0x472036, async). `jbd_flush` (0x588c90) is a
  HEAVY panel-init path (safe only from the BLE-RX context, not the display thread; rapid calls reboot).
- **Panel power** (separate displaydrvmgr task/queue): `display_power_up_sequence` (0x4720d0, cmds 0,1,3) /
  `post_display_power_up_msg` (0x471ee2) / `display_power_down_sequence` (0x4722fc). Idle-off is driven by
  the IMU head-down (`imu_headup_screen_toggle_detector` 0x4bd5b6 -> `screen_onoff_event_poster` 0x4bd58c).
  Wake from a payload: call `display_power_up_sequence`, zero `G_IMU_HEADDOWN` (0x20074eaf) to hold it on.

## Key LVGL v9.3 (all confirmed)
image_create 0x4b0ee8 / image_set_src 0x4b0f00 (dsc: see structs.h; cf 0x06 = L8; no lv_canvas compiled);
label_create 0x4b1c96 / label_set_text 0x4b1cae; obj_create 0x43de22 / set_pos 0x43f03a / set_size 0x43f460 /
invalidate 0x4405f6 / add_flag 0x43de74; display_get_default 0x44e94e / get_screen_active 0x44eb96 /
get_layer_top 0x44ebf2 / set_flush_cb 0x44eb62. Logging: `log_printf`(0x43d514)(level, tag, file, __func__,
line, fmt, ...) — arg3 = the real function name (that is how the 825 were auto-named).

## Loader-payload dev workflow (proven this session)
1. Write `patches/mode_*.c` (rt_api vtable {init,tick,on_input,on_data,exit}; state in a heap ctx anchored
   at *0x20053404; no writable statics; call fw by absolute Thumb addr, `#include "fw_2.2.4.34_syms.h"`).
2. `python3 patches/build.py mode_x.c [-Dflag]` -> `obj/mode_x.text.bin` (PIC, verifies no ext relocs).
3. `bun demos/runtime.ts load obj/mode_x.text.bin` (ARM=L|R to pick a lens); `send 1 hex:..` -> on_data.
4. Self-verify the display with the QOI screenshot debugger: `bun demos/screenshot-rt.ts <out>` (4bpp canvas,
   reliable when idle) or `mode_screenshot_l8` (L8 drawbuf, reliable when compositor active). Only the R lens
   can stream a screenshot back; capture the L lens via the peer relay (send_data_to_peer -> R relays).
5. Recover a bad payload with `runtime.ts reset` or a power-cycle (loader survives reboot; SRAM-only state).

## Working milestones (payloads in patches/)
mode_ownanim.c = own full-screen foreground mode + program animation (lv_image, dashboard hidden) + peer
relay/sync experiments. mode_ownmode.c = label milestone. mode_text/mode_boxtest = raw-canvas + jbd_flush
(idle-only). mode_screenshot.c + demos/screenshot-rt.ts = the QOI debugger. See the memory notes
`project_g2_cfw_display`, `reference_g2_display_arch`, `reference_g2_interlens_transmit`.
