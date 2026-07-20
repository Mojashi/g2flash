"""Validate g2emu against known-answer firmware functions."""
import struct
from g2emu import G2Emu, BASE

MEMCPY = 0x00439c04   # memcpy(dst, src, n)
MEMSET = 0x0043c0e4   # memset(dst, n, val)  (note arg order per disasm)
LINK_CHECK = 0x0047a9f6  # return (*(u8*)global & 0xc) == 0xc

def test_memcpy():
    e = G2Emu()
    src = e.malloc_scratch(64); dst = e.malloc_scratch(64)
    payload = bytes(range(32))
    e.wr(src, payload)
    e.wr(dst, b"\xAA" * 64)
    e.call(MEMCPY, [dst, src, 32])
    got = e.rd(dst, 32)
    assert got == payload, "memcpy FAIL: %s" % got.hex()
    # ensure it didn't overrun
    assert e.rd(dst + 32, 1) == b"\xAA", "memcpy overran"
    print("memcpy OK: copied %d bytes correctly" % 32)

def test_memset():
    e = G2Emu()
    dst = e.malloc_scratch(64)
    e.wr(dst, b"\x00" * 64)
    e.call(MEMSET, [dst, 20, 0xCD])  # memset(dst, n=20, val=0xCD)
    got = e.rd(dst, 22)
    assert got[:20] == b"\xCD" * 20, "memset FAIL body: %s" % got.hex()
    assert got[20:22] == b"\x00\x00", "memset overran: %s" % got.hex()
    print("memset OK: filled 20 bytes with 0xCD, no overrun")

def test_link_check_controllable():
    """Prove real firmware code runs against RAM we control: link_check reads a byte
    from a RAM global (addr stored in a flash literal). Setting it flips the result."""
    e = G2Emu()
    # ldr r0,[pc,#0x30] at 0x47a9f6: pc=align(0x47a9f6+4,4)=0x47a9f8, +0x30 = 0x47aa28
    lit_addr = 0x47aa28
    global_addr = e.u32(lit_addr)
    print("link_check reads global at 0x%x (from flash literal 0x%x)" % (global_addr, lit_addr))
    e.w8(global_addr, 0x00)
    r = e.call(LINK_CHECK)
    assert r == 0, "expected 0 when global=0, got %d" % r
    e.w8(global_addr, 0x0C)
    r = e.call(LINK_CHECK)
    assert r == 1, "expected 1 when global=0xC, got %d" % r
    e.w8(global_addr, 0xFF)  # (0xff & 0xc)==0xc -> 1
    r = e.call(LINK_CHECK)
    assert r == 1, "expected 1 when global=0xff, got %d" % r
    print("link_check OK: real code, answer controlled by RAM byte (host-link spoofable)")

if __name__ == "__main__":
    test_memcpy()
    test_memset()
    test_link_check_controllable()
    print("\nALL HARNESS VALIDATION TESTS PASSED")
