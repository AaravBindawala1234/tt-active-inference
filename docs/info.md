## How it works

This chip is a minimal **active inference agent** rendered directly in silicon.
Active inference is a framework from computational neuroscience in which an
agent acts to minimise "surprise" — the mismatch between what it predicts and
what it senses. It does this two ways: by updating its beliefs (perception) and
by acting on the world (action).  

The agent here lives on a 3-position line (LEFT / CENTER / RIGHT). It knows
which position it would *prefer* to occupy — that is baked in, and selectable at
runtime — but it does not know with certainty *where it currently is*. Its
sensor is unreliable: an observation matches the true position only 80% of the
time. So the agent must infer its own location from noisy evidence, and act on
that inference. Each tick it runs three operations:

1. **Perceive.** It reads a 2-bit observation and performs a Bayesian belief
   update. Because all probabilities are stored as logarithms, the update is a
   simple addition: `belief[state] += log P(observation | state)`. The three
   belief values are then re-normalised by subtracting their maximum.

2. **Plan.** For each of the three possible moves (shift LEFT, stay, shift
   RIGHT) it computes an expected-free-energy score: for every position it might
   currently be at, weighted by how strongly it believes it is there, how much
   would it like the position that move would lead to?  In symbols,
   `score(a) = sum_s belief[s] + C[target(s, a)]`, where `C` is the preference
   vector. This is the **pragmatic** (goal-seeking) term of expected free energy
   only. The epistemic, information-seeking term is deliberately not
   implemented: in a 3-state world with a fixed observation model there is
   little ambiguity for an exploratory action to resolve, and the term would
   have cost silicon for no change in behaviour. So "EFE" here is doing less
   than the full textbook quantity, and the agent is purely goal-directed.

3. **Act.** It selects the move with the best score and drives it on the output
   pins, then latches the updated belief.

The entire "mind" of the agent is three 8-bit signed registers holding
log-beliefs, in Q3.5 fixed-point format. The generative model — the observation
likelihood matrix, the deterministic shift model, and the two preference vectors
— is baked into the logic as constants. The whole loop is fixed-point integer
logic: no multipliers, no memory, no arithmetic wider than 10 bits.

Internally one inference step is sequenced by a small state machine rather than
resolved in a single clock edge: perceive, then one cycle per candidate action,
then act. Two reasons, both measured. Registers between the stages are what let
the arithmetic path close timing at 25 MHz in the slow process corners, which it
did not do as one combinational cloud. And scoring the three actions through a
single shared datapath, one per cycle, costs roughly two thirds less planning
logic than three parallel scoring cones. The restructure was driven by
measurement: an earlier single-cycle revision missed setup timing in all three
slow corners and implied a die about 89% larger than a 1x1 tile. As hardened for
ihp-sg13g2 the design is 47 sequential cells and about 750 combinational and
buffer cells, fitting a 1x1 tile with setup, hold, max-slew and max-cap all
clean. Neither change is visible from outside apart from the latency.

An earlier revision carried a 2-bit "precision" (gamma) input intended to tune
how decisively the agent commits. It was removed because it could not work: it
scaled every action score by the same positive constant before a deterministic
argmax, and that cannot change which score is largest. Precision is real in
active inference, but it only has an effect when the action is *sampled* from a
softmax over expected free energy; under an argmax the temperature cancels.
`ui[4:3]` are consequently unused.

## How to test

1. Apply a clock (25 MHz nominal, but any frequency works for logic testing).
2. Pulse `rst_n` low then high to reset. All beliefs start at 0 (no idea).
3. Set the observation on `ui[1:0]`:
   - `00` = sensed LEFT, `01` = sensed CENTER, `10` = sensed RIGHT.
4. Pulse `ui[2]` (tick) high for one clock to run an inference step. The step is
   started by the rising edge, so holding the pin high runs one inference rather
   than free-running.
5. Wait for `uo[2]` (ready) to go high — six clocks after the tick. It stays
   high until the next tick is accepted.
6. Read the result:
   - `uo[1:0]` = chosen action (0=move LEFT, 1=stay, 2=move RIGHT).
   - `uio[7:0]` = the belief value selected by `ui[6:5]` (bsel), signed Q3.5 —
     watch the LEFT belief drop as you feed RIGHT observations.

Feed a run of "sensed LEFT" observations and the agent should commit to moving
toward its preferred position; flip to "sensed RIGHT" observations and watch the
belief register cross over as it revises its inference.

## External hardware

None required. Optionally wire `uio[7:0]` to 8 LEDs to visualise the belief
state, and `uo[1:0]` to 2 LEDs to see the chosen action.
