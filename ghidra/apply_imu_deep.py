# -*- coding: utf-8 -*-
# Ghidra headless: apply the deep IMU RE findings (2026-07-20 agent session) to the DB.
# Names the BHI260AP chip driver functions, the FIFO parsers, the sensor hub reconfiguration,
# and the auto-brightness interference chain. @category CFW
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

# ---- function names (from RE agent's report) ----
NAMES = {
    # BHI260AP chip I/O
    0x527fd4: ("bhi260_parse_fifo_standard", "parse uncompressed accel/gyro/mag/temp FIFO frame, invokes callback via ctx+0x18"),
    0x528414: ("bhi260_parse_fifo_compressed", "parse BHI260 compressed delta-mode FIFO frames (4/5/8-bit nibble precision)"),
    0x528dba: ("bhi260_parse_fifo_fullres", "parse full-resolution 16-bit FIFO sample frame"),
    0x528f9a: ("bhi260_fifo_batch_dispatch", "FIFO batch parser dispatch loop: for each frame, routes to standard/compressed/fullres parser"),
    0x528f70: ("bhi260_fifo_read", "reads FIFO from BHI260 reg 0x12 (frame count) + 0x14 (bulk data), then dispatches"),
    0x52918a: ("bhi260_full_sensor_reconfig", "FULL BHI260 reconfiguration (908 bytes): rewrites sensor control regs 0x1d-0x22,0x28, virtual reg 0xa258, changes packet size, resets calibration state. Called by HUB_Open tasks. THIS IS WHAT KILLS GYRO AFTER display_startup."),
    0x529c44: ("bhi260_sensor_enable", "read-modify-write sensor enable register: mode=0→reg 0x18 (accel), mode=1→reg 0x58 (gyro). config bytes: [0]=accel,[1]=gyro,[2]=mag enable"),
    0x529590: ("bhi260_reset_calibration", "resets accel/gyro/mag calibrated flags at ctx+0x2c/0x2d/0x2e to 0. After this, parsed values are 0/sentinel until chip resends calibration."),
    0x5295f8: ("bhi260_delay_us", "microsecond delay via ctx[3] callback (→ FUN_0047e018)"),
    0x529516: ("bhi260_chip_init", "chip initialization sequence (called from FUN_00527e6c)"),
    0x5296a6: ("bhi260_read_chip_id", "reads chip WHO_AM_I register, expects 0x81 (BHI260AP)"),
    0x527ec8: ("bhi260_post_init_config", "post-init configuration (called after chip ID check passes)"),
    0x52c544: ("bhi260_reg_read", "register READ dispatch: routes to vtable ctx[0] for 8-bit regs, virtual reg protocol for >=0x100"),
    0x52c55c: ("bhi260_reg_write", "register WRITE dispatch: routes to vtable ctx[1] for 8-bit regs, virtual reg protocol for >=0x100"),
    0x52c582: ("bhi260_reg_read_8bit", "8-bit register read via I2C (calls ctx[0] = 0x4bbc69)"),
    0x52c59e: ("bhi260_reg_write_8bit", "8-bit register write via I2C (calls ctx[1] = 0x4bbca3)"),
    0x52c61c: ("bhi260_vreg_read_16bit", "virtual register read: addr via reg 0x7C (byte-swapped), data via 0x7E, with 4us delay"),
    0x52c68e: ("bhi260_vreg_write_16bit", "virtual register write: addr via reg 0x7C, data via 0x7E"),
    0x52c5ba: ("bhi260_vreg_validate_addr", "validate virtual register address range (0x2400-0x3FFF, 0x8400-0x9FFF, reject >=0xB000)"),
    0x529032: ("bhi260_odr_index_to_period", "map ODR index to sample period: idx3→156us, idx5→625us, idx7→2500us, idx9→10000us, idx11→40000us"),
    0x52b37c: ("bhi260_fusion_process", "sensor fusion library: accel+gyro+mag → quaternion+orientation"),
    0x529a22: ("bhi260_read_fifo_status", "read FIFO frame count from BHI260 register 0x12"),
    # IMU driver layer
    0x4bbd66: ("drv_imu_init", "IMU driver init: creates BHI260 driver ctx at *0x4bbeb8, registers callbacks, calls bhi260_chip_init+bhi260_sensor_enable(accel only)"),
    0x4bbcc6: ("drv_imu_register_fifo_handlers", "registers FIFO read/parse function pointers from ROM table 0x4bbe98-0x4bbeb4 into the sensor state struct at 0x200730c0"),
    0x4bbd00: ("drv_imu_headup_filter_step", "2-tap delay-line filter for head-up/head-down detection"),
    # Sensor hub layer
    0x4bf0d2: ("hub_send_message", "post message to sensor hub queue (*DAT_004bf584+0xc)"),
    0x4bf410: ("hub_open", "sensor hub open: role=2=gyro+compass, role=4=auto-brightness, role=5=IMU accel reporting"),
    0x4bf482: ("hub_close", "sensor hub close"),
    0x4bf4f4: ("hub_parameter_config", "sensor hub config: cfg_type=5→DRV_IMUAccelConfig, cfg_type=2→gyro params"),
    # Auto-brightness (the interference chain)
    0x46b7c4: ("svc_settings_auto_brightness_open", "THE TROUBLEMAKER: called by display_startup's display thread. Calls hub_open(4) which triggers bhi260_full_sensor_reconfig → overwrites gyro config → kills IMU data."),
    # Navigation compass (the official gyro enable path)
    0x564e4c: ("start_imu_compass_func", "enable gyro+compass: hub_open(2)+hub_parameter_config(2,{1000,5}). Used by navigation."),
    0x564ed4: ("stop_imu_compass_func", "disable gyro+compass: hub_close(2)"),
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
print("apply_imu_deep: named %d functions" % nfn)

# ---- key signatures ----
SIGS = [
    (0x529c44, I32, [(U32,"driver_ctx"),(I32,"mode"),(P(U8),"config")]),  # bhi260_sensor_enable
    (0x52918a, I32, [(U32,"driver_ctx")]),  # bhi260_full_sensor_reconfig (complex, just ctx)
    (0x529590, V, [(U32,"driver_ctx")]),  # bhi260_reset_calibration
    (0x52c544, I32, [(U32,"driver_ctx"),(U32,"reg"),(I32,"count"),(P(U8),"buf")]),  # bhi260_reg_read
    (0x52c55c, I32, [(U32,"driver_ctx"),(U32,"reg"),(I32,"count"),(P(U8),"buf")]),  # bhi260_reg_write
    (0x46b7c4, V, []),  # svc_settings_auto_brightness_open
    (0x564e4c, I32, []),  # start_imu_compass_func
    (0x564ed4, I32, []),  # stop_imu_compass_func
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
print("apply_imu_deep: set %d signatures" % nsig)
