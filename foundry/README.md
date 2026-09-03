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

The same genome now projects three expedition regions: the Echo Wilds,
Skyglass Garden, and Root Vault. Their palettes are mutated mathematically
from the town style; stochastic route traces are intersected with cyclic
circuits; sampled obstacles are admitted or repaired at the smallest
disconnected cell set. No regional TMX map, tileset, collision sheet, or
transition script is authored by hand.

`python -m foundry.campaign` treats the ecology tournament's admitted
survivors and semantic region roles as atoms. It enumerates whole campaign
assignments and minimizes distance from the requested dramatic curve. The
current campaign organism assigns Metesaur to the opening ordeal, Toucanary to
the short respite, and Vivipere to the long culmination. It also synthesizes
the nine-transition quest automaton consumed by the compiler and generic
playthrough interpreter; neither component contains a hard-coded map list.

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

The witness walks from town through every selected region, traverses the
runtime path to each sigil, returns through the compiled gateway, and only
then continues to the duel. It executes whatever campaign is present in the
lock rather than a scripted Echo Wilds walkthrough. This prevents a
collection of individually valid maps from masquerading as a connected
campaign.

`python -m foundry.ecology` derives a sentinel population directly from the
monster database using habitat and evolutionary-stage predicates, preserves
elemental diversity, and evaluates every species/level candidate through
Tuxemon's real combat state. Failed or stalled candidates are isolated and
journaled instead of aborting the population. The selected ecology is a
content-addressed lock consumed by the world compiler; the current survivor is
a level-4 Metesaur selected from 32 habitat-compatible species and 570
terminating battle trials.

The campaign witness fault-injects a one-HP party at the first sentinel and
proves that every actual loss can retreat across its region boundary, heal at
the generated clinic, re-enter the currently active region, and eventually
defeat the selected ecology. This tests recovery in the compiled scenario
rather than assuming self-play RNG seeds transfer between different
party-construction histories.

`python -m foundry.assets` verifies every semantic atlas and preview has its
declared shape, every generated TMX/TSX/PNG reference resolves, and regional
style projections remain content-distinct. It explicitly makes no claim that
these proxy properties prove beauty.

`python -m foundry.persistence` takes a checkpoint inside the first generated
region using Tuxemon's real `SaveData` encoder, fault-injects corruption into
quest state, position, and party health, reloads the file, compares the
authoritative facts, and resumes through a compiled return event. Persistence
is therefore an executable campaign invariant rather than an assumed engine
feature.

On Windows, `play_unmapped_province.cmd` is the one-click entry point. Arrow
keys move, Enter interacts, and Escape opens or closes menus.

## Proof-carrying Windows release

`make foundry-release` freezes the compiler-selected game as a standalone
Windows executable, boots that executable in a hidden smoke run, and promotes
it only when nine independently generated certificates are valid and every
world-bound certificate agrees on one fingerprint: world admission, ecology
selection, campaign selection, semantic asset identity, real-runtime probing,
actual-engine combat self-play, full campaign playthrough, persistence replay,
and frozen-runtime loading.

The release compiler writes `release-manifest.json` beside the executable. It
contains hashes for every payload file and a hash-linked summary of every
proof. The deterministic ZIP and its external receipt are written under
`dist/`. This makes a release a consequence of machine-checkable evidence,
not a manually assembled folder or a declaration that a build "seems done."
