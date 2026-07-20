#!/usr/bin/env bun
// Interactive stereo tweak server. Serves a browser UI where you drag to orbit
// the 3D city, slide disparity / framing, and (if the glasses are connected)
// push the full-panel 2x2-tiled stereo frame to the lens live.
//
//   bun stereo-server.ts                 # connect to glasses + serve UI on :8787
//   G2_NO_GLASSES=1 bun stereo-server.ts # preview-only, no BLE
//
// The renderer is shared with the CLI (stereo-render.ts). Glasses transport
// reuses the tiling lessons: CREATE root only + one REBUILD for all 4 tiles,
// warmup frame, window=1 serial sends with ack-miss tolerance, never shut down.

import {
  G2Session, buildCreateStartUpPageContainer, buildImageContainers,
  buildImageRawData, planImageFragments, queryCapabilities, hasFeature,
  type ImageContainerSpec,
} from "g2-kit/ble";
import { startHeartbeat } from "g2-kit/ui";
import { readFileSync } from "node:fs";
import {
  renderStereo, buildStereoPayload, cropTile, anaglyphBmp, DEFAULTS,
  type RenderParams, type City,
} from "./stereo-render.ts";

const PORT = Number(process.env.PORT ?? "8787");
const NO_GLASSES = process.env.G2_NO_GLASSES === "1";
const W = 576, H = 288, TW = 288, TH = 144;

let city: City | null = null;
try { city = JSON.parse(readFileSync(process.env.G2_CITY ?? "city.json", "utf8")); } catch { city = null; }
console.log(`[server] city: ${city ? `${city.buildings.length} buildings` : "none (procedural fallback)"}`);

function paramsFromQuery(q: URLSearchParams): RenderParams {
  const n = (k: string, d: number) => { const v = q.get(k); return v == null || v === "" ? d : Number(v); };
  return {
    W, H, scene: "map",
    focal: n("focal", DEFAULTS.focal),
    iod: n("iod", DEFAULTS.iod),
    converge: n("converge", DEFAULTS.converge),
    aa: q.get("aa") === "1",
    azimuth: n("az", DEFAULTS.azimuth),
    elev: n("elev", DEFAULTS.elev),
    dist: n("dist", DEFAULTS.dist),
    targetY: n("ty", DEFAULTS.targetY),
    span: n("span", DEFAULTS.span),
    maxBldg: n("maxb", DEFAULTS.maxBldg),
  };
}
// rough max crossed disparity (px) for the UI readout
function maxDisparity(p: RenderParams): number {
  const zNear = Math.max(1, p.converge - 4);
  return p.focal * p.iod * (1 / zNear - 1 / p.converge);
}

// ---------------------------------------------------------------- glasses ----
type Tile = { spec: ImageContainerSpec; sx: number; sy: number; sid: number };
let session: G2Session | null = null;
let tiles: Tile[] = [];
let connected = false, connecting = false;
let magic = 100;
const nextMagic = () => (magic = magic >= 255 ? 100 : magic + 1);

async function connect(): Promise<void> {
  if (NO_GLASSES || connected || connecting) return;
  connecting = true;
  try {
    console.log("[server] connecting to glasses...");
    const s = await G2Session.open();
    const caps = await queryCapabilities(s, 101).catch(() => null);
    if (caps && !hasFeature(caps, "stereo")) throw new Error(`no stereo feature: ${caps.raw}`);
    startHeartbeat({ session: s, nextMagic });

    const suffix = String(Date.now() % 10_000).padStart(4, "0");
    tiles = [];
    for (let row = 0, idx = 0; row < 2; row++) for (let col = 0; col < 2; col++, idx++) {
      tiles.push({
        spec: { name: `i${suffix}_${idx}`, containerId: 2 + idx, x: col * TW, y: row * TH, width: TW, height: TH },
        sx: col * TW, sy: row * TH, sid: 1,
      });
    }
    const create = buildCreateStartUpPageContainer({ name: `s${suffix}`, items: ["."], containerId: 1, captureEvents: false, magic: nextMagic() });
    if (!(await s.sendPb(0xe0, create.pb, create.magic, { ackTimeoutMs: 12000 }))) throw new Error("CREATE no ack");
    const rebuild = buildImageContainers({ containers: tiles.map((t) => t.spec), magic: nextMagic() });
    if (!(await s.sendPb(0xe0, rebuild.pb, rebuild.magic, { ackTimeoutMs: 12000 }))) throw new Error("REBUILD no ack");
    await new Promise((r) => setTimeout(r, 300));
    session = s;
    // warmup each container (first stream of a fresh container is dropped)
    const warm = buildStereoPayload(new Uint8Array(TW * TH), new Uint8Array(TW * TH));
    for (const t of tiles) { await sendTile(t, warm); t.sid++; }
    await new Promise((r) => setTimeout(r, 200));
    connected = true;
    console.log("[server] glasses connected — pushes will render live");
  } catch (e) {
    console.log(`[server] glasses not connected (${(e as Error).message}) — preview-only`);
    session = null;
  } finally {
    connecting = false;
  }
}

// window=1 serial send of one payload to one tile, with ack-miss tolerance
async function sendTile(t: Tile, payload: Uint8Array): Promise<boolean> {
  if (!session) return false;
  let miss = 0;
  for (const frag of planImageFragments(payload, 4000)) {
    const raw = buildImageRawData({
      containerId: t.spec.containerId, containerName: t.spec.name, mapSessionId: t.sid,
      mapTotalSize: payload.length, mapFragmentIndex: frag.index, mapRawData: frag.data, magic: nextMagic(),
    });
    const { ack } = await session.sendPbPipelined(0xe0, raw.pb, raw.magic, { ackTimeoutMs: 2500, arm: "R" });
    if ((await ack) === null && ++miss >= 8) return false;
  }
  return true;
}

// serialize frame streaming: only the latest requested params get streamed
let pending: RenderParams | null = null, streaming = false;
async function pushLatest(p: RenderParams): Promise<void> {
  pending = p;
  if (streaming || !session) return;
  streaming = true;
  try {
    while (pending) {
      const q = pending; pending = null;
      const { left, right } = renderStereo(q, city);
      for (const t of tiles) {
        const lt = cropTile(left, W, t.sx, t.sy, TW, TH);
        const rt = cropTile(right, W, t.sx, t.sy, TW, TH);
        const ok = await sendTile(t, buildStereoPayload(lt, rt));
        t.sid++;
        if (!ok) { console.log("[server] tile send failed — marking disconnected"); connected = false; session = null; return; }
      }
    }
  } finally {
    streaming = false;
  }
}

// ------------------------------------------------------------------- UI -------
const UI = /* html */ `<!doctype html><html><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>G2 Stereo Tweak</title><style>
:root{--bg:#0a0d10;--panel:#12171c;--line:#20272e;--txt:#d8e1e7;--mut:#8593a0;--cyan:#4fd6e0;--red:#ff5a6a}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--txt);
font:14px/1.5 ui-monospace,Menlo,monospace;-webkit-user-select:none;user-select:none}
.wrap{max-width:900px;margin:0 auto;padding:18px}
h1{font-size:15px;letter-spacing:.12em;text-transform:uppercase;color:var(--cyan);margin:0 0 14px}
#view{width:100%;display:block;border:1px solid var(--line);border-radius:8px;background:#000;
cursor:grab;image-rendering:auto;touch-action:none}
#view.drag{cursor:grabbing}
.hint{color:var(--mut);font-size:12px;margin:8px 0 16px}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:12px 22px}
.ctl{display:flex;flex-direction:column;gap:4px}
.ctl label{display:flex;justify-content:space-between;color:var(--mut);font-size:12px}
.ctl label b{color:var(--txt);font-weight:600}
input[type=range]{width:100%;accent-color:var(--cyan)}
.row{display:flex;gap:14px;align-items:center;margin:16px 0 4px;flex-wrap:wrap}
button{font:inherit;background:var(--cyan);color:#04222a;border:0;border-radius:6px;padding:8px 16px;font-weight:700;cursor:pointer}
button.ghost{background:transparent;color:var(--txt);border:1px solid var(--line)}
.chk{display:flex;align-items:center;gap:6px;color:var(--mut)}
#stat{margin-left:auto;color:var(--mut);font-size:12px}
#stat b{color:var(--cyan)}
.dot{width:8px;height:8px;border-radius:50%;display:inline-block;margin-right:5px}
</style></head><body><div class=wrap>
<h1>Even G2 · Stereo Tweak <span id=stat></span></h1>
<img id=view alt="stereo preview">
<div class=hint>ドラッグで回転（横=方位 / 縦=仰角）· 赤=左目 シアン=右目（赤シアンメガネで確認）</div>
<div class=grid id=sliders></div>
<div class=row>
<button id=push>グラスに送る</button>
<label class=chk><input type=checkbox id=auto> ドラッグ中も自動送信</label>
<label class=chk><input type=checkbox id=aa> アンチエイリアス</label>
<span id=disp></span>
</div>
</div><script>
const D=${JSON.stringify(DEFAULTS)};
const P={focal:D.focal,iod:0.5,converge:D.converge,az:D.azimuth,elev:D.elev,dist:D.dist,ty:D.targetY,span:D.span,maxb:D.maxBldg,aa:0};
const SL=[
 ['iod','視差 (IOD)',0.05,1.2,0.01],
 ['focal','ズーム (focal)',180,650,5],
 ['converge','収束深度 (Zc)',5,18,0.5],
 ['maxb','建物数',4,42,1],
 ['dist','カメラ距離',6,20,0.5],
 ['elev','仰角',-1.1,-0.05,0.02],
 ['ty','上下フレーミング',-0.5,2.5,0.1],
 ['span','スケール',2.5,7,0.1],
];
const qs=()=>Object.entries(P).map(([k,v])=>k+'='+v).join('&');
const sliders=document.getElementById('sliders');
for(const [k,lab,min,max,step] of SL){
 const d=document.createElement('div');d.className='ctl';
 d.innerHTML='<label>'+lab+'<b id="v_'+k+'"></b></label><input type=range min='+min+' max='+max+' step='+step+' id="s_'+k+'">';
 sliders.appendChild(d);
 const s=d.querySelector('input');s.value=P[k];
 document.getElementById('v_'+k).textContent=(+P[k]).toFixed(2);
 s.addEventListener('input',()=>{P[k]=+s.value;document.getElementById('v_'+k).textContent=(+s.value).toFixed(2);schedule(true);});
}
const view=document.getElementById('view');
let inflight=false,queued=false,doPush=false;
async function refresh(){
 if(inflight){queued=true;return;}
 inflight=true;
 const wantPush=doPush;doPush=false;
 view.src='/preview?'+qs()+'&_='+Date.now();
 if(wantPush){ try{const r=await fetch('/push?'+qs());const j=await r.json();setStat(j.connected);}catch(e){} }
 inflight=false;
 if(queued){queued=false;refresh();}
}
let t=null;
function schedule(push){ if(push&&(document.getElementById('auto').checked||push==='force'))doPush=true; clearTimeout(t); t=setTimeout(refresh,60); }
// disparity readout
function updDisp(){const zN=Math.max(1,P.converge-4);const px=(P.focal*P.iod*(1/zN-1/P.converge));document.getElementById('disp').textContent='最大視差 ~'+px.toFixed(1)+'px';}
setInterval(updDisp,200);updDisp();
// drag to orbit
let drag=false,lx=0,ly=0;
const down=(x,y)=>{drag=true;lx=x;ly=y;view.classList.add('drag');};
const move=(x,y)=>{if(!drag)return;P.az=(P.az+(x-lx)*0.008);P.elev=Math.max(-1.15,Math.min(-0.03,P.elev+(y-ly)*0.004));lx=x;ly=y;document.getElementById('s_elev').value=P.elev;schedule(true);};
const up=()=>{drag=false;view.classList.remove('drag');schedule('force');};
view.addEventListener('mousedown',e=>down(e.clientX,e.clientY));
window.addEventListener('mousemove',e=>move(e.clientX,e.clientY));
window.addEventListener('mouseup',up);
view.addEventListener('touchstart',e=>{const t=e.touches[0];down(t.clientX,t.clientY);},{passive:true});
window.addEventListener('touchmove',e=>{const t=e.touches[0];move(t.clientX,t.clientY);},{passive:true});
window.addEventListener('touchend',up);
document.getElementById('push').addEventListener('click',()=>{doPush=true;refresh();});
document.getElementById('aa').addEventListener('change',e=>{P.aa=e.target.checked?1:0;schedule(true);});
function setStat(c){const s=document.getElementById('stat');s.innerHTML='<span class=dot style="background:'+(c?'#39d353':'#f85149')+'"></span>'+(c?'glasses connected':'preview only');}
setStat(${connected});
refresh();
</script></body></html>`;

// ---------------------------------------------------------------- serve ------
if (!NO_GLASSES) connect();  // best-effort; UI works regardless

Bun.serve({
  port: PORT,
  async fetch(req) {
    const url = new URL(req.url);
    if (url.pathname === "/") return new Response(UI, { headers: { "content-type": "text/html; charset=utf-8" } });
    if (url.pathname === "/preview") {
      const p = paramsFromQuery(url.searchParams);
      const { left, right } = renderStereo(p, city);
      const bmp = anaglyphBmp(left, right, W, H);
      return new Response(bmp as unknown as BodyInit, { headers: { "content-type": "image/bmp", "cache-control": "no-store" } });
    }
    if (url.pathname === "/push") {
      const p = paramsFromQuery(url.searchParams);
      if (!connected && !connecting) connect();
      if (connected) pushLatest(p);
      return Response.json({ connected, disparity: +maxDisparity(p).toFixed(1) });
    }
    return new Response("not found", { status: 404 });
  },
});
console.log(`[server] UI: http://localhost:${PORT}  (drag to orbit, sliders to tune)`);
