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


def test_guide_lists_official_links_before_third_party():
    urls = [url for _label, url in sbir_guide.LINKS]
    assert urls[0].startswith("https://www.dodsbirsttr.mil/")
    assert any("sbir.gov" in url for url in urls)
    assert urls[-1] == "https://investech-consulting.com/programs/afwerx-sbir/"
    assert all(url.startswith("https://") for url in urls)
