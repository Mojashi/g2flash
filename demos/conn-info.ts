import { G2Session } from "g2-kit/ble";
const s = await G2Session.open({ quiet: true });
const info = (a: any) => `id=${a.peripheral.id} addr=${a.peripheral.address ?? "?"} name=${JSON.stringify(a.peripheral.advertisement?.localName ?? "?")} writeUuid=${a.write?.uuid} notifyUuid=${a.notify?.uuid}`;
console.log("LEFT :", info(s.left));
console.log("RIGHT:", info(s.right));
console.log("same device?", s.left.peripheral.id === s.right.peripheral.id);
await s.close(); process.exit(0);
