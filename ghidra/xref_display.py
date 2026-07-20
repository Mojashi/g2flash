# Ghidra headless: xref the display-framework anchors so we learn (a) how an app is OPENED
# (callers of display_startup) and (b) how the app cfg structs are initialized (writers of the
# .data cfg addresses / registry). Decompiles the callers of display_startup for the open idiom.
# @category CFW
from ghidra.app.decompiler import DecompInterface
from ghidra.util.task import ConsoleTaskMonitor

fm = currentProgram.getFunctionManager()
af = currentProgram.getAddressFactory()
def A(h): return af.getAddress("0x%x" % h)

args = getScriptArgs()
outfile = args[0] if args else "/tmp/xref_display.c"
out = open(outfile, "w")

ANCHORS = {
  0x443904: "display_startup",
  0x45f74c: "page_manager_register",
  0x20066210: "g_ui_registry",
  0x20074410: "g_ui_module_count",
  0x20000b38: "evenhub_cfg",
  0x20003e30: "terminal_cfg",
  0x200005bc: "dashboard_cfg",
  0x6a6cc4:   "static_registry_table",
}

caller_funcs = set()
for addr, name in ANCHORS.items():
    out.write("### refs to %s (0x%x)\n" % (name, addr))
    try:
        refs = getReferencesTo(A(addr))
    except Exception as e:
        out.write("  (err %s)\n\n" % e); continue
    seen = []
    for r in refs:
        fa = r.getFromAddress()
        f = fm.getFunctionContaining(fa)
        fn = f.getName() if f else "?"
        fe = f.getEntryPoint().toString() if f else "?"
        rt = r.getReferenceType().toString()
        seen.append("  from 0x%s  %-14s in %s @%s" % (fa, rt, fn, fe))
        if f and name in ("display_startup",):
            caller_funcs.add(f.getEntryPoint().getOffset())
    # dedup keep order
    for line in seen[:40]:
        out.write(line + "\n")
    out.write("  (%d refs total)\n\n" % len(seen))

# decompile the callers of display_startup to learn the open idiom
di = DecompInterface(); di.openProgram(currentProgram); mon = ConsoleTaskMonitor()
out.write("\n\n===== decompiled callers of display_startup =====\n\n")
for ep in sorted(caller_funcs):
    f = fm.getFunctionAt(A(ep))
    if not f: continue
    try:
        res = di.decompileFunction(f, 60, mon)
        c = res.getDecompiledFunction().getC() if (res and res.getDecompiledFunction()) else "// fail\n"
    except Exception as e:
        c = "// exc %s\n" % e
    out.write("// ---- %s @ 0x%x ----\n%s\n\n" % (f.getName(), ep, c))
out.close()
print("xref -> " + outfile)
