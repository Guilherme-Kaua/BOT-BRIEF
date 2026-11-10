# Design Document: Vida Organizer (`BOT-BRIEF`)

**Date:** 2026-11-09  
**Project Size:** Full Project  
**Target Platform:** Windows 10/11 (`Python 3.15` backend + System Tray + Local Web Dashboard)

---

## 1. Intent and the Why

The user (`kauam`) uses a two-drive Windows setup:
- **`C:\` (111 GB SSD, ~15.6 GB free):** Houses Windows, `C:\Users\kauam\Downloads`, `Desktop`, `Documents`, and active coding workspaces in `C:\Projetos`.
- **`F:\` (930 GB drive, ~410 GB free):** Houses **`F:\Vida`**, a PARA-inspired central directory structure (`00_Jogos`, `01_Projetos`, `02_Areas`, `03_Recursos`, `04_Arquivo_Morto`, `99_Inbox`) styled with colored folder icons via **Folcolor** (`C:\Program Files (x86)\Folcolor\Folcolor.exe` in `desktop.ini`).

While `F:\Vida` was designed as the clean home for the PC's files, day-to-day usage creates four recurring problems:
1. **`C:\Downloads` fills up the SSD:** Heavy `.exe`/`.msi` installers (`AnythingLLM`, `Obsidian`, multiple `MangoDisk` versions), `.zip`/`.rar` files sitting next to their already-extracted folders (`Login.zip` + `Login/`, `VALORANT FPSPACK 2.0.rar` + folder), images with hash/messy names (`32704256...jpg`, `WhatsApp Image...`), and college/concurso files pile up in `Downloads`.
2. **Loose files in `F:\Vida` category roots:** Files get dropped directly into `F:\Vida\02_Areas` or `F:\Vida\03_Recursos` (e.g., `AlumiGest.pdf`, `Ata_de_Reuniao_Sprint1-4-v5.pdf`, `TJPB.apkg`) instead of their proper subfolders (`01_Faculdade\ADS`, `01.2_Biblioteca_Concursos`).
3. **Unstandardized folders and missing icons:** Generic folder names (`Nova pasta`, `Projet`, `Projet 2`, `prova amanha`) appear across `01_Projetos` and `C:\Projetos`, and newly created subfolders inside `F:\Vida` revert to the default yellow Windows folder icon instead of inheriting their category's `Folcolor` icon.
4. **Lack of visibility:** Traditional background scripts either move files silently (confusing the user when a just-downloaded file vanishes) or provide no visual feedback on what is currently organized vs. disorganized and what rules are active.

**Vida Organizer (`BOT-BRIEF`)** solves this by acting as a lightweight background guardian in the Windows System Tray that uses `F:\Vida` as the official central hub, paired with an on-demand visual dashboard where the user can see folder health (**Organizado vs. Desorganizado**), inspect the simulation queue before or after moves, manage visual rules (**Se → Então + Cor Folcolor**), reclaim disk space on `C:\`, and undo any action in one click.

---

## 2. Goals, Non-Goals, and Anti-Goals

### Goals
- **Real-time & Scheduled Folder Health Classification:** Continuously scan watched folders (`C:\Users\kauam\Downloads`, `Desktop`, `Documents`, and `F:\Vida`) and classify items into **Organizado** vs. **Desorganizado** using a simulation engine inspired by `tfeldmann/organize`.
- **Smart Routing into `F:\Vida`:** Route files from `C:\Downloads` and loose category roots in `F:\Vida` into their exact target subfolders (`02_Areas\01_Faculdade\ADS`, `03_Recursos\01.2_Biblioteca_Concursos`, `00_Jogos\Ferramentas`, `03_Recursos\01_Biblioteca_Tech`, `03_Recursos\05_Midia_Cultura`, or `99_Inbox\Downloads` as fallback).
- **Disk Space Recovery Queue (`C:\` Relief):** Detect heavy installers (`.exe`, `.msi`, `.msix`), duplicate/versioned files (`v4`/`v5`, `(1)`), and redundant archives (`.zip`/`.rar` where an extracted folder of the same base name already exists) and group them under **Espaço Recuperável** for safe 1-click cleanup (Move to Recycle Bin via `send2trash` or archive to `F:\Vida\04_Arquivo_Morto`).
- **Automatic Visual Standardization (`Folcolor` + Clean Names):**
  - Automatically apply `desktop.ini` with the parent category's `Folcolor` icon index (and required Windows `FILE_ATTRIBUTE_SYSTEM | FILE_ATTRIBUTE_HIDDEN` on `desktop.ini` + `FILE_ATTRIBUTE_READONLY` on the directory) to subfolders inside `F:\Vida`.
  - Flag folders with generic names (`Nova pasta`, `Projet`, `Projet 2`) and files with hash/WhatsApp names (`32704256...jpg`, `WhatsApp Image...`) with clean rename suggestions.
- **Hybrid System Tray + Full Local Dashboard UX (Option C):**
  - Run quietly in the Windows System Tray (`< 30 MB` RAM) with quick actions (*Status*, *Organizar Tudo Agora*, *Desfazer Última Ação*, *Pausar Vigia*, *Abrir Painel*).
  - Open a modern dark-mode web dashboard on localhost when *Abrir Painel* is clicked, displaying Folder Health Cards, the Disorganized Queue, and Visual Rule Cards.
- **1-Click Undo Ledger:** Record every file move, rename, recycle bin action, and `desktop.ini` change in a local SQLite database so any batch or individual operation can be reversed cleanly.

### Non-Goals
- **Not a Windows Explorer replacement:** Users still browse and open files in Windows Explorer; the dashboard is strictly for organization visibility, rule management, space cleanup, and undo history.
- **No cloud sync or external AI API dependency:** The bot works 100% locally and offline without requiring paid LLM API keys.
- **No deep scanning of system directories:** `C:\Windows`, `Program Files`, `AppData`, etc. are never scanned.

### Anti-Goals (Must Never Happen)
- **Never break code projects or installed games:** Any directory containing `.git`, `node_modules`, `.venv`, `pyproject.toml`, `package.json`, `.sln`, or located inside `SteamLibrary`, `Riot Games`, `XboxGames`, `WindowsApps`, or `C:\Projetos` (inside individual project folders) is **strictly untouchable** — the bot must never move or rename internal project/game files.
- **Never snatch a file the user just downloaded:** Files in `C:\Downloads` must never be moved automatically the instant they finish downloading. Active downloads (`.crdownload`, `.part`, `.tmp`, locked files) are ignored, and automatic background moves from `C:\Downloads` only happen after a configurable idle cooldown (default: **2 hours** since creation/last modification), unless the user explicitly clicks **"Organizar Agora"** in the dashboard/tray.
- **Never silently delete files:** Automatic background execution only performs non-destructive **moves** (to `F:\Vida`) and **`desktop.ini` styling**. Deleting installers, duplicates, or redundant `.zip` files always requires explicit user confirmation in the dashboard (and even then uses the Windows Recycle Bin via `send2trash`, never raw `os.unlink`).
- **Never overwrite an existing file on conflict:** If a target path already has a file with the same name, compare SHA-256 hashes; if identical, flag as duplicate; if different, append a clean timestamp/version suffix (`_2026-11-09` or `_v2`) rather than overwriting.

---

## 3. Constraints

- **Operating System:** Windows 10/11 (`nt`). Relies on Windows file attributes (`ctypes.windll.kernel32.SetFileAttributesW` or `attrib`) so Explorer respects `desktop.ini`.
- **Available Runtimes on Machine:** Python `3.15.2`, Node.js `v26.12.1`, `pnpm` `12.14.0`. No Rust compiler installed.
- **Folcolor Path & Indices (from existing `F:\Vida` setup):**
  - Root `F:\Vida`: `C:\Program Files (x86)\Folcolor\Folcolor.exe,13`
  - `00_Jogos`: `Folcolor.exe,4`
  - `01_Projetos`: `Folcolor.exe,6`
  - `02_Areas`: `Folcolor.exe,9`
  - `03_Recursos`: `Folcolor.exe,8`
  - `04_Arquivo_Morto`: `Folcolor.exe,15`
  - `99_Inbox`: `Folcolor.exe,2`
  - *Fallback (Builder Call):* If `Folcolor.exe` is missing on a machine, fall back to standard `C:\Windows\System32\shell32.dll` icons without crashing.

---

## 4. Approaches Considered

### Approach 1: Lightweight Python Service in System Tray + Local FastAPI Web Dashboard (Selected)
- **Architecture:** Python background service (`watchdog` + periodic scanner + `pystray` for Windows tray icon + `FastAPI`/`uvicorn` serving a single-page dark-mode dashboard on `127.0.0.1`). SQLite stores rules, scan state, and the Undo ledger.
- **Pros:** Minimal RAM footprint (`~20–30 MB`) while gaming or coding; native `ctypes`/Win32 access for `desktop.ini` attributes and file lock checks; borrows the best simulation-first rule pattern from `tfeldmann/organize` and undo/tray patterns from `smart-file-organizer`; delivers the exact rich visual dashboard approved in the mockup.
- **Cons:** Opens the full dashboard in the user's browser (or `--app=` frameless browser window) rather than bundling a separate 200 MB Chromium binary.

### Approach 2: Node.js + Electron Desktop App (Inspired by `mojouto3/mojo-file-organizer`)
- **Architecture:** Electron main process (`chokidar` + tray) + React renderer window.
- **Pros:** Self-contained native desktop window.
- **Cons:** Consumes `180–300 MB` RAM permanently in the background just to sit in the tray; requires spawning PowerShell subprocesses to set Windows system/hidden attributes on `desktop.ini`.

### Approach 3: Wrapping `tfeldmann/organize` CLI + `CustomTkinter` Native GUI
- **Architecture:** Uses the off-the-shelf `organize-tool` Python package for YAML rules with a `CustomTkinter` desktop window.
- **Pros:** Less custom rule-matching code.
- **Cons:** `CustomTkinter` cannot easily reproduce the rich visual layout (health cards, side-by-side queue and color-coded rule blocks), and `organize-tool` lacks folder health scoring (`% Organizado`), `Folcolor` inheritance, and project-folder protection locks.

**Decision:** The user selected **Approach 1** paired with **UX Option C (Hybrid Tray + Full Dashboard on click)**.

---

## 5. Detailed Design (What Was Decided)

### 5.1 System Architecture
```
c:\Projetos\BOT-BRIEF\
├── app/
│   ├── main.py                # Entrypoint: starts FastAPI server + background scheduler + System Tray (or CLI/headless mode)
│   ├── config.py              # Default paths (C:\Downloads, F:\Vida), cooldowns, Folcolor icon map
│   ├── db.py                  # SQLite database (rules, action_history / undo batches, settings)
│   ├── engine/
│   │   ├── protector.py       # Anti-goal guard: detects .git, node_modules, SteamLibrary, active downloads, open file locks
│   │   ├── scanner.py         # Scans watched directories, computes % Organizado health score & disorganization items
│   │   ├── rules.py           # Rule evaluation engine (Sim mode vs. Execute mode) + default F:\Vida rule seed
│   │   ├── duplicates.py      # Detects duplicate files (size + SHA-256), versioned names (v4/v5), and archive+extracted-folder pairs
│   │   ├── folcolor.py        # Reads/applies Folcolor desktop.ini + Win32 FILE_ATTRIBUTE_SYSTEM/HIDDEN/READONLY
│   │   └── executor.py        # Executes moves, renames, send2trash, and writes reversible Undo entries to SQLite
│   ├── api/
│   │   └── routes.py          # REST API for dashboard: /status, /queue, /rules, /execute, /undo, /folcolor, /settings
│   ├── tray/
│   │   └── tray_agent.py      # Windows System Tray icon & menu (Abrir Painel, Organizar Agora, Desfazer, Pausar, Sair)
│   └── static/
│       ├── index.html         # Dark-mode Dashboard UI (Health cards, Disorganized Queue, Visual Rules, History/Undo)
│       ├── styles.css         # Styling matching the approved mockup
│       └── app.js             # Interactive frontend logic (one-click organize, per-item actions, rule editor modal)
├── tests/                     # Automated pytest suite using temporary directories (never touches real user files in tests)
└── requirements.txt
```

### 5.2 Folder Health & Classification Model ("Organizado vs. Desorganizado")
For each watched root (`C:\Users\kauam\Downloads`, `C:\Users\kauam\Desktop`, `C:\Users\kauam\Documents`, and the 6 main folders of `F:\Vida`), the scanner calculates:
- **Status Badge:**
  - `ORGANIZADO` (Green): `>= 90%` compliant, 0 loose files in category roots, icons applied.
  - `SOLTOS NA RAIZ` / `FORA DO PADRÃO` (Amber): `60% – 89%` compliant (e.g., loose PDFs in `F:\Vida\02_Areas` or unstandardized folder names like `Nova pasta`, `Projet` in `01_Projetos`).
  - `DESORGANIZADO` (Red): `< 60%` compliant or `> 10` loose/recoverable items (e.g., `C:\Downloads`).
- **Disorganized Queue Categories:**
  1. **`pronto_para_mover` (Auto-safe):** Matches a routing rule into `F:\Vida` (e.g., `AlumiGest.pdf` → `F:\Vida\02_Areas\01_Faculdade\ADS`). Moves automatically once past the idle cooldown (2h for `Downloads`; 15m for loose files dropped in `F:\Vida` category roots), or immediately when user clicks **Organizar Agora**.
  2. **`espaco_recuperavel` (Requires 1-click user confirmation):**
     - Heavy installers in `Downloads` (`.exe`, `.msi`, `.msix` older than 24h).
     - Redundant archives (`.zip`, `.rar`, `.7z` in `Downloads` where a directory with the same stem already exists in the same folder, e.g., `Login.zip` + `Login/`).
     - Exact duplicates (identical size + SHA-256 hash) or obvious older revisions (`Ata_de_Reuniao_Sprint1-4-v4.pdf` vs `v5.pdf`).
     - User can click **Mover p/ Lixeira** (`send2trash`) or **Arquivar em `04_Arquivo_Morto`**.
  3. **`renomear_sugerido` (Visual cleanup):**
     - Files with hash/WhatsApp/Gemini names (`3270425600f6...jpg`, `WhatsApp Image 2026-10-27...jpeg`, `Gemini_Generated_Image_...jpg`) or folders named `Nova pasta`, `Projet`, `Projet 2`.
     - Suggests a clean standardized name (e.g., `Img_2026-11-03_327042.jpg`, `WhatsApp_2026-10-27_12h17.jpeg`) and target destination.
  4. **`icone_pendente` (`Folcolor` standardization):**
     - Subfolders inside `F:\Vida` missing a `desktop.ini` or missing the Windows Read-Only directory attribute needed to display their category's `Folcolor` icon.

### 5.3 Default Visual Rule Set (Seeded for `kauam`'s PC)
Rules are stored in SQLite (and exportable/importable as JSON) and rendered as visual **Se → Então + Folcolor** cards in the UI:
1. **Faculdade / ADS (`Folcolor #9` - `02_Areas`):**
   - **IF** source is `C:\Downloads`, `Documents`, or loose in `F:\Vida\02_Areas` / `03_Recursos` **AND** filename matches keywords (`AlumiGest`, `Sprint`, `Ata_de_Reuniao`, `Aula`, `ADS`, `Usabilidade`, `Disponibilidade`, `Teste`, `Mapa da Empatia`, `PGC`, `Wazlawick`) with extensions `.pdf, .docx, .pptx, .xlsx, .txt, .zip`
   - **THEN** move to `F:\Vida\02_Areas\01_Faculdade\ADS` + apply `Folcolor #9`.
2. **Concursos & Estudos (`Folcolor #8` - `03_Recursos`):**
   - **IF** extension is `.apkg` **OR** filename matches (`PRF`, `TJPB`, `ACI`, `Concurso`, `Prova Objetiva`, `Edital`, `Study-OS`, `studyn-ciclo`)
   - **THEN** move to `F:\Vida\03_Recursos\01.2_Biblioteca_Concursos` + apply `Folcolor #8`.
3. **Documentos Pessoais & Currículos (`Folcolor #9` - `02_Areas`):**
   - **IF** filename matches (`Curriculo`, `Currículo`, `RG`, `CPF`, `Historico escolar`, `Comprovante`, `Contrato`)
   - **THEN** move to `F:\Vida\02_Areas\04_Docs_Pessoais` + apply `Folcolor #9`.
4. **Ferramentas, Portáteis & Mods (`Folcolor #4` / `#8`):**
   - **IF** folder or archive in `Downloads` matches tool/mod patterns (`ghidra`, `SDIO`, `FPSPACK`, `r2modman`, `MangoDisk-portable`, `scrcpy`, `yt-dlp`)
   - **THEN** move to `F:\Vida\00_Jogos\Ferramentas` (or `03_Recursos\01_Biblioteca_Tech` for dev tools like `ghidra`, `SDIO`).
5. **Mídia, Imagens & Memes (`Folcolor #8` - `03_Recursos`):**
   - **IF** extension is `.jpg, .jpeg, .png, .webp, .gif, .mp4` in `C:\Downloads` (after idle cooldown)
   - **THEN** clean filename (if hash/WhatsApp/Gemini) and move to `F:\Vida\03_Recursos\05_Midia_Cultura\Imagens_Salvas`.
6. **Fallback de Downloads Antigos (`Folcolor #2` - `99_Inbox`):**
   - **IF** any other non-installer file sits untouched in `C:\Downloads` for `> 3 days`
   - **THEN** move to `F:\Vida\99_Inbox\Downloads` to keep `C:\` free.

---

## 6. What's Left to the Builder (and Builder Calls)

- **UI Window Mode (Builder Call):** When clicking "Abrir Painel" in the System Tray, attempt to open Microsoft Edge / Chrome in `--app=http://127.0.0.1:<port>` mode so it looks and feels like a standalone native desktop window; fall back to `webbrowser.open()` if neither browser flag is available.
- **Port Selection (Builder Call):** Bind FastAPI to `127.0.0.1:18420` by default (with automatic fallback to a free port if busy).
- **File Lock Verification:** Before moving any file, attempt an exclusive open check (`open(path, 'rb+')`) so files currently open in Word, PowerPoint, PDF readers, or browsers are skipped until closed.
- **Depth of `Folcolor` Inheritance (Builder Call):** Apply `Folcolor` `desktop.ini` automatically to 1st and 2nd level subfolders inside `F:\Vida` categories (skipping protected code/game folders) so the user's daily navigation folders all have clean colored icons without touching thousands of deep asset subfolders inside games or backups.

