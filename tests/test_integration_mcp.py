import pytest
from pathlib import Path
from mcp import types # MCP Client SDK types
from conftest import run_mcp_tool_call # Import async helper

# --- MCP Tests (Asynchronous) ---

@pytest.mark.asyncio
async def test_mcp_read_context_basic(test_environment: Path):
    """Test basic MCP read_context respecting .contextfiles (dynamic rules)."""
    test_dir = test_environment
    tool_name = "read_context"
    # Use project_root, target is None
    arguments = { "project_root": str(test_dir) }
    result = await run_mcp_tool_call(tool_name, arguments)

    assert isinstance(result, types.CallToolResult)
    assert not result.isError
    assert len(result.content) == 1 and isinstance(result.content[0], types.TextContent)
    stdout_text = result.content[0].text

    # Assertions based on the fixture's _create_test_structure rules and dynamic application
    # Root .contextfiles: file_root.txt, *.md, src/, dir_c/, dir_e/, dir_f/, !*.log, !*.tmp
    # dir_a .contextfiles: *.txt, !file_a1.txt, important.log, !local.md
    # dir_c .contextfiles: !*.data
    # dir_e .contextfiles: !last_rule.txt
    # Defaults exclude: .*, build/, etc.

    # Check included content
    assert "File: file_root.txt" in stdout_text
    assert "File: README.md" in stdout_text
    assert "File: main.py" in stdout_text # Included by default '*'
    assert "File: src/app.py" in stdout_text # Included via root src/
    assert "File: src/utils.py" in stdout_text # Included via root src/
    assert "File: src/nested/deep.py" in stdout_text # Included via root src/
    assert "File: dir_a/important.log" in stdout_text # Included by local override of root !*.log
    assert "File: dir_c/file_c1.txt" in stdout_text # Included via root dir_c/
    assert "File: dir_f/file_f.txt" in stdout_text # Included via root dir_f/
    assert "File: docs/index.md" in stdout_text # Included via root *.md
    assert "File: docs/config/options.md" in stdout_text # Included via root *.md

    # Check excluded content
    assert "root.log" not in stdout_text # Excluded by root !*.log
    assert "temp.tmp" not in stdout_text # Excluded by root !*.tmp
    assert "dir_a/file_a1.txt" not in stdout_text # Excluded locally by !file_a1.txt
    assert "File: dir_b/file_b1.py" in stdout_text # Included by default '*'
    assert "File: dir_d/file_d.txt" in stdout_text # Included by default '*'
    assert "dir_e/last_rule.txt" not in stdout_text # Excluded locally by !last_rule.txt
    assert "build/" not in stdout_text # Excluded by default


@pytest.mark.asyncio
async def test_mcp_read_context_list_only(test_environment: Path):
    """Test MCP read_context with list_only=True."""
    test_dir = test_environment
    tool_name = "read_context"
    # Use project_root, target is None
    arguments = { "project_root": str(test_dir), "list_only": True }
    result = await run_mcp_tool_call(tool_name, arguments)

    assert isinstance(result, types.CallToolResult)
    assert not result.isError
    assert len(result.content) == 1 and isinstance(result.content[0], types.TextContent)
    stdout_text = result.content[0].text
    actual_files = sorted([line.strip() for line in stdout_text.strip().splitlines()])

    expected_files = sorted([
        "README.md",
        "file_root.txt",
        "main.py", # Included by default '*'
        "dir_a/important.log",
        "dir_b/file_b1.py", # Included by default '*'
        "dir_b/sub_dir_b/include_me.txt", # Included by default '*'
        "dir_c/file_c1.txt", # .contextfiles should be excluded
        "dir_d/file_d.txt", # Included by default '*'
        "dir_f/file_f.txt", # .contextfiles should be excluded
        "lib/somelib.py", # Included by default '*' now that it exists
        "docs/config/options.md", # Included via *.md
        "docs/index.md",          # Included via *.md
        "src/app.py",             # Included via src/, .hidden_in_src excluded
        "src/nested/deep.py",     # Included via src/
        "src/utils.py",           # Included via src/
    ])
    assert actual_files == expected_files, f"Expected {expected_files}, got {actual_files}"


@pytest.mark.asyncio
async def test_mcp_read_context_inline_rules(test_environment: Path):
    """Test MCP read_context with inline rules overriding file rules."""
    test_dir = test_environment
    tool_name = "read_context"
    # Use project_root, target is None
    arguments = {
        "project_root": str(test_dir),
        "rules": [ "*.py", "!src/app.py", "lib/**" ] # Inline: include py, exclude src/app.py, include lib/**
    }
    result = await run_mcp_tool_call(tool_name, arguments)

    assert isinstance(result, types.CallToolResult)
    assert not result.isError
    assert len(result.content) == 1 and isinstance(result.content[0], types.TextContent)
    stdout_text = result.content[0].text

    # Assertions based on inline rules (override) + defaults:
    assert "File: main.py" in stdout_text # Included by inline *.py
    assert "File: src/utils.py" in stdout_text # Included by inline *.py
    assert "File: src/nested/deep.py" in stdout_text # Included by inline *.py
    assert "File: lib/somelib.py" in stdout_text # Included by inline *.py

    assert "File: src/app.py" not in stdout_text # Excluded by inline !src/app.py
    # Check files included by root file rules are NOT included now unless matched by inline *.py
    assert "File: file_root.txt" in stdout_text # Included by default '*' rule combined with overrides
    assert "File: README.md" in stdout_text # Included by default '*' rule combined with overrides
    assert "dir_a/important.log" not in stdout_text # .contextfiles ignored


@pytest.mark.asyncio
async def test_mcp_debug_explain(test_environment: Path):
    """Test MCP read_context with debug_explain=True."""
    # This test mainly verifies the tool call succeeds and returns expected content.
    # Verifying server-side logging isn't feasible with stdio_client directly.
    test_dir = test_environment
    tool_name = "read_context"
    # Use project_root, target is None
    arguments = { "project_root": str(test_dir), "debug_explain": True }
    result = await run_mcp_tool_call(tool_name, arguments)

    # Check stdout content (same as basic MCP test)
    assert isinstance(result, types.CallToolResult)
    assert not result.isError
    assert len(result.content) == 1 and isinstance(result.content[0], types.TextContent)
    stdout_text = result.content[0].text
    # Basic check for some expected content
    assert "File: file_root.txt" in stdout_text
    assert "File: src/app.py" in stdout_text
    assert "File: dir_b/file_b1.py" in stdout_text # dir_b included by default rules

@pytest.mark.asyncio
async def test_mcp_read_context_target_file(test_environment: Path):
    """Test MCP read_context targeting a single file."""
    test_dir = test_environment
    target_file = test_dir / "src" / "app.py"
    tool_name = "read_context"
    # Target the specific file within the project root
    arguments = { "project_root": str(test_dir), "target": str(target_file) }
    result = await run_mcp_tool_call(tool_name, arguments)

    assert isinstance(result, types.CallToolResult)
    assert not result.isError
    assert len(result.content) == 1 and isinstance(result.content[0], types.TextContent)
    stdout_text = result.content[0].text

    # Should only contain the targeted file (as it's explicitly targeted)
    assert "File: src/app.py" in stdout_text # Path relative to project_root
    assert "print('app')" in stdout_text
    # Ensure no other files are present
    assert "File: main.py" not in stdout_text
    assert "File: README.md" not in stdout_text