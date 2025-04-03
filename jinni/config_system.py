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
    (RULE_EXCLUDE, "**/.git/"),
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
    contextfile_cache: Optional[RuleCache] = None,
    explain_mode: bool = False # New flag to control detailed logging
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

    # --- Symlink Check ---
    # Skip symlinks early, before resolving, as per design
    if item_path.is_symlink():
        return False, "Excluded: Item is a symbolic link"

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

    # --- Refactored Helper Function ---
    def _find_match_in_ruleset(
        rules: Optional[Ruleset],
        source_name: str,
        # Explicit paths needed for correct relativity:
        item_abs_path: Path,
        item_is_dir: bool,
        root_abs_path: Path,
        context_dir_abs_path: Optional[Path], # Absolute path of the dir containing the ruleset, if local
        explain_mode: bool = False
    ) -> Optional[CheckResult]:
        # This function now takes absolute paths and calculates the correct relative path for matching.
        logger.debug(f"Checking item '{item_abs_path}' against ruleset from '{source_name}' (Context Dir: {context_dir_abs_path})")
        if not rules:
            return None

        # Determine the relative path string to use for matching this specific ruleset
        path_for_match: Optional[str] = None
        if context_dir_abs_path:
            # Local rule: path relative to the contextfile's directory
            try:
                rel_path = item_abs_path.relative_to(context_dir_abs_path)
                path_for_match = str(rel_path).replace(os.sep, '/')
            except ValueError:
                # Item not under context dir. A local rule shouldn't match based on relative path.
                # However, a pattern like '!sub/*' in root could be intended to match 'sub/file' when checked from root.
                # Let's try root-relative path as fallback for local rules if context-relative fails.
                # This handles cases where local rules might use patterns relative to the root.
                try:
                    rel_path_from_root = item_abs_path.relative_to(root_abs_path)
                    path_for_match = str(rel_path_from_root).replace(os.sep, '/')
                    logger.debug(f"  Item not in context dir {context_dir_abs_path}, using root-relative path '{path_for_match}' for matching local rule.")
                except ValueError:
                    logger.warning(f"  Item {item_abs_path} not relative to context {context_dir_abs_path} or root {root_abs_path}. Cannot match.")
                    return None # Cannot determine path to match against
        else:
            # Global/Default/Inline rule: path relative to the project root
            try:
                rel_path = item_abs_path.relative_to(root_abs_path)
                path_for_match = str(rel_path).replace(os.sep, '/')
            except ValueError:
                logger.warning(f"  Item {item_abs_path} not relative to root {root_abs_path}. Cannot match global/default/inline.")
                return None # Cannot determine path to match against

        # Ensure path_for_match has trailing slash if item is a directory for consistent matching
        if item_is_dir and not path_for_match.endswith('/'):
            path_for_match += '/'

        match_found: Optional[CheckResult] = None
        for rule_type, pattern in reversed(rules): # Last rule in file has highest precedence
            is_dir_pattern = pattern.endswith('/')
            match_result = False

            # Simpler matching logic: Rely on fnmatch and correctly formatted path_str_for_match
            path_str_for_match = path_for_match
            if item_is_dir and not path_str_for_match.endswith('/'):
                path_str_for_match += '/'
            elif not item_is_dir and path_str_for_match.endswith('/'): # Safety check
                path_str_for_match = path_str_for_match.rstrip('/')

            # Perform match using fnmatch - it handles **, *, ?, leading dots.
            match_result = fnmatch.fnmatch(path_str_for_match, pattern)

            # Post-fnmatch check: Prevent non-directory patterns matching directories by basename
            # e.g., prevent pattern "build" matching directory "build/"
            # Post-fnmatch check: Prevent non-directory patterns matching directories by basename
            # e.g., prevent pattern "build" matching directory "build/"
            if not is_dir_pattern and item_is_dir and match_result:
                basename = os.path.basename(path_str_for_match.rstrip('/'))
                if pattern == basename:
                    if explain_mode: logger.debug(f"    Pattern '{pattern}' is file pattern, item '{path_str_for_match}' is dir with matching basename. Overriding match to False.")
                    match_result = False # Override match if file pattern matches dir basename

            # If a match was determined (and potentially overridden), record it and stop checking this ruleset
            if match_result:
                included = rule_type == RULE_INCLUDE
                reason = f"{'Included' if included else 'Excluded'} by {source_name}: '{pattern}'"
                match_found = (included, reason)
                if explain_mode: logger.debug(f"    Match found! Result: {match_found}")
                break # Stop checking this ruleset

        if not match_found and explain_mode:
             logger.debug(f"  No match found for ruleset '{source_name}'")
        return match_found

    # --- Check precedence levels ---
    # Store the match from each level if found.

    # 1. Check Inline Rules (Highest Precedence) - Use root-relative matching
    inline_match = _find_match_in_ruleset(
        inline_rules, "Inline Rule",
        item_abs_path=abs_item_path, item_is_dir=is_dir, root_abs_path=abs_root_path,
        context_dir_abs_path=None, explain_mode=explain_mode
    )

    # 2. Check .contextfiles (Closest first)
    # We only care about the match from the *closest* contextfile where a rule matches.
    local_match: Optional[CheckResult] = None # Initialize local_match here
    current_dir = abs_item_path.parent
    while current_dir >= abs_root_path:
        ruleset = find_and_parse_contextfile(current_dir, contextfile_cache)
        if ruleset:
             contextfile_rel_path = current_dir.relative_to(abs_root_path) / ".contextfiles"
             source_name = f"Local Rule ({str(contextfile_rel_path).replace(os.sep, '/')})"
             match_in_this_dir = _find_match_in_ruleset(
                 ruleset, source_name,
                 item_abs_path=abs_item_path, item_is_dir=is_dir, root_abs_path=abs_root_path,
                 context_dir_abs_path=current_dir.resolve(), # Pass absolute path of context dir
                 explain_mode=explain_mode
             )
             if match_in_this_dir is not None:
                 local_match = match_in_this_dir # Store the match from the closest file
                 break # Stop walking up once the closest match is found

        if current_dir == abs_root_path: # Stop if we've checked the root directory
            break
        current_dir = current_dir.parent # Move up one directory

    # 3. Check Global Rules - Use root-relative matching
    global_match = _find_match_in_ruleset(
        global_rules, "Global Rule",
        item_abs_path=abs_item_path, item_is_dir=is_dir, root_abs_path=abs_root_path,
        context_dir_abs_path=None, explain_mode=explain_mode
    )

    # 4. Check Default Exclusions (Lowest Precedence) - Use root-relative matching
    default_match = _find_match_in_ruleset(
        DEFAULT_EXCLUDE_RULESET, "Default Rule",
        item_abs_path=abs_item_path, item_is_dir=is_dir, root_abs_path=abs_root_path,
        context_dir_abs_path=None, explain_mode=explain_mode
    )

    # 5. Determine final result based on precedence (highest first)
    final_decision: Optional[CheckResult] = None
    if inline_match is not None:
        # Inline rules have the absolute highest precedence
        final_decision = inline_match
    elif local_match is not None:
        # If a local rule (closest first) matched, its decision takes precedence
        final_decision = local_match
    elif global_match is not None:
        # If a global rule matched, its decision takes precedence
        final_decision = global_match
    elif default_match is not None:
        # If a default exclusion rule matched (and no higher rules did)
        final_decision = default_match
    else:
        # If no rules matched at any level, include by default
        final_decision = (True, "Included by default (no matching rules)")

    if explain_mode:
        # Use relative_path_str calculated earlier for consistent logging path format
        logger.debug(f"Final decision for '{relative_path_str}': {final_decision}")

    return final_decision
# --- End of check_item function ---