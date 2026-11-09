# Design decisions

Architecture Decision Records (ADRs) for this downloader. Each file is one
decision: context, what we chose, why, tradeoffs, and the **counter-adversarial
review** that had to fail before the code landed.

| ADR | Decision |
| --- | --- |
| [000](000-template-and-process.md) | How we write ADRs and run the adversarial pass |
| [001](001-search-aliases.md) | Local AND-of-OR alias search (`DAF`, `UAS`, `Air Force`) |
| [002](002-dark-theme.md) | Dark clam Tkinter theme, no theme pack |
| [003](003-competitive-local-catalog.md) | Beat SaaS BD tools on DSIP snapshot depth, not by cloning a CRM |
| [004](004-adversarial-review.md) | Findings the counter-agent raised and how they were closed |
| [005](005-multi-source-modes.md) | GovWin / SAM / grants / SLED: keep DSIP; never GovWin or county scrape |
| [006](006-bd-triage-pipeline.md) | Local Pursue/Watch/Pass, pipeline strip, copy-brief — not a CRM |
| [007](007-topic-qa-and-component-chips.md) | Published Topic Q&A in the snapshot; DSIP component chips |
| [008](008-how-sbir-works-tab.md) | Offline How-SBIR-works tab; no consultant reprint or scrape |
| [009](009-hygiene-and-donext.md) | Hygiene + Do Next sprint: details, overview, persist, calendar |
| [010](010-optional-local-llms.md) | Future opt-in local Ollama/llama.cpp for snapshot text; no cloud/HF |
| [011](011-volume-page-limits.md) | Extractive tech-vol / feasibility page limits; blank if unstated |
| [012](012-camgian-commercial-carve-out.md) | PolyForm NC plus Camgian Corporation-only commercial use |

Do **not** use these notes as permission to: publish an unsigned `.exe`, send
filter text to DSIP `searchText`, call a cloud LLM or pull HuggingFace
weights, add third-party OAuth,
search GovWin, scrape navysbir.com, or scrape state/county portals. [005](005-multi-source-modes.md)
is research, not a green light to land those clients.
