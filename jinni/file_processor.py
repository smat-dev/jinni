# jinni/file_processor.py
"""Handles processing of individual files for Jinni context."""

import os
import logging
from pathlib import Path
from typing import Optional, Tuple, Dict, Any

# Import necessary components from other modules (adjust as needed)
from .utils import get_file_info, _is_binary # Assuming utils.py exists
from .exceptions import ContextSizeExceededError # Assuming exceptions.py exists

# Setup logger for this module
logger = logging.getLogger("jinni.file_processor")
if not logger.handlers and not logging.getLogger().handlers:
     logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# Constants might be moved to a central place later
SEPARATOR = "\n\n" + "=" * 80 + "\n"

def process_file(
    file_path: Path,
    output_rel_root: Path,
    size_limit_bytes: int,
    total_size_bytes: int,
    list_only: bool,
    include_size_in_list: bool,
    debug_explain: bool
) -> Tuple[Optional[str], int]:
    """
    Processes a single file: checks size, binary status, reads content, formats output.

    Args:
        file_path: Absolute path to the file to process.
        output_rel_root: The root directory for calculating relative paths in output.
        size_limit_bytes: Maximum total context size allowed in bytes.
        total_size_bytes: Current total size of context processed so far.
        list_only: If True, only return the relative path (optionally with size).
        include_size_in_list: If True and list_only is True, prepend size to path.
        debug_explain: If True, log detailed processing steps.

    Returns:
        A tuple containing:
        - The formatted output string (header + content or path string), or None if skipped.
        - The size of the file content added (0 if skipped or list_only).

    Raises:
        ContextSizeExceededError: If adding this file would exceed the size limit.
    """
    if debug_explain: logger.debug(f"Processing file: {file_path}")

    # Perform binary check first
    if _is_binary(file_path):
        if debug_explain: logger.debug(f"Skipping File: {file_path} -> Detected as binary (check applied for list_only={list_only})")
        return None, 0

    # Binary check passed, now get info and check size
    file_info = get_file_info(file_path)
    file_stat_size = file_info['size']

    if total_size_bytes + file_stat_size > size_limit_bytes:
        if file_stat_size > size_limit_bytes and total_size_bytes == 0:
            # Log warning only if size check fails *after* passing binary check
            logger.warning(f"File {file_path} ({file_stat_size} bytes) exceeds size limit of {size_limit_bytes / (1024*1024):.2f}MB. Skipping.")
            return None, 0 # Skip this file
        else:
            # Raise error if adding this file exceeds limit (even if file itself is smaller)
            raise ContextSizeExceededError(int(size_limit_bytes / (1024*1024)), total_size_bytes + file_stat_size, file_path)

    # --- Both binary and size checks passed ---

    # Get relative path for output
    try:
        relative_path_str = str(file_path.relative_to(output_rel_root)).replace(os.sep, '/')
    except ValueError:
        relative_path_str = str(file_path) # Fallback

    # Prepare output
    if list_only:
        output_line = f"{file_stat_size}\t{relative_path_str}" if include_size_in_list else relative_path_str
        if debug_explain: logger.debug(f"Adding to list: {output_line}")
        return output_line, 0 # No size added in list_only mode
    else:
        try:
            file_bytes = file_path.read_bytes()
            actual_file_size = len(file_bytes)
            # Double check size after reading (important!)
            if total_size_bytes + actual_file_size > size_limit_bytes:
                if actual_file_size > size_limit_bytes and total_size_bytes == 0:
                    logger.warning(f"File {file_path} ({actual_file_size} bytes) exceeds size limit of {size_limit_bytes / (1024*1024):.2f}MB after read. Skipping.")
                    return None, 0
                else:
                    raise ContextSizeExceededError(int(size_limit_bytes / (1024*1024)), total_size_bytes + actual_file_size, file_path)

            content: Optional[str] = None
            encodings_to_try = ['utf-8', 'latin-1', 'cp1252']
            for enc in encodings_to_try:
                try:
                    content = file_bytes.decode(enc)
                    if debug_explain: logger.debug(f"Decoded {file_path} using {enc}")
                    break
                except UnicodeDecodeError:
                    continue
            if content is None:
                logger.warning(f"Could not decode file {file_path} using {encodings_to_try}. Skipping content.")
                return None, 0

            header = (
                f"File: {relative_path_str}\n"
                f"Size: {actual_file_size} bytes\n"
                f"Last Modified: {file_info['last_modified']}\n"
                f"{'=' * 80}\n"
            )
            formatted_output = header + "\n" + content
            if debug_explain: logger.debug(f"Adding content for: {relative_path_str}")
            return formatted_output, actual_file_size

        except OSError as e_read:
            logger.warning(f"Error reading file {file_path}: {e_read}")
            return None, 0
        except Exception as e_general:
            logger.warning(f"Unexpected error processing file {file_path}: {e_general}")
            return None, 0