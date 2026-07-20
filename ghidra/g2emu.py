"""
g2emu.py -- Unicorn-based unit emulator for Even Realities G2 firmware (g2_2.2.4.34.bin).

The .bin is a flat MRAM/flash image that maps to ghidra_addr = file_offset + 0x39E680
(range 0x39E680 .. 0x78F187). It is a *partial* image: calls to addresses below
0x39E680 belong to other partitions we don't have, and mutable globals live in SRAM at
0x2000_0000+. We therefore do NOT boot from reset -- we call individual functions:
set r0..r3, point LR at a sentinel, and emu_start until the sentinel is reached.

Design decisions (see docs/terminal-protocol.md + the RECONSTRUCTED_*.md reports):
  * Everything in the image runs for REAL against SRAM we fully control. Functions like
    get_current_session_id / link_check just deref a RAM pointer -> we set the answer.
  * Only hardware/RTOS/log functions are stubbed (logging, BLE send, get_tick).
  * Calls that leave the image (addr < 0x39E680) are trapped by a ranged hook that
    records them and returns 0 cleanly (so we discover unknown externals instead of
    crashing).

Validated against real memcpy/memset (see test_g2emu.py).
"""
import struct
from unicorn import *
from unicorn.arm_const import *

IMG_PATH_DEFAULT = "/Users/mojashi/repos/odd/g2flash/g2_2.2.4.34.bin"
BASE = 0x39E680

# ---- memory map ----------------------------------------------------------
LOW_BASE     = 0x00001000                     # filler for below-image external calls
IMG_END      = 0x00790000                     # page-aligned end above 0x78F187
RAM_BASE     = 0x20000000
RAM_SIZE     = 0x00400000                     # 4MB SRAM window (covers 0x2006e0b0 etc.)
STACK_BASE   = 0x60000000
STACK_SIZE   = 0x00100000
STACK_TOP    = STACK_BASE + STACK_SIZE - 0x100
SCRATCH_BASE = 0x70000000                     # our own I/O buffers
SCRATCH_SIZE = 0x00100000
HEAP_BASE    = 0x71000000                     # bump allocator for malloc stubs
HEAP_SIZE    = 0x00800000
SENTINEL     = 0x50000000                     # LR target; emu stops when PC reaches it

# well-known firmware addresses (ghidra) -----------------------------------
LOG_LEVEL_CHECK = 0x0043d072   # returns bitmask; stub -> 0 disables all log branches
LOG_FMT         = 0x0043d514   # formatted deferred log; stub -> 0
LOG_COMPACT     = 0x0043ce46   # compact/binary log; stub -> 0
BLE_SEND_NOACK  = 0x0047398c   # aa21 send (arm, sid, ptr, len)
BLE_SEND_ACK    = 0x00473a92   # aa21 send w/ ack (arm, sid, ptr, len)
GET_TICK_MS     = 0x00448138   # monotonic ms tick


class G2Emu:
    def __init__(self, img_path=IMG_PATH_DEFAULT, trace=False):
        self.trace = trace
        self.data = open(img_path, "rb").read()
        self.uc = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
        self._map_memory()
        self.stubs = {}            # addr -> python fn(emu) ; fn may set r0 and/or pc
        self.watch = {}            # addr -> name ; record a pass-through hit, keep executing
        self.hits = []             # (name, r0, r1, r2, r3) recorded at watchpoints
        self.ext_calls = {}        # below-image addr -> hit count (discovered externals)
        self.ble_sends = []        # list of dict(sid, arm, data:bytes) captured on send
        self.fire_ui_events = []   # (event_id, arg) captured if fire_ui_event is stubbed
        self.tick = 1000
        self.heap_ptr = HEAP_BASE
        self.log = []              # freeform emulator log
        self._install_default_stubs()
        self._install_hooks()

    # ---- memory --------------------------------------------------------
    def _map_memory(self):
        uc = self.uc
        # one big block for filler + image
        uc.mem_map(LOW_BASE, IMG_END - LOW_BASE, UC_PROT_ALL)
        uc.mem_map(RAM_BASE, RAM_SIZE, UC_PROT_ALL)
        uc.mem_map(STACK_BASE, STACK_SIZE, UC_PROT_ALL)
        uc.mem_map(SCRATCH_BASE, SCRATCH_SIZE, UC_PROT_ALL)
        uc.mem_map(HEAP_BASE, HEAP_SIZE, UC_PROT_ALL)
        uc.mem_map(SENTINEL & ~0xFFF, 0x1000, UC_PROT_ALL)
        # fill below-image region with BX LR (0x4770) so stray external calls return
        bxlr = b"\x70\x47" * ((BASE - LOW_BASE) // 2)
        uc.mem_write(LOW_BASE, bxlr)
        # load the firmware image at its real base
        uc.mem_write(BASE, self.data)

    # ---- stubs ---------------------------------------------------------
    def _install_default_stubs(self):
        def ret0(emu):
            emu.uc.reg_write(UC_ARM_REG_R0, 0)
        self.stubs[LOG_LEVEL_CHECK] = ret0
        self.stubs[LOG_FMT] = ret0
        self.stubs[LOG_COMPACT] = ret0

        def ble_send(emu):
            u = emu.uc
            arm = u.reg_read(UC_ARM_REG_R0)
            sid = u.reg_read(UC_ARM_REG_R1)
            ptr = u.reg_read(UC_ARM_REG_R2)
            ln  = u.reg_read(UC_ARM_REG_R3)
            try:
                payload = u.mem_read(ptr, ln) if 0 < ln < 0x1000 else b""
            except UcError:
                payload = b"<unreadable>"
            emu.ble_sends.append({"arm": arm, "sid": sid, "data": bytes(payload)})
            u.reg_write(UC_ARM_REG_R0, 0)
        self.stubs[BLE_SEND_NOACK] = ble_send
        self.stubs[BLE_SEND_ACK] = ble_send

        def get_tick(emu):
            emu.tick += 1
            emu.uc.reg_write(UC_ARM_REG_R0, emu.tick)
        self.stubs[GET_TICK_MS] = get_tick

    def add_stub(self, addr, fn):
        """fn(emu) -> may read args via emu.uc.reg_read, set r0. Return handled automatically."""
        self.stubs[addr & ~1] = fn

    def add_watch(self, addr, name):
        """record a pass-through hit (name + r0-r3) when execution reaches addr; keeps running."""
        self.watch[addr & ~1] = name
        # install the hook lazily if emulation already started is unnecessary here;
        # hooks are one global code hook (see _install_hooks) so nothing else to do.

    # ---- hooks ---------------------------------------------------------
    def _install_hooks(self):
        uc = self.uc

        def hook_code(u, address, size, _):
            a = address & ~1
            # stubbed firmware function?
            fn = self.stubs.get(a)
            if fn is not None:
                fn(self)
                lr = u.reg_read(UC_ARM_REG_LR)
                u.reg_write(UC_ARM_REG_PC, lr)
                return
            # watchpoint: record args, keep executing the real function
            name = self.watch.get(a)
            if name is not None:
                self.hits.append((name,
                                  u.reg_read(UC_ARM_REG_R0), u.reg_read(UC_ARM_REG_R1),
                                  u.reg_read(UC_ARM_REG_R2), u.reg_read(UC_ARM_REG_R3)))
            if self.trace:
                self.log.append("pc=0x%x" % a)

        # main stub dispatch: fires every instruction but does a dict lookup only
        uc.hook_add(UC_HOOK_CODE, hook_code)

        # below-image external calls: record + clean return 0
        def hook_ext(u, address, size, _):
            a = address & ~1
            self.ext_calls[a] = self.ext_calls.get(a, 0) + 1
            u.reg_write(UC_ARM_REG_R0, 0)
            lr = u.reg_read(UC_ARM_REG_LR)
            u.reg_write(UC_ARM_REG_PC, lr)
        uc.hook_add(UC_HOOK_CODE, hook_ext, begin=LOW_BASE, end=BASE - 1)

        # surface memory faults instead of silent stops
        def hook_mem_invalid(u, access, address, size, value, _):
            self.log.append("MEM FAULT access=%d addr=0x%x size=%d value=0x%x pc=0x%x"
                            % (access, address, size, value, u.reg_read(UC_ARM_REG_PC)))
            return False  # let it raise
        uc.hook_add(UC_HOOK_MEM_READ_UNMAPPED | UC_HOOK_MEM_WRITE_UNMAPPED
                    | UC_HOOK_MEM_FETCH_UNMAPPED, hook_mem_invalid)

    # ---- convenience memory helpers -----------------------------------
    def rd(self, addr, n):
        return bytes(self.uc.mem_read(addr, n))

    def wr(self, addr, data):
        self.uc.mem_write(addr, bytes(data))

    def u32(self, addr):
        return struct.unpack("<I", self.rd(addr, 4))[0]

    def w32(self, addr, val):
        self.wr(addr, struct.pack("<I", val & 0xFFFFFFFF))

    def u8(self, addr):
        return self.rd(addr, 1)[0]

    def w8(self, addr, val):
        self.wr(addr, bytes([val & 0xFF]))

    def malloc(self, n):
        p = self.heap_ptr
        self.heap_ptr = (self.heap_ptr + n + 0xF) & ~0xF
        return p

    def scratch(self, data):
        """copy bytes into a fresh scratch buffer, return its address"""
        p = self.malloc_scratch(len(data) + 16)
        self.wr(p, data)
        return p

    _scr_ptr = SCRATCH_BASE
    def malloc_scratch(self, n):
        p = self._scr_ptr
        self._scr_ptr = (self._scr_ptr + n + 0xF) & ~0xF
        return p

    def follow_flash_ptr(self, flash_ptr_addr):
        """read a 32-bit pointer stored in the image and return it (e.g. a RAM global addr)."""
        return self.u32(flash_ptr_addr)

    # ---- calling -------------------------------------------------------
    def call(self, addr, args=(), timeout=5_000_000, count=2_000_000):
        """Call a Thumb function. args: up to 4 in r0-r3 (extend via stack if needed).
        Returns r0."""
        uc = self.uc
        regs = [UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3]
        for i in range(4):
            uc.reg_write(regs[i], args[i] if i < len(args) else 0)
        if len(args) > 4:
            # push extra args (right-to-left) onto stack
            extra = list(args[4:])
            sp = STACK_TOP & ~7
            for i, v in enumerate(extra):
                uc.mem_write(sp + i * 4, struct.pack("<I", v & 0xFFFFFFFF))
            uc.reg_write(UC_ARM_REG_SP, sp)
        else:
            uc.reg_write(UC_ARM_REG_SP, STACK_TOP & ~7)
        uc.reg_write(UC_ARM_REG_LR, SENTINEL | 1)
        self.ble_sends = []
        self.fire_ui_events = []
        self.hits = []
        try:
            uc.emu_start(addr | 1, SENTINEL, timeout=timeout, count=count)
        except UcError as e:
            pc = uc.reg_read(UC_ARM_REG_PC)
            raise RuntimeError("emu error %s at pc=0x%x; log tail=%s"
                               % (e, pc, self.log[-5:])) from e
        return uc.reg_read(UC_ARM_REG_R0)
