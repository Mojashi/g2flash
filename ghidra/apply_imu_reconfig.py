# -*- coding: utf-8 -*-
# Ghidra headless: apply IMU reconfiguration RE findings (2026-07-20) to the DB.
# Names sensor parameter setup, channel disable/config, WOM/temp interrupts, batch enable,
# vreg helpers, and hub state query. Updates bhi260_full_sensor_reconfig comment. @category CFW
from ghidra.program.model.symbol import SourceType
from ghidra.program.model.listing import CodeUnit, ParameterImpl, Function
from ghidra.program.model.data import (PointerDataType, VoidDataType, ByteDataType,
    UnsignedIntegerDataType, IntegerDataType, UnsignedShortDataType)
from java.lang import Throwable

fm = currentProgram.getFunctionManager()
af = currentProgram.getAddressFactory()
st = currentProgram.getSymbolTable()
listing = currentProgram.getListing()
dtm = currentProgram.getDataTypeManager()
def A(h): return af.getAddress(h)
U8 = ByteDataType.dataType; U16 = UnsignedShortDataType.dataType
U32 = UnsignedIntegerDataType.dataType; I32 = IntegerDataType.dataType
V = VoidDataType.dataType
def P(dt): return PointerDataType(dt)

# ---- function names ----
NAMES = {
    0x4bbed8: ("DRV_IMUSetSensorParameters",
               "Main sensor parameter setup. Builds 17-byte config array, calls bhi260_full_sensor_reconfig. Called by hub task when sensor roles change."),
    0x0052ae0e: ("bhi260_write_channel_disable_mask",
                 "Writes 14-bit channel disable mask to BHI260 reg 0x39. Gyro bits=0 -> gyro disabled in FIFO."),
    0x00529a64: ("bhi260_write_channel_config",
                 "Writes channel config to reg 0x16 (accel) or 0x56 (gyro). Controls which data appears in FIFO frames."),
    0x005290a8: ("bhi260_read_current_config",
                 "Reads regs 0x1d-0x22,0x28 into the 17-byte config array format."),
    0x0052b9b8: ("bhi260_enable_wom_interrupt",
                 "Sets reg 0x29 bit 2 + reg 0x2a bit 5 (wake-on-motion interrupt)."),
    0x0052be14: ("bhi260_enable_temp_interrupt",
                 "Sets reg 0x29 bit 3 + reg 0x2a bit 5 (temperature reporting)."),
    0x0052b7e2: ("bhi260_vreg_clear_bits",
                 "Reads virtual reg, clears bitmask, writes back."),
    0x0052af88: ("bhi260_set_batch_enable",
                 "Read-modify-write reg 0x2a: sets bit 6 (batch/FIFO commit enable)."),
    0x004bf408: ("hub_get_state",
                 "Returns current hub state (2 = uninitialized/error)."),
}

nfn = 0
for addr, (name, comment) in NAMES.items():
    try:
        f = fm.getFunctionAt(A("0x%x" % addr))
        if f is None:
            f = fm.getFunctionContaining(A("0x%x" % addr))
        if f is None: continue
        f.setName(name, SourceType.USER_DEFINED)
        listing.setComment(A("0x%x" % addr), CodeUnit.PLATE_COMMENT, comment)
        nfn += 1
    except Throwable as e:
        print("  fail 0x%x: %s" % (addr, e))
print("apply_imu_reconfig: named %d functions" % nfn)

# ---- update comment on existing bhi260_full_sensor_reconfig ----
UPDATED_COMMENTS = {
    0x52918a: "FULL BHI260 reconfiguration: takes 17-byte config array as 2nd param. config[0]=accel, [1]=gyro, [2]=mag enable, [4..5]=FIFO watermark, [6]=power mode, [7]=range, [12]=FIFO format, [13]=FIFO enable. When hub_open(4) calls this with config[1]=0, gyro is killed via reg 0x21/0x39/0x16. hub_open(2) first -> gyro included.",
}

ncom = 0
for addr, comment in UPDATED_COMMENTS.items():
    try:
        listing.setComment(A("0x%x" % addr), CodeUnit.PLATE_COMMENT, comment)
        ncom += 1
    except Throwable as e:
        print("  comment fail 0x%x: %s" % (addr, e))
print("apply_imu_reconfig: updated %d comments" % ncom)

# ---- key signatures ----
SIGS = [
    (0x4bbed8, I32, [(U32,"driver_ctx"),(P(U8),"config_17")]),  # DRV_IMUSetSensorParameters
    (0x0052ae0e, I32, [(U32,"driver_ctx"),(U16,"disable_mask")]),  # bhi260_write_channel_disable_mask
    (0x00529a64, I32, [(U32,"driver_ctx"),(I32,"mode"),(P(U8),"config")]),  # bhi260_write_channel_config
    (0x005290a8, I32, [(U32,"driver_ctx"),(P(U8),"out_config_17")]),  # bhi260_read_current_config
    (0x0052b9b8, I32, [(U32,"driver_ctx")]),  # bhi260_enable_wom_interrupt
    (0x0052be14, I32, [(U32,"driver_ctx")]),  # bhi260_enable_temp_interrupt
    (0x0052b7e2, I32, [(U32,"driver_ctx"),(U32,"vreg"),(U16,"mask")]),  # bhi260_vreg_clear_bits
    (0x0052af88, I32, [(U32,"driver_ctx")]),  # bhi260_set_batch_enable
    (0x004bf408, I32, []),  # hub_get_state
]

nsig = 0
for addr, ret, ps in SIGS:
    try:
        f = fm.getFunctionAt(A("0x%x" % addr))
        if f is None: continue
        params = [ParameterImpl(n, dt, currentProgram) for (dt, n) in ps]
        f.replaceParameters(Function.FunctionUpdateType.DYNAMIC_STORAGE_ALL_PARAMS, True,
                            SourceType.USER_DEFINED, params)
        f.setReturnType(ret, SourceType.USER_DEFINED)
        nsig += 1
    except Throwable as e:
        print("  sig fail 0x%x: %s" % (addr, e))
print("apply_imu_reconfig: set %d signatures" % nsig)
