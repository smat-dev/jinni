# jinni/core_logic.py
import os
import datetime
import sys
from pathlib import Path
from typing import List, Tuple, Dict, Optional, Any

# Import from the sibling module
from .config_system import check_item, parse_rules, Rule, Ruleset, RuleCache

# --- Constants ---
DEFAULT_SIZE_LIMIT_MB = 100
ENV_VAR_SIZE_LIMIT = 'JINNI_MAX_SIZE_MB'
SEPARATOR = "\n\n" + "=" * 80 + "\n"

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
        print(f"Warning: Could not get stats for {file_path}: {e}", file=sys.stderr)
        return {'size': 0, 'last_modified': 'N/A'} # Return 0 size on error

# --- Main Processing Function ---
def process_directory(
    root_path_str: str,
    list_only: bool = False,
    inline_rules_str: Optional[List[str]] = None,
    global_rules_str: Optional[List[str]] = None, # TODO: Add way to load global rules from file path if needed
    size_limit_mb: Optional[int] = None
) -> str:
    """
    Processes a directory, applying filtering rules and concatenating content.

    Args:
        root_path_str: The absolute path to the root directory to process.
        list_only: If True, only return a list of relative file paths.
        inline_rules_str: Optional list of rule strings provided directly (e.g., from MCP call).
        global_rules_str: Optional list of rule strings from a global config.
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
        print(f"Warning: Invalid value for {ENV_VAR_SIZE_LIMIT} ('{limit_mb_str}'). Using default {DEFAULT_SIZE_LIMIT_MB}MB.", file=sys.stderr)
        effective_limit_mb = DEFAULT_SIZE_LIMIT_MB
    size_limit_bytes = effective_limit_mb * 1024 * 1024

    # Parse inline and global rules
    inline_rules: Optional[Ruleset] = parse_rules("\n".join(inline_rules_str)) if inline_rules_str else None
    global_rules: Optional[Ruleset] = parse_rules("\n".join(global_rules_str)) if global_rules_str else None # Assuming strings for now

    output_parts: List[str] = []
    total_size_bytes: int = 0
    contextfile_cache: RuleCache = {}

    # Use os.walk with followlinks=False (default behavior matches design)
    for dirpath, dirnames, filenames in os.walk(root_path, topdown=True, followlinks=False):
        current_dir_path = Path(dirpath)

        # Filter dirnames in-place based on rules
        # Check directories first to prune traversal
        dirs_to_keep = []
        for dname in dirnames:
            dir_full_path = current_dir_path / dname
            # Removed check: if dir_full_path.is_dir():
            # Rely on os.walk providing valid dirs and check_item for filtering.
            if check_item(dir_full_path, root_path, inline_rules, global_rules, contextfile_cache):
                dirs_to_keep.append(dname)
            # If it's not a dir (or doesn't exist), it won't be traversed anyway by os.walk
        dirnames[:] = sorted(dirs_to_keep) # Sort for consistent order

        # Process files in the current directory
        for filename in sorted(filenames): # Sort for consistent order
            file_full_path = current_dir_path / filename
            # Removed check: if not file_full_path.is_file(): continue
            # Rely on os.walk providing valid files and check_item for filtering.

            # Check if file should be included
            if check_item(file_full_path, root_path, inline_rules, global_rules, contextfile_cache):
                relative_path = file_full_path.relative_to(root_path)
                relative_path_str = str(relative_path).replace(os.sep, '/')

                if list_only:
                    output_parts.append(relative_path_str)
                else:
                    file_info = get_file_info(file_full_path)
                    file_size = file_info['size']

                    # Check size limit *before* reading content
                    # Only add size if we are going to attempt reading it
                    if total_size_bytes + file_size > size_limit_bytes:
                        # Check if adding even this single file exceeds the limit from zero
                        if file_size > size_limit_bytes and total_size_bytes == 0:
                             print(f"Warning: Single file {relative_path_str} ({file_size} bytes) exceeds size limit of {effective_limit_mb}MB. Skipping.", file=sys.stderr)
                             continue # Skip this large file entirely
                        else:
                             # Otherwise, exceeding limit due to accumulation
                             raise ContextSizeExceededError(effective_limit_mb, total_size_bytes + file_size)


                    # Try reading content with multiple encodings
                    content: Optional[str] = None
                    encodings_to_try = ['utf-8', 'latin-1', 'cp1252']
                    try:
                        # Read bytes first to check size accurately before decoding
                        file_bytes = file_full_path.read_bytes()
                        actual_file_size = len(file_bytes)

                        # Re-check size limit with actual bytes read
                        if total_size_bytes + actual_file_size > size_limit_bytes:
                             if actual_file_size > size_limit_bytes and total_size_bytes == 0:
                                 print(f"Warning: Single file {relative_path_str} ({actual_file_size} bytes) exceeds size limit of {effective_limit_mb}MB. Skipping.", file=sys.stderr)
                                 continue
                             else:
                                 raise ContextSizeExceededError(effective_limit_mb, total_size_bytes + actual_file_size)

                        for enc in encodings_to_try:
                            try:
                                content = file_bytes.decode(enc)
                                break # Stop if successful
                            except UnicodeDecodeError:
                                continue # Try next encoding
                        if content is None: # All decodings failed
                             print(f"Warning: Could not decode file {relative_path_str} using {encodings_to_try}. Skipping content.", file=sys.stderr)

                    except OSError as e_inner:
                        print(f"Warning: Error reading file {relative_path_str}: {e_inner}", file=sys.stderr)
                        content = None # Ensure content is None if read fails
                    except Exception as e_general: # Catch other potential errors
                         print(f"Warning: Unexpected error processing file {relative_path_str}: {e_general}", file=sys.stderr)
                         content = None


                    if content is not None:
                        # Use actual_file_size for header consistency
                        header = (
                            f"File: {relative_path_str}\n"
                            f"Size: {actual_file_size} bytes\n"
                            f"Last Modified: {file_info['last_modified']}\n"
                            f"{'=' * 80}\n"
                        )
                        output_parts.append(header + "\n" + content)
                        total_size_bytes += actual_file_size # Add size only if content included
                    # else: # Content is None (read error or decode error)
                        # Decide if we add a placeholder or just skip entirely (currently skipping)


    # Join the parts
    if list_only:
        return "\n".join(output_parts)
    else:
        # Add a final newline if there's content, otherwise return empty string
        return SEPARATOR.join(output_parts) if output_parts else ""