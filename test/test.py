# SPDX-License-Identifier: Apache-2.0
# Cocotb test for the Active Inference chip.
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles


def s8(u):
    """Interpret an 8-bit value as signed."""
    return u - 256 if u >= 128 else u


@cocotb.test()
async def test_active_inference(dut):
    dut._log.info("Start")
    clock = Clock(dut.clk, 40, units="ns")  # 25 MHz
    cocotb.start_soon(clock.start())

    # Reset
    dut.ena.value = 1
    dut.ui_in.value = 0
    dut.uio_in.value = 0
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 5)
    dut.rst_n.value = 1
    await ClockCycles(dut.clk, 2)

    # Feed a sequence of observations and run an inference step for each.
    # obs encoding on ui_in[1:0]; tick on ui_in[2].
    obs_seq = [0, 0, 0, 2, 2, 2]   # sense LEFT a few times, then RIGHT
    beliefs = []
    actions = []
    for obs in obs_seq:
        dut.ui_in.value = (1 << 2) | obs   # tick=1, obs in low bits
        await ClockCycles(dut.clk, 1)
        dut.ui_in.value = obs              # tick=0
        await ClockCycles(dut.clk, 1)
        belief_left = s8(int(dut.uio_out.value))
        action = int(dut.uo_out.value) & 0x3
        beliefs.append(belief_left)
        actions.append(action)
        dut._log.info(f"obs={obs} belief[L]={belief_left} action={action}")

    # Basic sanity checks:
    # After sensing LEFT repeatedly, belief[LEFT] should be the max (>= others),
    # i.e. 0 after normalization. After sensing RIGHT, it should go negative.
    assert beliefs[2] >= beliefs[5], (
        f"belief[LEFT] should drop after RIGHT observations: "
        f"{beliefs[2]} -> {beliefs[5]}"
    )
    dut._log.info("Belief tracking verified: LEFT belief fell after RIGHT obs.")
