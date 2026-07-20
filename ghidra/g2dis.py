#!/usr/bin/env python3
"""G2 stock-firmware disassembly helper (Thumb-2 via capstone).

ghidra_addr = file_offset + DELTA  (DELTA verified against a known patch site).
Usage:
  g2dis.py verify
  g2dis.py dis <ghidra_hex_addr> <count>
  g2dis.py bytes <ghidra_hex_addr> <nbytes>
  g2dis.py words <ghidra_hex_addr> <nwords>     # dump as LE u32 (literal pools)
"""
import sys, struct
from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB, CS_MODE_LITTLE_ENDIAN

DELTA = 0x39E680
BIN = "/Users/mojashi/repos/odd/g2flash/g2_2.2.4.34.bin"
IMG = open(BIN, "rb").read()

md = Cs(CS_ARCH_ARM, CS_MODE_THUMB | CS_MODE_LITTLE_ENDIAN)
md.detail = False

def foff(addr): return addr - DELTA
def read_at(addr, n):
    o = foff(addr)
    return IMG[o:o+n]

def dis(addr, count):
    o = foff(addr)
    code = IMG[o:o + count*4 + 8]
    n = 0
    for insn in md.disasm(code, addr):
        b = insn.bytes.hex()
        print(f"  {insn.address:08x}: {b:<8} {insn.mnemonic:<8} {insn.op_str}")
        n += 1
        if n >= count: break

def verify():
    # patch_compress.py: (g2f(0x501062), "bd f8 2c 10", ...) with g2f=x-DELTA
    got = read_at(0x501062, 4).hex()
    print(f"DELTA={DELTA:#x}  @ghidra 0x501062 -> foff {foff(0x501062):#x} = {foff(0x501062)}")
    print(f"  expect bytes 'bdf82c10', got '{got}'  -> {'OK' if got=='bdf82c10' else 'MISMATCH'}")
    # also the two gesture sites
    for a, exp in [(0x4425ae, "28f049f8"), (0x4428de, "1df0cff9")]:
        g = read_at(a, 4).hex()
        print(f"  @ghidra {a:#x}: expect {exp}, got {g}  -> {'OK' if g==exp else 'MISMATCH'}")

def segs():
    n = struct.unpack_from('<I', IMG, 8)[0]
    print(f"container: {len(IMG)} bytes, {n} components")
    for i in range(n):
        off = struct.unpack_from('<I', IMG, 0x40 + i*16 + 4)[0]
        ps = struct.unpack_from('<I', IMG, off+8)[0]
        fn = IMG[off+48:off+128].split(b'\0')[0].decode('latin1')
        print(f"  [{i}] {fn:<28} payload={ps:>9} B ({ps/1024/1024:.2f} MB)  off={off:#x}")

def words(addr, n):
    o = foff(addr)
    for i in range(n):
        v = struct.unpack_from("<I", IMG, o + i*4)[0]
        print(f"  {addr+i*4:08x}: {v:08x}")

def strxref(s):
    """Find an ASCII string's ghidra addr, then every code literal (LE u32) that
    references it in the mainApp range -> pins the function(s) that use it."""
    b = s.encode("latin1")
    i = IMG.find(b)
    if i < 0:
        print(f"  NOT FOUND: {s!r}"); return
    saddr = i + DELTA
    print(f"  string {s!r}\n    @ ghidra 0x{saddr:08x} (file 0x{i:x})")
    tgt = struct.pack("<I", saddr)
    j = IMG.find(tgt); n = 0
    while j != -1:
        g = j + DELTA
        if 0x438000 <= g <= 0x800000:
            print(f"    xref literal @ ghidra 0x{g:08x}")
            n += 1
        j = IMG.find(tgt, j + 1)
    if n == 0:
        print("    (no absolute literal xref in mainApp range)")

def _movw_fields(hw1, hw2):
    imm4 = hw1 & 0xF
    i = (hw1 >> 10) & 1
    imm3 = (hw2 >> 12) & 7
    imm8 = hw2 & 0xFF
    rd = (hw2 >> 8) & 0xF
    return rd, (imm4 << 12) | (i << 11) | (imm3 << 8) | imm8

def movwt_xref(target, code_lo=0x438000, code_hi=0x790000):
    """Find movw/movt pairs in mainApp .text that construct the absolute address
    `target` (how IAR loads far rodata/format-string pointers). Prints code addrs."""
    lo16, hi16 = target & 0xffff, (target >> 16) & 0xffff
    o, fhi = code_lo - DELTA, min(code_hi - DELTA, len(IMG) - 8)
    hits = []
    while o < fhi - 8:
        hw1 = IMG[o] | (IMG[o+1] << 8)
        if (hw1 & 0xFBF0) == 0xF240:                    # movw
            rd, imm = _movw_fields(hw1, IMG[o+2] | (IMG[o+3] << 8))
            if imm == lo16:
                for d in range(4, 16, 2):               # movt within a few insns, same rd
                    h1 = IMG[o+d] | (IMG[o+d+1] << 8)
                    if (h1 & 0xFBF0) == 0xF2C0:         # movt
                        rd2, imm2 = _movw_fields(h1, IMG[o+d+2] | (IMG[o+d+3] << 8))
                        if rd2 == rd and imm2 == hi16:
                            hits.append(o + DELTA); break
        o += 2
    for h in hits:
        print(f"    movw/movt -> 0x{target:08x} @ ghidra 0x{h:08x}")
    if not hits:
        print(f"    (no movw/movt pair building 0x{target:08x})")
    return hits

def decode_bl(hw1, hw2):
    """Decode a Thumb-2 BL (T1) at (hw1,hw2); return signed displacement or None."""
    if (hw1 & 0xF800) != 0xF000: return None
    if (hw2 & 0xC000) != 0xC000: return None   # BL (not BLX)
    S = (hw1 >> 10) & 1
    imm10 = hw1 & 0x3FF
    j1 = (hw2 >> 13) & 1
    j2 = (hw2 >> 11) & 1
    imm11 = hw2 & 0x7FF
    i1 = (~(j1 ^ S)) & 1
    i2 = (~(j2 ^ S)) & 1
    imm = (S << 24) | (i1 << 23) | (i2 << 22) | (imm10 << 12) | (imm11 << 1)
    if imm & (1 << 24): imm -= (1 << 25)
    return imm

def calls_to(target, lo=0x438000, hi=None, ctx=10):
    """Scan mainApp range for every `bl target` (brute-force BL decode at each
    halfword), print the call site + `ctx` instructions after the call (to see
    what immediate the caller compares the result against)."""
    hi = hi or len(IMG) + DELTA
    o, fend = lo - DELTA, min(hi - DELTA, len(IMG) - 4)
    sites = []
    while o < fend:
        hw1 = IMG[o] | (IMG[o+1] << 8)
        hw2 = IMG[o+2] | (IMG[o+3] << 8)
        d = decode_bl(hw1, hw2)
        if d is not None:
            pc = o + DELTA
            if pc + 4 + d == target:
                sites.append(pc)
        o += 2
    print(f"  {len(sites)} call site(s) to 0x{target:08x}")
    for pc in sites:
        print(f"  --- call @ 0x{pc:08x} ---")
        dis(pc + 4, ctx)   # instructions right after the bl

def _try_str(addr, maxlen=60):
    o = foff(addr)
    if not (0 <= o < len(IMG)): return None
    b = IMG[o:o+maxlen]
    end = b.find(b"\0")
    if end < 3: return None
    s = b[:end]
    if all(0x20 <= c < 0x7f for c in s):
        return s.decode("latin1")
    return None

def tabledump(addr, nwords):
    """Print each word in [addr, addr+4*nwords) as: raw hex, and if it resolves to
    an ASCII string, its text; if it lands in mainApp code range, flag 'code?'."""
    for i in range(nwords):
        a = addr + i*4
        o = foff(a)
        if not (0 <= o+4 <= len(IMG)): break
        v = struct.unpack_from("<I", IMG, o)[0]
        tag = ""
        s = _try_str(v)
        if s is not None:
            tag = f'  str: "{s}"'
        elif 0x438000 <= v < 0x790000:
            tag = "  (code-range ptr?)"
        print(f"  {a:08x}: {v:08x}{tag}")

def carve(foff, n, out):
    open(out, "wb").write(IMG[foff:foff+n])
    print(f"carved {n} B from file 0x{foff:x} -> {out}")

def fwords(foff, n):
    for i in range(n):
        v = struct.unpack_from("<I", IMG, foff + i*4)[0]
        print(f"  +{i*4:04x} (0x{foff+i*4:x}): {v:08x}")

if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "verify": verify()
    elif cmd == "segs": segs()
    elif cmd == "dis": dis(int(sys.argv[2], 16), int(sys.argv[3]))
    elif cmd == "strxref": strxref(" ".join(sys.argv[2:]))
    elif cmd == "movwt": movwt_xref(int(sys.argv[2], 16))
    elif cmd == "calls": calls_to(int(sys.argv[2], 16), ctx=int(sys.argv[3]) if len(sys.argv) > 3 else 10)
    elif cmd == "table": tabledump(int(sys.argv[2], 16), int(sys.argv[3]))
    elif cmd == "carve": carve(int(sys.argv[2],16), int(sys.argv[3],16), sys.argv[4])
    elif cmd == "fwords": fwords(int(sys.argv[2],16), int(sys.argv[3]))
    elif cmd == "bytes": print(read_at(int(sys.argv[2],16), int(sys.argv[3])).hex())
    elif cmd == "words": words(int(sys.argv[2],16), int(sys.argv[3]))
