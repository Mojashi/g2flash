#!/usr/bin/env bun
// Fetch real building footprints + heights from OpenStreetMap (Overpass API) and
// write a compact, pre-projected city.json that stereo-demo.ts's `map` scene can
// extrude into a 3D skyline. Buildings come back as ways with inline geometry;
// we project lat/lon to local metres (equirectangular about the bbox centre),
// read height (height tag, else building:levels × 3.4 m, else a default), and
// keep the footprint polygon.
//
//   bun fetch-city.ts                     # default: Otemachi / Marunouchi, Tokyo
//   G2_BBOX="s,w,n,e" bun fetch-city.ts   # custom bbox (lat,lon,lat,lon)
//   G2_CITY_OUT=city.json                 # output path (default ./city.json)

const BBOX = process.env.G2_BBOX ?? "35.6845,139.7615,35.6895,139.7675"; // Otemachi/Marunouchi
const OUT = process.env.G2_CITY_OUT ?? "city.json";
const DEFAULT_H = Number(process.env.G2_DEFAULT_H ?? "14"); // metres, for untagged buildings
const [s, w, n, e] = BBOX.split(",").map(Number);
const lat0 = (s + n) / 2, lon0 = (w + e) / 2;
const mPerLat = 110540, mPerLon = 111320 * Math.cos((lat0 * Math.PI) / 180);

const query = `[out:json][timeout:40];way["building"](${s},${w},${n},${e});out geom tags;`;
console.log(`[fetch] Overpass buildings in ${BBOX} ...`);
const ENDPOINTS = [
  "https://overpass-api.de/api/interpreter",
  "https://overpass.kumi.systems/api/interpreter",
  "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
];
let res: Response | null = null;
for (const ep of ENDPOINTS) {
  try {
    const r = await fetch(ep, {
      method: "POST",
      headers: {
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
        "User-Agent": "g2-stereo-demo/0.1 (OSM building fetch; contact omori)",
      },
      body: "data=" + encodeURIComponent(query),
    });
    if (r.ok) { res = r; console.log(`[fetch] via ${ep}`); break; }
    console.error(`[fetch] ${ep}: HTTP ${r.status} ${r.statusText}`);
  } catch (err) {
    console.error(`[fetch] ${ep}: ${(err as Error).message}`);
  }
}
if (!res) { console.error("[fetch] all Overpass endpoints failed"); process.exit(1); }
const data = (await res.json()) as { elements: Array<{ type: string; geometry?: Array<{ lat: number; lon: number }>; tags?: Record<string, string> }> };

function parseHeight(tags?: Record<string, string>): number | null {
  if (!tags) return null;
  const h = tags["height"] ?? tags["building:height"];
  if (h) { const m = parseFloat(String(h).replace(",", ".")); if (isFinite(m) && m > 0) return m; }
  const lv = tags["building:levels"] ?? tags["levels"];
  if (lv) { const l = parseFloat(String(lv)); if (isFinite(l) && l > 0) return l * 3.4; }
  return null;
}

type Building = { h: number; poly: [number, number][]; tagged: boolean };
const buildings: Building[] = [];
let maxAbs = 1;
for (const el of data.elements) {
  if (el.type !== "way" || !el.geometry || el.geometry.length < 4) continue;
  const g = el.geometry;
  // drop the duplicated closing vertex if present
  const pts = g.slice(0, g[0]!.lat === g[g.length - 1]!.lat && g[0]!.lon === g[g.length - 1]!.lon ? -1 : undefined);
  if (pts.length < 3) continue;
  const poly: [number, number][] = pts.map((p) => {
    const x = (p.lon - lon0) * mPerLon;   // east (m)
    const z = (p.lat - lat0) * mPerLat;   // north (m)
    if (Math.abs(x) > maxAbs) maxAbs = Math.abs(x);
    if (Math.abs(z) > maxAbs) maxAbs = Math.abs(z);
    return [Math.round(x * 10) / 10, Math.round(z * 10) / 10];
  });
  const hParsed = parseHeight(el.tags);
  buildings.push({ h: hParsed ?? DEFAULT_H, poly, tagged: hParsed != null });
}

// Prefer the visually meaningful ones: sort by height, keep a manageable count so
// the wireframe stays legible on 288-wide tiles and the per-frame payload stays sane.
const MAX_BUILDINGS = Number(process.env.G2_MAX_BUILDINGS ?? "70");
buildings.sort((a, b) => b.h - a.h);
const kept = buildings.slice(0, MAX_BUILDINGS);
const tagged = kept.filter((b) => b.tagged).length;

const out = {
  source: "OpenStreetMap via Overpass API",
  bbox: BBOX, center: { lat: lat0, lon: lon0 }, extent_m: Math.round(maxAbs),
  count: kept.length, buildings: kept,
};
await Bun.write(OUT, JSON.stringify(out));
console.log(`[fetch] ${data.elements.length} ways -> kept ${kept.length} buildings ` +
  `(${tagged} with real height/levels), extent ±${Math.round(maxAbs)} m -> ${OUT}`);
const tall = kept.slice(0, 5).map((b) => `${b.h.toFixed(0)}m/${b.poly.length}pt`).join(", ");
console.log(`[fetch] tallest: ${tall}`);
