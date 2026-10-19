# Inbox plugin

## Principles
- The plugin channel and core snapshot own message and task state.
- Never infer task identity from incoming text or turn navigation into completion.
- External sends remain behind existing source and delivery guards.
- Reproduce known failures with deterministic offline tests first.

## Ivan decides
Owner decisions cover external services, money, relationships and information only
the owner has. Technical changes within an authorized scope go to docs/decisions.md.

## Work
Read docs/solutions/INDEX.md before non-trivial work; capture lessons with /compound.
Run the local gate with the core source on PYTHONPATH (or HUB_CORE):
`python3 tools/check.py`. `.local-ci.json` uses the same command.
Tests mock sources and sends. Browser acceptance uses an isolated headless browser and synthetic journal; no real account or live collector is needed.
Keep changes small. Installing a plugin activates its source: preserve operational
holds and concurrent edits; a source check does not prove rendered/live acceptance.

## Live development cadence
Ivan uses the development page while work continues. Publish coherent small fixes after their focused checks; do not repeat the full suite before every push. Run the full local gate at checkpoints and before claiming the complete audit finished. Verify the actual live URL after integration. Native screenshots are the visual target; a supplied screenshot is an example, not the audit scope.
