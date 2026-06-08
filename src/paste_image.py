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
    config = configparser.ConfigParser(interpolation=None)
    if os.path.exists(config_path):
        config.read(config_path, encoding="utf-8")

    return {
        "vault_base":      config.get("Obsidian", "vault_base",      fallback=r"U:\voothi.vault"),
        "default_project": config.get("Obsidian", "default_project", fallback="default"),
        "assets_folder":   config.get("Obsidian", "assets_folder",   fallback="assets"),
        "auto_create_project": config.getboolean("Obsidian", "auto_create_project", fallback=False),
        "name_template":   config.get("Obsidian", "name_template",   fallback="%Y%m%d%H%M%S-{name}"),
    }


# ---------------------------------------------------------------------------
# Active-file resolution helpers
# ---------------------------------------------------------------------------

def normalize_workspace_name(
    workspace: str | None,
    vault_base: str | None = None,
    auto_create_project: bool = False,
) -> str | None:
    """
    Normalizes a workspace token/title to a vault project name,
    resolving the correct project candidate for both VS Code and Antigravity IDE.
    """
    if not workspace:
        return None

    # If it matches an existing project directory directly, return it
    if vault_base and os.path.isdir(os.path.join(vault_base, workspace)):
        return workspace

    suffixes = [
        "Visual Studio Code",
        "VS Code",
        "VSCodium",
        "Cursor",
        "Antigravity",
        "Angigravity",
        "Code - OSS",
        "Obsidian",
    ]

    is_obsidian = bool(re.search(r'\s*-\s*Obsidian\b', workspace, re.IGNORECASE))
    parts = [p.strip() for p in workspace.split(" - ") if p.strip()]

    # Extract all possible ZID-prefixed workspace tokens
    tokens = re.findall(r"\d{14}-[\w-]+", workspace)
    if is_obsidian and parts:
        note_title = parts[0]
        tokens = [t for t in tokens if t != note_title]

    candidates = list(reversed(tokens)) if tokens else []

    # Split workspace by " - " and filter out IDE suffixes and filenames
    for idx, p in enumerate(parts):
        if is_obsidian and idx == 0:
            continue
        if vault_base and p.lower() == os.path.basename(vault_base).lower():
            continue
        is_suffix = False
        for suffix in suffixes:
            if suffix.lower() in p.lower():
                is_suffix = True
                break
        if is_suffix:
            continue
        clean_part = re.sub(r"\.code-workspace$", "", p, flags=re.IGNORECASE).strip()
        clean_part = re.sub(r"\.md$", "", clean_part, flags=re.IGNORECASE).strip()
        if clean_part and clean_part not in candidates:
            candidates.append(clean_part)

    # Fallback to the original title
    if not is_obsidian:
        candidates.append(workspace)

    seen_candidates = set()
    project_name = None

    for candidate in candidates:
        norm = candidate.strip()
        norm = re.sub(r"^\d{14}[-_\s]*", "", norm)
        norm = re.sub(r"\s*\(Workspace\).*", "", norm).strip()
        norm = re.sub(r"\.code-workspace$", "", norm, flags=re.IGNORECASE).strip()
        norm = re.sub(r"\.md$", "", norm, flags=re.IGNORECASE).strip()

        if not norm or norm in seen_candidates:
            continue
        seen_candidates.add(norm)

        # Check if the candidate is a file (ends with extension in original title)
        is_file = bool(re.search(re.escape(candidate) + r"\.[a-zA-Z0-9]+", workspace, re.IGNORECASE))

        # Check folder presence in vault
        potential_dir = os.path.join(vault_base, norm) if vault_base else None
        if potential_dir and os.path.isdir(potential_dir):
            project_name = norm
            print(f"[*] Workspace Focus - Selected project '{project_name}' from candidate '{candidate}'.")
            break
        if auto_create_project and not is_file:
            project_name = norm
            print(f"[*] Workspace Focus - Selected project '{project_name}' (will auto-create) from candidate '{candidate}'.")
            break

    # If no candidate could be resolved, fall back to the normalized first candidate
    # that is not a file (to avoid selecting a markdown/python file as project).
    if not project_name and candidates:
        fallback_candidate = None
        for candidate in candidates:
            is_file = bool(re.search(re.escape(candidate) + r"\.[a-zA-Z0-9]+", workspace, re.IGNORECASE))
            if not is_file:
                fallback_candidate = candidate
                break
        if not fallback_candidate:
            fallback_candidate = candidates[0]

        norm = fallback_candidate.strip()
        norm = re.sub(r"^\d{14}[-_\s]*", "", norm)
        norm = re.sub(r"\s*\(Workspace\).*", "", norm).strip()
        norm = re.sub(r"\.code-workspace$", "", norm, flags=re.IGNORECASE).strip()
        norm = re.sub(r"\.md$", "", norm, flags=re.IGNORECASE).strip()
        project_name = norm

    return project_name or None

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
    If *title* contains a full absolute ``*.md`` path inside the vault,
    use it directly. Otherwise, filename-based scans are performed only when
    *project_name* is supplied, scoped to ``vault_base/project_name/``.
    This prevents common filenames such as ``README.md`` from matching
    unrelated files in other vault projects.

    When *project_name* is given but has no corresponding folder in the
    vault the function returns ``None`` immediately (the workspace is a
    code-project, not a vault-project; workspace resolution will handle it).

    Returns ``None`` when no match is found.
    """
    if not os.path.isdir(vault_base):
        return None

    if not title:
        return None

    # Accept an absolute markdown path from the title if available.
    abs_match = re.search(r"([A-Za-z]:\\[^\x00-\x1F`\"*<>?|]+\.md)", title)
    if abs_match:
        candidate_abs = abs_match.group(1)
        if os.path.isfile(candidate_abs):
            norm_candidate = os.path.normcase(os.path.abspath(candidate_abs))
            norm_vault = os.path.normcase(os.path.abspath(vault_base))
            if norm_candidate.startswith(norm_vault + os.sep):
                print(f"[*] Active file resolved from absolute path in title: {candidate_abs}")
                return candidate_abs

    # ZID global discovery: if the title contains a ZID-prefixed token, search vault_base globally.
    zid_match = re.search(r"\b(\d{14}-[\w-]+)", title)
    if zid_match:
        target_name = zid_match.group(1)
        if not target_name.lower().endswith(".md"):
            target_name += ".md"
        for root, dirs, files in os.walk(vault_base):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            if target_name in files:
                found = os.path.join(root, target_name)
                print(f"[*] Active file resolved globally via ZID from window title: {found}")
                return found

    # Reliability guard: avoid unscoped global filename scans across all vaults.
    if not project_name:
        print("[*] No scoped workspace project for title scan — skipping filename vault scan.")
        return None

    # Capture a markdown filename token from the title, including common spaces
    # and punctuation used in note names.
    match = re.search(r"([^\\/:*?\"<>|\r\n]+\.md)\b", title, re.IGNORECASE)
    if not match:
        print("[*] No .md filename found in window title — skipping vault scan.")
        return None

    target_name = match.group(1).strip()

    # Scope the search to the project folder when we know which vault project
    # the workspace belongs to.  This stops generic names like README.md from
    # picking up files in unrelated vault subdirectories.
    search_root = os.path.join(vault_base, project_name)
    if not os.path.isdir(search_root):
        print(
            f"[*] Vault project '{project_name}' has no folder in vault "
            "— skipping title scan."
        )
        return None

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

    project_name = normalize_workspace_name(
        workspace,
        vault_base=vault_base,
        auto_create_project=config.get("auto_create_project", False)
    ) or config["default_project"]

    vault_dir = os.path.join(vault_base, project_name)

    # If the workspace-derived project doesn't exist in the vault, fall back to
    # default_project so images always land inside the vault, never in CWD or
    # some random code-project directory.
    # However, if auto_create_project is enabled, we create the project folder
    # directly instead of falling back.
    if not os.path.isdir(vault_dir) and project_name != config["default_project"]:
        if config.get("auto_create_project", False):
            print(
                f"[*] Vault project '{project_name}' not found; "
                f"auto-creating project folder in vault_base."
            )
        else:
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
    Returns an Obsidian Wikilink for *filepath*, using the clean base filename
    without any folder path prefix, matching Obsidian's shortest path format.
    """
    filename = os.path.basename(filepath)
    return f"![[{filename}]]"


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
    # 2. Build filename using name_template
    # ------------------------------------------------------------------ #
    now = datetime.now()
    template = config.get("name_template", "%Y%m%d%H%M%S-{name}")
    safe_slug = re.sub(r"[^a-zA-Z0-9-]", "", args.name.lower().replace(" ", "-"))
    
    # Format standard strftime patterns, then replace the {name} placeholder
    formatted_name = now.strftime(template).replace("{name}", safe_slug)
    
    # Ensure it ends with .png extension
    if not formatted_name.lower().endswith(".png"):
        filename = f"{formatted_name}.png"
    else:
        filename = formatted_name

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
        ws_project = normalize_workspace_name(
            args.workspace,
            vault_base=vault_base,
            auto_create_project=config.get("auto_create_project", False)
        )
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
