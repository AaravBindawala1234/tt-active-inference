# SPDX-License-Identifier: Apache-2.0
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles

def s8(u): return u-256 if u>=128 else u

OBS_LEFT, OBS_CENTER, OBS_RIGHT = 0, 1, 2
MOVE_L, STAY, MOVE_R = 0, 1, 2
SEEK_RIGHT, SEEK_LEFT = 0, 1

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

async def convince(dut, obs, csel, n=4):
    """Feed the same observation n times so the agent becomes confident."""
    for _ in range(n):
        await run_step(dut, obs, csel)


# ===========================================================================
# SPECIFICATION TESTS
# These encode what an active inference agent OUGHT to do, independent of how
# this one is implemented: once it is confident about where it is, it should
# move toward the position it prefers, and stay put once it has arrived.
# ===========================================================================

@cocotb.test()
async def test_belief_drives_action(dut):
    """The agent's belief about WHERE IT IS must determine what it does.

    This is the property the design exists to demonstrate, and it is easy to
    lose: an earlier revision summed the per-state score terms, which made
    sum_s belief[s] a constant offset on every action's score. It cancelled in
    the argmax, and the chip reduced to a fixed function of csel that ignored
    every observation it was ever given. This test fails loudly if that
    regresses.
    """
    cocotb.start_soon(Clock(dut.clk, 40, unit="ns").start())

    # (observation fed repeatedly, goal, expected action once confident)
    CASES = [
        (OBS_RIGHT,  SEEK_RIGHT, STAY,   "believes RIGHT, wants RIGHT -> arrived"),
        (OBS_LEFT,   SEEK_RIGHT, MOVE_R, "believes LEFT,  wants RIGHT -> go right"),
        (OBS_CENTER, SEEK_RIGHT, MOVE_R, "believes CENTER,wants RIGHT -> go right"),
        (OBS_LEFT,   SEEK_LEFT,  STAY,   "believes LEFT,  wants LEFT  -> arrived"),
        (OBS_RIGHT,  SEEK_LEFT,  MOVE_L, "believes RIGHT, wants LEFT  -> go left"),
        (OBS_CENTER, SEEK_LEFT,  MOVE_L, "believes CENTER,wants LEFT  -> go left"),
    ]
    for obs, csel, want, why in CASES:
        await reset(dut)
        await convince(dut, obs, csel)
        got = await run_step(dut, obs, csel)
        beliefs = await read_beliefs(dut, csel)
        dut._log.info(f"{why}: belief={beliefs} action={got}")
        assert got == want, f"{why}: expected action {want}, got {got}"


@cocotb.test()
async def test_same_goal_different_belief_differs(dut):
    """With the goal held FIXED, two different beliefs must produce different
    actions.

    SEEK_LEFT specifically, because it is the discriminating case. The old
    summing design chose 'move L' for every seek-LEFT belief without exception,
    so this comparison collapses to 0 vs 0 there and fails. Under SEEK_RIGHT it
    would have passed even on the broken design — 8-bit saturation happened to
    separate those two particular beliefs — which is exactly the kind of
    accidental pass this test exists to avoid relying on.
    """
    cocotb.start_soon(Clock(dut.clk, 40, unit="ns").start())

    await reset(dut)
    await convince(dut, OBS_LEFT, SEEK_LEFT)
    at_goal = await run_step(dut, OBS_LEFT, SEEK_LEFT)

    await reset(dut)
    await convince(dut, OBS_RIGHT, SEEK_LEFT)
    away = await run_step(dut, OBS_RIGHT, SEEK_LEFT)

    dut._log.info(f"csel=SEEK_LEFT: believes LEFT -> {at_goal}, believes RIGHT -> {away}")
    assert at_goal != away, (
        f"belief has no effect on the decision: both beliefs gave action {at_goal}")


@cocotb.test()
async def test_goal_switching(dut):
    """With the BELIEF held fixed, flipping the goal flips the action."""
    cocotb.start_soon(Clock(dut.clk, 40, unit="ns").start())

    await reset(dut)
    await convince(dut, OBS_CENTER, SEEK_RIGHT)
    right_goal = await run_step(dut, OBS_CENTER, SEEK_RIGHT)
    left_goal  = await run_step(dut, OBS_CENTER, SEEK_LEFT)

    dut._log.info(f"same belief: seek RIGHT -> {right_goal}, seek LEFT -> {left_goal}")
    assert right_goal == MOVE_R, f"seek-RIGHT from CENTER should move R, got {right_goal}"
    assert left_goal  == MOVE_L, f"seek-LEFT from CENTER should move L, got {left_goal}"


# ===========================================================================
# REGRESSION TRACES
# Generated from the fixed-point reference model. These pin down exact
# behaviour so refactors (pipelining, area cuts) cannot silently change it.
# They are a self-consistency check, NOT a correctness check — the tests above
# are what establish correctness.
# ===========================================================================

GOLDEN = [
    (0, (1, 1, 1, 1), [2, 2, 2, 2], [-121, 0, -121]),
    (0, (0, 0, 2, 2), [2, 2, 2, 1], [-13, -67, 0]),
    (0, (2, 2, 0, 0), [1, 1, 1, 1], [0, -67, -13]),
    (0, (0, 1, 2, 0), [2, 2, 1, 2], [0, -67, -54]),
    (0, (2, 1, 0, 1), [1, 1, 1, 2], [-54, 0, -67]),
    (1, (1, 1, 1, 1), [0, 0, 0, 0], [-121, 0, -121]),
    (1, (0, 0, 2, 2), [1, 1, 1, 1], [-13, -67, 0]),
    (1, (2, 2, 0, 0), [0, 0, 0, 1], [0, -67, -13]),
    (1, (0, 1, 2, 0), [1, 1, 1, 1], [0, -67, -54]),
    (1, (2, 1, 0, 1), [0, 0, 1, 0], [-54, 0, -67]),
]

@cocotb.test()
async def test_golden_sequences(dut):
    cocotb.start_soon(Clock(dut.clk, 40, unit="ns").start())
    for csel, seq, want_acts, want_beliefs in GOLDEN:
        await reset(dut)
        got = [await run_step(dut, obs, csel) for obs in seq]
        beliefs = await read_beliefs(dut, csel)
        dut._log.info(f"csel={csel} obs={seq} actions={got} beliefs={beliefs}")
        assert got == want_acts, \
            f"csel={csel} obs={seq}: actions {got}, expected {want_acts}"
        assert beliefs == want_beliefs, \
            f"csel={csel} obs={seq}: beliefs {beliefs}, expected {want_beliefs}"


# ===========================================================================
# INTERFACE / ROBUSTNESS
# ===========================================================================

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

    # tick is held at 1 throughout, including while sweeping bsel, so no new
    # edge occurs and the belief must not drift.
    first = await read_beliefs(dut, 0, obs=1, tick=1)
    dut.ui_in.value = pack(1, 1, 0)
    await ClockCycles(dut.clk, 20)
    second = await read_beliefs(dut, 0, obs=1, tick=1)
    dut._log.info(f"beliefs with tick held: {first} -> {second}")
    assert first == second, \
        f"tick is level-sensitive: beliefs drifted {first} -> {second}"


@cocotb.test()
async def test_invalid_encodings_are_safe(dut):
    """obs=3 and bsel=3 are outside the valid 0..2 range. Neither is reachable
    in normal use, but both are electrically reachable on the pins, so they must
    resolve to something defined rather than hanging or emitting X."""
    cocotb.start_soon(Clock(dut.clk, 40, unit="ns").start())
    await reset(dut)

    act = await run_step(dut, 3, SEEK_RIGHT)          # obs=3 -> Default branch
    assert act in (0, 1, 2), f"obs=3 produced out-of-range action {act}"
    dut._log.info(f"obs=3 handled, action={act}")

    dut.ui_in.value = pack(0, 0, SEEK_RIGHT, 3)       # bsel=3 -> Default branch
    await ClockCycles(dut.clk, 1)
    val = int(dut.uio_out.value)
    assert 0 <= val <= 255, f"bsel=3 produced undriven debug bus: {val}"
    dut._log.info(f"bsel=3 handled, debug bus={s8(val)}")


@cocotb.test()
async def test_reset_midflight(dut):
    """Reset asserted part-way through an inference must return the agent to a
    clean zero belief, not a half-updated one."""
    cocotb.start_soon(Clock(dut.clk, 40, unit="ns").start())
    await reset(dut)
    await convince(dut, OBS_RIGHT, SEEK_RIGHT)

    dut.ui_in.value = pack(OBS_RIGHT, 1, SEEK_RIGHT)  # start a step...
    await ClockCycles(dut.clk, 2)                     # ...and interrupt it
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 3)
    dut.rst_n.value = 1
    dut.ui_in.value = pack(0, 0, SEEK_RIGHT)
    await ClockCycles(dut.clk, 2)

    beliefs = await read_beliefs(dut, SEEK_RIGHT)
    dut._log.info(f"beliefs after mid-flight reset: {beliefs}")
    assert beliefs == [0, 0, 0], f"reset left a dirty belief state: {beliefs}"
