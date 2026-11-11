# AI usage

I designed this project and made its decisions: the problem, the data, the stack, the drift rule, the promotion gate and the trade-offs recorded in `docs/HLD.md`.

I used an AI coding assistant, Claude Code, throughout the build, under my direction. It helped write code, tests and documentation. It also wrote the evidence-capture script (`scripts/capture_evidence.py`, with `scripts/capture_evidence_host.sh`) that made the gallery in `docs/evidence/`. The 11 user-manual screenshots in `docs/screenshots/` I took myself, by hand.

I worked one stage at a time. After each stage I read the changes, ran the tests and the live checks, and asked for fixes where something was wrong before I committed it. `docs/PROGRESS.md` records each stage as it was built. I can explain every part of the project.
