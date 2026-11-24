# PanelProof contributor instructions

Read [the contract](reference/CONTRACT.md) and the assigned GitHub issue before changing code. Inspect the tree and its tests. Use the existing interfaces, scope work to the issue, and coordinate schema changes across Python, Rust, and TypeScript.

Run the acceptance checks you can execute. In the handoff, record changed paths, commands, results, artifact locations, and remaining work. State which checks were skipped and why. Clearly label mock runs and synthetic fixtures. Keep prompts and provider credentials out of Git.

Keep the default development flow local, CPU-only, and free of inference calls. Treat a live evaluation as a separate run with verified model access, agreed limits, and an explicit opt-in. Use only public task content when calling providers. Keep test answers and generated private evidence out of Git.

The code and examples implement fictional rules for a visual benchmark. Read [the submission checklist](reference/SUBMISSION.md) and [source references](reference/SOURCES.md) when preparing evidence or release artifacts.
