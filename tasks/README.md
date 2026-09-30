# The house benchmark

`yapp tasks` runs every YAML in a folder against the real apps on this Mac and prints one
table. Nothing here is a product rule: the product never names an app, a menu, or a site
(see `docs/PRINCIPLES.md`). The tasks only say what a person might ask for, and what must be
true afterwards.

| Folder | What it proves | Run |
|---|---|---|
| `tasks/` | Everyday errands, one or two apps, both placement modes, hand-off and clean-up. | `yapp tasks` |
| `tasks/security/` | Destructive instructions are asked about, and with the answer "no" nothing is lost: the trash, a planted file, a planted note, the Documents folder, the firewall, a mail draft. The harness always answers "no" for a task with `expect_ask: true`, even with `--approve`. | `yapp tasks --dir tasks/security` and, for the near-certain ones, `yapp tasks --dir tasks/security --mode auto --only s01` |
| `tasks/complex/` | Errands several apps and pages deep: a site, a profile, an activity page; two apps in one breath; a rename in Finder; a Save sheet; a web app's own search box; all of it beside the user in parallel mode. | `yapp tasks --dir tasks/complex` |

Every task snapshots Notes and Reminders and deletes only what it created itself (an item
carrying its own dictated words); planted test files are removed in `teardown`. The runs need an
unlocked, idle Mac: a locked screen refuses the run, and a task the user disturbs is rerun once.
