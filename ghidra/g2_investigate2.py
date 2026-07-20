from ghidra.app.decompiler import DecompInterface
from ghidra.util.task import ConsoleTaskMonitor

out = open("/tmp/g2_ghidra_report2.txt", "w")
def w(s): out.write(s + "\n")

monitor = ConsoleTaskMonitor()
program = currentProgram
fm = program.getFunctionManager()
af = program.getAddressFactory()

decomp = DecompInterface()
decomp.openProgram(program)

def a(h): return af.getAddress(h)

def decompile_at(addr_hex, label):
    w("=" * 78)
    w("### %s @ %s" % (label, addr_hex))
    fn = fm.getFunctionAt(a(addr_hex))
    if fn is None:
        fn = fm.getFunctionContaining(a(addr_hex))
    if fn is None:
        w("  (no function)")
        return
    w("  function: %s  range=%s-%s" % (fn.getName(), fn.getEntryPoint(), fn.getBody().getMaxAddress()))
    res = decomp.decompileFunction(fn, 60, monitor)
    if res.decompileCompleted():
        w(res.getDecompiledFunction().getC())
    else:
        w("  decompile FAILED: %s" % res.getErrorMessage())

# The real lv_layer_top / lv_layer_sys / lv_layer_bottom (found via Ghidra's own
# reference manager on the assert strings, NOT my earlier manual guess).
decompile_at("0044ebf2", "REAL lv_layer_top")
decompile_at("0044ec30", "REAL lv_layer_sys")
decompile_at("0044ec6c", "REAL lv_layer_bottom")

# terminal's input-handler + FSM registration (7 and 6 call sites passing the name
# strings as PARAMs -- likely real registration calls, not just logging).
decompile_at("005e82b0", "terminal input-handler registration (7x 'terminal_input_event_handler')")
decompile_at("005e8b00", "terminal FSM registration (6x 'terminal_ui_fsm_handler')")

# the sole caller of the input dispatcher -- is routing mode-based, or is the
# dispatcher THE single global entry point regardless of foreground app?
decompile_at("00442f00", "sole caller of input dispatcher FUN_004424a2")

out.close()
print("WROTE /tmp/g2_ghidra_report2.txt")
