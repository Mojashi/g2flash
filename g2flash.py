#!/usr/bin/env python3
"""
G2 firmware flasher — reimplements the official app's BLE flash protocol.

Two transports are supported, selected by the connection string passed on the
command line:

  g2://droidbridge?phone=<host>&port=<port>&token=<tok>&left=<mac>&right=<mac>
      Drive the glasses through a bonded phone running DroidBridge (lets us reuse
      a phone that is already paired/bonded with the glasses).

  g2://local?left=<addr>&right=<addr>&addressType=[public|random]
      Drive the glasses directly from this machine's Bluetooth radio via bleak.
      addressType=public is a normal MAC ("D0:7A:47:82:09:67"); addressType=
      random is the macOS / CoreBluetooth peripheral-UUID style. (Local mode
      needs `pip install bleak`.)

Protocol (reverse-engineered + validated byte-for-byte against a real flash):
  transport: aa21 envelope  aa 21 seq len totFrags fragIdx sid flag <pb> crc16LE(last frag)
             CRC-16/CCITT-FALSE over the concatenated pb; chunkSize=232.
  DATA channel (svc e1001: write e0001 / notify e0002), sid byte = message type:
     sid 0xc0 control body=<opcode>[..]crc16: 0x00 begin, 0x01+128B EVENOTA
        subheader (FILE_CHECK), 0x02 data-block marker, 0x03 end.
     sid 0xc1 data: 4096-byte payload block (18 frags), CRC-16 on last.
     each write acked on notify as [opcode,status]; status 0 = OK else NAK.
  per-component CRC32C (MSB-first, init0, xorout0) is in the subheader, verified
  by the glasses on END.
  CTRL/EvenHub channel (svc e5450: write e5401 / notify e5402) carries the sid
  0x80 heartbeat ~15s — keep it alive during the transfer.

--stop-before gates the stages so a dry-run can't run past where we intend to stop.
"""
import time, json, struct, threading, queue, asyncio, sys, argparse
import urllib.request, urllib.parse

# channel = (service uuid, write char, notify char). Mapping by handle order:
DATA = ("00002760-08c2-11e1-9073-0e8ac72e1001",   # firmware data svc (handles 0x082x)
        "00002760-08c2-11e1-9073-0e8ac72e0001",   # write  0x0822
        "00002760-08c2-11e1-9073-0e8ac72e0002")   # notify 0x0824
CTRL = ("00002760-08c2-11e1-9073-0e8ac72e5450",   # EvenHub/heartbeat svc (handles 0x084x)
        "00002760-08c2-11e1-9073-0e8ac72e5401",   # write  0x0842
        "00002760-08c2-11e1-9073-0e8ac72e5402")   # notify 0x0844

# Expected firmware layout: exactly 5 segments, one of which is the main image.
EXPECTED_SEGMENTS = 5
REQUIRED_SEGMENT = "ota/s200_firmware_ota.bin"

# how far to go: 'discover' | 'heartbeat' | 'file_check' | 'flash' | 'done'
STAGES = ["discover", "heartbeat", "file_check", "flash", "done"]
def allowed(stage, stop_before): return STAGES.index(stage) < STAGES.index(stop_before)

# ---------------- framing (validated byte-for-byte vs capture) ----------------
def crc16(d):
    c=0xffff
    for b in d:
        c^=b<<8
        for _ in range(8): c=((c<<1)^0x1021)&0xffff if c&0x8000 else (c<<1)&0xffff
    return bytes([c&0xff,(c>>8)&0xff])
def crc32c_msb(buf,_t=[]):
    if not _t:
        for b in range(256):
            c=b<<24
            for _ in range(8): c=((c<<1)^0x1edc6f41)&0xffffffff if c&0x80000000 else (c<<1)&0xffffffff
            _t.append(c)
    crc=0
    for byte in buf: crc=((crc<<8)&0xffffffff)^_t[((crc>>24)^byte)&0xff]
    return crc
CHUNK=232
_seq=[0]
def _reset_seq(): _seq[0]=0
def _nextseq():
    _seq[0]=(_seq[0]+1)&0xff; return _seq[0]
def frames(sid,pb,flag=0x00):
    body=pb+crc16(pb); tot=max(1,-(-len(body)//CHUNK)); seq=_nextseq(); out=[];off=0
    for i in range(tot):
        ch=body[off:off+CHUNK];off+=len(ch)
        out.append(bytes([0xaa,0x21,seq,len(ch),tot,i+1,sid,flag])+ch)
    return out
def ctrl_frames(op,data=b''): return frames(0xc0,bytes([op])+data)
def data_frames(block):        return frames(0xc1,block)

# ---------------- firmware parsing / validation ----------------
def parse_firmware_segments(img):
    """Unpack the OTA container into its component segments. Returns a list of
    dicts: {eid, off, size, crc, sub(128B subheader), ps(payload size), fn(name)}."""
    if len(img) < 0x40:
        raise ValueError("file is too small to be a firmware image")
    n = struct.unpack_from('<I', img, 8)[0]
    if not (0 < n <= 64):
        raise ValueError(f"implausible component count {n} (corrupt header?)")
    segs = []
    for i in range(n):
        eid, off, size, crc = struct.unpack_from('<IIII', img, 0x40 + i*16)
        sub = img[off:off+128]
        if len(sub) < 128:
            raise ValueError(f"segment {i} subheader runs past end of file")
        ps = struct.unpack_from('<I', sub, 8)[0]
        fn = sub[48:128].split(b'\0')[0].decode('latin1')
        segs.append({'eid':eid,'off':off,'size':size,'crc':crc,'sub':sub,'ps':ps,'fn':fn})
    return segs

def validate_firmware(img):
    """Sanity-check that the file looks like a flashable G2 firmware image. Returns
    the parsed segments on success, raises ValueError describing the problem."""
    segs = parse_firmware_segments(img)
    names = [s['fn'] for s in segs]
    if len(segs) != EXPECTED_SEGMENTS:
        raise ValueError(
            f"expected {EXPECTED_SEGMENTS} segments, found {len(segs)}: {names}")
    if REQUIRED_SEGMENT not in names:
        raise ValueError(
            f"required segment {REQUIRED_SEGMENT!r} not found; segments are: {names}")
    return segs

# ---------------- DroidBridge client ----------------
class Bridge:
    def __init__(self, base, token):
        self.base=base.rstrip('/'); self.token=token
        self.notes=queue.Queue()      # (char_uuid_lower, bytes)
        self._stop=False
    def _req(self,path,obj=None,method=None):
        data=json.dumps(obj).encode() if obj is not None else None
        r=urllib.request.Request(self.base+path,data=data,method=method or ('POST' if data else 'GET'))
        if self.token: r.add_header('Authorization','Bearer '+self.token)
        if data: r.add_header('Content-Type','application/json')
        with urllib.request.urlopen(r,timeout=30) as resp: return resp.read()
    def status(self): return json.loads(self._req('/status'))
    def connect(self,a): return self._req('/connect',{"address":a})
    def discover(self,a): return self._req('/discover',{"address":a})
    def services(self,a): return json.loads(self._req('/services/'+a))
    def notify(self,a,svc,ch,en=True): return self._req('/notify',{"address":a,"service":svc,"characteristic":ch,"enable":en})
    def write(self,a,svc,ch,hexdata,wtype=1): return self._req('/write',{"address":a,"service":svc,"characteristic":ch,"data":hexdata,"writeType":wtype})
    def start_ws(self):
        import websocket
        self.ws_open=False
        def on_open(ws): self.ws_open=True
        def on_close(ws,*a): self.ws_open=False
        def on_msg(ws,msg):
            try:
                m=json.loads(msg)
                if m.get('type')=='notification':
                    d=m['data']; self.notes.put((d.get('characteristic','').lower(), bytes.fromhex(d.get('data',''))))
            except Exception: pass
        hdr=['Authorization: Bearer '+self.token] if self.token else None
        self.ws=websocket.WebSocketApp(self.base.replace('http','ws'),header=hdr,on_open=on_open,on_close=on_close,on_message=on_msg)
        threading.Thread(target=lambda: self.ws.run_forever(reconnect=3),daemon=True).start()
        def ka():
            while not self._stop:
                try: self.ws.send("ping")
                except Exception: pass
                time.sleep(1.5)
        threading.Thread(target=ka,daemon=True).start()

# ---------------- transports ----------------
# A transport is bound to a single lens address and exposes a uniform surface the
# flash routine drives: connect / discover / set_notify / write, plus a `notes`
# queue of (char_uuid_lower, bytes) notifications.

class DroidBridgeTransport:
    """Per-lens view onto a shared DroidBridge. Notifications arrive on the
    bridge's single websocket; since lenses are flashed one at a time, the shared
    queue is unambiguous."""
    def __init__(self, bridge, address):
        self.br=bridge; self.address=address; self.notes=bridge.notes
    def status(self):
        try: return f"droidbridge {self.br.base}: {self.br.status()}"
        except Exception as e: return f"droidbridge {self.br.base}: status failed ({e})"
    def connect(self):
        # fresh GATT state: stale notify/connection state makes begin time out
        try: self.br._req('/disconnect',{"address":self.address})
        except Exception: pass
        time.sleep(2)
        self.br.connect(self.address); time.sleep(2)
    def discover(self):
        self.br.discover(self.address)
        for _ in range(20):
            try:
                s=self.br.services(self.address)
                if s and s.get('services'): return True
            except Exception: pass
            time.sleep(1)
        return False
    def set_notify(self, svc, ch, enable=True):
        self.br.notify(self.address, svc, ch, enable)
    def write(self, svc, ch, hexdata, wtype=1):
        self.br.write(self.address, svc, ch, hexdata, wtype)
    def close(self):
        try: self.br._req('/disconnect',{"address":self.address})
        except Exception: pass

class LocalBleTransport:
    """Direct connection over this machine's Bluetooth radio via bleak. bleak is
    async, so we run an event loop on a background thread and bridge each call
    across with run_coroutine_threadsafe."""
    def __init__(self, address, address_type=None):
        self.address=address; self.address_type=address_type
        self.notes=queue.Queue()
        self.client=None
        self._loop=asyncio.new_event_loop()
        self._thr=threading.Thread(target=self._run_loop, daemon=True)
        self._thr.start()
    def _run_loop(self):
        asyncio.set_event_loop(self._loop); self._loop.run_forever()
    def _call(self, coro): return asyncio.run_coroutine_threadsafe(coro, self._loop).result()
    def status(self):
        return f"local BLE {self.address}" + (f" ({self.address_type})" if self.address_type else "")
    def connect(self):
        from bleak import BleakClient
        kwargs={}
        # address_type ("public"/"random") is honored by the WinRT backend; macOS
        # CoreBluetooth and Linux BlueZ derive it from the address/scan instead.
        if self.address_type and sys.platform.startswith("win"):
            kwargs["address_type"]=self.address_type
        async def _c():
            self.client=BleakClient(self.address, **kwargs)
            await self.client.connect()
        self._call(_c())
    def discover(self):
        # bleak performs service discovery during connect()
        return bool(self.client and self.client.is_connected)
    def _on_note(self, fallback_ch):
        fb=fallback_ch.lower()
        def cb(sender, data):
            try: u=sender.uuid.lower()
            except Exception: u=fb
            self.notes.put((u, bytes(data)))
        return cb
    def set_notify(self, svc, ch, enable=True):
        async def _n():
            if enable: await self.client.start_notify(ch, self._on_note(ch))
            else: await self.client.stop_notify(ch)
        self._call(_n())
    def write(self, svc, ch, hexdata, wtype=1):
        data=bytes.fromhex(hexdata)
        # Android writeType 1 == WRITE_TYPE_NO_RESPONSE; anything else => with response.
        response=(wtype!=1)
        async def _w(): await self.client.write_gatt_char(ch, data, response=response)
        self._call(_w())
    def close(self):
        async def _d():
            if self.client and self.client.is_connected:
                await self.client.disconnect()
        try: self._call(_d())
        except Exception: pass
        self._loop.call_soon_threadsafe(self._loop.stop)

# ---------------- ack handling ----------------
DEBUG=False
def parse_rx(frame):
    """unwrap an aa12 reply envelope -> (sid, pb). pb is [opcode,status,...]."""
    if len(frame)>=10 and frame[0]==0xaa and frame[1]==0x12:
        ln=frame[3]; sid=frame[6]; pb=frame[8:8+max(0,ln-2)]
        return sid, pb
    return None, b''
def wait_ack(tp, want_op, ch_uuid, timeout=8):
    ch_uuid=ch_uuid.lower(); deadline=time.time()+timeout
    while time.time()<deadline:
        try: ch,frame=tp.notes.get(timeout=max(0.1,deadline-time.time()))
        except queue.Empty: break
        sid,pb=parse_rx(frame)
        if DEBUG: print(f"    [rx ...{ch[-4:]} sid=0x{sid:02x} pb={pb.hex()}]" if sid is not None else f"    [rx ...{ch[-4:]} {frame.hex()}]")
        if ch==ch_uuid and len(pb)>=2 and pb[0]==want_op: return pb[1]
    raise TimeoutError(f"no ack op=0x{want_op:02x} on {ch_uuid}")

def send_data_msg(tp, frames_list, want_op):
    svc,wch,nch=DATA
    for f in frames_list: tp.write(svc,wch,f.hex(),1)
    return wait_ack(tp, want_op, nch)

# ---------------- flash one lens ----------------
def flash_lens(tp, img, segs, stop_before):
    _reset_seq()
    print("status:", tp.status())
    tp.connect()
    ok=tp.discover()
    print("discovery:", "ok" if ok else "FAILED")
    if not ok:
        raise RuntimeError("service discovery failed")
    if not allowed("heartbeat", stop_before):
        print(f"[stop-before={stop_before}] discovery only; no writes."); return

    # enable notifications on the data + ctrl notify chars (give CCCD time to take)
    tp.set_notify(DATA[0],DATA[2],True)
    tp.set_notify(CTRL[0],CTRL[2],True)
    time.sleep(2.5)
    while not tp.notes.empty(): tp.notes.get()
    if not allowed("file_check", stop_before):
        print(f"[stop-before={stop_before}] notify set up; stopping before FILE_CHECK."); return

    # ---- (gated) actual flash ----
    # heartbeat keepalive on CTRL channel during the transfer (~12s, like the app)
    hb_stop=threading.Event()
    def hb_loop():
        while not hb_stop.wait(12):
            try:
                for f in frames(0x80, bytes.fromhex("080e10266a00")): tp.write(CTRL[0],CTRL[1],f.hex(),1)
            except Exception: pass
    threading.Thread(target=hb_loop,daemon=True).start()

    N=len(segs)
    print(f"flashing {len(img)}B, {N} components")
    while not tp.notes.empty(): tp.notes.get()          # drain stale notifications
    print("begin ack", send_data_msg(tp, ctrl_frames(0x00), 0x00))
    t_start=time.time()
    for i,seg in enumerate(segs):
        sub=seg['sub']; ps=seg['ps']; payload=img[seg['off']+128:seg['off']+128+ps]; fn=seg['fn']
        print(f"[{i}] FILE_CHECK {fn} ({ps}B crc32c=0x{crc32c_msb(payload):08x})")
        st=send_data_msg(tp, ctrl_frames(0x01, sub), 0x01)
        if st: hb_stop.set(); raise RuntimeError(f"FILE_CHECK NAK {st}")
        if not allowed("flash", stop_before):
            hb_stop.set(); print(f"[stop-before={stop_before}] FILE_CHECK acked; stopping before data blocks."); return
        nb=-(-len(payload)//4096)
        for b in range(nb):
            blk=payload[b*4096:(b+1)*4096]
            for tries in range(5):
                for f in ctrl_frames(0x02): tp.write(DATA[0],DATA[1],f.hex(),1)   # marker
                for f in data_frames(blk):  tp.write(DATA[0],DATA[1],f.hex(),1)   # 4 KB block
                try:
                    st=wait_ack(tp,0x02,DATA[2],timeout=8)
                    if st==0: break
                    print(f"   block {b} NAK={st} retry {tries}")
                except TimeoutError:
                    print(f"   block {b} ack-timeout retry {tries}")
            else:
                hb_stop.set(); raise RuntimeError(f"block {b} failed after retries")
            if b%50==0 or b==nb-1: print(f"   {fn}: block {b+1}/{nb}")
        print("   END ack", send_data_msg(tp, ctrl_frames(0x03), 0x03))
    hb_stop.set()
    print(f"=== all {N} components sent in {time.time()-t_start:.0f}s; glasses should verify + reboot ===")

# ---------------- connection string ----------------
def parse_connection_string(raw):
    """Parse g2://<method>?... into a dict. Methods: 'local', 'droidbridge'."""
    u=urllib.parse.urlparse(raw.strip())
    if u.scheme!='g2':
        raise ValueError(f"connection string must start with 'g2://', got {raw!r}")
    method=u.netloc.lower()
    q={k:v[0] for k,v in urllib.parse.parse_qs(u.query).items()}
    left=q.get('left'); right=q.get('right')
    if not left or not right:
        raise ValueError("connection string must include left= and right=")
    if method=='local':
        at=(q.get('addressType') or '').lower() or None
        if at not in (None,'public','random'):
            raise ValueError("addressType must be 'public' or 'random'")
        return {'method':'local','left':left,'right':right,'address_type':at}
    if method=='droidbridge':
        phone=q.get('phone'); port=q.get('port'); token=q.get('token','')
        if not phone or not port:
            raise ValueError("droidbridge connection string must include phone= and port=")
        return {'method':'droidbridge','left':left,'right':right,
                'base':f"http://{phone}:{port}",'token':token}
    raise ValueError(f"unknown connection method {method!r}; expected 'local' or 'droidbridge'")

# ---------------- warranty gate ----------------
WARRANTY_PHRASE="my warranty is void"
def confirm_warranty(skip):
    print("="*72)
    print("WARNING: flashing a custom firmware will VOID your G2's warranty and")
    print("carries a real risk of BRICKING the device. Proceed only if you")
    print("understand and accept that risk.")
    print("="*72)
    if skip:
        print('--my-warranty-is-void supplied; skipping interactive confirmation.')
        return
    try:
        resp=input(f'Type "{WARRANTY_PHRASE}" to continue: ')
    except (EOFError, KeyboardInterrupt):
        print("\nAborted."); sys.exit(1)
    if resp.strip()!=WARRANTY_PHRASE:
        print("Phrase did not match. Aborted."); sys.exit(1)

# ---------------- main ----------------
def main(argv=None):
    p=argparse.ArgumentParser(description="Flash firmware onto Even Realities G2 glasses.")
    p.add_argument('-c','--connection', required=True,
                   help="connection string: g2://droidbridge?phone=..&port=..&token=..&left=..&right=.. "
                        "or g2://local?left=..&right=..&addressType=public|random")
    p.add_argument('-f','--firmware', required=True, help="path to the firmware image to flash")
    p.add_argument('--lens', choices=['left','right','both'], default='both',
                   help="which lens to flash (default: both)")
    p.add_argument('--stop-before', choices=STAGES, default='done',
                   help="stop before this stage (dry-run gating; default: done = full flash)")
    p.add_argument('--my-warranty-is-void', action='store_true',
                   help="skip the interactive warranty confirmation (for automation)")
    p.add_argument('--debug', action='store_true', help="print received frames")
    args=p.parse_args(argv)

    global DEBUG; DEBUG=args.debug

    try:
        conn=parse_connection_string(args.connection)
    except ValueError as e:
        p.error(str(e))

    try:
        with open(args.firmware,'rb') as fh: img=fh.read()
    except OSError as e:
        print(f"cannot read firmware: {e}"); sys.exit(1)
    try:
        segs=validate_firmware(img)
    except ValueError as e:
        print(f"firmware validation failed: {e}"); sys.exit(1)
    print(f"firmware ok: {args.firmware} ({len(img)}B, {len(segs)} segments: {[s['fn'] for s in segs]})")

    confirm_warranty(args.my_warranty_is_void)

    sides=['right','left'] if args.lens=='both' else [args.lens]

    bridge=None
    if conn['method']=='droidbridge':
        bridge=Bridge(conn['base'], conn['token']); bridge.start_ws(); time.sleep(2)

    failures=[]
    for side in sides:
        addr=conn[side]
        print(f"\n=== flashing {side} lens ({addr}) ===")
        if conn['method']=='local':
            tp=LocalBleTransport(addr, conn.get('address_type'))
        else:
            tp=DroidBridgeTransport(bridge, addr)
        try:
            flash_lens(tp, img, segs, args.stop_before)
        except Exception as e:
            print(f"!!! {side} lens flash failed: {e}")
            failures.append(side)
        finally:
            tp.close()

    if bridge is not None:
        bridge._stop=True

    if failures:
        print(f"\nFAILED lenses: {failures}"); sys.exit(1)
    print("\nall selected lenses completed.")

if __name__=="__main__":
    main()
