# jinni/utils.py
"""Utility functions for the Jinni context processing tool."""

import os
import sys
import datetime
import logging
import mimetypes
import string
import platform, subprocess, shutil
from urllib.parse import urlparse, unquote, quote
from pathlib import Path
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

_BAD_UNC_CHARS = '<>:"/\\|?*%'

def _build_unc_path(distro: str, linux_path: str) -> str:
    """
    Helper function to build the WSL UNC path, sanitizing the distro name for UNC.
    Always emits paths in the \\wsl$\Distro\... format (never \\wsl.localhost\...).
    """
    # Replace only illegal UNC chars in the distro name
    safe_distro = distro.translate({ord(c): '_' for c in _BAD_UNC_CHARS})
    # Ensure linux_path starts with /
    if not linux_path.startswith("/"):
        linux_path = "/" + linux_path
    # Build UNC path, replacing forward slashes in the linux_path part
    # Note: Always emits \\wsl$\... (never \\wsl.localhost\...)
    windows_unc_path = rf"\\wsl$\{safe_distro}{linux_path}".replace("/", "\\")
    return windows_unc_path

@lru_cache(maxsize=256) # Cache results for POSIX paths
def _cached_wsl_to_unc(wslpath_executable: str, posix_path: str) -> Optional[str]:
    """Calls wslpath -w to convert a POSIX path to a Windows path and caches the result."""
    try:
        windows_unc_path = subprocess.check_output([wslpath_executable, "-w", posix_path], text=True, stderr=subprocess.PIPE).strip()
        logger.debug(f"Translated POSIX path '{posix_path}' via wslpath to: '{windows_unc_path}'")
        return windows_unc_path
    except subprocess.CalledProcessError as e:
        logger.debug(f"wslpath failed for '{posix_path}' (return code {e.returncode}): {e.stderr.strip()}. Returning original path.")
        return None # Indicate failure
    except Exception as e:
        logger.warning(f"Unexpected error calling wslpath for '{posix_path}': {e}. Returning original path.")
        return None # Indicate failure


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

    # 1) Handle vscode-remote:// URIs
    if parsed.scheme == "vscode-remote":
        netloc_decoded = unquote(parsed.netloc)
        distro: Optional[str] = None
        linux_path: Optional[str] = None
        uri_type: Optional[str] = None # Initialize uri_type

        if netloc_decoded.lower().startswith("wsl+"):
            distro = netloc_decoded[len("wsl+"):]
            linux_path = unquote(parsed.path)
            uri_type = "wsl+"
        elif netloc_decoded.lower() == "wsl.localhost":
            path_parts = parsed.path.strip("/").split("/", 1)
            if len(path_parts) >= 1:
                distro = path_parts[0]
                linux_path = "/" + unquote(path_parts[1]) if len(path_parts) > 1 else "/"
                uri_type = "wsl.localhost"
            else:
                logger.warning(f"Could not extract distro from wsl.localhost URI path: '{parsed.path}'. Returning original.")
                return path_str # Malformed wsl.localhost

        # Build UNC if distro and path were found
        if distro and linux_path is not None:
            logger.debug(f"Extracted distro='{distro}', linux_path='{linux_path}' from vscode-remote ({uri_type}) URI.")
            windows_unc_path = _build_unc_path(distro, linux_path)
            logger.debug(f"Translated vscode-remote URI '{path_str}' to UNC: '{windows_unc_path}'")
            return windows_unc_path
        elif distro is None and uri_type == "wsl+": # Handle case wsl+ but no distro found
            logger.warning(f"WSL URI '{path_str}' did not yield a valid distro name. Returning original.")
            return path_str
        # If it was vscode-remote scheme but not wsl+ or wsl.localhost (e.g., ssh-remote), fall through to return original

    # 2) Handle vscode://vscode-remote/wsl+Distro/path
    elif parsed.scheme == "vscode" and parsed.netloc == "vscode-remote":
        path_parts = parsed.path.strip("/").split("/", 1)
        if len(path_parts) >= 1 and path_parts[0].lower().startswith("wsl+"):
            authority = path_parts[0]
            distro = authority[len("wsl+"):]
            if distro:
                linux_path = "/" + unquote(path_parts[1]) if len(path_parts) > 1 else "/"
                logger.debug(f"Extracted distro='{distro}', linux_path='{linux_path}' from alternate vscode URI.")
                windows_unc_path = _build_unc_path(distro, linux_path)
                logger.debug(f"Translated alternate vscode URI '{path_str}' to UNC: '{windows_unc_path}'")
                return windows_unc_path
            else:
                logger.warning(f"Alternate WSL URI authority '{authority}' is missing distro name. Returning original path: '{path_str}'")
                return path_str
        # If not wsl+ authority, fall through

    # 3) Handle pure POSIX path /path/to/file
    elif path_str.startswith("/") and not parsed.scheme:
        wslpath_exe = _find_wslpath() # Lazy lookup
        if wslpath_exe:
            win_path = _cached_wsl_to_unc(wslpath_exe, path_str)
            if win_path:
                return win_path # Return translated UNC path
            else:
                # wslpath call failed, _cached_wsl_to_unc logged it
                return path_str # Return original POSIX path
        else:
             logger.debug("wslpath executable not found, cannot translate POSIX path. Returning original.")
             return path_str # Return original POSIX path

    # 4) No translation needed or possible (Windows path, other URI scheme, etc.)
    logger.debug(f"Path '{path_str}' did not match WSL translation conditions on Windows. Returning original.")
    return path_str

# ───────────────────────────────────────────────────────────────
#  Helper: strip VS Code WSL URIs to plain /posix/path
# ───────────────────────────────────────────────────────────────
def _strip_wsl_uri_to_posix(uri: str) -> Optional[str]:
    """
    If *uri* is a vscode‑remote WSL URI, return the embedded POSIX path
    (`/home/…`).  Otherwise return ``None``.
    Works even when the '+’ is percent‑encoded.
    Handles `wsl+` style for both `vscode-remote:` and `vscode:` schemes.
    Does NOT handle `wsl.localhost` style for stripping.
    """
    try:
        p = urlparse(uri)
        logger.debug(f"[_strip_wsl_uri_to_posix] Parsed URI: scheme='{p.scheme}', netloc='{p.netloc}', path='{p.path}'")

        # vscode-remote://wsl+Ubuntu/home/you
        if p.scheme == "vscode-remote":
            netloc_dec = unquote(p.netloc)
            logger.debug(f"[_strip_wsl_uri_to_posix] vscode-remote: netloc_dec='{''.join(c if ' ' <= c <= '~' else repr(c) for c in netloc_dec)}'") # Log safely
            # Make check case-insensitive
            if netloc_dec.lower().startswith("wsl+"):
                result = unquote(p.path) or "/"
                logger.debug(f"[_strip_wsl_uri_to_posix] Matched vscode-remote wsl+. Returning: '{result}'")
                return result

        # vscode://vscode-remote/wsl+Ubuntu/home/you
        if p.scheme == "vscode" and p.netloc == "vscode-remote":
            logger.debug(f"[_strip_wsl_uri_to_posix] vscode: path='{p.path}'")
            parts = p.path.lstrip("/").split("/", 1)
            # Make check case-insensitive
            if parts and parts[0].lower().startswith("wsl+"):
                result = "/" + unquote(parts[1]) if len(parts) > 1 else "/"
                logger.debug(f"[_strip_wsl_uri_to_posix] Matched vscode wsl+. Returning: '{result}'")
                return result

        logger.debug(f"[_strip_wsl_uri_to_posix] No match found. Returning None.")
        return None
    except Exception as e:
        logger.error(f"[_strip_wsl_uri_to_posix] Error processing URI '{uri}': {e}", exc_info=True)
        return None # Return None on unexpected error