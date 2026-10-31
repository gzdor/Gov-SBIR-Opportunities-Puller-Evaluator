# Implementation recommendations

Working backlog for the local DSIP appliance. Polar = deepen the snapshot.
Evaluator = no CRM, no login, no public unsigned `.exe`, no `searchText`, no
cloud LLM, no navysbir/GovWin scrape.

## Landed (2026-10-30)

Hygiene

- Toolbar wraps: Find / Export / Diff on row 1; Open folder / snapshot /
  settings on row 2.
- `_render_table` restores selection, focus, and `yview` after catalog-first
  `item_done` refreshes.
- `STATE_FILE` (`~/.dsip_downloader_state.json`) is documented as
  machine-local. It now also stores chips, Find, call filter, and tech area.
- `test_gui_download_button_runs_full_flow` skips on the conda Tk `scale.tcl`
  flake instead of failing the suite.

Do Next

1. Public `/topics/{id}/details` → `details/*.json` (keywords, tech areas,
   ITAR, objective). Invalid ids refuse before `open_url`.
2. **New** / **Changed** chips after **Diff previous…** (`snapshot_diff` by
   `topicCode`).
3. `refresh_due_in` on snapshot load so a restored folder ages.
4. Chip counts in labels; empty Component chips hide until **Show empty
   components** is on (not on a blank first launch).
5. Persist chips / Find / call filter / tech area in `STATE_FILE`.
6. **Open instruction PDF** via `resolve_pdf` (topic `instructionPdfs` or
   `solicitation_documents/`).
7. Full published Q&A in the Topic pane (`format_qa_excerpt(..., limit=None)`).
8. Ctrl+F focuses Find; Ctrl+B copies the brief; `1`/`2`/`3`/`0` stay
   table-only.
9. README screenshot caption stays; architecture diagrams moved to
   `CURRENT_ARCHITECTURE_README.md`.
10. FY27 monthly calendar in the How-SBIR-works tab as a dated snapshot.
    navysbir.com is a citation link only.

Topic overview

- Clicking a row shows **Overview (local extract from the topic PDF /
  details)** — `analyze.topic_overview_paragraph`. Not a neural net.

## Do not do

- Scrape navysbir.com, GovWin, BidNet, or county portals.
- Send Find / chips / download filter as DSIP `searchText`.
- Call OpenAI / HuggingFace / any hosted model for the overview. A later
  **opt-in local** Ollama or llama.cpp client is recorded in
  [ADR 010](design-decisions/010-optional-local-llms.md); it is not landed.
- Publish an unsigned `.exe` on GitHub Releases.
- Add DSIP login, “ask a question,” or a CRM pipeline.

## Later (only if named)

- Official opt-in clients from [ADR 005](design-decisions/005-multi-source-modes.md)
  (sbir.gov API, Grants.gov, SAM.gov with the user’s own key).
- Optional **localhost** Ollama or llama.cpp rewrite/query of the current
  snapshot, off by default, extractive fallback — [ADR 010](design-decisions/010-optional-local-llms.md).
  Do not bundle a GGUF in the exe.
- Code-signed public Windows download.
- Replace `docs/images/app-window.jpg` after the next real capture (counts,
  overview, instruction button).
- Optional second instruction PDF picker when a topic lists several.

## How to take a slice

One ADR or one test file per slice. Run `pytest` from the repo root with
`dsip-opportunities` active. Add a row to
[004-adversarial-review.md](design-decisions/004-adversarial-review.md) before
the code lands.
