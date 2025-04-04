import pytest
import os
from pathlib import Path
from typing import List, Optional, Dict

import pathspec # Direct import, assume it's installed
# Import the refactored functions and constants
from jinni.config_system import (
    load_rules_from_file,
    compile_spec_from_rules,
    DEFAULT_RULES, # Import to potentially check its content or use in tests
    CONTEXT_FILENAME
)

# --- Tests for load_rules_from_file ---

def test_load_rules_non_existent_file(tmp_path: Path):
    """Test loading rules from a file that does not exist."""
    non_existent_file = tmp_path / "no_such_file.rules"
    rules = load_rules_from_file(non_existent_file)
    assert rules == []

def test_load_rules_basic_file(tmp_path: Path):
    """Test loading rules from a simple file."""
    rule_file = tmp_path / "test.rules"
    content = "*.py\n!config.py\n# A comment\n\nbuild/"
    rule_file.write_text(content, encoding='utf-8')
    rules = load_rules_from_file(rule_file)
    # load_rules_from_file should return raw lines including comments/empty
    expected_lines = ["*.py", "!config.py", "# A comment", "", "build/"]
    assert rules == expected_lines

def test_load_rules_empty_file(tmp_path: Path):
    """Test loading rules from an empty file."""
    rule_file = tmp_path / "empty.rules"
    rule_file.touch()
    rules = load_rules_from_file(rule_file)
    assert rules == [] # read_text().splitlines() on empty file gives [''] which becomes [] after loop? No, splitlines() on empty string is [].

def test_load_rules_read_error(tmp_path: Path, monkeypatch):
    """Test handling of file read errors during loading."""
    rule_file = tmp_path / "unreadable.rules"
    rule_file.touch() # Create the file

    # Simulate read error
    def mock_read_text(*args, **kwargs):
        raise OSError("Permission denied")
    monkeypatch.setattr(Path, "read_text", mock_read_text)

    rules = load_rules_from_file(rule_file)
    assert rules == [] # Should return empty list on error

# --- Tests for compile_spec_from_rules ---

def test_compile_empty_list():
    """Test compiling an empty list of rules."""
    spec = compile_spec_from_rules([], "Empty List")
    assert isinstance(spec, pathspec.PathSpec)
    assert len(spec.patterns) == 0 # Should be an empty spec

def test_compile_comments_and_empty_lines():
    """Test that comments and empty lines are ignored during compilation."""
    rules = [
        "# This is a comment",
        "",
        "*.log", # Include logs
        "!important.log", # Exclude specific log
        " # Another comment",
        "",
        "src/",
        "",
    ]
    spec = compile_spec_from_rules(rules, "Comments and Empty")
    assert isinstance(spec, pathspec.PathSpec)
    # Check if patterns were correctly identified
    assert spec.match_file("debug.log")
    assert not spec.match_file("important.log") # Last match for important.log is !important.log
    assert spec.match_file("src/main.py")
    assert spec.match_file("src/") # Should match directory itself if pattern is 'src/'
    # Count valid patterns compiled
    assert len(spec.patterns) == 3 # *.log, !important.log, src/

def test_compile_basic_patterns():
    """Test compiling basic gitignore-style patterns."""
    rules = [
        "*.py",
        "!tests/",
        "docs/*.md",
        "/config.yaml",
    ]
    spec = compile_spec_from_rules(rules, "Basic Patterns")
    assert isinstance(spec, pathspec.PathSpec)
    assert spec.match_file("main.py")
    assert spec.match_file("utils/helper.py")
    assert not spec.match_file("tests/test_main.py") # Excluded by !tests/
    assert not spec.match_file("tests/")
    assert spec.match_file("docs/README.md")
    assert not spec.match_file("other/README.md") # Not matched by docs/*.md
    assert spec.match_file("config.yaml") # Anchored to root
    assert not spec.match_file("sub/config.yaml") # Anchored, shouldn't match sub

def test_compile_invalid_pattern_line():
    """Test handling of invalid lines during compilation."""
    # pathspec is generally robust, but some patterns might cause issues or be ignored.
    # An empty negation '!' is invalid.
    rules = ["*.py", "[invalid", "!"]
    spec = compile_spec_from_rules(rules, "Invalid Lines")
    # Expect an empty spec because pathspec raises error on '!'
    assert isinstance(spec, pathspec.PathSpec)
    assert len(spec.patterns) == 0

def test_compile_only_invalid_patterns():
    """Test compiling only invalid patterns."""
    rules = ["[invalid", "!"]
    spec = compile_spec_from_rules(rules, "Only Invalid")
    assert isinstance(spec, pathspec.PathSpec)
    assert len(spec.patterns) == 0

def test_default_rules_compilation():
    """Test that the default rules compile without errors."""
    # This is a basic sanity check
    spec = compile_spec_from_rules(DEFAULT_RULES, "Default Rules")
    assert isinstance(spec, pathspec.PathSpec)
    # Check a few default exclusions - .git/ pattern SHOULD match files inside
    assert not spec.match_file(".git/config") # Test that the pattern correctly excludes a file inside .git
    assert not spec.match_file("node_modules/package/index.js")
    assert not spec.match_file("__pycache__/some.cpython-39.pyc")
    # Check something not excluded by default
    assert spec.match_file("src/main.py") # Defaults include '*' first, so this should be included

# --- Remove tests for check_item and find_and_compile_contextfile ---
# All tests below this line from the original file are removed.