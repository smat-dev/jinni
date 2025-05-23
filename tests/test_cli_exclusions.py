# tests/test_cli_exclusions.py
"""Integration tests for CLI exclusion features."""

import pytest
import os
from pathlib import Path
from unittest import mock
from jinni.cli import main
from tests.conftest import run_jinni_cli
import tempfile
import shutil


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


class TestCLIExclusions:
    """Test CLI exclusion arguments."""
    
    @pytest.fixture
    def test_project(self):
        """Create a test project structure with various module types."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            
            # Create project structure
            structure = {
                "src": {
                    "main.py": "# Main application code",
                    "utils.py": "# Utility functions",
                    "legacy": {
                        "old_code.py": "# Legacy code",
                        "deprecated.py": "# Deprecated module"
                    },
                    "experimental": {
                        "new_feature.py": "# Experimental feature"
                    }
                },
                "tests": {
                    "test_main.py": "# Test for main",
                    "test_utils.py": "# Test for utils",
                    "integration": {
                        "test_integration.py": "# Integration tests"
                    }
                },
                "docs": {
                    "README.md": "# Documentation",
                    "api.md": "# API docs"
                },
                "vendor": {
                    "third_party.py": "# Third party code",
                    "library": {
                        "lib.py": "# External library"
                    }
                },
                "build": {
                    "output.js": "// Built file",
                    "dist": {
                        "app.min.js": "// Minified app"
                    }
                },
                "config.yaml": "# Configuration",
                "setup.py": "# Setup script",
                "data.json": '{"key": "value"}',
                "script.test.js": "// Test script",
                "module.spec.ts": "// Spec file",
                "temp.tmp": "# Temporary file",
                "debug.log": "# Log file"
            }
            
            create_project_structure(root, structure)
            yield root
    
    def test_not_flag_single_keyword(self, test_project):
        """Test --not flag with single keyword."""
        stdout, stderr = run_jinni_cli(["--not", "tests", "--list-only", str(test_project)])
        
        output_lines = stdout.strip().split('\n')
        
        # Should exclude all test-related files
        assert not any("tests/" in line for line in output_lines)
        assert not any("test_" in line for line in output_lines)
        assert not any(".test." in line for line in output_lines)
        assert not any(".spec." in line for line in output_lines)
        
        # Should include other files
        assert any("src/main.py" in line for line in output_lines)
        assert any("docs/README.md" in line for line in output_lines)
    
    def test_not_flag_multiple_keywords(self, test_project):
        """Test --not flag with multiple keywords."""
        stdout, stderr = run_jinni_cli([
            "--not", "tests",
            "--not", "vendor",
            "--not", "build",
            "--list-only",
            str(test_project)
        ])
        
        output_lines = stdout.strip().split('\n')
        
        # Should exclude specified modules
        assert not any("tests/" in line for line in output_lines)
        assert not any("vendor/" in line for line in output_lines)
        assert not any("build/" in line for line in output_lines)
        
        # Should include other files
        assert any("src/main.py" in line for line in output_lines)
        assert any("docs/README.md" in line for line in output_lines)
    
    def test_not_in_flag_scoped_exclusions(self, test_project):
        """Test --not-in flag for scoped exclusions."""
        stdout, stderr = run_jinni_cli([
            "--not-in", "src:legacy,experimental",
            "--list-only",
            str(test_project)
        ])
        
        output_lines = stdout.strip().split('\n')
        
        # Should exclude legacy and experimental only within src
        assert not any("src/legacy/" in line for line in output_lines)
        assert not any("src/experimental/" in line for line in output_lines)
        
        # Should include other src files
        assert any("src/main.py" in line for line in output_lines)
        assert any("src/utils.py" in line for line in output_lines)
        
        # Should include everything outside src
        assert any("tests/test_main.py" in line for line in output_lines)
        assert any("docs/README.md" in line for line in output_lines)
    
    def test_not_files_flag(self, test_project):
        """Test --not-files flag for file pattern exclusions."""
        stdout, stderr = run_jinni_cli([
            "--not-files", "*.test.js",
            "--not-files", "*.spec.ts",
            "--not-files", "*.tmp",
            "--not-files", "*.log",
            "--list-only",
            str(test_project)
        ])
        
        output_lines = stdout.strip().split('\n')
        
        # Should exclude files matching patterns
        assert not any("script.test.js" in line for line in output_lines)
        assert not any("module.spec.ts" in line for line in output_lines)
        assert not any("temp.tmp" in line for line in output_lines)
        assert not any("debug.log" in line for line in output_lines)
        
        # Should include other files
        assert any("src/main.py" in line for line in output_lines)
        assert any("config.yaml" in line for line in output_lines)
    
    def test_keep_only_flag(self, test_project):
        """Test --keep-only flag."""
        stdout, stderr = run_jinni_cli([
            "--keep-only", "src,docs",
            "--list-only",
            str(test_project)
        ])
        
        output_lines = stdout.strip().split('\n')
        
        # Should only include src and docs
        assert any("src/main.py" in line for line in output_lines)
        assert any("src/utils.py" in line for line in output_lines)
        assert any("docs/README.md" in line for line in output_lines)
        
        # Should exclude everything else
        assert not any("tests/" in line for line in output_lines)
        assert not any("vendor/" in line for line in output_lines)
        assert not any("build/" in line for line in output_lines)
        assert not any("config.yaml" in line for line in output_lines)
        assert not any("setup.py" in line for line in output_lines)
    
    def test_combined_exclusions(self, test_project):
        """Test combining multiple exclusion types."""
        stdout, stderr = run_jinni_cli([
            "--not", "vendor",
            "--not-in", "src:legacy",
            "--not-files", "*.log",
            "--list-only",
            str(test_project)
        ])
        
        output_lines = stdout.strip().split('\n')
        
        # Check combined exclusions work
        assert not any("vendor/" in line for line in output_lines)
        assert not any("src/legacy/" in line for line in output_lines)
        assert not any("debug.log" in line for line in output_lines)
        
        # Check non-excluded files are included
        assert any("src/main.py" in line for line in output_lines)
        assert any("src/experimental/new_feature.py" in line for line in output_lines)
        assert any("tests/test_main.py" in line for line in output_lines)
    
    def test_exclusions_with_overrides(self, test_project):
        """Test that exclusions work with override files."""
        # Create an override file
        override_file = test_project / "custom.rules"
        override_file.write_text("# Custom rules\n*.json\n")
        
        stdout, stderr = run_jinni_cli([
            "--overrides", str(override_file),
            "--not", "tests",
            "--list-only",
            str(test_project)
        ])
        
        output_lines = stdout.strip().split('\n')
        
        # Should apply both overrides and exclusions
        assert any("data.json" in line for line in output_lines)  # Included by override
        assert not any("tests/" in line for line in output_lines)  # Excluded by --not
    
    def test_exclusions_debug_output(self, test_project):
        """Test that debug mode shows exclusion pattern details."""
        stdout, stderr = run_jinni_cli([
            "--not", "tests",
            "--debug-explain",
            "--list-only",
            str(test_project)
        ])
        
        # Check debug output mentions exclusion patterns
        assert "exclusion patterns" in stderr.lower() or "exclusion pattern" in stderr.lower()
        assert "test" in stderr.lower()
    
    def test_exclusions_with_content(self, test_project):
        """Test exclusions work correctly when reading content (not just listing)."""
        stdout, stderr = run_jinni_cli([
            "--not", "tests",
            "--not", "vendor",
            str(test_project)
        ])
        
        # Content should not include test or vendor files
        assert "# Test for main" not in stdout
        assert "# Third party code" not in stdout
        
        # Should include other content
        assert "# Main application code" in stdout
        assert "# Documentation" in stdout
    
    def test_keep_only_with_nested_targets(self, test_project):
        """Test --keep-only with specific nested targets."""
        # When targeting a subdirectory with keep-only, it should be excluded
        # unless we're in the project root context
        stdout, stderr = run_jinni_cli([
            "--keep-only", "src",
            "--list-only", 
            str(test_project)
        ])
        
        output_lines = stdout.strip().split('\n')
        
        # Should include src files including legacy subdirectory
        assert any("src/legacy/old_code.py" in line for line in output_lines)
        assert any("src/legacy/deprecated.py" in line for line in output_lines)
        assert any("src/main.py" in line for line in output_lines)
        
        # Should exclude other modules
        assert not any("tests/" in line for line in output_lines)
        assert not any("vendor/" in line for line in output_lines)