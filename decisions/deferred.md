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
| Rain for the next two hours in `weather_now`, from MET's radar nowcast | The walking skeleton merged into main | One product at a time keeps the first review small |
| A forecast cache kept on disk across restarts | The walking skeleton merged; it must land before the plugin is approved for the voice | A restart forgets the cache and can ask MET again before `Expires`, which MET's terms forbid. One change per pull request |
| Telling apart two towns with the same name in one county | The first time a spoken name picks the wrong one of two such towns | A county is enough for every shared name tried so far; asking by municipality as well doubles the question |
| `pre-commit` as a requirement rather than an option | A second contributor | The gates run in CI, and a hook one person installs is a hook one person maintains |
