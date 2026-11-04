import sbir_guide


def test_guide_covers_process_without_copying_consultant_marketing():
    text = sbir_guide.guide_plain_text()
    assert "Direct to Phase II" in text
    assert "13 CFR 121.702" in text
    assert "SAM.gov" in text
    assert "Topic Q&A" in text
    assert "CMMC" in text
    assert "solicitation_documents" in text
    assert "Get my free funding report" not in text
    assert "kevin@" not in text
    assert "WhatsApp" not in text
    assert "never scrapes navysbir.com" in text
    assert "FY 2027" in text
    assert "Release 2" in text


def test_guide_section_titles_cover_the_process():
    titles = sbir_guide.section_titles()
    assert "Who can propose" in titles
    assert "Direct to Phase II vs Phase I" in titles
    assert "FY27 monthly calendar (snapshot, not a scrape)" in titles
    assert titles[0] == "What this tab is"


def test_guide_lists_official_links_before_third_party():
    urls = [url for _label, url in sbir_guide.LINKS]
    assert urls[0].startswith("https://www.dodsbirsttr.mil/")
    assert any("sbir.gov" in url for url in urls)
    assert urls[-1] == "https://investech-consulting.com/programs/afwerx-sbir/"
    assert "https://www.navysbir.com/solicitations.htm" in urls
    assert urls.index("https://www.navysbir.com/solicitations.htm") < len(urls) - 1
    assert all(url.startswith("https://") for url in urls)
