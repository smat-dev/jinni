# jinni/config_system.py
import os
import re
import fnmatch
import logging # Added for logging
from pathlib import Path
from typing import List, Tuple, Dict, Optional, Set, Tuple # Ensure Tuple is imported

# Setup logger for this module
logger = logging.getLogger(__name__)
# Configure basic logging if no handlers are configured by the application
if not logger.handlers:
    logging.basicConfig(level=logging.INFO, format='%(levelname)s:%(name)s:%(message)s')

# Rule type constants
RULE_INCLUDE = 'include'
RULE_EXCLUDE = 'exclude'

# --- Default Exclusions (Unified Glob Pattern Approach) ---
# These rules are applied with the lowest precedence.
# Users can override these with global, local, or inline rules.
DEFAULT_EXCLUDE_RULESET: 'Ruleset' = [
    # Version Control Systems & Files
    # (RULE_EXCLUDE, "**/.git/"), # Rely on hidden pattern below
    (RULE_EXCLUDE, "**/.svn/"),
    (RULE_EXCLUDE, "**/.hg/"),
    (RULE_EXCLUDE, "**/.bzr/"),
    (RULE_EXCLUDE, "**/.DS_Store"),

    # Common Build/Dependency Directories
    (RULE_EXCLUDE, "**/__pycache__/"),
    (RULE_EXCLUDE, "**/node_modules/"),
    (RULE_EXCLUDE, "**/venv/"),
    (RULE_EXCLUDE, "**/env/"),
    (RULE_EXCLUDE, "**/.venv/"),
    (RULE_EXCLUDE, "**/.env/"), # Note: Excludes common .env files by default
    (RULE_EXCLUDE, "**/build/"),
    (RULE_EXCLUDE, "**/dist/"),
    (RULE_EXCLUDE, "**/target/"), # Rust, Java (Maven/Gradle)
    (RULE_EXCLUDE, "**/out/"),   # Java (some IDEs)
    (RULE_EXCLUDE, "**/bin/"),   # Go, .NET, general build output
    (RULE_EXCLUDE, "**/obj/"),   # .NET
    (RULE_EXCLUDE, "**/*.egg-info/"), # Python packaging
    (RULE_EXCLUDE, "**/bower_components/"), # Web frontend
    (RULE_EXCLUDE, "**/jspm_packages/"),  # Web frontend
    (RULE_EXCLUDE, "**/vendor/"), # PHP (Composer), Go, Ruby
    (RULE_EXCLUDE, "**/Pods/"),   # iOS (CocoaPods)
    (RULE_EXCLUDE, "**/Carthage/"), # iOS
    (RULE_EXCLUDE, "**/packages/"), # .NET (NuGet), Dart (pub)

    # IDE/Editor Directories
    (RULE_EXCLUDE, "**/.idea/"),
    (RULE_EXCLUDE, "**/.vscode/"),
    (RULE_EXCLUDE, "**/.project"), # Eclipse
    (RULE_EXCLUDE, "**/.classpath"), # Eclipse
    (RULE_EXCLUDE, "**/.settings/"), # Eclipse

    # Log Files & Directories
    (RULE_EXCLUDE, "**/logs/"),
    (RULE_EXCLUDE, "**/log/"),
    (RULE_EXCLUDE, "**/*.log"),
    (RULE_EXCLUDE, "**/*.log.*"), # Handles .log.1, .log.gz etc.

    # Temporary/Backup Files
    (RULE_EXCLUDE, "**/*.bak"),
    (RULE_EXCLUDE, "**/*.tmp"),
    (RULE_EXCLUDE, "**/*.temp"),
    (RULE_EXCLUDE, "**/*.swp"),
    (RULE_EXCLUDE, "**/*~"),

    # OS Specific Files
    (RULE_EXCLUDE, "**/Thumbs.db"), # Windows image cache

    # Common Binary Executables/Libraries
    (RULE_EXCLUDE, "**/*.exe"), (RULE_EXCLUDE, "**/*.dll"), (RULE_EXCLUDE, "**/*.so"), (RULE_EXCLUDE, "**/*.dylib"),
    (RULE_EXCLUDE, "**/*.jar"), (RULE_EXCLUDE, "**/*.war"), (RULE_EXCLUDE, "**/*.ear"), (RULE_EXCLUDE, "**/*.class"),
    (RULE_EXCLUDE, "**/*.o"), (RULE_EXCLUDE, "**/*.a"), (RULE_EXCLUDE, "**/*.obj"),
    (RULE_EXCLUDE, "**/*.app"), (RULE_EXCLUDE, "**/*.dmg"), (RULE_EXCLUDE, "**/*.pkg"), (RULE_EXCLUDE, "**/*.deb"), (RULE_EXCLUDE, "**/*.rpm"),
    (RULE_EXCLUDE, "**/*.pyc"), (RULE_EXCLUDE, "**/*.pyo"),

    # Common Archive Files
    (RULE_EXCLUDE, "**/*.zip"), (RULE_EXCLUDE, "**/*.tar"), (RULE_EXCLUDE, "**/*.gz"), (RULE_EXCLUDE, "**/*.bz2"), (RULE_EXCLUDE, "**/*.xz"), (RULE_EXCLUDE, "**/*.rar"), (RULE_EXCLUDE, "**/*.7z"),

    # Common Document/Media Files (often large or binary)
    (RULE_EXCLUDE, "**/*.pdf"),
    (RULE_EXCLUDE, "**/*.doc"), (RULE_EXCLUDE, "**/*.docx"),
    (RULE_EXCLUDE, "**/*.xls"), (RULE_EXCLUDE, "**/*.xlsx"),
    (RULE_EXCLUDE, "**/*.ppt"), (RULE_EXCLUDE, "**/*.pptx"),
    (RULE_EXCLUDE, "**/*.odt"), (RULE_EXCLUDE, "**/*.ods"), (RULE_EXCLUDE, "**/*.odp"),
    (RULE_EXCLUDE, "**/*.jpg"), (RULE_EXCLUDE, "**/*.jpeg"), (RULE_EXCLUDE, "**/*.png"), (RULE_EXCLUDE, "**/*.gif"), (RULE_EXCLUDE, "**/*.bmp"), (RULE_EXCLUDE, "**/*.tiff"),
    (RULE_EXCLUDE, "**/*.svg"), (RULE_EXCLUDE, "**/*.webp"),
    (RULE_EXCLUDE, "**/*.mp3"), (RULE_EXCLUDE, "**/*.wav"), (RULE_EXCLUDE, "**/*.ogg"), (RULE_EXCLUDE, "**/*.flac"),
    (RULE_EXCLUDE, "**/*.mp4"), (RULE_EXCLUDE, "**/*.avi"), (RULE_EXCLUDE, "**/*.mkv"), (RULE_EXCLUDE, "**/*.mov"), (RULE_EXCLUDE, "**/*.wmv"), (RULE_EXCLUDE, "**/*.flv"),
    (RULE_EXCLUDE, "**/*.iso"), (RULE_EXCLUDE, "**/*.img"),

    # Hidden files/directories (catch-all, lowest priority default)
    # Users can include specific hidden files like '.gitignore' in their own .contextfiles
    (RULE_EXCLUDE, ".*"),     # Match hidden items at root
    (RULE_EXCLUDE, "**/.*"),  # Match hidden items in subdirs
]

Rule = Tuple[str, str] # (type, pattern) e.g. ('exclude', '*.log')
Ruleset = List[Rule]
RuleCache = Dict[Path, Optional[Ruleset]] # Cache parsed .contextfiles
CheckResult = Tuple[bool, Optional[str]] # (included: bool, reason: Optional[str]) - Define it here

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
            # Log error instead of printing to stderr
            logger.warning(f"Could not read or parse {contextfile_path}: {e}")
            ruleset = None # Explicitly None if error
    cache[abs_dir_path] = ruleset
    return ruleset

# Removed check_default_exclusions function as its logic is integrated into check_item
def check_item(
    item_path: Path,
    root_path: Path,
    inline_rules: Optional[Ruleset] = None,
    global_rules: Optional[Ruleset] = None,
    contextfile_cache: Optional[RuleCache] = None
) -> CheckResult:
    """
    Checks if an item should be included based on the full rule hierarchy.
    Returns a tuple: (included: bool, reason: Optional[str]).
    Reason explains the rule that determined the outcome.
    Precedence: Inline -> .contextfiles (closest first) -> Global -> Default.
    The *last* matching rule within the highest-precedence file determines the outcome.
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
         logger.warning(f"Item {abs_item_path} not relative to root {abs_root_path}")
         return False, "Excluded: Item outside root path"

    relative_path_str = str(relative_path).replace(os.sep, '/') # Use POSIX paths for matching
    is_dir = abs_item_path.is_dir()
    # Pattern to match against rules (append '/' for directories)
    pattern_to_match = f"{relative_path_str}/" if is_dir else relative_path_str

    # --- Store matches from each precedence level ---
    inline_match: Optional[CheckResult] = None
    local_match: Optional[CheckResult] = None
    global_match: Optional[CheckResult] = None
    default_match: Optional[CheckResult] = None

    # Helper function remains the same as before
    def _find_match_in_ruleset(rules: Optional[Ruleset], source_name: str, path_to_match: str, context_dir: Optional[Path] = None) -> Optional[CheckResult]:
        logger.debug(f"Checking item path '{path_to_match}' against ruleset from '{source_name}' (Context Dir: {context_dir})")
        if not rules:
            return None
        match_found: Optional[CheckResult] = None
        for rule_type, pattern in reversed(rules): # Last rule in file has highest precedence for this level
            # Determine the correct path string to match against
            current_path_to_match = path_to_match # Default: path relative to root
            if context_dir: # For local rules, match relative to the contextfile's directory
                try:
                    # Need absolute path of item for relative_to
                    rel_path = abs_item_path.relative_to(context_dir.resolve())
                    current_path_to_match = str(rel_path).replace(os.sep, '/')
                    if is_dir:
                        current_path_to_match += '/'
                except ValueError:
                    # Item not in or below context_dir, this rule doesn't apply directly
                    # This can happen if matching root patterns from a subdir contextfile
                    # Use the original path_to_match (relative to root) in this case
                    current_path_to_match = path_to_match

            # Check if pattern type matches item type or pattern is generic
            # Handle directory patterns ('/'), file patterns (no '/'), and generic patterns
            is_dir_pattern = pattern.endswith('/')
            # Adjust pattern for matching if it's a dir pattern
            match_pattern = pattern[:-1] if is_dir_pattern else pattern
            # Adjust item path for matching if it's a dir
            item_match_path = current_path_to_match[:-1] if is_dir and current_path_to_match.endswith('/') else current_path_to_match


            # 1. Pattern is for a directory, item is a directory
            # 2. Pattern is for a file, item is a file
            # 3. Pattern is generic (no '/'), item can be file or dir
            if (is_dir_pattern and is_dir) or \
               (not is_dir_pattern and not is_dir) or \
               (not is_dir_pattern):
                 # Use fnmatch for glob matching
                 match_result = fnmatch.fnmatch(item_match_path, match_pattern)
                 logger.debug(f"  Rule='{pattern}' ({rule_type}), ItemPath='{item_match_path}', MatchPattern='{match_pattern}', IsDir={is_dir}, IsDirPattern={is_dir_pattern} -> fnmatch result: {match_result}")
                 if match_result:
                    # If pattern was for a dir, ensure item is actually a dir
                    if is_dir_pattern and not is_dir:
                        logger.debug(f"    Dir pattern '{pattern}' cannot match file '{item_match_path}'. Skipping.")
                        continue # Dir pattern cannot match a file

                    # This is the last matching rule within this specific ruleset
                    included = rule_type == RULE_INCLUDE
                    reason = f"{'Included' if included else 'Excluded'} by {source_name}: '{pattern}'"
                    match_found = (included, reason)
                    logger.debug(f"    Match found! Result: {match_found}")
                    break # Stop checking this ruleset once the last match is found
        if not match_found:
             logger.debug(f"  No match found for ruleset '{source_name}'")
        return match_found

    # --- Check precedence levels ---
    # Store the match from each level if found.

    # 1. Check Inline Rules (Highest Precedence)
    inline_match = _find_match_in_ruleset(inline_rules, "Inline Rule", pattern_to_match)

    # 2. Check .contextfiles (Closest first)
    # We only care about the match from the *closest* contextfile where a rule matches.
    local_match: Optional[CheckResult] = None # Initialize local_match here
    current_dir = abs_item_path.parent
    while current_dir >= abs_root_path:
        ruleset = find_and_parse_contextfile(current_dir, contextfile_cache)
        if ruleset:
             contextfile_rel_path = current_dir.relative_to(abs_root_path) / ".contextfiles"
             source_name = f"Local Rule ({str(contextfile_rel_path).replace(os.sep, '/')})"
             match_in_this_dir = _find_match_in_ruleset(ruleset, source_name, pattern_to_match, context_dir=current_dir)
             if match_in_this_dir is not None:
                 local_match = match_in_this_dir # Store the match from the closest file
                 break # Stop walking up once the closest match is found

        if current_dir == abs_root_path: # Stop if we've checked the root directory
            break
        current_dir = current_dir.parent # Move up one directory

    # 3. Check Global Rules
    global_match = _find_match_in_ruleset(global_rules, "Global Rule", pattern_to_match)

    # 4. Check Default Exclusions (Lowest Precedence)
    default_match = _find_match_in_ruleset(DEFAULT_EXCLUDE_RULESET, "Default Rule", pattern_to_match)

    # 5. Determine final result based on precedence, prioritizing exclusions
    if inline_match is not None:
        # Highest precedence, return its result directly
        return inline_match
    # Check exclusions next, in order of precedence
    elif local_match is not None and not local_match[0]: # local_match is Exclude
        return local_match
    elif global_match is not None and not global_match[0]: # global_match is Exclude
        return global_match
    elif default_match is not None: # default_match is always Exclude if it exists
        return default_match
    # If no exclusions matched at higher levels, check inclusions
    elif local_match is not None and local_match[0]: # local_match is Include
        return local_match
    elif global_match is not None and global_match[0]: # global_match is Include
        return global_match
    else:
        # If no rules matched at any level, include by default
        return True, "Included by default (no matching rules)"
# --- End of check_item function ---