# jinni/config_system.py
import os
import re
import fnmatch
from pathlib import Path
from typing import List, Tuple, Dict, Optional, Set

# Rule type constants
RULE_INCLUDE = 'include'
RULE_EXCLUDE = 'exclude'

# --- Default Exclusions (adapted from prototype.py) ---
DEFAULT_SKIP_DIRECTORIES: Set[str] = {
    '__pycache__', 'node_modules', 'venv', 'env', '.venv', '.env',
    'build', 'dist', 'target', 'out', 'bin', 'obj',
    '.git', '.svn', '.hg',
    '.idea', '.vscode', # Note: check_item logic might need refinement for these
    'logs',
    'output',
}
DEFAULT_SKIP_DIRECTORY_PATTERNS: List[str] = [
    r'\.egg-info$',
]
DEFAULT_SKIP_FILE_PATTERNS: List[str] = [
    r'\.log(\.[0-9]+)?$',
    r'^log\.',
    r'\.bak$',
    r'\.tmp$',
    r'\.temp$',
    r'\.swp$',
    r'~$',
    # Add common binary extensions if needed, although prototype relied on text read errors
    # r'\.exe$', r'\.dll$', r'\.so$', r'\.dylib$', r'\.jar$', r'\.class$',
    # r'\.zip$', r'\.tar\.gz$', r'\.tgz$', r'\.rar$', r'\.7z$',
    # r'\.png$', r'\.jpe?g$', r'\.gif$', r'\.bmp$', r'\.tiff?$',
    # r'\.pdf$', r'\.docx?$', r'\.xlsx?$', r'\.pptx?$',
    # r'\.mp3$', r'\.wav$', r'\.ogg$', r'\.mp4$', r'\.avi$', r'\.mov$',
]
# Allowed hidden files/dirs (from prototype.py - simplified for now)
DEFAULT_ALLOWED_HIDDEN: Set[str] = {
    '.gitignore', '.dockerignore', '.editorconfig', '.env', '.gitattributes',
    '.pylintrc', '.flake8', '.babelrc', '.eslintrc', '.prettierrc',
    '.travis.yml', '.gitlab-ci.yml',
}

Rule = Tuple[str, str] # (type, pattern) e.g. ('exclude', '*.log')
Ruleset = List[Rule]
RuleCache = Dict[Path, Optional[Ruleset]] # Cache parsed .contextfiles

def parse_rules(rules_content: str) -> Ruleset:
    """Parses a string containing rules (like .contextfiles content)."""
    rules: Ruleset = []
    for line in rules_content.splitlines():
        stripped_line = line.strip()
        if not stripped_line or stripped_line.startswith('#'):
            continue
        if stripped_line.startswith('!'):
            pattern = stripped_line[1:].strip()
            if pattern:
                rules.append((RULE_EXCLUDE, pattern))
        else:
            pattern = stripped_line
            if pattern: # Ensure pattern is not empty after stripping
                rules.append((RULE_INCLUDE, pattern))
    return rules

def find_and_parse_contextfile(dir_path: Path, cache: RuleCache) -> Optional[Ruleset]:
    """Finds and parses .contextfiles in a directory, using cache."""
    abs_dir_path = dir_path.resolve() # Use absolute paths for cache keys
    if abs_dir_path in cache:
        return cache[abs_dir_path]

    contextfile_path = abs_dir_path / ".contextfiles"
    ruleset = None
    if contextfile_path.is_file():
        try:
            content = contextfile_path.read_text(encoding='utf-8')
            ruleset = parse_rules(content)
        except Exception as e:
            # TODO: Log error? For now, treat as non-existent or empty
            print(f"Warning: Could not read or parse {contextfile_path}: {e}", file=os.sys.stderr)
            ruleset = None # Explicitly None if error
    cache[abs_dir_path] = ruleset
    return ruleset

def check_default_exclusions(item_path: Path, is_dir: bool, root_path: Path) -> bool: # Added root_path
    """Check if an item or its ancestors match default exclusion rules. Returns True if excluded."""
    # Check the item itself first
    name = item_path.name
    name_lower = name.lower()

    # Skip hidden unless explicitly allowed (simplified logic from before, might need refinement)
    if name.startswith('.') and name not in DEFAULT_ALLOWED_HIDDEN and name_lower not in DEFAULT_ALLOWED_HIDDEN:
        # Allow specific top-level hidden dirs like .git, .vscode, .idea themselves
        if name not in {'.git', '.vscode', '.idea'}:
            return True
        elif not is_dir: # Exclude hidden files unless allowed
            return True

    if is_dir:
        if name in DEFAULT_SKIP_DIRECTORIES:
            return True
        if any(re.search(pattern, name) for pattern in DEFAULT_SKIP_DIRECTORY_PATTERNS):
            return True
    else: # Is file
        if any(re.search(pattern, name_lower) for pattern in DEFAULT_SKIP_FILE_PATTERNS):
            return True

    # Check parent directories up to the root
    try:
        current = item_path.parent
        # Ensure root_path is absolute for comparison
        abs_root_path = root_path.resolve()
        while current != abs_root_path and current != current.parent: # Stop at root or filesystem root
            if current.name in DEFAULT_SKIP_DIRECTORIES:
                return True # Excluded because parent is skipped
            current = current.parent
    except Exception as e:
        # Handle potential errors during traversal if needed
        print(f"Warning: Error checking parent directories for {item_path}: {e}", file=os.sys.stderr)
        pass # Continue without parent check if error occurs

    return False


def check_item(
    item_path: Path,
    root_path: Path,
    inline_rules: Optional[Ruleset] = None,
    global_rules: Optional[Ruleset] = None,
    contextfile_cache: Optional[RuleCache] = None
) -> bool:
    """
    Checks if an item should be included based on the full rule hierarchy.
    Returns True if included, False if excluded.
    DESIGN.md Precedence: Inline -> .contextfiles (subdir -> parent) -> Global -> Default
    """
    if contextfile_cache is None:
        contextfile_cache = {} # Initialize cache if not provided

    # Ensure paths are absolute for reliable comparison and cache keys
    abs_item_path = item_path.resolve()
    abs_root_path = root_path.resolve()

    try:
        relative_path = abs_item_path.relative_to(abs_root_path)
    except ValueError:
         # Item is not under root path, should not happen if called correctly from os.walk
         print(f"Warning: Item {abs_item_path} not relative to root {abs_root_path}", file=os.sys.stderr)
         return False # Exclude items outside the root

    relative_path_str = str(relative_path).replace(os.sep, '/') # Use POSIX paths for matching
    is_dir = abs_item_path.is_dir()
    # Pattern to match against rules (append '/' for directories)
    pattern_to_match = f"{relative_path_str}/" if is_dir else relative_path_str

    # --- Check rules based on precedence ---

    # 1. Inline Rules (Highest Precedence)
    if inline_rules:
        # Iterate rules in reverse to give later rules precedence within this set
        for rule_type, pattern in reversed(inline_rules):
            match_pattern = f"{pattern}/" if pattern.endswith('/') else pattern
            is_dir_pattern = pattern.endswith('/')
            # Check if pattern type matches item type or pattern is generic (no '/')
            if (is_dir and is_dir_pattern) or \
               (not is_dir and not is_dir_pattern) or \
               (not is_dir_pattern):
                 if fnmatch.fnmatch(pattern_to_match, match_pattern):
                    # First match determines outcome for this level
                    return rule_type == RULE_INCLUDE

    # 2. .contextfiles (Subdirectory to Root)
    current_dir = abs_item_path.parent
    # Iterate from item's directory up to the root directory
    while current_dir >= abs_root_path:
        ruleset = find_and_parse_contextfile(current_dir, contextfile_cache)
        if ruleset:
            # Calculate relative path for matching within this contextfile's directory scope
            try:
                rel_path_for_context = abs_item_path.relative_to(current_dir)
                rel_path_str_for_context = str(rel_path_for_context).replace(os.sep, '/')
                pattern_to_match_context = f"{rel_path_str_for_context}/" if is_dir else rel_path_str_for_context
            except ValueError:
                 # Should not happen if current_dir is an ancestor
                 break # Safety break

            # Iterate rules in reverse to give later rules precedence within this file
            for rule_type, pattern in reversed(ruleset):
                match_pattern = f"{pattern}/" if pattern.endswith('/') else pattern
                is_dir_pattern = pattern.endswith('/')
                # Check if pattern type matches item type or pattern is generic
                if (is_dir and is_dir_pattern) or \
                   (not is_dir and not is_dir_pattern) or \
                   (not is_dir_pattern):
                     if fnmatch.fnmatch(pattern_to_match_context, match_pattern):
                        # First match at this level determines outcome
                        return rule_type == RULE_INCLUDE

        if current_dir == abs_root_path: # Stop if we've checked the root
            break
        current_dir = current_dir.parent # Move up one directory


    # 3. Global Rules
    if global_rules:
         # Iterate rules in reverse
         for rule_type, pattern in reversed(global_rules):
            match_pattern = f"{pattern}/" if pattern.endswith('/') else pattern
            is_dir_pattern = pattern.endswith('/')
            # Check if pattern type matches item type or pattern is generic
            if (is_dir and is_dir_pattern) or \
               (not is_dir and not is_dir_pattern) or \
               (not is_dir_pattern):
                 # Match against path relative to root
                 if fnmatch.fnmatch(pattern_to_match, match_pattern):
                    # First match determines outcome for this level
                    return rule_type == RULE_INCLUDE

    # 4. Default Exclusions
    # Pass absolute root path for consistent parent checking
    if check_default_exclusions(abs_item_path, is_dir, abs_root_path): # MODIFIED call
        return False

    # 5. If no rules excluded it, include it by default
    return True