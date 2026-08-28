"""
ACTIVE INFERENCE CHIP v3.1 — Amaranth HDL. 3 states, 1-step EFE planning.

DESIGN HISTORY / HONEST NOTE:
  A full 2-step planning horizon was prototyped and MEASURED. It cost ~1,000
  extra cells (estimated ~108% tile utilization) AND, for this deterministic
  shift-model task, did not change the agent's decisions (verified in
  simulation). Adding ~1000 cells for no behavioural change is poor engineering,
  so the horizon was removed. v3 kept v2's verified 1-step EFE planning and
  added three upgrades; v3.1 keeps the two that survived measurement.

  UPGRADES OVER v2 (820 cells / 47% util):
   1. FULL BELIEF READOUT. A 2-bit select pin (bsel) multiplexes belief[0..2]
      onto the debug bus, so the entire mind-state is observable on a bench.
   2. A 4TH ROW OF PREFERENCE STRUCTURE via a programmable preference-select pin
      (csel) that picks between two baked preference vectors (e.g. "seek RIGHT"
      vs "seek LEFT"), making the agent's GOAL switchable at runtime.

  REMOVED IN v3.1 — the PRECISION (gamma) INPUT.
  It was a 2-bit pin that scaled the score spread by 2**gamma before action
  selection, intended as the active inference precision/temperature knob. It
  could not work, and the reason is algebra rather than a coding bug:

      sharp[a] = (sc[a] - min(sc)) * 2**gamma

  Scaling every score by the same positive constant cannot change which score
  is largest, and the action is chosen by a deterministic argmax. So gamma was
  provably incapable of changing any output. Confirmed exhaustively: over all
  486 five-step observation sequences x both goals x all four gamma values, the
  action sequence was identical every time.

  Precision is a real quantity in active inference, but it only bites when the
  action is SAMPLED from a softmax over -EFE. With a deterministic argmax the
  temperature cancels. Implementing it properly needs a stochastic selector
  (an LFSR and a comparison against the sharpened distribution), which is a
  different and much larger design. Removing the dead logic frees the 15-bit
  datapath, the min, three subtracts, three 4-way constant-multiply muxes and
  two pins.

AREA / TIMING STRUCTURE:
  v3 computed everything in ONE combinational cloud between `tick` and
  `action`, which did not close at 25 MHz: hardening reported setup violations
  in max_ss_100C_1v60, min_ss_100C_1v60 and nom_ss_100C_1v60. It also hardened
  to a die of 152.7 x 163.4 um against a 1x1 tile template of 161.0 x 111.52 um
  — about 139% of the tile.

  The agent is tick-driven, so latency is free. Two changes exploit that:

   * The step is SEQUENCED by an FSM, with registers between stages, so no
     single combinational path spans the whole inference.
   * The three action scores are evaluated through ONE score datapath over
     three consecutive cycles, with a running argmax, instead of three parallel
     scoring cones. This trades two cycles of latency for roughly two thirds of
     the planning logic.

  `ready` marks the cycle the new action is valid and stays high until the next
  tick is accepted.
"""
from amaranth import *
from amaranth.lib import wiring
from amaranth.lib.wiring import In, Out

N = 3

def clamp_s8(m, name, value):
    out = Signal(signed(8), name=name)
    with m.If(value > 127):    m.d.comb += out.eq(127)
    with m.Elif(value < -128): m.d.comb += out.eq(-128)
    with m.Else():             m.d.comb += out.eq(value)
    return out

class ActiveInferenceChipV3(wiring.Component):
    # ---- PINS ----
    obs:        In(2)   # observation 0/1/2
    tick:       In(1)   # run one inference step
    bsel:       In(2)   # belief readout select (0/1/2)
    csel:       In(1)   # preference select: 0 = seek RIGHT, 1 = seek LEFT
    action:     Out(2)  # chosen action 0=L 1=stay 2=R
    ready:      Out(1)  # decision valid
    belief_dbg: Out(8)  # selected belief value

    def elaborate(self, platform):
        m = Module()
        import math
        SCALE = 32
        def q(x): return max(-128, min(127, round(x*SCALE)))

        # ---- GENERATIVE MODEL CONSTANTS ----
        A = [[q(math.log(0.8 if s==o else 0.1)) for o in range(N)] for s in range(N)]
        # TWO preference vectors, runtime-selectable via csel:
        C_right = [q(math.log(0.1)), q(math.log(0.2)), q(math.log(0.7))]  # want R
        C_left  = [q(math.log(0.7)), q(math.log(0.2)), q(math.log(0.1))]  # want L
        shift = {0:-1, 1:0, 2:+1}

        # ---- BELIEF REGISTERS (the mind) ----
        belief = [Signal(signed(8), name=f"belief{s}", init=0) for s in range(N)]

        # ---- SEQUENCER STATE ----
        # Inputs are sampled once, when a tick is accepted, so the result cannot
        # be corrupted by the pins changing part-way through the computation.
        obs_r   = Signal(2)
        csel_r  = Signal(1)
        a_idx   = Signal(2)             # which action is being scored this cycle
        best_sc = Signal(signed(10))    # running argmax: best score so far
        best_a  = Signal(2)             # running argmax: its action index

        # ---- select active preference vector from the latched csel ----
        # Use Mux() (continuous assign) rather than If/Else (procedural always@*):
        # the procedural form produced an always@* block that failed to evaluate
        # in gate/RTL sim, leaving C = X and poisoning every downstream score.
        C = [Signal(signed(8), name=f"C{o}") for o in range(N)]
        for o in range(N):
            m.d.comb += C[o].eq(Mux(csel_r == 0, C_right[o], C_left[o]))

        # ===== PERCEIVE — Bayesian belief update, max-normalised =====
        ev = [Signal(signed(8), name=f"ev{s}") for s in range(N)]
        for s in range(N):
            with m.Switch(obs_r):
                for o in range(N):
                    with m.Case(o):
                        m.d.comb += ev[s].eq(A[s][o])
                with m.Default():
                    m.d.comb += ev[s].eq(A[s][0])
        upd = [clamp_s8(m, f"upd{s}", belief[s] + ev[s]) for s in range(N)]

        mx01 = Signal(signed(8))
        with m.If(upd[1] > upd[0]): m.d.comb += mx01.eq(upd[1])
        with m.Else():              m.d.comb += mx01.eq(upd[0])
        mxall = Signal(signed(8))
        with m.If(upd[2] > mx01):   m.d.comb += mxall.eq(upd[2])
        with m.Else():              m.d.comb += mxall.eq(mx01)
        nb = [clamp_s8(m, f"nb{s}", upd[s] - mxall) for s in range(N)]

        # ===== PLAN — one action's 1-step EFE score, selected by a_idx =====
        # Only ONE scoring cone exists in hardware. The preference term for each
        # state is muxed according to which action is under evaluation:
        #   a=0 (move L) : target states 0,0,1
        #   a=1 (stay)   : target states 0,1,2
        #   a=2 (move R) : target states 1,2,2
        ct = [Signal(signed(8), name=f"ct{s}") for s in range(N)]
        with m.Switch(a_idx):
            for a in range(N):
                with m.Case(a):
                    for s in range(N):
                        tgt = max(0, min(N-1, s + shift[a]))
                        m.d.comb += ct[s].eq(C[tgt])
            with m.Default():
                for s in range(N):
                    m.d.comb += ct[s].eq(C[s])

        terms = [clamp_s8(m, f"t{s}", belief[s] + ct[s]) for s in range(N)]
        sc = Signal(signed(10))
        m.d.comb += sc.eq(terms[0] + terms[1] + terms[2])

        # ===== FULL BELIEF READOUT =====
        with m.Switch(self.bsel):
            with m.Case(0): m.d.comb += self.belief_dbg.eq(belief[0])
            with m.Case(1): m.d.comb += self.belief_dbg.eq(belief[1])
            with m.Case(2): m.d.comb += self.belief_dbg.eq(belief[2])
            with m.Default(): m.d.comb += self.belief_dbg.eq(belief[0])

        # ===== SEQUENCER =====
        # A tick is accepted on its rising edge, so holding the pin high runs one
        # inference rather than free-running.
        tick_d = Signal(1)
        m.d.sync += tick_d.eq(self.tick)
        tick_edge = self.tick & ~tick_d

        with m.FSM():
            with m.State("IDLE"):
                with m.If(tick_edge):
                    m.d.sync += [
                        obs_r.eq(self.obs),
                        csel_r.eq(self.csel),
                        self.ready.eq(0),
                    ]
                    m.next = "PERCEIVE"
            with m.State("PERCEIVE"):
                for s in range(N):
                    m.d.sync += belief[s].eq(nb[s])
                # Below every reachable score: three clamped s8 terms sum to
                # at least -384, so -512 can never win the argmax.
                m.d.sync += [a_idx.eq(0), best_sc.eq(-512), best_a.eq(0)]
                m.next = "PLAN"
            with m.State("PLAN"):
                # Strict > keeps the LOWEST action index on a tie, matching the
                # original parallel argmax.
                with m.If(sc > best_sc):
                    m.d.sync += [best_sc.eq(sc), best_a.eq(a_idx)]
                m.d.sync += a_idx.eq(a_idx + 1)
                with m.If(a_idx == N - 1):
                    m.next = "ACT"
            with m.State("ACT"):
                m.d.sync += [self.action.eq(best_a), self.ready.eq(1)]
                m.next = "IDLE"

        return m

if __name__ == "__main__":
    from amaranth.back import verilog
    c = ActiveInferenceChipV3()
    v = verilog.convert(
        c,
        ports=[c.obs, c.tick, c.bsel, c.csel, c.action, c.ready, c.belief_dbg],
        name="active_inference_core",
        strip_internal_attrs=True,
    )
    open("active_inference_core.v","w").write(v)
    print("v3.1 elaborated. Verilog:", len(v), "chars")
