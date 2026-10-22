#!/usr/bin/env python3
"""Download every topic in the public DoD DSIP open-topics catalog.

The DSIP topics app loads that catalog from a paginated JSON search. This
script follows the same search, reads the reported total, and saves one topic
PDF per record plus the shared solicitation PDFs attached to those records.

Downloads are network and disk bound, so they run on a thread pool. Threads
(not processes) are used because the work is I/O bound: Python releases the GIL
during socket and file I/O, and threads avoid the pickling and start-up cost of
processes while sharing one HTTP connection pool per worker.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
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
DOWNLOAD_ATTEMPTS = 3
RETRYABLE_STATUS = {429, 500, 502, 503, 504}
TOPIC_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]+")
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "*/*",
}
INVALID_FILENAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

_print_lock = threading.Lock()


def default_workers() -> int:
    """Pick a thread count that saturates the download without flooding the host.

    Downloads are I/O bound, so more threads than CPUs helps. The count scales
    with the machine and is capped so a large box does not open an unreasonable
    number of simultaneous connections to one government server.
    """
    cpus = os.cpu_count() or 4
    return max(4, min(64, cpus * 5))


def log(message: str) -> None:
    with _print_lock:
        print(message, flush=True)


def format_clock(seconds: float) -> str:
    """Render seconds as mm:ss, or h:mm:ss past an hour (for the progress bar)."""
    total = int(max(0, seconds))
    minutes, secs = divmod(total, 60)
    if minutes < 60:
        return f"{minutes:02d}:{secs:02d}"
    hours, minutes = divmod(minutes, 60)
    return f"{hours:d}:{minutes:02d}:{secs:02d}"


def format_duration(seconds: float) -> str:
    """Human-readable elapsed time for the end-of-run summary."""
    seconds = max(0.0, float(seconds))
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes, secs = divmod(seconds, 60)
    if minutes < 60:
        return f"{int(minutes)}m {secs:04.1f}s"
    hours, minutes = divmod(int(minutes), 60)
    return f"{hours}h {minutes:02d}m {secs:04.1f}s"


class ProgressBar:
    """A small tqdm-style progress bar with no third-party dependency.

    Uses ASCII glyphs so it cannot raise UnicodeEncodeError on a non-UTF-8
    Windows console. On a TTY it redraws one line in place; when stdout is
    redirected (a file or CI) it prints one compact line per completion so the
    log stays readable.
    """

    def __init__(self, total: int, label: str, width: int = 28) -> None:
        self.total = total
        self.label = label
        self.width = width
        self.count = 0
        self.start = time.monotonic()
        self.stream = sys.stdout
        self.is_tty = hasattr(self.stream, "isatty") and self.stream.isatty()
        self._last_len = 0
        self._lock = threading.Lock()

    def _render(self) -> str:
        elapsed = time.monotonic() - self.start
        fraction = self.count / self.total if self.total else 1.0
        filled = int(self.width * fraction)
        bar = "#" * filled + "-" * (self.width - filled)
        rate = self.count / elapsed if elapsed > 0 else 0.0
        eta = (self.total - self.count) / rate if rate > 0 else 0.0
        return (
            f"{self.label} {int(fraction * 100):3d}%|{bar}| "
            f"{self.count}/{self.total} "
            f"[{format_clock(elapsed)}<{format_clock(eta)}, {rate:4.1f} file/s]"
        )

    def _draw(self) -> None:
        line = self._render()
        if self.is_tty:
            padding = " " * max(0, self._last_len - len(line))
            self.stream.write("\r" + line + padding)
            self._last_len = len(line)
        else:
            self.stream.write(line + "\n")
        self.stream.flush()

    def update(self, amount: int = 1) -> None:
        with self._lock:
            self.count += amount
            self._draw()

    def write(self, message: str) -> None:
        """Print a message (such as a failure) without corrupting the bar."""
        with self._lock:
            if self.is_tty and self._last_len:
                self.stream.write("\r" + " " * self._last_len + "\r")
                self._last_len = 0
            self.stream.write(message + "\n")
            self.stream.flush()
            if self.is_tty:
                self._draw()

    def close(self) -> None:
        with self._lock:
            if self.is_tty and self._last_len:
                self.stream.write("\n")
                self.stream.flush()
                self._last_len = 0


class ConsoleReporter:
    """Default progress sink: status lines + a terminal ProgressBar per phase.

    The downloader reports progress through a reporter object instead of
    printing directly, so a GUI (or any other front end) can receive the same
    events. This console implementation preserves the original CLI output.
    """

    def __init__(self) -> None:
        self._bar: ProgressBar | None = None

    def status(self, message: str) -> None:
        log(message)

    def start_phase(self, label: str, total: int) -> None:
        self._bar = ProgressBar(total, label)

    def advance(self, done: int, total: int, failure: str | None = None) -> None:
        if self._bar is None:
            return
        if failure:
            self._bar.write(failure)
        self._bar.update(1)

    def end_phase(self) -> None:
        if self._bar is not None:
            self._bar.close()
            self._bar = None


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
    parser.add_argument(
        "-j",
        "--workers",
        type=int,
        default=default_workers(),
        help=(
            "Number of concurrent download threads. "
            f"Default scales with this machine: {default_workers()}."
        ),
    )
    return parser.parse_args(argv)


def timestamped_dir(parent: Path) -> Path:
    """Return a new all_dsip_opportunities_YYYYMMDD_HHMMSS folder under parent.

    Used by the CLI (default in the repo root) and the GUI (inside whatever
    folder the user picks), so both place their output the same way.
    """
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    candidate = parent / f"all_dsip_opportunities_{stamp}"
    if not candidate.exists():
        return candidate
    for suffix in range(2, 1000):
        alternate = parent / f"all_dsip_opportunities_{stamp}_{suffix}"
        if not alternate.exists():
            return alternate
    raise RuntimeError("Could not allocate a timestamped output directory.")


def default_output_dir() -> Path:
    return timestamped_dir(REPO_ROOT)


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


def relpath(path: Path, base: Path) -> str:
    return str(path.relative_to(base)).replace("\\", "/")


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


def fetch_all_topics(reporter: "ConsoleReporter | None" = None) -> tuple[list[dict], int]:
    """Return every open-topic record and the total reported by the API.

    Pagination has to be sequential because each page depends on the previous
    page number, but this is fast: it is one small JSON request per 100 topics.
    """
    reporter = reporter or ConsoleReporter()
    topics: list[dict] = []
    seen: set[str] = set()
    total: int | None = None

    for page in range(MAX_PAGES):
        payload = search_page(page)
        if total is None:
            reported = payload.get("total", 0)
            total = int(reported) if isinstance(reported, int) else 0
            reporter.status(f"DSIP open-topics catalog reports {total} topic(s).")
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
        reporter.status(
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


def _read_exactly(response: object, count: int) -> bytes:
    """Read exactly count bytes unless the stream ends first.

    A single response.read(n) can legally return fewer than n bytes, so the
    PDF magic-number check must not assume the first read fills the buffer.
    """
    chunks: list[bytes] = []
    remaining = count
    while remaining > 0:
        chunk = response.read(remaining)
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _attempt_download(url: str, partial: Path) -> None:
    """Stream one response to the partial file or raise if it is not a PDF.

    Under heavy concurrency the DSIP server sometimes answers a valid request
    with an empty or non-PDF body, so the caller retries this on failure.
    """
    with open_url(url, timeout=180) as response:
        header = _read_exactly(response, 5)
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


def download_pdf(url: str, dest: Path) -> str:
    """Save url to dest. Return 'skipped' or 'downloaded'.

    Retries transient empty/non-PDF responses, which the HTTP-status retry in
    open_url cannot catch because they arrive as a successful 200.
    """
    if is_valid_pdf(dest):
        return "skipped"

    dest.parent.mkdir(parents=True, exist_ok=True)
    # Make the temp name unique per thread so concurrent downloads of distinct
    # destinations never collide on a shared .part file.
    partial = dest.with_name(f"{dest.name}.{threading.get_ident()}.part")
    last_error: Exception | None = None
    for attempt in range(1, DOWNLOAD_ATTEMPTS + 1):
        try:
            _attempt_download(url, partial)
            os.replace(partial, dest)
            if not is_valid_pdf(dest):
                raise RuntimeError(f"Saved file is not a PDF: {dest}")
            return "downloaded"
        except Exception as exc:  # noqa: BLE001 - retried below, re-raised if final
            last_error = exc
            if partial.exists():
                partial.unlink()
            if attempt < DOWNLOAD_ATTEMPTS:
                time.sleep(attempt)
        except BaseException:
            if partial.exists():
                partial.unlink()
            raise
    raise last_error if last_error else RuntimeError(f"Failed to download {url}")


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
    """Pick one unique PDF filename per topic, resolved before any threads run."""
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


@dataclass
class DownloadTask:
    key: object
    url: str
    dest: Path
    describe: str


def plan_solicitation_tasks(
    topics: list[dict], output_dir: Path
) -> tuple[list[DownloadTask], dict[object, dict]]:
    """Build one download task per distinct solicitation upload.

    Filenames are assigned here, single-threaded, so concurrent workers never
    race to claim the same name.
    """
    directory = output_dir / "solicitation_documents"
    unique: dict[object, dict] = {}
    for topic in topics:
        for document in solicitation_documents(topic):
            unique.setdefault(document["upload_id"], document)

    tasks: list[DownloadTask] = []
    meta: dict[object, dict] = {}
    used_names: set[str] = set()
    for upload_id, document in unique.items():
        filename = safe_filename(document["file_name"], max_len=160)
        if not filename.lower().endswith(".pdf"):
            filename = f"{filename}.pdf"
        if filename.lower() in used_names:
            filename = f"{Path(filename).stem}_{upload_id}.pdf"
        used_names.add(filename.lower())
        dest = directory / filename
        tasks.append(
            DownloadTask(
                key=upload_id,
                url=UPLOAD_PDF_URL.format(upload_id=upload_id),
                dest=dest,
                describe=filename,
            )
        )
        meta[upload_id] = {
            "upload_id": upload_id,
            "kind": document["kind"],
            "path": relpath(dest, output_dir),
        }
    return tasks, meta


def plan_topic_tasks(
    topics: list[dict], names: dict[str, str], output_dir: Path
) -> tuple[list[DownloadTask], dict[object, dict]]:
    tasks: list[DownloadTask] = []
    preset: dict[object, dict] = {}
    for topic in topics:
        topic_id = str(topic["topicId"])
        describe = str(topic.get("topicCode") or topic_id)
        if not TOPIC_ID_PATTERN.fullmatch(topic_id):
            preset[topic_id] = {
                "status": "failed",
                "error": f"Unexpected topic id: {topic_id}",
            }
            continue
        tasks.append(
            DownloadTask(
                key=topic_id,
                url=TOPIC_PDF_URL.format(topic_id=topic_id),
                dest=output_dir / names[topic_id],
                describe=describe,
            )
        )
    return tasks, preset


def download_tasks(
    tasks: list[DownloadTask],
    workers: int,
    label: str,
    reporter: "ConsoleReporter | None" = None,
) -> dict[object, dict]:
    """Download every task concurrently and return {key: {status, error}}.

    Progress is reported through the reporter, which drives the terminal bar on
    the CLI or the progress bar in the GUI. Failures are reported per item so
    none are lost.
    """
    reporter = reporter or ConsoleReporter()
    results: dict[object, dict] = {}
    total = len(tasks)
    if total == 0:
        return results

    def work(task: DownloadTask) -> tuple[object, str, dict]:
        try:
            status = download_pdf(task.url, task.dest)
            return task.key, task.describe, {"status": status, "error": None}
        except Exception as exc:  # noqa: BLE001 - recorded per task, never fatal
            return task.key, task.describe, {"status": "failed", "error": str(exc)}

    reporter.start_phase(label, total)
    worker_count = max(1, min(workers, total))
    done = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = [executor.submit(work, task) for task in tasks]
        for future in concurrent.futures.as_completed(futures):
            key, describe, outcome = future.result()
            results[key] = outcome
            done += 1
            failure = None
            if outcome["error"]:
                failure = f"{label} FAILED: {describe} -> {outcome['error']}"
            reporter.advance(done, total, failure)
    reporter.end_phase()
    return results


def write_manifest(path: Path, payload: dict) -> None:
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def run(
    output_dir: Path,
    workers: int | None = None,
    reporter: "ConsoleReporter | None" = None,
) -> int:
    reporter = reporter or ConsoleReporter()
    if workers is None:
        workers = default_workers()
    workers = max(1, workers)
    run_start = time.monotonic()
    output_dir.mkdir(parents=True, exist_ok=True)
    reporter.status(f"Output directory: {output_dir}")
    reporter.status(f"Download workers: {workers}")

    topics, total = fetch_all_topics(reporter)
    names = assign_topic_names(topics)

    download_start = time.monotonic()
    solicitation_tasks, solicitation_meta = plan_solicitation_tasks(topics, output_dir)
    reporter.status(f"Shared solicitation PDFs to fetch: {len(solicitation_tasks)}.")
    solicitation_results = download_tasks(
        solicitation_tasks, workers, "solicitation PDF", reporter
    )

    solicitation_saved: dict[object, dict] = {}
    failures: list[dict] = []
    for upload_id, meta in solicitation_meta.items():
        outcome = solicitation_results.get(upload_id, {})
        if outcome.get("error"):
            failures.append(
                {
                    "kind": "solicitation_document",
                    "upload_id": upload_id,
                    "file_name": Path(meta["path"]).name,
                    "error": outcome["error"],
                }
            )
            continue
        solicitation_saved[upload_id] = {
            "upload_id": upload_id,
            "kind": meta["kind"],
            "path": meta["path"],
            "status": outcome.get("status", "failed"),
        }

    topic_tasks, topic_results = plan_topic_tasks(topics, names, output_dir)
    reporter.status(f"Topic PDFs to fetch: {len(topics)}.")
    topic_results.update(download_tasks(topic_tasks, workers, "topic PDF", reporter))
    download_seconds = time.monotonic() - download_start

    topic_rows = []
    downloaded = 0
    skipped = 0
    for topic in topics:
        topic_id = str(topic["topicId"])
        outcome = topic_results.get(topic_id, {"status": "failed", "error": "No result"})
        status = outcome.get("status", "failed")
        error = outcome.get("error")
        if error:
            failures.append(
                {
                    "kind": "topic_pdf",
                    "topic_id": topic_id,
                    "topic_code": topic.get("topicCode") or topic_id,
                    "error": error,
                }
            )
        elif status == "downloaded":
            downloaded += 1
        else:
            skipped += 1

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
                "pdf": None if error else names[topic_id],
                "pdfStatus": status,
                "pdfError": error,
                "solicitationDocuments": attached,
            }
        )

    if total - len(topics) > 0:
        failures.append(
            {
                "kind": "catalog",
                "error": (
                    f"API reported {total} topics and the download collected "
                    f"{len(topics)}."
                ),
            }
        )

    total_seconds = time.monotonic() - run_start
    manifest = {
        "createdAt": datetime.now().astimezone().isoformat(timespec="seconds"),
        "outputDir": str(output_dir),
        "source": SEARCH_URL,
        "searchParam": SEARCH_PARAM,
        "pageSize": PAGE_SIZE,
        "workers": workers,
        "downloadSeconds": round(download_seconds, 2),
        "totalSeconds": round(total_seconds, 2),
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

    reporter.status("")
    reporter.status(f"API total: {total}")
    reporter.status(f"Topics retrieved: {len(topics)}")
    reporter.status(f"Topic PDFs downloaded: {downloaded}")
    reporter.status(f"Topic PDFs already present: {skipped}")
    reporter.status(f"Solicitation PDFs saved: {len(solicitation_saved)}")
    reporter.status(f"Failures: {len(failures)}")
    reporter.status(f"Download time: {format_duration(download_seconds)}")
    reporter.status(f"Total run time: {format_duration(total_seconds)}")
    reporter.status(f"Manifest: {manifest_path}")

    if failures:
        reporter.status("Completed with failures. See manifest.json.")
        return 1
    reporter.status("Finished. Every reported topic was retrieved.")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    output_dir = (
        args.output.expanduser().resolve()
        if args.output is not None
        else default_output_dir()
    )
    try:
        return run(output_dir, args.workers)
    except KeyboardInterrupt:
        print("\nInterrupted.")
        return 130
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
