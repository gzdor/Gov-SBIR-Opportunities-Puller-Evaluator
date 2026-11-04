# Three-minute walkthrough (recording script)

Show you in the loop. Do not lead with the ASCII boot screen.

## Setup (off camera)

- Checkout this repo, `conda activate dsip-opportunities`, `pip install -r requirements.txt`.
- Have `test/fixtures/OSW-DRPM_SBIR_27BZ_R1.pdf` in place.
- Optional: a failing scratch test you can revert.

## Minute 0:00 — the contract

“This is a local DSIP open-topics appliance. The agent writes the code.
I write the vetoes. Nothing typed goes to DSIP as searchText. Page limits
are extractive — no typical 15.”

Open `docs/design-decisions/011-volume-page-limits.md` for one beat.

## Minute 0:30 — the test that caught the lie

Open `test/test_analyze.py` at `test_osw_dv002_drpm_uxs_page_limits_are_five_and_five`.

“OSD DV002 states five and five. The agent kept filling typical DoW 15.
This test is the contract.”

Run:

```bat
pytest test/test_analyze.py::test_osw_dv002_drpm_uxs_page_limits_are_five_and_five test/test_analyze.py::test_volume_page_limits_blank_when_baa_silent -q
```

Green. Say: “If this goes red, the GUI is lying again.”

## Minute 1:20 — silent 403

Open `dsip_http.py` at `default_workers` and `ensure_session`.

“64 workers plus a VPN got us Akamai Access Denied. Warmup used to
swallow every topics-app failure. Now it prints. Cap is 8.”

Open `test/test_main.py::test_http_403_message_explains_akamai_block`.

## Minute 2:00 — restore, don’t blank

“A failed download used to persist an empty last_output. Launch looked
dead. We keep the last snapshot that still has a manifest.”

Point at `test_gui_restores_latest_manifest_if_last_output_is_empty`.

## Minute 2:30 — close

“I would not send this repo as ‘the polished product.’ I would send it as
the lab notebook: ADRs, failing tests, a time the agent was wrong, and
the fix. That is agentic coding.”

Stop. Do not demo the splash unless they ask.
