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
        "Third-party AFWERX/open-topic explainer (unaffiliated)",
        "https://investech-consulting.com/programs/afwerx-sbir/",
    ),
)

SECTIONS: tuple[tuple[str, str], ...] = (
    (
        "What this tab is",
        "This is a local briefing for a capture lead, not a live feed and not "
        "legal advice. Use the Catalog tab to see what is actually on DSIP "
        "right now. Dollar figures in the table that say “typical” are FY "
        "ceilings we inferred, not a quote from that topic sheet.",
    ),
    (
        "Who can propose",
        "SBIR/STTR is limited to U.S. for-profit small businesses (generally "
        "500 employees or fewer, including affiliates) that are more than "
        "50% owned and controlled by U.S. citizens or permanent residents, "
        "with the work performed in the United States. The regulation is "
        "13 CFR 121.702; that rule has listed exceptions. Individual topics "
        "add DoW constraints: a CMMC level, possible ITAR, and — for Direct "
        "to Phase II — feasibility evidence that must not come from prior "
        "federally funded SBIR/STTR work.",
    ),
    (
        "Specific topic vs open topic",
        "A specific topic states the technical need. You either already do "
        "that work or you can get there in Phase I. An open topic (titles "
        "often include OPEN) lets you bring your own dual-use solution, but "
        "you still need a named Air Force or Space Force customer problem. "
        "There is no standing “Air Force SBIR window” outside published "
        "DSIP topics. Open topics can be Phase I, Direct to Phase II, or "
        "both — the topic text decides, not the program name.",
    ),
    (
        "AFWERX, SpaceWERX, and DSIP",
        "AFWERX and SpaceWERX are Department of the Air Force innovation "
        "front doors. The money still lands through DoW SBIR/STTR releases. "
        "Every proposal is filed in DSIP against a published topic under the "
        "BAA or CSO. After Phase I/II, AFWERX follow-on vehicles (TACFI, "
        "STRATFI) can pair government and private funds toward Phase III. "
        "Those vehicles are not a substitute for a matching topic.",
    ),
    (
        "Pre-release, open, and questions",
        "In pre-release, TPOC names are usually visible and some components "
        "allow direct questions. Once the topic is Open, questions go through "
        "DSIP Topic Q&A only. This app can download published answers; it "
        "cannot post a question (that needs a DSIP login). Draft the "
        "technical volume while Q&A is still moving — answers change the "
        "requirement.",
    ),
    (
        "Registrations and a real submission",
        "Before close you need an active DSIP account, SAM.gov registration, "
        "and an SBA Company Registry entry. The proposal volumes are uploaded "
        "in DSIP. A package left in “In Progress” or “Ready to Certify” at "
        "the deadline is not submitted. Certify before the last day. "
        "Components typically notify select/non-select within 90 days of "
        "the close.",
    ),
    (
        "Direct to Phase II vs Phase I",
        "If the topic is Direct to Phase II (D2P2), a Phase I proposal is "
        "rejected. Feasibility documentation cannot be prior federal "
        "SBIR/STTR work. In this catalog those topics often carry a -DV "
        "code or “Direct to Phase II” in the sheet. Use the D2P2 chip on "
        "the Catalog tab to list them.",
    ),
    (
        "Where the dollar figure lives",
        "Many Air Force topics do not print an award ceiling on the topic "
        "card. The number sits in that release’s Department of the Air Force "
        "component instructions (this app already saves those PDFs under "
        "solicitation_documents/). Only treat a table Funding cell as a "
        "stated ceiling when it says “stated.” “Typical” means our FY "
        "fallback, not the instruction sheet.",
    ),
    (
        "CMMC and ITAR",
        "The CMMC line on a topic is a deliverable, not decoration. This "
        "catalog now shows the stated level in the CMMC column. ITAR and "
        "export-control language, when present, is in the topic PDF. Do not "
        "confuse “CMMC Level 2” with TRL 2.",
    ),
    (
        "Cadence",
        "DoW open-topic releases often land on a monthly cycle. A missed "
        "close is not the end of that technology area — watch the next "
        "snapshot, not one topic ID. Use Component chips, Has Q&A, and "
        "due-in columns to plan the week.",
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
