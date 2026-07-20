export const meta = {
  name: 'peer-comms-map',
  description: 'RE the G2 inter-lens (peer) comms: command space, transport, dispatch, usable primitives',
  phases: [{ title: 'Analyze', detail: 'one agent per aspect of the peer cluster, in parallel' }],
}

const A = typeof args === 'string' ? JSON.parse(args) : args
const BUNDLE = A.bundlePath

const CTX =
  `You are reverse-engineering the Even Realities G2 firmware 2.2.4.34 INTER-LENS (peer) communication ` +
  `subsystem. The two lenses (R=master/side1, L=slave/side2) are linked by a physical UART (sync.module.uart) ` +
  `and coordinate via sync.module.framework + a low-level peer-send API (sync.module.api). Read the DECOMPILED ` +
  `BUNDLE file (${BUNDLE}) — 54 functions, each under a "// ===== name @ 0xADDR [module] =====" header, already ` +
  `named and with pb/struct types applied. Our GOAL context: we run a custom hot-loaded app on BOTH lenses and ` +
  `want to (a) push per-lens content R->L, (b) trigger a cross-lens SYNCHRONIZED display present ("both eyes ` +
  `flip together"), (c) relay data L->R (e.g. a screenshot). Analyze precisely from the code — cite function ` +
  `names + addrs + the actual op/sub codes / struct offsets you see. Be concrete and honest about uncertainty.`

const ASPECTS = [
  { key: 'send', title: 'Send primitives & command space',
    focus: `The SEND side (sync.module.api): post_app_command (0x463f1a — the core poster; nail its FULL signature ` +
      `and the meaning of its trailing int args, e.g. the (3,2,0) / op/sub/flags — enumerate every distinct ` +
      `(op,sub) tuple used by callers you can see), send_peer_app_cmd_op3 (0x46435a), send_peer_app_ctrl_op16 ` +
      `(0x464462), send_app_command_to_peer (0x4644c4), send_data_to_peer (0x464c28) + _noevent (0x464988), ` +
      `send_input_event_to_peers (0x464ef0), SendDataToBothExt (0x46471e), sync_alloc_retry (0x463e98). For each: ` +
      `signature, what it puts on the wire (the packet header/format if visible), which (op,sub)/eventType it uses, ` +
      `and when you'd pick it. Produce a table of the peer command space.` },
  { key: 'recv', title: 'Receive, dispatch & wire format',
    focus: `The RECEIVE side: sched_recv_peer_sync_data (0x45ba68), SyncModuleReceivedDataHandler (0x45d860), ` +
      `SendUserDataToThreadPool (0x45aab0), _userDataHandlerCb (0x45aa54), UserDataReplyListener (0x45b90c), ` +
      `SlaveInputEventReplyListener (0x45bbd4), SyncModuleSendDataHandler (0x45e9e8), uart_thread_handler (0x4e1d68). ` +
      `Trace how a peer message arrives (UART -> handler -> thread pool -> target app's dataCb), the exact wire ` +
      `packet layout (appID/op/sub/len/payload offsets), how the target app + its callback is selected, and how ` +
      `replies/acks flow back (the *ReplyListener). This is what a custom app's dataCb receives.` },
  { key: 'display', title: 'Cross-lens display coordination (the "both eyes flip" sync)',
    focus: `The DISPLAY-COORDINATION primitives (sync.module.framework): AsyncRequestDisplayStartUp (0x45ac72) + ` +
      `its handler _AsyncStartUPApplicationDataHandlerCb (0x45ab8e), AsyncRequestDisplayReflash (0x45ae4e) + ` +
      `_AsyncReflashApplicationDataHandlerCb (0x45ad6a), AsyncSendInputEventToPeers (0x45b050) + handler ` +
      `(0x45af48), DispStartBlockingEn/Cancel (0x45c024/0x45c1f0), DispStartBlocking_TimerCb (0x45bf8a), ` +
      `SyncScheduleManagerInit (0x45d570), _private_getCurrentRoleStatus (0x45a8fc). Explain the EXACT protocol ` +
      `for a synchronized cross-lens present: what the master calls, what token/id/args it passes, how it's ` +
      `forwarded to the slave, and how both present together. CRUCIAL: could a custom app on the master call ` +
      `AsyncRequestDisplayReflash (or StartUp) to make BOTH lenses present ITS content in lockstep? What id/token ` +
      `would it need, and what does the local-present path do with it?` },
  { key: 'practice', title: 'Existing app practices & usable primitives for us',
    focus: `The APP-LEVEL usage examples (existing practices): RPC_SyncRingStatusWithPeer (0x47a940), ` +
      `RPC_Onboarding* (0x47af72/0x47afe8/0x47b05a), BoxDetect_ReceiveCaseInfoFromPeer (0x4c5182), ` +
      `CHG_SendBatteryInfoToPeer/ReceiveBatteryInfoFromPeer/RequestNotify (0x4c5d2e/0x4c5e42/0x4c5fcc), ` +
      `SendIdleCommandtoScheduleManager (0x4652b8), SendStartUpCommandtoScheduleManager (0x465524), ` +
      `SendDataToBothExt (0x46471e). Extract the common PATTERN each app uses to sync state R<->L (which send ` +
      `primitive, which appID, request/reply shape). Then SYNTHESIZE: which of these primitives are directly ` +
      `usable by OUR custom app for (a) push per-lens content R->L, (b) a synced present, (c) relay L->R data, ` +
      `and what appID/registration a custom app needs to receive peer messages. Flag the cleanest primitive per goal.` },
]

const results = await parallel(ASPECTS.map((a) => () =>
  agent(`${CTX}\n\nYOUR ASPECT: ${a.title}\n${a.focus}\n\nReturn a thorough, concrete Markdown analysis (### headers, ` +
        `tables, addr/opcode citations). Your output IS the deliverable.`,
        { label: `peer:${a.key}`, phase: 'Analyze' })
))

const out = ASPECTS.map((a, i) => `## ${a.title}\n\n${results[i] || '(no result)'}`).join('\n\n---\n\n')
return { markdown: out }
