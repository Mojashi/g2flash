#!/usr/bin/env python3
"""
Compile a C source to position-independent Thumb-2 machine code for the G2
mainapp core (ARMv7E-M, Cortex-M-class), verify it has NO relocations and no
external calls, and emit the raw .text bytes.

Usage: python3 build.py decompress.c [symbol]
Writes <stem>.o and prints, per exported function, its offset/size and the raw
bytes (hex) plus a Thumb disassembly for review.

Self-containedness is enforced: any relocation record or undefined symbol is a
hard error, because injected code cannot rely on the linker/loader to fix
addresses up.
"""
import sys, struct, subprocess, shutil

CLANG = "clang"
CFLAGS = [
    "--target=thumbv7em-none-eabi", "-mthumb",
    "-Os", "-ffreestanding", "-fno-jump-tables", "-fomit-frame-pointer",
    "-fno-builtin", "-mno-unaligned-access",
    "-fno-unwind-tables", "-fno-asynchronous-unwind-tables",
    "-Wall", "-Wextra",
]

# ---- minimal ELF32 LE parser (section headers + symtab) ----
def parse_elf(path):
    d = open(path, "rb").read()
    assert d[:4] == b"\x7fELF" and d[4] == 1 and d[5] == 1, "not ELF32-LE"
    (e_shoff,) = struct.unpack_from("<I", d, 0x20)
    e_shentsize, e_shnum, e_shstrndx = struct.unpack_from("<HHH", d, 0x2e)
    secs = []
    for i in range(e_shnum):
        off = e_shoff + i * e_shentsize
        name, typ, flags, addr, offset, size, link, info, align, entsz = \
            struct.unpack_from("<IIIIIIIIII", d, off)
        secs.append(dict(name=name, type=typ, flags=flags, offset=offset,
                         size=size, link=link, info=info, entsize=entsz))
    shstr = secs[e_shstrndx]
    def sname(n):
        s = d[shstr["offset"] + n:]
        return s[:s.index(b"\0")].decode()
    for s in secs:
        s["sname"] = sname(s["name"])
    return d, secs

def section(secs, name):
    for s in secs:
        if s["sname"] == name:
            return s
    return None

def main():
    args = sys.argv[1:]
    extra = [a for a in args if a.startswith("-")]   # e.g. -DFOO=0x1234
    src = next(a for a in args if not a.startswith("-"))
    stem = src.rsplit(".", 1)[0]
    obj = stem + ".o"
    subprocess.run([CLANG, *CFLAGS, *extra, "-c", src, "-o", obj], check=True)

    # 1) .text must have no relocations (other sections like .ARM.exidx don't
    #    matter — we only ever extract .text). Parse objdump -r block by block.
    rel = subprocess.run(["objdump", "-r", obj], capture_output=True, text=True).stdout
    cur, bad = None, []
    for ln in rel.splitlines():
        if "RELOCATION RECORDS FOR" in ln:
            cur = ln.split("[", 1)[1].split("]", 1)[0]
        elif cur == ".text" and ln.strip() and "OFFSET" not in ln:
            bad.append(ln)
    if bad:
        print("FAIL: .text has relocations (not position-independent):")
        print("\n".join(bad))
        sys.exit(1)

    d, secs = parse_elf(obj)
    text = section(secs, ".text")
    tbytes = d[text["offset"]:text["offset"] + text["size"]]

    # 2) no undefined symbols (external references)
    symtab = section(secs, ".symtab")
    strtab = secs[symtab["link"]]
    funcs = []
    undefs = []
    for i in range(symtab["size"] // 16):
        o = symtab["offset"] + i * 16
        st_name, st_value, st_size, st_info, st_other, st_shndx = \
            struct.unpack_from("<IIIBBH", d, o)
        nm = d[strtab["offset"] + st_name:]
        nm = nm[:nm.index(b"\0")].decode()
        typ = st_info & 0xf
        if st_shndx == 0 and nm:          # SHN_UNDEF with a name = external ref
            undefs.append(nm)
        if typ == 2:                      # STT_FUNC
            funcs.append((nm, st_value & ~1, st_size))
    if undefs:
        print("FAIL: undefined/external symbols referenced:", undefs)
        sys.exit(1)

    print(f"OK: {obj} .text = {len(tbytes)} bytes, no relocations, no external refs\n")
    for nm, val, sz in sorted(funcs, key=lambda x: x[1]):
        sz = sz or (len(tbytes) - val)
        b = tbytes[val:val + sz]
        print(f"== {nm}  (text+{val:#x}, {sz} bytes) ==")
        print("bytes:", b.hex())
        print()

    open(stem + ".text.bin", "wb").write(tbytes)
    print(f"wrote {stem}.text.bin ({len(tbytes)} bytes)")

if __name__ == "__main__":
    main()
