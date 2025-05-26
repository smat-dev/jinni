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
    assert "```path=file_root.txt" in stdout
    assert "Root file content" in stdout
    assert "```path=README.md" in stdout
    assert "# Readme" in stdout
    assert "```path=main.py" in stdout # Included by default '*'
    assert "```path=src/app.py" in stdout # Included via root src/
    assert "print('app')" in stdout
    assert "```path=src/utils.py" in stdout # Included via root src/
    assert "def helper(): pass" in stdout
    assert "```path=src/nested/deep.py" in stdout # Included via root src/
    assert "# Deep" in stdout
    assert "```path=dir_a/important.log" in stdout # Included by local override of root !*.log
    assert "Important Log Content" in stdout
    assert "```path=dir_c/file_c1.txt" in stdout # Included via root dir_c/
    assert "Content C1" in stdout
    assert "```path=dir_f/file_f.txt" in stdout # Included via root dir_f/
    assert "```path=docs/index.md" in stdout # Included via root *.md
    assert "```path=docs/config/options.md" in stdout # Included via root *.md

    # Check excluded content
    assert "root.log" not in stdout # Excluded by root !*.log
    assert "temp.tmp" not in stdout # Excluded by root !*.tmp
    assert ".hidden_root_file" not in stdout # Excluded by default .*
    assert "binary_file.bin" not in stdout # Binary file
    assert "dir_a/file_a1.txt" not in stdout # Excluded locally by !file_a1.txt
    assert "dir_a/file_a2.log" not in stdout # Excluded by root !*.log
    assert "dir_a/local.md" not in stdout # Excluded locally by !local.md
    assert "```path=dir_b/file_b1.py" in stdout # dir_b included by default '*'
    assert "```path=dir_b/sub_dir_b/include_me.txt" in stdout # dir_b included by default '*'
    assert "dir_c/file_c2.data" not in stdout # Excluded locally by !*.data
    assert "```path=dir_d/file_d.txt" in stdout # dir_d included by default '*'
    assert "dir_e/last_rule.txt" not in stdout # Excluded locally by !last_rule.txt
    assert "src/config.log" not in stdout # Excluded by root !*.log
    assert "src/nested/data.log" not in stdout # Excluded by root !*.log
    assert ".hidden_dir" not in stdout # Excluded by default .*
    assert "```path=.contextfiles" not in stdout # Excluded by default .*
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
        "src/nested/other.txt", # Add missing file
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
        "**/*.py\n"    # Include python files recursively
        "!main.py\n"   # But exclude main.py at the root
        "dir_b/\n"     # Include dir_b
        "lib/**\n"     # Explicitly include lib/ and its contents
        "README.md\n"  # Include README
        "src/\n"       # Explicitly include src directory for traversal
    , encoding='utf-8'
    )
    # Use --overrides with project root
    stdout, stderr = run_jinni_cli(["-r", str(test_dir), "--overrides", str(overrides_path), "--no-copy", "--debug-explain"])

    # Expected includes based on contextfiles + override rules + defaults:
    # Contextfiles include: file_root.txt, *.md, main.py, src/, dir_c/, dir_e/, dir_f/
    # Overrides add: **/*.py, !main.py, dir_b/, lib/**, README.md, src/
    # Defaults exclude: .*, build/, etc.

    # Check included
    assert "```path=README.md" in stdout # Included by override
    assert "```path=src/app.py" in stdout # Included by override **/*.py
    assert "```path=src/utils.py" in stdout # Included by override **/*.py
    assert "```path=src/nested/deep.py" in stdout # Included by override **/*.py
    assert "```path=dir_b/file_b1.py" in stdout # Included by override **/*.py and dir_b/
    assert "```path=lib/somelib.py" in stdout # Included by override **/*.py (and lib/ inclusion)

    # Check excluded
    assert "```path=main.py" not in stdout # Excluded by override !main.py
    # With the new design, .contextfiles are still respected when using overrides
    assert "```path=file_root.txt" in stdout # Included by .contextfiles
    assert "```path=dir_a/important.log" in stdout # Included by .contextfiles in dir_a
    assert "```path=dir_c/file_c1.txt" in stdout # Included by .contextfiles (dir_c/)
    assert "```path=dir_f/file_f.txt" in stdout # Included by .contextfiles (dir_f/)
    assert "```path=docs/index.md" in stdout # Included by .contextfiles (*.md matches at any depth)
    assert "config.yaml" not in stdout # Not included by override rules
    assert ".env" not in stdout # Excluded by default
    assert "build/" not in stdout # Excluded by default

    # Check stderr for debug info, but not for critical errors
    assert "INFO:jinni.core_logic:Override rules provided as high-priority additions to normal rules." in stderr
    assert "DEBUG:jinni.context_walker:Active spec patterns:" in stderr
    assert "DEBUG:jinni.context_walker:FILE MATCH CHECK:" in stderr

def test_cli_debug_explain(test_environment: Path):
    """Test the --debug-explain CLI flag with dynamic rules."""
    test_dir = test_environment
    stdout, stderr = run_jinni_cli(["-r", str(test_dir), "--debug-explain"])

    # Check stderr for expected explanation patterns (may need adjustment based on exact logging)
    # Look for dynamic spec source descriptions
    assert "DEBUG:jinni.context_walker:Compiled spec for" in stderr # Check for log from context_walker
    assert "from Default+Gitignore+Contextfiles at root" in stderr  # Root context
    assert "from Default+Gitignore+Contextfiles up to ./src" in stderr  # Src context
    assert "from Default+Gitignore+Contextfiles up to ./dir_a" in stderr  # Dir_a context

    # Check specific inclusion/exclusion reasons based on the dynamic context
    # Check for the log message from the context walker module
    assert "DEBUG:jinni.context_walker:Including File:" in stderr
    assert "DEBUG:jinni.context_walker:Excluding File:" in stderr # Check context_walker logger
    assert "DEBUG:jinni.context_walker:Pruning Directory" in stderr # Check context_walker logger

    # Example specific checks (adapt based on actual log output)
    assert "Including File: " in stderr and "file_root.txt" in stderr and "Default+Gitignore+Contextfiles at root" in stderr
    assert "Excluding File: " in stderr and "root.log" in stderr and "Default+Gitignore+Contextfiles at root" in stderr
    assert "Including File: " in stderr and "src/app.py" in stderr and "Default+Gitignore+Contextfiles up to ./src" in stderr
    assert "Excluding File: " in stderr and "dir_a/file_a1.txt" in stderr and "Default+Gitignore+Contextfiles up to ./dir_a" in stderr
    assert "Including File: " in stderr and "dir_a/important.log" in stderr and "Default+Gitignore+Contextfiles up to ./dir_a" in stderr
    assert "Keeping Directory: " in stderr and "dir_b" in stderr and "Default+Gitignore+Contextfiles at root" in stderr

    # Check stdout is still correct (same as test_cli_with_contextfiles)
    assert "```path=file_root.txt" in stdout
    assert "```path=src/app.py" in stdout
    assert "```path=dir_b/file_b1.py" in stdout # Should be included by default '*'

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
    assert "```path=src/app.py" in stdout_root # Relative to root

    # Run with project root set to test_dir/src, target is app.py (relative to CWD, resolves inside root)
    stdout_src, _ = run_jinni_cli(["-r", str(test_dir / "src"), str(test_dir / "src" / "app.py")]) # Pass absolute path for target
    assert "```path=app.py" in stdout_src # Relative to root (which is src)
    assert "```path=src/app.py" not in stdout_src

    # Run with project root set to test_dir.parent, target is project/src/app.py
    stdout_parent, _ = run_jinni_cli(["-r", str(test_dir.parent), str(test_dir / "src/app.py")])
    assert f"```path={test_dir.name}/src/app.py" in stdout_parent # Relative to root (parent)


def test_cli_target_dir_uses_project_rules(test_environment: Path):
    """Test CLI targeting a dir within project uses project root rules."""
    test_dir = test_environment
    # Root rule excludes utils.py
    (test_dir / CONTEXT_FILENAME).write_text("!**/utils.py", encoding='utf-8')
    # Local rule in src excludes data.json
    (test_dir / "src" / CONTEXT_FILENAME).write_text("!data.json", encoding='utf-8')

    # Run targeting the src directory, with project root set to test_dir
    stdout, stderr = run_jinni_cli(["-r", str(test_dir), str(test_dir / "src"), "--debug-explain"])

    # Expected behavior: src is within project root, so rules start from project root
    # Expected includes:
    # - app.py (included by default *)
    # - nested/deep.py (included by default *)
    # - nested/other.txt (included by default *)
    # Expected excludes:
    # - utils.py (excluded by root !**/utils.py)
    # - data.json (excluded by src/.contextfiles !data.json)
    # - .hidden_in_src (excluded by default !.*)

    # Check included
    assert "```path=src/app.py" in stdout
    assert "```path=src/nested/deep.py" in stdout
    assert "```path=src/nested/other.txt" in stdout

    # Check excluded
    assert "```path=src/utils.py" not in stdout # Excluded by root rule
    assert "```path=src/data.json" not in stdout # Excluded by local rule
    assert "```path=src/.hidden_in_src" not in stdout # Excluded by default rule

    # Check files outside target are not included
    assert "```path=main.py" not in stdout
    assert "```path=README.md" not in stdout

    # assert stderr.strip() == "" # Removed assertion as debug logs are expected


def test_cli_target_dot_directory(test_environment: Path):
    """Test targeting a dot-directory directly includes its non-dot files."""
    test_dir = test_environment
    target_dot_dir = test_dir / ".testdir"

    # Run targeting the .testdir directory, with project root set to test_dir
    stdout, stderr = run_jinni_cli(["-r", str(test_dir), str(target_dot_dir)])

    # Expected includes:
    # - yes (included by default '*' rule applied within .testdir)
    # Expected excludes:
    # - .nope (excluded by default '!.*' rule applied within .testdir)

    # Check included
    assert f"```path={target_dot_dir.name}/yes" in stdout # Path relative to root
    assert "it worked" in stdout

    # Check excluded
    assert f"```path={target_dot_dir.name}/.nope" not in stdout

    # Check files outside target are not included
    assert "```path=main.py" not in stdout
    assert "```path=README.md" not in stdout

    assert stderr.strip() == ""

@pytest.mark.skip(reason="Cannot test NUL handling in CLI subprocess: Python/OS will reject argument before app code runs")
def test_cli_nul_in_path_triggers_valueerror(test_environment: Path):
    """Test that a path with an embedded NUL triggers a clean ValueError and does not crash."""
    test_dir = test_environment
    # Insert a NUL in the path
    bad_path = str(test_dir) + "\x00bad"
    import sys
    from conftest import run_jinni_cli
    import pytest
    with pytest.raises(SystemExit):
        stdout, stderr = run_jinni_cli([bad_path, "--no-copy"])
        assert "Embedded NUL" in stderr or "\x00" in stderr

def test_cli_list_token(test_environment: Path):
    """Test the --list-token CLI flag."""
    test_dir = test_environment
    # Run with the project directory as the root, no specific target
    stdout, stderr = run_jinni_cli(["-r", str(test_dir), "-L", "--no-copy"])

    # Expected files are the same as test_cli_list_only
    expected_files_base = sorted([
        "README.md",
        "file_root.txt",
        "main.py",
        "dir_a/important.log",
        "dir_b/file_b1.py",
        "dir_b/sub_dir_b/include_me.txt",
        "dir_c/file_c1.txt",
        "dir_d/file_d.txt",
        "dir_f/file_f.txt",
        "lib/somelib.py",
        "src/app.py",
        "src/nested/deep.py",
        "src/utils.py",
        "docs/index.md",
        "docs/config/options.md",
        "src/nested/other.txt",
    ])

    lines = stdout.strip().splitlines()
    # Check the file lines (ignoring exact token count, just check format)
    output_files = []
    total_tokens = 0
    for line in lines[:-2]: # Exclude separator and total
        assert ":" in line
        assert "tokens" in line
        path_part = line.split(":")[0].strip()
        token_part = line.split(":")[1].strip().split()[0]
        output_files.append(path_part)
        assert token_part.isdigit() # Check token count is a number
        total_tokens += int(token_part)

    assert sorted(output_files) == expected_files_base

    # Check the separator and total line
    assert lines[-2] == "---"
    assert lines[-1].startswith("Total:")
    assert f"{total_tokens} tokens" in lines[-1]

    # Check stderr contains only the expected INFO log, not errors
    assert "INFO:jinni.core_logic:Processed" in stderr
    assert "ERROR" not in stderr
    assert "WARNING" not in stderr