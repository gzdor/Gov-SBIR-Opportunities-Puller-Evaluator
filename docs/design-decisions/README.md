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

Do **not** use these notes as permission to: publish an unsigned `.exe`, send
filter text to DSIP `searchText`, call a cloud LLM, add third-party OAuth,
search GovWin, or scrape state/county portals. [005](005-multi-source-modes.md)
is research, not a green light to land those clients.
