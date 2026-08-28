## How it works

This chip is a minimal **active inference agent** rendered directly in silicon.
Active inference is a framework from computational neuroscience in which an
agent acts to minimise "surprise" — the mismatch between what it predicts and
what it senses. It does this two ways: by updating its beliefs (perception) and
by acting on the world (action).  

The agent here lives on a 3-position line (LEFT / CENTER / RIGHT). One position
hides a reward. The agent does not know which. Each clock step it runs three
operations: 

1. **Perceive.** It reads a 2-bit observation and performs a Bayesian belief
   update. Because all probabilities are stored as logarithms, the update is a
   simple addition: `belief[state] += log P(observation | state)`. The three
   belief values are then re-normalised by subtracting their maximum.

2. **Plan.** For each of the three possible moves (shift LEFT, stay, shift
   RIGHT) it computes an Expected Free Energy score. The score combines how
   likely the move is to reach a *preferred* position (pragmatic value) with how
   much it sharpens the agent's belief (epistemic value). These reduce to small
   additions over the belief vector and a hardcoded preference table.

3. **Act.** It selects the move with the best score and drives it on the output
   pins, then latches the updated belief.

The entire "mind" of the agent is three 8-bit signed registers holding
log-beliefs, in Q3.5 fixed-point format. The generative model (likelihood,
transition bias, preferences) is baked into the logic as constants. The whole
loop is fixed-point integer logic — no multipliers, no memory, microwatt-class.

Internally one inference step is sequenced by a small state machine rather than
resolved in a single clock edge: perceive, then one cycle per candidate action,
then act. Two reasons, both measured. Registers between the stages are what let
the arithmetic path close timing at 25 MHz in the slow process corners, which it
did not do as one combinational cloud. And scoring the three actions through a
single shared datapath, one per cycle, costs roughly two thirds less planning
logic than three parallel scoring cones. Measured on sky130, the two cuts took
the implied die from 178.9 x 189.6 um down to 126.3 x 137.0 um — roughly a 49%
area reduction, taking the design from about 189% of a 1x1 tile to about 96%.
Neither change is visible from outside apart from the latency.

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
