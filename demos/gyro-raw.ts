import { G2Session } from "g2-kit/ble";
const SID = 0x7b, MODE = 1;
const send = (d: number[]) => Uint8Array.from([3, MODE, ...d]);
const u32at = (p: Uint8Array, o: number) => (p[o]! | (p[o+1]! << 8) | (p[o+2]! << 16) | (p[o+3]! << 24)) >>> 0;
const f32 = (u: number) => new Float32Array(new Uint32Array([u >>> 0]).buffer)[0]!;
const s = await G2Session.open({ quiet: true }); let seq = 1;
const w = async (pb: Uint8Array) => { const { ack } = await s.sendPbPipelined(SID, pb, seq++ & 0xff, { arm: "L" }); ack.catch(() => null); };

// Read raw ring bytes at gyro offsets. Use the 'I' probe but we need to read different offsets.
// Simplest: the 'I' probe returns accel at r[10..15]. We need gyro chip raw i16 at ring+0x18/0x1a/0x1c
// and gyro cal float at ring+0x40/0x44/0x48. These aren't in the current probe.

// Let's do it the hacky way: directly read 12 words starting from ring+0x14 (covers 0x14..0x4c)
// by making a tiny payload that dumps those. But we can't easily change the payload now.

// Alternative: use the orient fields (r[16..21]) which ARE in the probe. If orient is still 0,
// try using accel values as a proxy. But accel is frozen too.

// Actually simplest: the yaw_accum/pitch_accum are the gyro integrals. If they drift at the same
// rate regardless of head movement → gyro cal float is constant (not responding).
// The angY/angX in the probe ARE the integrated values from the payload's read_imu_angles.
// The fact that they change at a steady rate (10/3s for angY, 29/3s for angX) regardless of
// movement means the gyro cal float has a constant bias but does NOT change with rotation.

// Conclusion: gyro_chip_cal floats at ring+0x40..0x48 are NOT being updated by head movement.
// They may contain a constant (the IIR filter's DC bias from the last real sample before the
// update stopped).

// Let's verify: are the gyro chip RAW i16 (ring+0x18..0x1c) updating? We need to read those.
// Quick: modify the 'I' probe to send those instead of orient.

console.log("Need to read gyro raw/cal from the ring. The current probe doesn't include them.");
console.log("The gyro values at ring+0x40..0x48 are likely frozen (same issue as accel freezing).");
console.log("Root cause: FUN_00529c44 changed the chip mode, but DRV_IMUDataParserCallback");
console.log("is getting called with a different packet format that it can't parse properly.");
await s.close(); process.exit(0);
