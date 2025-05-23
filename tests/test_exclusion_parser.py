# tests/test_exclusion_parser.py
"""Tests for the exclusion parser module."""

import pytest
from pathlib import Path
from jinni.exclusion_parser import ExclusionParser, create_exclusion_patterns


class TestExclusionParser:
    """Test the ExclusionParser class."""
    
    def test_parse_not_common_keywords(self):
        """Test parsing common module keywords."""
        parser = ExclusionParser()
        
        # Test single keyword
        patterns = parser.parse_not(["tests"])
        assert "!**/test/**" in patterns
        assert "!**/tests/**" in patterns
        assert "!**/*.test.*" in patterns
        assert "!**/*.spec.*" in patterns
        
        # Test multiple keywords
        patterns = parser.parse_not(["vendor", "docs"])
        assert "!vendor/**" in patterns
        assert "!**/vendor/**" in patterns
        assert "!docs/**" in patterns
        assert "!**/docs/**" in patterns
    
    def test_parse_not_custom_keywords(self):
        """Test parsing custom/unknown keywords."""
        parser = ExclusionParser()
        patterns = parser.parse_not(["custom_module"])
        
        # Should create general patterns
        assert "!custom_module/**" in patterns
        assert "!**/custom_module/**" in patterns
        assert "!*custom_module*/**" in patterns
        assert "!**/*custom_module*/**" in patterns
        assert "!*custom_module*" in patterns
        assert "!**/*custom_module*" in patterns
    
    def test_parse_not_in_scoped(self):
        """Test parsing scoped exclusions."""
        parser = ExclusionParser()
        
        # Test single scope
        result = parser.parse_not_in(["src:legacy,experimental"])
        assert "src" in result
        assert "!legacy/**" in result["src"]
        assert "!experimental/**" in result["src"]
        
        # Test multiple scopes
        result = parser.parse_not_in(["src:old", "lib:deprecated,wip"])
        assert "src" in result
        assert "lib" in result
        assert "!old/**" in result["src"]
        assert "!deprecated/**" in result["lib"]
        assert "!wip/**" in result["lib"]
    
    def test_parse_not_in_invalid_format(self):
        """Test handling of invalid scoped exclusion format."""
        parser = ExclusionParser()
        result = parser.parse_not_in(["invalid_format", "valid:tests"])
        
        # Should skip invalid, process valid
        assert "invalid_format" not in result
        assert "valid" in result
        assert len(result["valid"]) > 0
        # Should have expanded 'tests' keyword
        assert any("test" in pattern for pattern in result["valid"])
    
    def test_parse_not_files(self):
        """Test parsing file pattern exclusions."""
        parser = ExclusionParser()
        
        # Test simple patterns
        patterns = parser.parse_not_files(["*.test.js", "*.spec.ts"])
        assert "!*.test.js" in patterns
        assert "!**/*.test.js" in patterns
        assert "!*.spec.ts" in patterns
        assert "!**/*.spec.ts" in patterns
        
        # Test patterns with paths
        patterns = parser.parse_not_files(["src/*.tmp", "build/output.log"])
        assert "!src/*.tmp" in patterns
        assert "!build/output.log" in patterns
    
    def test_parse_keep_only(self):
        """Test parsing keep-only modules."""
        parser = ExclusionParser()
        patterns = parser.parse_keep_only(["src", "lib"])
        
        # Should exclude everything first
        assert "!*" in patterns
        # Then include only specified modules
        assert "src/**" in patterns
        assert "src" in patterns
        assert "lib/**" in patterns
        assert "lib" in patterns
        
        # Check that parser tracks keep_only
        assert parser.keep_only == ["src", "lib"]
    
    def test_combine_exclusions_all_types(self):
        """Test combining all exclusion types."""
        parser = ExclusionParser()
        patterns = parser.combine_exclusions(
            not_keywords=["test", "vendor"],
            not_in_scoped=["src:legacy,old"],
            not_files=["*.tmp", "*.log"],
            keep_only_modules=None
        )
        
        # Should have patterns from all types
        assert any("test" in p for p in patterns)
        assert any("vendor" in p for p in patterns)
        assert any("tmp" in p for p in patterns)
        assert any("log" in p for p in patterns)
        
        # Scoped exclusions should be in parser.scoped_exclusions
        assert "src" in parser.scoped_exclusions
    
    def test_combine_exclusions_keep_only_overrides(self):
        """Test that keep_only overrides other exclusions."""
        parser = ExclusionParser()
        patterns = parser.combine_exclusions(
            not_keywords=["test"],
            not_in_scoped=["src:legacy"],
            not_files=["*.tmp"],
            keep_only_modules=["src", "docs"]
        )
        
        # Should only have keep_only patterns
        assert "!*" in patterns
        assert "src/**" in patterns
        assert "docs/**" in patterns
        # Should not have other exclusion patterns
        assert not any("test" in p for p in patterns if p != "!*")
    
    def test_get_scoped_patterns(self):
        """Test getting scoped patterns for a specific directory."""
        parser = ExclusionParser()
        parser.combine_exclusions(not_in_scoped=["src:legacy,old", "lib:deprecated"])
        
        walk_root = Path("/project")
        
        # Test exact scope match - patterns should include scope prefix
        patterns = parser.get_scoped_patterns(Path("/project/src"), walk_root)
        assert "!src/legacy/**" in patterns
        assert "!src/old/**" in patterns
        
        # Test nested path within scope - patterns should still include scope prefix
        patterns = parser.get_scoped_patterns(Path("/project/src/subdir"), walk_root)
        assert "!src/legacy/**" in patterns
        assert "!src/old/**" in patterns
        
        # Test different scope
        patterns = parser.get_scoped_patterns(Path("/project/lib"), walk_root)
        assert "!lib/deprecated/**" in patterns
        assert "!src/legacy/**" not in patterns
        
        # Test path outside any scope
        patterns = parser.get_scoped_patterns(Path("/project/docs"), walk_root)
        assert len(patterns) == 0
    
    def test_create_exclusion_patterns_function(self):
        """Test the convenience function."""
        patterns, parser = create_exclusion_patterns(
            not_keywords=["test"],
            not_in_scoped=["src:legacy"],
            not_files=["*.tmp"],
            keep_only_modules=None
        )
        
        assert isinstance(patterns, list)
        assert isinstance(parser, ExclusionParser)
        assert len(patterns) > 0
        assert "src" in parser.scoped_exclusions