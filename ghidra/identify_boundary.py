# -*- coding: utf-8 -*-
# Identify ALL boundary FUN_ functions called by Even's app code.
#
# Strategy:
# 1. Style setters: FUN_ that calls lv_obj_set_local_style_prop(obj, PROP_ID, val, sel)
#    -> prop ID determines the function name from LVGL style property table
# 2. Widget creators: FUN_ that calls lv_obj_class_create_obj with a specific class ptr
#    -> class ptr determines which widget (label, image, button, etc.)
# 3. Known patterns: memcpy wrapper, color_make, strncmp, etc.
# 4. Remaining: decompile and classify
#
# @category G2

from ghidra.program.model.symbol import SourceType
from ghidra.app.decompiler import DecompInterface
from collections import defaultdict
import re

program = currentProgram
fm = program.getFunctionManager()
listing = program.getListing()

# LVGL v9.3 style property ID -> name mapping
# From lv_style.h
STYLE_PROPS = {
    0x01: 'width', 0x02: 'min_width', 0x03: 'max_width',
    0x04: 'height', 0x05: 'min_height', 0x06: 'max_height',
    0x07: 'length', 0x09: 'x', 0x0a: 'y',
    0x0b: 'align', 0x0c: 'transform_width', 0x0d: 'transform_height',
    0x0e: 'translate_x', 0x0f: 'translate_y',
    0x10: 'transform_scale_x', 0x11: 'transform_scale_y',
    0x12: 'transform_rotation', 0x13: 'transform_pivot_x', 0x14: 'transform_pivot_y',
    0x15: 'transform_skew_x', 0x16: 'transform_skew_y',
    0x17: 'pad_top', 0x18: 'pad_bottom', 0x19: 'pad_left', 0x1a: 'pad_right',
    0x1b: 'pad_row', 0x1c: 'pad_column',
    0x1d: 'bg_opa',
    0x20: 'bg_color', 0x21: 'bg_grad_color', 0x22: 'bg_grad_dir',
    0x23: 'bg_main_stop', 0x24: 'bg_grad_stop',
    0x25: 'bg_main_opa', 0x26: 'bg_grad_opa', 0x27: 'bg_grad',
    0x28: 'bg_image_src', 0x29: 'bg_image_opa', 0x2a: 'bg_image_recolor',
    0x2b: 'bg_image_recolor_opa', 0x2c: 'bg_image_tiled',
    0x30: 'border_color', 0x31: 'border_opa', 0x32: 'border_width',
    0x33: 'border_side', 0x34: 'border_post',
    0x36: 'outline_width', 0x37: 'outline_color', 0x38: 'outline_opa',
    0x39: 'outline_pad',
    0x40: 'shadow_width', 0x41: 'shadow_offset_x', 0x42: 'shadow_offset_y',
    0x43: 'shadow_spread', 0x44: 'shadow_color', 0x45: 'shadow_opa',
    0x48: 'image_opa', 0x49: 'image_recolor', 0x4a: 'image_recolor_opa',
    0x50: 'line_width', 0x51: 'line_dash_width', 0x52: 'line_dash_gap',
    0x53: 'line_rounded', 0x54: 'line_color', 0x55: 'line_opa',
    0x56: 'arc_width', 0x57: 'arc_rounded', 0x58: 'arc_color', 0x59: 'arc_opa',
    0x55: 'line_opa',
    0x58: 'text_color', 0x59: 'text_opa', 0x5a: 'text_font',
    0x5b: 'text_letter_space', 0x5c: 'text_line_space',
    0x5d: 'text_decor', 0x5e: 'text_align',
    0x60: 'radius', 0x61: 'clip_corner',
    0x62: 'opa', 0x63: 'color_filter_dsc', 0x64: 'color_filter_opa',
    0x65: 'anim', 0x66: 'anim_duration', 0x67: 'transition',
    0x68: 'blend_mode', 0x69: 'layout',
    0x6a: 'base_dir',
    0x70: 'bitmap_mask_src',
    0x80: 'rotary_sensitivity',
    0xc0: 'flex_flow', 0xc1: 'flex_main_place', 0xc2: 'flex_cross_place',
    0xc3: 'flex_track_place', 0xc4: 'flex_grow',
    0xc7: 'grid_column_dsc_array', 0xc8: 'grid_column_align',
    0xc9: 'grid_row_dsc_array', 0xca: 'grid_row_align',
    0xcb: 'grid_cell_column_pos', 0xcc: 'grid_cell_x_align',
    0xcd: 'grid_cell_column_span', 0xce: 'grid_cell_row_pos',
    0xcf: 'grid_cell_y_align', 0xd0: 'grid_cell_row_span',
}

# Style GETTER prop IDs (same IDs, different function pattern)
# lv_obj_get_style_* calls lv_obj_get_style_prop(obj, part, PROP_ID)

print("identify: Setting up decompiler...")
decomp = DecompInterface()
decomp.openProgram(program)

# Find all Even-named functions
even_funcs = set()
lib_named = set()
for func in fm.getFunctions(True):
    n = func.getName()
    if n.startswith('FUN_'):
        continue
    if n.startswith('lv_') or n.startswith('_lv_') or \
       any(n.startswith(p) for p in ['Att','Dm','Smp','Hci','Wsf','L2c','Svc','Sec','Bda']) or \
       n.startswith('am_hal') or n.startswith('am_device') or \
       any(n.startswith(p) for p in ['vTask','xTask','xQueue','vPort','pvPort','memset','memcpy','__aeabi','__iar']):
        lib_named.add(n)
    else:
        even_funcs.add(n)

# Find all FUN_ called by Even code
def get_callees(func):
    result = []
    for cu in listing.getCodeUnits(func.getBody(), True):
        if hasattr(cu, 'getMnemonicString'):
            mn = cu.getMnemonicString()
            if mn and mn.lower() in ('bl', 'blx'):
                for ref in cu.getReferencesFrom():
                    if ref.getReferenceType().isCall():
                        t = fm.getFunctionAt(ref.getToAddress())
                        if t:
                            result.append(t.getName())
    return result

boundary_funs = defaultdict(set)
for func in fm.getFunctions(True):
    if func.getName() not in even_funcs:
        continue
    for callee in get_callees(func):
        if callee.startswith('FUN_'):
            boundary_funs[callee].add(func.getName())

print("identify: %d boundary FUN_ to identify" % len(boundary_funs))

# ---- Identify each FUN_ ----
identified = 0
total = 0

# Known addresses for key internal functions
SET_STYLE_PROP = None  # lv_obj_set_local_style_prop
GET_STYLE_PROP = None  # lv_obj_get_style_prop

# Find set_style_prop and get_style_prop by name
for func in fm.getFunctions(True):
    n = func.getName()
    if n == 'lv_obj_set_local_style_prop':
        SET_STYLE_PROP = func.getEntryPoint().getOffset()
    elif n == 'lv_obj_get_style_prop':
        GET_STYLE_PROP = func.getEntryPoint().getOffset()

# FUN_0044ad80 is called by many style setters - check if it's set_local_style_prop
# Actually check decompiled code pattern
print("identify: SET_STYLE_PROP=0x%x, GET_STYLE_PROP=0x%x" %
      (SET_STYLE_PROP or 0, GET_STYLE_PROP or 0))

# For each boundary FUN_, decompile and classify
results = []
for fun_name in sorted(boundary_funs.keys()):
    n_callers = len(boundary_funs[fun_name])
    total += 1

    func = None
    for f in fm.getFunctions(True):
        if f.getName() == fun_name:
            func = f
            break
    if not func:
        continue

    size = func.getBody().getNumAddresses()
    addr = func.getEntryPoint().getOffset()

    # Decompile
    result = decomp.decompileFunction(func, 15, monitor)
    if not result or not result.decompileCompleted():
        continue
    c_code = result.getDecompiledFunction().getC()
    if not c_code:
        continue

    new_name = None
    confidence = 'LOW'

    # Pattern 1: Style setter - calls FUN_0044ad80(obj, PROP_ID, value, selector)
    # or lv_obj_set_local_style_prop
    m = re.search(r'FUN_0044ad80\(\w+,(0x[0-9a-f]+),', c_code)
    if not m:
        m = re.search(r'lv_obj_set_local_style_prop\(\w+,(0x[0-9a-f]+),', c_code)
    if m:
        prop_id = int(m.group(1), 16)
        if prop_id in STYLE_PROPS:
            prop_name = STYLE_PROPS[prop_id]
            new_name = 'lv_obj_set_style_%s' % prop_name
            confidence = 'HIGH'

    # Pattern 2: Style getter - calls lv_obj_get_style_prop(obj, part, PROP_ID)
    if not new_name and GET_STYLE_PROP:
        m = re.search(r'lv_obj_get_style_prop\(\w+,\w+,(0x[0-9a-f]+)\)', c_code)
        if m:
            prop_id = int(m.group(1), 16)
            if prop_id in STYLE_PROPS:
                prop_name = STYLE_PROPS[prop_id]
                new_name = 'lv_obj_get_style_%s' % prop_name
                confidence = 'HIGH'

    # Pattern 3: Widget creator - calls lv_obj_class_create_obj
    if not new_name and 'lv_obj_class_create_obj' in c_code:
        # The class pointer determines the widget type
        # Can't easily determine from decompiled code, but we know from callers
        if addr == 0x4b1c96:
            new_name = 'lv_label_create'
            confidence = 'HIGH'
        elif addr == 0x4b0ee8:
            new_name = 'lv_image_create'
            confidence = 'HIGH'

    # Pattern 4: Known library functions
    if not new_name:
        # memcpy wrapper
        if size <= 10 and '__aeabi_memcpy' in c_code:
            new_name = 'fw_memcpy'
            confidence = 'MEDIUM'
        # strncmp
        elif 'param_1 < *param_2' in c_code and 'param_3 + -1' in c_code:
            new_name = 'lv_strncmp'
            confidence = 'HIGH'
        # color_make
        elif size <= 30 and 'CONCAT' in c_code and 'param_1 >> 0x10' in c_code:
            new_name = 'lv_color_make'
            confidence = 'MEDIUM'
        # lv_obj_scroll_to_y
        elif 'lv_obj_scroll_to' in c_code and 'param_2' in c_code:
            if 'FUN_0044d6d2' in c_code:
                new_name = 'lv_obj_scroll_to_y'
                confidence = 'HIGH'

    # Pattern 5: Style prop setter calling FUN_0044ad80 with variable prop
    if not new_name and 'FUN_0044ad80' in c_code and size <= 40:
        # Small function that wraps set_style with a fixed prop
        m = re.search(r'FUN_0044ad80\(\w+,(\d+),', c_code)
        if m:
            prop_id = int(m.group(1))
            if prop_id in STYLE_PROPS:
                new_name = 'lv_obj_set_style_%s' % STYLE_PROPS[prop_id]
                confidence = 'HIGH'

    if new_name:
        # Apply
        func.setName(new_name, SourceType.ANALYSIS)
        func.setComment("Boundary identified: %s [%s]" % (confidence, new_name))
        identified += 1
        if identified <= 60:
            print("identify: %s -> %s (%d callers, %dB) [%s]" %
                  (fun_name, new_name, n_callers, size, confidence))

    results.append({
        'addr': hex(addr),
        'name': fun_name,
        'new_name': new_name,
        'callers': n_callers,
        'size': size,
        'confidence': confidence if new_name else None,
    })

print("\nidentify: === DONE: %d/%d identified ===" % (identified, total))

# Show unidentified with high caller count
unidentified = [r for r in results if not r['new_name'] and r['callers'] >= 3]
print("\nidentify: Unidentified with 3+ callers: %d" % len(unidentified))
for r in sorted(unidentified, key=lambda x: -x['callers'])[:20]:
    print("  %3d callers  %4dB  %s" % (r['callers'], r['size'], r['addr']))

decomp.dispose()
