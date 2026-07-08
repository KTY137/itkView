# itkFlow Agent Instructions

This repository uses `CLAUDE.md` as the canonical project rulebook. All agents
must read it before substantial planning or implementation.

Mandatory startup context:

1. Read `CLAUDE.md`.
2. Read the living execution roadmap in `docs/04-roadmap.md`.
3. Align work with the nearest active roadmap milestone unless the user
   explicitly redirects the task.
4. Do not invent a competing roadmap in chat. Update `docs/04-roadmap.md`, or
   leave a clear handoff note naming the affected roadmap item.
5. Before any UI work, read the binding UI design reference
   `docs/05-ui-design-reference.md` and its mockup, and do not drift from the
   design goal. Reuse the layout/interaction; product labels stay English.

Hard rules, summarized:

- Never execute or import `references/zeuthenflow`; read/grep only.
- Never develop or test against the production ITk PDB. Defaults must point to
  the PDB test instance.
- Do not commit secrets, tokens, personal data, or non-anonymized fixtures.
- Do not hardcode institute-specific behavior; it belongs in the institute
  profile/configuration.
- Product-facing UI, API text, code comments, and user/developer docs are
  English. Internal planning docs under `docs/0*.md` stay German.
