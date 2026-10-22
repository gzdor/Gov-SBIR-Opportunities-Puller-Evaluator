# Gov SBIR Opportunities Puller

Downloads the current public [DoD SBIR/STTR DSIP topics catalog](https://www.dodsbirsttr.mil/topics-app/) to disk: one topic-detail PDF per topic, the shared solicitation PDFs attached to those topics, and a `manifest.json` that lists every record the API returned. Downloads run concurrently on a thread pool.

`main.py` is the script to run. It uses only the Python standard library. `DSIP_portal_ai_query_tool.ipynb` is the Colab notebook that found the DSIP search API and the download buttons; it is kept as the research log.

## Architecture

```mermaid
flowchart TB
    subgraph user[User]
        CLI["Command line<br/>python main.py [-o DIR] [-j N]"]
    end

    subgraph app["main.py (stdlib only)"]
        ARGS["parse_args<br/>default_output_dir / default_workers"]
        FETCH["fetch_all_topics<br/>sequential paging of 100"]
        PLAN["assign_topic_names<br/>plan_topic_tasks / plan_solicitation_tasks"]
        POOL["download_tasks<br/>ThreadPoolExecutor"]
        DL["download_pdf<br/>%PDF header check + atomic replace"]
        MAN["write_manifest"]
    end

    subgraph dsip["DoD DSIP public endpoints"]
        SEARCH["topics search JSON"]
        TPDF["topic PDF route"]
        UPLOAD["solicitation upload route"]
    end

    subgraph fs["Output directory"]
        PDFS["topic + solicitation PDFs"]
        MJSON["manifest.json"]
    end

    CLI --> ARGS --> FETCH
    FETCH <-->|HTTP GET| SEARCH
    FETCH --> PLAN --> POOL --> DL
    DL <-->|HTTP GET| TPDF
    DL <-->|HTTP GET| UPLOAD
    DL --> PDFS
    PLAN --> MAN
    POOL --> MAN
    MAN --> MJSON
```

## Data flow

```mermaid
flowchart LR
    A["DSIP search API"] -->|JSON pages of 100| B["topic records"]
    B --> C{"for each topic"}
    C --> D["topic PDF URL<br/>/topics/{id}/download/PDF"]
    C --> E["solicitation upload ids<br/>baaPrefaceUploadId + baaInstructions"]
    E -->|dedupe by uploadId| G["solicitation upload URL"]
    D -->|threaded GET| F["topic_*.pdf"]
    G -->|threaded GET| H["solicitation_documents/*.pdf"]
    B --> I["metadata rows"]
    F --> J["manifest.json"]
    H --> J
    I --> J
```

## User data flow

```mermaid
sequenceDiagram
    actor U as User
    participant M as main.py
    participant API as DSIP search API
    participant CDN as DSIP PDF routes
    participant FS as Output folder

    U->>M: python main.py [-o DIR] [-j N]
    M->>API: GET search?size=100&page=0
    API-->>M: total + first 100 topics
    loop until total collected
        M->>API: GET next page
        API-->>M: more topics
    end
    M->>M: assign unique filenames, build tasks
    par N download threads
        M->>CDN: GET topic / solicitation PDF
        CDN-->>M: PDF bytes
        M->>FS: write *.pdf (atomic replace)
    end
    M->>FS: write manifest.json
    M-->>U: summary + exit code (0 ok / 1 issues)
```

## Python version

Use **Python 3.14**. The conda environment for this repo is named `dsip-opportunities` and is Python 3.14. `main.py` imports only the standard library, so Python 3.10 or newer can run it; 3.14 is the version to install and the version the environment and tests were verified on.

## Install Miniconda

Skip this when `conda --version` already prints a version. This machine already has Miniconda at `%UserProfile%\miniconda3` (Windows) and `~/miniconda3` (WSL). The one-liners are for a computer that does not have it yet. Both were run with these flags into a temporary folder, checked with `conda --version`, and removed.

The install prefix cannot contain spaces. On Windows, `/D=` has to be the last argument.

Windows Command Prompt:

```bat
curl -fsSL -o "%TEMP%\Miniconda3-latest-Windows-x86_64.exe" https://repo.anaconda.com/miniconda/Miniconda3-latest-Windows-x86_64.exe && start /wait "" "%TEMP%\Miniconda3-latest-Windows-x86_64.exe" /InstallationType=JustMe /AddToPath=0 /RegisterPython=0 /S /D=%UserProfile%\miniconda3 && del "%TEMP%\Miniconda3-latest-Windows-x86_64.exe"
```

Bash:

```bash
curl -fsSL https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh -o /tmp/miniconda.sh && bash /tmp/miniconda.sh -b -p "$HOME/miniconda3" && rm /tmp/miniconda.sh
```

The Windows install does not put `conda` on `PATH`. Load it in the same Command Prompt with:

```bat
call "%UserProfile%\miniconda3\condabin\conda.bat"
```

In bash, load it and enter `base` with:

```bash
source "$HOME/miniconda3/etc/profile.d/conda.sh"
conda activate base
```

## Environment

A fresh Miniconda `base` is Python 3.14 already, but create a dedicated environment so this project is isolated. Windows and WSL each have their own Miniconda, so each one gets its own `dsip-opportunities` environment (both Python 3.14.8).

Windows Command Prompt, from the repository root:

```bat
cd /d C:\Users\zdorg\code_dev\Gov-SBIR-Opportunities-Puller-Evaluator
conda create -n dsip-opportunities python=3.14 -y
call "%UserProfile%\miniconda3\condabin\conda.bat" activate dsip-opportunities
python -c "import sys; print(sys.version)"
pip install -r requirements.txt
pytest
python main.py --help
```

WSL bash:

```bash
source "$HOME/miniconda3/etc/profile.d/conda.sh"
conda create -n dsip-opportunities python=3.14 -y
conda activate dsip-opportunities
python -c 'import sys; print(sys.version)'
cd /mnt/c/Users/zdorg/code_dev/Gov-SBIR-Opportunities-Puller-Evaluator
pip install -r requirements.txt
pytest
python main.py --help
```

Both sequences were run end to end. `pip install -r requirements.txt` installs the notebook packages plus pytest (`main.py` itself needs none of them). `pytest` runs the 20 tests in `test/test_main.py`. `python main.py --help` prints the downloader usage. `conda create` stops if the environment name already exists.

## Quick start

With `dsip-opportunities` active, from the repository root:

```bat
python main.py
```

That creates a new folder in this directory named `all_dsip_opportunities_YYYYMMDD_HHMMSS` (local time) and writes the PDFs there.

Choose the folder yourself:

```bat
python main.py --output D:\dsip_pulls\october
```

Set the number of download threads:

```bat
python main.py --workers 16
```

A relative `--output` path is resolved from the current working directory. The folder is created if it does not exist. Files that are already valid PDFs in that folder are left in place, so a second run into the same directory resumes.

## Concurrency and performance

Downloads are network and disk bound, not CPU bound, so `main.py` uses a **thread pool** (`concurrent.futures.ThreadPoolExecutor`), not processes. Python releases the GIL during socket and file I/O, so threads overlap transfers effectively, and they avoid the pickling and start-up cost of processes while reusing one HTTP connection pool per worker.

`--workers` sets the thread count. The default scales with the machine, `cpu_count * 5`, floored at 4 and capped at 64 so a large box does not open an unreasonable number of simultaneous connections to one government server. The pool is also capped at the number of files to fetch. Catalog paging stays sequential because each page request depends on the previous page number, but that is a handful of small JSON requests; the PDFs, which are the slow part, all download concurrently.

The run prints `[done/total]` progress as each file lands, so lines appear out of catalog order. `manifest.json` is always written in catalog order regardless of which thread finished first, and the chosen worker count is recorded in the manifest.

## Tests

```bat
call "%UserProfile%\miniconda3\condabin\conda.bat" activate dsip-opportunities
cd /d C:\Users\zdorg\code_dev\Gov-SBIR-Opportunities-Puller-Evaluator
pytest
```

The tests live in `test/test_main.py` (20 tests). They cover filename cleanup, timestamped output folders, paging past a short page and past a full page of 100, PDF header checks including PDFs delivered in tiny chunks, worker-count bounds, concurrent downloads with mixed success and failure, shared solicitation files, and a short catalog. Search and download calls are stubbed, so pytest does not contact DSIP.

## Will a run get every topic?

The numbers 10 and 100 in the notebook are page sizes. They are not a limit on how many topics to keep.

Checked against the live DSIP search API:

| Call | What came back |
| --- | --- |
| `size=10&page=0` | 10 records. The same call reports `total`. |
| `size=10&page=1` and `page=2` | The next 10, then the last 8. Page 3 is empty. |
| `size=100&page=0` | All 28 records in one response. `total` was 28. |

A page of 10 is the first screen of the table. A page of 100 is one API request that happened to hold the whole catalog that day. The catalog count changes as topics open and close, so the script does not assume 28, 10, or 100.

`main.py` requests pages of 100, reads `total`, and keeps going until every reported topic id is collected. A short page does not end the walk while `total` is still ahead. If the API reports 28 and only 20 ids come back, the process exits with status 1 and records the gap in `manifest.json`. After the catalog is collected it downloads a topic PDF for each id, concurrently.

"Every topic" means every topic in the DSIP **open topics** view: the search the notebook captured, `solicitationCycleNames: ["openTopics"]` and `topicReleaseStatus: [591, 592]`. That view includes pre-release and open solicitations. Closed and archived topics are a different search and are outside this download.

## What gets saved

```text
all_dsip_opportunities_20261021_214405/
  manifest.json
  topic_ARM26BX03-DP007_xTech_Kinetic Reach Competition.pdf
  topic_....pdf
  solicitation_documents/
    DoW 2026 SBIR CSO Preface_07152026.pdf
    ARMY_26BX_R3.pdf
```

- Topic PDFs are the file behind **Download Topic Details as: PDF** on each row. The DSIP app requests `GET /topics/api/public/topics/{topicId}/download/PDF`; a direct request returns a body that starts with `%PDF`. The filename follows the app's pattern, `topic_{topicCode}_{topicTitle}.pdf`, with characters Windows rejects (`\ / : * ? " < > |`) replaced. Titles longer than 100 characters are shortened in the filename; the full title stays in `manifest.json`. Filenames are assigned before any thread runs, so concurrent workers never race for the same name; a collision gets the topic id appended.
- `solicitation_documents/` holds each distinct BAA preface and component instruction PDF referenced by those topics (`baaPrefaceUploadId`, `baaInstructions[].uploadId`), fetched from `submissions/api/public/download?uploadId=`. Many topics share one preface, so each upload id is saved once.
- `manifest.json` lists the API total, the worker count, every topic (code, title, status, component, program, solicitation, cycle, release, dates), the local PDF name, and any failures.

`all_dsip_opportunities_*/` is listed in `.gitignore`. A custom `--output` folder inside the repo is not ignored automatically.

Exit status `0` means the retrieved topic count matches `total` and every PDF saved or was already valid. Exit status `1` means a request failed or the catalog came up short. Exit status `130` means the run was interrupted; whatever finished is already on disk, and running again with the same `--output` skips valid PDFs.

## Notebook map

`DSIP_portal_ai_query_tool.ipynb` was written in Google Colab and is kept as the record of how the API was found. Hard-coded `/content/...` paths have been removed: every output cell now writes under `OUTPUT_ROOT`, which defaults to a `notebook_outputs/` folder next to the notebook and can be overridden with the `DSIP_OUTPUT_ROOT` environment variable. That lets the notebook run unchanged on Colab or a local clone.

1. **Setup.** `pip install browser-use langchain-google-genai playwright nest_asyncio ipywidgets`, then `playwright install chromium` and `playwright install-deps`. Later cells also import `beautifulsoup4` and `requests`, which are in `requirements.txt`.
2. **Configure Credentials.** Prompts for `GOOGLE_API_KEY`. Only the chatbot cell uses it.
3. **DSIP PDF Downloader Chatbot.** A `browser-use` agent on `gemini-1.5-pro` with a small widget UI. The next markdown cell notes this agent hit structured-output problems, which is why the notebook switches to fixed Playwright scripts.
4. **Deterministic Playwright scraper.** Headless Chromium that expands each `mat-expansion-panel` and clicks PDF icons.
5. **Row / page-source / network inspection.** Helpers that dump rendered HTML and XHR URLs; this is how the search endpoint was found.
6. **Inspect API Data Structure.** One GET of the public search API, `size=10&page=0`; prints `total` and the keys on a topic record.
7. **Bulk API Downloader.** Paginates with `size=100` and downloads preface and instruction uploads through a browser cookie jar.
8. **Hybrid UI downloader** and **Run Full Site PDF Downloader.** Repeat the expansion-panel click loop; the stored output processed 10 rows and stopped.
9. **Git backup.** A Colab cell that commits and force-pushes with a GitHub token. Leave `GITHUB_TOKEN` empty; this repo is already a git clone.

No Google API key is required for `main.py`. The search and PDF routes it uses are the public ones the topics app calls when nobody is logged in.

## Design notes and limitations

- **Standard library only.** `main.py` has no third-party dependencies, so it runs in a bare Python 3.10+ interpreter. `requirements.txt` exists for the notebook and the tests.
- **Idempotent, resumable.** Each file is validated by its `%PDF` header and written to a per-thread `.part` file, then atomically moved into place. A re-run skips files that are already valid PDFs.
- **Open topics only.** The filter is the DSIP open-topics view. Changing to closed or historical topics means a different `searchParam`.
- **Public routes can change.** DSIP is a government app; endpoint paths or the search schema can change without notice. The search URL, the topic PDF route, and the upload route are defined as constants at the top of `main.py` so they are easy to update, and every download is header-checked so an HTML error page is never saved as a PDF.
- **Politeness vs. speed.** The default worker cap (64) balances throughput against hammering one server. Lower `--workers` if you see throttling.

## Troubleshooting

- **`python` is not found.** Activate `dsip-opportunities` first. In Command Prompt: `call "%UserProfile%\miniconda3\condabin\conda.bat" activate dsip-opportunities`. In bash: `source "$HOME/miniconda3/etc/profile.d/conda.sh"` then `conda activate dsip-opportunities`.
- **A topic PDF fails.** The manifest row has `pdfStatus: "failed"` and `pdfError`. Re-run with the same `--output`; valid PDFs are skipped and failed ones retried.
- **Throttling or connection resets.** Lower `--workers`.
- **The catalog total changed between two runs.** That is the live DSIP list. Compare `apiTotal` in the two manifests.
- **Notebook browser cells.** They need a Chromium install from Playwright (`playwright install chromium`) and, on Linux/WSL, `playwright install-deps`. Outputs go under `notebook_outputs/` unless `DSIP_OUTPUT_ROOT` is set. `main.py` does not launch a browser.
