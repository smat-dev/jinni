# jinni/utils.py
"""Utility functions for the Jinni context processing tool."""

import os
import sys
import datetime
import logging
import mimetypes
import string
from pathlib import Path
from typing import List, Tuple, Dict, Optional, Any

# Attempt to import pathspec needed by get_large_files
try:
    import pathspec
except ImportError:
    print("Error: 'pathspec' library not found. Required by utils.get_large_files.")
    print("Please install it: pip install pathspec")
    # Allow the module to load but get_large_files will fail if called
    pathspec = None

# Import constants and config functions needed by helpers
# Assuming these will eventually live elsewhere or be passed in,
# but for now, import directly if needed by moved functions.
# We might need to adjust these imports later during the refactor.
from .config_system import (
    compile_spec_from_rules, # Needed by get_large_files
    DEFAULT_RULES,           # Needed by get_large_files
    CONTEXT_FILENAME,        # Needed by _find_context_files_for_dir
)

# Setup logger for this module
# Consider passing logger instance or using getLogger(__name__)
logger = logging.getLogger("jinni.utils") # Use a specific logger for utils
if not logger.handlers and not logging.getLogger().handlers:
     # Basic config if running standalone or not configured by main app
     logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')


# --- Constants moved temporarily or redefined ---
# These might belong in a dedicated constants module later
BINARY_CHECK_CHUNK_SIZE = 1024

APPLICATION_TEXT_MIMES = {
    'application/json', 'application/xml', 'application/xhtml+xml', 'application/rtf',
    'application/atom+xml', 'application/rss+xml', 'application/x-yaml',
    'application/x-www-form-urlencoded', 'application/javascript', 'application/ecmascript',
    'application/sql', 'application/graphql', 'application/ld+json', 'application/csv',
}

# --- Constants for Shared Usage Documentation ---
ESSENTIAL_USAGE_DOC = """
**Jinni: Configuration (`.contextfiles` & Overrides)**

Jinni uses `.contextfiles` (or an override file) to determine which files and directories to include or exclude, based on `.gitignore`-style patterns.

*   **Core Principle:** Rules are applied dynamically during traversal. The effective rules for any given file/directory depend on the `.contextfiles` found in its parent directories (up to a common root) or the override rules.
*   **Location (`.contextfiles`):** Place `.contextfiles` in any directory. Rules apply to that directory and its subdirectories, inheriting rules from parent directories.
*   **Format:** Plain text, UTF-8 encoded, one pattern per line.
*   **Syntax:** Uses standard `.gitignore` pattern syntax (specifically `pathspec`'s `gitwildmatch` implementation). **This syntax applies to rules in `.contextfiles`, the `rules` MCP argument, and the `--overrides` CLI file.**
    *   **Comments:** Lines starting with `#` are ignored.
    *   **Inclusion Patterns:** Specify files/directories to include (e.g., `src/**/*.py`, `*.md`, `/config.yaml`).
    *   **Exclusion Patterns:** Lines starting with `!` indicate that a matching file should be excluded (negates the pattern).
    *   **Anchoring:** A leading `/` anchors the pattern to the directory containing the `.contextfiles`.
    *   **Directory Matching:** A trailing `/` matches directories only.
    *   **Wildcards:** `*`, `**`, `?` work as in `.gitignore`.
*   **Rule Application Logic:**
    1.  **Override Check:** If `--overrides` (CLI) or `rules` (MCP) are provided, these rules are used exclusively. All `.contextfiles` and built-in defaults are ignored.
    2.  **Dynamic Context Rules (No Overrides):** When processing a file or directory, Jinni:
        *   Finds all `.contextfiles` starting from a common root directory down to the current item's directory.
        *   Combines the rules from these files (parent rules first, child rules last) along with built-in default rules.
        *   Compiles these combined rules into a temporary specification (`PathSpec`).
        *   Matches the current file/directory path (relative to the common root) against this specification.
    3.  **Matching:** The **last pattern** in the combined rule set that matches the item determines its fate. If the last matching pattern starts with `!`, the item is excluded. Otherwise, it's included. If no user-defined pattern in the combined rule set matches the item, it is included *unless* it matches one of the built-in default exclusion patterns (e.g., `.git/`, `node_modules/`, common binary extensions). If no pattern matches at all (neither user nor default), the item is included.
    4.  **Target Handling:** If specific `targets` are provided (CLI or MCP), they are validated to be within the `project_root`. If a target is a file, only that file is processed (rule checks don't apply to the target file itself, but binary/size checks do). If a target is a directory, the walk starts there, but rules are still applied relative to the `project_root`.

**Examples (`.contextfiles`)**

**Example 1: Include Python Source and Root Config**

Located at `my_project/.contextfiles`:

```
# Include all Python files in the src directory and subdirectories
src/**/*.py

# Include the main config file at the root of the project
/config.json

# Include all markdown files anywhere
*.md

# Exclude any test data directories found anywhere
!**/test_data/
```

**Example 2: Overriding in a Subdirectory**

Located at `my_project/src/.contextfiles`:

```
# In addition to rules inherited from parent .contextfiles...

# Include specific utility scripts in this directory
utils/*.sh

# Exclude a specific generated file within src, even if *.py is included elsewhere
!generated_parser.py
```
"""

# --- Helper Functions (Moved from core_logic.py) ---

def get_file_info(file_path: Path) -> Dict[str, Any]:
    """Get file information including size and last modified time."""
    try:
        stats = os.stat(file_path)
        size = int(stats.st_size)
        last_modified = datetime.datetime.fromtimestamp(stats.st_mtime).strftime('%Y-%m-%d %H:%M:%S')
        return {'size': size, 'last_modified': last_modified}
    except Exception as e:
        logger.warning(f"Could not get stats for {file_path}: {e}")
        return {'size': 0, 'last_modified': 'N/A'}

def is_human_readable(filepath: Path, blocksize=BINARY_CHECK_CHUNK_SIZE) -> bool:
    """
    Heuristic check based on printable character ratio in the first block.
    Returns True if the ratio is high (likely text), False otherwise.
    """
    try:
        with open(filepath, 'rb') as file:
            chunk_bytes = file.read(blocksize)
            if not chunk_bytes:
                logger.debug(f"File {filepath} is empty, considered non-readable by heuristic.")
                return False  # Empty files are not readable

            # Attempt to decode as UTF-8
            chunk_str = chunk_bytes.decode('utf-8')

            # Count printable characters
            printable_count = sum(c in string.printable for c in chunk_str)
            total_len = len(chunk_str)
            if total_len == 0: # Should not happen if chunk_bytes was not empty, but safety check
                 logger.debug(f"File {filepath} resulted in zero-length string after decode, considered non-readable.")
                 return False

            printable_ratio = printable_count / total_len
            is_readable = printable_ratio > 0.95 # Use user-provided threshold
            logger.debug(f"File {filepath} printable ratio: {printable_ratio:.3f}. Considered readable: {is_readable}")
            return is_readable
    except UnicodeDecodeError:
        logger.debug(f"File {filepath} failed UTF-8 decoding. Considered non-readable by heuristic.")
        return False
    except OSError as e:
        logger.warning(f"Could not read file {filepath} for human-readable check: {e}. Assuming non-readable.")
        return False
    except Exception as e:
        logger.error(f"Unexpected error during human-readable check for {filepath}: {e}. Assuming non-readable.")
        return False


def _is_binary(file_path: Path) -> bool:
    """
    Check if a file is likely binary.
    1. Check MIME type: If text/* or in APPLICATION_TEXT_MIMES -> Not Binary (False)
    2. Fallback (MIME is None or ambiguous):
        a. Check for null bytes in first chunk -> Binary (True) if found.
        b. If no null bytes, use is_human_readable heuristic -> Binary (True) if heuristic returns False.
    """
    filepath_str = str(file_path)
    mime_type, encoding = mimetypes.guess_type(filepath_str)
    logger.debug(f"Checking file type for {file_path}. Guessed MIME: {mime_type}, Encoding: {encoding}")

    if mime_type:
        # Check primary text types
        if mime_type.startswith('text/'):
            logger.debug(f"File {file_path} identified as TEXT by MIME type: {mime_type}")
            return False
        # Check known application text types
        if mime_type in APPLICATION_TEXT_MIMES:
            logger.debug(f"File {file_path} identified as TEXT by known application MIME type: {mime_type}")
            return False
        # MIME is known but not identified as text
        logger.debug(f"MIME type {mime_type} not identified as text. Falling back to secondary checks.")
    else:
        # MIME type could not be guessed
        logger.debug(f"No MIME type guessed for {file_path}. Falling back to secondary checks.")

    # Fallback checks for None or ambiguous MIME types
    try:
        with open(file_path, 'rb') as f:
            chunk = f.read(BINARY_CHECK_CHUNK_SIZE)
            # Check for null bytes first
            if b'\x00' in chunk:
                logger.debug(f"File {file_path} contains null bytes. Considered BINARY.")
                return True
            # If no null bytes, use the printable ratio heuristic
            # Re-call is_human_readable as it handles its own reading/errors
            is_readable_heuristic = is_human_readable(file_path)
            if is_readable_heuristic:
                 logger.debug(f"File {file_path} considered TEXT by heuristic fallback (no null bytes).")
                 return False # Heuristic says it's readable -> Not Binary
            else:
                 logger.debug(f"File {file_path} considered BINARY by heuristic fallback (no null bytes).")
                 return True # Heuristic says it's not readable -> Binary
    except OSError as e:
         logger.warning(f"Could not read file {file_path} for fallback binary check: {e}. Assuming TEXT (safer default).")
         return False # Default to False (text) on read error during fallback
    except Exception as e:
         logger.error(f"Unexpected error during fallback binary check for {file_path}: {e}. Assuming TEXT.")
         return False # Default to False (text) on unexpected error


# get_usage_doc function removed as it's no longer used.
# The CLI and Server now use hardcoded essential usage info.


def get_large_files(root_dir_str: str = ".", top_n: int = 10) -> List[Tuple[str, int]]:
    """
    Finds the largest files in the project directory, ignoring .git and applying default rules.

    Args:
        root_dir_str: The root directory to search (defaults to current).
        top_n: The number of largest files to return.

    Returns:
        A list of tuples: (relative_path_str, size_in_bytes), sorted descending by size.
    """
    if pathspec is None:
        logger.error("pathspec library is not available. Cannot execute get_large_files.")
        return []

    root_dir = Path(root_dir_str).resolve()
    logger.info(f"Scanning for large files under: {root_dir}")
    file_sizes = []
    # Compile default spec to ignore common patterns like .git
    default_spec = compile_spec_from_rules(DEFAULT_RULES, "Defaults")

    for dirpath_str, dirnames, filenames in os.walk(root_dir, topdown=True, followlinks=False):
        current_dir_path = Path(dirpath_str).resolve()

        # Prune based on default rules
        dirnames_to_remove = []
        for dirname in dirnames:
            sub_dir_path = (current_dir_path / dirname).resolve()
            try:
                path_for_match = str(sub_dir_path.relative_to(root_dir)).replace(os.sep, '/') + '/'
                if not default_spec.match_file(path_for_match):
                    dirnames_to_remove.append(dirname)
            except ValueError:
                pass # Cannot make relative, likely outside root_dir somehow? Skip check.
            except Exception as e_prune:
                 logger.warning(f"Error checking directory {sub_dir_path} against default spec: {e_prune}")

        if dirnames_to_remove:
            dirnames[:] = [d for d in dirnames if d not in dirnames_to_remove]

        # Check files
        for filename in filenames:
            file_path = (current_dir_path / filename).resolve()
            try:
                path_for_match = str(file_path.relative_to(root_dir)).replace(os.sep, '/')
                if default_spec.match_file(path_for_match):
                    if file_path.is_file() and not file_path.is_symlink():
                        try:
                            size = file_path.stat().st_size
                            relative_path_str = str(file_path.relative_to(root_dir)).replace(os.sep, '/')
                            file_sizes.append((relative_path_str, size))
                        except OSError as e_stat:
                            logger.debug(f"Could not stat file {file_path}: {e_stat}")
            except ValueError:
                 pass # Cannot make relative, skip check.
            except Exception as e_match:
                 logger.warning(f"Error checking file {file_path} against default spec: {e_match}")


    # Sort by size descending and return top N
    file_sizes.sort(key=lambda item: item[1], reverse=True)
    return file_sizes[:top_n]

def _find_context_files_for_dir(dir_path: Path, root_path: Path) -> List[Path]:
    """Finds all .contextfiles from root_path down to dir_path."""
    context_files = []
    current = dir_path.resolve()
    root = root_path.resolve()

    # Ensure dir_path is within or at root_path
    if not (current == root or root in current.parents):
         logger.warning(f"Directory {current} is not within the root {root}. Cannot find context files.")
         return []

    # Walk upwards from dir_path to root, collecting paths
    paths_to_check = []
    temp_path = current
    while temp_path >= root:
        paths_to_check.append(temp_path)
        if temp_path == root: break
        parent = temp_path.parent
        if parent == temp_path: break # Should not happen with pathlib resolve
        temp_path = parent

    # Reverse the list so it's root-down, and check for .contextfile
    for p in reversed(paths_to_check):
        context_file = p / CONTEXT_FILENAME
        if context_file.is_file():
            context_files.append(context_file)
            logger.debug(f"Found context file: {context_file}")

    return context_files