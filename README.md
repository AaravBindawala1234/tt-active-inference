![](../../workflows/gds/badge.svg) ![](../../workflows/docs/badge.svg) ![](../../workflows/test/badge.svg) ![](../../workflows/fpga/badge.svg)

# Active Inference Agent — a Bayesian agent in silicon

A [Tiny Tapeout](https://tinytapeout.com) project: a complete **active inference
agent** implemented as fixed-function digital logic in a single 1x1 tile, taped
out on the IHP SG13G2 open PDK.

- [Read the full documentation](docs/info.md)

## What it does

Active inference is a framework from computational neuroscience in which an
agent maintains beliefs about the world and acts to bring about the states it
prefers. This chip implements that whole loop — perception and action — in
integer arithmetic, with no processor, no memory and no multipliers.

The agent lives on a 3-position line. Its sensor is unreliable (an observation
matches the true position only 80% of the time), so it must infer where it is
from noisy evidence, then choose a move that takes it toward the position it
prefers.

Its entire mind is **three 8-bit signed registers** holding log-probabilities in
Q3.5 fixed point. Working in the log domain turns Bayes' rule into addition:

```
belief[state] += log P(observation | state)
```

so the chip never needs a hardware multiplier. Each tick it runs:

1. **Perceive** — Bayesian belief update from the observation, then re-normalise
   by subtracting the maximum.
2. **Plan** — score each of the three candidate moves by the pragmatic term of
   expected free energy: `score(a) = sum_s belief[s] + C[target(s, a)]`.
3. **Act** — drive the highest-scoring move onto the output pins.

The three action scores are evaluated one per cycle through a single shared
datapath, so an inference step takes six clocks rather than one. That is what
lets the design close timing at 25 MHz in the slow corners *and* fit a 1x1 tile.

## Runtime-switchable goal

The headline demonstration is `ui[7]` (`csel`), which selects between two baked
preference vectors. Feed the chip the **same** observation with `csel` flipped
and it takes the **opposite** action — identical evidence, identical beliefs,
opposite behaviour, because only the goal changed. That is the active inference
claim made physical.

## Pinout

| pin | function |
|---|---|
| `ui[1:0]` | observation (0 = LEFT, 1 = CENTER, 2 = RIGHT) |
| `ui[2]` | tick — rising edge runs one inference step |
| `ui[4:3]` | unused |
| `ui[6:5]` | `bsel` — which belief to show on the debug bus |
| `ui[7]` | `csel` — goal (0 = seek RIGHT, 1 = seek LEFT) |
| `uo[1:0]` | chosen action (0 = move LEFT, 1 = stay, 2 = move RIGHT) |
| `uo[2]` | ready — decision valid, 6 clocks after the tick |
| `uio[7:0]` | selected belief value, signed Q3.5 |

## Source

The RTL is generated from [Amaranth HDL](https://amaranth-lang.org):
[`src/active_inference_v3.py`](src/active_inference_v3.py) is the design;
[`src/active_inference_core.v`](src/active_inference_core.v) is its generated
Verilog, and [`src/project.v`](src/project.v) is the Tiny Tapeout wrapper.
Regenerate with:

```
python3 src/active_inference_v3.py
```

## Testing

```
cd test && make
```

Runs three cocotb testbenches: the goal-switching demonstration, eight golden
multi-step traces checked against a fixed-point reference model (actions and
final beliefs), and a check that `tick` is edge-triggered rather than
level-sensitive. The same tests are re-run by CI against the post-layout
gate-level netlist with real cell delays.

## Resources

- [Tiny Tapeout FAQ](https://tinytapeout.com/faq/)
- [Digital design lessons](https://tinytapeout.com/digital_design/)
- [Join the community](https://tinytapeout.com/discord)
