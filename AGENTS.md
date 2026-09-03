# AI-native foundry contract

This fork treats Tuxemon as a deterministic execution target, not as an
artisan-facing authoring environment.

## Production law

> Probabilistic systems propose. Deterministic systems admit. The runtime only
> executes admitted artifacts.

- Do not hand-author derived TMX, campaign YAML, database records, balance
  tables, localization catalogs, or raster sheets when a compiler can emit
  them from a smaller semantic representation.
- AI changes authoritative intent through typed genome mutations. It does not
  directly patch runtime state or scatter unrelated edits across generated
  files.
- Existing Tuxemon formats are compiler targets. Preserve compatibility with
  the engine unless an executable counterexample proves that the engine
  boundary itself must change.
- Every hard guarantee requires a machine-checkable proof obligation or an
  adversarial counterexample.
- Use the actual Tuxemon runtime for executable exploration and combat
  evaluation. Approximate models must declare and measure their divergence.
- Preserve rejected candidates and minimized failure traces. Never weaken a
  tolerance after observing a candidate.
- Repair the smallest failed semantic atom and freeze admitted siblings.
- Keep stochastic prompts, seeds, model identifiers, fingerprints, lineage,
  and admission results with generated artifacts.
- Human input defines constitutions, taste, and release intent. It does not
  manually compensate for missing production machinery.
- Never describe proxy metrics as proof of fun, beauty, meaning, or player
  preference.

## Repository boundaries

- `tuxemon/` is the deterministic runtime inherited from upstream.
- `mods/tuxemon/` is the observed legacy corpus and compatibility fixture.
- `foundry/` is the semantic ingestion, generation, proof, repair, and
  compilation layer.
- `foundry/artifacts/` contains reproducible generated certificates.
- A future generated game mod must live outside `mods/tuxemon/` and must be
  reproducible from its genome.

## First admission gate

Before generated campaign content can enter play, the foundry must prove:

1. source data and maps decode;
2. every emitted reference resolves;
3. mandatory map transitions are spatially traversable;
4. every mandatory quest has an executable completion witness;
5. combat lies inside the declared policy envelope;
6. generated assets satisfy their semantic identity packs;
7. save/load replay preserves authoritative facts.
