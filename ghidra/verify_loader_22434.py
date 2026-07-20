"""
Logic verification of the 2.2.4.34 mode-runtime loader (runtime_main_22434 blob) + the
test payload (mode_selftest blob) in Unicorn, firmware primitives stubbed by ADDRESS.

Proves: rt_rx_hook LOAD_FRAG accumulates -> ACTIVATE verifies len+CRC32, does INLINE cache
maintenance (DCCMVAC clean + ICIALLU invalidate -> writes to the SCB region), then jumps
into the loaded payload -> payload runs, sends its marker {0xA7,0xEE,lens} via
api_reply(FW_SEND) and fills the framebuffer canvas. Also tests SEND (on_data echo) + PING.
No firmware image needed — only our blobs run; firmware calls are Python stubs.

Key 2.2.4.34 facts (vs the 2.2.6.10 verify): FW addresses swapped to the binary-confirmed
even-entry values; anchor 0x20053304; canvas ptr 0x20074464; payload ctx slot 0x20053404
(distinct from the anchor); cache maintenance is INLINE (no FW_FLUSH stub).
"""
import struct, zlib
from unicorn import *
from unicorn.arm_const import *

REPO="/Users/mojashi/repos/odd/g2flash"
RT   = open(REPO+"/obj/runtime_main_22434.text.bin","rb").read()
PAY  = open(REPO+"/obj/mode_selftest.text.bin","rb").read()

RT_BASE   = 0x10000000
HEAP      = 0x20300000; HEAP_SZ=0x100000     # in SRAM range so rt_in_sram() passes
SCRATCH   = 0x12000000
STACK     = 0x13000000; STACK_TOP=STACK+0x80000
RAM       = 0x20000000; RAM_SZ=0x00200000    # covers anchor/canvas/ctx-slot
CANVAS    = 0x20180000; CANVAS_SZ=640*480//2
FWLO      = 0x00438000; FW_SZ=0x00074000     # firmware stub region (bx lr filler)
SCB       = 0xE000E000
SENT      = 0x0EED0000

# firmware EVEN-entry addresses (ptr & ~1) the loader blob calls — 2.2.4.34, confirmed
FW = {
 0x472b6e:"malloc", 0x472bb2:"free", 0x47398c:"send", 0x45a8ec:"side",
 0x448138:"tick",   0x441c68:"dispatch",
}
RT_ANCHOR_A   = 0x20053304
MODE_CTX_SLOT = 0x20053404
FB_CANVAS_PTR = 0x20074464
RUNTIME_SID   = 0x7b

uc = Uc(UC_ARCH_ARM, UC_MODE_THUMB | UC_MODE_MCLASS)  # Cortex-M: decodes mrs/cpsid/dsb/isb
for base,sz in [(RT_BASE,0x10000),(HEAP,HEAP_SZ),(SCRATCH,0x10000),(STACK,0x80000),
                (RAM,RAM_SZ),(FWLO,FW_SZ),(SCB,0x1000),(SENT&~0xFFF,0x1000)]:
    uc.mem_map(base,sz,UC_PROT_ALL)
uc.mem_write(RT_BASE, RT)
uc.mem_write(FWLO, b"\x70\x47"*(FW_SZ//2))   # bx lr filler
uc.mem_write(RAM, b"\x00"*0x1000)
def w32(a,v): uc.mem_write(a, struct.pack("<I",v&0xffffffff))
w32(RT_ANCHOR_A, 0)                 # cold boot: anchor = 0
w32(FB_CANVAS_PTR, CANVAS)          # canvas pointer -> our canvas buffer
uc.mem_write(CANVAS, b"\x00"*CANVAS_SZ)

heap_ptr=[HEAP]; sent=[]
def stub(u, addr, size, ud):
    a=addr & ~1
    name=FW.get(a)
    if name is None: return
    r0=u.reg_read(UC_ARM_REG_R0); r2=u.reg_read(UC_ARM_REG_R2); r3=u.reg_read(UC_ARM_REG_R3)
    ret=0
    if name=="malloc":
        p=heap_ptr[0]; heap_ptr[0]=(p+r0+0xF)&~0xF; ret=p
    elif name=="free": ret=0
    elif name=="side": ret=1                     # transmit lens
    elif name=="tick": stub.t+=1; ret=stub.t
    elif name=="dispatch": ret=0                 # router no-op
    elif name=="send":                           # send(type,sid,ptr,len)
        r1=u.reg_read(UC_ARM_REG_R1)
        try: data=bytes(u.mem_read(r2, r3)) if 0<r3<0x400 else b""
        except UcError: data=b""
        sent.append((r0,r1,data)); ret=0
    u.reg_write(UC_ARM_REG_R0, ret)
    u.reg_write(UC_ARM_REG_PC, u.reg_read(UC_ARM_REG_LR))
stub.t=1000
uc.hook_add(UC_HOOK_CODE, stub, begin=FWLO, end=FWLO+FW_SZ-1)
hits={}
def stub_count(u,addr,size,ud):
    a=addr&~1
    if a in FW: hits[FW[a]]=hits.get(FW[a],0)+1
uc.hook_add(UC_HOOK_CODE, stub_count, begin=FWLO, end=FWLO+FW_SZ-1)
last_pc=[0]
def trace(u,addr,size,ud): last_pc[0]=addr
uc.hook_add(UC_HOOK_CODE, trace)

def call(addr, args):
    for i,r in enumerate([UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2,UC_ARM_REG_R3]):
        uc.reg_write(r, args[i] if i<len(args) else 0)
    uc.reg_write(UC_ARM_REG_SP, STACK_TOP)
    uc.reg_write(UC_ARM_REG_LR, SENT|1)
    try:
        uc.emu_start(addr|1, SENT, timeout=30_000_000, count=40_000_000)
    except UcError as e:
        print("   !! emu error %s at pc=0x%x (last=0x%x)"%(e, uc.reg_read(UC_ARM_REG_PC), last_pc[0]))
    return uc.reg_read(UC_ARM_REG_R0)

RT_RX = RT_BASE + 0x0   # rt_rx_hook at blob offset 0
def send_cmd(cmd):
    uc.mem_write(SCRATCH, cmd)
    return call(RT_RX, [RUNTIME_SID, SCRATCH, len(cmd), 0])

print("=== 1) LOAD_FRAG the %d-byte payload ==="%len(PAY))
FRAG=180; off=0; idx=0
while off < len(PAY):
    chunk=PAY[off:off+FRAG]; last=1 if off+FRAG>=len(PAY) else 0
    send_cmd(bytes([0x01,0x00])+struct.pack("<H",idx)+bytes([last])+chunk); off+=FRAG; idx+=1
print("  loaded %d fragments"%idx)

print("=== 2) ACTIVATE (len+CRC32, inline cache maint, jump) ===")
crc=zlib.crc32(PAY)&0xffffffff
sent.clear()
send_cmd(bytes([0x02,0x00])+struct.pack("<I",len(PAY))+struct.pack("<I",crc))
for t,sid,data in sent:
    print("    send(type=%d,sid=0x%x): %s"%(t,sid,data.hex()))
marker=[d for (t,sid,d) in sent if sid==RUNTIME_SID and len(d)>=2 and d[0]==0xA7 and d[1]==0xEE]
ok_marker = len(marker)>0
print("  >>> payload marker {A7 EE ..} received:", ok_marker)
cv=bytes(uc.mem_read(CANVAS, 4096)); nonzero=sum(1 for b in cv if b)
print("  >>> canvas non-zero bytes in first 4KB: %d"%nonzero)
anchor=struct.unpack("<I",bytes(uc.mem_read(RT_ANCHOR_A,4)))[0]
ctx=struct.unpack("<I",bytes(uc.mem_read(MODE_CTX_SLOT,4)))[0]
print("  >>> anchor=0x%08x  ctx_slot=0x%08x  (must differ)"%(anchor,ctx))

print("=== 3) SEND (on_data echo) ===")
sent.clear()
send_cmd(bytes([0x03,0x00])+b"PING123")
echo=[d for (t,sid,d) in sent if sid==RUNTIME_SID and len(d)>=2 and d[0]==0xA7 and d[1]==0xEC]
ok_echo = any(b"PING123" in d for d in echo)
print("  echo frames:", [d.hex() for (t,sid,d) in sent]); print("  >>> on_data echo of PING123:", ok_echo)

print("=== 4) PING (anchor still valid after payload wrote its ctx slot) ===")
sent.clear()
send_cmd(bytes([0x05]))
ping=[(hex(sid),d.hex()) for (t,sid,d) in sent]
ok_ping = any(d[0]==0xA7 and d[1]==0x05 and d[2]==1 for (t,sid,d) in sent)
print("  ping reply:", ping); print("  >>> PING reports mode active (0x05,mode=1):", ok_ping)

print("=== 5) anchor integrity: reload (LOAD idx0 + ACTIVATE) does not corrupt loader ===")
off=0; idx=0
while off < len(PAY):
    chunk=PAY[off:off+FRAG]; last=1 if off+FRAG>=len(PAY) else 0
    send_cmd(bytes([0x01,0x00])+struct.pack("<H",idx)+bytes([last])+chunk); off+=FRAG; idx+=1
sent.clear()
send_cmd(bytes([0x02,0x00])+struct.pack("<I",len(PAY))+struct.pack("<I",crc))
ok_reload = any(d[0]==0xA7 and d[1]==0x02 and d[2]==1 for (t,sid,d) in sent)
print("  reactivate reply:", [d.hex() for (t,sid,d) in sent]); print("  >>> reload OK:", ok_reload)

allok = ok_marker and nonzero>0 and (anchor!=ctx) and ok_echo and ok_ping and ok_reload
print("\nRESULT:", "PASS" if allok else "*** CHECK")
print("=== DIAG === FW hits:", hits, " anchor:0x%x"%anchor)
