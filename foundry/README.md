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

`python -m foundry.runtime --probe` loads that output in the real Tuxemon
runtime and writes a rendered-frame certificate. `python -m foundry.runtime
--play` launches the explorable build.

On Windows, `play_unmapped_province.cmd` is the one-click entry point. Arrow
keys move, Enter interacts, and Escape opens or closes menus.
