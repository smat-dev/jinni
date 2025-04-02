# jinni/core_logic.py
import os
import datetime
import sys
import logging # Added
from pathlib import Path
from typing import List, Tuple, Dict, Optional, Any

# Import from the sibling module
from .config_system import check_item, parse_rules, Rule, Ruleset, RuleCache

# Setup logger for this module
logger = logging.getLogger("jinni.core_logic")
# Configure basic logging if no handlers are configured by the application
if not logger.handlers and not logging.getLogger().handlers:
     logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
# --- Constants ---
DEFAULT_SIZE_LIMIT_MB = 100
ENV_VAR_SIZE_LIMIT = 'JINNI_MAX_SIZE_MB'
SEPARATOR = "\n\n" + "=" * 80 + "\n"
BINARY_CHECK_CHUNK_SIZE = 1024 # Bytes to read for binary check

# --- Custom Exception ---
class ContextSizeExceededError(Exception):
    """Custom exception for when context size limit is reached."""
    def __init__(self, limit_mb: int, current_size_bytes: int):
        self.limit_mb = limit_mb
        self.current_size_bytes = current_size_bytes
        super().__init__(f"Total content size exceeds limit of {limit_mb}MB. Processing aborted.")

# --- Helper Functions ---
def get_file_info(file_path: Path) -> Dict[str, Any]:
    """Get file information including size and last modified time."""
    try:
        stats = os.stat(file_path)
        # Ensure size is an integer
        size = int(stats.st_size)
        last_modified = datetime.datetime.fromtimestamp(stats.st_mtime).strftime('%Y-%m-%d %H:%M:%S')
        return {'size': size, 'last_modified': last_modified}
    except Exception as e:
        logger.warning(f"Could not get stats for {file_path}: {e}")
        return {'size': 0, 'last_modified': 'N/A'} # Return 0 size on error

# --- Main Processing Function ---
def process_directory(
    root_path_str: str,
    list_only: bool = False,
    inline_rules_str: Optional[List[str]] = None,
    global_rules_str: Optional[List[str]] = None, # TODO: Add way to load global rules from file path if needed
    size_limit_mb: Optional[int] = None,
    debug_explain: bool = False # New flag
) -> str:
    """
    Processes a directory, applying filtering rules and concatenating content.

    Args:
        root_path_str: The absolute path to the root directory to process.
        list_only: If True, only return a list of relative file paths.
        inline_rules_str: Optional list of rule strings provided directly (e.g., from MCP call).
        global_rules_str: Optional list of rule strings from a global config.
        size_limit_mb: Optional override for the size limit in MB.
        debug_explain: If True, print inclusion/exclusion reasons to stderr.
        size_limit_mb: Optional override for the size limit in MB.

    Returns:
        A formatted string containing concatenated file content or a list of files.

    Raises:
        FileNotFoundError: If the root path doesn't exist or isn't a directory.
        ContextSizeExceededError: If the total size of included files exceeds the limit.
        ValueError: If root_path_str is not an absolute path.
    """
    if not os.path.isabs(root_path_str):
         raise ValueError(f"Root path must be absolute: {root_path_str}")

    root_path = Path(root_path_str).resolve()
    # Removed check: if not root_path.is_dir(): raise FileNotFoundError(...)
    # os.walk handles non-existent paths gracefully.

    # Determine size limit
    limit_mb_str = os.environ.get(ENV_VAR_SIZE_LIMIT)
    try:
        effective_limit_mb = size_limit_mb if size_limit_mb is not None \
                             else int(limit_mb_str) if limit_mb_str else DEFAULT_SIZE_LIMIT_MB
    except ValueError:
        logger.warning(f"Invalid value for {ENV_VAR_SIZE_LIMIT} ('{limit_mb_str}'). Using default {DEFAULT_SIZE_LIMIT_MB}MB.")
        effective_limit_mb = DEFAULT_SIZE_LIMIT_MB
    size_limit_bytes = effective_limit_mb * 1024 * 1024

    # Parse inline and global rules
    inline_rules: Optional[Ruleset] = parse_rules("\n".join(inline_rules_str)) if inline_rules_str else None
    global_rules: Optional[Ruleset] = parse_rules("\n".join(global_rules_str)) if global_rules_str else None # Assuming strings for now

    output_parts: List[str] = []
    total_size_bytes: int = 0
    contextfile_cache: RuleCache = {}

    # Use os.walk with followlinks=False (default behavior matches design)
    logger.debug(f"Starting directory walk from: {root_path}")
    for dirpath, dirnames, filenames in os.walk(root_path, topdown=True, followlinks=False):
        current_dir_path = Path(dirpath)

        # Filter dirnames in-place based on rules
        # Check directories first to prune traversal
        dirs_to_keep = []
        for dname in dirnames:
            dir_full_path = current_dir_path / dname
            # Removed check: if dir_full_path.is_dir():
            # Rely on os.walk providing valid dirs and check_item for filtering.
            included, reason = check_item(dir_full_path, root_path, inline_rules, global_rules, contextfile_cache, explain_mode=debug_explain) # Pass flag
            if debug_explain:
                rel_dir_path = dir_full_path.relative_to(root_path)
                # Use logger instead of print for debug explain
                logger.debug(f"Checking Dir : {str(rel_dir_path).replace(os.sep, '/')}/ -> {reason}") # Keep as DEBUG
            if included:
                dirs_to_keep.append(dname)
        dirnames[:] = sorted(dirs_to_keep) # Sort for consistent order

        # Process files in the current directory
        for filename in sorted(filenames): # Sort for consistent order
            file_full_path = current_dir_path / filename
            # Removed check: if not file_full_path.is_file(): continue
            # Rely on os.walk providing valid files and check_item for filtering.

            # Check if file should be included by rules
            included, reason = check_item(file_full_path, root_path, inline_rules, global_rules, contextfile_cache, explain_mode=debug_explain) # Pass flag
            relative_path = file_full_path.relative_to(root_path) # Get relative path regardless for debug output
            relative_path_str = str(relative_path).replace(os.sep, '/')
            if debug_explain:
                 # Use logger instead of print for debug explain
                 logger.debug(f"Checking File: {relative_path_str} -> {reason}") # Keep as DEBUG

            if included:
                relative_path_str = str(relative_path).replace(os.sep, '/')

                # --- Binary File Check (Heuristic) ---
                # Perform this check even for list_only to ensure the list is accurate
                # --- Binary File Check (Heuristic) ---
                # Perform this check only if the file was included by rules
                try:
                    with open(file_full_path, 'rb') as f:
                        chunk = f.read(BINARY_CHECK_CHUNK_SIZE)
                        if b'\x00' in chunk:
                            if debug_explain:
                                logger.debug(f"Skipping File: {relative_path_str} -> Detected as binary") # Keep as DEBUG
                            # else: # Remove the INFO log, DEBUG covers it when enabled
                                # logger.info(f"Skipping likely binary file: {relative_path_str}")
                            continue # Skip this file entirely
                except OSError as e_bin_check:
                    if debug_explain:
                         logger.debug(f"Skipping File: {relative_path_str} -> Binary check failed ({e_bin_check})") # Keep as DEBUG
                    # else: # Keep warning
                         # logger.warning(f"Could not perform binary check on {relative_path_str}: {e_bin_check}. Skipping file.")
                    continue # Skip this file entirely

                # --- File Processing Logic ---
                if list_only:
                    # We already passed the binary check, so add to list
                    output_parts.append(relative_path_str)
                    continue # Skip content processing

                # --- Get File Info and Check Size Limit ---
                file_info = get_file_info(file_full_path)
                file_size = file_info['size'] # Use reported size for initial check

                if total_size_bytes + file_size > size_limit_bytes:
                    if file_size > size_limit_bytes and total_size_bytes == 0:
                        logger.warning(f"Single file {relative_path_str} ({file_size} bytes) exceeds size limit of {effective_limit_mb}MB. Skipping.")
                        continue
                    else:
                        raise ContextSizeExceededError(effective_limit_mb, total_size_bytes + file_size)

                # --- Read Content and Decode ---
                content: Optional[str] = None
                actual_file_size: int = 0
                encodings_to_try = ['utf-8', 'latin-1', 'cp1252']
                try:
                    # Read the full content now we know it's likely text and within limits (initially)
                    file_bytes = file_full_path.read_bytes()
                    actual_file_size = len(file_bytes)

                    # Re-check size limit with actual bytes read (important for race conditions or stat inaccuracies)
                    if total_size_bytes + actual_file_size > size_limit_bytes:
                         if actual_file_size > size_limit_bytes and total_size_bytes == 0:
                             logger.warning(f"Single file {relative_path_str} ({actual_file_size} bytes) exceeds size limit of {effective_limit_mb}MB after read. Skipping.")
                             continue
                         else:
                             # Abort immediately if limit exceeded after reading this file
                             raise ContextSizeExceededError(effective_limit_mb, total_size_bytes + actual_file_size)

                    # Attempt decoding
                    for enc in encodings_to_try:
                        try:
                            content = file_bytes.decode(enc)
                            break # Stop if successful
                        except UnicodeDecodeError:
                            continue # Try next encoding
                    if content is None: # All decodings failed
                         logger.warning(f"Could not decode file {relative_path_str} using {encodings_to_try}. Skipping content.")

                except OSError as e_read:
                    logger.warning(f"Error reading file {relative_path_str}: {e_read}")
                    content = None # Ensure content is None if read fails
                except Exception as e_general: # Catch other potential errors
                     logger.warning(f"Unexpected error processing file {relative_path_str}: {e_general}")
                     content = None

                # --- Append Content if Successful ---
                if content is not None:
                    header = (
                        f"File: {relative_path_str}\n"
                        f"Size: {actual_file_size} bytes\n" # Use actual size read
                        f"Last Modified: {file_info['last_modified']}\n"
                        f"{'=' * 80}\n"
                    )
                    output_parts.append(header + "\n" + content)
                    total_size_bytes += actual_file_size # Add size only if content included
    # Join the parts
    if list_only:
        return "\n".join(output_parts)
    else:
        # Add a final newline if there's content, otherwise return empty string
        return SEPARATOR.join(output_parts) if output_parts else ""