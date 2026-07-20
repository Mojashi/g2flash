# Firmware descriptor -> app message binding (fingerprint join)

Each firmware envelope descriptor (wire tags we decode) matched to the app-side
message (Blutter names) by tag-structure fingerprint. Score = fraction of tags whose
submessage-vs-scalar shape agrees.

- **0x777840** (25 fields) -> `TerminalDataPackage` [service terminal]  match=92%
- **0x7727a0** (23 fields) -> `evenhub_main_msg_ctx` [service EvenHub]  match=78%
- **0x771300** (16 fields) -> `DashboardDataPackage` [service dashboard]  match=88%
- **0x772398** (13 fields) -> `EvenAIDataPackage` [service even_ai]  match=100%
- **0x777510** (13 fields) -> `TelepromptDataPackage` [service teleprompt]  match=92%
- **0x770d18** (13 fields) -> `ConversateDataPackage` [service conversate]  match=85%
- **0x771858** (10 fields) -> `DashboardExtPackage` [service dashboard_ext]  match=90%
- **0x774af8** (10 fields) -> `navigation_main_msg_ctx` [service navigation]  match=50%
- **0x777fc0** (8 fields) -> `TranslateDataPackage` [service translate]  match=88%
- **0x772980** (7 fields) -> `G2SettingPackage` [service g2_setting]  match=86%
- **0x773010** (7 fields) -> `TranscribeDataPackage` [service transcribe]  match=57%
- **0x772c80** (6 fields) -> `HealthDataPackage` [service health]  match=100%
- **0x774c30** (6 fields) -> `NotificationDataPackage` [service notification]  match=86%
- **0x774eb8** (5 fields) -> `OnboardingDataPackage` [service onboarding]  match=100%
- **0x7761a8** (5 fields) -> `QuicklistDataPackage` [service quicklist]  match=80%
- **0x7719c0** (5 fields) -> `CreateStartUpPageContainer` [service EvenHub]  match=40%
- **0x7719f0** (5 fields) -> `tracepoint_main_msg_ctx` [service tracepoint]  match=40%
- **0x771750** (4 fields) -> `watchfaceLayoutConfigure` [service dashboard_ext]  match=75%
- **0x7748e8** (4 fields) -> `DashboardReceiveFromApp` [service dashboard]  match=75%
- **0x7749f0** (4 fields) -> `sPageStateSync` [service dashboard]  match=43%
- **0x776268** (4 fields) -> `SendDeviceEvent` [service EvenHub]  match=25%
- **0x7719a8** (3 fields) -> `logger_main_msg_ctx` [service logger]  match=50%
- **0x7773d8** (3 fields) -> `DashboardSendToApp` [service dashboard]  match=40%
- **0x771a20** (3 fields) -> `RebuildPageContainer` [service EvenHub]  match=25%
- **0x771a38** (3 fields) -> `DeviceInfoValue` [service dev_infomation]  match=22%
- **0x771a98** (3 fields) -> `DevCfgDataPackage` [service dev_config_protocol]  match=12%
- **0x771ab0** (3 fields) -> `DeviceReceiveInfoFromAPP` [service g2_setting]  match=0%
- **0x772b90** (3 fields) -> `sWidgetComponent` [service dashboard]  match=0%