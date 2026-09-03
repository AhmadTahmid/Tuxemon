# The Tuxemon AI-native foundry

This directory is a compiler laboratory. Tuxemon is treated as a deterministic
runtime target; its current mod is treated as a compatibility corpus.

The first transformation is deliberately observational:

```text
YAML + TMX → typed nodes + evidence edges + proof results + counterexamples
```

Run it with:

```bash
python -m foundry
```

The generated ontology is not a claim that the existing campaign is valid. It
is an inspectable baseline showing what the machine can currently decode and
which references do not resolve. Later generators must satisfy stricter gates
than the observed legacy corpus.

The intended production direction is:

```text
constitution
  → semantic genome population
  → causal and spatial proofs
  → quality-diversity archive
  → TMX/YAML/database/localization compilers
  → real headless Tuxemon execution
  → minimized counterexamples
  → smallest-atom repair
  → signed playable mod
```

## Generated spatial slice

`python -m foundry.town` compiles a real Tuxemon mod from
`worlds/unmapped_province.seed.yaml`. The seed contains intent, topology,
aesthetic genes, a quest automaton, and admission thresholds—not a hand-laid
tile map. The compiler derives the pixel-art atlas, TMX layers, collision
AABBs, events, quest witness, proof certificate, and visual preview.

The same genome now projects a second region, the Echo Wilds. Its palette is
mutated mathematically from the town style; a stochastic route trace is
intersected with a cyclic circuit; sampled forest obstacles are admitted or
repaired at the smallest disconnected cell set. The quest compiler places the
relic there and emits a bidirectional map transition. No second TMX map,
tileset, collision sheet, or transition script is authored by hand.

`python -m foundry.runtime --probe` loads that output in the real Tuxemon
runtime and writes a rendered-frame certificate. `python -m foundry.runtime
--play` launches the explorable build.

`python -m foundry.evolve` explores a deterministic population of semantic
seeds and retains a quality-diversity archive indexed by route length, path
spread, and collision complexity. This replaces choosing one layout by taste
with inspectable fitness plus behavioral diversity.

`python -m foundry.selfplay` makes Tuxemon's own trainer AI control both teams
inside the actual combat state across seeded level cohorts. The result is a
machine-readable termination, duration, and difficulty-curve certificate—not
a spreadsheet or a parallel combat approximation. Combatants, levels, sample
size, desired win-rate band, and turn bounds live in the semantic world seed;
the selected duel is rejected when its measured behavior violates that
contract.

`python -m foundry.playthrough` consumes the admitted quest witness, makes the
real Tuxemon pathfinder walk every route, evaluates the compiled interaction
conditions, executes the actual event actions and battle, and rejects the
world unless the terminal quest state is reached. This joins spatial, causal,
and combat evidence into an executable campaign proof. Its first adverse run
found that losing the duel stranded a fainted party; the semantic world now
requires a reachable clinic recovery action, and the witness deliberately
proves a loss → recovery → retry → victory cycle.

The witness also walks from town into the generated Echo Wilds, traverses the
runtime path to the relic, returns through the compiled gateway, and only then
continues to the duel. This prevents a collection of individually valid maps
from masquerading as a valid connected campaign.

On Windows, `play_unmapped_province.cmd` is the one-click entry point. Arrow
keys move, Enter interacts, and Escape opens or closes menus.

## Proof-carrying Windows release

`make foundry-release` freezes the compiler-selected game as a standalone
Windows executable, boots that executable in a hidden smoke run, and promotes
it only when five independently generated certificates agree on one world
fingerprint: static admission, real-runtime traversal, actual-engine combat
self-play, full campaign playthrough, and frozen-runtime loading.

The release compiler writes `release-manifest.json` beside the executable. It
contains hashes for every payload file and a hash-linked summary of every
proof. The deterministic ZIP and its external receipt are written under
`dist/`. This makes a release a consequence of machine-checkable evidence,
not a manually assembled folder or a declaration that a build "seems done."
