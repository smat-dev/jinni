# tests/test_mcp_exclusions.py
"""Integration tests for MCP server exclusion features using flat parameters."""

import pytest
import pytest_asyncio
import json
import tempfile
from pathlib import Path
from tests.conftest import run_mcp_tool_call

# Mark all tests in this module as asyncio
pytestmark = pytest.mark.asyncio


def create_project_structure(root: Path, structure: dict):
    """Create a nested directory/file structure from a dict."""
    for name, content in structure.items():
        path = root / name
        if isinstance(content, dict):
            # It's a directory
            path.mkdir(exist_ok=True)
            create_project_structure(path, content)
        else:
            # It's a file
            path.parent.mkdir(exist_ok=True, parents=True)
            path.write_text(content, encoding='utf-8')


class TestMCPExclusions:
    """Test MCP server exclusion functionality with flat parameters."""

    @pytest.fixture
    def test_project(self):
        """Create a test project structure."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)

            structure = {
                "src": {
                    "app.py": "# Application",
                    "utils.py": "# Utils",
                    "legacy": {
                        "old.py": "# Old code"
                    },
                    "tests": {
                        "test_app.py": "# App tests"
                    }
                },
                "tests": {
                    "test_integration.py": "# Integration"
                },
                "vendor": {
                    "lib.py": "# Library"
                },
                "docs": {
                    "readme.md": "# Docs"
                },
                "build": {
                    "output.js": "// Built"
                },
                "app.test.js": "// JS test",
                "util.spec.py": "# Python spec",
                "temp.log": "Log file"
            }

            create_project_structure(root, structure)
            yield root

    async def test_exclusions_global(self, test_project):
        """Test global exclusions via MCP using not_keywords parameter."""
        result = await run_mcp_tool_call(
            "read_context",
            project_root=str(test_project),
            targets=[],
            rules=[],
            list_only=True,
            not_keywords=["tests", "vendor"]
        )

        lines = result.strip().split('\n')

        # Should exclude globally
        assert not any("tests/" in line for line in lines)
        assert not any("test_" in line for line in lines)
        assert not any("vendor/" in line for line in lines)
        assert not any(".test." in line for line in lines)

        # Should include others
        assert any("src/app.py" in line for line in lines)
        assert any("docs/readme.md" in line for line in lines)

    async def test_exclusions_scoped(self, test_project):
        """Test scoped exclusions via MCP using not_in parameter."""
        result = await run_mcp_tool_call(
            "read_context",
            project_root=str(test_project),
            targets=[],
            rules=[],
            list_only=True,
            not_in=["src:legacy,tests"]
        )

        lines = result.strip().split('\n')

        # Should exclude only within src
        assert not any("src/legacy/" in line for line in lines)
        assert not any("src/tests/" in line for line in lines)

        # Should include other src files
        assert any("src/app.py" in line for line in lines)
        assert any("src/utils.py" in line for line in lines)

        # Should include tests outside src
        assert any("tests/test_integration.py" in line for line in lines)

    async def test_exclusions_patterns(self, test_project):
        """Test file pattern exclusions via MCP using not_files parameter."""
        result = await run_mcp_tool_call(
            "read_context",
            project_root=str(test_project),
            targets=[],
            rules=[],
            list_only=True,
            not_files=["*.test.*", "*.spec.*", "*.log"]
        )

        lines = result.strip().split('\n')

        # Should exclude matching patterns
        assert not any("app.test.js" in line for line in lines)
        assert not any("util.spec.py" in line for line in lines)
        assert not any("temp.log" in line for line in lines)

        # Should include others
        assert any("src/app.py" in line for line in lines)

    async def test_exclusions_combined(self, test_project):
        """Test combining all exclusion types via MCP."""
        result = await run_mcp_tool_call(
            "read_context",
            project_root=str(test_project),
            targets=[],
            rules=[],
            list_only=True,
            not_keywords=["vendor", "build"],
            not_in=["src:legacy"],
            not_files=["*.log"]
        )

        lines = result.strip().split('\n')

        # Check all exclusions work
        assert not any("vendor/" in line for line in lines)
        assert not any("build/" in line for line in lines)
        assert not any("src/legacy/" in line for line in lines)
        assert not any(".log" in line for line in lines)

        # Check inclusions
        assert any("src/app.py" in line for line in lines)
        assert any("tests/test_integration.py" in line for line in lines)

    async def test_exclusions_with_specific_targets(self, test_project):
        """Test exclusions work with specific targets."""
        result = await run_mcp_tool_call(
            "read_context",
            project_root=str(test_project),
            targets=["src"],
            rules=[],
            list_only=True,
            not_keywords=["tests"]
        )

        lines = result.strip().split('\n')

        # Should only process src, excluding tests within it
        assert any("src/app.py" in line for line in lines)
        assert not any("src/tests/" in line for line in lines)

        # Should not include anything outside src
        assert not any("vendor/" in line for line in lines)
        assert not any("docs/" in line for line in lines)

    async def test_exclusions_with_rules(self, test_project):
        """Test exclusions work together with rules."""
        result = await run_mcp_tool_call(
            "read_context",
            project_root=str(test_project),
            targets=[],
            rules=["!**/legacy/**"],  # Exclude legacy
            list_only=True,
            not_keywords=["vendor"]
        )

        lines = result.strip().split('\n')

        # Should apply both rules and exclusions
        assert any("src/app.py" in line for line in lines)
        assert any("src/utils.py" in line for line in lines)

        # Excluded by rules
        assert not any("legacy/" in line for line in lines)

        # Excluded by exclusions
        assert not any("vendor/" in line for line in lines)

    async def test_exclusions_empty(self, test_project):
        """Test that no exclusion parameters has same effect as defaults."""
        result_without = await run_mcp_tool_call(
            "read_context",
            project_root=str(test_project),
            targets=[],
            rules=[],
            list_only=True
        )

        # Just verify it returns successfully
        lines = result_without.strip().split('\n')
        assert len(lines) > 0

    async def test_exclusions_debug_mode(self, test_project):
        """Test debug mode shows exclusion information."""
        result = await run_mcp_tool_call(
            "read_context",
            project_root=str(test_project),
            targets=[],
            rules=[],
            list_only=True,
            debug_explain=True,
            not_keywords=["tests"]
        )

        # Should contain debug information
        assert "DEBUG LOG" in result

    async def test_default_parameters(self, test_project):
        """Test that only project_root is required, other params have defaults."""
        # This should work with just project_root - targets and rules default to []
        result = await run_mcp_tool_call(
            "read_context",
            project_root=str(test_project),
            list_only=True
        )

        # Should return successfully
        lines = result.strip().split('\n')
        assert len(lines) > 0
        assert any("src/app.py" in line for line in lines)


class TestCursorCompatibility:
    """Test Cursor-specific compatibility features."""

    @pytest.fixture
    def test_project(self):
        """Create a simple test project."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "file.py").write_text("# Python file", encoding='utf-8')
            (root / "test.py").write_text("# Test file", encoding='utf-8')
            yield root

    async def test_stringified_targets_list(self, test_project):
        """Test that stringified JSON targets are parsed correctly."""
        # Simulate what Cursor might send - a stringified JSON array
        # The defensive parsing should handle this
        result = await run_mcp_tool_call(
            "read_context",
            project_root=str(test_project),
            targets='["file.py"]',  # Stringified JSON
            rules=[],
            list_only=True
        )

        # Should work despite stringified input
        assert "file.py" in result

    async def test_stringified_rules_list(self, test_project):
        """Test that stringified JSON rules are parsed correctly."""
        result = await run_mcp_tool_call(
            "read_context",
            project_root=str(test_project),
            targets=[],
            rules='["*.py"]',  # Stringified JSON
            list_only=True
        )

        # Should work despite stringified input
        assert "file.py" in result

    async def test_stringified_not_keywords(self, test_project):
        """Test that stringified not_keywords are parsed correctly."""
        # Create a test_something file that matches the pattern
        (test_project / "test_something.py").write_text("# Test", encoding='utf-8')

        result = await run_mcp_tool_call(
            "read_context",
            project_root=str(test_project),
            targets=[],
            rules=[],
            list_only=True,
            not_keywords='["tests"]'  # Stringified JSON
        )

        # Should exclude files matching test patterns (test_*)
        lines = result.strip().split('\n')
        assert not any("test_something.py" in line for line in lines)
        # But file.py should still be included
        assert any("file.py" in line for line in lines)

    async def test_single_string_targets(self, test_project):
        """Test that single string targets are wrapped in a list."""
        result = await run_mcp_tool_call(
            "read_context",
            project_root=str(test_project),
            targets="file.py",  # Single string, not a list
            rules=[],
            list_only=True
        )

        # Should work with single string
        assert "file.py" in result
