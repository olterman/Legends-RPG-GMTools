# Fellic Aspect Mapping

The legacy Fellic file does not line up perfectly with the rebuilt taxonomy.

## Legacy Aspect Names

- Cat
- Fox
- Dog
- Bear
- Bull
- Turtle
- Bird

## Current Rebuild Taxonomy

- Feline
- Lupine
- Canine
- Ursine
- Bovine
- Chelonian
- Avian
- Anatine

## Triage Notes

- `Cat -> Feline` is straightforward.
- `Dog -> Canine` is straightforward.
- `Bear -> Ursine` is straightforward.
- `Bull -> Bovine` is straightforward.
- `Turtle -> Chelonian` is straightforward.
- `Bird -> Avian` is mostly straightforward.
- `Fox` does not map cleanly to the current taxonomy.
- `Anatine` exists in the rebuild taxonomy but does not have a clean dedicated legacy section in `the_fellic.json`.
- `Lupine` exists in the rebuild taxonomy but the legacy source currently gives us `Fox`, not `Wolf`.

## Working Rule

Until fuller source material is imported, keep the shared top-level Fellic myth and culture in canonical lore, but treat fine-grained subgroup expansion as an AI-lore triage problem where the taxonomy mismatch needs to be resolved deliberately rather than papered over.
