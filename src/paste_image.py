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

def get_config(config_path="config.ini"):
    """
    Loads configuration settings from config.ini, falling back to defaults if not found.
    """
    config = configparser.ConfigParser()
    if os.path.exists(config_path):
        config.read(config_path, encoding="utf-8")
    
    # Defaults
    vault_base = config.get("Obsidian", "vault_base", fallback=r"U:\voothi.vault")
    default_project = config.get("Obsidian", "default_project", fallback="default")
    assets_folder_name = config.get("Obsidian", "assets_folder", fallback="assets")
    
    return {
        "vault_base": vault_base,
        "default_project": default_project,
        "assets_folder": assets_folder_name
    }

def discover_assets_dir(workspace, config):
    """
    Infers the correct assets directory in the vault using the workspace name.
    """
    vault_base = config["vault_base"]
    
    if workspace:
        # Strip any leading ZID and trailing info to get the project directory name
        project_name = workspace.strip()
        project_name = re.sub(r'^\d{14}[-_\s]*', '', project_name)
        project_name = re.sub(r'\s*\(Workspace\).*', '', project_name).strip()
    else:
        project_name = config["default_project"]
        
    vault_dir = os.path.join(vault_base, project_name)
    assets_dir = os.path.join(vault_dir, config["assets_folder"])
    
    # Create the assets folder if the project vault directory exists
    if os.path.exists(vault_dir) and not os.path.exists(assets_dir):
        os.makedirs(assets_dir, exist_ok=True)
        print(f"[*] Created assets directory: {assets_dir}")
        
    return assets_dir, project_name

def find_active_file(title, vault_base):
    """
    Finds the active markdown file path on disk by looking for a .md filename
    in the window title and searching the vault. If not found, scans the vault
    for the most recently modified .md file.
    """
    if not os.path.exists(vault_base):
        return None

    # 1. Try to find the file matching the name from the title
    if title:
        # Regex to find a markdown filename e.g. "20260529193801-but-you-can-make.md"
        match = re.search(r'([\w-]+\.md)\b', title)
        if match:
            target_name = match.group(1)
            # Scan the vault recursively for this filename
            for root, dirs, files in os.walk(vault_base):
                # Skip dotfiles/history dirs
                dirs[:] = [d for d in dirs if not d.startswith('.')]
                if target_name in files:
                    active_path = os.path.join(root, target_name)
                    print(f"[*] Found active file from window title: {active_path}")
                    return active_path
                    
    # 2. Fallback: Scan the vault recursively for the most recently modified .md file
    print("[*] Active file not found in window title. Scanning vault for the most recently modified markdown file...")
    latest_file = None
    latest_mtime = 0
    
    for root, dirs, files in os.walk(vault_base):
        dirs[:] = [d for d in dirs if not d.startswith('.')]
        for f in files:
            if f.endswith('.md'):
                fpath = os.path.join(root, f)
                try:
                    mtime = os.path.getmtime(fpath)
                    if mtime > latest_mtime:
                        latest_mtime = mtime
                        latest_file = fpath
                except Exception:
                    continue
                    
    if latest_file:
        print(f"[*] Fallback - Found most recently modified markdown file: {latest_file}")
        return latest_file
        
    return None

def main():
    parser = argparse.ArgumentParser(
        description="Obsidian Paste Image Utility - Extracts images from the clipboard, saves them inside the vault, and returns Wikilinks."
    )
    parser.add_argument("-w", "--workspace", type=str, help="Active workspace name (e.g. 20260308110646-kardenwort-mpv) to dynamically discover vault directory.")
    parser.add_argument("-c", "--config", type=str, default="config.ini", help="Path to config file.")
    parser.add_argument("-n", "--name", type=str, default="pasted-image", help="Optional description slug to include in the filename.")
    parser.add_argument("-t", "--title", type=str, help="Active editor window title to resolve currently active markdown file path.")
    parser.add_argument("-f", "--active-file", type=str, help="Path to the active markdown file being edited.")
    
    args = parser.parse_args()
    config = get_config(args.config)
    
    # 1. Grab image from clipboard
    print("[*] Accessing system clipboard...")
    clipboard_content = ImageGrab.grabclipboard()
    
    if clipboard_content is None:
        print("[!] Error: No image found in system clipboard.")
        sys.exit(1)
        
    # Handle case where user copied an image file from file explorer (returns a list of file paths)
    img = None
    if isinstance(clipboard_content, list):
        if clipboard_content and os.path.exists(clipboard_content[0]):
            try:
                img = Image.open(clipboard_content[0])
                print(f"[*] Loaded image from copied file: {clipboard_content[0]}")
            except Exception as e:
                print(f"[!] Error loading copied file: {e}")
                sys.exit(1)
    elif isinstance(clipboard_content, Image.Image):
        img = clipboard_content
        print("[*] Extracted raw image data from clipboard.")
        
    if img is None:
        print("[!] Error: Clipboard content is not a valid image.")
        sys.exit(1)
        
    # 2. Save the image with unique ZID
    zid = datetime.now().strftime("%Y%m%d%H%M%S")
    safe_slug = re.sub(r'[^a-zA-Z0-9-]', '', args.name.lower().replace(" ", "-"))
    filename = f"{zid}-{safe_slug}.png"

    # 3. Discover target assets folder (Main: Active File classic way, Fallback: workspace base)
    vault_base = config["vault_base"]
    
    active_file = args.active_file
    if active_file and os.path.exists(active_file):
        print(f"[*] Found active file from direct parameter: {active_file}")
    else:
        active_file = find_active_file(args.title, vault_base)
    
    assets_dir = None
    if active_file:
        active_dir = os.path.dirname(active_file)
        assets_dir = os.path.join(active_dir, config["assets_folder"])
        os.makedirs(assets_dir, exist_ok=True)
        print(f"[*] Classic Mode - Saving relative to active file: {assets_dir}")
    else:
        # Fallback to project-level base assets folder
        print("[!] Active file could not be determined. Falling back to workspace directory resolution.")
        assets_dir, project_name = discover_assets_dir(args.workspace, config)
    
    if not assets_dir or not os.path.exists(assets_dir):
        # Fallback to current working directory
        assets_dir = os.path.abspath(".")
        print(f"[*] Saving image to current directory instead: {assets_dir}")
        
    filepath = os.path.join(assets_dir, filename)
    
    try:
        # Save as PNG
        img.save(filepath, "PNG")
        print(f"[+] Successfully saved image to: {filepath}")
    except Exception as e:
        print(f"[!] Error saving image file: {e}")
        sys.exit(1)
        
    # 4. Generate Obsidian Wikilink
    # Use relative subfolder path if config assets_folder is specified
    if config["assets_folder"] and config["assets_folder"] != ".":
        link_path = os.path.join(config["assets_folder"], filename).replace("\\", "/")
    else:
        link_path = filename
        
    wikilink = f"![[{link_path}]]"
    
    # Copy link back to clipboard
    if PYPERCLIP_AVAILABLE:
        pyperclip.copy(wikilink)
        print("[*] Formatted Wikilink copied back to system clipboard.")
    else:
        print("[!] Warning: Pyperclip not available, could not write back to clipboard.")
        
    print("\n--- Output Wikilink ---")
    print(wikilink)
    print("-----------------------")

if __name__ == "__main__":
    main()
