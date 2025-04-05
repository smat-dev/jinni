from pathlib import Path
from conftest import run_jinni_cli, CONTEXT_FILENAME # Import helper and constant
import pytest # Import pytest for fixture usage if needed later

# --- CLI Tests (Synchronous) ---

def test_cli_with_contextfiles(test_environment: Path):
    """Test CLI run respecting hierarchical .contextfiles (dynamic rule application)."""
    test_dir = test_environment
    # Run with the project directory as the root, no specific target
    stdout, stderr = run_jinni_cli(["-r", str(test_dir), "--no-copy"])

    # Expected includes based on conftest.py setup and dynamic rules:
    # Root .contextfiles: file_root.txt, *.md, src/, dir_c/, dir_e/, dir_f/, !*.log, !*.tmp
    # dir_a .contextfiles: *.txt, !file_a1.txt, important.log, !local.md
    # dir_c .contextfiles: !*.data
    # dir_e .contextfiles: !last_rule.txt
    # Defaults exclude: .*, build/, etc.

    # Check included content
    assert "File: file_root.txt" in stdout
    assert "Root file content" in stdout
    assert "File: README.md" in stdout
    assert "# Readme" in stdout
    assert "File: main.py" in stdout # Included by default '*'
    assert "File: src/app.py" in stdout # Included via root src/
    assert "print('app')" in stdout
    assert "File: src/utils.py" in stdout # Included via root src/
    assert "def helper(): pass" in stdout
    assert "File: src/nested/deep.py" in stdout # Included via root src/
    assert "# Deep" in stdout
    assert "File: dir_a/important.log" in stdout # Included by local override of root !*.log
    assert "Important Log Content" in stdout
    assert "File: dir_c/file_c1.txt" in stdout # Included via root dir_c/
    assert "Content C1" in stdout
    assert "File: dir_f/file_f.txt" in stdout # Included via root dir_f/
    assert "File: docs/index.md" in stdout # Included via root *.md
    assert "File: docs/config/options.md" in stdout # Included via root *.md

    # Check excluded content
    assert "root.log" not in stdout # Excluded by root !*.log
    assert "temp.tmp" not in stdout # Excluded by root !*.tmp
    assert ".hidden_root_file" not in stdout # Excluded by default .*
    assert "binary_file.bin" not in stdout # Binary file
    assert "dir_a/file_a1.txt" not in stdout # Excluded locally by !file_a1.txt
    assert "dir_a/file_a2.log" not in stdout # Excluded by root !*.log
    assert "dir_a/local.md" not in stdout # Excluded locally by !local.md
    assert "File: dir_b/file_b1.py" in stdout # dir_b included by default '*'
    assert "File: dir_b/sub_dir_b/include_me.txt" in stdout # dir_b included by default '*'
    assert "dir_c/file_c2.data" not in stdout # Excluded locally by !*.data
    assert "File: dir_d/file_d.txt" in stdout # dir_d included by default '*'
    assert "dir_e/last_rule.txt" not in stdout # Excluded locally by !last_rule.txt
    assert "src/config.log" not in stdout # Excluded by root !*.log
    assert "src/nested/data.log" not in stdout # Excluded by root !*.log
    assert ".hidden_dir" not in stdout # Excluded by default .*
    assert ".contextfiles" not in stdout # Excluded by default .*
    assert "build/" not in stdout # Excluded by default build/

    assert stderr.strip() == ""

def test_cli_list_only(test_environment: Path):
    """Test the --list-only CLI flag with dynamic rules."""
    test_dir = test_environment
    stdout, stderr = run_jinni_cli(["-r", str(test_dir), "--list-only", "--no-copy"])

    expected_files = sorted([
        "README.md",
        "file_root.txt",
        "main.py", # Included by default '*'
        "dir_a/important.log",
        "dir_b/file_b1.py", # Included by default '*'
        "dir_b/sub_dir_b/include_me.txt", # Included by default '*'
        "dir_c/file_c1.txt", # .contextfiles in dir_c should be excluded by default
        "dir_d/file_d.txt", # Included by default '*'
        "dir_f/file_f.txt", # .contextfiles in dir_f should be excluded by default
        "lib/somelib.py", # Included by default '*' now that it exists
        "src/app.py", # .hidden_in_src should be excluded by default
        "src/nested/deep.py",
        "src/utils.py",
        "docs/index.md",
        "docs/config/options.md",
    ])
    actual_files = sorted([line.strip() for line in stdout.strip().splitlines()])
    assert actual_files == expected_files, f"Expected {expected_files}, got {actual_files}"
    assert stderr.strip() == ""

def test_cli_overrides(test_environment: Path): # Renamed from test_cli_global_config
    """Test the --overrides CLI flag."""
    test_dir = test_environment
    overrides_path = test_dir / "override.rules"
    overrides_path.write_text(
        "# Override Rules\n"
        "*.py\n"       # Include python files
        "!main.py\n"   # But exclude main.py
        "dir_b/\n"     # Include dir_b
        "lib/**\n"     # Explicitly include lib/ and its contents
        "README.md\n"  # Include README
        , encoding='utf-8'
    )
    # Use --overrides with project root
    stdout, stderr = run_jinni_cli(["-r", str(test_dir), "--overrides", str(overrides_path), "--no-copy"])

    # Expected includes based ONLY on override rules + defaults:
    # Overrides: *.py, !main.py, dir_b/, README.md
    # Defaults exclude: .*, build/, etc.

    # Check included
    assert "File: README.md" in stdout # Included by override
    assert "File: src/app.py" in stdout # Included by override *.py
    assert "File: src/utils.py" in stdout # Included by override *.py
    assert "File: src/nested/deep.py" in stdout # Included by override *.py
    assert "File: dir_b/file_b1.py" in stdout # Included by override *.py and dir_b/
    assert "File: lib/somelib.py" in stdout # Included by override *.py (and lib/ inclusion)

    # Check excluded
    assert "File: main.py" not in stdout # Excluded by override !main.py
    assert "File: file_root.txt" not in stdout # Excluded because .contextfiles are ignored by overrides
    assert "File: dir_a/important.log" not in stdout # Excluded because .contextfiles are ignored by overrides
    assert "File: dir_c/file_c1.txt" not in stdout # Excluded because .contextfiles are ignored by overrides
    assert "File: dir_f/file_f.txt" not in stdout # Excluded because .contextfiles are ignored by overrides
    assert "File: docs/index.md" not in stdout # Excluded because .contextfiles are ignored by overrides
    assert "config.yaml" not in stdout # Not included by override rules
    assert ".env" not in stdout # Excluded by default
    assert "build/" not in stdout # Excluded by default

    # Check stderr doesn't contain critical errors (lines starting with ERROR: or containing Traceback),
    # allowing for warnings/debug from binary detection.
    for line in stderr.splitlines():
        line_lower = line.lower()
        assert not line_lower.startswith("error:"), f"stderr contained line starting with 'error:': {line}"
        assert "traceback" not in line_lower, f"stderr contained 'traceback': {line}"

def test_cli_debug_explain(test_environment: Path):
    """Test the --debug-explain CLI flag with dynamic rules."""
    test_dir = test_environment
    stdout, stderr = run_jinni_cli(["-r", str(test_dir), "--debug-explain"])

    # Check stderr for expected explanation patterns (may need adjustment based on exact logging)
    # Look for dynamic spec source descriptions
    assert "DEBUG:jinni.context_walker:Compiled spec for" in stderr # Check for log from context_walker
    assert "from Context files at root" in stderr # Root context (Updated assertion)
    assert "from Context files up to ./src" in stderr # Src context
    assert "from Context files up to ./dir_a" in stderr # Dir_a context

    # Check specific inclusion/exclusion reasons based on the dynamic context
    # Check for the log message from the context walker module
    assert "DEBUG:jinni.context_walker:Including File:" in stderr
    assert "DEBUG:jinni.context_walker:Excluding File:" in stderr # Check context_walker logger
    assert "DEBUG:jinni.context_walker:Pruning Directory" in stderr # Check context_walker logger

    # Example specific checks (adapt based on actual log output)
    assert "Including File: " in stderr and "file_root.txt" in stderr and "Context files at root" in stderr # Corrected assertion
    assert "Excluding File: " in stderr and "root.log" in stderr and "Context files at root" in stderr # Excluded by root !*.log (Corrected assertion)
    assert "Including File: " in stderr and "src/app.py" in stderr and "Context files up to ./src" in stderr # Included by root src/
    assert "Excluding File: " in stderr and "dir_a/file_a1.txt" in stderr and "Context files up to ./dir_a" in stderr # Excluded by dir_a !file_a1.txt
    assert "Including File: " in stderr and "dir_a/important.log" in stderr and "Context files up to ./dir_a" in stderr # Included by dir_a important.log
    assert "Keeping Directory: " in stderr and "dir_b" in stderr and "Context files at root" in stderr # Kept because included by default '*' at root (Corrected assertion)

    # Check stdout is still correct (same as test_cli_with_contextfiles)
    assert "File: file_root.txt" in stdout
    assert "File: src/app.py" in stdout
    assert "File: dir_b/file_b1.py" in stdout # Should be included by default '*'

# Test removed as CLI now takes only one optional target
# def test_cli_multi_path_input(test_environment: Path):

# (Content removed)

def test_cli_project_root(test_environment: Path):
    """Test the -r/--root flag."""
    test_dir = test_environment
    # Include just src/app.py for simplicity
    (test_dir / CONTEXT_FILENAME).write_text("src/app.py", encoding='utf-8')

    # Run with project root set to test_dir, target is src/app.py
    stdout_root, _ = run_jinni_cli(["-r", str(test_dir), str(test_dir / "src/app.py")])
    assert "File: src/app.py" in stdout_root # Relative to root

    # Run with project root set to test_dir/src, target is app.py (relative to CWD, resolves inside root)
    stdout_src, _ = run_jinni_cli(["-r", str(test_dir / "src"), str(test_dir / "src" / "app.py")]) # Pass absolute path for target
    assert "File: app.py" in stdout_src # Relative to root (which is src)
    assert "File: src/app.py" not in stdout_src

    # Run with project root set to test_dir.parent, target is project/src/app.py
    stdout_parent, _ = run_jinni_cli(["-r", str(test_dir.parent), str(test_dir / "src/app.py")])
    assert f"File: {test_dir.name}/src/app.py" in stdout_parent # Relative to root (parent)