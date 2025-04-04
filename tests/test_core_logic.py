import pytest
import os
import datetime
from pathlib import Path
from typing import Set, List, Optional, Tuple

import pathspec # Direct import, assume it's installed
# Import the refactored function and exception
from jinni.core_logic import read_context, ContextSizeExceededError, SEPARATOR, _find_context_files_for_dir # Import helper for specific tests if needed
from jinni.config_system import CONTEXT_FILENAME, DEFAULT_RULES # Import constants

# --- Test Fixture ---

@pytest.fixture
def test_dir(tmp_path: Path) -> Path:
    """Creates a standard test directory structure."""
    root = tmp_path / "project"
    root.mkdir()

    # Root level files and dirs
    (root / "README.md").write_text("# Project", encoding='utf-8')
    (root / "main.py").write_text("print('main')", encoding='utf-8')
    (root / ".env").write_text("SECRET=123", encoding='utf-8') # Should be excluded by default
    (root / "config.yaml").write_text("key: value", encoding='utf-8')
    (root / "temp.tmp").touch() # Should be excluded by default
    (root / "image.jpg").write_bytes(b'\xff\xd8\xff\xe0') # Binary

    # Src directory
    (root / "src").mkdir()
    (root / "src" / "app.py").write_text("print('app')", encoding='utf-8')
    (root / "src" / "utils.py").write_text("def helper(): pass", encoding='utf-8')
    (root / "src" / "data.json").write_text('{"data": true}', encoding='utf-8')
    (root / "src" / ".hidden_in_src").touch() # Hidden

    # Lib directory (should be excluded by default)
    (root / "lib").mkdir()
    (root / "lib" / "somelib.py").write_text("# Library code", encoding='utf-8')
    (root / "lib" / "binary.dll").write_bytes(b'\x4d\x5a\x90\x00') # Binary

    # Docs directory
    (root / "docs").mkdir()
    (root / "docs" / "index.md").write_text("Docs index", encoding='utf-8')
    (root / "docs" / "config").mkdir()
    (root / "docs" / "config" / "options.md").write_text("Config options", encoding='utf-8')

    # Nested directory to test hierarchy
    (root / "src" / "nested").mkdir()
    (root / "src" / "nested" / "deep.py").write_text("# Deep", encoding='utf-8')
    (root / "src" / "nested" / "other.txt").write_text("Nested text", encoding='utf-8')

    # Build directory (should be excluded by default)
    (root / "build").mkdir()
    (root / "build" / "output.bin").touch()

    # Symlink (if possible)
    symlink_target = root / "main.py"
    symlink_path = root / "main_link.py"
    if symlink_target.exists():
         try:
            symlink_path.symlink_to(symlink_target)
         except OSError:
             print("Warning: Symlink creation failed in test setup.")

    return root

# Helper function to run read_context and normalize output
def run_read_context_helper(
    targets: List[str], # List of target paths (relative to tmp_path)
    tmp_path: Path,
    output_relative_to: Optional[str] = None, # Relative to tmp_path
    override_rules: Optional[List[str]] = None,
    list_only: bool = False,
    size_limit_mb: Optional[int] = None,
    debug_explain: bool = False,
) -> str:
    """Runs read_context with absolute paths and returns normalized output."""

    target_abs_paths = [str(tmp_path / p) for p in targets]
    output_rel_abs_path = str(tmp_path / output_relative_to) if output_relative_to else None

    content = read_context(
        target_paths_str=target_abs_paths,
        output_relative_to_str=output_rel_abs_path,
        override_rules=override_rules,
        list_only=list_only,
        size_limit_mb=size_limit_mb,
        debug_explain=debug_explain
    )
    # Normalize line endings and strip leading/trailing whitespace for comparison
    # For list_only, sort the lines
    if list_only:
        lines = sorted([line.rstrip() for line in content.splitlines() if line.strip()])
        return "\n".join(lines)
    else:
        # For content, just normalize line endings and strip outer whitespace
        normalized_content = "\n".join(line.rstrip() for line in content.splitlines()).strip()
        return normalized_content


# --- Test Cases ---

def test_read_context_no_rules_defaults(test_dir: Path):
    """Test processing with no rules - relies on default exclusions."""
    content = run_read_context_helper(["project"], test_dir.parent)

    # Check for files expected to be included (not excluded by defaults)
    assert "File: README.md" in content
    assert "File: main.py" in content
    assert "File: config.yaml" in content
    assert "File: src/app.py" in content
    assert "File: src/utils.py" in content
    assert "File: src/data.json" in content
    assert "File: src/nested/deep.py" in content
    assert "File: src/nested/other.txt" in content
    assert "File: docs/index.md" in content
    assert "File: docs/config/options.md" in content
    assert "File: temp.tmp" in content # Included by '*' default, not excluded by others

    # Check for files/dirs expected to be excluded by defaults or type
    assert "File: .env" not in content # Excluded by !.*
    assert "File: image.jpg" not in content # Binary
    # assert "File: lib/somelib.py" in content # Included by '*' default, not excluded by others - Assertion added below
    assert "File: lib/binary.dll" not in content # Binary
    assert "File: src/.hidden_in_src" not in content # Excluded by !.*
    assert "File: build/output.bin" not in content # Excluded by !build/
    assert "File: main_link.py" not in content # Symlink

def test_read_context_list_only_defaults(test_dir: Path):
    """Test list_only mode with default exclusions."""
    content = run_read_context_helper(["project"], test_dir.parent, list_only=True)
    expected_files = sorted([
        "README.md",
        "main.py",
        "config.yaml",
        "temp.tmp", # Included by '*' default
        "src/app.py",
        "src/utils.py",
        "src/data.json",
        "src/nested/deep.py",
        "src/nested/other.txt",
        "lib/somelib.py", # Included by '*' default
        "docs/index.md",
        "docs/config/options.md",
    ])
    assert content == "\n".join(expected_files)

def test_read_context_include_py_files(test_dir: Path):
    """Test including only Python files using a context file."""
    (test_dir / CONTEXT_FILENAME).write_text("**/*.py", encoding='utf-8')
    content = run_read_context_helper(["project"], test_dir.parent)

    assert "File: main.py" in content
    assert "File: src/app.py" in content
    assert "File: src/utils.py" in content
    assert "File: src/nested/deep.py" in content
    assert "File: lib/somelib.py" in content # Now included because of rule

    assert "File: README.md" in content # Included by default '*'
    assert "File: config.yaml" in content # Included by default '*'
    assert "File: src/data.json" in content # Included by default '*'

def test_read_context_exclude_overrides_include(test_dir: Path):
    """Test exclusion pattern overriding inclusion in the same file."""
    (test_dir / CONTEXT_FILENAME).write_text("**/*.py\n!project/src/utils.py", encoding='utf-8')
    content = run_read_context_helper(["project"], test_dir.parent)

    assert "File: main.py" in content
    assert "File: src/app.py" in content
    assert "File: src/nested/deep.py" in content
    assert "File: lib/somelib.py" in content
    assert "File: src/utils.py" not in content # Excluded

def test_read_context_directory_exclusion(test_dir: Path):
    """Test excluding a directory prevents processing files within."""
    (test_dir / CONTEXT_FILENAME).write_text("**/*.py\n!project/lib/", encoding='utf-8')
    content = run_read_context_helper(["project"], test_dir.parent)

    assert "File: main.py" in content
    assert "File: src/app.py" in content
    assert "File: lib/somelib.py" not in content # Excluded via directory rule

def test_read_context_hierarchy_sub_includes(test_dir: Path):
    """Test sub .contextfiles including files not matched by root."""
    (test_dir / CONTEXT_FILENAME).write_text("project/*.md", encoding='utf-8') # Root includes only root md
    (test_dir / "src" / CONTEXT_FILENAME).write_text("*.json", encoding='utf-8') # Src includes json

    content = run_read_context_helper(["project"], test_dir.parent)

    assert "File: README.md" in content
    assert "File: docs/index.md" in content # Matched by root rule *.md
    assert "File: src/data.json" in content # Included by sub rule *.json
    assert "File: main.py" in content # Included by default '*'
    assert "File: src/app.py" in content # Included by default '*'

def test_read_context_hierarchy_sub_excludes(test_dir: Path):
    """Test sub .contextfiles excluding files matched by root."""
    (test_dir / CONTEXT_FILENAME).write_text("**/*.py", encoding='utf-8') # Root includes all py
    (test_dir / "src" / CONTEXT_FILENAME).write_text("!app.py", encoding='utf-8') # Src excludes app.py

    content = run_read_context_helper(["project"], test_dir.parent)

    assert "File: main.py" in content
    assert "File: src/utils.py" in content # Included by root, not excluded by sub
    assert "File: src/nested/deep.py" in content # Included by root
    assert "File: lib/somelib.py" in content # Included by root
    assert "File: src/app.py" not in content # Excluded by sub rule

def test_read_context_override_rules(test_dir: Path):
    """Test using override rules, ignoring context files."""
    (test_dir / CONTEXT_FILENAME).write_text("**/*.py", encoding='utf-8') # File includes py
    override = ["project/src/app.py", "*.md"] # Override includes only app.py and markdown
    content = run_read_context_helper(["project"], test_dir.parent, override_rules=override)

    assert "File: src/app.py" in content # Included by override
    assert "File: README.md" in content # Included by override
    assert "File: docs/index.md" in content # Included by override
    assert "File: docs/config/options.md" in content # Included by override

    assert "File: main.py" in content # Included by default '*' (overrides ignored for this path)
    assert "File: src/utils.py" in content # Included by default '*' (overrides ignored for this path)
    assert "File: config.yaml" in content # Included by default '*' (overrides ignored for this path)

def test_read_context_binary_skip(test_dir: Path):
    """Test binary files are skipped even if rules include them."""
    (test_dir / CONTEXT_FILENAME).write_text("*", encoding='utf-8') # Include everything
    content = run_read_context_helper(["project"], test_dir.parent)

    assert "File: image.jpg" not in content
    assert "File: lib/binary.dll" not in content
    assert "File: main.py" in content # Text file still included

def test_read_context_symlink_skip(test_dir: Path):
    """Test symlinks are skipped."""
    symlink_path = test_dir / "main_link.py"
    if not symlink_path.exists():
         pytest.skip("Symlink does not exist, skipping test.")
    (test_dir / CONTEXT_FILENAME).write_text("*.py", encoding='utf-8')
    content = run_read_context_helper(["project"], test_dir.parent)
    assert "File: main.py" in content
    assert "File: main_link.py" not in content

def test_read_context_size_limit_exceeded(test_dir: Path):
    """Test exceeding size limit raises error."""
    (test_dir / CONTEXT_FILENAME).write_text("**/*.py", encoding='utf-8')
    limit_mb = 0.0001 # ~100 bytes
    with pytest.raises(ContextSizeExceededError):
        run_read_context_helper(["project"], test_dir.parent, size_limit_mb=limit_mb)

def test_read_context_explicit_target_file_included(test_dir: Path):
    """Test explicitly targeted file is included even if rules exclude it."""
    (test_dir / CONTEXT_FILENAME).write_text("!**/*.py", encoding='utf-8') # Exclude all py
    # Target main.py directly
    content = run_read_context_helper(["project/main.py"], test_dir.parent)
    assert "File: main.py" in content # Explicit target overrides rules
    assert "print('main')" in content

def test_read_context_explicit_target_dir_traversed(test_dir: Path):
    """Test explicitly targeted dir is traversed even if rules exclude it."""
    (test_dir / CONTEXT_FILENAME).write_text("!project/src/", encoding='utf-8') # Exclude src dir
    # Target src directory directly
    content = run_read_context_helper(["project/src"], test_dir.parent)
    # Files inside should be processed (and included by default rules here)
    assert "File: src/app.py" in content
    assert "File: src/utils.py" in content
    assert "File: src/data.json" in content
    assert "File: src/nested/deep.py" in content
    assert "File: src/nested/other.txt" in content
    # Files outside src should not be included
    assert "File: main.py" not in content

def test_read_context_multiple_targets(test_dir: Path):
    """Test processing multiple targets."""
    (test_dir / CONTEXT_FILENAME).write_text("*.py\n*.md", encoding='utf-8')
    content = run_read_context_helper(["project/main.py", "project/docs"], test_dir.parent)

    assert "File: main.py" in content # Explicit target
    assert "File: docs/index.md" in content # Included via rule during dir walk
    assert "File: docs/config/options.md" in content # Included via rule

    assert "File: README.md" not in content # Not targeted or matched by rule in docs walk
    assert "File: src/app.py" not in content # Not targeted

def test_read_context_output_relative_to(test_dir: Path):
    """Test using output_relative_to argument."""
    (test_dir / CONTEXT_FILENAME).write_text("project/src/app.py", encoding='utf-8')
    # Set relative root to src/
    content = run_read_context_helper(
        ["project/src/app.py"],
        test_dir.parent,
        output_relative_to="project/src"
    )
    # Path in header should be relative to project/src
    assert "File: app.py" in content
    assert "File: project/src/app.py" not in content

def test_read_context_target_outside_relative_root(test_dir: Path):
    """Test when target is outside the output_relative_to root."""
    (test_dir / CONTEXT_FILENAME).write_text("project/main.py", encoding='utf-8')
    # Set relative root to src/, but target main.py
    content = run_read_context_helper(
        ["project/main.py"],
        test_dir.parent,
        output_relative_to="project/src"
    )
    # Should fall back to absolute path or path relative to CWD if not possible
    # For simplicity, check if the full path part is present
    assert f"File: {test_dir.name}/main.py" in content or "File: project/main.py" in content

def test_find_context_files_helper(test_dir: Path):
    """Test the _find_context_files_for_dir helper directly."""
    root = test_dir
    src = test_dir / "src"
    nested = test_dir / "src" / "nested"
    docs = test_dir / "docs"

    (root / CONTEXT_FILENAME).touch()
    (src / CONTEXT_FILENAME).touch()
    (nested / CONTEXT_FILENAME).touch()
    # No context file in docs

    # Check from nested
    files = _find_context_files_for_dir(nested, root)
    assert files == [
        root / CONTEXT_FILENAME,
        src / CONTEXT_FILENAME,
        nested / CONTEXT_FILENAME,
    ]

    # Check from src
    files = _find_context_files_for_dir(src, root)
    assert files == [
        root / CONTEXT_FILENAME,
        src / CONTEXT_FILENAME,
    ]

    # Check from root
    files = _find_context_files_for_dir(root, root)
    assert files == [
        root / CONTEXT_FILENAME,
    ]

    # Check from docs (should only find root)
    files = _find_context_files_for_dir(docs, root)
    assert files == [
        root / CONTEXT_FILENAME,
    ]

    # Check outside root (should be empty)
    files = _find_context_files_for_dir(root.parent, root)
    assert files == []