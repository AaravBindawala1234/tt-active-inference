# SPDX-License-Identifier: Apache-2.0
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles

def s8(u): return u-256 if u>=128 else u

@cocotb.test()
async def test_active_inference_v3(dut):
    dut._log.info("Start v3")
    cocotb.start_soon(Clock(dut.clk, 40, units="ns").start())
    dut.ena.value=1; dut.ui_in.value=0; dut.uio_in.value=0
    dut.rst_n.value=0
    await ClockCycles(dut.clk,5)
    dut.rst_n.value=1
    await ClockCycles(dut.clk,2)

    # csel=0 (seek RIGHT): feed CENTER observations, expect action=2 (move R)
    # ui_in bits: obs[1:0], tick[2], gamma[4:3], bsel[6:5], csel[7]
    def pack(obs, tick, csel):
        return (csel<<7) | (obs&0x3) | (tick<<2)
    dut.ui_in.value = pack(1, 1, 0)  # obs=CENTER, tick=1, csel=0
    await ClockCycles(dut.clk,1)
    dut.ui_in.value = pack(1, 0, 0)
    await ClockCycles(dut.clk,1)
    act_right_goal = int(dut.uo_out.value) & 0x3
    dut._log.info(f"csel=0 action={act_right_goal} (expect 2=move R)")

    # csel=1 (seek LEFT): same observation, expect action=0 (move L)
    dut.ui_in.value = pack(1, 1, 1)
    await ClockCycles(dut.clk,1)
    dut.ui_in.value = pack(1, 0, 1)
    await ClockCycles(dut.clk,1)
    act_left_goal = int(dut.uo_out.value) & 0x3
    dut._log.info(f"csel=1 action={act_left_goal} (expect 0=move L)")

    assert act_right_goal == 2, f"seek-RIGHT goal should move R, got {act_right_goal}"
    assert act_left_goal == 0, f"seek-LEFT goal should move L, got {act_left_goal}"
    dut._log.info("Runtime goal switching verified: same obs, opposite actions.")
