// FIRMWARE-EXACT nanopb message structs for g2 fw 2.2.4.34
// Generated from on-device pb_msgdesc_t descriptors (offsets/sizes are GROUND TRUTH).
// Names overlaid from Blutter app proto, propagated through the submessage graph.
// conf: seed=fingerprint-bound root, prop=name-propagated, struct=layout-only (pb_<addr>).
// 244 messages, 156 named.

#include <stdint.h>
#include <stdbool.h>
typedef uint16_t pb_size_t;

typedef struct ConversateDataPackage {   // @0x770d18  fields=13  size=4012 [seed]
  uint8_t commandId;                         // @0  // tag 1
  uint8_t magicRandom;                       // @1  // tag 2
  uint16_t    which_ConversateDataPackage;   // @2
  union {
    ConversateControl      ctrl;  // tag 3
    pb_770d90              prepNoteListRequest;  // tag 4
    ConversatePrepNoteList prepNoteList;  // tag 5
    ConversatePrepNoteSelect prepNoteSelect;  // tag 6
    ConversateTagData      tagData;  // tag 7
    ConversateTranscribeData transcribeData;  // tag 8
    ConversateStatusNotify statusNotify;  // tag 9
    ConversateCommResp     commResp;  // tag 10
    pb_770e80              heartBeat;  // tag 11
    ConversateTagTrackingData tagTrackingData;  // tag 12
    ConversatePrepNotePacket prepNotePacket;  // tag 13
  } u; // @4  // oneof @off 4, size 4008
} ConversateDataPackage;

typedef struct ConversateSettings {   // @0x770d48  fields=5  size=5 [prop]
  uint8_t aiCue;                             // @0  // tag 1
  uint8_t transcribe;                        // @1  // tag 2
  uint8_t autoPopEn;                         // @2  // tag 3
  uint8_t useAudio;                          // @3  // tag 4
  uint8_t cueDuration;                       // @4  // tag 5
} ConversateSettings;

typedef struct ConversatePrepNoteListItem {   // @0x770d60  fields=2  size=136 [prop]
  uint32_t id;                               // @0  // tag 1
  char title[130];                           // @4  // tag 2
} ConversatePrepNoteListItem;

typedef struct ConversatePrepNoteList {   // @0x770d78  fields=2  size=2728 [prop]
  uint16_t    list_count;                    // @0
  ConversatePrepNoteListItem list[20];       // @4  // tag 1 rep[20]
  uint32_t selectId;                         // @2724  // tag 2
} ConversatePrepNoteList;

typedef struct pb_770d90 {   // @0x770d90  fields=0  size=1 [struct]
} pb_770d90;

typedef struct ConversatePrepNoteSelect {   // @0x770da8  fields=2  size=8 [prop]
  uint8_t isSkip;                            // @0  // tag 1
  uint32_t selectId;                         // @4  // tag 2
} ConversatePrepNoteSelect;

typedef struct ConversatePrepNote {   // @0x770dc0  fields=2  size=136 [prop]
  char title[130];                           // @0  // tag 1
  uint32_t totalPackets;                     // @132  // tag 2
} ConversatePrepNote;

typedef struct ConversatePrepNotePacket {   // @0x770dd8  fields=2  size=4008 [prop]
  uint32_t packetIndex;                      // @0  // tag 1
  char text[4002];                           // @4  // tag 2
} ConversatePrepNotePacket;

typedef struct ConversateControl {   // @0x770df0  fields=4  size=148 [prop]
  uint8_t cmd;                               // @0  // tag 1
  bool        has_settings;                  // @1
  ConversateSettings settings;               // @2  // tag 2
  bool        has_noteInfo;                  // @7
  ConversatePrepNote noteInfo;               // @8  // tag 3
  uint8_t errCode;                           // @144  // tag 4
} ConversateControl;

typedef struct ConversateTagData {   // @0x770e08  fields=4  size=1164 [prop]
  uint8_t tagType;                           // @0  // tag 1
  char tagText[130];                         // @2  // tag 2
  char tagTextExtend[1026];                  // @132  // tag 3
  uint32_t tagId;                            // @1160  // tag 4
} ConversateTagData;

typedef struct ConversateTranscribeData {   // @0x770e20  fields=2  size=1032 [prop]
  char transcribeText[1026];                 // @0  // tag 1
  uint32_t transcribeEndFlag;                // @1028  // tag 2
} ConversateTranscribeData;

typedef struct ConversateStatusNotify {   // @0x770e38  fields=2  size=2 [prop]
  uint8_t cmd;                               // @0  // tag 1
  uint8_t errCode;                           // @1  // tag 2
} ConversateStatusNotify;

typedef struct ConversateTagTrackingData {   // @0x770e50  fields=4  size=12 [prop]
  uint32_t tagId;                            // @0  // tag 1
  uint8_t openType;                          // @4  // tag 2
  uint8_t closeType;                         // @5  // tag 3
  uint32_t durationTimeMs;                   // @8  // tag 4
} ConversateTagTrackingData;

typedef struct ConversateCommResp {   // @0x770e68  fields=1  size=1 [prop]
  uint8_t errCode;                           // @0  // tag 1
} ConversateCommResp;

typedef struct pb_770e80 {   // @0x770e80  fields=0  size=1 [struct]
} pb_770e80;

typedef struct RequestNewsFifoCountCmd {   // @0x7711f8  fields=1  size=4 [prop]
  uint32_t cmd;                              // @0  // tag 1
} RequestNewsFifoCountCmd;

typedef struct ResponseNewsFifoMsg {   // @0x771210  fields=1  size=4 [prop]
  uint32_t count;                            // @0  // tag 1
} ResponseNewsFifoMsg;

typedef struct AppRequestDeviceNewsInfo {   // @0x771228  fields=1  size=4 [prop]
  uint32_t cmd;                              // @0  // tag 1
} AppRequestDeviceNewsInfo;

typedef struct DeviceResponseNewsInfo {   // @0x771240  fields=2  size=48 [prop]
  uint32_t totalNewsCount;                   // @0  // tag 1
  uint16_t    newsId_count;                  // @4
  uint32_t newsId[10];                       // @8  // tag 2 rep[10]
} DeviceResponseNewsInfo;

typedef struct AppSendNewsData {   // @0x771258  fields=9  size=7344 [prop]
  uint32_t sessionId;                        // @0  // tag 1
  uint32_t sessionStatus;                    // @4  // tag 2
  uint32_t sessionTotalCount;                // @8  // tag 3
  uint32_t sessionNewsIndex;                 // @12  // tag 4
  uint32_t newsId;                           // @16  // tag 5
  uint8_t bytes_tag6[128];                   // @20  // tag 6
  uint64_t reportTime;                       // @152  // tag 7
  uint8_t bytes_tag8[128];                   // @160  // tag 8
  uint8_t bytes_tag9[7050];                  // @288  // tag 9
} AppSendNewsData;

typedef struct DeviceResponseNewData {   // @0x771288  fields=5  size=20 [prop]
  uint32_t sessionId;                        // @0  // tag 1
  uint32_t sessionTotalCount;                // @4  // tag 2
  uint32_t sessionNewsIndex;                 // @8  // tag 3
  uint32_t newsId;                           // @12  // tag 4
  uint32_t newsStatus;                       // @16  // tag 5
} DeviceResponseNewData;

typedef struct DeviceRequestNewsUpgrade {   // @0x7712a0  fields=1  size=4 [prop]
  uint32_t cmd;                              // @0  // tag 1
} DeviceRequestNewsUpgrade;

typedef struct DeviceNotifyNewsEvent {   // @0x7712b8  fields=2  size=8 [prop]
  uint8_t eventID;                           // @0  // tag 1
  uint32_t value;                            // @4  // tag 2
} DeviceNotifyNewsEvent;

typedef struct AppResetClearAllDataMsg {   // @0x7712d0  fields=1  size=4 [prop]
  uint32_t cmd;                              // @0  // tag 1
} AppResetClearAllDataMsg;

typedef struct DeviceResponseClearAllDataMsg {   // @0x7712e8  fields=1  size=4 [prop]
  uint32_t cmd;                              // @0  // tag 1
} DeviceResponseClearAllDataMsg;

typedef struct DashboardDataPackage {   // @0x771300  fields=16  size=7360 [seed]
  uint8_t commandId;                         // @0  // tag 1
  uint32_t magicRandom;                      // @4  // tag 2
  uint16_t    which_DashboardDataPackage;    // @8
  union {
    DashboardRespondToApp  dashboardRespond;  // tag 3
    DashboardReceiveFromApp dashboardReceive;  // tag 4
    AppRespondToDashboard  appRespond;  // tag 5
    DashboardSendToApp     appReceive;  // tag 6
    RequestNewsFifoCountCmd ReqNewsCmd;  // tag 7
    ResponseNewsFifoMsg    ResNewsMsg;  // tag 8
    AppRequestDeviceNewsInfo ReqNewsInfo;  // tag 9
    DeviceResponseNewsInfo ResNewsInfo;  // tag 10
    AppSendNewsData        SendNewsData;  // tag 11
    DeviceResponseNewData  ResNewsData;  // tag 12
    DeviceRequestNewsUpgrade ReqNewsUpgrade;  // tag 13
    DeviceNotifyNewsEvent  NotifyNewsEvent;  // tag 14
    AppResetClearAllDataMsg ResClearAllData;  // tag 15
    DeviceResponseClearAllDataMsg RespClearAllData;  // tag 16
  } u; // @16  // oneof @off 16, size 7344
} DashboardDataPackage;

typedef struct rWeatherStatus {   // @0x771318  fields=9  size=120 [prop]
  uint32_t temperature;                      // @0  // tag 1
  uint8_t unit;                              // @4  // tag 2
  uint8_t type;                              // @5  // tag 3
  uint64_t updateTime;                       // @8  // tag 4
  uint8_t bytes_tag5[32];                    // @16  // tag 5
  uint32_t rainfallProbabilityIcon;          // @48  // tag 6
  uint8_t bytes_tag7[32];                    // @52  // tag 7
  int32_t sunsetSelect;                      // @84  // tag 8
  uint8_t bytes_tag9[32];                    // @88  // tag 9
} rWeatherStatus;

typedef struct sNotificationStatus {   // @0x771330  fields=1  size=4 [prop]
  uint32_t unreadCount;                      // @0  // tag 1
} sNotificationStatus;

typedef struct sPowerStatus {   // @0x771348  fields=2  size=8 [prop]
  uint32_t powerLeft;                        // @0  // tag 1
  uint32_t powerRight;                       // @4  // tag 2
} sPowerStatus;

typedef struct rStatusComponent {   // @0x771360  fields=1  size=128 [prop]
  bool        has_weather;                   // @0
  rWeatherStatus weather;                    // @8  // tag 1
} rStatusComponent;

typedef struct sStatusComponent {   // @0x771378  fields=2  size=20 [prop]
  bool        has_notification;              // @0
  sNotificationStatus notification;          // @4  // tag 1
  bool        has_power;                     // @8
  sPowerStatus power;                        // @12  // tag 2
} sStatusComponent;

typedef struct rNewsWidget {   // @0x771390  fields=4  size=3296 [prop]
  uint32_t newsTotal;                        // @0  // tag 1
  uint32_t newsNum;                          // @4  // tag 2
  bool        has_news;                      // @8
  News news;                                 // @16  // tag 3
  uint32_t newsForceUpgrade;                 // @3288  // tag 4
} rNewsWidget;

typedef struct News {   // @0x7713a8  fields=5  size=3272 [prop]
  uint32_t newsId;                           // @0  // tag 1
  uint8_t bytes_tag2[128];                   // @4  // tag 2
  uint64_t reportTime;                       // @136  // tag 3
  uint8_t bytes_tag4[128];                   // @144  // tag 4
  uint8_t bytes_tag5[3000];                  // @272  // tag 5
} News;

typedef struct sNewsWidgetApplyNews {   // @0x7713c0  fields=2  size=8 [prop]
  uint32_t requiredCount;                    // @0  // tag 1
  uint32_t requiredStartId;                  // @4  // tag 2
} sNewsWidgetApplyNews;

typedef struct sNewsWidgetSync {   // @0x7713d8  fields=2  size=16 [prop]
  uint32_t syncNewsId;                       // @0  // tag 1
  uint64_t syncNewsBytesRead;                // @8  // tag 2
} sNewsWidgetSync;

typedef struct sNewsWidget {   // @0x7713f0  fields=2  size=24 [prop]
  uint16_t    which_sNewsWidget;             // @0
  union {
    sNewsWidgetApplyNews   applyEvent;  // tag 1
    sNewsWidgetSync        syncEvent;  // tag 2
  } u; // @8  // oneof @off 8, size 16
} sNewsWidget;

typedef struct rStockWidget {   // @0x771408  fields=3  size=1080 [prop]
  uint32_t stockTotal;                       // @0  // tag 1
  uint32_t stockNum;                         // @4  // tag 2
  bool        has_stock;                     // @8
  Stock stock;                               // @16  // tag 3
} rStockWidget;

typedef struct Stock {   // @0x771420  fields=16  size=1064 [prop]
  uint8_t bytes_tag1[64];                    // @0  // tag 1
  uint8_t bytes_tag2[64];                    // @64  // tag 2
  uint64_t marketCap;                        // @128  // tag 3
  uint32_t priceChangePercent;               // @136  // tag 4
  uint32_t currentPrice;                     // @140  // tag 5
  uint8_t bytes_tag6[128];                   // @144  // tag 6
  uint32_t dayHigh;                          // @272  // tag 7
  uint32_t dayLow;                           // @276  // tag 8
  uint32_t openPrice;                        // @280  // tag 9
  uint64_t volume;                           // @288  // tag 10
  uint64_t marketValue;                      // @296  // tag 11
  uint32_t peRatio;                          // @304  // tag 12
  uint32_t changingTrend;                    // @308  // tag 13
  uint32_t pointTotal;                       // @312  // tag 14
  uint32_t darkPrice;                        // @316  // tag 15
  uint16_t    brightPrice_count;             // @320
  uint32_t brightPrice[185];                 // @324  // tag 16 rep[185]
} Stock;

typedef struct pb_771438 {   // @0x771438  fields=1  size=64 [struct]
  uint8_t bytes_tag1[64];                    // @0  // tag 1
} pb_771438;

typedef struct rScheduleWidget {   // @0x771450  fields=4  size=548 [prop]
  uint32_t scheduleTotal;                    // @0  // tag 1
  uint32_t scheduleNum;                      // @4  // tag 2
  bool        has_schedule;                  // @8
  Schedule schedule;                         // @12  // tag 3
  uint32_t scheduleAuthority;                // @544  // tag 4
} rScheduleWidget;

typedef struct Schedule {   // @0x771468  fields=5  size=532 [prop]
  uint32_t scheduleId;                       // @0  // tag 1
  uint8_t bytes_tag2[176];                   // @4  // tag 2
  uint8_t bytes_tag3[283];                   // @180  // tag 3
  uint8_t bytes_tag4[64];                    // @463  // tag 4
  uint32_t endTimestamp;                     // @528  // tag 5
} Schedule;

typedef struct sScheduleWidget {   // @0x771480  fields=2  size=8 [prop]
  uint32_t syncScheduleId;                   // @0  // tag 1
  uint32_t syncScheduleLine;                 // @4  // tag 2
} sScheduleWidget;

typedef struct rWidgetComponent {   // @0x771498  fields=3  size=3304 [prop]
  uint16_t    which_rWidgetComponent;        // @0
  union {
    rNewsWidget            news;  // tag 1
    rStockWidget           stock;  // tag 2
    rScheduleWidget        schedule;  // tag 3
  } u; // @8  // oneof @off 8, size 3296
} rWidgetComponent;

typedef struct sWidgetComponent {   // @0x7714b0  fields=3  size=72 [prop]
  uint16_t    which_sWidgetComponent;        // @0
  union {
    sNewsWidget            news;  // tag 1
    pb_771438              stock;  // tag 2
    sScheduleWidget        schedule;  // tag 3
  } u; // @8  // oneof @off 8, size 64
} sWidgetComponent;

typedef struct AppRequest {   // @0x7714c8  fields=1  size=4 [prop]
  uint32_t appRequestNewsInfo;               // @0  // tag 1
} AppRequest;

typedef struct DashboardRespondToApp {   // @0x7714e0  fields=2  size=8 [prop]
  uint32_t packageId;                        // @0  // tag 1
  uint8_t flag;                              // @4  // tag 2
} DashboardRespondToApp;

typedef struct DashboardReceiveFromApp {   // @0x7714f8  fields=4  size=3320 [prop]
  uint32_t packageId;                        // @0  // tag 1
  uint16_t    which_DashboardReceiveFromApp; // @4
  union {
    DashboardDisplaySetting bashboardDisplaySetting;  // tag 2
    DashboardContent       bashboardConfig;  // tag 3
    AppRequest             appRequest;  // tag 4
  } u; // @8  // oneof @off 8, size 3312
} DashboardReceiveFromApp;

typedef struct DashboardDisplaySetting {   // @0x771510  fields=7  size=44 [prop]
  uint32_t displayMode;                      // @0  // tag 1
  uint32_t statusDisplayCount;               // @4  // tag 2
  uint16_t    statusDisplayOrder_count;      // @8
  uint8_t statusDisplayOrder[10];            // @10  // tag 3 rep[10]
  uint32_t widgetDisplayCount;               // @20  // tag 4
  uint16_t    widgetDisplayOrder_count;      // @24
  uint8_t widgetDisplayOrder[10];            // @26  // tag 5 rep[10]
  uint32_t halfDayFormat;                    // @36  // tag 6
  uint32_t temperatureUnit;                  // @40  // tag 7
} DashboardDisplaySetting;

typedef struct DashboardContent {   // @0x771528  fields=2  size=3312 [prop]
  uint16_t    which_DashboardContent;        // @0
  union {
    rStatusComponent       statusComponents;  // tag 1
    rWidgetComponent       widgetComponents;  // tag 2
  } u; // @8  // oneof @off 8, size 3304
} DashboardContent;

typedef struct AppRespondToDashboard {   // @0x771540  fields=2  size=8 [prop]
  uint32_t packageId;                        // @0  // tag 1
  uint8_t flag;                              // @4  // tag 2
} AppRespondToDashboard;

typedef struct DashboardSendToApp {   // @0x771558  fields=5  size=80 [prop]
  uint32_t packageId;                        // @0  // tag 1
  bool b_tag2;                               // @4  // tag 2
  uint16_t    which_DashboardSendToApp;      // @6
  union {
    sStatusComponent       statusComponents;  // tag 3
    sWidgetComponent       widgetComponents;  // tag 4
    sPageStateSync         pageStateSync;  // tag 5
  } u; // @8  // oneof @off 8, size 72
} DashboardSendToApp;

typedef struct DashboardMainPageState {   // @0x771570  fields=2  size=8 [prop]
  uint32_t activeTileIndex;                  // @0  // tag 1
  uint8_t activeWidgetType;                  // @4  // tag 2
} DashboardMainPageState;

typedef struct NewsExpandedPageState {   // @0x771588  fields=1  size=4 [prop]
  uint32_t currentNewsIndex;                 // @0  // tag 1
} NewsExpandedPageState;

typedef struct StockExpandedPageState {   // @0x7715a0  fields=1  size=4 [prop]
  uint32_t currentPageIndex;                 // @0  // tag 1
} StockExpandedPageState;

typedef struct CalendarExpandedPageState {   // @0x7715b8  fields=1  size=4 [prop]
  uint32_t currentPageIndex;                 // @0  // tag 1
} CalendarExpandedPageState;

typedef struct QuicklistExpandedPageState {   // @0x7715d0  fields=5  size=60 [prop]
  uint32_t displayedUidCount;                // @0  // tag 1
  uint16_t    displayedUidList_count;        // @4
  uint32_t displayedUidList[10];             // @8  // tag 2 rep[10]
  uint32_t borderState;                      // @48  // tag 3
  uint32_t focusedUidIndex;                  // @52  // tag 4
  bool b_tag5;                               // @56  // tag 5
} QuicklistExpandedPageState;

typedef struct HealthExpandedPageState {   // @0x7715e8  fields=1  size=4 [prop]
  uint32_t currentPageIndex;                 // @0  // tag 1
} HealthExpandedPageState;

typedef struct sPageStateSync {   // @0x771600  fields=7  size=64 [prop]
  uint8_t currentPageType;                   // @0  // tag 1
  uint16_t    which_sPageStateSync;          // @2
  union {
    DashboardMainPageState dashboardMain;  // tag 2
    NewsExpandedPageState  newsExpanded;  // tag 3
    StockExpandedPageState stockExpanded;  // tag 4
    CalendarExpandedPageState calendarExpanded;  // tag 5
    QuicklistExpandedPageState quicklistExpanded;  // tag 6
    HealthExpandedPageState healthExpanded;  // tag 7
  } u; // @4  // oneof @off 4, size 60
} sPageStateSync;

typedef struct pb_7716d8 {   // @0x7716d8  fields=3  size=8 [struct]
  uint32_t u_tag1;                           // @0  // tag 1
  uint8_t u_tag2;                            // @4  // tag 2
  uint8_t u_tag3;                            // @5  // tag 3
} pb_7716d8;

typedef struct pb_771708 {   // @0x771708  fields=4  size=20 [struct]
  uint32_t u_tag1;                           // @0  // tag 1
  uint32_t u_tag2;                           // @4  // tag 2
  uint32_t u_tag3;                           // @8  // tag 3
  uint16_t    u_tag4_count;                  // @12
  uint8_t u_tag4[3];                         // @14  // tag 4 rep[3]
} pb_771708;

typedef struct pb_771720 {   // @0x771720  fields=3  size=12 [struct]
  uint32_t u_tag1;                           // @0  // tag 1
  uint32_t u_tag2;                           // @4  // tag 2
  uint32_t u_tag3;                           // @8  // tag 3
} pb_771720;

typedef struct pb_771738 {   // @0x771738  fields=4  size=120 [struct]
  uint32_t u_tag1;                           // @0  // tag 1
  uint32_t u_tag2;                           // @4  // tag 2
  uint16_t    bytes_tag3_count;              // @8
  uint8_t bytes_tag3[32];                    // @10  // tag 3 rep[3]
  uint16_t    f32_tag4_count;                // @106
  uint32_t f32_tag4[3];                      // @108  // tag 4 rep[3]
} pb_771738;

typedef struct pb_771750 {   // @0x771750  fields=4  size=124 [struct]
  uint16_t    which_pb_771750;               // @0
  union {
    pb_7716d8              msg_tag1;  // tag 1
    pb_771708              msg_tag2;  // tag 2
    pb_771720              msg_tag3;  // tag 3
    pb_771738              msg_tag4;  // tag 4
  } u; // @4  // oneof @off 4, size 120
} pb_771750;

typedef struct AppRequestPbFileInfo {   // @0x771780  fields=1  size=4 [prop]
  uint32_t cmd;                              // @0  // tag 1
} AppRequestPbFileInfo;

typedef struct OsResponsePbFileInfo {   // @0x7717b0  fields=3  size=52 [prop]
  uint32_t isPbFileExist;                    // @0  // tag 1
  uint8_t bytes_tag2[16];                    // @4  // tag 2
  uint8_t bytes_tag3[32];                    // @20  // tag 3
} OsResponsePbFileInfo;

typedef struct AppRequestUpgradePbFile {   // @0x7717c8  fields=1  size=4 [prop]
  uint32_t cmd;                              // @0  // tag 1
} AppRequestUpgradePbFile;

typedef struct OsResponseUpgradePbFile {   // @0x7717e0  fields=1  size=4 [prop]
  uint32_t status;                           // @0  // tag 1
} OsResponseUpgradePbFile;

typedef struct OsNotifyPbFileTransmitStart {   // @0x7717f8  fields=1  size=4 [prop]
  uint32_t cmd;                              // @0  // tag 1
} OsNotifyPbFileTransmitStart;

typedef struct AppSendPbFileData {   // @0x771810  fields=6  size=4120 [prop]
  uint32_t sessionId;                        // @0  // tag 1
  uint32_t totalSize;                        // @4  // tag 2
  uint32_t compressMode;                     // @8  // tag 3
  uint32_t fragmentIndex;                    // @12  // tag 4
  uint32_t fragmentPacketSize;               // @16  // tag 5
  char rawData[4098];                        // @20  // tag 6
} AppSendPbFileData;

typedef struct OsResponsePbFileData {   // @0x771828  fields=6  size=24 [prop]
  uint32_t sessionId;                        // @0  // tag 1
  uint32_t totalSize;                        // @4  // tag 2
  uint32_t compressMode;                     // @8  // tag 3
  uint32_t fragmentIndex;                    // @12  // tag 4
  uint32_t fragmentPacketSize;               // @16  // tag 5
  uint32_t OsStatus;                         // @20  // tag 6
} OsResponsePbFileData;

typedef struct OsNotifyPbFileUpdate {   // @0x771840  fields=1  size=4 [prop]
  uint32_t cmd;                              // @0  // tag 1
} OsNotifyPbFileUpdate;

typedef struct DashboardExtPackage {   // @0x771858  fields=10  size=4132 [seed]
  uint8_t cmdId;                             // @0  // tag 1
  uint32_t magicRandom;                      // @4  // tag 2
  uint16_t    which_DashboardExtPackage;     // @8
  union {
    AppRequestPbFileInfo   ReqPbInfoMsg;  // tag 3
    OsResponsePbFileInfo   ResPbInfoMsg;  // tag 4
    AppRequestUpgradePbFile ReqPbUpgrade;  // tag 5
    OsResponseUpgradePbFile ResPbupgrade;  // tag 6
    OsNotifyPbFileTransmitStart NotifyPbTransStart;  // tag 7
    AppSendPbFileData      SendPbFile;  // tag 8
    OsResponsePbFileData   ResPbFile;  // tag 9
    OsNotifyPbFileUpdate   NotifyPbUpdate;  // tag 10
  } u; // @12  // oneof @off 12, size 4120
} DashboardExtPackage;

typedef struct pb_7718e8 {   // @0x7718e8  fields=2  size=2 [struct]
  uint8_t u_tag1;                            // @0  // tag 1
  uint8_t u_tag2;                            // @1  // tag 2
} pb_7718e8;

typedef struct pb_771900 {   // @0x771900  fields=2  size=200 [struct]
  uint16_t    msg_tag1_count;                // @0
  pb_771918 msg_tag1[8];                     // @4  // tag 1 rep[8]
  uint8_t u_tag2;                            // @196  // tag 2
} pb_771900;

typedef struct pb_771918 {   // @0x771918  fields=9  size=24 [struct]
  uint8_t u_tag1;                            // @0  // tag 1
  uint16_t    which_pb_771918;               // @2
  union {
    pb_771930              msg_tag2;  // tag 2
    uint32_t               u_tag3;  // tag 3
    pb_771948              msg_tag4;  // tag 4
    pb_771948              msg_tag5;  // tag 5
    pb_771978              msg_tag6;  // tag 6
    pb_771960              msg_tag7;  // tag 7
    pb_771960              msg_tag8;  // tag 8
    pb_771990              msg_tag9;  // tag 9
  } u; // @4  // oneof @off 4, size 20
} pb_771918;

typedef struct pb_771930 {   // @0x771930  fields=3  size=8 [struct]
  uint32_t u_tag1;                           // @0  // tag 1
  uint8_t u_tag2;                            // @4  // tag 2
  uint8_t u_tag3;                            // @5  // tag 3
} pb_771930;

typedef struct pb_771948 {   // @0x771948  fields=2  size=8 [struct]
  uint32_t u_tag1;                           // @0  // tag 1
  uint8_t u_tag2;                            // @4  // tag 2
} pb_771948;

typedef struct pb_771960 {   // @0x771960  fields=2  size=20 [struct]
  char str_tag1[18];                         // @0  // tag 1
  uint8_t u_tag2;                            // @18  // tag 2
} pb_771960;

typedef struct pb_771978 {   // @0x771978  fields=3  size=12 [struct]
  uint32_t u_tag1;                           // @0  // tag 1
  uint32_t u_tag2;                           // @4  // tag 2
  uint8_t u_tag3;                            // @8  // tag 3
} pb_771978;

typedef struct pb_771990 {   // @0x771990  fields=2  size=10 [struct]
  char str_tag1[8];                          // @0  // tag 1
  uint8_t u_tag2;                            // @8  // tag 2
} pb_771990;

typedef struct pb_7719a8 {   // @0x7719a8  fields=3  size=3 [struct]
  bool b_tag1;                               // @0  // tag 1
  uint8_t u_tag2;                            // @1  // tag 2
  uint8_t u_tag3;                            // @2  // tag 3
} pb_7719a8;

typedef struct pb_7719c0 {   // @0x7719c0  fields=5  size=30 [struct]
  bool b_tag1;                               // @0  // tag 1
  char str_tag2[8];                          // @2  // tag 2
  char str_tag3[18];                         // @10  // tag 3
  uint8_t u_tag4;                            // @28  // tag 4
  uint8_t u_tag5;                            // @29  // tag 5
} pb_7719c0;

typedef struct pb_7719f0 {   // @0x7719f0  fields=5  size=8 [struct]
  uint16_t u_tag1;                           // @0  // tag 1
  uint16_t u_tag2;                           // @2  // tag 2
  uint8_t u_tag3;                            // @4  // tag 3
  bool b_tag4;                               // @5  // tag 4
  uint8_t u_tag5;                            // @6  // tag 5
} pb_7719f0;

typedef struct pb_771a08 {   // @0x771a08  fields=2  size=2 [struct]
  uint8_t u_tag1;                            // @0  // tag 1
  uint8_t u_tag2;                            // @1  // tag 2
} pb_771a08;

typedef struct pb_771a20 {   // @0x771a20  fields=3  size=11 [struct]
  uint8_t u_tag1;                            // @0  // tag 1
  char str_tag2[8];                          // @2  // tag 2
  uint8_t u_tag3;                            // @10  // tag 3
} pb_771a20;

typedef struct pb_771a38 {   // @0x771a38  fields=3  size=11 [struct]
  uint8_t u_tag1;                            // @0  // tag 1
  char str_tag2[8];                          // @2  // tag 2
  uint8_t u_tag3;                            // @10  // tag 3
} pb_771a38;

typedef struct pb_771a50 {   // @0x771a50  fields=1  size=1 [struct]
  uint8_t u_tag1;                            // @0  // tag 1
} pb_771a50;

typedef struct pb_771a68 {   // @0x771a68  fields=1  size=1 [struct]
  uint8_t u_tag1;                            // @0  // tag 1
} pb_771a68;

typedef struct pb_771a80 {   // @0x771a80  fields=1  size=1 [struct]
  uint8_t u_tag1;                            // @0  // tag 1
} pb_771a80;

typedef struct pb_771a98 {   // @0x771a98  fields=3  size=8 [struct]
  uint32_t u_tag1;                           // @0  // tag 1
  int8_t i_tag2;                             // @4  // tag 2
  uint8_t u_tag3;                            // @5  // tag 3
} pb_771a98;

typedef struct pb_771ab0 {   // @0x771ab0  fields=3  size=12 [struct]
  uint8_t u_tag1;                            // @0  // tag 1
  uint32_t u_tag2;                           // @4  // tag 2
  uint8_t u_tag3;                            // @8  // tag 3
} pb_771ab0;

typedef struct EvenAIDataPackage {   // @0x772398  fields=13  size=524 [seed]
  uint8_t commandId;                         // @0  // tag 1
  uint8_t magicRandom;                       // @1  // tag 2
  uint16_t    which_EvenAIDataPackage;       // @2
  union {
    EvenAIControl          ctrl;  // tag 3
    EvenAIVADInfo          vadInfo;  // tag 4
    EvenAIAskInfo          askInfo;  // tag 5
    EvenAIAnalyseInfo      analyseInfo;  // tag 6
    EvenAIReplyInfo        replyInfo;  // tag 7
    EvenAISkillInfo        skillInfo;  // tag 8
    EvenAIPromptInfo       promptInfo;  // tag 9
    EvenAIEvent            event;  // tag 10
    EvenAIHeartbeat        heartbeat;  // tag 11
    EvenAICommRsp          resp;  // tag 12
    EvenAIConfig           config;  // tag 13
  } u; // @4  // oneof @off 4, size 520
} EvenAIDataPackage;

typedef struct EvenAIControl {   // @0x7723b0  fields=2  size=2 [prop]
  uint8_t status;                            // @0  // tag 1
  uint8_t errorCode;                         // @1  // tag 2
} EvenAIControl;

typedef struct EvenAIVADInfo {   // @0x7723c8  fields=2  size=2 [prop]
  uint8_t vadStatus;                         // @0  // tag 1
  uint8_t errorCode;                         // @1  // tag 2
} EvenAIVADInfo;

typedef struct EvenAIAskInfo {   // @0x7723e0  fields=5  size=520 [prop]
  uint8_t cmdCnt;                            // @0  // tag 1
  uint8_t streamEnable;                      // @1  // tag 2
  uint8_t textMode;                          // @2  // tag 3
  char text[514];                            // @4  // tag 4
  uint8_t errorCode;                         // @518  // tag 5
} EvenAIAskInfo;

typedef struct EvenAIAnalyseInfo {   // @0x7723f8  fields=1  size=1 [prop]
  uint8_t errorCode;                         // @0  // tag 1
} EvenAIAnalyseInfo;

typedef struct EvenAIReplyInfo {   // @0x772410  fields=6  size=520 [prop]
  uint8_t cmdCnt;                            // @0  // tag 1
  uint8_t streamEnable;                      // @1  // tag 2
  uint8_t textMode;                          // @2  // tag 3
  char text[514];                            // @4  // tag 4
  uint8_t errorCode;                         // @518  // tag 5
  uint8_t fTextEnd;                          // @519  // tag 6
} EvenAIReplyInfo;

typedef struct EvenAISkillInfo {   // @0x772428  fields=6  size=268 [prop]
  uint8_t streamEnable;                      // @0  // tag 1
  uint8_t skillId;                           // @1  // tag 2
  uint32_t skillParam;                       // @4  // tag 3
  char text[258];                            // @8  // tag 4
  uint8_t errorCode;                         // @266  // tag 5
  uint8_t fTextEnd;                          // @267  // tag 6
} EvenAISkillInfo;

typedef struct EvenAIPromptInfo {   // @0x772440  fields=2  size=2 [prop]
  uint8_t promptType;                        // @0  // tag 1
  uint8_t errorCode;                         // @1  // tag 2
} EvenAIPromptInfo;

typedef struct EvenAIEvent {   // @0x772458  fields=2  size=2 [prop]
  uint8_t event;                             // @0  // tag 1
  uint8_t errorCode;                         // @1  // tag 2
} EvenAIEvent;

typedef struct EvenAIHeartbeat {   // @0x772470  fields=2  size=2 [prop]
  uint8_t hbCnt;                             // @0  // tag 1
  uint8_t errorCode;                         // @1  // tag 2
} EvenAIHeartbeat;

typedef struct EvenAICommRsp {   // @0x772488  fields=1  size=1 [prop]
  uint8_t errorCode;                         // @0  // tag 1
} EvenAICommRsp;

typedef struct EvenAIConfig {   // @0x7724a0  fields=4  size=4 [prop]
  uint8_t voiceSwitch;                       // @0  // tag 1
  uint8_t streamSpeed;                       // @1  // tag 2
  uint8_t errorCode;                         // @2  // tag 3
  uint8_t duplexMode;                        // @3  // tag 4
} EvenAIConfig;

typedef struct pb_7724b8 {   // @0x7724b8  fields=5  size=92 [struct]
  uint32_t u_tag1;                           // @0  // tag 1
  uint8_t bytes_tag2[16];                    // @4  // tag 2
  uint8_t bytes_tag3[64];                    // @20  // tag 3
  uint32_t u_tag4;                           // @84  // tag 4
  uint8_t u_tag5;                            // @88  // tag 5
} pb_7724b8;

typedef struct pb_7724d0 {   // @0x7724d0  fields=3  size=24 [struct]
  uint32_t u_tag1;                           // @0  // tag 1
  uint8_t bytes_tag2[16];                    // @4  // tag 2
  uint8_t u_tag3;                            // @20  // tag 3
} pb_7724d0;

typedef struct pb_7724e8 {   // @0x7724e8  fields=3  size=12 [struct]
  uint32_t f32_tag1;                         // @0  // tag 1
  uint32_t f32_tag2;                         // @4  // tag 2
  uint32_t f32_tag3;                         // @8  // tag 3
} pb_7724e8;

typedef struct pb_772518 {   // @0x772518  fields=4  size=20 [struct]
  uint8_t u_tag1;                            // @0  // tag 1
  uint8_t u_tag2;                            // @1  // tag 2
  bool        has_msg_tag3;                  // @2
  pb_7724e8 msg_tag3;                        // @4  // tag 3
  uint32_t u_tag4;                           // @16  // tag 4
} pb_772518;

typedef struct pb_772530 {   // @0x772530  fields=3  size=96 [struct]
  uint16_t    which_pb_772530;               // @0
  union {
    pb_7724b8              msg_tag1;  // tag 1
    pb_7724d0              msg_tag2;  // tag 2
    pb_772518              msg_tag3;  // tag 3
  } u; // @4  // oneof @off 4, size 92
} pb_772530;

typedef struct pb_772548 {   // @0x772548  fields=4  size=1296 [struct]
  uint32_t u_tag1;                           // @0  // tag 1
  uint32_t u_tag2;                           // @4  // tag 2
  uint32_t u_tag3;                           // @8  // tag 3
  uint16_t    bytes_tag4_count;              // @12
  uint8_t bytes_tag4[64];                    // @14  // tag 4 rep[20]
} pb_772548;

typedef struct pb_772560 {   // @0x772560  fields=12  size=1356 [struct]
  uint32_t u_tag1;                           // @0  // tag 1
  uint32_t u_tag2;                           // @4  // tag 2
  uint32_t u_tag3;                           // @8  // tag 3
  uint32_t u_tag4;                           // @12  // tag 4
  uint32_t u_tag5;                           // @16  // tag 5
  uint32_t u_tag6;                           // @20  // tag 6
  uint32_t u_tag7;                           // @24  // tag 7
  uint32_t u_tag8;                           // @28  // tag 8
  uint32_t u_tag9;                           // @32  // tag 9
  uint8_t bytes_tag10[16];                   // @36  // tag 10
  bool        has_msg_tag11;                 // @52
  pb_772548 msg_tag11;                       // @56  // tag 11
  uint32_t u_tag12;                          // @1352  // tag 12
} pb_772560;

typedef struct pb_772578 {   // @0x772578  fields=5  size=2028 [struct]
  uint32_t u_tag1;                           // @0  // tag 1
  uint8_t bytes_tag2[16];                    // @4  // tag 2
  uint32_t u_tag3;                           // @20  // tag 3
  uint32_t u_tag4;                           // @24  // tag 4
  uint8_t bytes_tag5[2000];                  // @28  // tag 5
} pb_772578;

typedef struct pb_772590 {   // @0x772590  fields=1  size=1 [struct]
  uint8_t u_tag1;                            // @0  // tag 1
} pb_772590;

typedef struct pb_7725a8 {   // @0x7725a8  fields=12  size=1056 [struct]
  uint32_t u_tag1;                           // @0  // tag 1
  uint32_t u_tag2;                           // @4  // tag 2
  uint32_t u_tag3;                           // @8  // tag 3
  uint32_t u_tag4;                           // @12  // tag 4
  uint32_t u_tag5;                           // @16  // tag 5
  uint32_t u_tag6;                           // @20  // tag 6
  uint32_t u_tag7;                           // @24  // tag 7
  uint32_t u_tag8;                           // @28  // tag 8
  uint32_t u_tag9;                           // @32  // tag 9
  uint8_t bytes_tag10[16];                   // @36  // tag 10
  uint32_t u_tag11;                          // @52  // tag 11
  uint8_t bytes_tag12[1000];                 // @56  // tag 12
} pb_7725a8;

typedef struct pb_7725c0 {   // @0x7725c0  fields=8  size=4140 [struct]
  uint32_t u_tag1;                           // @0  // tag 1
  uint8_t bytes_tag2[16];                    // @4  // tag 2
  uint32_t u_tag3;                           // @20  // tag 3
  uint32_t u_tag4;                           // @24  // tag 4
  uint32_t u_tag5;                           // @28  // tag 5
  uint32_t u_tag6;                           // @32  // tag 6
  uint32_t u_tag7;                           // @36  // tag 7
  char str_tag8[4098];                       // @40  // tag 8
} pb_7725c0;

typedef struct pb_7725d8 {   // @0x7725d8  fields=8  size=44 [struct]
  uint32_t u_tag1;                           // @0  // tag 1
  uint8_t bytes_tag2[16];                    // @4  // tag 2
  uint32_t u_tag3;                           // @20  // tag 3
  uint32_t u_tag4;                           // @24  // tag 4
  uint32_t u_tag5;                           // @28  // tag 5
  uint32_t u_tag6;                           // @32  // tag 6
  uint32_t u_tag7;                           // @36  // tag 7
  uint8_t u_tag8;                            // @40  // tag 8
} pb_7725d8;

typedef struct pb_7725f0 {   // @0x7725f0  fields=6  size=36 [struct]
  uint32_t u_tag1;                           // @0  // tag 1
  uint32_t u_tag2;                           // @4  // tag 2
  uint32_t u_tag3;                           // @8  // tag 3
  uint32_t u_tag4;                           // @12  // tag 4
  uint32_t u_tag5;                           // @16  // tag 5
  uint8_t bytes_tag6[16];                    // @20  // tag 6
} pb_7725f0;

typedef struct pb_772608 {   // @0x772608  fields=5  size=14036 [struct]
  uint32_t u_tag1;                           // @0  // tag 1
  uint16_t    msg_tag2_count;                // @4
  pb_772560 msg_tag2[4];                     // @8  // tag 2 rep[4]
  uint16_t    msg_tag3_count;                // @5432
  pb_7725a8 msg_tag3[8];                     // @5436  // tag 3 rep[8]
  uint16_t    msg_tag4_count;                // @13884
  pb_7725f0 msg_tag4[4];                     // @13888  // tag 4 rep[4]
  uint32_t u_tag5;                           // @14032  // tag 5
} pb_772608;

typedef struct pb_772620 {   // @0x772620  fields=1  size=1 [struct]
  uint8_t u_tag1;                            // @0  // tag 1
} pb_772620;

typedef struct pb_772638 {   // @0x772638  fields=4  size=14032 [struct]
  uint32_t u_tag1;                           // @0  // tag 1
  uint16_t    msg_tag2_count;                // @4
  pb_772560 msg_tag2[4];                     // @8  // tag 2 rep[4]
  uint16_t    msg_tag3_count;                // @5432
  pb_7725a8 msg_tag3[8];                     // @5436  // tag 3 rep[8]
  uint16_t    msg_tag4_count;                // @13884
  pb_7725f0 msg_tag4[4];                     // @13888  // tag 4 rep[4]
} pb_772638;

typedef struct pb_772650 {   // @0x772650  fields=1  size=1 [struct]
  uint8_t u_tag1;                            // @0  // tag 1
} pb_772650;

typedef struct pb_772668 {   // @0x772668  fields=1  size=4 [struct]
  uint32_t u_tag1;                           // @0  // tag 1
} pb_772668;

typedef struct pb_772680 {   // @0x772680  fields=1  size=1 [struct]
  uint8_t u_tag1;                            // @0  // tag 1
} pb_772680;

typedef struct pb_7726b0 {   // @0x7726b0  fields=4  size=28 [struct]
  uint32_t u_tag1;                           // @0  // tag 1
  uint8_t bytes_tag2[16];                    // @4  // tag 2
  uint32_t u_tag3;                           // @20  // tag 3
  uint32_t u_tag4;                           // @24  // tag 4
} pb_7726b0;

typedef struct pb_7726c8 {   // @0x7726c8  fields=1  size=4 [struct]
  uint32_t u_tag1;                           // @0  // tag 1
} pb_7726c8;

typedef struct pb_7726e0 {   // @0x7726e0  fields=2  size=8 [struct]
  uint32_t u_tag1;                           // @0  // tag 1
  uint8_t u_tag2;                            // @4  // tag 2
} pb_7726e0;

typedef struct pb_7726f8 {   // @0x7726f8  fields=2  size=8 [struct]
  uint8_t u_tag1;                            // @0  // tag 1
  uint32_t u_tag2;                           // @4  // tag 2
} pb_7726f8;

typedef struct pb_772710 {   // @0x772710  fields=1  size=4 [struct]
  uint32_t u_tag1;                           // @0  // tag 1
} pb_772710;

typedef struct pb_772728 {   // @0x772728  fields=1  size=4 [struct]
  uint32_t u_tag1;                           // @0  // tag 1
} pb_772728;

typedef struct pb_772740 {   // @0x772740  fields=1  size=4 [struct]
  uint32_t u_tag1;                           // @0  // tag 1
} pb_772740;

typedef struct pb_772758 {   // @0x772758  fields=2  size=204 [struct]
  uint32_t u_tag1;                           // @0  // tag 1
  uint8_t bytes_tag2[200];                   // @4  // tag 2
} pb_772758;

typedef struct pb_772770 {   // @0x772770  fields=2  size=8 [struct]
  uint32_t u_tag1;                           // @0  // tag 1
  uint32_t u_tag2;                           // @4  // tag 2
} pb_772770;

typedef struct pb_772788 {   // @0x772788  fields=1  size=4 [struct]
  uint32_t u_tag1;                           // @0  // tag 1
} pb_772788;

typedef struct pb_7727a0 {   // @0x7727a0  fields=23  size=14040 [struct]
  uint8_t u_tag1;                            // @0  // tag 1
  uint8_t u_tag2;                            // @1  // tag 2
  uint16_t    which_pb_7727a0;               // @2
  union {
    pb_772608              msg_tag3;  // tag 3
    pb_772620              msg_tag4;  // tag 4
    pb_7725c0              msg_tag5;  // tag 5
    pb_7725d8              msg_tag6;  // tag 6
    pb_772638              msg_tag7;  // tag 7
    pb_772650              msg_tag8;  // tag 8
    pb_772578              msg_tag9;  // tag 9
    pb_772590              msg_tag10;  // tag 10
    pb_772668              msg_tag11;  // tag 11
    pb_772680              msg_tag12;  // tag 12
    pb_772530              msg_tag13;  // tag 13
    pb_7726c8              msg_tag14;  // tag 14
    pb_7726e0              msg_tag15;  // tag 15
    pb_7726b0              msg_tag16;  // tag 16
    pb_7726f8              msg_tag17;  // tag 17
    pb_772710              msg_tag18;  // tag 18
    pb_772728              msg_tag19;  // tag 19
    pb_772740              msg_tag20;  // tag 20
    pb_772758              msg_tag21;  // tag 21
    pb_772770              msg_tag22;  // tag 22
    pb_772788              msg_tag23;  // tag 23
  } u; // @4  // oneof @off 4, size 14036
} pb_7727a0;

typedef struct G2SettingPackage {   // @0x772980  fields=7  size=104 [seed]
  uint8_t commandId;                         // @0  // tag 1
  uint32_t magicRandom;                      // @4  // tag 2
  uint16_t    which_G2SettingPackage;        // @8
  union {
    DeviceReceiveInfoFromAPP deviceReceiveInfoFromApp;  // tag 3
    DeviceReceiveRequestFromAPP deviceReceiveRequestFromApp;  // tag 4
    DeviceSendInfoToAPP    deviceSendInfoToApp;  // tag 5
    Device_Respond_To_App  deviceRespondToApp;  // tag 6
    App_Respond_To_Device  appRespondToDevice;  // tag 7
  } u; // @12  // oneof @off 12, size 92
} G2SettingPackage;

typedef struct DeviceReceive_Brightness {   // @0x772998  fields=4  size=8 [prop]
  uint16_t    which_DeviceReceive_Brightness; // @0
  union {
    uint32_t               autoAdjust;  // tag 1
    uint32_t               brightnessLevel;  // tag 2
    uint32_t               leftCalibration;  // tag 3
    uint32_t               rightCalibration;  // tag 4
  } u; // @4  // oneof @off 4, size 4
} DeviceReceive_Brightness;

typedef struct DeviceReceive_Y_Coordinate {   // @0x7729b0  fields=1  size=4 [prop]
  uint32_t yCoordinateLevel;                 // @0  // tag 1
} DeviceReceive_Y_Coordinate;

typedef struct DeviceReceive_X_Coordinate {   // @0x7729c8  fields=1  size=4 [prop]
  uint32_t xCoordinateLevel;                 // @0  // tag 1
} DeviceReceive_X_Coordinate;

typedef struct DeviceReceive_Head_UP_Setting {   // @0x7729e0  fields=4  size=8 [prop]
  uint16_t    which_DeviceReceive_Head_UP_Setting; // @0
  union {
    uint32_t               headUpSwitch;  // tag 1
    uint32_t               headUpAngle;  // tag 2
    uint32_t               headUpCalibrationSwitch;  // tag 3
    uint32_t               headUpCalibration;  // tag 4
  } u; // @4  // oneof @off 4, size 4
} DeviceReceive_Head_UP_Setting;

typedef struct Wear_Detection_Setting {   // @0x7729f8  fields=1  size=4 [prop]
  uint32_t wearDetectionSwitch;              // @0  // tag 1
} Wear_Detection_Setting;

typedef struct DeviceReceive_Silent_Mode_Setting {   // @0x772a10  fields=1  size=4 [prop]
  uint32_t silentModeSwitch;                 // @0  // tag 1
} DeviceReceive_Silent_Mode_Setting;

typedef struct DeviceReceive_APP_PAGE {   // @0x772a28  fields=1  size=4 [prop]
  uint32_t appPage;                          // @0  // tag 1
} DeviceReceive_APP_PAGE;

typedef struct DeviceReceive_Advanced_Setting {   // @0x772a40  fields=1  size=4 [prop]
  uint32_t killAllFeature;                   // @0  // tag 1
} DeviceReceive_Advanced_Setting;

typedef struct DeviceReceiveInfoFromAPP {   // @0x772a58  fields=12  size=68 [prop]
  uint16_t    which_DeviceReceiveInfoFromAPP; // @0
  union {
    DeviceReceive_Brightness deviceReceiveBrightness;  // tag 1
    DeviceReceive_Y_Coordinate deviceReceiveYCoordinate;  // tag 2
    DeviceReceive_X_Coordinate deviceReceiveXCoordinate;  // tag 3
    DeviceReceive_Head_UP_Setting deviceReceiveHeadUpSetting;  // tag 4
    Wear_Detection_Setting deviceReceiveWearDetection;  // tag 5
    DeviceReceive_Silent_Mode_Setting deviceReceiveSilentMode;  // tag 6
    DeviceReceive_APP_PAGE deviceReceiveAppPage;  // tag 7
    DeviceReceive_Advanced_Setting deviceReceiveAdvancedSetting;  // tag 8
    APP_Send_Universe_Setting appSendUniverseSetting;  // tag 9
    APP_Send_Gesture_Control_List appSendGestureControlList;  // tag 10
    APP_Send_Dominant_Hand appSendDominantHand;  // tag 11
    APP_Control_Device     appControlDevice;  // tag 12
  } u; // @4  // oneof @off 4, size 64
} DeviceReceiveInfoFromAPP;

typedef struct DeviceReceiveRequestFromAPP {   // @0x772a70  fields=19  size=92 [prop]
  uint8_t settingInfoType;                   // @0  // tag 1
  uint32_t autoBrightnessLevel;              // @4  // tag 2
  uint32_t yCoordinateLevelRestored;         // @8  // tag 3
  uint32_t xCoordinateLevelRestored;         // @12  // tag 4
  uint8_t bytes_tag5[12];                    // @16  // tag 5
  uint8_t bytes_tag6[12];                    // @28  // tag 6
  uint32_t headUpSwitchRestored;             // @40  // tag 7
  uint32_t headUpAngleRestored;              // @44  // tag 8
  uint32_t headUpAngleCalibrationRestored;   // @48  // tag 9
  uint32_t wearDetectionSwitchRestored;      // @52  // tag 10
  uint32_t deviceRunningStatus;              // @56  // tag 11
  uint32_t battery;                          // @60  // tag 12
  uint32_t chargingStatus;                   // @64  // tag 13
  uint32_t silentModeSwitchRestored;         // @68  // tag 14
  uint32_t leftCalibrationRestored;          // @72  // tag 15
  uint32_t rightCalibrationRestored;         // @76  // tag 16
  uint32_t headUpRecalibrationSuccess;       // @80  // tag 17
  uint32_t autoBrightnessSwitchRestored;     // @84  // tag 18
  uint32_t unreadMessageCount;               // @88  // tag 19
} DeviceReceiveRequestFromAPP;

typedef struct DeviceSendInfoToAPP {   // @0x772a88  fields=2  size=8 [prop]
  uint16_t    which_DeviceSendInfoToAPP;     // @0
  union {
    uint32_t               currentRecalibrationStatus;  // tag 1
    uint32_t               silentModeSwitch;  // tag 2
  } u; // @4  // oneof @off 4, size 4
} DeviceSendInfoToAPP;

typedef struct APP_Send_Universe_Setting {   // @0x772ab8  fields=5  size=20 [prop]
  uint32_t unitFormat;                       // @0  // tag 1
  uint32_t distanceUnit;                     // @4  // tag 2
  uint32_t timeFormat;                       // @8  // tag 3
  uint32_t dateFormat;                       // @12  // tag 4
  uint32_t temperatureUnit;                  // @16  // tag 5
} APP_Send_Universe_Setting;

typedef struct APP_Send_Gesture_Control {   // @0x772ad0  fields=3  size=12 [prop]
  uint32_t screenOn;                         // @0  // tag 1
  uint32_t operationType;                    // @4  // tag 2
  uint8_t apptype;                           // @8  // tag 3
} APP_Send_Gesture_Control;

typedef struct APP_Send_Gesture_Control_List {   // @0x772ae8  fields=1  size=64 [prop]
  uint16_t    gestureControlList_count;      // @0
  APP_Send_Gesture_Control gestureControlList[5]; // @4  // tag 1 rep[5]
} APP_Send_Gesture_Control_List;

typedef struct APP_Send_Dominant_Hand {   // @0x772b00  fields=2  size=12 [prop]
  uint32_t dominantHand;                     // @0  // tag 1
  char ringMac[8];                           // @4  // tag 2
} APP_Send_Dominant_Hand;

typedef struct Device_Respond_To_App {   // @0x772b18  fields=2  size=8 [prop]
  uint32_t packageId;                        // @0  // tag 1
  uint8_t receiveFlag;                       // @4  // tag 2
} Device_Respond_To_App;

typedef struct App_Respond_To_Device {   // @0x772b30  fields=2  size=8 [prop]
  uint32_t packageId;                        // @0  // tag 1
  uint8_t receiveFlag;                       // @4  // tag 2
} App_Respond_To_Device;

typedef struct APP_Control_Device {   // @0x772b48  fields=1  size=4 [prop]
  uint32_t turnOnDevice;                     // @0  // tag 1
} APP_Control_Device;

typedef struct pb_772b90 {   // @0x772b90  fields=3  size=10 [struct]
  uint8_t u_tag1;                            // @0  // tag 1
  uint8_t u_tag2;                            // @1  // tag 2
  uint16_t    which_pb_772b90;               // @2
  union {
    pb_772bc0              msg_tag3;  // tag 3
  } u; // @4  // oneof @off 4, size 5
} pb_772b90;

typedef struct pb_772bc0 {   // @0x772bc0  fields=5  size=5 [struct]
  uint8_t u_tag1;                            // @0  // tag 1
  uint8_t u_tag2;                            // @1  // tag 2
  uint8_t u_tag3;                            // @2  // tag 3
  uint8_t u_tag4;                            // @3  // tag 4
  uint8_t u_tag5;                            // @4  // tag 5
} pb_772bc0;

typedef struct HealthDataPackage {   // @0x772c80  fields=6  size=796 [seed]
  uint8_t commandId;                         // @0  // tag 1
  uint8_t magicRandom;                       // @1  // tag 2
  uint16_t    which_HealthDataPackage;       // @2
  union {
    HealthSingleData       singleData;  // tag 3
    HealthMultData         multData;  // tag 4
    HealthSingleHighlight  singleHighlight;  // tag 5
    HealthMultHighlight    multHighlight;  // tag 6
  } u; // @4  // oneof @off 4, size 790
} HealthDataPackage;

typedef struct HealthSingleData {   // @0x772c98  fields=7  size=24 [prop]
  uint8_t dataType;                          // @0  // tag 1
  uint32_t goal;                             // @4  // tag 2
  uint32_t value;                            // @8  // tag 3
  uint32_t avgValue;                         // @12  // tag 4
  uint32_t duration;                         // @16  // tag 5
  uint8_t errorCode;                         // @20  // tag 6
  uint8_t trend;                             // @21  // tag 7
} HealthSingleData;

typedef struct HealthMultData {   // @0x772cb0  fields=3  size=200 [prop]
  uint8_t dataType;                          // @0  // tag 1
  uint16_t    dataSet_count;                 // @2
  HealthSingleData dataSet[8];               // @4  // tag 2 rep[8]
  uint8_t errorCode;                         // @196  // tag 3
} HealthMultData;

typedef struct HealthSingleHighlight {   // @0x772cc8  fields=3  size=262 [prop]
  uint8_t dataType;                          // @0  // tag 1
  char text[258];                            // @2  // tag 2
  uint8_t errorCode;                         // @260  // tag 3
} HealthSingleHighlight;

typedef struct HealthMultHighlight {   // @0x772ce0  fields=2  size=790 [prop]
  uint16_t    Highlight_count;               // @0
  HealthSingleHighlight Highlight[3];        // @2  // tag 1 rep[3]
  uint8_t errorCode;                         // @788  // tag 2
} HealthMultHighlight;

typedef struct pb_772fc8 {   // @0x772fc8  fields=1  size=1282 [struct]
  uint16_t    bytes_tag1_count;              // @0
  uint8_t bytes_tag1[32];                    // @2  // tag 1 rep[40]
} pb_772fc8;

typedef struct pb_772fe0 {   // @0x772fe0  fields=1  size=32 [struct]
  uint8_t bytes_tag1[32];                    // @0  // tag 1
} pb_772fe0;

typedef struct pb_772ff8 {   // @0x772ff8  fields=1  size=4 [struct]
  uint32_t u_tag1;                           // @0  // tag 1
} pb_772ff8;

typedef struct pb_773010 {   // @0x773010  fields=7  size=1288 [struct]
  uint8_t u_tag1;                            // @0  // tag 1
  uint8_t u_tag2;                            // @1  // tag 2
  uint16_t    which_pb_773010;               // @2
  union {
    uint32_t               u_tag3;  // tag 3
    pb_772ff8              msg_tag4;  // tag 4
    uint32_t               bytes_tag5;  // tag 5
    pb_772fc8              msg_tag6;  // tag 6
    pb_772fe0              msg_tag7;  // tag 7
  } u; // @4  // oneof @off 4, size 1282
} pb_773010;

typedef struct pb_7748a0 {   // @0x7748a0  fields=4  size=44 [struct]
  uint32_t u_tag1;                           // @0  // tag 1
  uint32_t u_tag2;                           // @4  // tag 2
  uint8_t bytes_tag3[32];                    // @8  // tag 3
  uint32_t u_tag4;                           // @40  // tag 4
} pb_7748a0;

typedef struct pb_7748b8 {   // @0x7748b8  fields=2  size=888 [struct]
  uint32_t u_tag1;                           // @0  // tag 1
  uint16_t    msg_tag2_count;                // @4
  pb_7748a0 msg_tag2[20];                    // @8  // tag 2 rep[20]
} pb_7748b8;

typedef struct pb_7748d0 {   // @0x7748d0  fields=1  size=4 [struct]
  uint32_t u_tag1;                           // @0  // tag 1
} pb_7748d0;

typedef struct pb_7748e8 {   // @0x7748e8  fields=4  size=892 [struct]
  uint8_t u_tag1;                            // @0  // tag 1
  uint8_t u_tag2;                            // @1  // tag 2
  uint16_t    which_pb_7748e8;               // @2
  union {
    pb_7748b8              msg_tag3;  // tag 3
    pb_7748d0              msg_tag4;  // tag 4
  } u; // @4  // oneof @off 4, size 888
} pb_7748e8;

typedef struct pb_7749c0 {   // @0x7749c0  fields=1  size=4 [struct]
  uint32_t u_tag1;                           // @0  // tag 1
} pb_7749c0;

typedef struct pb_7749d8 {   // @0x7749d8  fields=1  size=4 [struct]
  uint32_t u_tag1;                           // @0  // tag 1
} pb_7749d8;

typedef struct pb_7749f0 {   // @0x7749f0  fields=4  size=8 [struct]
  uint8_t u_tag1;                            // @0  // tag 1
  uint8_t u_tag2;                            // @1  // tag 2
  uint16_t    which_pb_7749f0;               // @2
  union {
    pb_7749c0              msg_tag3;  // tag 3
    pb_7749d8              msg_tag4;  // tag 4
  } u; // @4  // oneof @off 4, size 4
} pb_7749f0;

typedef struct pb_774a20 {   // @0x774a20  fields=4  size=1372 [struct]
  uint32_t u_tag1;                           // @0  // tag 1
  uint16_t    bytes_tag2_count;              // @4
  uint8_t bytes_tag2[64];                    // @6  // tag 2 rep[20]
  uint16_t    u_tag3_count;                  // @1286
  uint32_t u_tag3[20];                       // @1288  // tag 3 rep[20]
  uint8_t u_tag4;                            // @1368  // tag 4
} pb_774a20;

typedef struct pb_774a50 {   // @0x774a50  fields=4  size=76 [struct]
  uint8_t bytes_tag1[64];                    // @0  // tag 1
  uint8_t u_tag2;                            // @64  // tag 2
  uint32_t u_tag3;                           // @68  // tag 3
  uint32_t u_tag4;                           // @72  // tag 4
} pb_774a50;

typedef struct pb_774a68 {   // @0x774a68  fields=9  size=396 [struct]
  uint32_t u_tag1;                           // @0  // tag 1
  uint8_t bytes_tag2[64];                    // @4  // tag 2
  uint8_t bytes_tag3[64];                    // @68  // tag 3
  uint8_t bytes_tag4[64];                    // @132  // tag 4
  uint8_t bytes_tag5[64];                    // @196  // tag 5
  uint8_t bytes_tag6[64];                    // @260  // tag 6
  uint8_t bytes_tag7[64];                    // @324  // tag 7
  uint32_t u_tag8;                           // @388  // tag 8
  uint8_t u_tag9;                            // @392  // tag 9
} pb_774a68;

typedef struct pb_774a80 {   // @0x774a80  fields=6  size=8212 [struct]
  uint32_t u_tag1;                           // @0  // tag 1
  uint32_t u_tag2;                           // @4  // tag 2
  char str_tag3[8194];                       // @8  // tag 3
  uint8_t u_tag4;                            // @8202  // tag 4
  uint32_t u_tag5;                           // @8204  // tag 5
  uint32_t u_tag6;                           // @8208  // tag 6
} pb_774a80;

typedef struct pb_774a98 {   // @0x774a98  fields=7  size=4120 [struct]
  uint32_t u_tag1;                           // @0  // tag 1
  uint32_t u_tag2;                           // @4  // tag 2
  uint32_t u_tag3;                           // @8  // tag 3
  uint32_t u_tag4;                           // @12  // tag 4
  uint32_t u_tag5;                           // @16  // tag 5
  char str_tag6[4098];                       // @20  // tag 6
  uint8_t u_tag7;                            // @4118  // tag 7
} pb_774a98;

typedef struct pb_774ab0 {   // @0x774ab0  fields=3  size=72 [struct]
  uint8_t u_tag1;                            // @0  // tag 1
  uint8_t bytes_tag2[64];                    // @1  // tag 2
  uint32_t u_tag3;                           // @68  // tag 3
} pb_774ab0;

typedef struct pb_774ac8 {   // @0x774ac8  fields=1  size=4 [struct]
  uint32_t u_tag1;                           // @0  // tag 1
} pb_774ac8;

typedef struct pb_774ae0 {   // @0x774ae0  fields=1  size=4 [struct]
  uint32_t u_tag1;                           // @0  // tag 1
} pb_774ae0;

typedef struct pb_774af8 {   // @0x774af8  fields=10  size=8216 [struct]
  uint8_t u_tag1;                            // @0  // tag 1
  uint8_t u_tag2;                            // @1  // tag 2
  uint16_t    which_pb_774af8;               // @2
  union {
    pb_774ab0              msg_tag3;  // tag 3
    pb_774a20              msg_tag4;  // tag 4
    pb_774a68              msg_tag5;  // tag 5
    pb_774a80              msg_tag6;  // tag 6
    pb_774a98              msg_tag7;  // tag 7
    pb_774a50              msg_tag8;  // tag 8
    pb_774ac8              msg_tag9;  // tag 9
    pb_774ae0              msg_tag10;  // tag 10
  } u; // @4  // oneof @off 4, size 8212
} pb_774af8;

typedef struct NotificationDataPackage {   // @0x774c30  fields=6  size=74 [seed]
  uint8_t commandId;                         // @0  // tag 1
  uint8_t magicRandom;                       // @1  // tag 2
  uint16_t    which_NotificationDataPackage; // @2
  union {
    NotificationControl    ctrl;  // tag 3
    NotificationIOS        IOS;  // tag 4
    NotificationCommRsp    resp;  // tag 5
    NotificationWhitelistCtrl whitelistCtrl;  // tag 6
  } u; // @4  // oneof @off 4, size 70
} NotificationDataPackage;

typedef struct NotificationControl {   // @0x774c60  fields=5  size=5 [prop]
  uint8_t notifEnable;                       // @0  // tag 1
  uint8_t autoDispEnable;                    // @1  // tag 2
  uint8_t dispTime;                          // @2  // tag 3
  uint8_t errorCode;                         // @3  // tag 4
  uint8_t avoidDisturbEnable;                // @4  // tag 5
} NotificationControl;

typedef struct NotificationIOS {   // @0x774c90  fields=3  size=70 [prop]
  char appID[34];                            // @0  // tag 1
  char displayName[34];                      // @34  // tag 2
  uint8_t errorCode;                         // @68  // tag 3
} NotificationIOS;

typedef struct NotificationCommRsp {   // @0x774ca8  fields=2  size=2 [prop]
  uint8_t commandId;                         // @0  // tag 1
  uint8_t errorCode;                         // @1  // tag 2
} NotificationCommRsp;

typedef struct NotificationWhitelistCtrl {   // @0x774cc0  fields=2  size=2 [prop]
  uint8_t whitelistDisable;                  // @0  // tag 1
  uint8_t errorCode;                         // @1  // tag 2
} NotificationWhitelistCtrl;

typedef struct OnboardingDataPackage {   // @0x774eb8  fields=5  size=16 [seed]
  uint8_t commandId;                         // @0  // tag 1
  uint8_t magicRandom;                       // @1  // tag 2
  uint16_t    which_OnboardingDataPackage;   // @2
  union {
    OnboardingConfig       config;  // tag 3
    OnboardingHeartbeat    heartbeat;  // tag 4
    OnboardingEvent        event;  // tag 5
  } u; // @4  // oneof @off 4, size 12
} OnboardingDataPackage;

typedef struct OnboardingConfig {   // @0x774ed0  fields=2  size=2 [prop]
  uint8_t processId;                         // @0  // tag 1
  uint8_t errorCode;                         // @1  // tag 2
} OnboardingConfig;

typedef struct OnboardingHeartbeat {   // @0x774ee8  fields=1  size=1 [prop]
  uint8_t errorCode;                         // @0  // tag 1
} OnboardingHeartbeat;

typedef struct OnboardingEvent {   // @0x774f00  fields=3  size=12 [prop]
  uint8_t event;                             // @0  // tag 1
  uint32_t eventParam;                       // @4  // tag 2
  uint8_t errorCode;                         // @8  // tag 3
} OnboardingEvent;

typedef struct QuicklistDataPackage {   // @0x7761a8  fields=5  size=4664 [seed]
  uint8_t commandId;                         // @0  // tag 1
  uint8_t magicRandom;                       // @1  // tag 2
  uint16_t    which_QuicklistDataPackage;    // @2
  union {
    QuicklistItem          item;  // tag 3
    QuicklistMultItems     multItems;  // tag 4
    QuicklistEvent         event;  // tag 5
  } u; // @8  // oneof @off 8, size 4656
} QuicklistDataPackage;

typedef struct QuicklistItem {   // @0x7761c0  fields=7  size=232 [prop]
  uint32_t uid;                              // @0  // tag 1
  uint32_t index;                            // @4  // tag 2
  uint32_t isCompleted;                      // @8  // tag 3
  int64_t i_tag4;                            // @16  // tag 4
  char title[204];                           // @24  // tag 5
  uint8_t errorCode;                         // @228  // tag 6
  uint8_t tsType;                            // @229  // tag 7
} QuicklistItem;

typedef struct QuicklistMultItems {   // @0x7761d8  fields=4  size=4656 [prop]
  uint8_t dataType;                          // @0  // tag 1
  uint8_t totalCount;                        // @1  // tag 2
  uint16_t    items_count;                   // @2
  QuicklistItem items[20];                   // @8  // tag 3 rep[20]
  uint8_t errorCode;                         // @4648  // tag 4
} QuicklistMultItems;

typedef struct QuicklistEvent {   // @0x7761f0  fields=3  size=12 [prop]
  uint8_t event;                             // @0  // tag 1
  uint32_t uid;                              // @4  // tag 2
  uint8_t errorCode;                         // @8  // tag 3
} QuicklistEvent;

typedef struct pb_776268 {   // @0x776268  fields=4  size=64 [struct]
  uint8_t u_tag1;                            // @0  // tag 1
  uint8_t u_tag2;                            // @1  // tag 2
  uint16_t    which_pb_776268;               // @2
  union {
    pb_776298              msg_tag3;  // tag 3
    pb_7762b0              msg_tag4;  // tag 4
  } u; // @4  // oneof @off 4, size 60
} pb_776268;

typedef struct pb_776298 {   // @0x776298  fields=4  size=20 [struct]
  char str_tag1[8];                          // @0  // tag 1
  uint8_t u_tag2;                            // @8  // tag 2
  uint32_t u_tag3;                           // @12  // tag 3
  uint8_t u_tag4;                            // @16  // tag 4
} pb_776298;

typedef struct pb_7762b0 {   // @0x7762b0  fields=17  size=60 [struct]
  uint8_t u_tag1;                            // @0  // tag 1
  uint8_t u_tag2;                            // @1  // tag 2
  uint8_t u_tag3;                            // @2  // tag 3
  uint32_t u_tag4;                           // @4  // tag 4
  uint8_t u_tag5;                            // @8  // tag 5
  uint32_t u_tag6;                           // @12  // tag 6
  uint16_t u_tag7;                           // @16  // tag 7
  uint32_t u_tag8;                           // @20  // tag 8
  uint16_t u_tag9;                           // @24  // tag 9
  uint32_t u_tag10;                          // @28  // tag 10
  uint16_t u_tag11;                          // @32  // tag 11
  uint32_t u_tag12;                          // @36  // tag 12
  uint16_t u_tag13;                          // @40  // tag 13
  uint32_t u_tag14;                          // @44  // tag 14
  uint32_t u_tag15;                          // @48  // tag 15
  uint32_t u_tag16;                          // @52  // tag 16
  uint8_t u_tag17;                           // @56  // tag 17
} pb_7762b0;

typedef struct pb_7773c0 {   // @0x7773c0  fields=2  size=8 [struct]
  uint32_t u_tag1;                           // @0  // tag 1
  uint32_t u_tag2;                           // @4  // tag 2
} pb_7773c0;

typedef struct pb_7773d8 {   // @0x7773d8  fields=3  size=12 [struct]
  uint8_t u_tag1;                            // @0  // tag 1
  uint8_t u_tag2;                            // @1  // tag 2
  bool        has_msg_tag3;                  // @2
  pb_7773c0 msg_tag3;                        // @4  // tag 3
} pb_7773d8;

typedef struct TelepromptDataPackage {   // @0x777510  fields=13  size=3928 [seed]
  uint8_t commandId;                         // @0  // tag 1
  uint8_t magicRandom;                       // @1  // tag 2
  uint16_t    which_TelepromptDataPackage;   // @2
  union {
    TelepromptControl      ctrl;  // tag 3
    TelepromptFileList     fileList;  // tag 4
    TelepromptPageData     pageData;  // tag 5
    TelepromptAISync       aiSync;  // tag 6
    TelepromptStatusNotify statusNotify;  // tag 7
    pb_7775d0              fileListReq;  // tag 8
    TelepromptFileSelect   fileSelect;  // tag 9
    TelepromptPageDataRequest pageDataReq;  // tag 10
    TelepromptScrollSync   scrollSync;  // tag 11
    TelepromptCommResp     commResp;  // tag 12
    TelepromptHeartBeat    heartBeat;  // tag 13
  } u; // @4  // oneof @off 4, size 3922
} TelepromptDataPackage;

typedef struct TelepromptFileInfo {   // @0x777528  fields=2  size=196 [prop]
  char fileId[66];                           // @0  // tag 1
  char filename[130];                        // @66  // tag 2
} TelepromptFileInfo;

typedef struct TelepromptSetting {   // @0x777540  fields=9  size=36 [prop]
  uint8_t mode;                              // @0  // tag 1
  uint32_t startPageId;                      // @4  // tag 2
  uint32_t startLineId;                      // @8  // tag 3
  uint32_t totalPages;                       // @12  // tag 4
  uint32_t totalLines;                       // @16  // tag 5
  uint32_t displayWidth;                     // @20  // tag 6
  uint32_t scrollIntervalMs;                 // @24  // tag 7
  uint32_t countdownSeconds;                 // @28  // tag 8
  uint32_t useAudio;                         // @32  // tag 9
} TelepromptSetting;

typedef struct TelepromptControl {   // @0x777558  fields=2  size=40 [prop]
  uint8_t cmd;                               // @0  // tag 1
  bool        has_startSettings;             // @1
  TelepromptSetting startSettings;           // @4  // tag 2
} TelepromptControl;

typedef struct TelepromptFileList {   // @0x777570  fields=1  size=3922 [prop]
  uint16_t    files_count;                   // @0
  TelepromptFileInfo files[20];              // @2  // tag 1 rep[20]
} TelepromptFileList;

typedef struct TelepromptPageData {   // @0x777588  fields=3  size=1036 [prop]
  uint32_t pageId;                           // @0  // tag 1
  uint32_t pageLineCount;                    // @4  // tag 2
  char pageText[1026];                       // @8  // tag 3
} TelepromptPageData;

typedef struct TelepromptAISync {   // @0x7775a0  fields=3  size=12 [prop]
  uint32_t pageId;                           // @0  // tag 1
  uint32_t lineId;                           // @4  // tag 2
  uint32_t charId;                           // @8  // tag 3
} TelepromptAISync;

typedef struct TelepromptStatusNotify {   // @0x7775b8  fields=2  size=2 [prop]
  uint8_t cmd;                               // @0  // tag 1
  uint8_t errCode;                           // @1  // tag 2
} TelepromptStatusNotify;

typedef struct pb_7775d0 {   // @0x7775d0  fields=0  size=1 [struct]
} pb_7775d0;

typedef struct TelepromptFileSelect {   // @0x7775e8  fields=1  size=66 [prop]
  char fileId[66];                           // @0  // tag 1
} TelepromptFileSelect;

typedef struct TelepromptPageDataRequest {   // @0x777600  fields=1  size=4 [prop]
  uint32_t pageId;                           // @0  // tag 1
} TelepromptPageDataRequest;

typedef struct TelepromptCommResp {   // @0x777618  fields=1  size=1 [prop]
  uint8_t errCode;                           // @0  // tag 1
} TelepromptCommResp;

typedef struct TelepromptScrollSync {   // @0x777630  fields=3  size=12 [prop]
  uint32_t pageId;                           // @0  // tag 1
  uint32_t lineId;                           // @4  // tag 2
  uint32_t mode;                             // @8  // tag 3
} TelepromptScrollSync;

typedef struct TelepromptHeartBeat {   // @0x777648  fields=4  size=16 [prop]
  uint32_t appPageId;                        // @0  // tag 1
  uint32_t appLineId;                        // @4  // tag 2
  uint32_t osPageId;                         // @8  // tag 3
  uint32_t osLineId;                         // @12  // tag 4
} TelepromptHeartBeat;

typedef struct TerminalDataPackage {   // @0x777840  fields=25  size=2128 [seed]
  uint8_t commandId;                         // @0  // tag 1
  uint8_t magicRandom;                       // @1  // tag 2
  uint16_t    which_TerminalDataPackage;     // @2
  union {
    TerminalModeSync       modeSync;  // tag 3
    TerminalHostStatusMsg  hostStatus;  // tag 4
    TerminalAsrResult      asrResult;  // tag 5
    TerminalSessionStatusMsg sessionStatus;  // tag 6
    TerminalAgentContent   agentContent;  // tag 7
    TerminalQuery          query;  // tag 8
    TerminalStatusReply    statusReply;  // tag 9
    TerminalVoiceInput     voiceInput;  // tag 10
    TerminalQueryReply     queryReply;  // tag 11
    TerminalAgentInterrupt agentInterrupt;  // tag 12
    TerminalCommResp       commResp;  // tag 13
    pb_777a98              heartBeat;  // tag 14
    TerminalErrorMsg       errorMsg;  // tag 15
    TerminalSessionList    sessionList;  // tag 16
    TerminalSessionSwitchResult sessionSwitchResult;  // tag 17
    TerminalSessionSwitchRequest sessionSwitchRequest;  // tag 18
    TerminalNewSessionRequest newSessionRequest;  // tag 19
    TerminalDisplayState   displayStateNotify;  // tag 20
    TerminalSessionChange  sessionChange;  // tag 21
    pb_777a20              newSessionCancel;  // tag 22
    TerminalNewSessionResult newSessionResult;  // tag 23
    TerminalListFocus      listFocus;  // tag 24
    TerminalOverlayFocus   overlayFocus;  // tag 25
  } u; // @4  // oneof @off 4, size 2124
} TerminalDataPackage;

typedef struct TerminalModeSync {   // @0x777858  fields=2  size=2 [prop]
  uint8_t targetMode;                        // @0  // tag 1
  uint8_t errCode;                           // @1  // tag 2
} TerminalModeSync;

typedef struct TerminalHostStatusMsg {   // @0x777870  fields=2  size=2 [prop]
  uint8_t hostStatus;                        // @0  // tag 1
  uint8_t errCode;                           // @1  // tag 2
} TerminalHostStatusMsg;

typedef struct TerminalAsrResult {   // @0x777888  fields=3  size=516 [prop]
  char text[514];                            // @0  // tag 1
  uint8_t sentenceFinal;                     // @514  // tag 2
  uint8_t allFinal;                          // @515  // tag 3
} TerminalAsrResult;

typedef struct TerminalSessionStatusMsg {   // @0x7778a0  fields=2  size=8 [prop]
  uint8_t status;                            // @0  // tag 1
  uint32_t sessionId;                        // @4  // tag 2
} TerminalSessionStatusMsg;

typedef struct TerminalAgentContent {   // @0x7778b8  fields=6  size=532 [prop]
  uint8_t style;                             // @0  // tag 1
  char text[514];                            // @2  // tag 2
  uint8_t contentOp;                         // @516  // tag 3
  uint32_t contentId;                        // @520  // tag 4
  uint8_t event;                             // @524  // tag 5
  uint32_t sessionId;                        // @528  // tag 6
} TerminalAgentContent;

typedef struct TerminalQuery {   // @0x7778d0  fields=4  size=2124 [prop]
  uint32_t queryId;                          // @0  // tag 1
  char question[1026];                       // @4  // tag 2
  uint16_t    options_count;                 // @1030
  TerminalQueryOption options[8];            // @1032  // tag 3 rep[8]
  uint32_t sessionId;                        // @2120  // tag 4
} TerminalQuery;

typedef struct TerminalQueryOption {   // @0x7778e8  fields=2  size=136 [prop]
  uint32_t optionId;                         // @0  // tag 1
  char optionText[130];                      // @4  // tag 2
} TerminalQueryOption;

typedef struct TerminalErrorMsg {   // @0x777900  fields=1  size=1 [prop]
  uint8_t errCode;                           // @0  // tag 1
} TerminalErrorMsg;

typedef struct TerminalSessionList {   // @0x777918  fields=3  size=1372 [prop]
  uint32_t hostId;                           // @0  // tag 1
  uint32_t currentSessionId;                 // @4  // tag 2
  uint16_t    sessions_count;                // @8
  TerminalSessionListItem sessions[10];      // @12  // tag 3 rep[10]
} TerminalSessionList;

typedef struct TerminalSessionListItem {   // @0x777930  fields=3  size=136 [prop]
  uint32_t sessionId;                        // @0  // tag 1
  char title[130];                           // @4  // tag 2
  uint8_t sessionStatus;                     // @134  // tag 3
} TerminalSessionListItem;

typedef struct TerminalSessionSwitchResult {   // @0x777948  fields=1  size=1 [prop]
  uint8_t result;                            // @0  // tag 1
} TerminalSessionSwitchResult;

typedef struct TerminalNewSessionResult {   // @0x777960  fields=1  size=1 [prop]
  uint8_t result;                            // @0  // tag 1
} TerminalNewSessionResult;

typedef struct TerminalSessionChange {   // @0x777978  fields=1  size=4 [prop]
  uint32_t sessionId;                        // @0  // tag 1
} TerminalSessionChange;

typedef struct TerminalStatusReply {   // @0x777990  fields=2  size=2 [prop]
  uint8_t currentMode;                       // @0  // tag 1
  uint8_t errCode;                           // @1  // tag 2
} TerminalStatusReply;

typedef struct TerminalVoiceInput {   // @0x7779a8  fields=1  size=1 [prop]
  uint8_t cmd;                               // @0  // tag 1
} TerminalVoiceInput;

typedef struct TerminalQueryReply {   // @0x7779c0  fields=2  size=8 [prop]
  uint32_t queryId;                          // @0  // tag 1
  uint32_t optionId;                         // @4  // tag 2
} TerminalQueryReply;

typedef struct TerminalAgentInterrupt {   // @0x7779d8  fields=1  size=1 [prop]
  uint8_t dummyField;                        // @0  // tag 1
} TerminalAgentInterrupt;

typedef struct TerminalSessionSwitchRequest {   // @0x7779f0  fields=2  size=8 [prop]
  uint32_t sessionId;                        // @0  // tag 1
  uint32_t hostId;                           // @4  // tag 2
} TerminalSessionSwitchRequest;

typedef struct TerminalNewSessionRequest {   // @0x777a08  fields=1  size=4 [prop]
  uint32_t hostId;                           // @0  // tag 1
} TerminalNewSessionRequest;

typedef struct pb_777a20 {   // @0x777a20  fields=0  size=1 [struct]
} pb_777a20;

typedef struct TerminalDisplayState {   // @0x777a38  fields=3  size=12 [prop]
  uint8_t state;                             // @0  // tag 1
  uint32_t sessionId;                        // @4  // tag 2
  uint8_t overlay;                           // @8  // tag 3
} TerminalDisplayState;

typedef struct TerminalListFocus {   // @0x777a50  fields=1  size=4 [prop]
  uint32_t focusedIndex;                     // @0  // tag 1
} TerminalListFocus;

typedef struct TerminalOverlayFocus {   // @0x777a68  fields=2  size=8 [prop]
  uint8_t overlay;                           // @0  // tag 1
  uint32_t focusedIndex;                     // @4  // tag 2
} TerminalOverlayFocus;

typedef struct TerminalCommResp {   // @0x777a80  fields=1  size=1 [prop]
  uint8_t errCode;                           // @0  // tag 1
} TerminalCommResp;

typedef struct pb_777a98 {   // @0x777a98  fields=0  size=1 [struct]
} pb_777a98;

typedef struct TranslateDataPackage {   // @0x777fc0  fields=8  size=2132 [seed]
  uint8_t commandId;                         // @0  // tag 1
  uint8_t magicRandom;                       // @1  // tag 2
  uint16_t    which_TranslateDataPackage;    // @2
  union {
    TranslateControl       ctrl;  // tag 3
    TranslateResult        result;  // tag 4
    TranslateNotify        notify;  // tag 5
    TranslateModeSwitch    modeSwitch;  // tag 6
    TranslateResp          resp;  // tag 7
    pb_778068              heartbeat;  // tag 8
  } u; // @4  // oneof @off 4, size 2128
} TranslateDataPackage;

typedef struct TranslateNotify {   // @0x777fd8  fields=2  size=2 [prop]
  uint8_t cmd;                               // @0  // tag 1
  uint8_t errorCode;                         // @1  // tag 2
} TranslateNotify;

typedef struct TranslateModeSwitch {   // @0x777ff0  fields=1  size=4 [prop]
  uint32_t mode;                             // @0  // tag 1
} TranslateModeSwitch;

typedef struct TranslateResp {   // @0x778008  fields=1  size=1 [prop]
  uint8_t errorCode;                         // @0  // tag 1
} TranslateResp;

typedef struct TranslateControl {   // @0x778038  fields=4  size=20 [prop]
  uint8_t cmd;                               // @0  // tag 1
  char languagePair[10];                     // @2  // tag 2
  uint32_t useAudio;                         // @12  // tag 3
  uint8_t errorCode;                         // @16  // tag 4
} TranslateControl;

typedef struct TranslateResult {   // @0x778050  fields=5  size=2128 [prop]
  char srcText[1026];                        // @0  // tag 1
  char dstText[1026];                        // @1026  // tag 2
  uint8_t errorCode;                         // @2052  // tag 3
  uint32_t endFlag;                          // @2056  // tag 4
  char speaker[66];                          // @2060  // tag 5
} TranslateResult;

typedef struct pb_778068 {   // @0x778068  fields=0  size=1 [struct]
} pb_778068;
