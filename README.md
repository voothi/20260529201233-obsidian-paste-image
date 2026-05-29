# Obsidian Paste Image ZID Utility

[![Version](https://img.shields.io/badge/version-v1.0.0-green)](https://github.com/voothi/20260529201233-obsidian-paste-image)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

A premium, lightweight Python command-line utility to automate extracting copied/screenshot image data from the system clipboard, dynamically saving it as a ZID-tracked file in the active project vault's assets folder, and generating/pasting clean Obsidian Wikilinks seamlessly.

## Table of Contents
- [Features](#features)
- [Project Structure](#project-structure)
- [Configuration](#configuration)
- [Usage](#usage)
- [AHK Integration](#ahk-integration)
- [Running Tests](#running-tests)
- [License](#license)

---

## Features
- **Classic Relative Mode (Main Option)**: Resolves the open active markdown note path via window title extraction (`--title`) or recently modified files, saving images inside the same directory's `assets/` subfolder (e.g., `U:\voothi.vault\kardenwort-mpv\conversations\assets`) exactly matching Obsidian's standard local attachment system.
- **Dynamic Vault Fallback (Spare Option)**: Automatically falls back to the workspace project-level `assets/` folder if no active editing file is found anywhere.
- **ZID-Tracked Filenames**: Saves all pasted screenshots and clipboard images starting with a unique 14-digit ZID timestamp (`YYYYMMDDHHMMS-pasted-image.png`) to preserve perfect chronological traceability.
- **Double Copied File Support**: Handles both raw image clipboard data (screenshots) and copied image files (Ctrl+C from explorer), reading and saving them dynamically.
- **Silent AHK Wrapper**: Pairs beautifully with an AutoHotkey shortcut to run silently in the background and instantly paste Obsidian links.

---

## Project Structure
```text
20260529201233-obsidian-paste-image/
├── config.ini               # Fallback configuration directory settings
├── config.ini.template      # Configurations settings template
├── README.md                # Detailed utility documentation
├── src/                     # Source directory containing implementation
│   └── paste_image.py       # Core image clipboard parser and saver
└── tests/                   # Automated unit test suite
    └── test_paste_image.py  # Complete test coverage for directory resolution
```

---

## Configuration

Default `config.ini` settings:
```ini
[Obsidian]
# Fallback vault root base
vault_base = U:\voothi.vault

# Default project name fallback
default_project = default

# Asset attachments subfolder name inside vault
assets_folder = assets
```

---

## Usage

### 1. Manual Invocation (CLI)
Instantly save clipboard image to fallback vault:
```powershell
python src/paste_image.py
```

### 2. Dynamically Save to Active Project Workspace
```powershell
python src/paste_image.py --workspace "20260308110646-kardenwort-mpv"
```

### 3. Save with Custom Title Slug
```powershell
python src/paste_image.py --name "main-menu-design"
```

---

## AHK Integration (`Ctrl + Alt + I`)

Add the following shortcut inside `U:\voothi\20240411110510-autohotkey\obsidian-paste-image.ahk` to enable high-speed universal image pastes:
```autohotkey
^!i::
{
    ; Extract the active window title to parse the workspace (e.g., 20260308110646-kardenwort-mpv)
    activeTitle := WinGetTitle("A")
    workspace := ""
    if RegExMatch(activeTitle, "(\d{14}-[\w-]+)", &match) {
        workspace := match[1]
    }

    cmd := "C:\Python\Python312\python.exe U:\voothi\20260529201233-obsidian-paste-image\src\paste_image.py"
    if (workspace != "") {
        cmd .= " --workspace `"" . workspace . "`""
    }
    if (activeTitle != "") {
        cmd .= " --title `"" . activeTitle . "`""
    }

    RunWait(cmd, "U:\voothi\20260529201233-obsidian-paste-image", "Hide")
    Sleep(300)
    KeyWait "Alt"
    KeyWait "Control"
    Send("^v")
}
```

---

## Running Tests

To run the unit test suite and verify dynamic project path resolution, execute:
```powershell
python tests/test_paste_image.py
```

---

## License
MIT License. See LICENSE file for details.
