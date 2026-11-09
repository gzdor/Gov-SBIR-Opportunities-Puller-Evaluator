# Run this tool on Windows 11 without Git, conda, or admin

For a business analyst or BD manager who has a normal Windows 11 PC, no
Python yet, no Git, and **no administrator password**. You will install
Python from the Microsoft Store (per-user), download a ZIP of this project
from GitHub, and start the window with one command.

Developers who already have conda should keep using the main
[README.md](../README.md) (`dsip-opportunities` env).

This project is licensed [PolyForm Noncommercial](../LICENSE) except for
**Camgian Corporation** (CAGE 4NP29; [camgian.com](https://www.camgian.com/)),
which may use it for Camgian’s own commercial / BD work. No other company
may. If you are using it for company business and you are not Camgian,
read that license first — it does not allow that.

There is **no** official `.exe` download. Unsigned copies are often blocked
as malware; this guide uses Microsoft Store Python instead.

## What you will have when you are done

A window titled **DSIP Opportunities — Discovery**. You pick a folder
(Downloads is fine), click **Download all opportunities**, and get a table of
open DoD SBIR/STTR topics plus PDFs on your PC. Nothing you type is sent to
DSIP as a search box. There is no login.

You need: Windows 11, internet, about 500 MB of disk, 15 minutes.

## 1. Install Python from the Microsoft Store (no admin)

You may need to **sign in to the Microsoft Store** before it will let you
install Python. Use the Microsoft account already on this PC (personal or
work/school). If **Get** / **Install** is greyed out, click the profile icon
in the top-right of Store, sign in, then try Python again.

1. Open the **Microsoft Store** (Start menu → type `Store`).
2. Sign in if Store asks (profile icon, top right). A BD analyst does not
   need admin rights for this — only a Store login.
3. Search for **Python 3.13** (Python 3.12 is also fine).
4. Open the listing published by the **Python Software Foundation**.
5. Click **Get** / **Install**. Wait until it says **Open**.
6. If Windows asks about **app execution aliases**, leave **python.exe** and
   **python3.exe** **On** (Settings → Apps → Advanced app settings → App
   execution aliases).

Check it worked:

1. Press **Start**, type `Terminal` or `cmd`, press Enter.
2. Type this line and press Enter:

```bat
python --version
```

You should see `Python 3.12` or `Python 3.13` (or similar), not
“Python was not found.”

If you see “Python was not found”:

- Open **Microsoft Store** again and confirm Python is installed.
- Turn **python.exe** on under App execution aliases (search Windows for
  `app execution aliases`).
- Close Terminal completely and open a **new** Terminal window, then retry
  `python --version`.

You do **not** need Miniconda, Visual Studio, or Git.

## 2. Download this project without Git

1. In a browser, open  
   <https://github.com/gzdor/Gov-SBIR-Opportunities-Puller-Evaluator>
2. Click the green **Code** button.
3. Click **Download ZIP**.
4. When the ZIP finishes, open your **Downloads** folder.
5. Right-click `Gov-SBIR-Opportunities-Puller-Evaluator-main.zip` →
   **Extract All…** → **Extract**.
6. Open the new folder, then open the inner folder until you see `gui.py`
   in the list of files.

Remember that folder. Example:

`C:\Users\YourName\Downloads\Gov-SBIR-Opportunities-Puller-Evaluator-main\Gov-SBIR-Opportunities-Puller-Evaluator-main`

## 3. Start the app

**Option A — double-click (easiest)**

1. In that folder, double-click `run-gui.bat`.
2. The first run may take a minute while it installs `pypdf` (PDF reading).
3. A dark window should open. If a black console window appears too, leave
   it open while you use the app.

If Windows SmartScreen says it “prevented an unrecognized app”:

1. Click **More info**.
2. Click **Run anyway** only if you downloaded the ZIP from the GitHub
   address above.

**Option B — type two lines**

1. In File Explorer, click the address bar at the top of the folder that
   contains `gui.py`.
2. Type `cmd` and press Enter. A terminal opens in that folder.
3. Run:

```bat
python -m pip install pypdf
python gui.py
```

## 4. First capture (what to click)

1. **Save in folder** can stay `C:\Users\YourName\Downloads`.
2. Leave **Download filter** empty to pull every open topic, or type a
   phrase such as `DAF UAS` (that filter stays on your PC).
3. Click **Download all opportunities**.
4. Wait until the bar says **Done**. The table fills earlier; PDFs finish
   after.
5. Click a row. The bottom **Topic** pane shows the overview, page limits,
   CMMC, **Released** date, and Q&A that were already public on DSIP.
6. If you already have an older download in the same folder, **New** /
   **New Q&A** chips fill in automatically. Click **New** to see only topics
   that were not in the previous snapshot. Click **Released** to sort newest
   first.

Page limits: **Tech Vol Page Limit** and **Feasibility Study Page Limit**.
A value like `5 (stated)` was read from that topic’s instruction PDF. A
blank cell means the PDF did not state a number — not a guess. Details:
[PAGE_LIMIT_EXTRACTION_README.md](PAGE_LIMIT_EXTRACTION_README.md).

Your Pursue / Watch / Pass marks stay on this computer in
`%USERPROFILE%\.dsip_downloader_state.json`. They are not uploaded.

## 5. Next time

Open the same folder and double-click `run-gui.bat` again. Use **Open
snapshot** if you want yesterday’s download without hitting DSIP.

## If something fails

| What you see | What to try |
| --- | --- |
| Store will not install Python / Get is greyed out | Sign in to Microsoft Store (profile icon), then retry Python 3.13 |
| `python` is not found | Store Python + app execution aliases; new Terminal |
| `pip` / `pypdf` install fails | Stay on internet; retry `python -m pip install pypdf` |
| Window never appears | Run `python gui.py` in Terminal and read the red text |
| Page-limit columns empty | Restart the app once (it installs `pypdf`); use **Open snapshot** |
| Download errors | DSIP must be reachable; try again later; resume is automatic for valid PDFs already in the folder |
| Company laptop blocks Store | You need IT, or a developer with conda — this guide cannot bypass policy |

You never need to “Run as administrator” for these steps.
