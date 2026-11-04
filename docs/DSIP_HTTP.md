# DSIP HTTP client

`dsip_http.py` is the only module that talks to `dodsbirsttr.mil`.

It is a **public catalog client**, not a login and not a stealth scraper.
The topics-app JSON routes sit behind Akamai. A normal browser:

1. Opens `https://www.dodsbirsttr.mil/topics-app/`
2. Sends a desktop Chrome User-Agent
3. Sends that page as `Referer` on later `/topics/api/public/...` calls
4. Keeps the first-party cookies Akamai set on step 1

This appliance does the same four things. That is impersonation of the
topics-app tab, documented here so a reviewer does not have to guess.

## What is sent

| Piece | Value |
| --- | --- |
| User-Agent | Chrome 131 on Windows |
| Referer | `/topics-app/` |
| Cookie warmup | one GET of `/topics-app/` before the first API call |
| searchParam | open-topics statuses 591/592; **JSON nulls omitted** |
| searchText | never set from anything you type |

Typed filters stay on this machine (`analyze.filter_topics`).

## Failure modes

- **HTTP 403 / Access Denied** is a WAF/IP block, not a missing login.
  The error text tells you to open the topics-app URL in a browser on
  this PC. If that page is also denied, VPN or a prior flood is the cause.
- **Cookie warmup failure is printed.** It is not swallowed. A later 403
  repeats the warmup error.
- **Workers default to at most 8.** 64 parallel PDF fetches were enough
  for Akamai to ban the IP.

Retry only 429/5xx, three times, with a pause. A 403 is not retried in a
tight loop.
