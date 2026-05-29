import os
import sys
import unittest
import shutil
import re
from unittest.mock import patch, MagicMock
from PIL import Image

# Add src folder to import path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))

from paste_image import get_config, discover_assets_dir, find_active_file

class TestPasteImage(unittest.TestCase):
    
    def setUp(self):
        self.config = {
            "vault_base": "mock_vault_base",
            "default_project": "default-project",
            "assets_folder": "assets"
        }
        os.makedirs(self.config["vault_base"], exist_ok=True)
        
    def tearDown(self):
        if os.path.exists(self.config["vault_base"]):
            shutil.rmtree(self.config["vault_base"])

    def test_discover_assets_dir_with_workspace(self):
        """
        Verify that discover_assets_dir infers project vault and assets folder
        dynamically from active Antigravity workspace window tokens.
        """
        # Create mock project folder
        project_dir = os.path.join(self.config["vault_base"], "kardenwort-mpv")
        os.makedirs(project_dir, exist_ok=True)
        
        # Test workspace with leading ZID
        workspace_token = "20260308110646-kardenwort-mpv"
        assets_dir, project_name = discover_assets_dir(workspace_token, self.config)
        
        self.assertEqual(project_name, "kardenwort-mpv")
        self.assertEqual(
            os.path.abspath(assets_dir), 
            os.path.abspath(os.path.join(project_dir, "assets"))
        )
        # Ensure the assets directory was automatically created on disk
        self.assertTrue(os.path.exists(assets_dir))

    def test_discover_assets_dir_fallback(self):
        """
        Verify that discover_assets_dir falls back gracefully to default settings
        when no active workspace is passed.
        """
        assets_dir, project_name = discover_assets_dir(None, self.config)
        self.assertEqual(project_name, "default-project")
        self.assertEqual(
            os.path.abspath(assets_dir), 
            os.path.abspath(os.path.join(self.config["vault_base"], "default-project", "assets"))
        )

    def test_find_active_file_by_title(self):
        """
        Verify that find_active_file correctly parses a markdown filename
        from a window title and scans the vault to find it.
        """
        project_dir = os.path.join(self.config["vault_base"], "kardenwort-mpv")
        conversations_dir = os.path.join(project_dir, "conversations")
        os.makedirs(conversations_dir, exist_ok=True)
        
        target_file = os.path.join(conversations_dir, "20260529193801-but-you-can-make.md")
        with open(target_file, "w", encoding="utf-8") as f:
            f.write("# Hello")
            
        title = "20260529193801-but-you-can-make.md - 20260308110646-kardenwort-mpv - Antigravity IDE"
        active_path = find_active_file(title, self.config["vault_base"])
        
        self.assertIsNotNone(active_path)
        self.assertEqual(os.path.abspath(active_path), os.path.abspath(target_file))

    def test_find_active_file_by_recent_modification(self):
        """
        Verify that find_active_file falls back to scanning the vault for the
        most recently modified markdown file when no title matches.
        """
        project_dir = os.path.join(self.config["vault_base"], "kardenwort-mpv")
        conversations_dir = os.path.join(project_dir, "conversations")
        os.makedirs(conversations_dir, exist_ok=True)
        
        file1 = os.path.join(conversations_dir, "20260529120000-old.md")
        file2 = os.path.join(conversations_dir, "20260529130000-recent.md")
        
        # Write files with offset modification times
        with open(file1, "w", encoding="utf-8") as f:
            f.write("old")
        os.utime(file1, (1000000, 1000000))
        
        with open(file2, "w", encoding="utf-8") as f:
            f.write("recent")
        os.utime(file2, (2000000, 2000000))
        
        # No matching window title passed
        active_path = find_active_file(None, self.config["vault_base"])
        
        self.assertIsNotNone(active_path)
        self.assertEqual(os.path.abspath(active_path), os.path.abspath(file2))

if __name__ == '__main__':
    unittest.main()
