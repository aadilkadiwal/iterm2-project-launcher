# iTerm2 Project Launcher

A native macOS project launcher for iTerm2 that opens split-pane development environments with a single keyboard shortcut.

Stop wasting 2-3 minutes manually splitting panes, cd-ing into directories, and running commands every time you switch projects. Press **`Cmd+Option+A`** and you're coding in 1 second.

## Features

- **One shortcut** (`Cmd+Option+A`) to launch any project
- **Auto-detects project structure** — finds frontend/backend/celery directories and opens 3 or 4 pane layouts automatically
- **Runs your dev commands** — `yarn dev`, `make run`, `make celery`, `make sh` start automatically in each pane
- **Spotlight-style UI** — native macOS translucent picker with grouped section cards
- **Search** — instantly filter across all projects
- **Running indicator** — see which projects already have open tabs
- **Pin/favorite** — pin frequently used projects, sections, and subdirectories to the top
- **New Tab options** — quickly open 1, 2, 3, or 4 pane tabs at home directory
- **Create directories** — inline `+` button to create new projects or subdirectories
- **Expand/collapse** — toggle subdirectory visibility per project
- **Open in Finder/Cursor** — one-click to open any subdirectory in Finder or Cursor IDE
- **Tab naming** — iTerm2 tab title is set to the project name
- **Color-coded badges** — green `[4P]` (4 panes, has Celery), blue `[3P]` (3 panes), gray `[2P]`
- **Keyboard navigation** — Up/Down arrows, Enter to launch, Esc to close
- **Zero dependencies** — uses only macOS built-in frameworks (AppKit, Foundation) and iTerm2's Python API

## Pane Layouts

### 4-Pane Layout (project uses Celery)
```
+------------+------------+
|  Frontend  |  Backend   |
|  yarn dev  |  make run  |
+------------+------------+
|   Celery   |   Shell    |
| make celery|  make sh   |
+------------+------------+
```

### 3-Pane Layout (no Celery)
```
+------------+------------+
|            |  Backend   |
|  Frontend  |  make run  |
|  yarn dev  +------------+
|            |   Shell    |
|            |  make sh   |
+------------+------------+
```

## Installation

### 1. Copy the script

```bash
cp project_launcher.py ~/Library/Application\ Support/iTerm2/Scripts/
```

### 2. Enable Python API in iTerm2

Go to **iTerm2 > Settings > General > Magic** and check **Enable Python API**.

### 3. Run the script

In iTerm2, go to **Scripts > project_launcher** to launch the picker.

### 4. Set up keyboard shortcut (recommended)

1. Open **iTerm2 > Settings** (`Cmd+,`)
2. Go to **Keys > Key Bindings**
3. Click the **`+`** button
4. Press **`Cmd+Option+A`** in the shortcut field
5. Action: **Select Menu Item...**
6. Type: `Scripts > project_launcher`
7. Click **OK**

Now press `Cmd+Option+A` from anywhere in iTerm2 to open the project picker.

## Project Structure

Your project root should follow this structure:

```
~/your/project/root/
├── Work/                    # Section (shown as grouped card)
│   ├── ProjectA/            # Project
│   │   ├── frontend/        # Auto-detected
│   │   └── backend/         # Auto-detected
│   ├── ProjectB/
│   └── ...
└── Personal/                # Section
    ├── SideProject/
    └── ...
```

- **Sections** = top-level directories (e.g., Work, Personal, Client)
- **Projects** = directories inside sections
- **Subdirectories** = directories inside projects (frontend, backend, etc.)

The launcher auto-detects:
- **Frontend** — any directory with "frontend" in the name
- **Backend** — any directory with "backend" in the name
- **Celery** — checks Makefile, requirements.txt, docker-compose.yml, celery.py for celery references

## Configuration

### Project Root

Edit the `PROJECT_ROOT` variable at the top of `project_launcher.py`:

```python
PROJECT_ROOT = os.path.expanduser("~/Desktop/Project")
```

Change it to your project root path.

### Default Commands

Edit `DEFAULT_COMMANDS` to match your workflow:

```python
DEFAULT_COMMANDS = {
    "frontend": "yarn dev",
    "backend": "make run",
    "celery": "make celery",
    "shell": "make sh",
}
```

### Excluded Directories

Directories like `node_modules`, `.git`, `temp`, etc. are excluded from the picker. Edit `EXCLUDE_DIRS` to customize:

```python
EXCLUDE_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv",
    "media", "static", "assets",
    # ... add your own
}
```

## Data Files

The launcher stores user data in `~/.config/iterm2/`:

| File | Purpose |
|------|---------|
| `project_launcher_pins.json` | Pinned/favorited projects and sections |
| `project_launcher_usage.json` | Usage frequency for sorting |

## UI Overview

```
  Search projects...

  NEW TAB
  [ 1 Pane ] [ 2 Pane ] [ 3 Pane ] [ 4 Pane ]

  RUNNING                              2 active
  +-------------------------------------------+
  |  * Living Thing    * Ngo-assesment        |
  +-------------------------------------------+

  * PIXELDUST                     + 11 projects
  +-------------------------------------------+
  |  * [4P]  Benepower           +    2 |     |
  |  - - - - - - - - - - - - - - - - - -|     |
  |  * [4P]  Finops              +    2 |     |
  |  - - - - - - - - - - - - - - - - - -|     |
  |  * [3P]  Ecom Express        +    2 |     |
  +-------------------------------------------+
```

- **Pin** (star) — click to pin/unpin, pinned items sort to top
- **Badge** `[4P]`/`[3P]` — pane layout indicator (green = 4P, blue = 3P)
- **Plus** `+` — create new directory
- **Toggle** `2 down/up` — expand/collapse subdirectories
- **Name** — click to open project in iTerm2

## Requirements

- **macOS** 14+ (Sonoma or later)
- **iTerm2** 3.4+ with Python API enabled
- **Python** — uses iTerm2's bundled Python (no separate installation needed)

## How It Works

1. On launch, the script scans your project root for sections and projects
2. It briefly connects to iTerm2 to detect which projects already have open tabs
3. A native Cocoa picker (NSPanel + NSVisualEffectView) is displayed — no Electron, no web views
4. When you select a project, it connects to iTerm2 and creates a new tab with split panes
5. Each pane runs the configured command (`yarn dev`, `make run`, etc.)
6. The tab title is set to the project name for easy identification

## License

MIT License - see [LICENSE](LICENSE) for details.

## Author

**Aadil Kadiwal** - [GitHub](https://github.com/aadilkadiwal)
