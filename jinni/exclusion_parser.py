# jinni/exclusion_parser.py
"""
Exclusion parser for converting natural language exclusions to pathspec patterns.
Supports global exclusions, scoped exclusions, and file patterns.
"""

import logging
from typing import List, Dict, Set, Tuple, Optional
from pathlib import Path

logger = logging.getLogger("jinni.exclusion_parser")


class ExclusionParser:
    """Parses and converts high-level exclusion directives to pathspec patterns."""
    
    # Common module/directory keywords and their typical patterns
    MODULE_PATTERNS = {
        "tests": ["**/test/**", "**/tests/**", "**/*_test/**", "**/*_tests/**", 
                  "**/test_*/**", "**/test_*", "**/*.test.*", "**/*.spec.*", "**/spec/**"],
        "test": ["**/test/**", "**/tests/**", "**/*_test/**", "**/*_tests/**", 
                 "**/test_*/**", "**/test_*", "**/*.test.*", "**/*.spec.*", "**/spec/**"],
        "vendor": ["vendor/**", "**/vendor/**", "third_party/**", "**/third_party/**",
                   "external/**", "**/external/**"],
        "vendors": ["vendor/**", "**/vendor/**", "third_party/**", "**/third_party/**",
                    "external/**", "**/external/**"],
        "docs": ["docs/**", "**/docs/**", "documentation/**", "**/documentation/**",
                 "doc/**", "**/doc/**"],
        "doc": ["docs/**", "**/docs/**", "documentation/**", "**/documentation/**",
                "doc/**", "**/doc/**"],
        "build": ["build/**", "**/build/**", "dist/**", "**/dist/**", 
                  "out/**", "**/out/**", "target/**", "**/target/**"],
        "builds": ["build/**", "**/build/**", "dist/**", "**/dist/**", 
                   "out/**", "**/out/**", "target/**", "**/target/**"],
        "examples": ["examples/**", "**/examples/**", "example/**", "**/example/**",
                     "samples/**", "**/samples/**", "demo/**", "**/demo/**"],
        "example": ["examples/**", "**/examples/**", "example/**", "**/example/**",
                    "samples/**", "**/samples/**", "demo/**", "**/demo/**"],
        "cache": ["cache/**", "**/cache/**", ".cache/**", "**/.cache/**",
                  "__pycache__/**", "**/__pycache__/**"],
        "caches": ["cache/**", "**/cache/**", ".cache/**", "**/.cache/**",
                   "__pycache__/**", "**/__pycache__/**"],
        "temp": ["tmp/**", "**/tmp/**", "temp/**", "**/temp/**", 
                 "*.tmp", "*.temp", "**/*.tmp", "**/*.temp"],
        "tmp": ["tmp/**", "**/tmp/**", "temp/**", "**/temp/**", 
                "*.tmp", "*.temp", "**/*.tmp", "**/*.temp"],
        "logs": ["logs/**", "**/logs/**", "*.log", "**/*.log", 
                 "log/**", "**/log/**"],
        "log": ["logs/**", "**/logs/**", "*.log", "**/*.log", 
                "log/**", "**/log/**"],
        "generated": ["generated/**", "**/generated/**", "gen/**", "**/gen/**",
                      "*_generated.*", "**/*_generated.*", "*.generated.*", "**/*.generated.*"],
        "gen": ["generated/**", "**/generated/**", "gen/**", "**/gen/**",
                "*_generated.*", "**/*_generated.*", "*.generated.*", "**/*.generated.*"],
        "legacy": ["legacy/**", "**/legacy/**", "old/**", "**/old/**",
                   "deprecated/**", "**/deprecated/**"],
        "old": ["legacy/**", "**/legacy/**", "old/**", "**/old/**",
                "deprecated/**", "**/deprecated/**"],
        "experimental": ["experimental/**", "**/experimental/**", "experiment/**", 
                         "**/experiment/**", "proto/**", "**/proto/**", "wip/**", "**/wip/**"],
        "experiment": ["experimental/**", "**/experimental/**", "experiment/**", 
                       "**/experiment/**", "proto/**", "**/proto/**", "wip/**", "**/wip/**"],
    }
    
    def __init__(self):
        self.global_exclusions: List[str] = []
        self.scoped_exclusions: Dict[str, List[str]] = {}
        self.file_patterns: List[str] = []
        self.keep_only: Optional[List[str]] = None
    
    def parse_not(self, keywords: List[str]) -> List[str]:
        """
        Parse --not keywords into exclusion patterns.
        E.g., --not "tests" -> patterns to exclude all test-related files
        """
        patterns = []
        for keyword in keywords:
            keyword_lower = keyword.lower().strip()
            
            # Check if it's a known module pattern
            if keyword_lower in self.MODULE_PATTERNS:
                patterns.extend(self.MODULE_PATTERNS[keyword_lower])
                logger.debug(f"Expanded '{keyword}' to module patterns: {self.MODULE_PATTERNS[keyword_lower]}")
            else:
                # Treat as a literal directory/file pattern
                # Support both exact directory and nested occurrences
                patterns.extend([
                    f"{keyword}/**",           # Exact directory at any level
                    f"**/{keyword}/**",        # Nested directory
                    f"*{keyword}*/**",         # Directory containing keyword
                    f"**/*{keyword}*/**",      # Nested directory containing keyword
                    f"*{keyword}*",            # Files containing keyword at root
                    f"**/*{keyword}*"          # Files containing keyword anywhere
                ])
                logger.debug(f"Created general patterns for '{keyword}'")
        
        # Prefix with ! for exclusion in pathspec
        return [f"!{p}" for p in patterns]
    
    def parse_not_in(self, scoped_exclusions: List[str]) -> Dict[str, List[str]]:
        """
        Parse --not-in scoped exclusions.
        E.g., --not-in "src:legacy,experimental" -> exclude legacy and experimental only within src/
        """
        result = {}
        for scoped in scoped_exclusions:
            if ':' not in scoped:
                logger.warning(f"Invalid --not-in format '{scoped}', expected 'scope:keyword1,keyword2'")
                continue
            
            scope, keywords_str = scoped.split(':', 1)
            keywords = [k.strip() for k in keywords_str.split(',') if k.strip()]
            
            if not keywords:
                continue
            
            # Convert keywords to patterns relative to the scope
            patterns = []
            for keyword in keywords:
                keyword_lower = keyword.lower()
                if keyword_lower in self.MODULE_PATTERNS:
                    # For scoped patterns, adapt the patterns to be relative to scope
                    for pattern in self.MODULE_PATTERNS[keyword_lower]:
                        if pattern.startswith('**/'):
                            # Convert **/ patterns to be relative
                            patterns.append(pattern[3:])  # Remove **/
                        else:
                            patterns.append(pattern)
                else:
                    # Simple patterns relative to scope
                    patterns.extend([
                        f"{keyword}/**",
                        f"*{keyword}*/**",
                        f"*{keyword}*",
                    ])
            
            result[scope] = [f"!{p}" for p in patterns]
            logger.debug(f"Scoped exclusions for '{scope}': {result[scope]}")
        
        return result
    
    def parse_not_files(self, patterns: List[str]) -> List[str]:
        """
        Parse --not-files patterns.
        E.g., --not-files "*.test.js" "*.spec.ts"
        """
        result = []
        for pattern in patterns:
            # Ensure the pattern can match at any depth
            if '/' not in pattern:
                # File pattern without path - make it work at any level
                result.extend([
                    f"!{pattern}",        # At root
                    f"!**/{pattern}"      # At any depth
                ])
            else:
                # Pattern includes path separator, use as-is
                result.append(f"!{pattern}")
            logger.debug(f"File exclusion pattern: {pattern}")
        
        return result
    
    def parse_keep_only(self, modules: List[str]) -> List[str]:
        """
        Parse --keep-only modules.
        E.g., --keep-only "src,lib" -> include only src/ and lib/ directories
        """
        patterns = []
        
        # First, exclude everything
        patterns.append("!*")
        
        # Then include only the specified modules
        for module in modules:
            module = module.strip()
            # Include the module directory and its contents
            patterns.extend([
                f"{module}/**",     # Include everything under the module
                f"{module}",        # Include the directory itself
            ])
            logger.debug(f"Keep only module: {module}")
        
        self.keep_only = modules
        return patterns
    
    def combine_exclusions(self, 
                          not_keywords: Optional[List[str]] = None,
                          not_in_scoped: Optional[List[str]] = None,
                          not_files: Optional[List[str]] = None,
                          keep_only_modules: Optional[List[str]] = None) -> List[str]:
        """
        Combine all exclusion types into a final list of pathspec patterns.
        Returns patterns ready to be appended to existing rules.
        """
        all_patterns = []
        
        # Handle --keep-only first as it's the most restrictive
        if keep_only_modules:
            return self.parse_keep_only(keep_only_modules)
        
        # Global exclusions from --not
        if not_keywords:
            self.global_exclusions = self.parse_not(not_keywords)
            all_patterns.extend(self.global_exclusions)
        
        # Scoped exclusions from --not-in
        if not_in_scoped:
            self.scoped_exclusions = self.parse_not_in(not_in_scoped)
            # Scoped exclusions are handled differently during traversal
            # We don't add them to the global patterns
        
        # File pattern exclusions from --not-files
        if not_files:
            self.file_patterns = self.parse_not_files(not_files)
            all_patterns.extend(self.file_patterns)
        
        return all_patterns
    
    def get_scoped_patterns(self, current_path: Path, walk_root: Path) -> List[str]:
        """
        Get exclusion patterns that apply to the current directory based on scope.
        Used during directory traversal to apply scoped exclusions.
        """
        if not self.scoped_exclusions:
            return []
        
        try:
            rel_path = current_path.relative_to(walk_root)
            path_parts = rel_path.parts
        except ValueError:
            return []
        
        patterns = []
        
        # Check each scope to see if it applies to current path
        for scope, scope_patterns in self.scoped_exclusions.items():
            # Check if we're within this scope
            scope_parts = Path(scope).parts
            if len(path_parts) >= len(scope_parts):
                # Check if the scope matches the beginning of our path
                if path_parts[:len(scope_parts)] == scope_parts:
                    # Adjust patterns to include the scope prefix for pathspec matching
                    adjusted_patterns = []
                    for pattern in scope_patterns:
                        if pattern.startswith("!"):
                            # For exclusion patterns, prepend the scope path
                            adjusted_pattern = f"!{scope}/{pattern[1:]}"
                            adjusted_patterns.append(adjusted_pattern)
                        else:
                            # For inclusion patterns (shouldn't happen in our case)
                            adjusted_patterns.append(f"{scope}/{pattern}")
                    patterns.extend(adjusted_patterns)
                    logger.debug(f"Applied scoped exclusions for '{scope}' at '{rel_path}' with adjusted patterns: {adjusted_patterns}")
        
        return patterns


def create_exclusion_patterns(not_keywords: Optional[List[str]] = None,
                            not_in_scoped: Optional[List[str]] = None,
                            not_files: Optional[List[str]] = None,
                            keep_only_modules: Optional[List[str]] = None) -> Tuple[List[str], Optional[ExclusionParser]]:
    """
    Convenience function to create exclusion patterns and return the parser instance.
    Returns: (patterns, parser_instance)
    
    The parser instance is needed for scoped exclusion lookups during traversal.
    Returns None for parser if no exclusions are specified.
    """
    # Check if any exclusions are provided
    if not any([not_keywords, not_in_scoped, not_files, keep_only_modules]):
        return [], None
    
    parser = ExclusionParser()
    patterns = parser.combine_exclusions(not_keywords, not_in_scoped, not_files, keep_only_modules)
    return patterns, parser