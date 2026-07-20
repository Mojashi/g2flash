# -*- coding: utf-8 -*-
# Ghidra headless: define IMU sensor data types from the RE of DRV_IMUDataParserCallback (0x4bdd8c).
# The ring buffer has a 3-word header then 20 entries of 0x70 (112) bytes each. Naming each field
# from its role in the decompiled code. Also names the key global pointer variables. @category CFW
from ghidra.program.model.data import (StructureDataType, PointerDataType, CategoryPath,
    DataTypeConflictHandler, ByteDataType, UnsignedShortDataType, ShortDataType,
    UnsignedIntegerDataType, IntegerDataType, FloatDataType, ArrayDataType)
from ghidra.program.model.symbol import SourceType
from ghidra.program.model.listing import CodeUnit
from java.lang import Throwable

dtm = currentProgram.getDataTypeManager()
fm = currentProgram.getFunctionManager()
af = currentProgram.getAddressFactory()
st = currentProgram.getSymbolTable()
listing = currentProgram.getListing()
def A(h): return af.getAddress(h)
REPLACE = DataTypeConflictHandler.REPLACE_HANDLER
U8=ByteDataType.dataType; U16=UnsignedShortDataType.dataType; I16=ShortDataType.dataType
U32=UnsignedIntegerDataType.dataType; I32=IntegerDataType.dataType; F32=FloatDataType.dataType

# ---- imu_ring_entry_t: 0x70 = 112 bytes per entry ----
# Field offsets derived from DRV_IMUDataParserCallback decompilation:
#   piVar1 is int* (DAT_004be79c); piVar1[uVar7*0x1c + N] = byte offset uVar7*0x70 + N*4
#   Also: (int)piVar1 + uVar7*0x70 + byteOff  (explicit byte arithmetic in some lines)
# Entry structure (byte offsets within one 0x70-byte entry):
#   +0x00 (piVar1[+3]):  u32 timestamp (computed from rate table)
#   +0x04 (piVar1[+4] low byte): u8 flags: bit0=accel_valid, bit1=gyro_raw_valid, bit3=gyro_fused_valid, bit5=quat_valid
#   +0x10: reserved/padding
#   --- ACCEL (bit0 of flags) ---
#   +0x12: i16 accel_raw_x (from data[6])     [explicit byte: (int)piVar1 + uVar7*0x70 + 0x12]
#   +0x14: i16 accel_raw_y (from data[8])      [piVar1[uVar7*0x1c + 5] = byte +0x14]
#   +0x16: i16 accel_raw_z (from data[10])     [explicit byte: + 0x16]
#   +0x34: float accel_cal_x (after FUN_004bdbec IIR filter, piVar1[+0xd] = byte +0x34)
#   +0x38: float accel_cal_y (piVar1[+0xe] = +0x38)  [HW-CONFIRMED: these 3 floats update continuously]
#   +0x3c: float accel_cal_z (piVar1[+0xf] = +0x3c)
#   --- GYRO (bit3 of flags, from fusion lib psVar2) ---
#   +0x18: i16 gyro_raw_x (from data[0xc])    [piVar1[+6] = +0x18]  **NO: this is in the bit1 branch**
#   Wait — re-reading more carefully:
#   bit1 branch (*data << 0x1e < 0 = bit1 set):
#     piVar1[+6] = data[0xc], piVar1 byte+0x1a = data[0xe], piVar1[+7] = data[0x10]
#     → +0x18: i16 raw_gyro_x, +0x1a: i16 raw_gyro_y, +0x1c: i16 raw_gyro_z
#     FUN_004bdbec(..., piVar1[+0x10], 0x10, 3) → +0x40..+0x4c: float filtered gyro? (piVar1[+0x10]=+0x40)
#   bit3 branch (psVar2[0x1b] != 0, from fusion lib):
#     piVar1 byte+0x1e = psVar2[0x18], piVar1[+8] = psVar2[0x19], piVar1 byte+0x22 = psVar2[0x1a]
#     → +0x1e: i16 fused_gyro_x, +0x20: i16 fused_gyro_y, +0x22: i16 fused_gyro_z
#     local_34 = psVar2[0x18]*0x1333 - bias → FUN_004bdbec(&local_34, piVar1[+0x13], 0x10, 3)
#     → +0x4c: float fused_gyro_cal_x, +0x50: fused_gyro_cal_y, +0x54: fused_gyro_cal_z
#   bit5 (quat, from fusion lib psVar2):
#     piVar1[+9..+0xc] = quat w/x/y/z (int32 Q16, psVar2[0..3]<<16)
#     → +0x24: i32 quat_w, +0x28: i32 quat_x, +0x2c: i32 quat_y, +0x30: i32 quat_z  (all <<16 fixed point)
#     FUN_004bdbec(piVar1[+9], piVar1[+0x16], 0x1e, 4) → +0x58..+0x64: float filtered quat? (piVar1[+0x16]=+0x58)
#     FUN_004bdc30(piVar1[+0x16], piVar1[+0x1a]) → +0x68..+0x70: float orientation (piVar1[+0x1a]=+0x68)
#     Then: piVar1[+0x1a]=piVar1[+0x1b], piVar1[+0x1b]=-piVar1[+0x1c], piVar1[+0x1c]=piVar1[+0x1a]
#     → axes swapped: orient_x, orient_y=orient_z, orient_z=-orient_y (Euler conversion)
#     → +0x68: float orient_x (yaw?), +0x6c: float orient_y (swapped), +0x70: float orient_z (swapped)

entry = StructureDataType(CategoryPath("/"), "imu_ring_entry_t", 0x70)
entry.replaceAtOffset(0x00, U32, 4, "timestamp", "computed from rate table + ring index")
entry.replaceAtOffset(0x04, U32, 4, "flags_pad", "low byte = flags: b0=accel, b1=gyro_raw, b3=gyro_fused, b5=quat")
# accel
entry.replaceAtOffset(0x12, I16, 2, "accel_raw_x", "from IMU chip data[6], raw i16")
entry.replaceAtOffset(0x14, I16, 2, "accel_raw_y", "from IMU chip data[8]")
entry.replaceAtOffset(0x16, I16, 2, "accel_raw_z", "from IMU chip data[10]")
entry.replaceAtOffset(0x34, F32, 4, "accel_cal_x", "IIR-filtered calibrated accel (float, g units). HW-confirmed live.")
entry.replaceAtOffset(0x38, F32, 4, "accel_cal_y", "IIR-filtered calibrated accel y")
entry.replaceAtOffset(0x3c, F32, 4, "accel_cal_z", "IIR-filtered calibrated accel z")
# gyro raw (bit1 of flags, from IMU chip directly)
entry.replaceAtOffset(0x18, I16, 2, "gyro_chip_x", "from IMU chip data[0xc], raw i16 (bit1 flag)")
entry.replaceAtOffset(0x1a, I16, 2, "gyro_chip_y", "from IMU chip data[0xe]")
entry.replaceAtOffset(0x1c, I16, 2, "gyro_chip_z", "from IMU chip data[0x10]")
entry.replaceAtOffset(0x40, F32, 4, "gyro_chip_cal_x", "IIR-filtered chip gyro (bit1 path)")
entry.replaceAtOffset(0x44, F32, 4, "gyro_chip_cal_y", None)
entry.replaceAtOffset(0x48, F32, 4, "gyro_chip_cal_z", None)
# gyro fused (bit3 of flags, from fusion lib FUN_0052b37c)
entry.replaceAtOffset(0x1e, I16, 2, "gyro_fused_x", "from fusion lib psVar2[0x18], raw*0x1333-bias (bit3 flag)")
entry.replaceAtOffset(0x20, I16, 2, "gyro_fused_y", "from fusion lib psVar2[0x19]")
entry.replaceAtOffset(0x22, I16, 2, "gyro_fused_z", "from fusion lib psVar2[0x1a]")
entry.replaceAtOffset(0x4c, F32, 4, "gyro_fused_cal_x", "IIR-filtered fused gyro (float)")
entry.replaceAtOffset(0x50, F32, 4, "gyro_fused_cal_y", None)
entry.replaceAtOffset(0x54, F32, 4, "gyro_fused_cal_z", None)
# quaternion (bit5 of flags, from fusion lib)
entry.replaceAtOffset(0x24, I32, 4, "quat_w_q16", "quaternion w, Q16 fixed-point (psVar2[0..3]<<16)")
entry.replaceAtOffset(0x28, I32, 4, "quat_x_q16", "quaternion x")
entry.replaceAtOffset(0x2c, I32, 4, "quat_y_q16", "quaternion y")
entry.replaceAtOffset(0x30, I32, 4, "quat_z_q16", "quaternion z")
entry.replaceAtOffset(0x58, F32, 4, "quat_filt_w", "IIR-filtered quaternion (float)")
entry.replaceAtOffset(0x5c, F32, 4, "quat_filt_x", None)
entry.replaceAtOffset(0x60, F32, 4, "quat_filt_y", None)
entry.replaceAtOffset(0x64, F32, 4, "quat_filt_z", None)
# orientation (derived from quaternion, axes swapped)
entry.replaceAtOffset(0x68, F32, 4, "orient_x", "post-fusion orientation (axes swapped from quat: x, z, -y). Includes YAW when fusion enabled (HUB_Open(2)).")
entry.replaceAtOffset(0x6c, F32, 4, "orient_y", "post-fusion orientation y (swapped)")
entry.replaceAtOffset(0x70-4, F32, 4, "orient_z", "post-fusion orientation z (swapped)")
dt_entry = dtm.addDataType(entry, REPLACE)

# ---- imu_ring_hdr_t: the 3-word header before the entries ----
hdr = StructureDataType(CategoryPath("/"), "imu_ring_hdr_t", 12)
hdr.replaceAtOffset(0, U32, 4, "base_timestamp", "piVar1[0]")
hdr.replaceAtOffset(4, U32, 4, "prev_index", "piVar1[1]")
hdr.replaceAtOffset(8, U32, 4, "current_index", "piVar1[2], 0..19, wraps")
dt_hdr = dtm.addDataType(hdr, REPLACE)

print("apply_imu_types: defined imu_ring_entry_t (%d bytes) + imu_ring_hdr_t (%d bytes)" % (dt_entry.getLength(), dt_hdr.getLength()))

# ---- name the global pointer variables ----
labels = {
    0x4be79c: ("g_imu_ring_ptr", "ptr to imu_ring_hdr_t + 20x imu_ring_entry_t in SRAM (runtime-init)"),
    0x4bea20: ("g_imu_accel_bias", "int32[3] accel calibration bias (subtracted from raw*8)"),
    0x4bea24: ("g_imu_fusion_buf", "ptr to fusion lib output buffer (psVar2, 0x50 bytes, from FUN_0052b37c)"),
    0x4bea28: ("g_imu_fusion_ctx", "ptr to fusion library context (1st arg to FUN_0052b37c)"),
    0x4bea38: ("g_imu_gyro_bias", "int32[3] gyro calibration bias (subtracted from raw*0x1333)"),
    0x4be228: ("g_imu_headup_filter_ctx", "ptr to headup filter struct (delay-line at +0x28, output at +0x38, threshold at +0x6c)"),
    0x4be584: ("g_imu_accel_rate", "current accel sample rate (100..5024 Hz, set by DRV_IMUAccelConfig)"),
    0x4be590: ("g_imu_rate_config_table", "ptr to rate config table (entry stride 0x10, [+4]=period_us)"),
    0x4be598: ("g_imu_rate_index", "ptr to current rate table index"),
    0x4bec28: ("g_imu_mag_raw", "int32[3] magnetometer raw (from fusion lib psVar2[0x13..0x15]<<4)"),
}
nlbl = 0
for addr, (name, comment) in labels.items():
    try:
        a = A("0x%x" % addr)
        st.createLabel(a, name, SourceType.USER_DEFINED)
        listing.setComment(a, CodeUnit.EOL_COMMENT, comment)
        nlbl += 1
    except Throwable as e:
        print("  label fail 0x%x: %s" % (addr, e))
print("apply_imu_types: labeled %d IMU globals" % nlbl)

# ---- set signature on DRV_IMUDataParserCallback ----
from ghidra.program.model.listing import ParameterImpl, Function
from ghidra.program.model.data import PointerDataType, VoidDataType
try:
    f = fm.getFunctionAt(A("0x4bdd8c"))
    ps = [ParameterImpl("data", PointerDataType(U8), currentProgram)]
    f.replaceParameters(Function.FunctionUpdateType.DYNAMIC_STORAGE_ALL_PARAMS, True, SourceType.USER_DEFINED, ps)
    f.setReturnType(VoidDataType.dataType, SourceType.USER_DEFINED)
    listing.setComment(A("0x4bdd8c"), CodeUnit.PLATE_COMMENT,
        "DRV_IMUDataParserCallback: parses a raw IMU chip packet into the ring buffer "
        "(imu_ring_entry_t[20] at *g_imu_ring_ptr+12). Populates accel (data bit0), gyro_chip (bit1), "
        "gyro_fused+quat+orientation (bits 3/5, requires fusion lib FUN_0052b37c / HUB_Open(2)). "
        "Orientation at +0x68..+0x6c includes YAW from gyro integration. See imu_ring_entry_t.")
    print("apply_imu_types: typed DRV_IMUDataParserCallback")
except Throwable as e:
    print("  sig fail: %s" % e)

# ---- names for the fusion + filter functions ----
fn_names = {
    0x4bdbec: ("imu_iir_filter", "IIR low-pass filter: (int32* in, float* state, int order, int taps)"),
    0x4bdc30: ("imu_quat_to_euler", "quaternion-to-Euler conversion: (float* quat_filt, float* orient_out)"),
    0x4bbd00: ("imu_headup_filter_step", "2-tap delay-line filter for the headup/headdown detector"),
    0x52b37c: ("imu_fusion_process", "sensor fusion library (accel+gyro+mag → quat+orient, ctx in DAT_004bea28)"),
    0x4bf410: ("HUB_Open", "sensor hub open: role=2 enables gyro+compass fusion, role=5 enables IMU accel reporting"),
    0x4bf482: ("HUB_Close", "sensor hub close"),
    0x4bf4f4: ("HUB_ParameterConfig", "sensor hub config: cfg_type=5→DRV_IMUAccelConfig, cfg_type=2→gyro params"),
    0x4bf0d2: ("HUB_SendMessage", "post message to sensor hub queue (*DAT_004bf584+0xc)"),
    0x564e4c: ("StartIMUCompassFunc", "enable gyro+compass: HUB_Open(2)+HUB_ParameterConfig(2,...). Used by navigation."),
    0x564ed4: ("StopIMUCompassFunc", "disable gyro+compass: HUB_Close(2)"),
}
nfn = 0
for addr, (name, comment) in fn_names.items():
    try:
        f = fm.getFunctionAt(A("0x%x" % addr))
        if f is None: continue
        f.setName(name, SourceType.USER_DEFINED)
        listing.setComment(A("0x%x" % addr), CodeUnit.PLATE_COMMENT, comment)
        nfn += 1
    except Throwable as e:
        print("  fn fail 0x%x: %s" % (addr, e))
print("apply_imu_types: named %d IMU functions" % nfn)
