/* fw 2.2.4.34 mainapp — reverse-engineered struct layouts for hot-loaded payloads.
 * Pairs with fw_2.2.4.34_syms.h (named entry points). All offsets verified this session
 * (stock LVGL v9.3 + Even Realities display framework). Keep in sync with the Ghidra DB. */
#pragma once
#include <stdint.h>

/* ---- LVGL v9.3 image descriptor (THIS build: lv_image_t has an extra word at obj+0x30) ---- */
typedef struct lv_image_dsc {
    uint8_t  magic;        /* 0x19 = LV_IMAGE_HEADER_MAGIC          */
    uint8_t  cf;           /* color format: 0x06 = L8 (8bpp gray)   */
    uint16_t flags;
    uint16_t w;
    uint16_t h;
    uint16_t stride;       /* bytes per row (= w for L8)            */
    uint16_t reserved;
    uint32_t data_size;    /* w*h for L8                            */
    const uint8_t* data;   /* pixel buffer (dcache_clean before use)*/
} lv_image_dsc_t;          /* 20 bytes */

typedef struct lv_area { int32_t x1, y1, x2, y2; } lv_area_t;  /* inclusive */

/* ---- display-app framework ---- */
typedef struct app_entry {     /* RAM registry @ 0x20066210, stride 16, count @ *0x20074410 */
    uint32_t app_id;
    uint32_t dataCb;           /* fn ptr | thumb: dataCb(uint evt, void* data, uint len, uint arg) */
    uint32_t uiCb;             /* fn ptr | thumb: uiCb(uint event, uint a2, uint a3, void* container) */
    uint32_t cfg;              /* -> app_cfg_t                       */
} app_entry_t;

typedef struct app_cfg {       /* page config; page_manager copies 0x1c bytes then fills a node */
    uint32_t page_id;          /* +0x00: nonzero, == app_id          */
    uint32_t root;             /* +0x04: root lv_obj (uiCb sets this on STARTUP; MANDATORY)   */
    uint8_t  align;            /* +0x08: overlay slide-in dir (base: ignore)                 */
    uint8_t  _pad9, _padA;
    uint8_t  type;             /* +0x0b: 0=base(visible container), 1=overlay(transparent)   */
    uint32_t width;            /* +0x0c: default 300 if 0 (use 576)  */
    uint32_t height;           /* +0x10: default 300 if 0 (use 288)  */
    uint16_t f14;              /* +0x14: default 0x32 if 0           */
    uint8_t  f16;              /* +0x16: default 100 if 0            */
    uint8_t  visible_base;     /* +0x17: MUST be 1 for a base page, else root gets HIDDEN     */
    uint8_t  rest[8];          /* +0x18..0x1f                        */
} app_cfg_t;

/* ---- inter-lens peer message (built by send_data_to_peer/post_app_command) ---- */
/* payload header packed before the data: [0]=msg_class [1]=msg_id [2:3]=app_id
 * [4:5]=event_type/flags [6:7]=len, then len bytes of data. class 4/id 0xc = SEND_DATA_TO_PEER;
 * class 3/id 7 = input events; class 5/id 0xe/0xf = startup sync-control. */
typedef struct peer_pkt_hdr { uint8_t msg_class, msg_id; uint16_t app_id, event_type, len; } peer_pkt_hdr_t;

/* ---- display-device power message (posted to *(*0x20074428_ctx? see syms) power queue) ---- */
/* 0x24-byte zeroed msg; word0 = cmd {0,1,3 = power up seq; 2,5 = power down}; +0x20 = fsm flag */

/* ---- key RAM globals (deref where noted) ---- */
#define G_UI_REGISTRY      0x20066210u  /* app_entry_t[]              */
#define G_UI_COUNT         0x20074410u  /* u32                        */
#define G_PAGE_MGR_PP      0x2007440cu  /* -> page_mgr (mgr+0x18=576x288 root, +0x1c=base, +0x20=overlay) */
#define G_BASE_APPID       0x20074414u  /* u32                        */
#define G_STARTUP_STATE    0x20074418u  /* u8                         */
#define G_OVERLAY_APPID    0x2007441cu  /* u32                        */
#define G_FG_STATE         0x20074e00u  /* u8: 0=idle/dashboard (display_startup opens fresh only when 0) */
#define G_PANEL_PWR        0x20074428u  /* u8: 0=off                  */
#define G_IMU_HEADDOWN     0x20074eafu  /* u8: 0 blocks idle power-off */
#define G_PANEL_CANVAS_PP  0x20074464u  /* -> 640x480 4bpp panel canvas (=0x20094400, stride 320) */
#define G_CLEAR_CB         0x20074468u  /* pre-compose clear cb (restore 0x004d508d if zeroed)    */
#define G_LV_DISPLAY_PP    0x200745d0u  /* -> lv_display_t (flush_cb @ +0x28)                     */
#define G_LV_DRAWBUF_PP    0x200745ccu  /* -> lv_draw_buf_t (L8 576x288 render target; data @ +0x10) */
