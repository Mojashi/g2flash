# Ghidra headless: cluster functions by the LVGL __FILE__ assert string they reference.
# For each target source file, find the path string in memory, get all references, map to the
# containing function. Emits a map file -> [ (func_addr, func_name, size) ] so we can see which
# functions live in lv_image.c / lv_label.c / lv_obj*.c etc, then decompile the chosen ones.
# @category CFW
from ghidra.program.model.symbol import RefType

fm = currentProgram.getFunctionManager()
af = currentProgram.getAddressFactory()
mem = currentProgram.getMemory()
listing = currentProgram.getListing()

args = getScriptArgs()
outfile = args[0] if args else "/tmp/lvgl_clusters.txt"

# The files whose API we most want to locate.
TARGET_SUBSTR = [
    "lv_image.c", "lv_label.c", "lv_obj.c", "lv_obj_pos.c", "lv_obj_tree.c",
    "lv_obj_class.c", "lv_obj_style.c", "lv_ambiq_display.c", "lv_display.c",
    "lv_draw_buf.c", "lv_image_decoder.c", "lv_draw_ambiq_img.c", "lv_refr.c",
    "lv_draw_ambiq_buffer.c", "lv_draw_ambiq.c",
]

# Find candidate string addresses by scanning defined strings and raw bytes.
def find_string_addrs(substr):
    hits = []
    # scan defined data for strings containing substr
    di = listing.getDefinedData(True)
    needle = substr
    for d in di:
        try:
            v = d.getValue()
        except:
            v = None
        if v is not None:
            s = str(v)
            if needle in s and s.rstrip().endswith(".c"):
                hits.append(d.getAddress())
    return hits

out = open(outfile, "w")
for sub in TARGET_SUBSTR:
    addrs = find_string_addrs(sub)
    out.write("### FILE %s  (%d string hit(s))\n" % (sub, len(addrs)))
    funcs = {}
    for sa in addrs:
        refs = getReferencesTo(sa)
        for r in refs:
            fa = r.getFromAddress()
            f = fm.getFunctionContaining(fa)
            if f is not None:
                funcs[f.getEntryPoint().toString()] = (f.getName(), f.getBody().getNumAddresses())
    for ent in sorted(funcs.keys()):
        nm, sz = funcs[ent]
        out.write("  0x%s  %-40s  %dB\n" % (ent, nm, sz))
    out.write("\n")
out.close()
print("clusters -> " + outfile)
