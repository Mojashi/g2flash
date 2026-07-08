#!/usr/bin/env python3
"""
Compile a C source to position-independent Thumb-2 machine code for the G2
mainapp core (ARMv7E-M, Cortex-M-class), verify it has NO relocations and no
external calls, and emit the raw .text bytes.

Usage:
  python3 build.py <src.c> [-Dname=val ...]           # human report + <stem>.text.bin
  python3 build.py <src.c> [-Dname=val ...] --json     # machine-readable JSON to stdout

Human mode prints, per exported function, its offset/size and the raw bytes (hex)
and writes <stem>.text.bin. JSON mode prints a single object:

  {
    "src": "zlib_glue.c",
    "text_len": 1394,
    "text": "<hex of the full .text section>",
    "functions": [{"name": "...", "offset": 0, "size": 14, "bytes": "<hex>"}, ...]
  }

so patch_compress.py can pull the exact bytes it injects straight from the build
instead of carrying pasted hex. --json has no side effects beyond the <stem>.o the
compiler emits (it does NOT write <stem>.text.bin).

Self-containedness is enforced in both modes. Intra-.text branch relocations
(R_ARM_THM_CALL / R_ARM_THM_JUMP24 to a symbol defined in .text) ARE resolved here
-- build.py acts as a mini-linker and rewrites the BL/B.W displacement -- so
injected functions can call each other by name (incl. from inline asm) without the
"everything must be static" restriction. Any OTHER relocation, or a branch to an
external/undefined symbol, is still a hard error, because PIC injection has no
linker to fix absolute addresses up (firmware entry points must be called via
absolute-constant function pointers instead).
"""
import sys, struct, subprocess, json

R_ARM_THM_CALL   = 10   # BL / BLX  (Thumb-2, 32-bit)
R_ARM_THM_JUMP24 = 30   # B.W       (Thumb-2, 32-bit)

def resolve_thumb_branch(tbytes, off, target):
    """Rewrite the Thumb-2 BL/B.W at tbytes[off:off+4] to branch to .text offset
    `target`, preserving the BL-vs-B.W opcode bits. Both are PC-relative to off+4."""
    hw2_old = tbytes[off + 2] | (tbytes[off + 3] << 8)
    disp = target - (off + 4)
    if disp % 2 or not (-(1 << 24) <= disp < (1 << 24)):
        raise BuildError(f"branch at {off:#x} -> {target:#x} out of Thumb range (disp {disp})")
    imm = (disp >> 1) & 0xFFFFFF
    S     = (imm >> 23) & 1
    i1    = (imm >> 22) & 1
    i2    = (imm >> 21) & 1
    imm10 = (imm >> 11) & 0x3FF
    imm11 = imm & 0x7FF
    j1 = (~(i1 ^ S)) & 1
    j2 = (~(i2 ^ S)) & 1
    hw1 = 0xF000 | (S << 10) | imm10
    hw2 = (hw2_old & 0xD000) | (j1 << 13) | (j2 << 11) | imm11   # keep bits 15/14(type)/12
    tbytes[off:off + 4] = bytes([hw1 & 0xFF, hw1 >> 8, hw2 & 0xFF, hw2 >> 8])

CLANG = "clang"
CFLAGS = [
    "--target=thumbv7em-none-eabi", "-mthumb",
    "-O2", "-ffreestanding", "-fno-jump-tables", "-fomit-frame-pointer",
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

class BuildError(Exception):
    pass

def compile_text(src, extra=()):
    """Compile `src` to Thumb-2 and return (text_bytes, funcs) where funcs is a
    list of (name, offset, size) with sizes resolved. Raises BuildError if the
    emitted .text has any relocation or the object references an external symbol.
    Sizes are resolved from st_size, falling back to the gap to the next function
    (or end of .text for the last one) when a symbol reports size 0."""
    stem = src.rsplit(".", 1)[0]
    obj = stem + ".o"
    subprocess.run([CLANG, *CFLAGS, *extra, "-c", src, "-o", obj], check=True)

    d, secs = parse_elf(obj)
    text = section(secs, ".text")
    text_idx = secs.index(text)
    tbytes = bytearray(d[text["offset"]:text["offset"] + text["size"]])

    # collect all symbols (name, value, size, type, section index)
    symtab = section(secs, ".symtab")
    strtab = secs[symtab["link"]]
    syms = []
    for i in range(symtab["size"] // 16):
        o = symtab["offset"] + i * 16
        st_name, st_value, st_size, st_info, st_other, st_shndx = \
            struct.unpack_from("<IIIBBH", d, o)
        nm = d[strtab["offset"] + st_name:]
        nm = nm[:nm.index(b"\0")].decode()
        syms.append(dict(name=nm, value=st_value, size=st_size,
                         typ=st_info & 0xf, shndx=st_shndx))

    # resolve .text relocations: intra-.text BL/B.W to a symbol defined in .text are
    # rewritten here (mini-linker); anything else is a hard error. `.rel.text` (REL,
    # 8-byte entries) is what clang emits for ARM; support `.rela.text` too.
    rel = section(secs, ".rel.text") or section(secs, ".rela.text")
    bad = []
    if rel:
        ent = 12 if rel["sname"].startswith(".rela") else 8
        for i in range(rel["size"] // ent):
            base = rel["offset"] + i * ent
            r_offset, r_info = struct.unpack_from("<II", d, base)
            r_type = r_info & 0xff
            sym = syms[r_info >> 8]
            if r_type in (R_ARM_THM_CALL, R_ARM_THM_JUMP24) and sym["shndx"] == text_idx:
                resolve_thumb_branch(tbytes, r_offset, sym["value"] & ~1)
            else:
                bad.append(f"  {r_offset:#08x} type={r_type} -> {sym['name']!r} "
                           f"(shndx={sym['shndx']}); only intra-.text BL/B.W resolvable")
    if bad:
        raise BuildError(f"{src}: unresolvable .text relocation(s) — call firmware "
                         f"entry points via absolute-constant fn-ptrs, not by name:\n"
                         + "\n".join(bad))

    # collect STT_FUNC symbols for the report / patch_compress
    raw_funcs = [(s["name"], s["value"] & ~1, s["size"]) for s in syms if s["typ"] == 2]
    # resolve sizes: st_size, else gap to next function, else end of .text
    raw_funcs.sort(key=lambda x: x[1])
    funcs = []
    for i, (nm, val, sz) in enumerate(raw_funcs):
        if not sz:
            nxt = raw_funcs[i + 1][1] if i + 1 < len(raw_funcs) else len(tbytes)
            sz = nxt - val
        funcs.append((nm, val, sz))
    return bytes(tbytes), funcs

def build_dict(src, extra=()):
    tbytes, funcs = compile_text(src, extra)
    return {
        "src": src,
        "text_len": len(tbytes),
        "text": tbytes.hex(),
        "functions": [
            {"name": nm, "offset": val, "size": sz, "bytes": tbytes[val:val + sz].hex()}
            for nm, val, sz in funcs
        ],
    }

def main():
    args = sys.argv[1:]
    as_json = "--json" in args
    args = [a for a in args if a != "--json"]
    extra = [a for a in args if a.startswith("-")]   # e.g. -DFOO=0x1234
    src = next(a for a in args if not a.startswith("-"))

    try:
        if as_json:
            print(json.dumps(build_dict(src, extra)))
            return
        tbytes, funcs = compile_text(src, extra)
    except BuildError as e:
        print("FAIL:", e)
        sys.exit(1)

    stem = src.rsplit(".", 1)[0]
    print(f"OK: {stem}.o .text = {len(tbytes)} bytes, intra-.text relocs resolved, no external refs\n")
    for nm, val, sz in sorted(funcs, key=lambda x: x[1]):
        b = tbytes[val:val + sz]
        print(f"== {nm}  (text+{val:#x}, {sz} bytes) ==")
        print("bytes:", b.hex())
        print()

    open(stem + ".text.bin", "wb").write(tbytes)
    print(f"wrote {stem}.text.bin ({len(tbytes)} bytes)")

if __name__ == "__main__":
    main()
