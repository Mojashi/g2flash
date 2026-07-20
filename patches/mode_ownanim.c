/*
 * mode_ownanim.c — clean own-mode STEREO animation with L/R barrier sync, for the G2 CFW.
 * Rewritten 2026-07-19 to bake in everything we learned this session.
 *
 * ARCHITECTURE (hard-won facts — see memory reference_g2_interlens_transmit / _crosslens_sync):
 *  - The two lenses are separate MCUs. A hot-loaded payload written to the L device is executed on
 *    L AND relayed to R; a write to the R device hits only R. => To run on BOTH lenses, LOAD/DRIVE
 *    VIA arm:"L" ONLY. Never load via both arms (that double-loads R and frees its live buffer ->
 *    hardfault). Reads still disambiguate by side: 'k'->R replies R's frame, 'l'->L relays L's.
 *  - Each lens runs its own instance and self-ticks its own frame counter -> they DRIFT. We sync
 *    them with a wait-for-ack peer BARRIER: R(master) draws N, sends N to L, waits for L's ack, then
 *    advances. Bounds L/R skew to <=1 frame (imperceptible, ~= native). Enable with 'm'.
 *  - STEREO/3D is pure APP-SIDE DISPARITY: both lenses draw the SAME barrier-synced frame N; each
 *    computes its own eye view (horizontal shift from lens_side()) locally. No firmware stereo mode.
 *    Toggle with 'd'. Objects at different disparities read at different depths.
 *  - The SLAVE must DRAW from the display TICK, never from the BLE-RX callback (a 165 KB draw in the
 *    peer-RX context reboots the lens). dataCb only records frame N + acks; the tick draws it.
 *  - Register the app_entry ONCE (a repeated 'g' must not append a duplicate -> reboot). Foreground
 *    base app needs cfg[0x17]=1 (visible_base) and fg-state==0 to open + hide the dashboard.
 *  - Always dcache_clean the L8 buffer after drawing or the GPU/DMA blit reads stale bytes (garbled).
 *
 *  - HOST-DRIVEN ROTATION ('F'/'A'): the barrier doesn't care WHAT number c->frame advances to next
 *    (see next_frame()) -- only that master pushes it and slave acks it. So a host slider/IMU-derived
 *    angle just overwrites what the MASTER advances to; the EXISTING barrier delivers it to the slave
 *    with no new peer protocol. 'F'+u32LE sets the target angle + enables manual mode (send to the
 *    master, i.e. via arm:"L" same as everything else); 'A' returns to auto-rotate.
 *
 * DRIVE (all via arm:"L"):  'g' open both · 'm'/'n' barrier sync on/off · 'd' stereo on/off ·
 *   'i' IMU head-tracking toggle (on-device accel → rotation, bypasses BLE, tick-rate) ·
 *   'F'+u32LE set rotation frame/angle (host slider/IMU drive) · 'A' back to auto-rotate ·
 *   'k' report R frame · 'l' report L frame (peer relay) · 's' capture this lens (whichever instance
 *   the arm reaches; L relays via R) · 'S' capture L ONLY (isolates the peer-relay path, HW-verified
 *   2026-07-19 — the received image is stamped SIDE:2) · 'q' close.
 */
#include <stdint.h>
#include "font8.h"

typedef struct rt_api {
    uint32_t abi_version; void* (*mem_alloc)(uint32_t); void (*mem_free)(void*);
    int (*send)(int,void*,int); void (*reply)(void*,int); int (*lens_side)(void);
    uint32_t (*tick_ms)(void); uint8_t* (*fb_canvas)(void); void (*present)(void);
    void (*dcache_clean)(void*,uint32_t); uint32_t fb_w, fb_h;
} rt_api_t;
typedef struct mode_vtable {
    void (*init)(rt_api_t*); void (*tick)(uint32_t); void (*on_input)(void*);
    void (*on_data)(uint8_t*,int); void (*exit)(void);
} mode_vtable_t;

/* ---- firmware entry points (call by absolute Thumb address; see patches/fw_2.2.4.34_syms.h) ---- */
#define FW_DISPLAY_STARTUP   0x00443905u
#define FW_DISPLAY_CLOSE     0x00443ae5u
#define FW_WAKE_FSM          0x004720d1u
#define FW_WAKE_BARE         0x00471ee3u
#define FW_LV_IMAGE_CREATE   0x004b0ee9u
#define FW_LV_IMAGE_SETSRC   0x004b0f01u
#define FW_LV_OBJ_SET_POS    0x0043f03bu
#define FW_LV_OBJ_INVAL      0x004405f7u
/* inter-lens peer comms (docs/peer_comms_map.md). We use send_data_to_peer both ways (proven to
 * carry EVT_* for our appID in either direction). The type-correct alternative is kept for reference: */
#define FW_SEND_DATA_TO_PEER 0x00464c29u  /* type4/op0xc: send_data_to_peer(appID,data,len,ctx,evt); evt->dataCb cmd */
#define FW_SEND_APPCMD_PEER  0x004644c5u  /* type1/op9 bidir: send_app_command_to_peer(appID,data,len,ctx) [ref] */
#define FW_HUB_OPEN          0x004bf411u  /* HUB_Open(uint role): role=2 enables gyro+compass fusion */
#define FW_HUB_CLOSE         0x004bf483u  /* HUB_Close(uint role) */
#define FW_HUB_PARAMCONFIG   0x004bf4f5u  /* HUB_ParameterConfig(byte cfg_type, uint32_t* params) */
#define FW_START_COMPASS     0x00564e4du  /* StartIMUCompassFunc(): HUB_Open(2)+HUB_ParameterConfig(2,{1000,5}) — the official gyro+compass enable */
/* RE'd (2026-07-20): the IMU chip's sensor enable register is written by FUN_00529c44(driver_ctx,
 * mode, &config). config bytes: [0]=accel, [1]=gyro, [2]=mag (each 0/1). mode=0 → chip reg 0x18,
 * mode=1 → reg 0x58. The init (FUN_004bbd66) only enables accel ({1,0,0}). To get gyro+fusion,
 * we must call FUN_00529c44 with {1,1,1} (or {1,1,0}) from our payload. driver_ctx = *0x4bbeb8. */
#define FW_IMU_SET_ENABLE    0x00529c45u  /* FUN_00529c44(driver_ctx, mode, &config) — IMU chip sensor enable */
#define IMU_DRIVER_CTX_PTR   0x004bbeb8u  /* ptr to IMU driver context (runtime-init'd SRAM) */
/* NOTE: DispStartBlockingEn/Cancel (0x45c024/0x45c1f0) were investigated as a possible native
 * delta->0 present-barrier and RULED OUT (2026-07-19, traced sched_exec_display_startup 0x45c3dc):
 * that gate only defers opcode==1 (app-LAUNCH) messages, never opcode==3 (reflash/present) — so it
 * cannot synchronize an ongoing animation's presents. The wait-for-ack barrier below (delta<=1,
 * HW-proven) is the best known mechanism for this. See reference_g2_crosslens_sync memory. */

/* peer event types (become the dataCb 'cmd' arg) */
#define EVT_SYNC   0x41u  /* MASTER->SLAVE: render frame N */
#define EVT_ACK    0x42u  /* SLAVE->MASTER: I have N (barrier release) */
#define EVT_LCHUNK 0x43u  /* SLAVE->MASTER: a QOI screenshot fragment; R re-emits to phone */
#define EVT_LFRAME 0x44u  /* SLAVE->MASTER: report my frame counter (for the 'l' measurement) */

#define SYNC_TIMEOUT_MS 200u  /* master advances even if an ack is lost (never stalls) */
#define SYNC_IDLE_MS    600u  /* slave resumes self-tick if the master goes quiet */

/* ---- RAM globals / registry (see reference_g2_display_arch) ---- */
#define REG_BASE      0x20066210u
#define REG_COUNT     0x20074410u
#define FG_STATE      0x20074e00u
#define IMU_HEADDOWN  0x20074eafu
#define PANEL_PWR     0x20074428u
#define MODE_CTX_SLOT 0x20053404u
#define OUR_APPID     0x0077u

#define IW 576u
#define IH 288u
#define SCALE 3u
#define GLYPH_W (8u*SCALE)

typedef void  (*voidfn)(void);
typedef int   (*startupfn)(unsigned,void*,unsigned);
typedef void* (*create_fn)(void*);
typedef void  (*setsrc_fn)(void*,const void*);
typedef void  (*setxy_fn)(void*,int32_t,int32_t);
typedef void  (*obj1_fn)(void*);
typedef int   (*peer_fn)(unsigned appid, void* data, unsigned len, void* ctx, unsigned evt);

mode_vtable_t* payload_entry(rt_api_t* api);
__attribute__((naked, used)) void _start(void){ __asm__ volatile ("b.w payload_entry"); }

typedef struct dsc { uint8_t magic, cf; uint16_t flags; uint16_t w, h, stride, resv;
                     uint32_t data_size; const uint8_t* data; } dsc_t;
typedef struct ctx {
    mode_vtable_t vt; rt_api_t* api; uint8_t cfg[32];
    volatile uint32_t* entry; void* img; uint8_t* buf; dsc_t dsc;
    uint32_t frame;         /* the animation frame (barrier-synced across lenses) */
    uint8_t  started;
    uint8_t  sync_on;       /* barrier enabled ('m') */
    uint8_t  waiting;       /* master: awaiting the slave's ack */
    uint8_t  dirty;         /* slave: a new frame arrived, draw it on the next tick */
    uint8_t  stereo;        /* per-eye disparity enabled ('d') */
    uint8_t  manual;        /* MASTER: host is driving rotation directly ('F'), not auto-rotate */
    uint8_t  imu_on;        /* use on-device IMU gyro to drive rotation (tick-rate, matrix mode) */
    uint8_t  imu_angY, imu_angX;  /* SLAVE: angles received from master's EVT_SYNC (legacy) */
    uint8_t  last_angY, last_angX; /* MASTER: last computed (legacy) */
    int32_t  yaw_accum;
    int32_t  pitch_accum;
    int32_t  rot[9];        /* 3×3 rotation matrix, Q14 (16384 = 1.0). No gimbal lock. */
    uint8_t  ortho_cnt;     /* frame counter for periodic re-orthogonalization */
    uint32_t manual_frame;  /* MASTER: latest host-set frame/angle value */
    uint32_t wait_start, last_sync_ms;
} ctx_t;
/* Wherever the barrier/standalone path would normally auto-advance c->frame, it calls this instead:
 * in manual mode it snaps to the host's latest slider value (picked up within one barrier round-trip,
 * ~imperceptible); otherwise it's the same +1 auto-rotate as before. This reuses the EXISTING proven
 * peer-sync barrier verbatim -- driving rotation from a host slider needed no new peer protocol,
 * just a different answer to "what's the next frame". */
static uint32_t next_frame(ctx_t* c){ return c->manual ? c->manual_frame : c->frame+1u; }
static inline ctx_t* ctx_get(void){ return *(ctx_t* volatile*)MODE_CTX_SLOT; }
static void mark(rt_api_t* a, uint8_t s, uint32_t v){ uint8_t r[6]={0xA7,0x4e,s,(uint8_t)v,(uint8_t)(v>>8),(uint8_t)(v>>16)}; a->reply(r,6); }

/* L-capture: screenshot.c streams QOI fragments through SS_SEND_HOOK. On R send straight to the
 * phone; on L forward each over the peer link (EVT_LCHUNK) to R, which re-emits on sid 0x7d. */
static void ss_relay_send(void* frag, int len);
#define SS_SEND_HOOK(ptr,len) ss_relay_send((ptr),(len))
#include "screenshot.c"   /* build -DSS_FB_L8 : capture the composited L8 panel of THIS lens */
static void ss_relay_send(void* frag, int len){
    if(SS_FW_SIDE()==1) SS_FW_SEND(1, SS_SID, frag, len);                                 /* R -> phone */
    else ((peer_fn)FW_SEND_DATA_TO_PEER)(OUR_APPID, frag, (unsigned)len, 0, EVT_LCHUNK);  /* L -> R relay */
}

/* ---------------- pixel + text drawing (8bpp L8 buffer, 3x bitmap font) ---------------- */
static inline void px(uint8_t* b,int x,int y,uint8_t v){ if((unsigned)x<IW&&(unsigned)y<IH) b[y*IW+x]=v; }
static void fillrect(uint8_t* b,int x0,int y0,int w,int h,uint8_t v){ for(int y=y0;y<y0+h;y++) for(int x=x0;x<x0+w;x++) px(b,x,y,v); }
static void rect_outline(uint8_t* b,int x,int y,int w,int h,int t,uint8_t v){ fillrect(b,x,y,w,t,v); fillrect(b,x,y+h-t,w,t,v); fillrect(b,x,y,t,h,v); fillrect(b,x+w-t,y,t,h,v); }
static void draw_char(uint8_t* b,int ox,int oy,char ch,uint8_t v){
    unsigned i=(unsigned)(uint8_t)ch; if(i<0x20u||i>0x7Fu) i=0x20u; const uint8_t* g=FONT8[i-0x20u];
    for(int r=0;r<8;r++){ uint8_t rw=g[r]; for(int c=0;c<8;c++) if(rw&(0x80u>>c))
        for(uint32_t dy=0;dy<SCALE;dy++) for(uint32_t dx=0;dx<SCALE;dx++) px(b,ox+c*(int)SCALE+(int)dx,oy+r*(int)SCALE+(int)dy,v); }
}
static void draw_text(uint8_t* b,int x,int y,const char* s,uint8_t v){ for(;*s;s++){ draw_char(b,x,y,*s,v); x+=GLYPH_W+2; } }
static int itoa_r(uint32_t t,char* d){ char tmp[12]; int k=0; if(t==0) tmp[k++]='0'; while(t){ tmp[k++]=(char)('0'+t%10); t/=10; } int n=0; while(k) d[n++]=tmp[--k]; d[n]=0; return n; }
/* Integer Bresenham (Wikipedia's classic 2-error-term form) -- no float, no division per step. */
static void draw_line(uint8_t* b,int x0,int y0,int x1,int y1,uint8_t v){
    int dx = (x1>x0) ? (x1-x0) : (x0-x1); int sx = (x0<x1) ? 1 : -1;
    int dy = (y1>y0) ? (y0-y1) : (y1-y0); int sy = (y0<y1) ? 1 : -1;   /* dy stored negated */
    int err = dx+dy;
    for(;;){
        px(b,x0,y0,v);
        if(x0==x1 && y0==y1) break;
        int e2=2*err;
        if(e2>=dy){ err+=dy; x0+=sx; }
        if(e2<=dx){ err+=dx; y0+=sy; }
    }
}

/* ---- onboard 3D: a rotating wireframe icosahedron, real per-vertex stereo parallax ----
 * Model + trig are baked as compile-time CONST DATA (like FONT8) -- no float, no libm, no malloc:
 * a payload here can only branch/call intra-.text and reference PC-relative rodata (build.py's PIC
 * contract), so any "3D model" MUST be plain data tables, and rotation MUST be fixed-point using a
 * precomputed sin table (float sin()/cos() would need libm, which is an external call and rejected).
 * Verified hardware SDIV is emitted for plain '/' on this target (no soft-div libcall), so the
 * perspective divide below is a single instruction, not a runtime library dependency.
 *
 * ICO_V/ICO_E were generated + SELF-VERIFIED in Python (not hand-transcribed): 12 vertices at an
 * equal radius from the golden-ratio construction, edges = the 30 (of 66 possible) vertex pairs at
 * the globally-shortest pairwise distance (a regular icosahedron's edge set, confirmed by count).
 */
static const int8_t ICO_V[12][3] = {
    {-123,0,-76},{-123,0,76},{-76,-123,0},{-76,123,0},{0,-76,-123},{0,-76,123},
    {0,76,-123},{0,76,123},{76,-123,0},{76,123,0},{123,0,-76},{123,0,76},
};
static const uint8_t ICO_E[30][2] = {
    {0,1},{0,2},{0,3},{0,4},{0,6},{1,2},{1,3},{1,5},{1,7},{2,4},
    {2,5},{2,8},{3,6},{3,7},{3,9},{4,6},{4,8},{4,10},{5,7},{5,8},
    {5,11},{6,9},{6,10},{7,9},{7,11},{8,10},{8,11},{9,10},{9,11},{10,11},
};
/* Q8 sine, one full turn = 256 steps (values -256..256 = -1.0..1.0 scaled by 256). cos(a)=SINQ8[(a+64)&255]. */
static const int16_t SINQ8[256] = {
0,6,13,19,25,31,38,44,50,56,62,68,74,80,86,92,98,104,109,115,121,126,132,137,142,147,152,157,162,167,172,177,
181,185,190,194,198,202,206,209,213,216,220,223,226,229,231,234,237,239,241,243,245,247,248,250,251,252,253,254,255,255,256,256,
256,256,256,255,255,254,253,252,251,250,248,247,245,243,241,239,237,234,231,229,226,223,220,216,213,209,206,202,198,194,190,185,
181,177,172,167,162,157,152,147,142,137,132,126,121,115,109,104,98,92,86,80,74,68,62,56,50,44,38,31,25,19,13,6,
0,-6,-13,-19,-25,-31,-38,-44,-50,-56,-62,-68,-74,-80,-86,-92,-98,-104,-109,-115,-121,-126,-132,-137,-142,-147,-152,-157,-162,-167,-172,-177,
-181,-185,-190,-194,-198,-202,-206,-209,-213,-216,-220,-223,-226,-229,-231,-234,-237,-239,-241,-243,-245,-247,-248,-250,-251,-252,-253,-254,-255,-255,-256,-256,
-256,-256,-256,-255,-255,-254,-253,-252,-251,-250,-248,-247,-245,-243,-241,-239,-237,-234,-231,-229,-226,-223,-220,-216,-213,-209,-206,-202,-198,-194,-190,-185,
-181,-177,-172,-167,-162,-157,-152,-147,-142,-137,-132,-126,-121,-115,-109,-104,-98,-92,-86,-80,-74,-68,-62,-56,-50,-44,-38,-31,-25,-19,-13,-6,
};
#define CAM_Z    340   /* camera distance (world units); always > max |z| so the divisor stays positive */
#define FOCAL    240   /* focal length (controls on-screen size) */
#define EYE_HALF  16   /* half interpupillary separation (world units); the STEREO "pop" strength */

/* Rotate + project using TWO independent Q8 angles (for auto-rotate mode). */
static void project_vertex(int8_t vx,int8_t vy,int8_t vz, int angY,int angX, int eyeShift,
                            int* sx,int* sy,int* depth){
    int cy=SINQ8[(angY+64)&255], sy_=SINQ8[angY&255];
    int x1=((int)vx*cy - (int)vz*sy_)>>8;
    int z1=((int)vx*sy_ + (int)vz*cy)>>8;
    int cx=SINQ8[(angX+64)&255], sx_=SINQ8[angX&255];
    int y1=((int)vy*cx - z1*sx_)>>8;
    int z2=((int)vy*sx_ + z1*cx)>>8;
    int denom=z2+CAM_Z;
    *sx = IW/2 + ((x1-eyeShift)*FOCAL)/denom;
    *sy = IH/2 - (y1*FOCAL)/denom;
    *depth = z2;
}
/* Rotate + project using the 3×3 rotation matrix (for IMU gyro mode — no gimbal lock). */
/* project_vertex_mat removed — using Euler angles for now (matrix version had IMU rate issues) */

/* ---- on-device IMU reader: read the firmware's live accel ring buffer directly from SRAM ----
 * The sensor_hub driver (DRV_IMUDataParserCallback) fills a 20-entry ring at *(uint32_t*)0x4be79c
 * (runtime-initialized SRAM ptr). Each entry is 0x70 bytes; current index at ring+8 (uint32).
 * Normalized accel floats (gravity vector, ~1g magnitude) sit at entry+0x34 (x), +0x38 (y), +0x3c (z).
 * HW-verified: these values change between consecutive reads and track head orientation in real time.
 * We convert accel x/y/z to two Q8 rotation angles (Y-spin from roll, X-tumble from pitch). */
#define IMU_RING_PTR  0x4be79cu   /* firmware global -> SRAM ring base */
#define IMU_ENTRY_SZ  0x70u
#define IMU_IDX_OFF   8u          /* offset of the current-entry index (uint32) within ring header */
#define IMU_FX_OFF    0x34u       /* float x within an entry */
#define IMU_FY_OFF    0x38u       /* float y */
#define IMU_FZ_OFF    0x3cu       /* float z */


/* ---- Rotation matrix IMU integration (no gimbal lock) ----
 * Maintains a 3×3 Q14 rotation matrix in ctx->rot[9]. Each tick, reads raw gyro from entry 0,
 * computes a differential rotation dR ≈ I + [ω]×, and multiplies: R_new = R * dR.
 * Periodically re-orthogonalizes to prevent numerical drift. */
#define Q14 16384
#define GYRO_SCALE 1  /* raw/SCALE → Q14 small-angle per tick. 1=most responsive (matches old Euler version). */

static void rot_init_from_accel(int32_t* m);  /* forward decl */

static void rot_init(int32_t* m){
    m[0]=Q14; m[1]=0;    m[2]=0;
    m[3]=0;    m[4]=Q14; m[5]=0;
    m[6]=0;    m[7]=0;    m[8]=Q14;
}

static void rot_orthogonalize(int32_t* m){
    /* Gram-Schmidt on rows: normalize row0, make row1 perpendicular, row2 = cross(row0,row1) */
    /* Row 0 magnitude squared (Q28) */
    int64_t d0 = (int64_t)m[0]*m[0] + (int64_t)m[1]*m[1] + (int64_t)m[2]*m[2];
    if(d0 < Q14) { rot_init(m); return; }  /* degenerate → reset */
    /* Approximate normalize: scale = Q14 / sqrt(d0/Q14^2) = Q14^2 / sqrt(d0)
     * Use one Newton-Raphson step: s ≈ 3/2 - d0/(2*Q14^2) then m[i] *= s */
    int32_t s0 = (int32_t)((3LL * Q14 * Q14 * Q14 / 2 - d0 * Q14 / 2) / ((int64_t)Q14 * Q14));
    /* Clamp to avoid divergence */
    if(s0 < Q14/2) s0 = Q14; if(s0 > Q14*2) s0 = Q14;
    m[0] = (int32_t)((int64_t)m[0] * s0 / Q14);
    m[1] = (int32_t)((int64_t)m[1] * s0 / Q14);
    m[2] = (int32_t)((int64_t)m[2] * s0 / Q14);
    /* Row 1: subtract projection onto row 0 */
    int64_t dot01 = (int64_t)m[3]*m[0] + (int64_t)m[4]*m[1] + (int64_t)m[5]*m[2];
    m[3] -= (int32_t)(dot01 * m[0] / ((int64_t)Q14*Q14));
    m[4] -= (int32_t)(dot01 * m[1] / ((int64_t)Q14*Q14));
    m[5] -= (int32_t)(dot01 * m[2] / ((int64_t)Q14*Q14));
    /* Normalize row 1 */
    int64_t d1 = (int64_t)m[3]*m[3] + (int64_t)m[4]*m[4] + (int64_t)m[5]*m[5];
    if(d1 < Q14) { rot_init(m); return; }
    int32_t s1 = (int32_t)((3LL * Q14 * Q14 * Q14 / 2 - d1 * Q14 / 2) / ((int64_t)Q14 * Q14));
    if(s1 < Q14/2) s1 = Q14; if(s1 > Q14*2) s1 = Q14;
    m[3] = (int32_t)((int64_t)m[3] * s1 / Q14);
    m[4] = (int32_t)((int64_t)m[4] * s1 / Q14);
    m[5] = (int32_t)((int64_t)m[5] * s1 / Q14);
    /* Row 2 = cross(row0, row1) */
    m[6] = (int32_t)(((int64_t)m[1]*m[5] - (int64_t)m[2]*m[4]) / Q14);
    m[7] = (int32_t)(((int64_t)m[2]*m[3] - (int64_t)m[0]*m[5]) / Q14);
    m[8] = (int32_t)(((int64_t)m[0]*m[4] - (int64_t)m[1]*m[3]) / Q14);
}

static void imu_update_matrix(ctx_t* c){
    uint32_t ring = *(volatile uint32_t*)0x4be79cu;
    if(ring < 0x20000000u || ring >= 0x20800000u) return;
    int16_t gx_raw = *(volatile int16_t*)(ring + 0x18);
    int16_t gy_raw = *(volatile int16_t*)(ring + 0x1a);
    int16_t gz_raw = *(volatile int16_t*)(ring + 0x1c);
    if(gx_raw > -5 && gx_raw < 5) gx_raw = 0;
    if(gy_raw > -5 && gy_raw < 5) gy_raw = 0;
    if(gz_raw > -5 && gz_raw < 5) gz_raw = 0;
    if(gx_raw == 0 && gy_raw == 0 && gz_raw == 0) goto accel_correct;
    /* Axis mapping from working Euler version:
     * chip Y (gy) → yaw  = rotation around world Y axis (screen vertical)
     * chip Z (gz) → pitch = rotation around world X axis (screen horizontal)
     * chip X (gx) → roll  = rotation around world Z axis (into screen) */
    { int32_t wx = (int32_t)gz_raw / GYRO_SCALE;  /* pitch */
      int32_t wy = (int32_t)gy_raw / GYRO_SCALE;  /* yaw */
      int32_t wz = (int32_t)gx_raw / GYRO_SCALE;  /* roll */
      /* WORLD-FRAME rotation: R_new = dR * R (LEFT multiply).
       * This matches Euler-style behavior where angY/angX are world-axis angles.
       * dR = I + [ω]×. For dR*R, each ROW of R is updated:
       * n[i][j] = dR[i][0]*R[0][j] + dR[i][1]*R[1][j] + dR[i][2]*R[2][j] */
      int32_t* m = c->rot;
      int32_t n[9];
      for(int j = 0; j < 3; j++){
          int32_t c0 = m[0*3+j], c1 = m[1*3+j], c2 = m[2*3+j];
          n[0*3+j] = c0 + (int32_t)(((int64_t)(-wz)*c1 + (int64_t)wy*c2) / Q14);
          n[1*3+j] = c1 + (int32_t)(((int64_t)wz*c0 + (int64_t)(-wx)*c2) / Q14);
          n[2*3+j] = c2 + (int32_t)(((int64_t)(-wy)*c0 + (int64_t)wx*c1) / Q14);
      }
      for(int i = 0; i < 9; i++) m[i] = n[i];
    }
accel_correct:
    /* Complementary filter: tilt matrix row2 toward measured gravity */
    { int32_t* m = c->rot;
      union{uint32_t u; float f;} v;
      v.u = *(volatile uint32_t*)(ring + 0x34); float ax = v.f;
      v.u = *(volatile uint32_t*)(ring + 0x38); float ay = v.f;
      v.u = *(volatile uint32_t*)(ring + 0x3c); float az = v.f;
      float mag2 = ax*ax + ay*ay + az*az;
      if(mag2 > 0.7f && mag2 < 1.3f){
          float inv_m; { float x2=mag2*0.5f; union{float f;uint32_t i;} c2; c2.f=mag2;
            c2.i=0x5f3759df-(c2.i>>1); inv_m=c2.f; inv_m=inv_m*(1.5f-x2*inv_m*inv_m); }
          float gx=ax*inv_m, gy=ay*inv_m, gz=az*inv_m;
          float cx=(float)m[6]/Q14, cy=(float)m[7]/Q14, cz=(float)m[8]/Q14;
          float ex=cy*gz-cz*gy, ey=cz*gx-cx*gz, ez=cx*gy-cy*gx;
          #define ACCEL_GAIN 40
          int32_t corr_x=(int32_t)(ex*ACCEL_GAIN), corr_y=(int32_t)(ey*ACCEL_GAIN), corr_z=(int32_t)(ez*ACCEL_GAIN);
          int32_t nn[9];
          for(int j=0;j<3;j++){
              int32_t c0=m[0*3+j], c1=m[1*3+j], c2=m[2*3+j];
              nn[0*3+j]=c0+(int32_t)(((int64_t)(-corr_z)*c1+(int64_t)corr_y*c2)/Q14);
              nn[1*3+j]=c1+(int32_t)(((int64_t)corr_z*c0+(int64_t)(-corr_x)*c2)/Q14);
              nn[2*3+j]=c2+(int32_t)(((int64_t)(-corr_y)*c0+(int64_t)corr_x*c1)/Q14);
          }
          for(int i=0;i<9;i++) m[i]=nn[i];
      }
    }
    if(++c->ortho_cnt >= 30){ c->ortho_cnt = 0; rot_orthogonalize(c->rot); }
}

/* Project vertex using the full 3×3 rotation matrix (no gimbal lock). */
static void project_vertex_mat(int8_t vx, int8_t vy, int8_t vz, int32_t* rot, int eyeShift,
                               int* sx, int* sy, int* depth){
    int x1 = (int)(((int64_t)rot[0]*vx + (int64_t)rot[1]*vy + (int64_t)rot[2]*vz) >> 14);
    int y1 = (int)(((int64_t)rot[3]*vx + (int64_t)rot[4]*vy + (int64_t)rot[5]*vz) >> 14);
    int z1 = (int)(((int64_t)rot[6]*vx + (int64_t)rot[7]*vy + (int64_t)rot[8]*vz) >> 14);
    int denom = z1 + CAM_Z;
    if(denom < 10) denom = 10;
    *sx = IW/2 + ((x1 - eyeShift) * FOCAL) / denom;
    *sy = IH/2 - (y1 * FOCAL) / denom;
    *depth = z1;
}

/* Initialize rotation matrix from current gravity vector (accelerometer).
 * Aligns the matrix so that "up" in model space matches the actual gravity direction.
 * Yaw (heading) defaults to identity since accel can't determine it. */
static void rot_init_from_accel(int32_t* m){
    uint32_t ring = *(volatile uint32_t*)0x4be79cu;
    if(ring < 0x20000000u || ring >= 0x20800000u){ rot_init(m); return; }
    union{uint32_t u; float f;} v;
    v.u = *(volatile uint32_t*)(ring + 0x34); float ax = v.f;
    v.u = *(volatile uint32_t*)(ring + 0x38); float ay = v.f;
    v.u = *(volatile uint32_t*)(ring + 0x3c); float az = v.f;
    /* Magnitude check */
    float mag2 = ax*ax + ay*ay + az*az;
    if(mag2 < 0.5f || mag2 > 2.0f){ rot_init(m); return; } /* invalid */
    /* Approximate 1/sqrt via Newton-Raphson (one iteration, good enough for init) */
    float inv_mag = 1.0f;
    { /* fast inverse sqrt approximation */
        float x2 = mag2 * 0.5f;
        union{float f; uint32_t i;} conv; conv.f = mag2;
        conv.i = 0x5f3759df - (conv.i >> 1);
        inv_mag = conv.f;
        inv_mag = inv_mag * (1.5f - x2 * inv_mag * inv_mag);
    }
    /* Gravity unit vector (points "down" in world) */
    float gx = ax * inv_mag, gy = ay * inv_mag, gz = az * inv_mag;
    /* Construct orthonormal frame:
     * row2 (Z axis of model) = gravity direction (what was "up" becomes aligned to gravity)
     * row0 (X axis) = perpendicular to gravity, in the XZ plane if possible
     * row1 (Y axis) = cross(row2, row0) */
    /* "Right" vector: cross(arbitrary_up, gravity). Use [0,1,0] as hint unless gravity is along Y */
    float rx, ry, rz;
    if(gy*gy > 0.9f){ /* gravity nearly along Y → use [1,0,0] as hint */
        rx = gz; ry = 0; rz = -gx;
    } else { /* cross([0,1,0], g) */
        rx = gz; ry = 0; rz = -gx; /* simplified: [0,1,0]×[gx,gy,gz] = [gz, 0, -gx] (ignoring gy term for simplicity) */
    }
    /* Normalize right vector */
    float rmag2 = rx*rx + ry*ry + rz*rz;
    if(rmag2 < 0.001f){ rot_init(m); return; }
    { float x2 = rmag2 * 0.5f; union{float f;uint32_t i;} c2; c2.f=rmag2; c2.i=0x5f3759df-(c2.i>>1);
      float ir=c2.f; ir=ir*(1.5f-x2*ir*ir); rx*=ir; ry*=ir; rz*=ir; }
    /* "Forward" = cross(gravity, right) */
    float fx = gy*rz - gz*ry;
    float fy = gz*rx - gx*rz;
    float fz = gx*ry - gy*rx;
    /* Build rotation matrix (rows = [right, forward, gravity]) in Q14 */
    m[0]=(int32_t)(rx*Q14); m[1]=(int32_t)(ry*Q14); m[2]=(int32_t)(rz*Q14);
    m[3]=(int32_t)(fx*Q14); m[4]=(int32_t)(fy*Q14); m[5]=(int32_t)(fz*Q14);
    m[6]=(int32_t)(gx*Q14); m[7]=(int32_t)(gy*Q14); m[8]=(int32_t)(gz*Q14);
}

/* Legacy Euler angle reader (kept for fallback/debug) */
static void read_imu_angles(int* angY, int* angX){
    uint32_t ring = *(volatile uint32_t*)0x4be79cu;
    if(ring < 0x20000000u || ring >= 0x20800000u){ *angY=0; *angX=0; return; }
    int16_t gyr = *(volatile int16_t*)(ring + 0x1a);
    int16_t gzr = *(volatile int16_t*)(ring + 0x1c);
    if(gyr > 5 || gyr < -5) ctx_get()->yaw_accum += (int)gyr;
    if(gzr > 5 || gzr < -5) ctx_get()->pitch_accum -= (int)gzr;
    *angY = (ctx_get()->yaw_accum / 512 + 256) & 255;
    *angX = (ctx_get()->pitch_accum / 512 + 256) & 255;
}

/* Draw the current frame into the L8 buffer. Both lenses call this with the SAME barrier-synced
 * c->frame -- the rotation angles are a pure function of c->frame (or the live IMU if imu_on),
 * so both eyes rotate in lockstep; the ONLY per-lens difference is the stereo eye offset. */
static void draw_scene(ctx_t* c){
    uint8_t* b=c->buf; if(!b) return;
    uint32_t f=c->frame;
    int side=c->api->lens_side();
    int eyeShift = !c->stereo ? 0 : (side==2 ? -EYE_HALF : EYE_HALF);
    for(uint32_t i=0;i<IW*IH;i++) b[i]=0;

    /* clean: no frame, no text — just the 3D model */

    /* rotation source: IMU matrix (on-device, tick-rate, no gimbal lock) or frame-counter */
    int spx[12], spy[12], sdep[12];
    if(c->imu_on){
        /* MASTER: update rotation matrix from gyro each tick */
        if(c->api->lens_side()==1) imu_update_matrix(c);
        /* Both lenses use the matrix (slave gets it via SYNC) */
        for(int i=0;i<12;i++)
            project_vertex_mat(ICO_V[i][0],ICO_V[i][1],ICO_V[i][2], c->rot, eyeShift, &spx[i],&spy[i],&sdep[i]);
    } else {
        int angY=(int)((f*3u)&255u), angX=(int)((f)&255u);
        for(int i=0;i<12;i++)
            project_vertex(ICO_V[i][0],ICO_V[i][1],ICO_V[i][2], angY,angX, eyeShift, &spx[i],&spy[i],&sdep[i]);
    }
    for(int e=0;e<30;e++){
        int a=ICO_E[e][0], bI=ICO_E[e][1];
        /* depth-fade: sdep (z2) GROWS with distance from the eye (see project_vertex: it's the
         * divisor's variable part, denom=z2+CAM_Z, so bigger z2 = farther = smaller/less-disparity
         * on screen). FIXED (was inverted: had far edges brighter). Near = bright, far = dim, full
         * strength (coefficient 1, not /2) so the fade is actually visible edge-to-edge. */
        int avgd=(sdep[a]+sdep[bI])/2;
        int v = 190 - avgd; if(v<25) v=25; if(v>255) v=255;
        draw_line(b, spx[a],spy[a], spx[bI],spy[bI], (uint8_t)v);
    }
    for(int i=0;i<12;i++) fillrect(b, spx[i]-2, spy[i]-2, 4, 4, 0xFF);   /* vertex markers */

    /* Draw XYZ axis vectors (origin at center, length 100 units) */
    { int ox,oy,od;
      /* axis tips as vertices projected through the same rotation */
      int ax,ay,bx,by,cx,cy;
      if(c->imu_on){
          project_vertex_mat(100,0,0, c->rot, eyeShift, &ax,&ay,&od); /* X tip */
          project_vertex_mat(0,100,0, c->rot, eyeShift, &bx,&by,&od); /* Y tip */
          project_vertex_mat(0,0,100, c->rot, eyeShift, &cx,&cy,&od); /* Z tip */
      } else {
          int aY=(int)((f*3u)&255u), aX=(int)((f)&255u);
          project_vertex(100,0,0, aY,aX, eyeShift, &ax,&ay,&od);
          project_vertex(0,100,0, aY,aX, eyeShift, &bx,&by,&od);
          project_vertex(0,0,100, aY,aX, eyeShift, &cx,&cy,&od);
      }
      ox=(int)(IW/2) - eyeShift*FOCAL/CAM_Z; oy=(int)(IH/2);
      draw_line(b,ox,oy,ax,ay,0xC0); draw_char(b,ax+2,ay-12,'X',0xC0); /* X axis: bright */
      draw_line(b,ox,oy,bx,by,0x80); draw_char(b,bx+2,by-12,'Y',0x80); /* Y axis: medium */
      draw_line(b,ox,oy,cx,cy,0x50); draw_char(b,cx+2,cy-12,'Z',0x50); /* Z axis: dim */
    }

    c->api->dcache_clean(b, IW*IH);             /* flush CPU writes before the GPU/DMA blit */
}

/* ---------------- display callback: build the image (event 2) + animate (event 4) ---------------- */
static int our_uiCb(unsigned event, unsigned a2, unsigned a3, void* container){
    (void)a2;(void)a3;
    ctx_t* c=ctx_get(); if(!c) return 0;
    if(event==2u){                              /* STARTUP: allocate buffer + one full-screen lv_image */
        c->buf=(uint8_t*)c->api->mem_alloc(IW*IH); mark(c->api,'B',(uint32_t)c->buf);
        if(!c->buf) return 0;
        c->dsc.magic=0x19; c->dsc.cf=0x06; c->dsc.flags=0; c->dsc.w=IW; c->dsc.h=IH;
        c->dsc.stride=IW; c->dsc.resv=0; c->dsc.data_size=IW*IH; c->dsc.data=c->buf;
        c->frame=0; draw_scene(c);
        void* img=((create_fn)FW_LV_IMAGE_CREATE)(container);
        ((setxy_fn)FW_LV_OBJ_SET_POS)(img,0,0);
        ((setsrc_fn)FW_LV_IMAGE_SETSRC)(img,&c->dsc);
        *(uint32_t*)(c->cfg+4)=(uint32_t)img; c->img=img; mark(c->api,'U',(uint32_t)img);
    } else if(event==4u){                        /* TICK: advance + redraw + invalidate */
        if(!(c->img && c->buf)) return 0;
        uint32_t now=c->api->tick_ms();
        if(c->sync_on){
            if(c->api->lens_side()==1){
                /* MASTER: hold frame N until the slave acks it (dataCb does frame++), then the next
                 * tick draws+sends N+1. Timeout guards a lost ack. Bounds L/R skew to one in-flight
                 * frame (self-throttling) — the app-level twin of the native DispStartBlocking barrier. */
                if(!c->waiting){
                    draw_scene(c); ((obj1_fn)FW_LV_OBJ_INVAL)(c->img);
                    /* Send frame + imu_on flag + rotation matrix (9×i16, Q14>>2=Q12).
                     * Total = 4 + 1 + 18 = 23 bytes — fits aa21 peer payload. */
                    uint8_t syncbuf[23]; syncbuf[0]=(uint8_t)c->frame; syncbuf[1]=(uint8_t)(c->frame>>8);
                    syncbuf[2]=(uint8_t)(c->frame>>16); syncbuf[3]=(uint8_t)(c->frame>>24);
                    syncbuf[4]=c->imu_on;
                    if(c->imu_on){
                        for(int j=0;j<9;j++){
                            int16_t v=(int16_t)(c->rot[j]>>2); /* Q14→Q12 */
                            syncbuf[5+j*2]=(uint8_t)(v&0xff); syncbuf[5+j*2+1]=(uint8_t)((v>>8)&0xff);
                        }
                    } else { for(int j=5;j<23;j++) syncbuf[j]=0; }
                    ((peer_fn)FW_SEND_DATA_TO_PEER)(OUR_APPID,syncbuf,23,0,EVT_SYNC);
                    c->waiting=1; c->wait_start=now;
                } else if(now-c->wait_start > SYNC_TIMEOUT_MS){ c->frame=next_frame(c); c->waiting=0; }
            } else {
                /* SLAVE: EVT_SYNC (dataCb) set c->frame + dirty; DRAW here in the safe tick context.
                 * If the master goes quiet, fall back to self-tick so we never freeze. */
                if(c->dirty){ draw_scene(c); ((obj1_fn)FW_LV_OBJ_INVAL)(c->img); c->dirty=0; }
                if(now-c->last_sync_ms > SYNC_IDLE_MS) c->sync_on=0;
            }
        } else {                                 /* standalone: each lens self-ticks (drifts vs peer) */
            c->frame=next_frame(c); draw_scene(c); ((obj1_fn)FW_LV_OBJ_INVAL)(c->img);
        }
    } else if(event==5u){ c->img=0; mark(c->api,'X',5); }
    return 0;
}

/* dataCb runs on the RECEIVING lens (peer-RX context). Keep it LIGHTWEIGHT: no drawing here. */
static int our_dataCb(unsigned cmd, unsigned char* data, unsigned len, unsigned arg){
    (void)arg; ctx_t* c=ctx_get(); if(!c) return 0;
    if(cmd==EVT_SYNC && len>=4 && data){
        /* SLAVE: record frame N + rotation matrix (if imu_on) + ack. */
        c->frame=(uint32_t)data[0]|((uint32_t)data[1]<<8)|((uint32_t)data[2]<<16)|((uint32_t)data[3]<<24);
        if(len>=5) c->imu_on=data[4];
        if(c->imu_on && len>=23){
            for(int j=0;j<9;j++){
                int16_t v=(int16_t)((uint16_t)data[5+j*2] | ((uint16_t)data[5+j*2+1]<<8));
                c->rot[j]=(int32_t)v << 2;  /* Q12→Q14 */
            }
        }
        c->sync_on=1; c->last_sync_ms=c->api->tick_ms(); c->dirty=1;
        uint32_t v=c->frame; ((peer_fn)FW_SEND_DATA_TO_PEER)(OUR_APPID,&v,4,0,EVT_ACK);
    } else if(cmd==EVT_ACK && len>=4){
        /* MASTER: slave has N -> advance (or snap to the host's manual value) for the next tick. */
        c->frame=next_frame(c); c->waiting=0;
    } else if(cmd==EVT_LFRAME && len>=4 && data){
        /* MASTER: relay the slave's reported frame counter to the phone (for the 'l' measurement). */
        uint8_t r[8]={0xA7,0x6c,data[0],data[1],data[2],data[3],(uint8_t)c->api->lens_side(),0}; c->api->reply(r,8);
    } else if(cmd==EVT_LCHUNK && data && len>=8){
        /* MASTER: a QOI screenshot fragment from L -> re-emit on sid 0x7d to the phone. */
        SS_FW_SEND(1, SS_SID, data, (int)len);
    }
    return 0;
}

/* ---------------- lifecycle ---------------- */
static void busywait(rt_api_t* a, uint32_t ms){ uint32_t t0=a->tick_ms(); while(a->tick_ms()-t0<ms){} }

static void go(ctx_t* c){
    ((startupfn)FW_DISPLAY_CLOSE)(OUR_APPID,0,0);
    for(int i=0;i<20 && *(volatile uint8_t*)FG_STATE!=0;i++) busywait(c->api,25);
    mark(c->api,'F',*(volatile uint8_t*)FG_STATE);
    ((voidfn)FW_WAKE_FSM)(); if(*(volatile uint8_t*)PANEL_PWR==0) ((voidfn)FW_WAKE_BARE)();
    *(volatile uint8_t*)IMU_HEADDOWN=0;
    for(int i=0;i<32;i++) c->cfg[i]=0;
    *(uint32_t*)(c->cfg+0)=OUR_APPID; c->cfg[0x0b]=0 /* type 0 = full-screen base (not overlay) */;
    c->cfg[0x17]=1 /* visible_base: make-or-break */;
    *(uint32_t*)(c->cfg+0x0c)=IW; *(uint32_t*)(c->cfg+0x10)=IH;
    if(!c->entry){   /* register the app_entry ONCE; a repeated 'g' must not append a duplicate */
        uint32_t count=*(volatile uint32_t*)REG_COUNT; if(count>=120u){ mark(c->api,'E',count); return; }
        volatile uint32_t* e=(volatile uint32_t*)(REG_BASE+count*16u);
        e[0]=OUR_APPID; e[1]=(uint32_t)&our_dataCb; e[2]=(uint32_t)&our_uiCb; e[3]=(uint32_t)c->cfg;
        __asm__ volatile("dsb sy":::"memory"); *(volatile uint32_t*)REG_COUNT=count+1u; c->entry=e;
        mark(c->api,'R',count+1u);
    }
    ((startupfn)FW_DISPLAY_STARTUP)(OUR_APPID,0,0); c->started=1; mark(c->api,'S',OUR_APPID);
}

static void a_init(rt_api_t* api){ uint8_t r[6]={0xA7,0x4e,'I',0,0,0}; api->reply(r,6); }
static void a_data(uint8_t* b,int n){ ctx_t* c=ctx_get(); if(!c||n<1) return;
    switch(b[0]){
    case 'g': go(c); break;                                                   /* open (send via arm-L: both lenses) */
    case 'm': c->sync_on=1; c->waiting=0; mark(c->api,'m',1); break;           /* barrier sync ON */
    case 'n': c->sync_on=0; c->waiting=0; mark(c->api,'n',0); break;           /* barrier sync OFF (self-tick) */
    case 'd': c->stereo^=1; mark(c->api,'d',c->stereo); break;                 /* stereo/3D toggle */
    case 'i': {  /* IMU toggle — MASTER ONLY. Uses rotation matrix (no gimbal lock).
                  * On enable: reads current accel to initialize the matrix aligned to gravity,
                  * then gyro integration keeps it updated. */
        if(c->api->lens_side()==1){
            c->imu_on^=1;
            if(c->imu_on){
                ((int(*)(void))FW_START_COMPASS)();
                busywait(c->api, 200); /* let sensor stabilize */
                rot_init_from_accel(c->rot);
                c->ortho_cnt=0;
            } else {
                ((int(*)(unsigned))FW_HUB_CLOSE)(2u);
                rot_init(c->rot);
            }
        }
        mark(c->api,'i',c->imu_on);
    } break;
    case 'F': if(n>=5){ c->manual_frame=(uint32_t)b[1]|((uint32_t)b[2]<<8)|((uint32_t)b[3]<<16)|((uint32_t)b[4]<<24); c->manual=1; } break; /* host sets rotation frame (slider/IMU drive); send to R (master) via arm-L */
    case 'A': c->manual=0; break;                                              /* back to auto-rotate */
    /* ---- gyro debug commands (testing different enable sequences) ---- */
    case 'P': {  /* PRE-IMU: call StartIMUCompassFunc BEFORE go(). Theory: if gyro is already active
                  * when display_startup's auto-brightness triggers bhi260_full_sensor_reconfig,
                  * the reconfig might include gyro in its active-sensor set. */
        ((int(*)(void))FW_START_COMPASS)();
        c->imu_on=1; mark(c->api,'P',1);
    } break;
    case 'H': {  /* HUB_CLOSE(4) → delay → StartIMUCompassFunc: kill auto-brightness sensor role,
                  * then re-enable gyro. Theory: removing role=4 prevents future reconfigs from
                  * overwriting gyro state. */
        ((int(*)(unsigned))FW_HUB_CLOSE)(4u);
        busywait(c->api, 500);
        ((int(*)(void))FW_START_COMPASS)();
        c->imu_on=1; mark(c->api,'H',1);
    } break;
    case 'J': {  /* RAW sensor enable: bypass the hub entirely, write chip registers directly.
                  * Uses bhi260_sensor_enable(ctx, mode=0, {1,1,1}) to set accel+gyro+mag on reg 0x18,
                  * then mode=1 on reg 0x58 for the second bank. */
        uint32_t drv_ctx = *(volatile uint32_t*)IMU_DRIVER_CTX_PTR;
        uint8_t cfg[3] = {1,1,1};
        ((int(*)(uint32_t,int,uint8_t*))FW_IMU_SET_ENABLE)(drv_ctx, 0, cfg);
        busywait(c->api, 100);
        ((int(*)(uint32_t,int,uint8_t*))FW_IMU_SET_ENABLE)(drv_ctx, 1, cfg);
        c->imu_on=1; mark(c->api,'J',1);
    } break;
    case 'K': {  /* HUB_OPEN(2) only — just the role activation without parameter config.
                  * hub_open(2) might trigger a proper full-reconfig that includes gyro. */
        ((int(*)(unsigned))FW_HUB_OPEN)(2u);
        c->imu_on=1; mark(c->api,'K',1);
    } break;
    case 'L': {  /* FULL SEQUENCE: hub_close(4) + hub_close(5) + delay + hub_open(2) + param_config.
                  * Theory: close ALL other sensor roles, then open JUST gyro so the chip gets a clean
                  * reconfig with only gyro+accel active. */
        ((int(*)(unsigned))FW_HUB_CLOSE)(4u);
        ((int(*)(unsigned))FW_HUB_CLOSE)(5u);
        busywait(c->api, 1000);
        ((int(*)(unsigned))FW_HUB_OPEN)(2u);
        busywait(c->api, 500);
        uint32_t params[2] = {1000, 5};
        ((int(*)(uint8_t,uint32_t*))FW_HUB_PARAMCONFIG)(2, params);
        c->imu_on=1; mark(c->api,'L',1);
    } break;
    case 'I': {  /* dump live IMU state from entry 0 (ring base — always the live data slot) */
        uint32_t ring = *(volatile uint32_t*)0x4be79cu;
        uint32_t idx=0; uint8_t flags=0; float ax=0,ay=0,az=0;
        int16_t grx=0,gry=0,grz=0;
        if(ring>=0x20000000u&&ring<0x20800000u){
            idx=*(volatile uint32_t*)(ring+8);
            flags=*(volatile uint8_t*)(ring+0x10);
            union{uint32_t u;float f;} v;
            v.u=*(volatile uint32_t*)(ring+0x34); ax=v.f;
            v.u=*(volatile uint32_t*)(ring+0x38); ay=v.f;
            v.u=*(volatile uint32_t*)(ring+0x3c); az=v.f;
            grx=*(volatile int16_t*)(ring+0x18);
            gry=*(volatile int16_t*)(ring+0x1a);
            grz=*(volatile int16_t*)(ring+0x1c);
        }
        uint8_t r[32]; r[0]=0xA7; r[1]=0x49;
        r[2]=c->imu_on; r[3]=c->imu_angY; r[4]=c->imu_angX;
        r[5]=(uint8_t)c->api->lens_side(); r[6]=(uint8_t)idx; r[7]=flags;
        r[8]=(uint8_t)(grx&0xff); r[9]=(uint8_t)(grx>>8);
        int16_t ix=(int16_t)(ax*100.0f),iy=(int16_t)(ay*100.0f),iz=(int16_t)(az*100.0f);
        r[10]=(uint8_t)ix; r[11]=(uint8_t)(ix>>8);
        r[12]=(uint8_t)iy; r[13]=(uint8_t)(iy>>8);
        r[14]=(uint8_t)iz; r[15]=(uint8_t)(iz>>8);
        { union{uint32_t u;float f;} gv;
          gv.u=*(volatile uint32_t*)(ring+0x40); int16_t gxi=(int16_t)(gv.f*100.0f);
          gv.u=*(volatile uint32_t*)(ring+0x44); int16_t gyi=(int16_t)(gv.f*100.0f);
          gv.u=*(volatile uint32_t*)(ring+0x48); int16_t gzi=(int16_t)(gv.f*100.0f);
          r[16]=(uint8_t)gxi; r[17]=(uint8_t)(gxi>>8);
          r[18]=(uint8_t)gyi; r[19]=(uint8_t)(gyi>>8);
          r[20]=(uint8_t)gzi; r[21]=(uint8_t)(gzi>>8); }
        r[22]=(uint8_t)(gry&0xff); r[23]=(uint8_t)(gry>>8);
        r[24]=(uint8_t)(grz&0xff); r[25]=(uint8_t)(grz>>8);
        c->api->reply(r,26);
    } break;
    case 'D': {  /* DUMP: raw hex of entry 0 (ring base, the live data slot), 0x70 bytes in 2 chunks */
        uint32_t ring = *(volatile uint32_t*)0x4be79cu;
        if(ring>=0x20000000u&&ring<0x20800000u){
            uint32_t idx=*(volatile uint32_t*)(ring+8);
            uint8_t r0[60]; r0[0]=0xA7; r0[1]=0x44; r0[2]=0; r0[3]=(uint8_t)idx;
            for(int j=0;j<56;j++) r0[4+j]=*(volatile uint8_t*)(ring+j);
            c->api->reply(r0,60);
            uint8_t r1[60]; r1[0]=0xA7; r1[1]=0x44; r1[2]=1; r1[3]=(uint8_t)idx;
            for(int j=0;j<56;j++) r1[4+j]=*(volatile uint8_t*)(ring+56+j);
            c->api->reply(r1,60);
        }
    } break;
    case 'k': { uint32_t f=c->frame; uint8_t r[8]={0xA7,0x6b,(uint8_t)f,(uint8_t)(f>>8),(uint8_t)(f>>16),(uint8_t)(f>>24),(uint8_t)c->api->lens_side(),0}; c->api->reply(r,8); } break; /* report THIS lens's frame (R replies) */
    case 'l': { uint32_t f=c->frame; ((peer_fn)FW_SEND_DATA_TO_PEER)(OUR_APPID,&f,4,0,EVT_LFRAME); } break;         /* L: relay my frame via R */
    case 's': { const uint8_t* fb=ss_fb_ptr(); if(fb) cfw_screenshot_capture(fb,SS_FB_W,SS_FB_H,SS_FB_BPP); } break; /* capture THIS lens (L relays via R) */
    case 'S': { if(c->api->lens_side()==2){ const uint8_t* fb=ss_fb_ptr(); if(fb) cfw_screenshot_capture(fb,SS_FB_W,SS_FB_H,SS_FB_BPP); } } break; /* L-ONLY capture: isolates the peer-relay path (no R direct-capture collision on sid 0x7d) */
    case 'q': ((startupfn)FW_DISPLAY_CLOSE)(OUR_APPID,0,0); if(c->entry){c->entry[0]=0;c->entry[2]=0;} mark(c->api,'Q',0); break;
    default: break;
    }
}
static void a_tick(uint32_t d){(void)d;} static void a_input(void* e){(void)e;}
static void a_exit(void){ ctx_t* c=ctx_get(); if(!c) return; ((startupfn)FW_DISPLAY_CLOSE)(OUR_APPID,0,0);
    if(c->entry){c->entry[0]=0;c->entry[2]=0;} if(c->buf) c->api->mem_free(c->buf); c->api->mem_free(c); *(ctx_t* volatile*)MODE_CTX_SLOT=0; }

mode_vtable_t* payload_entry(rt_api_t* api){
    ctx_t* c=(ctx_t*)api->mem_alloc(sizeof(ctx_t)); if(!c) return 0;
    for(unsigned i=0;i<sizeof(ctx_t);i++) ((uint8_t*)c)[i]=0;
    rot_init(c->rot);
    c->vt.init=a_init; c->vt.tick=a_tick; c->vt.on_input=a_input; c->vt.on_data=a_data; c->vt.exit=a_exit;
    c->api=api; *(ctx_t* volatile*)MODE_CTX_SLOT=c; return &c->vt;
}
