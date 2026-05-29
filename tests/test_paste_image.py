"""
Tests for the Obsidian Paste Image Utility.

Coverage
--------
get_config            — defaults and INI overrides
discover_assets_dir   — workspace-name parsing, auto-creation, fallback
find_active_file      — title-based scan, recent-file fallback, missing vault
build_wikilink        — classic (active-file relative) and project modes
main() integration    — overwrite guard, --active-file param, clipboard image
"""

import os
import sys
import time
import shutil
import tempfile
import unittest
from unittest.mock import patch, MagicMock, PropertyMock
from PIL import Image

# Make src importable regardless of the working directory
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from paste_image import (
    get_config,
    discover_assets_dir,
    find_active_file,
    build_wikilink,
    main,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_tiny_png(path: str) -> None:
    """Creates a 4×4 black PNG at *path*."""
    img = Image.new("RGB", (4, 4), color=(0, 0, 0))
    img.save(path, "PNG")


class BaseVaultTest(unittest.TestCase):
    """Provides a fresh temporary vault for each test and tears it down."""

    def setUp(self):
        self.vault = tempfile.mkdtemp(prefix="test_vault_")
        self.config = {
            "vault_base":      self.vault,
            "default_project": "default-project",
            "assets_folder":   "assets",
        }

    def tearDown(self):
        shutil.rmtree(self.vault, ignore_errors=True)

    def _make_md(self, *rel_parts: str) -> str:
        """Creates an empty .md file at vault/<rel_parts> and returns the path."""
        path = os.path.join(self.vault, *rel_parts)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write("# Test\n")
        return path


# ---------------------------------------------------------------------------
# get_config
# ---------------------------------------------------------------------------

class TestGetConfig(unittest.TestCase):

    def test_defaults_without_ini(self):
        """Returns safe defaults when no config file exists."""
        cfg = get_config("/nonexistent/config.ini")
        self.assertEqual(cfg["vault_base"], r"U:\voothi.vault")
        self.assertEqual(cfg["default_project"], "default")
        self.assertEqual(cfg["assets_folder"], "assets")

    def test_reads_ini_values(self):
        """Correctly reads all three keys from an existing INI file."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".ini", delete=False, encoding="utf-8"
        ) as f:
            f.write("[Obsidian]\nvault_base = Z:\\my_vault\ndefault_project = my-proj\nassets_folder = img\n")
            ini_path = f.name

        try:
            cfg = get_config(ini_path)
            self.assertEqual(cfg["vault_base"], r"Z:\my_vault")
            self.assertEqual(cfg["default_project"], "my-proj")
            self.assertEqual(cfg["assets_folder"], "img")
        finally:
            os.unlink(ini_path)

    def test_partial_ini_keeps_defaults(self):
        """Missing keys in INI fall back to defaults."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".ini", delete=False, encoding="utf-8"
        ) as f:
            f.write("[Obsidian]\nvault_base = X:\\vault\n")
            ini_path = f.name

        try:
            cfg = get_config(ini_path)
            self.assertEqual(cfg["vault_base"], r"X:\vault")
            self.assertEqual(cfg["default_project"], "default")
        finally:
            os.unlink(ini_path)


# ---------------------------------------------------------------------------
# discover_assets_dir
# ---------------------------------------------------------------------------

class TestDiscoverAssetsDir(BaseVaultTest):

    def test_workspace_with_zid_prefix(self):
        """Strips 14-digit ZID prefix and resolves project assets folder."""
        project_dir = os.path.join(self.vault, "kardenwort-mpv")
        os.makedirs(project_dir)

        assets_dir, project_name = discover_assets_dir(
            "20260308110646-kardenwort-mpv", self.config
        )

        self.assertEqual(project_name, "kardenwort-mpv")
        self.assertEqual(
            os.path.normcase(os.path.abspath(assets_dir)),
            os.path.normcase(os.path.abspath(os.path.join(project_dir, "assets"))),
        )
        # Auto-created
        self.assertTrue(os.path.isdir(assets_dir))

    def test_workspace_with_workspace_suffix(self):
        """Handles 'X (Workspace)' suffix from the Antigravity title bar."""
        project_dir = os.path.join(self.vault, "kardenwort-mpv")
        os.makedirs(project_dir)

        _, project_name = discover_assets_dir(
            "20260308110646-kardenwort-mpv (Workspace)", self.config
        )
        self.assertEqual(project_name, "kardenwort-mpv")

    def test_fallback_no_workspace(self):
        """Returns default_project path when workspace is None."""
        assets_dir, project_name = discover_assets_dir(None, self.config)
        self.assertEqual(project_name, "default-project")
        expected = os.path.join(self.vault, "default-project", "assets")
        self.assertEqual(
            os.path.normcase(os.path.abspath(assets_dir)),
            os.path.normcase(os.path.abspath(expected)),
        )

    def test_creates_assets_even_when_project_dir_missing(self):
        """
        Assets directory is always created, even if the vault project dir
        did not exist beforehand. This ensures images never land in CWD.
        """
        assets_dir, _ = discover_assets_dir(
            "20260308110646-nonexistent-project", self.config
        )
        # Falls back to default_project and creates the directory
        self.assertTrue(os.path.isdir(assets_dir))

    def test_falls_back_to_default_project_when_workspace_missing(self):
        """
        When the workspace-derived project has no folder in the vault,
        discover_assets_dir silently falls back to default_project.
        """
        assets_dir, project_name = discover_assets_dir(
            "20260308110646-not-a-real-project", self.config
        )
        self.assertEqual(project_name, "default-project")
        expected = os.path.join(self.vault, "default-project", "assets")
        self.assertEqual(
            os.path.normcase(os.path.abspath(assets_dir)),
            os.path.normcase(os.path.abspath(expected)),
        )
        self.assertTrue(os.path.isdir(assets_dir))


# ---------------------------------------------------------------------------
# find_active_file
# ---------------------------------------------------------------------------

class TestFindActiveFile(BaseVaultTest):

    def test_resolves_from_window_title(self):
        """Finds the correct .md file when its name appears in the title."""
        target = self._make_md("kardenwort-mpv", "conversations",
                               "20260529193801-my-note.md")

        title = "20260529193801-my-note.md - 20260308110646-kardenwort-mpv - Antigravity IDE"
        found = find_active_file(title, self.vault, "kardenwort-mpv")

        self.assertIsNotNone(found)
        self.assertEqual(
            os.path.normcase(os.path.abspath(found)),
            os.path.normcase(os.path.abspath(target)),
        )

    def test_returns_none_when_no_title_given(self):
        """
        Returns None immediately when no title is provided.
        The 'most recently modified .md' scan has been removed to prevent
        random, unrelated file locations being used as save targets.
        """
        self._make_md("proj", "conversations", "20260101-old.md")
        self._make_md("proj", "conversations", "20260601-new.md")

        result = find_active_file(None, self.vault)
        self.assertIsNone(result)

    def test_returns_none_for_missing_vault(self):
        """Returns None gracefully when vault_base does not exist."""
        result = find_active_file(None, "/totally/missing/path")
        self.assertIsNone(result)

    def test_returns_none_when_title_has_no_md_filename(self):
        """
        Returns None when the window title contains no .md filename.
        No fallback scan is performed.
        """
        self._make_md("proj", "note.md")
        result = find_active_file("Some random window title without md", self.vault)
        self.assertIsNone(result)

    def test_returns_none_when_md_not_found_in_vault(self):
        """Returns None when the .md filename from the title is not in the vault."""
        result = find_active_file(
            "nonexistent-note.md - kardenwort-mpv - Antigravity IDE",
            self.vault,
            "kardenwort-mpv",
        )
        self.assertIsNone(result)

    def test_scoped_to_project_folder(self):
        """
        When project_name is given, only that project's vault folder is searched.
        A file with the same name in a different vault project is NOT returned.
        """
        # Same filename in two different vault projects
        correct = self._make_md("kardenwort-mpv", "conversations", "my-note.md")
        _wrong  = self._make_md("other-project",  "conversations", "my-note.md")

        title = "my-note.md - 20260308110646-kardenwort-mpv - Antigravity IDE"
        found = find_active_file(title, self.vault, "kardenwort-mpv")

        self.assertIsNotNone(found)
        self.assertEqual(
            os.path.normcase(os.path.abspath(found)),
            os.path.normcase(os.path.abspath(correct)),
        )

    def test_common_filename_in_code_workspace_returns_none(self):
        """
        The scenario that caused the seeds/dendron.templates bug:
        editing README.md in a code project (not in the vault) while the
        vault happens to contain a README.md somewhere else.
        project_name='obsidian-paste-image' has no vault folder → returns None.
        """
        # Vault contains a README.md in an unrelated location
        self._make_md("seeds", "dendron.templates", "README.md")

        title = "20260529201233-obsidian-paste-image · Antigravity IDE - README.md"
        # project_name derived from workspace token
        found = find_active_file(title, self.vault, "obsidian-paste-image")
        self.assertIsNone(found)

    def test_ignores_hidden_directories_during_title_scan(self):
        """The vault scan skips dotfile directories when searching by title."""
        _hidden_md = self._make_md(".obsidian", "target-note.md")
        visible_md = self._make_md("proj",      "target-note.md")

        title = "target-note.md - kardenwort-mpv - Antigravity IDE"
        found = find_active_file(title, self.vault, "proj")

        self.assertIsNotNone(found)
        self.assertEqual(
            os.path.normcase(os.path.abspath(found)),
            os.path.normcase(os.path.abspath(visible_md)),
        )


# ---------------------------------------------------------------------------
# build_wikilink
# ---------------------------------------------------------------------------

class TestBuildWikilink(BaseVaultTest):

    def test_classic_mode_relative_path(self):
        """In classic mode the link is relative to the active file's directory."""
        active_file = self._make_md("conversations", "my-note.md")
        assets_dir  = os.path.join(self.vault, "conversations", "assets")
        os.makedirs(assets_dir, exist_ok=True)
        image_path  = os.path.join(assets_dir, "20260529123456-pasted-image.png")

        link = build_wikilink(image_path, active_file, "assets")

        self.assertEqual(link, "![[assets/20260529123456-pasted-image.png]]")

    def test_project_mode_uses_assets_prefix(self):
        """Without an active file the link uses the configured assets prefix."""
        image_path = os.path.join(self.vault, "assets", "20260529123456-pasted-image.png")

        link = build_wikilink(image_path, None, "assets")

        self.assertEqual(link, "![[assets/20260529123456-pasted-image.png]]")

    def test_project_mode_no_assets_folder(self):
        """When assets_folder is empty the link is just the filename."""
        image_path = os.path.join(self.vault, "20260529123456-img.png")

        link = build_wikilink(image_path, None, "")

        self.assertEqual(link, "![[20260529123456-img.png]]")

    def test_classic_mode_subfolder(self):
        """Classic mode works even when assets are in a nested subfolder."""
        active_file = self._make_md("a", "b", "note.md")
        assets_dir  = os.path.join(self.vault, "a", "b", "assets")
        os.makedirs(assets_dir, exist_ok=True)
        image_path  = os.path.join(assets_dir, "20260529123456-img.png")

        link = build_wikilink(image_path, active_file, "assets")

        self.assertIn("assets/20260529123456-img.png", link)


# ---------------------------------------------------------------------------
# Integration — main() via CLI args
# ---------------------------------------------------------------------------

class TestMainIntegration(BaseVaultTest):
    """
    Integration tests for the main() CLI entry-point.
    PIL.ImageGrab.grabclipboard is mocked to avoid needing a real clipboard.
    pyperclip is mocked to avoid clipboard writes during tests.
    """

    def _make_config_ini(self) -> str:
        """Writes a config.ini pointing at self.vault and returns its path."""
        ini_path = os.path.join(self.vault, "config.ini")
        with open(ini_path, "w", encoding="utf-8") as f:
            f.write(
                f"[Obsidian]\n"
                f"vault_base = {self.vault}\n"
                f"default_project = default-project\n"
                f"assets_folder = assets\n"
            )
        return ini_path

    def _make_clipboard_image(self):
        img = Image.new("RGB", (4, 4), color=(255, 0, 0))
        return img

    def test_active_file_param_saves_relative(self):
        """--active-file causes the image to land in assets/ next to that file."""
        active_file = self._make_md("conversations", "my-note.md")
        ini         = self._make_config_ini()
        img         = self._make_clipboard_image()

        with patch("paste_image.ImageGrab.grabclipboard", return_value=img), \
             patch("paste_image.pyperclip", create=True) as mock_clip:

            mock_clip.copy = MagicMock()
            sys.argv = [
                "paste_image.py",
                "--config", ini,
                "--active-file", active_file,
            ]
            main()

        assets_dir = os.path.join(os.path.dirname(active_file), "assets")
        self.assertTrue(os.path.isdir(assets_dir))
        pngs = [f for f in os.listdir(assets_dir) if f.endswith(".png")]
        self.assertEqual(len(pngs), 1)

    def test_overwrite_guard_exits_with_error(self):
        """If the target file already exists main() exits with code 1."""
        active_file = self._make_md("conversations", "note.md")
        ini         = self._make_config_ini()
        assets_dir  = os.path.join(os.path.dirname(active_file), "assets")
        os.makedirs(assets_dir, exist_ok=True)

        img = self._make_clipboard_image()

        # Patch datetime so both calls produce the identical ZID → same filename
        fixed_dt = MagicMock()
        fixed_dt.strftime.return_value = "20260529120000"

        with patch("paste_image.ImageGrab.grabclipboard", return_value=img), \
             patch("paste_image.datetime") as mock_dt, \
             patch("paste_image.pyperclip", create=True):

            mock_dt.now.return_value = fixed_dt
            sys.argv = [
                "paste_image.py",
                "--config", ini,
                "--active-file", active_file,
            ]
            main()  # first call — should succeed

        with patch("paste_image.ImageGrab.grabclipboard", return_value=img), \
             patch("paste_image.datetime") as mock_dt, \
             patch("paste_image.pyperclip", create=True):

            mock_dt.now.return_value = fixed_dt
            sys.argv = [
                "paste_image.py",
                "--config", ini,
                "--active-file", active_file,
            ]
            with self.assertRaises(SystemExit) as ctx:
                main()  # second call with identical ZID — must fail

            self.assertEqual(ctx.exception.code, 1)

    def test_active_file_outside_vault_falls_back_to_workspace(self):
        """
        When --active-file points to a file outside the vault (e.g. a config.ini
        in a code project), classic mode is skipped and workspace resolution is
        used instead. This prevents images scattering into unrelated directories.
        """
        # Create a project dir inside the vault for workspace resolution to find
        project_dir = os.path.join(self.vault, "kardenwort-mpv")
        os.makedirs(project_dir, exist_ok=True)
        ini = self._make_config_ini()
        img = self._make_clipboard_image()

        # active_file is OUTSIDE the vault (simulate editing config.ini in a code project)
        outside_file = os.path.join(tempfile.gettempdir(), "some-project", "config.ini")
        os.makedirs(os.path.dirname(outside_file), exist_ok=True)
        with open(outside_file, "w") as f:
            f.write("[section]\nkey = value\n")

        try:
            with patch("paste_image.ImageGrab.grabclipboard", return_value=img), \
                 patch("paste_image.pyperclip", create=True):

                sys.argv = [
                    "paste_image.py",
                    "--config", ini,
                    "--active-file", outside_file,
                    "--workspace", "20260308110646-kardenwort-mpv",
                ]
                main()  # should not crash

            # Image must land in the workspace project assets, NOT next to config.ini
            assets_dir = os.path.join(project_dir, "assets")
            self.assertTrue(os.path.isdir(assets_dir))
            pngs = [f for f in os.listdir(assets_dir) if f.endswith(".png")]
            self.assertEqual(len(pngs), 1)

            # config.ini directory must NOT have an assets folder
            outside_assets = os.path.join(os.path.dirname(outside_file), "assets")
            self.assertFalse(os.path.exists(outside_assets))
        finally:
            shutil.rmtree(os.path.dirname(outside_file), ignore_errors=True)

    def test_no_image_in_clipboard_exits_with_error(self):
        """Exits with code 1 when the clipboard has no image."""
        ini = self._make_config_ini()

        with patch("paste_image.ImageGrab.grabclipboard", return_value=None):
            sys.argv = ["paste_image.py", "--config", ini]
            with self.assertRaises(SystemExit) as ctx:
                main()
            self.assertEqual(ctx.exception.code, 1)

    def test_workspace_param_derives_vault_project(self):
        """--workspace resolves to the correct project assets directory."""
        project_dir = os.path.join(self.vault, "kardenwort-mpv")
        os.makedirs(project_dir)
        ini = self._make_config_ini()
        img = self._make_clipboard_image()

        with patch("paste_image.ImageGrab.grabclipboard", return_value=img), \
             patch("paste_image.pyperclip", create=True):

            sys.argv = [
                "paste_image.py",
                "--config", ini,
                "--workspace", "20260308110646-kardenwort-mpv",
            ]
            main()

        assets_dir = os.path.join(project_dir, "assets")
        self.assertTrue(os.path.isdir(assets_dir))
        pngs = [f for f in os.listdir(assets_dir) if f.endswith(".png")]
        self.assertEqual(len(pngs), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
