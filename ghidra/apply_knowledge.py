# Ghidra headless script: apply our accumulated RE knowledge (function names, global labels,
# structs, signatures) to the g2fw program so the decompiler emits clean, human-readable C.
# Persists into the project (compounds across runs). Then re-decompiles a target set.
# Usage: analyzeHeadless <proj> g2fw -process g2_mainapp.bin -noanalysis \
#          -scriptPath <dir> -postScript apply_knowledge.py <out.c>
# @category CFW
from ghidra.app.decompiler import DecompInterface
from ghidra.util.task import ConsoleTaskMonitor
from ghidra.program.model.symbol import SourceType
from ghidra.program.model.data import StructureDataType, PointerDataType, UnsignedIntegerDataType, CategoryPath

fm = currentProgram.getFunctionManager()
af = currentProgram.getAddressFactory()
st = currentProgram.getSymbolTable()
dtm = currentProgram.getDataTypeManager()
listing = currentProgram.getListing()
mem = currentProgram.getMemory()
def A(h): return af.getAddress(h)

# ---- 0) define the RAM + peripheral memory map (a human's first step) ----
def ensure_block(name, base, size):
    a = A("0x%x"%base)
    if mem.getBlock(a) is not None:
        return
    try:
        b = mem.createUninitializedBlock(name, a, size, False)
        b.setRead(True); b.setWrite(True); b.setVolatile(name.startswith("PERIPH"))
        print("mapped %s @0x%x +0x%x"%(name,base,size))
    except:
        try:
            b = mem.createBitMappedBlock  # noop guard
        except: pass
        print("block %s create failed"%name)
ensure_block("SRAM", 0x20000000, 0x00800000)
ensure_block("PERIPH", 0x40000000, 0x00100000)
ensure_block("PPB",    0xE0000000, 0x00100000)

# ---- 1) function renames (+ where useful, treat as functions) ----
FUNCS = {
 # display-application framework
 0x443904:"display_startup", 0x4439e4:"display_refresh", 0x443ae4:"display_close",
 0x443bd0:"display_close_all", 0x4419ce:"dispatch_ui_event",
 0x441b9a:"register_all_foreground_ui_pages", 0x441cea:"init_ui_modules",
 0x442f00:"ui_display_thread_handler", 0x4422c4:"getStartUpAppID",
 0x441c68:"find_ui_DataHandler_by_id",
 0x45f4de:"page_manager_init", 0x45f74c:"page_manager_register",
 0x45fe2c:"page_manager_set_active", 0x45fbc4:"find_page_by_id",
 0x45fc54:"get_active_page", 0x45bf78:"is_terminal_active",
 # jbd micro-LED panel pipeline
 0x588c90:"jbd_flush", 0x588c5c:"jbd_present", 0x58973c:"jbd_powerup_mspi",
 0x5897c4:"jbd_powerdown_mspi", 0x589702:"jbd_refresh", 0x5893c6:"jbd_compose",
 0x589290:"jbd_plot", 0x4716c4:"lvgl_flush_cb", 0x44eb62:"lv_display_set_flush_cb",
 # per-app callbacks
 0x506174:"evenhub_dataCb", 0x506460:"evenhub_uiCb",
 0x5e5414:"terminal_dataCb", 0x5e5482:"terminal_uiCb",
 0x4b6614:"dashboard_dataCb", 0x4b6ee8:"dashboard_uiCb",
 0x5e8b00:"terminal_fsm_handler",
 # core primitives (from fw_2.2.4.34.h)
 0x472b6e:"fw_malloc", 0x472bb2:"fw_free", 0x47398c:"aa21_send",
 0x45a8ec:"lens_side", 0x448138:"get_tick_ms", 0x439be4:"fw_memcpy",
 0x448b0e:"xQueueSend", 0x448806:"mutex_lock", 0x44886c:"mutex_unlock",
}
nf=0
for addr,name in FUNCS.items():
    a=A("0x%x"%addr)
    f=fm.getFunctionAt(a) or fm.getFunctionContaining(a)
    if f is None:
        try: disassemble(a); f=createFunction(a,None)
        except: f=None
    if f is not None:
        try: f.setName(name, SourceType.USER_DEFINED); nf+=1
        except Exception as e: print("rename fail %s: %s"%(name,e))

# ---- 1b) stock LVGL v9.3 API names (from the naming workflow, wf_name_lvgl.js) ----
# 189 addr->name pairs generated into lvgl_funcs.py; applied here so the DB compounds.
nl=0
try:
    _g={}
    execfile("/private/tmp/claude-501/-Users-mojashi-repos-odd/70e4d562-4b1b-41ba-9eac-bd869645bc38/scratchpad/lvgl_funcs.py", _g)
    for addr,name in _g["LVGL_FUNCS"].items():
        a=A("0x%x"%addr)
        f=fm.getFunctionAt(a) or fm.getFunctionContaining(a)
        if f is None:
            try: disassemble(a); f=createFunction(a,None)
            except: f=None
        if f is not None:
            try: f.setName(name, SourceType.USER_DEFINED); nl+=1
            except Exception as e: print("lvgl rename fail %s: %s"%(name,e))
    print("applied %d LVGL names"%nl)
except Exception as e:
    print("lvgl_funcs merge failed: %s"%e)

# ---- 1c) firmware subsystem names (peer/sync, display power, foreground, burst) ----
nfw=0
try:
    _g2={}
    execfile("/private/tmp/claude-501/-Users-mojashi-repos-odd/70e4d562-4b1b-41ba-9eac-bd869645bc38/scratchpad/fw_funcs.py", _g2)
    for addr,name in _g2["FW_FUNCS"].items():
        a=A("0x%x"%addr)
        f=fm.getFunctionAt(a) or fm.getFunctionContaining(a)
        if f is None:
            try: disassemble(a); f=createFunction(a,None)
            except: f=None
        if f is not None:
            try: f.setName(name, SourceType.USER_DEFINED); nfw+=1
            except Exception as e: print("fw rename fail %s: %s"%(name,e))
    print("applied %d FW names"%nfw)
except Exception as e:
    print("fw_funcs merge failed: %s"%e)

# ---- 2) global labels (RAM) ----
GLOBALS = {
 0x20074410:"g_ui_module_count", 0x20066210:"g_ui_registry", 0x2007440c:"g_app_mgr_ctx",
 0x20074414:"g_base_app_id", 0x2007441c:"g_foreground_app_id", 0x20074418:"g_startup_state",
 0x20074464:"g_panel_canvas", 0x20074468:"g_clear_cb", 0x20074460:"g_mspi_handle",
 0x200745cc:"g_lvgl_drawbuf", 0x200745d0:"g_lv_display", 0x20074420:"g_display_queue",
 0x20073ac0:"g_display_ring", 0x20074424:"g_display_mutex", 0x20074408:"g_driver_vtable",
 0x200744a8:"g_page_list_root", 0x53304:"g_rt_state_anchor",
}
ng=0
for addr,name in GLOBALS.items():
    try: st.createLabel(A("0x%x"%addr), name, SourceType.USER_DEFINED); ng+=1
    except Exception as e: print("label fail %s: %s"%(name,e))

# ---- 3) app-entry struct (16B) + apply to the RAM registry ----
try:
    dt=dtm.getDataType("/app_entry_t")
    if dt is None:
        s=StructureDataType(CategoryPath("/"),"app_entry_t",0)
        u32=UnsignedIntegerDataType.dataType; p=PointerDataType(u32)
        s.add(u32,4,"applicationID",None)
        s.add(p,4,"dataCb",None); s.add(p,4,"uiCb",None); s.add(p,4,"cfg",None)
        dt=dtm.addDataType(s,None)
    # apply an array of 42 at the RAM registry so the decompiler shows entry[i].uiCb
    from ghidra.program.model.data import ArrayDataType
    arr=ArrayDataType(dt,42,dt.getLength())
    a=A("0x20066210")
    listing.clearCodeUnits(a, a.add(arr.getLength()-1), False)
    listing.createData(a, arr)
    print("app_entry_t[42] applied at 0x20066210")
except Exception as e:
    print("struct apply fail: %s"%e)

print("renamed %d funcs, %d globals"%(nf,ng))

# ---- 4) re-decompile the key display-framework functions to clean C ----
args=getScriptArgs()
outfile=args[0] if args else "/tmp/g2_clean.c"
TARGETS=[0x443904,0x4419ce,0x441b9a,0x45f74c,0x442f00,0x45fe2c,0x506460,0x5e5482]
di=DecompInterface(); di.openProgram(currentProgram); mon=ConsoleTaskMonitor()
out=open(outfile,"w")
for addr in TARGETS:
    f=fm.getFunctionAt(A("0x%x"%addr))
    if f is None: out.write("// no func 0x%x\n\n"%addr); continue
    res=di.decompileFunction(f,90,mon)
    if res and res.getDecompiledFunction():
        out.write("// ===== %s @ %s =====\n"%(f.getName(),f.getEntryPoint()))
        out.write(res.getDecompiledFunction().getC()); out.write("\n\n")
out.close()
print("clean C -> "+outfile)
