# SPDX-License-Identifier: Apache-2.0
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles

def s8(u): return u-256 if u>=128 else u

# ui_in bits: obs[1:0], tick[2], gamma[4:3], bsel[6:5], csel[7]
def pack(obs, tick, csel, gamma=0, bsel=0):
    return ((csel & 1) << 7) | ((bsel & 3) << 5) | ((gamma & 3) << 3) \
           | ((tick & 1) << 2) | (obs & 3)

async def run_step(dut, obs, csel, gamma=0, timeout=20):
    """Pulse tick for one cycle, then wait for ready. Returns the action."""
    dut.ui_in.value = pack(obs, 1, csel, gamma)
    await ClockCycles(dut.clk, 1)
    dut.ui_in.value = pack(obs, 0, csel, gamma)
    for _ in range(timeout):
        await ClockCycles(dut.clk, 1)
        if int(dut.uo_out.value) & 0x4:      # uo_out[2] = ready
            return int(dut.uo_out.value) & 0x3
    raise AssertionError(f"ready never asserted within {timeout} cycles")

@cocotb.test()
async def test_active_inference_v3(dut):
    dut._log.info("Start v3")
    cocotb.start_soon(Clock(dut.clk, 40, unit="ns").start())
    dut.ena.value=1; dut.ui_in.value=0; dut.uio_in.value=0
    dut.rst_n.value=0
    await ClockCycles(dut.clk,5)
    dut.rst_n.value=1
    await ClockCycles(dut.clk,2)

    # csel=0 (seek RIGHT): feed CENTER observations, expect action=2 (move R)
    act_right_goal = await run_step(dut, obs=1, csel=0)
    dut._log.info(f"csel=0 action={act_right_goal} (expect 2=move R)")

    # csel=1 (seek LEFT): same observation, expect action=0 (move L)
    act_left_goal = await run_step(dut, obs=1, csel=1)
    dut._log.info(f"csel=1 action={act_left_goal} (expect 0=move L)")

    assert act_right_goal == 2, f"seek-RIGHT goal should move R, got {act_right_goal}"
    assert act_left_goal == 0, f"seek-LEFT goal should move L, got {act_left_goal}"
    dut._log.info("Runtime goal switching verified: same obs, opposite actions.")

    # Precision (gamma) must not change WHICH action wins, only the margin.
    for g in range(4):
        a = await run_step(dut, obs=1, csel=0, gamma=g)
        assert a == 2, f"gamma={g} changed the decision: got {a}, expected 2"
    dut._log.info("Precision sweep: decision stable across gamma 0..3.")

    # Full belief readout: every state must be observable via bsel.
    beliefs = []
    for b in range(3):
        dut.ui_in.value = pack(1, 0, 0, 0, b)
        await ClockCycles(dut.clk, 1)
        beliefs.append(s8(int(dut.uio_out.value)))
    dut._log.info(f"belief readout via bsel: {beliefs}")
    assert max(beliefs) == 0, f"max-normalised belief should peak at 0, got {beliefs}"
