# -*- coding: utf-8 -*-
# Ghidra headless script: match FW functions to LVGL reference symbols.
#
# Strategy:
# 1. Find all LVGL __FILE__ strings in the FW (LV_ASSERT embeds these)
# 2. For each string, find all FW functions that reference it
# 3. Load the LVGL symbol list (name, size, source_file) from lvgl_symbols.txt
# 4. For functions in the same source file, match by:
#    a. Exact name match (function name appears as a string in the binary)
#    b. Size similarity (GCC vs IAR size ratio)
#    c. Position ordering within the same source file
# 5. For high-confidence matches, rename in the Ghidra DB
#
# Also uses a simpler approach: many LVGL API functions have their name
# as a string in the binary (from LV_ASSERT_MSG, debug logs, etc.).
# We can grep for "lv_*" strings and match to known symbols.
#
# @category G2
# @author Claude

import json
import os
import re
from ghidra.program.model.symbol import SourceType
from ghidra.program.model.listing import CodeUnit

program = currentProgram
listing = program.getListing()
mem = program.getMemory()
symtab = program.getSymbolTable()
refmgr = program.getReferenceManager()
fm = program.getFunctionManager()
base = program.getImageBase()

def addr(offset):
    return program.getAddressFactory().getDefaultAddressSpace().getAddress(offset)

def get_string_at(address):
    """Read a null-terminated string at address."""
    try:
        result = []
        for i in range(512):
            b = mem.getByte(address.add(i))
            if b == 0:
                break
            result.append(chr(b & 0xff))
        return ''.join(result)
    except:
        return None

# Step 1: Find all defined strings in the program that look like LVGL paths
print("match_lvgl: Step 1 - Finding LVGL __FILE__ strings...")

lvgl_file_strings = {}  # address -> relative path (e.g. "core/lv_obj.c")
lvgl_func_strings = {}  # address -> function name string (e.g. "lv_obj_create")

data_iter = listing.getDefinedData(True)
string_count = 0
for d in data_iter:
    if d.hasStringValue():
        s = d.getValue()
        if s and isinstance(s, (str, unicode if 'unicode' in dir(__builtins__) else str)):
            string_count += 1
            # LVGL __FILE__ path
            m = re.search(r'lvgl_v9\.3\\LVGL\\src\\(.+\.c)$', s.replace('/', '\\'))
            if m:
                rel = m.group(1).replace('\\', '/')
                lvgl_file_strings[d.getAddress()] = rel

            # LVGL function name strings (from LV_ASSERT or debug)
            if s.startswith('lv_') and not '\\' in s and not '/' in s and not ' ' in s and len(s) < 80:
                lvgl_func_strings[d.getAddress()] = s

print("match_lvgl:   Found %d LVGL __FILE__ strings, %d lv_* name strings (from %d total strings)" %
      (len(lvgl_file_strings), len(lvgl_func_strings), string_count))

# Step 2: Load reference symbols from compiled .o files
print("match_lvgl: Step 2 - Loading reference LVGL symbols...")

sym_file = os.path.join(os.path.dirname(os.path.abspath(sourceFile.getAbsolutePath())),
                        '..', '..', 'lv_port_ambiq', 'build_ref', 'lvgl_symbols.txt')
# Try alternate path
if not os.path.exists(sym_file):
    sym_file = '/Users/mojashi/repos/odd/lv_port_ambiq/build_ref/lvgl_symbols.txt'

ref_symbols = {}  # name -> (size_hex, source_file)
ref_by_file = {}  # source_file -> [(name, size_int)]

with open(sym_file, 'r') as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        parts = line.split('|')
        if len(parts) != 3:
            continue
        name, size_hex, obj_file = parts
        # Convert obj filename back to source path
        # src_core_lv_group.o -> core/lv_group.c
        src_path = obj_file.replace('.o', '.c').replace('src_', '', 1).replace('_', '/', obj_file.count('_') - 1)
        # Better: just map from the known .o naming convention
        # e.g. src_core_lv_obj.o was compiled from src/core/lv_obj.c
        # The obj file name is the source path with / replaced by _ and src/ prefix
        # We need to reconstruct the path
        ref_symbols[name] = (int(size_hex, 16), src_path)
        if src_path not in ref_by_file:
            ref_by_file[src_path] = []
        ref_by_file[src_path].append((name, int(size_hex, 16)))

print("match_lvgl:   Loaded %d reference symbols from %d source files" %
      (len(ref_symbols), len(ref_by_file)))

# Step 3: Direct string-based matching
# Many LVGL functions have their name as a string in the binary
# (from LV_TRACE_*, LV_LOG_*, assert messages)
# Match: if a FUN_ function references a string that is an exact LVGL symbol name,
# and no other FUN_ references the same string, it's very likely that function.
print("match_lvgl: Step 3 - Direct string-name matching...")

matched = {}  # fw_func_addr -> (lvgl_name, confidence, method)
already_named = set()  # track which LVGL names are already in the DB

# Check which functions are already named
func_iter = fm.getFunctions(True)
for func in func_iter:
    name = func.getName()
    if name.startswith('lv_') or name.startswith('_lv_'):
        already_named.add(name)

print("match_lvgl:   %d lv_* functions already named in DB" % len(already_named))

# For each lv_* string in the binary, find which FUN_ functions reference it
for str_addr, func_name in lvgl_func_strings.items():
    if func_name not in ref_symbols:
        continue
    if func_name in already_named:
        continue

    # Find all references TO this string
    refs = refmgr.getReferencesTo(str_addr)
    referencing_funs = set()
    for ref in refs:
        from_addr = ref.getFromAddress()
        func = fm.getFunctionContaining(from_addr)
        if func and func.getName().startswith('FUN_'):
            referencing_funs.add(func)

    if len(referencing_funs) == 1:
        func = list(referencing_funs)[0]
        if func.getEntryPoint() not in matched:
            matched[func.getEntryPoint()] = (func_name, 'HIGH', 'string_ref_unique')
    elif len(referencing_funs) > 1:
        # Multiple functions reference this name string — less certain
        # Check if one of them has a similar size to the reference
        ref_size = ref_symbols[func_name][0]
        for func in referencing_funs:
            fw_size = func.getBody().getNumAddresses()
            ratio = float(fw_size) / ref_size if ref_size > 0 else 0
            if 0.5 < ratio < 2.0 and func.getEntryPoint() not in matched:
                matched[func.getEntryPoint()] = (func_name, 'MEDIUM', 'string_ref_multi+size')

print("match_lvgl:   String-based matches: %d" % len(matched))

# Step 4: __FILE__ based matching
# For each LVGL __FILE__ string, find FUN_ functions that reference it.
# These functions come from the same source file.
# Match by function size against the reference symbols from that file.
print("match_lvgl: Step 4 - __FILE__ + size matching...")

file_match_count = 0
for file_str_addr, rel_path in lvgl_file_strings.items():
    # Find reference symbols from this source file
    # rel_path is like "core/lv_obj.c", ref_by_file keys are like "core/lv_obj.c"
    matching_refs = None
    for ref_path, syms in ref_by_file.items():
        # Fuzzy match on filename
        if rel_path.endswith(ref_path) or ref_path.endswith(rel_path) or \
           os.path.basename(rel_path) == os.path.basename(ref_path):
            matching_refs = syms
            break

    if not matching_refs:
        continue

    # Find all FUN_ functions that reference this __FILE__ string
    refs = refmgr.getReferencesTo(file_str_addr)
    fw_funs = []
    for ref in refs:
        from_addr = ref.getFromAddress()
        func = fm.getFunctionContaining(from_addr)
        if func and func.getName().startswith('FUN_'):
            if func.getEntryPoint() not in matched:
                fw_size = func.getBody().getNumAddresses()
                fw_funs.append((func, fw_size))

    if not fw_funs:
        continue

    # For each unmatched FW function from this file, try to match by size
    # Only match if there's a unique best match (size ratio closest to 1.0)
    used_refs = set()
    for func, fw_size in fw_funs:
        best_match = None
        best_ratio = 999
        for ref_name, ref_size in matching_refs:
            if ref_name in already_named or ref_name in used_refs:
                continue
            if ref_size == 0:
                continue
            ratio = abs(1.0 - float(fw_size) / ref_size)
            if ratio < best_ratio and ratio < 0.5:  # within 50% size
                best_ratio = ratio
                best_match = ref_name

        if best_match and best_ratio < 0.3:  # within 30% = high confidence
            matched[func.getEntryPoint()] = (best_match, 'MEDIUM', 'file+size(%.0f%%)' % (best_ratio*100))
            used_refs.add(best_match)
            file_match_count += 1

print("match_lvgl:   __FILE__+size matches: %d" % file_match_count)

# Step 5: Apply matches
print("match_lvgl: Step 5 - Applying %d matches..." % len(matched))

applied = 0
skipped = 0
for func_addr, (lvgl_name, confidence, method) in sorted(matched.items(), key=lambda x: x[1][1], reverse=True):
    func = fm.getFunctionAt(func_addr)
    if not func:
        continue

    old_name = func.getName()
    if not old_name.startswith('FUN_'):
        skipped += 1
        continue

    # Only apply HIGH confidence automatically; MEDIUM gets a plate comment
    if confidence == 'HIGH':
        func.setName(lvgl_name, SourceType.ANALYSIS)
        func.setComment("LVGL match: %s [%s]" % (method, confidence))
        applied += 1
        print("match_lvgl:   RENAMED %s -> %s (%s)" % (old_name, lvgl_name, method))
    else:
        # Add as plate comment for manual review
        listing.setComment(func_addr, CodeUnit.PLATE_COMMENT,
                          "LVGL candidate: %s [%s, %s]" % (lvgl_name, method, confidence))
        applied += 1

print("match_lvgl: === DONE: %d applied (%d renamed, rest commented), %d skipped ===" %
      (applied, len([x for x in matched.values() if x[1] == 'HIGH']), skipped))
