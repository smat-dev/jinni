# tests/test_mcp_exclusions.py
"""Integration tests for MCP server exclusion features."""

import pytest
import json
import tempfile
from pathlib import Path
from tests.conftest import run_mcp_tool_call


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
    """Test MCP server exclusion functionality."""
    
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
        """Test global exclusions via MCP."""
        result = await run_mcp_tool_call(
            "read_context",
            project_root=str(test_project),
            targets=[],
            rules=[],
            list_only=True,
            exclusions={
                "global": ["tests", "vendor"]
            }
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
        """Test scoped exclusions via MCP."""
        result = await run_mcp_tool_call(
            "read_context",
            project_root=str(test_project),
            targets=[],
            rules=[],
            list_only=True,
            exclusions={
                "scoped": {
                    "src": ["legacy", "tests"]
                }
            }
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
        """Test file pattern exclusions via MCP."""
        result = await run_mcp_tool_call(
            "read_context",
            project_root=str(test_project),
            targets=[],
            rules=[],
            list_only=True,
            exclusions={
                "patterns": ["*.test.*", "*.spec.*", "*.log"]
            }
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
            exclusions={
                "global": ["vendor", "build"],
                "scoped": {
                    "src": ["legacy"]
                },
                "patterns": ["*.log"]
            }
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
            exclusions={
                "global": ["tests"]
            }
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
            rules=["*.py", "!**/legacy/**"],  # Include only .py, exclude legacy
            list_only=True,
            exclusions={
                "global": ["vendor"]
            }
        )
        
        lines = result.strip().split('\n')
        
        # Should apply both rules and exclusions
        assert any("src/app.py" in line for line in lines)
        assert any("src/utils.py" in line for line in lines)
        
        # Excluded by rules
        assert not any(".js" in line for line in lines)
        assert not any(".md" in line for line in lines)
        assert not any("legacy/" in line for line in lines)
        
        # Excluded by exclusions
        assert not any("vendor/" in line for line in lines)
    
    async def test_exclusions_empty(self, test_project):
        """Test empty exclusions object has no effect."""
        result_with_empty = await run_mcp_tool_call(
            "read_context",
            project_root=str(test_project),
            targets=[],
            rules=[],
            list_only=True,
            exclusions={}
        )
        
        result_without = await run_mcp_tool_call(
            "read_context",
            project_root=str(test_project),
            targets=[],
            rules=[],
            list_only=True
        )
        
        # Results should be identical
        assert result_with_empty == result_without
    
    async def test_exclusions_with_summarize(self, test_project):
        """Test exclusions work with summarize_context tool."""
        result = await run_mcp_tool_call(
            "summarize_context",
            project_root=str(test_project),
            targets=[],
            rules=[],
            list_only=True,
            exclusions={
                "global": ["tests", "vendor"]
            }
        )
        
        lines = result.strip().split('\n')
        
        # Exclusions should work same as read_context
        assert not any("tests/" in line for line in lines)
        assert not any("vendor/" in line for line in lines)
        assert any("src/app.py" in line for line in lines)
    
    async def test_exclusions_debug_mode(self, test_project):
        """Test debug mode shows exclusion information."""
        result = await run_mcp_tool_call(
            "read_context",
            project_root=str(test_project),
            targets=[],
            rules=[],
            list_only=True,
            debug_explain=True,
            exclusions={
                "global": ["tests"]
            }
        )
        
        # Should contain debug information
        assert "DEBUG LOG" in result
        assert "exclusion patterns" in result.lower()
    
    async def test_exclusions_invalid_structure(self, test_project):
        """Test handling of invalid exclusion structures."""
        # Test with non-list values
        result = await run_mcp_tool_call(
            "read_context",
            project_root=str(test_project),
            targets=[],
            rules=[],
            list_only=True,
            exclusions={
                "global": "tests",  # Should be a list
                "patterns": ["*.log"]
            }
        )
        
        # Should still work, ignoring invalid parts
        lines = result.strip().split('\n')
        assert not any(".log" in line for line in lines)