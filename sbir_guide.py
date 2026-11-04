"""Offline 'How the SBIR program works' copy for the desktop app.

Text is original to this repo. It restates public SBA / DSIP / DoW process
rules. It is not a scrape or reprint of any consultant page. A third-party
Air Force/AFWERX explainer is listed under LINKS for further reading.
"""

from __future__ import annotations

# Official first. Third-party last, labeled as unaffiliated.
LINKS = (
    ("DSIP topics and Topic Q&A", "https://www.dodsbirsttr.mil/topics-app/"),
    (
        "DSIP active solicitation PDFs",
        "https://www.dodsbirsttr.mil/submissions/solicitation-documents/active-solicitations",
    ),
    ("SBIR.gov program overview", "https://www.sbir.gov/"),
    ("SAM.gov registration", "https://sam.gov/"),
    ("SBA Company Registry", "https://www.sbir.gov/registration"),
    ("AFWERX funding vehicles", "https://afwerx.com/"),
    (
        "DoW FY27 solicitation calendar citation (confirm dates on DSIP)",
        "https://www.navysbir.com/solicitations.htm",
    ),
    (
        "Third-party AFWERX/open-topic explainer (unaffiliated)",
        "https://investech-consulting.com/programs/afwerx-sbir/",
    ),
)

SECTIONS: tuple[tuple[str, str], ...] = (
    (
        "What this tab is",
        "Local briefing for a capture lead — not a live feed, not legal advice.\n"
        "• Catalog tab = what is actually on DSIP right now.\n"
        "• Funding cells that say “typical” are inferred FY ceilings, not a "
        "quote from that topic sheet.\n"
        "• Official rules win if they disagree with anything here.",
    ),
    (
        "Who can propose",
        "SBIR/STTR is limited to U.S. for-profit small businesses.\n"
        "• Generally 500 employees or fewer, including affiliates.\n"
        "• More than 50% owned and controlled by U.S. citizens or permanent "
        "residents.\n"
        "• Work performed in the United States.\n"
        "The regulation is 13 CFR 121.702; that rule has listed exceptions.\n"
        "Topics add DoW constraints: a CMMC level, possible ITAR, and — for "
        "Direct to Phase II — feasibility evidence that must not come from "
        "prior federally funded SBIR/STTR work.",
    ),
    (
        "Specific topic vs open topic",
        "Specific: the sheet states the technical need. You already do that "
        "work, or you can get there in Phase I.\n"
        "Open (titles often include OPEN): you bring a dual-use solution, but "
        "you still need a named Air Force or Space Force customer problem.\n"
        "There is no standing “Air Force SBIR window” outside published DSIP "
        "topics. Open topics can be Phase I, Direct to Phase II, or both — "
        "the topic text decides, not the program name.",
    ),
    (
        "AFWERX, SpaceWERX, and DSIP",
        "AFWERX and SpaceWERX are Department of the Air Force innovation "
        "front doors. The money still lands through DoW SBIR/STTR releases.\n"
        "• File every proposal in DSIP against a published topic under the "
        "BAA or CSO.\n"
        "• After Phase I/II, AFWERX follow-on vehicles (TACFI, STRATFI) can "
        "pair government and private funds toward Phase III.\n"
        "Those vehicles are not a substitute for a matching topic.",
    ),
    (
        "Pre-release, open, and questions",
        "Pre-release: TPOC names are usually visible; some components allow "
        "direct questions.\n"
        "Open: questions go through DSIP Topic Q&A only.\n"
        "This app can download published answers; it cannot post a question "
        "(that needs a DSIP login). Draft the technical volume while Q&A is "
        "still moving — answers change the requirement.",
    ),
    (
        "Registrations and a real submission",
        "Before close you need all three:\n"
        "• Active DSIP account\n"
        "• SAM.gov registration\n"
        "• SBA Company Registry entry\n"
        "Upload volumes in DSIP. A package left in “In Progress” or “Ready to "
        "Certify” at the deadline is not submitted. Certify before the last "
        "day. Components typically notify select/non-select within 90 days of "
        "the close.",
    ),
    (
        "Direct to Phase II vs Phase I",
        "If the topic is Direct to Phase II (D2P2), a Phase I proposal is "
        "rejected.\n"
        "• Feasibility documentation cannot be prior federal SBIR/STTR work.\n"
        "• In this catalog those topics often carry a -DV code or “Direct to "
        "Phase II” in the sheet.\n"
        "Use the D2P2 chip on the Catalog tab to list them.",
    ),
    (
        "Where the dollar figure lives",
        "Many Air Force topics do not print an award ceiling on the topic "
        "card. The number sits in that release’s Department of the Air Force "
        "component instructions (this app already saves those PDFs under "
        "solicitation_documents/).\n"
        "• Treat a Funding cell as a stated ceiling only when it says "
        "“stated.”\n"
        "• “Typical” means our FY fallback, not the instruction sheet.",
    ),
    (
        "CMMC and ITAR",
        "The CMMC line on a topic is a deliverable, not decoration. This "
        "catalog shows the stated level in the CMMC column.\n"
        "ITAR and export-control language, when present, is in the topic PDF.\n"
        "Do not confuse “CMMC Level 2” with TRL 2.",
    ),
    (
        "Cadence",
        "DoW open-topic releases often land on a monthly cycle. A missed "
        "close is not the end of that technology area — watch the next "
        "snapshot, not one topic ID.\n"
        "Use Component chips, Has Q&A, and due-in columns to plan the week.",
    ),
    (
        "FY27 monthly calendar (snapshot, not a scrape)",
        "Dated snapshot of the published FY 2027 monthly release calendar "
        "(updated 28 Sep 2026 on the Navy SBIR solicitations page). Confirm "
        "every deadline on DSIP before you staff a bid. This app never "
        "scrapes navysbir.com.\n"
        "\n"
        "              Pre-release     Opens          Closes\n"
        "Release 1     7 Oct 2026      28 Oct 2026    25 Nov 2026\n"
        "Release 2     4 Nov 2026      2 Dec 2026     6 Jan 2027\n"
        "Release 3     2 Dec 2026      6 Jan 2027     3 Feb 2027\n"
        "Release 4     6 Jan 2027      27 Jan 2027    24 Feb 2027\n"
        "Release 5     3 Feb 2027      24 Feb 2027    24 Mar 2027\n"
        "Release 6     3 Mar 2027      24 Mar 2027    21 Apr 2027\n"
        "Release 7     7 Apr 2027      28 Apr 2027    26 May 2027\n"
        "Release 8     5 May 2027      26 May 2027    23 Jun 2027\n"
        "Release 9     2 Jun 2027      23 Jun 2027    21 Jul 2027\n"
        "Release 10    7 Jul 2027      28 Jul 2027    25 Aug 2027\n"
        "Release 11    4 Aug 2027      25 Aug 2027    22 Sep 2027\n"
        "Release 12    1 Sep 2027      22 Sep 2027    20 Oct 2027\n"
        "\n"
        "Typical pattern: pre-release on the first Wednesday, open about "
        "three weeks later, close about four weeks after open at "
        "12:00 p.m. ET. Not every component is in every release.",
    ),
    (
        "How to use this app in that process",
        "1. Download or reopen a snapshot.\n"
        "2. Narrow to DAF (or another component) and sort Open, soonest due.\n"
        "3. Read published Q&A and the component-instruction PDF before you "
        "quote funding.\n"
        "4. Mark Pursue / Watch / Pass and Copy brief into your capture note.\n"
        "5. Submit only in DSIP, never from this tool.",
    ),
)


def section_titles() -> tuple[str, ...]:
    return tuple(title for title, _body in SECTIONS)


def guide_plain_text() -> str:
    """Full briefing as plain text (tests and the Text widget)."""
    blocks = [
        "How the SBIR / STTR program works",
        "",
        "Local notes for a BD or capture analyst. Official rules win if they "
        "disagree with anything here.",
        "",
    ]
    for title, body in SECTIONS:
        blocks.append(title)
        blocks.append(body)
        blocks.append("")
    blocks.append("Links (opens in your browser)")
    for label, url in LINKS:
        blocks.append(f"• {label}")
        blocks.append(f"  {url}")
    return "\n".join(blocks).strip() + "\n"
