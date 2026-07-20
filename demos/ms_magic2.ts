import { G2Session } from "g2-kit/ble";
function varint(n: number): number[] {
  const out: number[] = []; let v = n >>> 0;
  do { let b = v & 0x7f; v >>>= 7; if (v) b |= 0x80; out.push(b); } while (v);
  return out;
}
function tagByte(f: number, w: number): number[] { return varint((f << 3) | w); }
function build(magic: number): Uint8Array {
  return new Uint8Array([...tagByte(1,0), ...varint(magic), ...tagByte(3,2), ...varint(2), ...tagByte(1,0), ...varint(2)]);
}
const session = await G2Session.open();
console.log("connected");
session.onRawFrame((frame, raw, arm) => {
  if (!frame.ok) return;
  console.log(`${arm} sid=0x${frame.sid.toString(16)} pb=${Buffer.from(frame.pb).toString("hex")}`);
});
const magic = Number(process.argv[2] ?? "2");
const pb = build(magic);
console.log(`sending mode_sync magic=${magic} bytes=${Buffer.from(pb).toString("hex")}`);
const ack = await session.sendPb(0x30, pb, magic, { ackTimeoutMs: 1500 });
console.log(ack ? `ack: ${Buffer.from(ack.pb).toString("hex")}` : "no direct ack, watching 5s...");
await new Promise(r => setTimeout(r, 5000));
await session.close();
process.exit(0);
