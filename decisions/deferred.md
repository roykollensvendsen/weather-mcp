# What is deliberately not done yet

A thing left undone with no trigger is a thing forgotten. Each row names what
would make it worth doing, so the question comes back on its own rather than
depending on someone remembering it. Nothing enforces a trigger; the list is
read whenever a decision record is written and when a phase ends.

| Not done | The trigger | Why not now |
|---|---|---|
| A coverage threshold in CI | Two months of measured coverage to set it below | A number picked before there is data is a guess with a gate on it |
| A code of conduct and issue templates | A second contributor, or the first outside issue | Boilerplate answering questions nobody has asked |
| A release workflow and publishing | The first release someone outside will install | A published name is claimed and a published version cannot be reused |
| `CODEOWNERS` | A second person who reviews | It would name one person as the owner of everything |
| Rows under `scripts/mutations/` for the two rules marked in `scripts/imperative.py`, which already have tests | A change to that script here | They are guarded where the template keeps them, and are unchanged here |
| A hook that runs the private-data scan with home and the private list before each push | `pre-commit` made a requirement, or a second machine that commits here | CI has no config, so only the patterns run there; the owner runs the full scan by hand, and the scan says plainly what it could not check |
| `pre-commit` as a requirement rather than an option | A second contributor | The gates run in CI, and a hook one person installs is a hook one person maintains |
