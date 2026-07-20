# -*- coding: utf-8 -*-
# Identify all remaining CALLS_LIB boundary functions.
# For each: decompile, extract the library functions it calls,
# and infer its name from the call pattern.
#
# @category G2

from ghidra.program.model.symbol import SourceType
from ghidra.app.decompiler import DecompInterface
from collections import defaultdict
import re as re_mod

program = currentProgram
fm = program.getFunctionManager()
listing = program.getListing()

decomp = DecompInterface()
decomp.openProgram(program)

# Collect all named functions
named_funcs = {}
for func in fm.getFunctions(True):
    n = func.getName()
    if not n.startswith('FUN_'):
        named_funcs[n] = func

# Identify Even vs Library
even_funcs = set()
lib_named = set()
for n in named_funcs:
    if n.startswith('lv_') or n.startswith('_lv_') or \
       any(n.startswith(p) for p in ['Att','Dm','Smp','Hci','Wsf','L2c','Svc','Sec','Bda',
           'am_hal','am_device','vTask','xTask','xQueue','vPort','pvPort',
           'memset','memcpy','memcmp','__aeabi','__iar','fw_memcpy','fw_memset',
           'log_printf','log_get','pb_encode','wsf_','FW_SIDE','fw_is',
           'littlefs','lv_font','lv_strlen','lv_snprintf','lv_strncmp','lv_color',
           'lv_obj_set_style','lv_obj_get_style','lv_label_create','lv_image_create',
           'lv_obj_set_local','lv_obj_set_x','lv_obj_scroll','lv_timer','ble_msg',
           'even_display','even_sync','even_queue','get_global','lv_widget']):
        lib_named.add(n)
    else:
        even_funcs.add(n)

# Find remaining boundary FUN_ (called by Even, NOT yet named, calls library)
boundary = defaultdict(set)
for func in fm.getFunctions(True):
    if func.getName() not in even_funcs:
        continue
    for cu in listing.getCodeUnits(func.getBody(), True):
        if hasattr(cu, 'getMnemonicString'):
            mn = cu.getMnemonicString()
            if mn and mn.lower() in ('bl', 'blx'):
                for ref in cu.getReferencesFrom():
                    if ref.getReferenceType().isCall():
                        t = fm.getFunctionAt(ref.getToAddress())
                        if t and t.getName().startswith('FUN_'):
                            boundary[t.getName()].add(func.getName())

# For each boundary FUN_, get its callees
targets = []
for fun_name, callers in sorted(boundary.items(), key=lambda x: -len(x[1])):
    func = None
    for f in fm.getFunctions(True):
        if f.getName() == fun_name:
            func = f
            break
    if not func:
        continue

    # Get named callees
    callees = set()
    for cu in listing.getCodeUnits(func.getBody(), True):
        if hasattr(cu, 'getMnemonicString'):
            mn = cu.getMnemonicString()
            if mn and mn.lower() in ('bl', 'blx'):
                for ref in cu.getReferencesFrom():
                    if ref.getReferenceType().isCall():
                        t = fm.getFunctionAt(ref.getToAddress())
                        if t and not t.getName().startswith('FUN_'):
                            callees.add(t.getName())

    lib_callees = callees & lib_named
    if lib_callees:
        targets.append((fun_name, len(callers), func, lib_callees))

print("id_lib: %d remaining CALLS_LIB boundary functions" % len(targets))

# Decompile and classify each
identified = 0
output_lines = []

for fun_name, n_callers, func, lib_callees in targets:
    addr = func.getEntryPoint().getOffset()
    size = func.getBody().getNumAddresses()

    result = decomp.decompileFunction(func, 10, monitor)
    if not result or not result.decompileCompleted():
        continue
    c_code = result.getDecompiledFunction().getC()
    if not c_code:
        continue

    new_name = None

    # Classify by dominant library call pattern
    lv_calls = [c for c in lib_callees if c.startswith('lv_')]
    ble_calls = [c for c in lib_callees if any(c.startswith(p) for p in ['Att','Dm','Smp','Hci','Wsf','L2c','Svc','ble_msg'])]
    hal_calls = [c for c in lib_callees if c.startswith('am_hal') or c.startswith('am_device')]
    rtos_calls = [c for c in lib_callees if any(c.startswith(p) for p in ['xQueue','vTask','xTask','vPort'])]
    mem_calls = [c for c in lib_callees if any(c.startswith(p) for p in ['memcpy','memset','fw_memcpy','fw_memset','__aeabi_mem'])]

    # Style setter/getter already handled by previous script, skip

    # Infer name from call pattern
    if lv_calls and not new_name:
        if 'lv_anim_init' in lib_callees and 'lv_anim_start' in lib_callees:
            new_name = 'even_start_anim_0x%x' % addr
        elif 'lv_obj_set_size' in lib_callees or 'lv_obj_set_width' in lib_callees:
            new_name = 'even_ui_layout_0x%x' % addr
        elif 'lv_label_set_text' in lib_callees or 'lv_label_set_text_fmt' in lib_callees:
            new_name = 'even_set_text_0x%x' % addr
        elif 'lv_image_set_src' in lib_callees:
            new_name = 'even_set_image_0x%x' % addr
        elif 'lv_obj_add_event_cb' in lib_callees:
            new_name = 'even_add_event_0x%x' % addr
        elif 'lv_obj_invalidate' in lib_callees:
            new_name = 'even_invalidate_0x%x' % addr
        elif 'lv_obj_delete' in lib_callees or 'lv_obj_clean' in lib_callees:
            new_name = 'even_cleanup_0x%x' % addr
        elif any('set_style' in c for c in lv_calls):
            new_name = 'even_apply_style_0x%x' % addr
        elif 'lv_obj_scroll' in ' '.join(lv_calls):
            new_name = 'even_scroll_0x%x' % addr
        else:
            # Generic LVGL wrapper — use the most distinctive callee
            main_call = sorted(lv_calls, key=len)[-1]  # longest name = most specific
            short = main_call.replace('lv_obj_', '').replace('lv_', '')
            new_name = 'lvgl_%s_0x%x' % (short[:20], addr)

    elif ble_calls and not new_name:
        if 'WsfBufAlloc' in lib_callees:
            new_name = 'ble_alloc_msg_0x%x' % addr
        elif 'WsfMsgEnq' in lib_callees:
            new_name = 'ble_enqueue_0x%x' % addr
        elif 'DmConn' in ' '.join(ble_calls):
            new_name = 'ble_conn_0x%x' % addr
        else:
            new_name = 'ble_func_0x%x' % addr

    elif hal_calls and not new_name:
        if 'am_hal_interrupt_master_disable' in lib_callees:
            new_name = 'hal_critical_0x%x' % addr
        else:
            main = sorted(hal_calls, key=len)[-1]
            short = main.replace('am_hal_', '').replace('am_devices_', '')
            new_name = 'hal_%s_0x%x' % (short[:20], addr)

    elif rtos_calls and not new_name:
        new_name = 'rtos_op_0x%x' % addr

    elif mem_calls and not new_name:
        if size <= 60:
            new_name = 'mem_op_0x%x' % addr
        else:
            new_name = 'data_proc_0x%x' % addr

    elif not new_name:
        # Calls only log/misc
        if 'log_printf' in lib_callees and len(lib_callees) <= 2:
            new_name = 'logged_op_0x%x' % addr
        else:
            new_name = 'lib_call_0x%x' % addr

    if new_name and func.getName().startswith('FUN_'):
        func.setName(new_name, SourceType.ANALYSIS)
        identified += 1

    output_lines.append((n_callers, fun_name, new_name or '?', sorted(lib_callees)[:3], size))

print("\nid_lib: Identified: %d/%d" % (identified, len(targets)))

# Show top results
print("\nid_lib: Top identified boundary functions:")
for nc, fn, nn, lc, sz in sorted(output_lines, key=lambda x: -x[0])[:30]:
    print("  %3d callers  %4dB  %s -> %s  calls=%s" % (nc, sz, fn, nn, lc))

# Final count
total = named = 0
for f in fm.getFunctions(True):
    total += 1
    if not f.getName().startswith('FUN_'):
        named += 1
print("\nid_lib: FINAL named=%d/%d (%.1f%%)" % (named, total, 100.0*named/total))

decomp.dispose()
