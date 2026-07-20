"""
Logic verification of the mode-runtime loader (runtime_main blob) + test payload
(mode_selftest blob) in Unicorn, with all firmware primitives stubbed by address.

Proves: rt_rx_hook LOAD_FRAG accumulates -> ACTIVATE verifies CRC + cache-maintains +
jumps into the loaded payload -> payload runs and sends its marker {0xA7,0xEE,lens} via
api_reply(FW_SEND) + fills the framebuffer canvas. Also tests PING.
No firmware image needed — only our blobs run; firmware calls are Python stubs.
"""
import struct, zlib
from unicorn import *
from unicorn.arm_const import *

REPO="/Users/mojashi/repos/odd/g2flash"
RT   = open(REPO+"/obj/runtime_main.text.bin","rb").read()
PAY  = open(REPO+"/obj/mode_selftest.text.bin","rb").read()

RT_BASE   = 0x10000000
HEAP      = 0x20300000; HEAP_SZ=0x100000  # in SRAM (0x2000_0000..0x207f_ffff) so runtime's rt_in_sram() passes
SCRATCH   = 0x12000000
STACK     = 0x13000000; STACK_TOP=STACK+0x80000
RAM       = 0x20000000; RAM_SZ=0x00200000
CANVAS    = 0x20180000; CANVAS_SZ=640*480//2
FWLO      = 0x00438000; FW_SZ=0x00072000     # firmware stub region (filler bx lr)
SCB       = 0xE000E000
SENT      = 0x0EED0000

# firmware even-entry addresses (ptr & ~1) that the blob calls
FW = {
 0x4991d8:"malloc", 0x49921c:"free", 0x49a01a:"send", 0x47ea6e:"side",
 0x43e0d8:"tick", 0x499614:"flush", 0x466a2a:"dispatch",
 0x43e3a2:"timer_new", 0x43e48a:"timer_start", 0x46d9de:"timer_stop",
}
RT_ANCHOR_A = 0x20003ffc
FB_CANVAS_PTR = 0x20074528
RUNTIME_SID = 0x7b

uc = Uc(UC_ARCH_ARM, UC_MODE_THUMB | UC_MODE_MCLASS)  # Cortex-M: decodes mrs/msr/cpsid/dsb/isb
for base,sz in [(RT_BASE,0x10000),(HEAP,HEAP_SZ),(SCRATCH,0x10000),(STACK,0x80000),
                (RAM,RAM_SZ),(FWLO,FW_SZ),(SCB,0x1000),(SENT&~0xFFF,0x1000)]:
    uc.mem_map(base,sz,UC_PROT_ALL)   # CANVAS is inside RAM (0x2000_0000..0x2020_0000)
uc.mem_write(RT_BASE, RT)
uc.mem_write(FWLO, b"\x70\x47"*(FW_SZ//2))   # bx lr filler
uc.mem_write(RAM, b"\x00"*0x1000)
def w32(a,v): uc.mem_write(a, struct.pack("<I",v&0xffffffff))
w32(RT_ANCHOR_A, 0)                  # cold boot: anchor = 0
w32(FB_CANVAS_PTR, CANVAS)           # canvas pointer -> our canvas buffer
uc.mem_write(CANVAS, b"\x00"*CANVAS_SZ)

heap_ptr=[HEAP]
sent=[]          # captured FW_SEND frames (type,sid,bytes)
timer_cb=[None]

def stub(u, addr, size, ud):
    a=addr & ~1
    name=FW.get(a)
    if name is None: return
    r0=u.reg_read(UC_ARM_REG_R0); r1=u.reg_read(UC_ARM_REG_R1)
    r2=u.reg_read(UC_ARM_REG_R2); r3=u.reg_read(UC_ARM_REG_R3)
    ret=0
    if name=="malloc":
        p=heap_ptr[0]; heap_ptr[0]=(p+r0+0xF)&~0xF; ret=p
    elif name=="free": ret=0
    elif name=="side": ret=1                     # transmit lens
    elif name=="tick": stub.t+=1; ret=stub.t
    elif name=="flush": ret=0
    elif name=="dispatch": ret=0                 # router no-op
    elif name=="send":                           # send(type,sid,ptr,len)
        try: data=bytes(u.mem_read(r2, r3)) if 0<r3<0x400 else b""
        except UcError: data=b""
        sent.append((r0,r1,data)); ret=0
    elif name=="timer_new": timer_cb[0]=r0; ret=0x7   # capture callback ptr, return fake handle
    elif name=="timer_start": ret=0
    elif name=="timer_stop": ret=0
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
        uc.emu_start(addr|1, SENT, timeout=5_000_000, count=5_000_000)
    except UcError as e:
        print("   !! emu error %s at pc=0x%x (last=0x%x)"%(e, uc.reg_read(UC_ARM_REG_PC), last_pc[0]))
    return uc.reg_read(UC_ARM_REG_R0)

RT_RX = RT_BASE + 0x0   # rt_rx_hook at offset 0

def send_cmd(cmd):
    uc.mem_write(SCRATCH, cmd)
    return call(RT_RX, [RUNTIME_SID, SCRATCH, len(cmd), 0])

print("=== 1) LOAD_FRAG the %d-byte payload ==="%len(PAY))
FRAG=180
idx=0; off=0
while off < len(PAY):
    chunk=PAY[off:off+FRAG]; last=1 if off+FRAG>=len(PAY) else 0
    cmd=bytes([0x01,0x00])+struct.pack("<H",idx)+bytes([last])+chunk
    send_cmd(cmd); off+=FRAG; idx+=1
print("  loaded %d fragments"%idx)

print("=== 2) ACTIVATE (with CRC32) ==="
      )
crc=zlib.crc32(PAY)&0xffffffff
sent.clear()
send_cmd(bytes([0x02,0x00])+struct.pack("<I",len(PAY))+struct.pack("<I",crc))
print("  frames sent during activate: %d"%len(sent))
for t,sid,data in sent:
    print("    send(type=%d,sid=0x%x): %s"%(t,sid,data.hex()))
marker=[d for (t,sid,d) in sent if sid==RUNTIME_SID and len(d)>=2 and d[0]==0xA7]
ok_marker = any(d[0]==0xA7 and d[1]==0xEE for d in marker)
print("  >>> payload marker {A7 EE ..} received:", ok_marker)

# check canvas got written
cv=bytes(uc.mem_read(CANVAS, 4096))
nonzero=sum(1 for b in cv if b)
print("  >>> canvas non-zero bytes in first 4KB: %d (payload drew a pattern)"%nonzero)

print("=== 3) PING ===")
sent.clear()
send_cmd(bytes([0x05]))
print("  ping reply frames:", [(hex(sid),d.hex()) for (t,sid,d) in sent])

print("\nRESULT:", "PASS" if ok_marker and nonzero>0 else "*** CHECK")
