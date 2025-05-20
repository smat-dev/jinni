# jinni/utils.py
"""Utility functions for the Jinni context processing tool."""

import os
import sys
import datetime
import logging
import logging.handlers # Added for RotatingFileHandler
import mimetypes
import string
import platform, subprocess, shutil
import json # Added for JSON operations for caching
import hashlib # Added for file hashing for caching
import tiktoken # Added for token counting in call_gemini_api
from urllib.parse import urlparse, unquote, quote
from pathlib import Path, PureWindowsPath
from typing import List, Tuple, Dict, Optional, Any
from functools import lru_cache

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
    GITIGNORE_FILENAME,      # Needed by _find_gitignore_files_for_dir
)

# Setup logger for this module
# Consider passing logger instance or using getLogger(__name__)
logger = logging.getLogger("jinni.utils") # Use a specific logger for utils
if not logger.handlers and not logging.getLogger().handlers:
     # Basic config if running standalone or not configured by main app
     logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# --- Cache wslpath lookup ---
# Remove module-level lookup:
# _WSLPATH_PATH = shutil.which("wslpath")
# if _WSLPATH_PATH:
#     logger.debug(f"Found wslpath executable at: {_WSLPATH_PATH}")
# else:
#     logger.debug("wslpath command not found in PATH.")

@lru_cache(maxsize=1)
def _find_wslpath() -> Optional[str]:
    """Finds the wslpath executable using shutil.which and caches the result."""
    wslpath_path = shutil.which("wslpath")
    if wslpath_path:
        logger.debug(f"Found wslpath executable at: {wslpath_path}")
        return wslpath_path
    else:
        logger.debug("wslpath command not found in PATH.")
        return None

# _BAD_UNC_CHARS = '<>:\"/\\|?*%' # OLD
_BAD_UNC_CHARS = r'<>:"/\\|?*%'
_UNC_PREFIX = r'\\wsl$'  # Corrected raw string definition

def _build_unc_path(distro: str, linux_path: str) -> str:
    """
    Helper function to build the WSL UNC path using pathlib.
    Always emits paths in the \\wsl$\Distro\... format.
    Handles illegal characters in distro name.
    """
    safe_distro = distro.translate({ord(c): '_' for c in _BAD_UNC_CHARS})
    if not linux_path.startswith("/"):
        linux_path = "/" + linux_path

    relative_linux_path = linux_path.lstrip('/')
    base_unc_path = PureWindowsPath(f"{_UNC_PREFIX}\\{safe_distro}")

    try:
        if not relative_linux_path:  # root "/" case
            # Return exactly two trailing backslashes for UNC root
            return f"{base_unc_path}\\"
        else:
            # Join components using pathlib for robustness
            return str(base_unc_path.joinpath(*relative_linux_path.split('/')))
    except Exception as e:
        logger.error(
            "Error constructing UNC path with pathlib for distro=%r path=%r: %s",
            distro, linux_path, e,
        )
        # final, brute‑force fallback – guaranteed no further exceptions
        fallback = rf"{_UNC_PREFIX}\{safe_distro}{linux_path}".replace("/", "\\")
        return fallback

def _cached_wsl_to_unc(wslpath_executable: str, posix_path: str) -> str | None:
    """
    Translate *posix_path* using **wslpath**.  
    – Try "u", then "w".  
    – Verify that the returned string is a \\wsl$ UNC and that the share is
      reachable.
    – Return the verified UNC or **None**.
    """
    def _try(flag: str) -> str | None:
        try:
            # Use '--' to prevent misinterpretation of paths starting with '-'
            unc = subprocess.check_output(
                [wslpath_executable, flag, '--', posix_path],
                text=True,
                stderr=subprocess.PIPE,
                timeout=5 # Add a timeout
            ).strip()

            # Verify it's a \\wsl$ path and it actually exists
            # Use lower() for case-insensitive check of start
            if unc.lower().startswith(r"\\wsl$"):
                # Use Path().exists() for robustness with UNC paths
                # Add try-except around exists() for potential OS errors
                try:
                    if Path(unc).exists():
                        logger.debug(f"wslpath {flag} returned verified UNC path: {unc}")
                        return unc
                    else:
                         logger.debug(f"wslpath {flag} returned UNC path, but it does not exist: {unc}")
                except OSError as e_exists:
                    logger.warning(f"Error checking existence of UNC path '{unc}' from wslpath {flag}: {e_exists}")
                except Exception as e_generic_exists:
                    logger.error(f"Unexpected error checking existence of UNC path '{unc}': {e_generic_exists}", exc_info=True)
            else:
                logger.debug(f"wslpath {flag} returned non-UNC path: {unc}")

        except subprocess.CalledProcessError as e:
            # This often means the flag isn't supported or the path is invalid *within WSL*
            stderr_snippet = e.stderr.strip().splitlines()[0] if e.stderr else "(no stderr)"
            stderr_snippet = stderr_snippet[:100] + '...' if len(stderr_snippet) > 103 else stderr_snippet
            logger.debug(f"wslpath {flag} failed for '{posix_path}' (rc={e.returncode}): {stderr_snippet}")
        except subprocess.TimeoutExpired:
            logger.warning(f"wslpath {flag} timed out for '{posix_path}'")
        except FileNotFoundError:
            # Should not happen if wslpath_executable was found by _find_wslpath, but safety first
            logger.error(f"wslpath executable '{wslpath_executable}' not found during execution with {flag}.")
        except Exception as e_call:
             logger.error(f"Unexpected error calling wslpath {flag} for '{posix_path}': {e_call}", exc_info=True)

        return None # Return None if try block failed or checks didn't pass

    # 1️⃣ Try preferred UNC output (-u) first
    unc = _try('-u')
    if unc:
        return unc

    # 2️⃣ Fallback to Windows path output (-w) but still verify \\wsl$ and existence
    unc = _try('-w')
    if unc:
        return unc

    # 3️⃣ Both flags failed
    logger.debug(
        "wslpath -u/-w both failed to translate %r into a verified UNC.",
        posix_path,
    )
    return None

def ensure_no_nul(s: str, field: str = "value"):
    """
    Raises ValueError if the string contains an embedded NUL (\x00) or is None.
    Used to guard against Windows path bugs and invalid input.
    Typical usage: ensure_no_nul(path, "project_root")
    """
    if s is None:
        raise ValueError(f"Missing value for {field} (got None)")
    if "\x00" in s:
        logger.error(f"Embedded NUL (\\x00) found in {field}: {repr(s)}")
        raise ValueError(f"Embedded NUL (\\x00) found in {field}: {repr(s)}")

# --- Unit Test for ensure_no_nul ---
def _test_ensure_no_nul():
    try:
        ensure_no_nul("abc", "test")  # Should not raise
    except Exception:
        print("FAIL: ensure_no_nul raised unexpectedly on normal string")
        return False
    try:
        ensure_no_nul("a\x00b", "test")
        print("FAIL: ensure_no_nul did not raise on NUL string")
        return False
    except ValueError:
        pass  # Expected
    print("PASS: ensure_no_nul")
    return True

if __name__ == "__main__":
    _test_ensure_no_nul()

@lru_cache(maxsize=1)
def _get_default_wsl_distro() -> str:
    """
    Return the default WSL distro (never None):
    - Tries `wsl -l -q` (UTF-8/CP or UTF-16LE as needed).
    - Falls back to 'Ubuntu' if no distro is found.
    """
    distro = None
    try:
        proc = subprocess.run(
            ["wsl", "-l", "-q"],
            capture_output=True,  check=False,
            timeout=2,
        )
        if proc.returncode == 0:
            raw = proc.stdout
            # Detect UTF-16LE: BOM or NULs in first 4 bytes
            if raw.startswith(b'\xff\xfe') or b'\x00' in raw[:4]:
                txt = raw.decode("utf-16le", "replace")
            else:
                txt = raw.decode("utf-8", "replace")
            lines = [ln.strip() for ln in txt.splitlines() if ln.strip()]
            if lines:
                ensure_no_nul(lines[0], "WSL distro name")
            distro = lines[0] if lines else None
    except Exception:
        pass
    return distro or "Ubuntu"

# --- Logging Setup Utility ---
def setup_file_logging(logger_instance: logging.Logger, log_to_file_flag: bool, log_filename: str = "jinni.log") -> None:
    """
    Configures file logging for a given logger instance.

    Args:
        logger_instance: The logger object to configure.
        log_to_file_flag: Boolean indicating if file logging should be enabled.
        log_filename: The name of the log file.
    """
    if log_to_file_flag:
        log_file_path = Path(log_filename).resolve()
        try:
            # Ensure parent directory exists
            log_file_path.parent.mkdir(parents=True, exist_ok=True)

            # Create a RotatingFileHandler
            file_handler = logging.handlers.RotatingFileHandler(
                log_file_path,
                maxBytes=5 * 1024 * 1024,  # 5MB
                backupCount=3,
                encoding='utf-8' # Good practice to specify encoding
            )
            # Create a Formatter
            formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
            file_handler.setFormatter(formatter)
            file_handler.setLevel(logging.INFO) # Or logging.DEBUG if more verbosity needed in file

            # Add the handler to the logger instance
            logger_instance.addHandler(file_handler)
            # Log a message indicating file logging is active
            # Use the logger_instance itself to log this, so it goes to the new file handler too
            logger_instance.info(f"File logging active. Logging to: {log_file_path}")

        except Exception as e:
            # If file logging setup fails, log error to stderr (or existing handlers)
            # and continue without file logging.
            logger_instance.error(f"Failed to setup file logging to {log_file_path}: {e}", exc_info=True)


# --- Constants moved temporarily or redefined ---
# These might belong in a dedicated constants module later
BINARY_CHECK_CHUNK_SIZE = 1024

# --- Constants for Summarization Cache ---
SUMMARY_CACHE_FILENAME = ".jinni_summary_cache.json"
# For now, cache is in the current working directory from where jinni is run.
# Consider options like user config dir (e.g., appdirs) in the future.
DEFAULT_CACHE_DIR = Path(".") # Represents the current working directory

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
    1.  **Override Check:** If `--overrides` (CLI) or `rules` (MCP) are provided, these rules are used exclusively. **IMPORTANT:** All `.contextfiles` and built-in default rules (which exclude common directories like `.git/`, `node_modules/`, `.venv/`, etc.) are ignored. If you use overrides, you may need to explicitly add back common exclusions if you don't want those files included.
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

**Guidance for AI Model Usage**

When requesting context using the `read_context` tool:
*   **Default Behavior:** If you provide an empty `rules` list (`[]`), Jinni uses sensible default exclusions (like `.git`, `node_modules`, `__pycache__`, common binary types) combined with any project-specific `.contextfiles`. This usually provides the "canonical context" - files developers typically track in version control. Assume this is what the user wants if they just ask to read context.
*   **Targeting Specific Files:** If you need specific files (e.g., `["src/main.py", "README.md"]`), provide them in the `targets` list. This is efficient and precise.
*   **Using `rules` (Overrides):** If you provide specific `rules`, remember they *replace* the defaults. You gain full control but lose the default exclusions. For example, if you use `rules: ["*.py"]`, you might get Python files from `.venv/` unless you also add `"!*.venv/"`.
*   **Unsure What to Exclude?** If you're crafting `rules` and unsure what to exclude, consider inspecting the project's `.gitignore` file (if available) for patterns commonly ignored by developers. You might adapt these patterns for your `rules` list (remembering `!` means exclude in Jinni rules).
"""

# --- Helper Functions (Moved from core_logic.py) ---

def _calculate_file_hash(file_path: Path) -> str:
    """
    Calculates the SHA256 hash of a file.

    Args:
        file_path: The path to the file.

    Returns:
        The hexadecimal SHA256 hash string of the file.
        Returns an empty string if the file cannot be read.
    """
    logger.debug(f"Calculating SHA256 hash for: {file_path}")
    hasher = hashlib.sha256()
    try:
        with open(file_path, 'rb') as f:
            while chunk := f.read(8192): # Read in 8KB chunks
                hasher.update(chunk)
        hex_hash = hasher.hexdigest()
        logger.debug(f"Calculated hash for {file_path}: {hex_hash}")
        return hex_hash
    except OSError as e:
        logger.error(f"Could not read file {file_path} for hashing: {e}")
        return "" # Return empty string or raise? Empty for now.
    except Exception as e:
        logger.error(f"Unexpected error during hashing for {file_path}: {e}", exc_info=True)
        return ""

# --- Cache Utility Functions ---

def load_cache(cache_dir: Path) -> dict:
    """
    Loads the summary cache from a JSON file.

    Args:
        cache_dir: The directory where the cache file is located.

    Returns:
        A dictionary containing the cached summaries.
        Returns an empty dictionary if the cache file doesn't exist or is invalid.
    """
    cache_file_path = cache_dir / SUMMARY_CACHE_FILENAME
    logger.info(f"Attempting to load summary cache from: {cache_file_path}")
    if cache_file_path.exists() and cache_file_path.is_file():
        try:
            with open(cache_file_path, 'r', encoding='utf-8') as f:
                cache_data = json.load(f)
            logger.info(f"Successfully loaded summary cache from: {cache_file_path}")
            return cache_data
        except json.JSONDecodeError as e:
            logger.error(f"Error decoding JSON from cache file {cache_file_path}: {e}")
            return {}
        except OSError as e:
            logger.error(f"Error reading cache file {cache_file_path}: {e}")
            return {}
        except Exception as e:
            logger.error(f"Unexpected error loading cache file {cache_file_path}: {e}", exc_info=True)
            return {}
    else:
        logger.info(f"Cache file not found at: {cache_file_path}. Returning empty cache.")
        return {}

def save_cache(cache_dir: Path, cache_data: dict) -> None:
    """
    Saves the summary cache data to a JSON file.

    Args:
        cache_dir: The directory where the cache file will be saved.
        cache_data: The dictionary containing the cache data to save.
    """
    cache_file_path = cache_dir / SUMMARY_CACHE_FILENAME
    logger.info(f"Attempting to save summary cache to: {cache_file_path}")
    try:
        cache_dir.mkdir(parents=True, exist_ok=True) # Ensure directory exists
        with open(cache_file_path, 'w', encoding='utf-8') as f:
            json.dump(cache_data, f, indent=4)
        logger.info(f"Successfully saved summary cache to: {cache_file_path}")
    except OSError as e:
        logger.error(f"Error writing cache file {cache_file_path}: {e}")
    except Exception as e:
        logger.error(f"Unexpected error saving cache file {cache_file_path}: {e}", exc_info=True)

def get_summary_from_cache(cache_data: dict, file_path: Path, project_root: Path) -> Optional[str]:
    """
    Retrieves a summary from the cache if available and the file hash matches.

    Args:
        cache_data: The loaded cache data.
        file_path: The absolute path to the file.
        project_root: The absolute path to the project root directory.

    Returns:
        The cached summary string if found and valid, otherwise None.
    """
    if not file_path.is_absolute():
        logger.warning(f"File path for cache lookup is not absolute: {file_path}. This might lead to incorrect cache keys.")
    if not project_root.is_absolute():
        logger.warning(f"Project root for cache lookup is not absolute: {project_root}. This might lead to incorrect cache keys.")

    try:
        relative_path_str = str(file_path.relative_to(project_root)).replace(os.sep, '/')
    except ValueError as e:
        logger.error(f"Could not determine relative path for {file_path} in project {project_root}: {e}")
        return None

    logger.debug(f"Attempting to get summary for '{relative_path_str}' from cache.")
    cached_item = cache_data.get(relative_path_str)

    if cached_item:
        stored_hash = cached_item.get("hash")
        current_hash = _calculate_file_hash(file_path)

        if not current_hash: # File unreadable or other hash error
            logger.warning(f"Could not calculate current hash for {file_path}. Invalidating cache entry.")
            return None

        if stored_hash == current_hash:
            logger.info(f"Cache hit for: {relative_path_str} (Hash: {current_hash})")
            return cached_item.get("summary")
        else:
            logger.info(f"Cache miss for: {relative_path_str}. Hash mismatch (Stored: {stored_hash}, Current: {current_hash})")
            return None
    else:
        logger.info(f"Cache miss for: {relative_path_str}. Item not found in cache.")
        return None

def update_cache(cache_data: dict, file_path: Path, project_root: Path, summary: str) -> None:
    """
    Updates the cache with a new summary and file hash.

    Args:
        cache_data: The cache data dictionary to update.
        file_path: The absolute path to the file.
        project_root: The absolute path to the project root directory.
        summary: The summary string to cache for the file.
    """
    if not file_path.is_absolute():
        logger.warning(f"File path for cache update is not absolute: {file_path}. This might lead to incorrect cache keys.")
    if not project_root.is_absolute():
        logger.warning(f"Project root for cache update is not absolute: {project_root}. This might lead to incorrect cache keys.")

    try:
        relative_path_str = str(file_path.relative_to(project_root)).replace(os.sep, '/')
    except ValueError as e:
        logger.error(f"Could not determine relative path for {file_path} in project {project_root} for cache update: {e}")
        return

    current_hash = _calculate_file_hash(file_path)
    if not current_hash: # File unreadable or other hash error
        logger.warning(f"Could not calculate hash for {file_path}. Cannot update cache.")
        return

    logger.info(f"Updating cache for: {relative_path_str} (Hash: {current_hash})")
    cache_data[relative_path_str] = {
        "hash": current_hash,
        "summary": summary,
        "last_updated_utc": datetime.datetime.utcnow().isoformat() + "Z" # Added timestamp
    }
    # Note: The save_cache function needs to be called separately after updates.

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

def _find_gitignore_files_for_dir(dir_path: Path, root_path: Path) -> List[Path]:
    """Finds all .gitignore files from root_path down to dir_path."""
    gitignore_files = []
    current = dir_path.resolve()
    root = root_path.resolve()

    if not (current == root or root in current.parents):
         logger.warning(f"Directory {current} is not within the root {root}. Cannot find gitignore files.")
         return []

    paths_to_check = []
    temp_path = current
    while temp_path >= root:
        paths_to_check.append(temp_path)
        if temp_path == root:
            break
        parent = temp_path.parent
        if parent == temp_path:
            break
        temp_path = parent

    for p in reversed(paths_to_check):
        ignore_file = p / GITIGNORE_FILENAME
        if ignore_file.is_file():
            gitignore_files.append(ignore_file)
            logger.debug(f"Found gitignore file: {ignore_file}")

    return gitignore_files

# --- WSL Path Translation Helper ---

def _translate_wsl_path(path_str: str) -> str:
    """
    Convert POSIX paths *or* vscode-remote WSL URIs to a Windows path when running on Windows.
    Always returns a string; the caller is responsible for converting to Path if needed.
    Handles lazy lookup and caching of wslpath execution.
    Supports:
    - vscode-remote://wsl+Distro/path
    - vscode-remote://wsl.localhost/Distro/path
    - vscode://vscode-remote/wsl+Distro/path
    - /posix/path
    Can be disabled by setting environment variable JINNI_NO_WSL_TRANSLATE=1.
    """
    # --- Initial Guards ---
    if not path_str:
        return "" # Return empty string if input is empty
    if os.environ.get("JINNI_NO_WSL_TRANSLATE") == "1":
        logger.debug("WSL path translation explicitly disabled via JINNI_NO_WSL_TRANSLATE=1")
        return path_str

    host_is_windows = platform.system().lower() == "windows"

    # ───────────────────────────────────────────────────────────────
    #  Handle non‑Windows systems (Linux, macOS) - Return stripped URI or original
    # ───────────────────────────────────────────────────────────────
    if not host_is_windows:
        stripped = _strip_wsl_uri_to_posix(path_str)
        # Return stripped POSIX path if successful, otherwise the original path
        return stripped if stripped is not None else path_str

    # ───────────────────────────────────────────────────────────────
    #  Handle Windows systems - Return translated UNC path or original
    # ───────────────────────────────────────────────────────────────

    # Check if it's already a UNC path
    if path_str.startswith(r"\\wsl"):
        logger.debug(f"Path '{path_str}' already looks like a WSL UNC path. Returning original.")
        return path_str

    parsed = urlparse(path_str)
    logger.debug(f"Parsing path/URI '{path_str}': scheme='{parsed.scheme}', netloc='{parsed.netloc}', path='{parsed.path}'")

    # --- Empty Distro Name Check (for relevant schemes) ---
    if parsed.scheme == "vscode-remote" and parsed.netloc.lower().startswith("wsl+") and not parsed.netloc[4:]:
        raise ValueError("missing distro name in WSL URI")
    # Note: wsl.localhost format check happens inside the block below
    # Note: alternate vscode:// format check happens inside the block below

    # 1) Handle vscode-remote:// URIs
    if parsed.scheme == "vscode-remote":
        netloc_decoded = unquote(parsed.netloc)
        distro: Optional[str] = None
        linux_path: Optional[str] = None
        uri_type: Optional[str] = None # Initialize uri_type

        if netloc_decoded.lower().startswith("wsl+"):
            # Distro check already performed above
            distro = netloc_decoded[len("wsl+"):]
            linux_path = unquote(parsed.path)
            uri_type = "wsl+"
            ensure_no_nul(distro, "WSL distro name from URI")
            ensure_no_nul(linux_path, "WSL linux_path from URI")
        elif netloc_decoded.lower() == "wsl.localhost":
            # Path should be /<distro>/<actual_path>
            # Reject paths starting with // immediately as they lack a distro
            if parsed.path.startswith("//"):
                logger.warning(f"Invalid wsl.localhost URI path (starts with //): '{parsed.path}'")
                raise ValueError("missing distro name in wsl.localhost URI path")
            # Need at least two parts after stripping leading /
            path_parts = parsed.path.lstrip("/").split("/", 1)
            if len(path_parts) == 2 and path_parts[0]: # Check we have exactly two parts and distro is non-empty
                distro = path_parts[0]
                linux_path = "/" + unquote(path_parts[1]) # Path part can be empty, becomes "/"
                uri_type = "wsl.localhost"
                ensure_no_nul(distro, "WSL distro name from wsl.localhost URI")
                ensure_no_nul(linux_path, "WSL linux_path from wsl.localhost URI")
            elif len(path_parts) == 1 and path_parts[0]: # Handle case like /DistroName
                distro = path_parts[0]
                linux_path = "/" # No path part means root
                uri_type = "wsl.localhost"
                ensure_no_nul(distro, "WSL distro name from wsl.localhost URI")
                ensure_no_nul(linux_path, "WSL linux_path from wsl.localhost URI")
            else:
                # Malformed wsl.localhost (missing distro or wrong format)
                logger.warning(f"Could not extract valid distro/path from wsl.localhost URI path: '{parsed.path}'")
                raise ValueError("missing or invalid distro/path in wsl.localhost URI path")

        # Build UNC if distro and path were found
        if distro and linux_path is not None:
            logger.debug(f"Extracted distro='{distro}', linux_path='{linux_path}' from vscode-remote ({uri_type}) URI.")
            windows_unc_path = _build_unc_path(distro, linux_path)
            logger.debug(f"Translated vscode-remote URI '{path_str}' to UNC: '{windows_unc_path}'")
            return windows_unc_path
        # If it was vscode-remote scheme but not wsl+ or wsl.localhost (e.g., ssh-remote), fall through to return original

    # 2) Handle vscode://vscode-remote/wsl+Distro/path
    elif parsed.scheme == "vscode" and parsed.netloc == "vscode-remote":
        path_parts = parsed.path.strip("/").split("/", 1)
        if len(path_parts) >= 1 and path_parts[0].lower().startswith("wsl+"):
            authority = path_parts[0]
            distro = authority[len("wsl+"):]
            if not distro:
                # Malformed alternate vscode uri (missing distro)
                raise ValueError("missing distro name in alternate vscode URI authority")
            linux_path = "/" + unquote(path_parts[1]) if len(path_parts) > 1 else "/"
            ensure_no_nul(distro, "WSL distro name from alternate vscode URI")
            ensure_no_nul(linux_path, "WSL linux_path from alternate vscode URI")
            logger.debug(f"Extracted distro='{distro}', linux_path='{linux_path}' from alternate vscode URI.")
            windows_unc_path = _build_unc_path(distro, linux_path)
            logger.debug(f"Translated alternate vscode URI '{path_str}' to UNC: '{windows_unc_path}'")
            return windows_unc_path
        # If not wsl+ authority, fall through

    # 3) Handle pure POSIX path /path/to/file
    elif path_str.startswith("/") and not parsed.scheme:
        wslpath_exe = _find_wslpath() # Lazy lookup
        if wslpath_exe:
            # Call the new function which tries -u, then -w, and verifies existence
            verified_unc_path = _cached_wsl_to_unc(wslpath_exe, path_str)
            if verified_unc_path:
                logger.debug(f"Translated POSIX path '{path_str}' to verified UNC: '{verified_unc_path}'")
                ensure_no_nul(verified_unc_path, "UNC path from wslpath")
                return verified_unc_path # Return the verified UNC path
            else:
                # wslpath call failed or didn't produce a usable path.
                # _cached_wsl_to_unc logged the details.
                logger.debug(f"wslpath (via _cached_wsl_to_unc) did not return a verified UNC path for '{path_str}'. Attempting manual fallback.")
                # Continue to manual fallback below...
        else:
             logger.debug("wslpath executable not found. Attempting manual fallback.")

        # --- Manual Fallback (wslpath failed/not found OR _cached_wsl_to_unc returned None) ---
        assumed_distro = os.getenv("JINNI_ASSUME_WSL_DISTRO") or _get_default_wsl_distro()
        if assumed_distro is None:
            raise RuntimeError(
                "Cannot map POSIX path to Windows: No WSL distro found (JINNI_ASSUME_WSL_DISTRO not set and could not detect default WSL distro). "
                "Ensure WSL is installed and functional, or set JINNI_ASSUME_WSL_DISTRO."
            )
        ensure_no_nul(path_str, "POSIX path for manual fallback")
        ensure_no_nul(assumed_distro, "WSL distro name for manual fallback")

        if assumed_distro:
            logger.debug(
                "Using assumed WSL distro %r for manual UNC path construction.",
                assumed_distro,
            )
            candidate_unc_path = _build_unc_path(assumed_distro, path_str)
            ensure_no_nul(candidate_unc_path, "UNC path from manual fallback")

            # Probe only the share root; individual files may lag.
            share_root = Path(fr"\\wsl$\{assumed_distro}")
            if not share_root.exists():
                logger.debug(
                    "UNC share root %s still not visible — continuing anyway",
                    share_root,
                )

            return candidate_unc_path   # return even if the root isn't up yet
        else:
            logger.debug("Could not determine a WSL distro from env var or 'wsl -l -q'. Cannot construct manual UNC path.")
            # Fall through to raise RuntimeError outside the 'if assumed_distro' block

        # If manual fallback failed (no distro OR path doesn't exist/check failed)
        # Truncate potentially long path in error message
        truncated_path = path_str[:50] + '...' if len(path_str) > 53 else path_str
        raise RuntimeError(
            f"Cannot map POSIX path starting with '{truncated_path}' to Windows. WSL may not be available or path is invalid within the default/assumed distro. "
            f"Ensure WSL is installed and functional, or run Jinni inside the WSL distro. "
            f"You can also set JINNI_ASSUME_WSL_DISTRO if the default distro is incorrect."
        )

    # 4) No translation needed or possible (Windows path, other URI scheme, etc.)
    logger.debug(f"Path '{path_str}' did not match WSL translation conditions on Windows. Returning original.")
    return path_str

# ───────────────────────────────────────────────────────────────
#  Helper: strip VS Code WSL URIs to plain /posix/path
# ───────────────────────────────────────────────────────────────
def _strip_wsl_uri_to_posix(uri: str) -> Optional[str]:
    """
    If *uri* is a VS Code WSL URI (`vscode-remote:` or `vscode:` scheme),
    return the embedded POSIX path (`/home/...`). Otherwise return ``None``.
    Works even when the '+' is percent-encoded.
    Handles `wsl+<Distro>` style for both schemes.
    Handles `wsl.localhost/<Distro>` style for `vscode-remote:` scheme.
    """
    try:
        p = urlparse(uri)
        logger.debug(f"[_strip_wsl_uri_to_posix] Parsed URI: scheme='{p.scheme}', netloc='{p.netloc}', path='{p.path}'")

        # vscode-remote://wsl+Ubuntu/home/you
        # vscode-remote://wsl.localhost/Ubuntu/home/you
        if p.scheme == "vscode-remote":
            netloc_dec = unquote(p.netloc)
            # logger.debug(f"[_strip_wsl_uri_to_posix] vscode-remote: netloc_dec='{''.join(c if ' ' <= c <= '~' else repr(c) for c in netloc_dec)}'") # Log safely

            # Handle wsl+
            if netloc_dec.lower().startswith("wsl+"):
                # Check for missing distro name after wsl+
                if not netloc_dec[4:]:
                    logger.debug("[_strip_wsl_uri_to_posix] Matched vscode-remote wsl+ but missing distro name.")
                    return None # Or raise? For stripping, None is safer.
                result = unquote(p.path) or "/"
                logger.debug(f"[_strip_wsl_uri_to_posix] Matched vscode-remote wsl+. Returning: '{result}'")
                return result

            # Handle wsl.localhost
            elif netloc_dec.lower() == "wsl.localhost":
                # Path must be /<distro>/<path_part> or /<distro>
                if not p.path.startswith("/") or p.path.startswith("//"):
                    logger.debug(f"[_strip_wsl_uri_to_posix] Matched vscode-remote wsl.localhost but path format invalid: '{p.path}'")
                    return None # Invalid path format

                parts = p.path.lstrip("/").split("/", 1)
                # Ensure we have at least a non-empty distro part
                if len(parts) >= 1 and parts[0]:
                    # If only distro, path is "/". If path part exists, use it.
                    posix_path = "/" + unquote(parts[1]) if len(parts) > 1 and parts[1] else "/"
                    logger.debug(f"[_strip_wsl_uri_to_posix] Matched vscode-remote wsl.localhost. Returning: '{posix_path}'")
                    return posix_path
                else:
                    logger.debug("[_strip_wsl_uri_to_posix] Matched vscode-remote wsl.localhost but no distro found in path.")
                    return None # Missing distro in path

        # vscode://vscode-remote/wsl+Ubuntu/home/you
        if p.scheme == "vscode" and p.netloc == "vscode-remote":
            # logger.debug(f"[_strip_wsl_uri_to_posix] vscode: path='{p.path}'")
            parts = p.path.lstrip("/").split("/", 1)
            # Check authority part starts with wsl+ and has a distro name
            if parts and parts[0].lower().startswith("wsl+") and parts[0][4:]:
                result = "/" + unquote(parts[1]) if len(parts) > 1 else "/"
                logger.debug(f"[_strip_wsl_uri_to_posix] Matched vscode wsl+. Returning: '{result}'")
                return result
            else:
                logger.debug("[_strip_wsl_uri_to_posix] Matched vscode scheme but not valid wsl+ format.")

        # logger.debug(f"[_strip_wsl_uri_to_posix] No matching WSL URI format found. Returning None.")
        return None
    except Exception as e:
        logger.error(f"[_strip_wsl_uri_to_posix] Error processing URI '{uri}': {e}", exc_info=True)
        return None # Return None on unexpected error

# --- Gemini API Utility ---
def call_gemini_api(prompt_text: str, api_key: Optional[str] = None) -> str:
    """
    Calls the Gemini API to generate content based on the provided prompt.

    Args:
        prompt_text: The text prompt to send to the Gemini API.
        api_key: The API key for the Gemini API. If not provided,
                 it will be retrieved from the GEMINI_API_KEY environment variable.

    Returns:
        The text response from the Gemini API.

    Raises:
        ValueError: If the API key is not found.
        # TODO: Potentially raise a custom exception for API errors.
    """
    logger.info("Initiating Gemini API call.")

    if not api_key:
        api_key = os.environ.get("GEMINI_API_KEY")

    if not api_key:
        logger.error("Gemini API key not found in arguments or environment variables.")
        raise ValueError("Gemini API key not provided and not found in GEMINI_API_KEY environment variable.")

    try:
        import google.generativeai as genai
    except ImportError:
        logger.error("google-generativeai library not found. Please install it: pip install google-generativeai")
        return "Error: google-generativeai library not installed."

    # Log prompt length
    prompt_char_len = len(prompt_text)
    prompt_byte_len = len(prompt_text.encode('utf-8'))
    num_prompt_tokens = 0
    try:
        enc = tiktoken.get_encoding("cl100k_base") # Standard encoder
        num_prompt_tokens = len(enc.encode(prompt_text))
    except Exception as e_tiktoken:
        logger.debug(f"Could not count prompt tokens with tiktoken: {e_tiktoken}. Token count will be 0.")
    
    logger.info(f"Gemini API call initiated. Prompt length: {prompt_char_len} chars / {prompt_byte_len} bytes / {num_prompt_tokens} tokens.")
    logger.debug(f"Generating content with Gemini for prompt (first 100 chars): '{prompt_text[:100]}...'")


    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-1.5-flash') # Using gemini-1.5-flash as per current availability
        response = model.generate_content(prompt_text)
        
        summary_char_len = len(response.text)
        # Assuming summary is text, so byte length similar to char length for ASCII, varies for UTF-8
        logger.info(f"Gemini API call successful. Summary length: {summary_char_len} chars.")
        return response.text
    except Exception as e: # Catching a broad exception for now, can be refined
        # Check for specific Google API errors if the library provides them, e.g., google.api_core.exceptions
        # For now, using a general exception catch.
        # Example of how you might check for a specific error type if you knew it:
        # if isinstance(e, google.api_core.exceptions.PermissionDenied):
        #     logger.error(f"Gemini API permission denied: {e}")
        #     return f"Error: Gemini API Permission Denied - {e}"
        # elif isinstance(e, google.api_core.exceptions.GoogleAPIError):
        #    logger.error(f"Gemini API call failed due to a Google API error: {e}")
        #    return f"Error: Gemini API call failed - {e}"

        logger.error(f"Gemini API call failed: {e}", exc_info=True) # Log with stack trace
        return f"Error: Gemini API call failed - {e}"
