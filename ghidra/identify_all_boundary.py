# -*- coding: utf-8 -*-
# Identify ALL remaining boundary FUN_ functions.
# Decompile each, classify by pattern, name automatically.
#
# @category G2

from ghidra.program.model.symbol import SourceType
from ghidra.app.decompiler import DecompInterface
from collections import defaultdict
import re as re_mod

program = currentProgram
fm = program.getFunctionManager()
listing = program.getListing()

# LVGL style property table (expanded)
STYLE_PROPS = {
    0x01:'width',0x02:'min_width',0x03:'max_width',0x04:'height',0x05:'min_height',
    0x06:'max_height',0x07:'length',0x09:'x',0x0a:'y',0x0b:'align',
    0x0c:'transform_width',0x0d:'transform_height',0x0e:'translate_x',0x0f:'translate_y',
    0x10:'transform_scale_x',0x11:'transform_scale_y',0x12:'transform_rotation',
    0x13:'transform_pivot_x',0x14:'transform_pivot_y',0x15:'transform_skew_x',
    0x16:'transform_skew_y',0x17:'pad_top',0x18:'pad_bottom',0x19:'pad_left',
    0x1a:'pad_right',0x1b:'pad_row',0x1c:'pad_column',0x1d:'bg_opa',
    0x20:'bg_color',0x21:'bg_grad_color',0x22:'bg_grad_dir',0x23:'bg_main_stop',
    0x24:'bg_grad_stop',0x25:'bg_main_opa',0x26:'bg_grad_opa',0x27:'bg_grad',
    0x28:'bg_image_src',0x29:'bg_image_opa',0x2a:'bg_image_recolor',
    0x2b:'bg_image_recolor_opa',0x2c:'bg_image_tiled',
    0x30:'border_color',0x31:'border_opa',0x32:'border_width',0x33:'border_side',
    0x34:'border_post',0x36:'outline_width',0x37:'outline_color',0x38:'outline_opa',
    0x39:'outline_pad',0x40:'shadow_width',0x41:'shadow_offset_x',0x42:'shadow_offset_y',
    0x43:'shadow_spread',0x44:'shadow_color',0x45:'shadow_opa',
    0x48:'image_opa',0x49:'image_recolor',0x4a:'image_recolor_opa',
    0x50:'line_width',0x51:'line_dash_width',0x52:'line_dash_gap',0x53:'line_rounded',
    0x54:'line_color',0x55:'line_opa',0x56:'arc_width',0x57:'arc_rounded',
    0x58:'text_color',0x59:'text_opa',0x5a:'text_font',0x5b:'text_letter_space',
    0x5c:'text_line_space',0x5d:'text_decor',0x5e:'text_align',
    0x60:'radius',0x61:'clip_corner',0x62:'opa',0x63:'color_filter_dsc',
    0x64:'color_filter_opa',0x65:'anim',0x66:'anim_duration',0x67:'transition',
    0x68:'blend_mode',0x69:'layout',0x6a:'base_dir',0x70:'bitmap_mask_src',
    0x80:'rotary_sensitivity',
    0xc0:'flex_flow',0xc1:'flex_main_place',0xc2:'flex_cross_place',
    0xc3:'flex_track_place',0xc4:'flex_grow',
    0xc7:'grid_column_dsc_array',0xc8:'grid_column_align',0xc9:'grid_row_dsc_array',
    0xca:'grid_row_align',0xcb:'grid_cell_column_pos',0xcc:'grid_cell_x_align',
    0xcd:'grid_cell_column_span',0xce:'grid_cell_row_pos',0xcf:'grid_cell_y_align',
    0xd0:'grid_cell_row_span',
}

decomp = DecompInterface()
decomp.openProgram(program)

# Build even func set
even_funcs = set()
lib_named = set()
for func in fm.getFunctions(True):
    n = func.getName()
    if n.startswith('FUN_'):
        continue
    if n.startswith('lv_') or n.startswith('_lv_') or \
       any(n.startswith(p) for p in ['Att','Dm','Smp','Hci','Wsf','L2c','Svc','Sec','Bda',
           'am_hal','am_device','vTask','xTask','xQueue','vPort','pvPort',
           'memset','memcpy','memcmp','__aeabi','__iar','fw_memcpy','log_printf',
           'pb_encode','wsf_','FW_SIDE','fw_is','littlefs','lv_font','lv_strlen',
           'lv_snprintf','lv_strncmp','lv_color']):
        lib_named.add(n)
    else:
        even_funcs.add(n)

# Find boundary FUN_
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

# Sort by callers descending
sorted_boundary = sorted(boundary.items(), key=lambda x: -len(x[1]))

print("id_all: %d boundary FUN_ to process" % len(sorted_boundary))

identified = 0
classified = defaultdict(int)  # pattern -> count

# Known internal function addresses (already named but track for pattern)
SET_STYLE = 0x44ad80  # lv_obj_set_local_style_prop
GET_STYLE = 0x44ad1e  # lv_obj_get_style_prop

for fun_name, callers in sorted_boundary:
    func = None
    for f in fm.getFunctions(True):
        if f.getName() == fun_name:
            func = f
            break
    if not func or not func.getName().startswith('FUN_'):
        continue

    addr = func.getEntryPoint().getOffset()
    size = func.getBody().getNumAddresses()
    n_callers = len(callers)

    result = decomp.decompileFunction(func, 10, monitor)
    if not result or not result.decompileCompleted():
        classified['DECOMP_FAIL'] += 1
        continue
    c_code = result.getDecompiledFunction().getC()
    if not c_code:
        classified['NO_CODE'] += 1
        continue

    new_name = None
    pattern = 'UNKNOWN'

    # --- Pattern matching ---

    # P1: Style setter (calls set_local_style_prop with const prop ID)
    m = re_mod.search(r'(?:FUN_0044ad80|lv_obj_set_local_style_prop)\(\w+,(0x[0-9a-f]+|[0-9]+),', c_code)
    if m:
        val = m.group(1)
        prop_id = int(val, 16) if val.startswith('0x') else int(val)
        if prop_id in STYLE_PROPS:
            new_name = 'lv_obj_set_style_%s' % STYLE_PROPS[prop_id]
            pattern = 'STYLE_SETTER'

    # P2: Style getter (calls get_style_prop with const prop ID)
    if not new_name:
        m = re_mod.search(r'(?:FUN_0044ad1e|lv_obj_get_style_prop)\(\w+,\w+,(0x[0-9a-f]+|[0-9]+)\)', c_code)
        if m:
            val = m.group(1)
            prop_id = int(val, 16) if val.startswith('0x') else int(val)
            if prop_id in STYLE_PROPS:
                new_name = 'lv_obj_get_style_%s' % STYLE_PROPS[prop_id]
                pattern = 'STYLE_GETTER'

    # P3: Widget creator (calls lv_obj_class_create_obj)
    if not new_name and 'lv_obj_class_create_obj' in c_code:
        # Try to identify from class variable
        if 'lv_label' in c_code.lower() or addr == 0x4b1c96:
            new_name = 'lv_label_create'
        elif 'lv_image' in c_code.lower() or 'lv_img' in c_code.lower() or addr == 0x4b0ee8:
            new_name = 'lv_image_create'
        else:
            new_name = 'lv_widget_create_0x%x' % addr
        pattern = 'WIDGET_CREATE'

    # P4: Thin wrapper (size <= 10, single call + return)
    if not new_name and size <= 10:
        # Read the global or just return a value
        if 'return' in c_code and c_code.count('\n') <= 8:
            # Check if it returns a global (getter)
            m2 = re_mod.search(r'return\s+\*?DAT_([0-9a-f]+)', c_code)
            if m2:
                new_name = 'get_global_0x%s' % m2.group(1)
                pattern = 'GLOBAL_GETTER'
            elif '__aeabi_memcpy' in c_code or 'fw_memcpy' in c_code:
                new_name = 'fw_memcpy_0x%x' % addr
                pattern = 'MEMCPY_WRAPPER'

    # P5: memcpy/memset wrapper
    if not new_name:
        if size <= 40 and ('__aeabi_memcpy' in c_code or 'fw_memcpy' in c_code):
            new_name = 'fw_memcpy_0x%x' % addr
            pattern = 'MEMCPY_WRAPPER'
        elif size <= 40 and '__aeabi_memset' in c_code:
            new_name = 'fw_memset_0x%x' % addr
            pattern = 'MEMSET_WRAPPER'

    # P6: lv_obj_set_* (calls lv_obj_set_pos, lv_obj_set_size, etc.)
    if not new_name:
        for lv_func in ['lv_obj_set_pos', 'lv_obj_set_size', 'lv_obj_set_width',
                        'lv_obj_set_height', 'lv_obj_add_flag', 'lv_obj_remove_flag',
                        'lv_obj_add_state', 'lv_obj_remove_state', 'lv_obj_invalidate',
                        'lv_obj_set_parent', 'lv_obj_create', 'lv_obj_clean',
                        'lv_obj_delete', 'lv_obj_scroll_to', 'lv_obj_send_event']:
            if lv_func in c_code and size <= 60:
                new_name = '%s_wrapper_0x%x' % (lv_func, addr)
                pattern = 'LVGL_WRAPPER'
                break

    # P7: Even framework (page_manager, display_startup, etc.)
    if not new_name:
        if 'display_startup' in c_code or 'page_manager' in c_code:
            new_name = 'even_display_0x%x' % addr
            pattern = 'EVEN_DISPLAY'
        elif 'send_data_to_peer' in c_code or 'post_app_command' in c_code:
            new_name = 'even_sync_0x%x' % addr
            pattern = 'EVEN_SYNC'
        elif 'xQueueSend' in c_code or 'xQueue' in c_code:
            new_name = 'even_queue_0x%x' % addr
            pattern = 'EVEN_QUEUE'
        elif 'WsfBufAlloc' in c_code or 'WsfMsgEnq' in c_code:
            new_name = 'ble_msg_0x%x' % addr
            pattern = 'BLE_MSG'

    # P8: Pure Even app code (no library calls at all)
    if not new_name:
        has_lib_call = False
        for lib in lib_named:
            if lib in c_code:
                has_lib_call = True
                break
        if not has_lib_call:
            pattern = 'EVEN_INTERNAL'
            # Don't name these — they're Even's own code, not a boundary

    # P9: Catch-all for functions with library calls
    if not new_name and pattern == 'UNKNOWN':
        # Check which library it calls
        lib_calls = []
        for lib in lib_named:
            if lib in c_code:
                lib_calls.append(lib)
        if lib_calls:
            pattern = 'CALLS_LIB(%s)' % ','.join(lib_calls[:3])

    classified[pattern] += 1

    if new_name and func.getName().startswith('FUN_'):
        func.setName(new_name, SourceType.ANALYSIS)
        identified += 1

print("\nid_all: === RESULTS ===")
print("id_all: Identified: %d" % identified)
print("\nid_all: Pattern distribution:")
for pattern, count in sorted(classified.items(), key=lambda x: -x[1]):
    print("  %-30s %d" % (pattern, count))

# Final count
total = named = 0
for f in fm.getFunctions(True):
    total += 1
    if not f.getName().startswith('FUN_'):
        named += 1
print("\nid_all: TOTAL named=%d/%d (%.1f%%)" % (named, total, 100.0*named/total))

decomp.dispose()
