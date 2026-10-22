#!/usr/bin/env python3
"""Download every topic in the public DoD DSIP open-topics catalog.

The DSIP topics app loads that catalog from a paginated JSON search. This
script follows the same search, reads the reported total, and saves one topic
PDF per record plus the shared solicitation PDFs attached to those records.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

REPO_ROOT = Path(__file__).resolve().parent
SEARCH_URL = "https://www.dodsbirsttr.mil/topics/api/public/topics/search"
TOPIC_PDF_URL = (
    "https://www.dodsbirsttr.mil/topics/api/public/topics/{topic_id}/download/PDF"
)
UPLOAD_PDF_URL = (
    "https://www.dodsbirsttr.mil/submissions/api/public/download?uploadId={upload_id}"
)

# Same filter the notebook captured from the DSIP topics app: the open-topics
# view, which includes pre-release and open solicitations (status ids 591, 592).
SEARCH_PARAM = {
    "searchText": None,
    "components": None,
    "programYear": None,
    "solicitationCycleNames": ["openTopics"],
    "releaseNumbers": [],
    "topicReleaseStatus": [591, 592],
    "modernizationPriorities": [],
    "sortBy": "finalTopicCode,asc",
    "technologyAreaIds": [],
    "component": None,
    "program": None,
}

PAGE_SIZE = 100
MAX_PAGES = 1000
REQUEST_PAUSE_SECONDS = 0.2
RETRYABLE_STATUS = {429, 500, 502, 503, 504}
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "*/*",
}
INVALID_FILENAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Download every open DoD DSIP topic PDF. "
            "Page size is not a cap: the script keeps requesting pages until "
            "the API total is collected."
        )
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help=(
            "Directory for the PDFs and manifest.json. "
            "Default: a new all_dsip_opportunities_YYYYMMDD_HHMMSS folder "
            "in the repository root."
        ),
    )
    return parser.parse_args(argv)


def default_output_dir() -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    candidate = REPO_ROOT / f"all_dsip_opportunities_{stamp}"
    if not candidate.exists():
        return candidate
    for suffix in range(2, 1000):
        alternate = REPO_ROOT / f"all_dsip_opportunities_{stamp}_{suffix}"
        if not alternate.exists():
            return alternate
    raise RuntimeError("Could not allocate a timestamped output directory.")


def safe_filename(name: str, max_len: int = 140) -> str:
    cleaned = INVALID_FILENAME.sub("_", name)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    if len(cleaned) > max_len:
        cleaned = cleaned[:max_len].rstrip(" .")
    return cleaned or "document"


def topic_pdf_name(topic: dict) -> str:
    code = safe_filename(str(topic.get("topicCode") or "topic"), max_len=80)
    title = safe_filename(str(topic.get("topicTitle") or "untitled"), max_len=100)
    return f"topic_{code}_{title}.pdf"


def epoch_ms_to_iso(value: object) -> str | None:
    if not isinstance(value, (int, float)):
        return None
    return datetime.fromtimestamp(value / 1000, tz=timezone.utc).isoformat()


def open_url(url: str, timeout: int) -> object:
    last_error: Exception | None = None
    for attempt in range(1, 4):
        try:
            request = urllib.request.Request(url, headers=HEADERS)
            return urllib.request.urlopen(request, timeout=timeout)
        except urllib.error.HTTPError as exc:
            detail = exc.read(300)
            exc.close()
            last_error = RuntimeError(
                f"HTTP {exc.code} for {url}: {detail[:240]!r}"
            )
            if exc.code not in RETRYABLE_STATUS or attempt == 3:
                raise last_error from exc
        except urllib.error.URLError as exc:
            last_error = exc
            if attempt == 3:
                raise
        time.sleep(attempt)
    raise RuntimeError(f"Request failed for {url}") from last_error


def fetch_json(url: str) -> dict:
    with open_url(url, timeout=60) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"Expected a JSON object from {url}")
    return payload


def search_page(page: int) -> dict:
    query = urlencode(
        {
            "searchParam": json.dumps(SEARCH_PARAM, separators=(",", ":")),
            "size": PAGE_SIZE,
            "page": page,
        }
    )
    return fetch_json(f"{SEARCH_URL}?{query}")


def fetch_all_topics() -> tuple[list[dict], int]:
    """Return every open-topic record and the total reported by the API."""
    topics: list[dict] = []
    seen: set[str] = set()
    total: int | None = None

    for page in range(MAX_PAGES):
        payload = search_page(page)
        if total is None:
            reported = payload.get("total", 0)
            total = int(reported) if isinstance(reported, int) else 0
            print(f"DSIP open-topics catalog reports {total} topic(s).")
        items = payload.get("data") or []
        if not isinstance(items, list):
            raise RuntimeError("Search response did not include a data list.")

        fresh = []
        for item in items:
            topic_id = str(item.get("topicId") or "")
            if not topic_id or topic_id in seen:
                continue
            seen.add(topic_id)
            fresh.append(item)
        topics.extend(fresh)
        print(
            f"Page {page}: received {len(items)} record(s), "
            f"{len(topics)} of {total} collected."
        )

        if total == 0 or len(topics) >= total or not items or not fresh:
            break
        time.sleep(REQUEST_PAUSE_SECONDS)
    else:
        raise RuntimeError(
            f"Stopped after {MAX_PAGES} pages with {len(topics)} of {total} topics."
        )

    if total is None:
        total = len(topics)
    return topics, total


def is_valid_pdf(path: Path) -> bool:
    if not path.is_file() or path.stat().st_size < 5:
        return False
    with path.open("rb") as handle:
        return handle.read(5) == b"%PDF-"


def download_pdf(url: str, dest: Path) -> str:
    """Save url to dest. Return 'skipped' or 'downloaded'."""
    if is_valid_pdf(dest):
        return "skipped"

    dest.parent.mkdir(parents=True, exist_ok=True)
    partial = dest.with_name(dest.name + ".part")
    try:
        with open_url(url, timeout=180) as response:
            header = response.read(5)
            if header != b"%PDF-":
                extra = response.read(240)
                preview = (header + extra)[:240]
                raise RuntimeError(f"Expected a PDF from {url}, received {preview!r}")
            with partial.open("wb") as handle:
                handle.write(header)
                while True:
                    chunk = response.read(64 * 1024)
                    if not chunk:
                        break
                    handle.write(chunk)
        os.replace(partial, dest)
    except Exception:
        if partial.exists():
            partial.unlink()
        raise

    if not is_valid_pdf(dest):
        raise RuntimeError(f"Saved file is not a PDF: {dest}")
    return "downloaded"


def solicitation_documents(topic: dict) -> list[dict]:
    documents = []
    preface_id = topic.get("baaPrefaceUploadId")
    preface_name = topic.get("baaPrefaceUploadTitle")
    if preface_id and preface_name:
        documents.append(
            {
                "upload_id": preface_id,
                "file_name": str(preface_name),
                "kind": "preface",
            }
        )
    for instruction in topic.get("baaInstructions") or []:
        upload_id = instruction.get("uploadId")
        file_name = instruction.get("fileName")
        if upload_id and file_name:
            documents.append(
                {
                    "upload_id": upload_id,
                    "file_name": str(file_name),
                    "kind": "instructions",
                }
            )
    return documents


def assign_topic_names(topics: list[dict]) -> dict[str, str]:
    claimed: set[str] = set()
    names: dict[str, str] = {}
    for topic in topics:
        topic_id = str(topic["topicId"])
        base = topic_pdf_name(topic)
        filename = base
        if filename.lower() in claimed:
            suffix = safe_filename(topic_id[-12:], max_len=12)
            filename = f"{Path(base).stem}_{suffix}.pdf"
            copy = 2
            while filename.lower() in claimed:
                filename = f"{Path(base).stem}_{suffix}_{copy}.pdf"
                copy += 1
        claimed.add(filename.lower())
        names[topic_id] = filename
    return names


def download_solicitation_files(
    topics: list[dict], output_dir: Path
) -> tuple[dict[object, dict], list[dict]]:
    directory = output_dir / "solicitation_documents"
    saved: dict[object, dict] = {}
    failures: list[dict] = []
    unique: dict[object, dict] = {}
    for topic in topics:
        for document in solicitation_documents(topic):
            unique.setdefault(document["upload_id"], document)

    print(f"Shared solicitation PDFs to fetch: {len(unique)}.")
    used_names: set[str] = set()
    for index, document in enumerate(unique.values(), start=1):
        upload_id = document["upload_id"]
        filename = safe_filename(document["file_name"], max_len=160)
        if not filename.lower().endswith(".pdf"):
            filename = f"{filename}.pdf"
        if filename.lower() in used_names:
            filename = f"{Path(filename).stem}_{upload_id}.pdf"
        used_names.add(filename.lower())
        dest = directory / filename
        url = UPLOAD_PDF_URL.format(upload_id=upload_id)
        print(f"  [{index}/{len(unique)}] {filename}")
        try:
            status = download_pdf(url, dest)
        except Exception as exc:
            print(f"    failed: {exc}")
            failures.append(
                {
                    "kind": "solicitation_document",
                    "upload_id": upload_id,
                    "file_name": filename,
                    "error": str(exc),
                }
            )
            continue
        print(f"    {status}: {dest.relative_to(output_dir)}")
        saved[upload_id] = {
            "upload_id": upload_id,
            "kind": document["kind"],
            "path": str(dest.relative_to(output_dir)).replace("\\", "/"),
            "status": status,
        }
        time.sleep(REQUEST_PAUSE_SECONDS)
    return saved, failures


def write_manifest(path: Path, payload: dict) -> None:
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def run(output_dir: Path) -> int:
    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"Output directory: {output_dir}")

    topics, total = fetch_all_topics()
    names = assign_topic_names(topics)
    solicitation_saved, failures = download_solicitation_files(topics, output_dir)

    topic_rows = []
    downloaded = 0
    skipped = 0
    print(f"Topic PDFs to fetch: {len(topics)}.")
    for index, topic in enumerate(topics, start=1):
        topic_id = str(topic["topicId"])
        filename = names[topic_id]
        dest = output_dir / filename
        code = topic.get("topicCode") or topic_id
        title = topic.get("topicTitle") or ""
        print(f"[{index}/{len(topics)}] {code}  {title}")
        status = "failed"
        error = None
        try:
            if not re.fullmatch(r"[A-Za-z0-9_-]+", topic_id):
                raise RuntimeError(f"Unexpected topic id: {topic_id}")
            status = download_pdf(TOPIC_PDF_URL.format(topic_id=topic_id), dest)
        except Exception as exc:
            error = str(exc)
            print(f"  failed: {exc}")
            failures.append(
                {
                    "kind": "topic_pdf",
                    "topic_id": topic_id,
                    "topic_code": code,
                    "error": error,
                }
            )
        else:
            print(f"  {status}: {filename}")
            if status == "downloaded":
                downloaded += 1
            else:
                skipped += 1
            time.sleep(REQUEST_PAUSE_SECONDS)

        attached = []
        for document in solicitation_documents(topic):
            saved = solicitation_saved.get(document["upload_id"])
            if saved:
                attached.append(saved["path"])

        topic_rows.append(
            {
                "topicId": topic_id,
                "topicCode": topic.get("topicCode"),
                "topicTitle": topic.get("topicTitle"),
                "topicStatus": topic.get("topicStatus"),
                "component": topic.get("component"),
                "command": topic.get("command"),
                "program": topic.get("program"),
                "solicitationNumber": topic.get("solicitationNumber"),
                "solicitationTitle": topic.get("solicitationTitle"),
                "cycleName": topic.get("cycleName"),
                "releaseNumber": topic.get("releaseNumber"),
                "topicStartDate": epoch_ms_to_iso(topic.get("topicStartDate")),
                "topicEndDate": epoch_ms_to_iso(topic.get("topicEndDate")),
                "topicPreReleaseStartDate": epoch_ms_to_iso(
                    topic.get("topicPreReleaseStartDate")
                ),
                "topicPreReleaseEndDate": epoch_ms_to_iso(
                    topic.get("topicPreReleaseEndDate")
                ),
                "pdf": None if error else filename,
                "pdfStatus": status,
                "pdfError": error,
                "solicitationDocuments": attached,
            }
        )

    shortfall = max(total - len(topics), 0)
    if shortfall:
        failures.append(
            {
                "kind": "catalog",
                "error": (
                    f"API reported {total} topics and the download collected "
                    f"{len(topics)}."
                ),
            }
        )

    manifest = {
        "createdAt": datetime.now().astimezone().isoformat(timespec="seconds"),
        "outputDir": str(output_dir),
        "source": SEARCH_URL,
        "searchParam": SEARCH_PARAM,
        "pageSize": PAGE_SIZE,
        "apiTotal": total,
        "topicsRetrieved": len(topics),
        "topicPdfsDownloaded": downloaded,
        "topicPdfsSkipped": skipped,
        "topicPdfFailures": sum(1 for row in topic_rows if row["pdfStatus"] == "failed"),
        "solicitationDocuments": list(solicitation_saved.values()),
        "failures": failures,
        "topics": topic_rows,
    }
    manifest_path = output_dir / "manifest.json"
    write_manifest(manifest_path, manifest)

    print("")
    print(f"API total: {total}")
    print(f"Topics retrieved: {len(topics)}")
    print(f"Topic PDFs downloaded: {downloaded}")
    print(f"Topic PDFs already present: {skipped}")
    print(f"Solicitation PDFs saved: {len(solicitation_saved)}")
    print(f"Failures: {len(failures)}")
    print(f"Manifest: {manifest_path}")

    if failures:
        print("Completed with failures. See manifest.json.")
        return 1
    print("Finished. Every reported topic was retrieved.")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    output_dir = (
        args.output.expanduser().resolve()
        if args.output is not None
        else default_output_dir()
    )
    try:
        return run(output_dir)
    except KeyboardInterrupt:
        print("\nInterrupted.")
        return 130
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
