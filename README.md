# Gov SBIR Opportunities Puller

Downloads the current public [DoD SBIR/STTR DSIP topics catalog](https://www.dodsbirsttr.mil/topics-app/) to disk: one topic-detail PDF per topic, the shared solicitation PDFs attached to those topics, and a `manifest.json` that lists every record the API returned.

`main.py` is the script to run. `DSIP_portal_ai_query_tool.ipynb` is the Colab notebook that found the DSIP search API and the download buttons. The notebook is kept as the research log. It still contains hard-coded Colab paths (`/content/...`) and a page-by-page browser scraper.

## Python version

Use **Python 3.12**. The conda environment for this repo is named `dsip-opportunities`. `main.py` uses only the standard library. Python 3.10 or newer can run the script; 3.12 is the version to install.

A fresh Miniconda `base` environment currently ships Python 3.14. Create `dsip-opportunities` with `python=3.12` so the project stays on the recommended version.

## Install Miniconda

Skip this when `conda --version` already prints a version. This machine already has Miniconda at `%UserProfile%\miniconda3` (Windows) and `~/miniconda3` (WSL). The one-liners are for a computer that does not have it yet. Both were run with the same installer flags into a temporary folder, checked with `conda --version` (conda 26.9.3), and then removed.

The install prefix cannot contain spaces. On Windows, `/D=` has to be the last argument.

Windows Command Prompt:

```bat
curl -fsSL -o "%TEMP%\Miniconda3-latest-Windows-x86_64.exe" https://repo.anaconda.com/miniconda/Miniconda3-latest-Windows-x86_64.exe && start /wait "" "%TEMP%\Miniconda3-latest-Windows-x86_64.exe" /InstallationType=JustMe /AddToPath=0 /RegisterPython=0 /S /D=%UserProfile%\miniconda3 && del "%TEMP%\Miniconda3-latest-Windows-x86_64.exe"
```

Bash:

```bash
curl -fsSL https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh -o /tmp/miniconda.sh && bash /tmp/miniconda.sh -b -p "$HOME/miniconda3" && rm /tmp/miniconda.sh
```

That Windows install does not put `conda` on `PATH`. In the same Command Prompt, load it with:

```bat
call "%UserProfile%\miniconda3\condabin\conda.bat"
```

In bash, load it and enter `base` with:

```bash
source "$HOME/miniconda3/etc/profile.d/conda.sh"
conda activate base
```

## Environment

Windows and WSL each have their own Miniconda, so each one has its own `dsip-opportunities` environment:

| Shell | Environment | Python reported |
| --- | --- | --- |
| Windows Command Prompt | `C:\Users\zdorg\miniconda3\envs\dsip-opportunities` | 3.12.15 |
| WSL bash | `/home/zdorg/miniconda3/envs/dsip-opportunities` | 3.12.13 |

From the repository root in Command Prompt:

```bat
cd /d C:\Users\zdorg\code_dev\Gov-SBIR-Opportunities-Puller-Evaluator
conda create -n dsip-opportunities python=3.12 -y
call "%UserProfile%\miniconda3\condabin\conda.bat" activate dsip-opportunities
python -c "import sys; print(sys.version)"
pip install -r requirements.txt
pytest
python main.py --help
```

In WSL bash, from the repo:

```bash
source "$HOME/miniconda3/etc/profile.d/conda.sh"
conda create -n dsip-opportunities python=3.12 -y
conda activate dsip-opportunities
python -c 'import sys; print(sys.version)'
cd /mnt/c/Users/zdorg/code_dev/Gov-SBIR-Opportunities-Puller-Evaluator
pip install -r requirements.txt
pytest
python main.py --help
```

Both sequences were run. `pip install -r requirements.txt` installs the notebook packages plus pytest. `pytest` runs the 14 tests in `test/test_main.py`. `python main.py --help` prints the downloader usage. `conda create` stops if that environment name already exists, which it now does on both installs.

## Quick start

With `dsip-opportunities` active, from the repository root:

```bat
python main.py
```

That creates a new folder in this directory named `all_dsip_opportunities_YYYYMMDD_HHMMSS` (local time) and writes the PDFs there.

To choose the folder yourself:

```bat
python main.py --output D:\dsip_pulls\october
```

A relative `--output` path is resolved from the current working directory. The folder is created if it does not exist. Files that are already valid PDFs in that folder are left in place, so a second run into the same directory resumes.

`requirements.txt` covers the notebook (Playwright, BeautifulSoup, requests, the browser-use agent, Jupyter) and pytest. `main.py` itself does not import those packages.

## Tests

```bat
call "%UserProfile%\miniconda3\condabin\conda.bat" activate dsip-opportunities
cd /d C:\Users\zdorg\code_dev\Gov-SBIR-Opportunities-Puller-Evaluator
pytest
```

The tests live in `test/test_main.py`. They cover filename cleanup, timestamped output folders, paging past a short page and past a full page of 100, PDF header checks, shared solicitation files, and a short catalog. Search and download calls are stubbed, so pytest does not contact DSIP.

## Will a run get every topic?

The numbers 10 and 100 in the notebook are page sizes. They are not a limit on how many topics to keep.

Checked against the live DSIP search API on 21 October 2026:

| Call | What came back |
| --- | --- |
| `size=10&page=0` | 10 records. The same call reports `total`. |
| `size=10&page=1` and `page=2` | The next 10, then the last 8. Page 3 is empty. |
| `size=100&page=0` | All 28 records in one response. `total` was 28. |

So a page of 10 is the first screen of the table. A page of 100 is one API request that happened to hold the whole catalog on that day. The catalog count changes as topics open and close. The script does not assume 28, 10, or 100.

What each notebook cell actually does:

- **Inspect API Data Structure** requests `size=10&page=0` and prints the first page plus `total`. It does not download files and does not request later pages.
- **Bulk API Downloader** requests `size=100` and then page 1, page 2, and so on. It stops when a page comes back with fewer than 100 rows. With the API honoring `size=100`, that loop does walk the whole open catalog: a short last page ends the loop, and a catalog of exactly 100, 200, ... causes one extra empty request and then stops. It would stop early if the server ever silently capped a page below 100 while `total` was still larger, because it never reads `total`. That cell also downloads only BAA preface and instruction files, and it calls `/document/download` URLs that respond with errors. The upload URL that returns a PDF is `https://www.dodsbirsttr.mil/submissions/api/public/download?uploadId=...`.
- **Deterministic Playwright scraper**, **Debugged Hybrid downloader**, and **Run Full Site PDF Downloader** walk the on-screen table. The saved notebook output says `Found 10 topic rows on this page` and then finishes. Ten is how many rows the topics table renders at once. The code looks for a Next Page button and is written to continue, but the output stored in the notebook ends after page 1, so that execution did not show a full-catalog download. Those cells also save into `/content/...`, which exists on Colab and not on this machine.

`main.py` requests pages of 100, reads `total`, and keeps going until every reported topic id is collected. A short page does not end the walk while `total` is still ahead. If the API says 28 and only 20 ids come back, the process exits with status 1 and records the gap in `manifest.json`. After the catalog is collected it downloads a topic PDF for each id.

"Every topic" here means every topic in the DSIP **open topics** view: the same search the notebook captured, `solicitationCycleNames: ["openTopics"]` and `topicReleaseStatus: [591, 592]`. That view includes pre-release and open solicitations. Closed and archived topics are a different search and are outside this download.

## What gets saved

```text
all_dsip_opportunities_20261021_205530/
  manifest.json
  topic_ARM26BX03-DP007_xTech_Kinetic Reach Competition.pdf
  topic_....pdf
  solicitation_documents/
    DoW 2026 SBIR CSO Preface_07152026.pdf
    ARMY_26BX_R3.pdf
```

- Topic PDFs are the file behind **Download Topic Details as: PDF** on each row. The DSIP app requests `GET /topics/api/public/topics/{topicId}/download/PDF`. A direct request returns a body that starts with `%PDF`. The filename follows the app's pattern, `topic_{topicCode}_{topicTitle}.pdf`, with characters Windows rejects (`\ / : * ? " < > |`) replaced. Titles longer than 100 characters are shortened in the filename; the full title stays in `manifest.json`. If two solicitation uploads share a file name, the second file name includes its upload id.
- `solicitation_documents/` holds each distinct BAA preface and component instruction PDF referenced by those topics (`baaPrefaceUploadId`, `baaInstructions[].uploadId`). Many topics share one preface, so each upload id is saved once.
- `manifest.json` lists the API total, every topic (code, title, status, component, program, solicitation, cycle, release, dates), the local PDF name, and any failures.

`all_dsip_opportunities_*/` is listed in `.gitignore`. A custom `--output` folder inside the repo is not ignored automatically.

The run prints a count at the end. Exit status `0` means the retrieved topic count matches `total` and every PDF saved or was already a valid PDF. Exit status `1` means a request failed or the catalog came up short. Exit status `130` means the run was interrupted; whatever finished is already on disk, and running again with the same `--output` skips valid PDFs.

## Notebook map

`DSIP_portal_ai_query_tool.ipynb` was written in Google Colab. Read it as the path that found the API. Use `main.py` to download.

1. **Setup.** `pip install browser-use langchain-google-genai playwright nest_asyncio ipywidgets`, then `playwright install chromium` and `playwright install-deps`. Later cells also import `beautifulsoup4` and `requests`, which are in `requirements.txt`.
2. **Configure Credentials.** Prompts for `GOOGLE_API_KEY`. Only the chatbot cell uses it.
3. **DSIP PDF Downloader Chatbot.** A `browser-use` agent on `gemini-1.5-pro` with a small widget UI. The following markdown cell says this agent hit structured-output compatibility problems, which is why the notebook switches to a fixed Playwright script.
4. **Deterministic Playwright scraper.** Headless Chromium, accepts the DoD consent banner, expands each `mat-expansion-panel`, clicks PDF icons, then clicks Next page. Output path: `/content/dod_sbir_pdfs_ui`.
5. **Row / page-source / network inspection.** Helpers that dump rendered HTML and XHR URLs. This is how the search endpoint was found.
6. **Inspect API Data Structure.** One GET of the public search API, `size=10&page=0`. Prints `total` and the keys on a topic record.
7. **Bulk API Downloader.** Paginates with `size=100` and tries to download preface and instruction uploads through a browser cookie jar. See the table above for the page-size behavior and the download URLs.
8. **Hybrid UI downloader** and **Run Full Site PDF Downloader.** Repeat the expansion-panel click loop. The stored output processed 10 rows and stopped.
9. **Git backup.** A Colab cell that commits and force-pushes with a GitHub personal access token. Leave `GITHUB_TOKEN` empty. This repository is already cloned from GitHub; that cell is not part of the downloader.

No Google API key is required for `main.py`. The search and PDF routes used here are the public ones the topics app calls when nobody is logged in.

## Troubleshooting

- **`python` is not found.** Activate `dsip-opportunities` first. In Command Prompt that is `call "%UserProfile%\miniconda3\condabin\conda.bat" activate dsip-opportunities`. In bash it is `source "$HOME/miniconda3/etc/profile.d/conda.sh"` and then `conda activate dsip-opportunities`.
- **A topic PDF fails.** The manifest row has `pdfStatus: "failed"` and `pdfError`. Run the same command again with the same `--output`. Valid PDFs are skipped; failed ones are retried.
- **The catalog total changed between two runs.** That is the live DSIP list. Compare `apiTotal` in the two manifests.
- **Notebook browser cells on this PC.** They expect Colab's `/content` directory and a Chromium install from Playwright. Point `DOWNLOAD_DIR` at a local folder before running them. `playwright install-deps` needs system packages and, in WSL, the usual browser libraries. `main.py` does not launch a browser.
- **Consent banner / 403s in the notebook's API cell.** Those cells call `/document/download`. The public topic PDF route and `submissions/api/public/download?uploadId=` respond without a browser session; that is what `main.py` calls. Each saved file is checked for a `%PDF` header, so an HTML error page is not kept as a successful download.
