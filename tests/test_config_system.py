import unittest
import tempfile
import os
from pathlib import Path

# Import the actual functions from the implementation module
from jinni.config_system import parse_rules, check_item, RuleCache # Assuming check_item handles file reading internally

class TestConfigSystemParsing(unittest.TestCase):

    def test_parse_empty_string(self):
        """Test parsing an empty string."""
        # No need to create a file, just parse empty content
        rules = parse_rules("")
        self.assertEqual(rules, [])

    def test_parse_comments_and_empty_lines(self):
        """Test that comments and empty lines are ignored when parsing content."""
        content = """
# This is a comment

!*.log
# Another comment

include_this.txt

        """
        # Parse the string content directly
        rules = parse_rules(content)
        # Expected: only the valid rules are returned
        self.assertCountEqual(rules, [('exclude', '*.log'), ('include', 'include_this.txt')])

    def test_parse_basic_rules(self):
        """Test parsing basic include and exclude rules from content."""
        content = """
!*.pyc
*.py
!temp/
config.json
        """
        # Parse the string content directly
        rules = parse_rules(content)
        expected_rules = [
            ('exclude', '*.pyc'),
            ('include', '*.py'),
            ('exclude', 'temp/'),
            ('include', 'config.json')
        ]
        self.assertCountEqual(rules, expected_rules)

# Add more test cases for parsing edge cases later


# (Dummy check_item function removed, will use imported version)

class TestConfigSystemHierarchy(unittest.TestCase):

    def setUp(self):
        """Create a temporary directory structure for hierarchy tests."""
        self.test_dir = tempfile.TemporaryDirectory()
        self.root_path = Path(self.test_dir.name)

        # Create structure for hierarchy tests:
        # root/
        #   .contextfiles (!*.log, sub/*_include_root.txt)
        #   file_root.txt (include - no rules)
        #   skip_default.log (exclude - rule in root)
        #   .hidden_file (exclude - default hidden)
        #   .git/ (exclude - default dir)
        #     config
        #   sub/
        #     .contextfiles (!file_sub.txt)
        #     file_sub.txt (exclude - rule in sub)
        #     file_sub_include_root.txt (include - rule in root)
        #     subsub/
        #       file_subsub.txt (include - no rules)

        (self.root_path / "sub" / "subsub").mkdir(parents=True, exist_ok=True)
        (self.root_path / ".git").mkdir(exist_ok=True)

        (self.root_path / ".contextfiles").write_text("!*.log\nsub/*_include_root.txt\n", encoding='utf-8')
        (self.root_path / "file_root.txt").touch()
        (self.root_path / "skip_default.log").touch()
        (self.root_path / ".hidden_file").touch()
        (self.root_path / ".git" / "config").touch()

        (self.root_path / "sub" / ".contextfiles").write_text("!file_sub.txt\n", encoding='utf-8')
        (self.root_path / "sub" / "file_sub.txt").touch()
        (self.root_path / "sub" / "file_sub_include_root.txt").touch()

        (self.root_path / "sub" / "subsub" / "file_subsub.txt").touch()
        # Initialize cache for each test method if needed, or pass None
        self.cache: RuleCache = {}


    def tearDown(self):
        """Clean up the temporary directory."""
        self.test_dir.cleanup()

    def test_default_exclusions(self):
        """Test that default exclusions work (e.g., .git, hidden files)."""
        # Use the imported check_item
        self.assertFalse(check_item(self.root_path / ".git" / "config", self.root_path, contextfile_cache=self.cache), ".git/config should be excluded")
        self.assertFalse(check_item(self.root_path / ".git", self.root_path, contextfile_cache=self.cache), ".git dir should be excluded")
        self.assertFalse(check_item(self.root_path / ".hidden_file", self.root_path, contextfile_cache=self.cache), ".hidden_file should be excluded")


    def test_root_contextfile_exclusion(self):
        """Test exclusion rule in root .contextfiles."""
        # Use the imported check_item
        self.assertFalse(check_item(self.root_path / "skip_default.log", self.root_path, contextfile_cache=self.cache), "*.log should be excluded by root .contextfiles")

    def test_sub_contextfile_exclusion(self):
        """Test exclusion rule in subdirectory .contextfiles."""
        # Use the imported check_item
        self.assertFalse(check_item(self.root_path / "sub" / "file_sub.txt", self.root_path, contextfile_cache=self.cache), "file_sub.txt should be excluded by sub/.contextfiles")

    def test_root_contextfile_inclusion(self):
        """Test inclusion rule in root .contextfiles applying to subdirectory."""
        # Use the imported check_item
        self.assertTrue(check_item(self.root_path / "sub" / "file_sub_include_root.txt", self.root_path, contextfile_cache=self.cache), "file_sub_include_root.txt should be included by root .contextfiles")

    def test_no_rule_match_inclusion(self):
        """Test that files with no matching rules are included by default."""
        # Use the imported check_item
        self.assertTrue(check_item(self.root_path / "sub" / "subsub" / "file_subsub.txt", self.root_path, contextfile_cache=self.cache), "file_subsub.txt should be included as no rules match")
        self.assertTrue(check_item(self.root_path / "file_root.txt", self.root_path, contextfile_cache=self.cache), "file_root.txt should be included as no rules match")

    # --- Tests for Inline/Global Rules (Add later once basic hierarchy works) ---
    # def test_inline_rule_overrides_contextfile(self): ...
    # def test_global_rule_overrides_default(self): ...
    # def test_contextfile_overrides_global(self): ...


if __name__ == '__main__':
    unittest.main()