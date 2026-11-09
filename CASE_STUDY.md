# Case study: local DSIP Discovery under agentic coding

A capture analyst needs the current DoD SBIR/STTR open-topics catalog on
disk — topic PDFs, instruction books, published Q&A, extractive briefing —
without a GovWin seat and without sending typed filters to DSIP.

The product is a **local appliance** (Tkinter + stdlib HTTP). An agent
wrote most of the code. The hiring signal is the **loop**, not the radar
icon.

## Standing vetoes (the contract)

- Nothing typed is sent as DSIP `searchText`.
- Page-limit cells are extractive. Typical DoW 15/5 is never filled in.
- No cloud LLM, no HuggingFace, no login/ask-Q&A, no CRM.
- No public unsigned `.exe`. No scrape of navysbir.com / GovWin.

## Three times the agent was confidently wrong

1. **Typical 15.** The extractor filled “usual” DoW tech-vol caps when
   the BAA was silent. The test became the contract: OSD DRPM UxS DV002
   must read **5 / 5** from the instruction PDF; silent BAAs stay blank.
2. **Blank columns after a green test.** `bluf_row` cached empty strings;
   the GUI painted the cache. `pypdf` was missing in the interpreter that
   actually launched `run-gui.bat`. Recompute on load; install `pypdf`
   into *that* Python.
3. **Akamai 403.** Default `cpu_count * 5` became 64 workers. Plus VPN.
   Cookie warmup was silent when topics-app failed. Cap is 8; warmup
   errors are printed; 403 text says “open topics-app in a browser.”

## What to look at

- Tests as spec: `test_osw_dv002_*`, `test_volume_page_limits_blank_*`,
  `test_http_403_message_*`, `test_gui_restores_latest_manifest_*`.
- ADRs in `docs/design-decisions/` (000–012) and the adversarial review.
- `dsip_http.py` — the honest network client.
- `WALKTHROUGH.md` — three-minute recording script of the loop.

PolyForm Noncommercial, plus a Camgian Corporation-only commercial
carve-out (LICENSE addendum / ADR 012). Government PDFs stay public-domain
U.S. works.
