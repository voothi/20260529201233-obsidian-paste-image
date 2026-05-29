"""
Obsidian Paste Image Utility
----------------------------
Reads an image from the system clipboard (screenshot or copied file),
saves it inside the correct Obsidian vault assets directory, and
writes the Obsidian Wikilink back to the clipboard.

Active-file resolution priority
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
1. --active-file  Direct absolute path to the open markdown file.
2. --title        Window title; the script parses the .md filename
                  and scans the vault for it.
3. --workspace    ZID-prefixed workspace token; infers vault project
                  directory and saves under <project>/assets/.
4. config fallback  default_project value from config.ini.
"""

import os
import sys
import re
import argparse
from datetime import datetime
import configparser

from PIL import Image, ImageGrab

try:
    import pyperclip
    PYPERCLIP_AVAILABLE = True
except ImportError:
    PYPERCLIP_AVAILABLE = False


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

def get_config(config_path: str = "config.ini") -> dict:
    """
    Loads configuration from *config_path*.
    All keys fall back to safe defaults so the script works without a
    config file.
    """
    config = configparser.ConfigParser()
    if os.path.exists(config_path):
        config.read(config_path, encoding="utf-8")

    return {
        "vault_base":      config.get("Obsidian", "vault_base",      fallback=r"U:\voothi.vault"),
        "default_project": config.get("Obsidian", "default_project", fallback="default"),
        "assets_folder":   config.get("Obsidian", "assets_folder",   fallback="assets"),
    }


# ---------------------------------------------------------------------------
# Active-file resolution helpers
# ---------------------------------------------------------------------------

def find_active_file(
    title: str | None,
    vault_base: str,
    project_name: str | None = None,
) -> str | None:
    """
    Resolves the path of the markdown file currently open in the editor
    by searching the vault for a filename extracted from the window title.

    Strategy
    --------
    If *title* contains a ``*.md`` filename, scan the vault for it.
    The search is **scoped** to ``vault_base/project_name/`` when
    *project_name* is supplied — this prevents common filenames such as
    ``README.md`` from matching unrelated files in other vault projects.

    When *project_name* is given but has no corresponding folder in the
    vault the function returns ``None`` immediately (the workspace is a
    code-project, not a vault-project; workspace resolution will handle it).

    Returns ``None`` when no match is found.
    """
    if not os.path.isdir(vault_base):
        return None

    if not title:
        return None

    match = re.search(r"([\w-]+\.md)\b", title)
    if not match:
        print("[*] No .md filename found in window title — skipping vault scan.")
        return None

    target_name = match.group(1)

    # Scope the search to the project folder when we know which vault project
    # the workspace belongs to.  This stops generic names like README.md from
    # picking up files in unrelated vault subdirectories.
    if project_name:
        search_root = os.path.join(vault_base, project_name)
        if not os.path.isdir(search_root):
            print(
                f"[*] Vault project '{project_name}' has no folder in vault "
                "— skipping title scan."
            )
            return None
    else:
        search_root = vault_base

    for root, dirs, files in os.walk(search_root):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        if target_name in files:
            found = os.path.join(root, target_name)
            print(f"[*] Active file resolved from window title: {found}")
            return found

    print(f"[*] '{target_name}' not found in vault — skipping vault scan.")
    return None


def discover_assets_dir(workspace: str | None, config: dict) -> tuple[str, str]:
    """
    Derives the vault assets directory from the *workspace* token (the
    ZID-prefixed workspace name visible in the editor title bar).

    Falls back to ``config["default_project"]`` when *workspace* is ``None``.

    Returns ``(assets_dir, project_name)``.
    """
    vault_base = config["vault_base"]

    if workspace:
        # Strip the leading ZID (14 digits + separator) and "(Workspace)" suffix
        project_name = re.sub(r"^\d{14}[-_\s]*", "", workspace.strip())
        project_name = re.sub(r"\s*\(Workspace\).*", "", project_name).strip()
    else:
        project_name = config["default_project"]

    vault_dir = os.path.join(vault_base, project_name)

    # If the workspace-derived project doesn't exist in the vault, fall back to
    # default_project so images always land inside the vault, never in CWD or
    # some random code-project directory.
    if not os.path.isdir(vault_dir) and project_name != config["default_project"]:
        print(
            f"[*] Vault project '{project_name}' not found; "
            f"falling back to default project: {config['default_project']!r}"
        )
        project_name = config["default_project"]
        vault_dir    = os.path.join(vault_base, project_name)

    assets_dir = os.path.join(vault_dir, config["assets_folder"])

    # Always ensure the assets directory exists (creates vault_dir too if needed)
    os.makedirs(assets_dir, exist_ok=True)
    print(f"[*] Assets directory: {assets_dir}")

    return assets_dir, project_name


# ---------------------------------------------------------------------------
# Wikilink helpers
# ---------------------------------------------------------------------------

def build_wikilink(filepath: str, active_file: str | None, assets_folder: str) -> str:
    """
    Returns an Obsidian Wikilink for *filepath*.

    * **Classic mode** (active file known): produces a path relative to the
      directory containing the active markdown file, matching the behaviour
      of the original dendron paste-image plugin.
    * **Project mode** (workspace-level): prefixes with the configured
      assets_folder name so Obsidian resolves the link correctly.
    """
    if active_file:
        active_dir = os.path.dirname(active_file)
        rel = os.path.relpath(filepath, active_dir).replace("\\", "/")
        return f"![[{rel}]]"

    # Project / workspace mode
    filename = os.path.basename(filepath)
    if assets_folder and assets_folder != ".":
        link_path = f"{assets_folder}/{filename}"
    else:
        link_path = filename
    return f"![[{link_path}]]"


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Obsidian Paste Image — reads an image from the clipboard, saves it "
            "inside the vault, and returns an Obsidian Wikilink."
        )
    )
    parser.add_argument(
        "-w", "--workspace", type=str,
        help="Active workspace token (e.g. 20260308110646-kardenwort-mpv).",
    )
    parser.add_argument(
        "-c", "--config", type=str, default="config.ini",
        help="Path to config.ini (default: config.ini next to the script).",
    )
    parser.add_argument(
        "-n", "--name", type=str, default="pasted-image",
        help="Descriptive slug included in the saved filename.",
    )
    parser.add_argument(
        "-t", "--title", type=str,
        help="Active editor window title — used to resolve the open markdown file.",
    )
    parser.add_argument(
        "-f", "--active-file", type=str, dest="active_file",
        help="Absolute path to the markdown file currently being edited.",
    )
    args = parser.parse_args()

    # Resolve config relative to the script file so it works regardless of
    # the current working directory.
    config_path = args.config
    if not os.path.isabs(config_path):
        config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", config_path)
    config = get_config(config_path)

    # ------------------------------------------------------------------ #
    # 1. Grab image from clipboard
    # ------------------------------------------------------------------ #
    print("[*] Accessing system clipboard…")
    clipboard_content = ImageGrab.grabclipboard()

    if clipboard_content is None:
        print("[!] Error: No image found in the system clipboard.")
        sys.exit(1)

    img: Image.Image | None = None

    if isinstance(clipboard_content, list):
        # User copied a file from Explorer
        if clipboard_content and os.path.exists(clipboard_content[0]):
            try:
                img = Image.open(clipboard_content[0])
                print(f"[*] Loaded image from copied file: {clipboard_content[0]}")
            except Exception as exc:
                print(f"[!] Error loading copied file: {exc}")
                sys.exit(1)
    elif isinstance(clipboard_content, Image.Image):
        img = clipboard_content
        print("[*] Extracted raw image data from clipboard.")

    if img is None:
        print("[!] Error: Clipboard content is not a valid image.")
        sys.exit(1)

    # ------------------------------------------------------------------ #
    # 2. Build filename  (ZID-slug.png)
    # ------------------------------------------------------------------ #
    zid       = datetime.now().strftime("%Y%m%d%H%M%S")
    safe_slug = re.sub(r"[^a-zA-Z0-9-]", "", args.name.lower().replace(" ", "-"))
    filename  = f"{zid}-{safe_slug}.png"

    # ------------------------------------------------------------------ #
    # 3. Resolve target assets directory
    # ------------------------------------------------------------------ #
    vault_base  = config["vault_base"]
    active_file = args.active_file

    if active_file:
        if os.path.isfile(active_file):
            # Classic mode only applies when the active file is INSIDE the vault.
            # If the user is editing a code file / config / terminal outside the
            # vault, skip classic mode so we don't scatter assets into random dirs.
            norm_active = os.path.normcase(os.path.abspath(active_file))
            norm_vault  = os.path.normcase(os.path.abspath(vault_base))
            if norm_active.startswith(norm_vault + os.sep):
                print(f"[*] Active file inside vault: {active_file}")
            else:
                print(
                    f"[*] Active file is outside the vault ({active_file!r}); "
                    "using workspace resolution instead."
                )
                active_file = None
        else:
            print(f"[!] Warning: --active-file path does not exist: {active_file!r}. Ignoring.")
            active_file = None

    # Only scan the vault by title when --active-file was not supplied at all.
    # Scope the scan to the workspace's vault project folder so common
    # filenames (README.md, index.md, etc.) cannot match unrelated vault files.
    if active_file is None and args.active_file is None:
        ws_project: str | None = None
        if args.workspace:
            ws_project = re.sub(r"^\d{14}[-_\s]*", "", args.workspace.strip())
            ws_project = re.sub(r"\s*\(Workspace\).*", "", ws_project).strip() or None
        active_file = find_active_file(args.title, vault_base, ws_project)

    assets_dir: str | None = None

    if active_file:
        active_dir = os.path.dirname(active_file)
        assets_dir = os.path.join(active_dir, config["assets_folder"])
        os.makedirs(assets_dir, exist_ok=True)
        print(f"[*] Classic mode — assets relative to active file: {assets_dir}")
    else:
        print("[*] Falling back to workspace directory resolution.")
        assets_dir, _proj = discover_assets_dir(args.workspace, config)

    # discover_assets_dir always creates the directory (including default_project
    # fallback), so there is no need for a CWD safety net that would produce
    # broken wikilinks.

    # ------------------------------------------------------------------ #
    # 4. Guard against overwriting an existing file (same ZID = same second)
    # ------------------------------------------------------------------ #
    filepath = os.path.join(assets_dir, filename)
    if os.path.exists(filepath):
        print(f"[!] Error: File already exists and would be overwritten: {filepath}")
        print("[!] Wait one second and retry, or use --name to add a unique slug.")
        sys.exit(1)

    # ------------------------------------------------------------------ #
    # 5. Save
    # ------------------------------------------------------------------ #
    try:
        img.save(filepath, "PNG")
        print(f"[+] Saved: {filepath}")
    except Exception as exc:
        print(f"[!] Error saving image: {exc}")
        sys.exit(1)

    # ------------------------------------------------------------------ #
    # 6. Build Wikilink and copy to clipboard
    # ------------------------------------------------------------------ #
    wikilink = build_wikilink(filepath, active_file, config["assets_folder"])

    if PYPERCLIP_AVAILABLE:
        pyperclip.copy(wikilink)
        print("[*] Wikilink copied to clipboard.")
    else:
        print("[!] Warning: pyperclip not available — could not copy to clipboard.")

    print("\n--- Output Wikilink ---")
    print(wikilink)
    print("-----------------------")


if __name__ == "__main__":
    main()
