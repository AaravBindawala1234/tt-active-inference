# SPDX-License-Identifier: Apache-2.0
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles

def s8(u): return u-256 if u>=128 else u

# ui_in bits: obs[1:0], tick[2], unused[4:3], bsel[6:5], csel[7]
def pack(obs, tick, csel, bsel=0):
    return ((csel & 1) << 7) | ((bsel & 3) << 5) | ((tick & 1) << 2) | (obs & 3)

async def reset(dut):
    dut.ena.value=1; dut.ui_in.value=0; dut.uio_in.value=0
    dut.rst_n.value=0
    await ClockCycles(dut.clk,5)
    dut.rst_n.value=1
    await ClockCycles(dut.clk,2)

async def run_step(dut, obs, csel, timeout=20):
    """Pulse tick for one cycle, then wait for ready. Returns the action."""
    dut.ui_in.value = pack(obs, 1, csel)
    await ClockCycles(dut.clk, 1)
    dut.ui_in.value = pack(obs, 0, csel)
    for _ in range(timeout):
        await ClockCycles(dut.clk, 1)
        if int(dut.uo_out.value) & 0x4:      # uo_out[2] = ready
            return int(dut.uo_out.value) & 0x3
    raise AssertionError(f"ready never asserted within {timeout} cycles")

async def read_beliefs(dut, csel, obs=0, tick=0):
    """Sweep bsel and sample the debug bus. `tick` is held at the caller's
    level so that reading beliefs cannot itself create a tick edge."""
    out = []
    for b in range(3):
        dut.ui_in.value = pack(obs, tick, csel, b)
        await ClockCycles(dut.clk, 1)
        out.append(s8(int(dut.uio_out.value)))
    return out

@cocotb.test()
async def test_goal_switching(dut):
    """Same observation, opposite goals -> opposite actions."""
    cocotb.start_soon(Clock(dut.clk, 40, unit="ns").start())
    await reset(dut)

    act_right_goal = await run_step(dut, obs=1, csel=0)
    dut._log.info(f"csel=0 action={act_right_goal} (expect 2=move R)")
    act_left_goal = await run_step(dut, obs=1, csel=1)
    dut._log.info(f"csel=1 action={act_left_goal} (expect 0=move L)")

    assert act_right_goal == 2, f"seek-RIGHT goal should move R, got {act_right_goal}"
    assert act_left_goal == 0, f"seek-LEFT goal should move L, got {act_left_goal}"


# Golden vectors from the fixed-point reference model: for each (csel, obs
# sequence), the action after every step and the three beliefs at the end.
# These pin the v3.1 sequential argmax to the behaviour of the original v3
# parallel argmax, which is the property the area rewrite had to preserve.
GOLDEN = [
    (0, (1,1,1,1), [2,2,2,2], [-121, 0, -121]),
    (0, (0,0,2,2), [2,2,2,2], [ -13,-67,    0]),
    (0, (2,2,0,0), [2,1,2,2], [   0,-67,  -13]),   # exercises the "stay" action
    (0, (0,1,2,0), [2,2,2,2], [   0,-67,  -54]),
    (1, (1,1,1,1), [0,0,0,0], [-121, 0, -121]),
    (1, (0,0,2,2), [0,0,0,0], [ -13,-67,    0]),
    (1, (2,2,0,0), [0,0,0,0], [   0,-67,  -13]),
    (1, (0,1,2,0), [0,0,0,0], [   0,-67,  -54]),
]

@cocotb.test()
async def test_golden_sequences(dut):
    """Multi-step traces must match the reference model exactly."""
    cocotb.start_soon(Clock(dut.clk, 40, unit="ns").start())

    for csel, seq, want_acts, want_beliefs in GOLDEN:
        await reset(dut)
        got = []
        for obs in seq:
            got.append(await run_step(dut, obs, csel))
        beliefs = await read_beliefs(dut, csel)
        dut._log.info(f"csel={csel} obs={seq} actions={got} beliefs={beliefs}")
        assert got == want_acts, \
            f"csel={csel} obs={seq}: actions {got}, expected {want_acts}"
        assert beliefs == want_beliefs, \
            f"csel={csel} obs={seq}: beliefs {beliefs}, expected {want_beliefs}"


@cocotb.test()
async def test_tick_is_edge_triggered(dut):
    """Holding tick high runs ONE inference, not a free-running loop."""
    cocotb.start_soon(Clock(dut.clk, 40, unit="ns").start())
    await reset(dut)

    dut.ui_in.value = pack(1, 1, 0)          # tick asserted and held
    for _ in range(20):
        await ClockCycles(dut.clk, 1)
        if int(dut.uo_out.value) & 0x4:
            break
    else:
        raise AssertionError("ready never asserted with tick held high")

    # With tick still high, the belief must not keep updating. tick is held
    # at 1 throughout, including while sweeping bsel, so no new edge occurs.
    first = await read_beliefs(dut, 0, obs=1, tick=1)
    dut.ui_in.value = pack(1, 1, 0)
    await ClockCycles(dut.clk, 20)
    second = await read_beliefs(dut, 0, obs=1, tick=1)
    dut._log.info(f"beliefs with tick held: {first} -> {second}")
    assert first == second, \
        f"tick is level-sensitive: beliefs drifted {first} -> {second}"
