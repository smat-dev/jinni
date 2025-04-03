# jinni/core_logic.py
import os
import datetime
import sys
import logging # Added
from pathlib import Path
from typing import List, Tuple, Dict, Optional, Any, Set # Added Set

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
# --- Helper Function for Single File Processing ---
# (Moved above main function for clarity)
def _process_single_file(
    file_full_path: Path,
    rule_root_path: Path, # Root for rule discovery (.contextfiles)
    output_rel_root_path: Path, # Root for calculating OUTPUT relative paths
    processed_files_set: Set[Path], # Set of already processed absolute paths
    total_size_bytes: int, # Current total size
    size_limit_bytes: int,
    effective_limit_mb: int,
    list_only: bool,
    # Rule checking arguments:
    inline_rules: Optional[Ruleset],
    global_rules: Optional[Ruleset],
    contextfile_cache: RuleCache,
    debug_explain: bool
) -> Tuple[Optional[str], int, bool]: # Returns (content_part | None, new_total_size, added_to_set)
    """Processes a single file: checks rules, duplicates, reads, formats."""

    abs_file_path = file_full_path.resolve() # Ensure absolute path

    # 1. Check if already processed
    if abs_file_path in processed_files_set:
        if debug_explain: logger.debug(f"Skipping File: {abs_file_path} -> Already processed")
        return None, total_size_bytes, False

    # 2. Check rules
    included, reason = check_item(
        file_full_path, rule_root_path, inline_rules, global_rules, contextfile_cache, explain_mode=debug_explain
    )
    # Use output_rel_root_path for display/logging relative path
    relative_path_str = str(file_full_path.relative_to(output_rel_root_path)).replace(os.sep, '/')
    if debug_explain:
        logger.debug(f"Checking File: {relative_path_str} -> {reason}")

    if not included:
        return None, total_size_bytes, False

    # 3. Binary Check (Perform even for list_only to ensure list accuracy)
    try:
        with open(file_full_path, 'rb') as f:
            chunk = f.read(BINARY_CHECK_CHUNK_SIZE)
            if b'\x00' in chunk:
                if debug_explain: logger.debug(f"Skipping File: {relative_path_str} -> Detected as binary")
                return None, total_size_bytes, False
    except OSError as e_bin_check:
        logger.warning(f"Could not perform binary check on {relative_path_str}: {e_bin_check}. Skipping file.")
        return None, total_size_bytes, False

    # 4. Handle list_only mode
    if list_only:
        processed_files_set.add(abs_file_path) # Add to set even in list_only
        return relative_path_str, total_size_bytes, True

    # 5. Get File Info and Check Size Limit
    file_info = get_file_info(file_full_path)
    file_size = file_info['size']

    if total_size_bytes + file_size > size_limit_bytes:
        if file_size > size_limit_bytes and total_size_bytes == 0:
            logger.warning(f"Single file {relative_path_str} ({file_size} bytes) exceeds size limit of {effective_limit_mb}MB. Skipping.")
            return None, total_size_bytes, False
        else:
            # Raise error to be caught by the main processing loop
            raise ContextSizeExceededError(effective_limit_mb, total_size_bytes + file_size)

    # 6. Read Content and Decode
    content: Optional[str] = None
    actual_file_size: int = 0
    encodings_to_try = ['utf-8', 'latin-1', 'cp1252']
    try:
        file_bytes = file_full_path.read_bytes()
        actual_file_size = len(file_bytes)

        if total_size_bytes + actual_file_size > size_limit_bytes:
             if actual_file_size > size_limit_bytes and total_size_bytes == 0:
                 logger.warning(f"Single file {relative_path_str} ({actual_file_size} bytes) exceeds size limit of {effective_limit_mb}MB after read. Skipping.")
                 return None, total_size_bytes, False
             else:
                 raise ContextSizeExceededError(effective_limit_mb, total_size_bytes + actual_file_size)

        for enc in encodings_to_try:
            try:
                content = file_bytes.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        if content is None:
             logger.warning(f"Could not decode file {relative_path_str} using {encodings_to_try}. Skipping content.")

    except OSError as e_read:
        logger.warning(f"Error reading file {relative_path_str}: {e_read}")
        content = None
    except Exception as e_general:
         logger.warning(f"Unexpected error processing file {relative_path_str}: {e_general}")
         content = None

    # 7. Format Output and Update State
    # 7. Format Output and Update State
    if content is not None:
        header = (
            f"File: {relative_path_str}\n" # Use output relative path
            f"Size: {actual_file_size} bytes\n"
            f"Last Modified: {file_info['last_modified']}\n"
            f"{'=' * 80}\n"
        )
        output_part = header + "\n" + content
        processed_files_set.add(abs_file_path) # Add only if successfully processed
        logger.debug(f"Successfully processed and returning content for: {relative_path_str}") # DEBUG ADDED
        return output_part, total_size_bytes + actual_file_size, True
    else:
        # File read/decode failed, or content was None
        return None, total_size_bytes, False


# --- Main Processing Function (Refactored) ---
# --- Main Processing Function (Refactored Signature) ---
def process_directory(
    root_path_str: str, # Root for RULE DISCOVERY, MUST BE ABSOLUTE DIR
    output_rel_root_str: str, # Root for calculating OUTPUT relative paths, MUST BE ABSOLUTE DIR
    processing_target_str: str, # The specific file/dir to process, MUST BE ABSOLUTE
    processed_files_set: Set[Path], # Pass IN and get OUT updated set of absolute paths
    list_only: bool = False,
    inline_rules_str: Optional[List[str]] = None,
    global_rules_str: Optional[List[str]] = None,
    size_limit_mb: Optional[int] = None,
    debug_explain: bool = False
) -> Tuple[str, Set[Path]]: # Return content string AND updated processed set
    """
    Processes a target file or directory, applying filtering rules and concatenating content.
    Avoids processing files listed in processed_files_set and updates the set.

    Args:
        root_path_str: Absolute path to the directory used as the root for rule context discovery.
        output_rel_root_str: Absolute path used as the base for calculating relative paths in output.
        processing_target_str: Absolute path to the file or directory to process.
        processed_files_set: Set of absolute file paths already processed.
        list_only: If True, only return a list of relative file paths.
        inline_rules_str: Optional list of rule strings provided directly.
        global_rules_str: Optional list of rule strings from a global config.
        size_limit_mb: Optional override for the size limit in MB.
        debug_explain: If True, print inclusion/exclusion reasons to stderr.

    Returns:
        A tuple containing:
        - A formatted string (concatenated content or file list).
        - The updated set of processed absolute file paths.

    Raises:
        FileNotFoundError: If the root path or processing target doesn't exist.
        ContextSizeExceededError: If the total size of included files exceeds the limit.
        ValueError: If paths are not absolute.
    """
    # --- Initial Setup & Validation ---
    if not os.path.isabs(root_path_str):
         raise ValueError(f"Rule root path must be absolute: {root_path_str}")
    if not os.path.isabs(output_rel_root_str):
         raise ValueError(f"Output relative root path must be absolute: {output_rel_root_str}")
    if not os.path.isabs(processing_target_str):
         raise ValueError(f"Processing target path must be absolute: {processing_target_str}")

    rule_root_path = Path(root_path_str).resolve()
    output_rel_root_path = Path(output_rel_root_str).resolve()
    processing_target = Path(processing_target_str).resolve()

    if not rule_root_path.is_dir():
        raise FileNotFoundError(f"Rule root path is not a valid directory: {rule_root_path}")
    if not output_rel_root_path.is_dir():
        raise FileNotFoundError(f"Output relative root path is not a valid directory: {output_rel_root_path}")
    if not processing_target.exists():
        raise FileNotFoundError(f"Processing target path does not exist: {processing_target}")
    # Ensure target is within or is the root path (for relative path calculations)
    # This check might be too strict if target is a file and root is its parent? Revisit if needed.
    # try:
    #     processing_target.relative_to(root_path)
    # except ValueError:
    #      raise ValueError(f"Processing target '{processing_target}' must be inside the root path '{root_path}' for relative path context.")


    # Determine size limit (moved inside as it's needed per call potentially)
    limit_mb_str = os.environ.get(ENV_VAR_SIZE_LIMIT)
    try:
        effective_limit_mb = size_limit_mb if size_limit_mb is not None \
                             else int(limit_mb_str) if limit_mb_str else DEFAULT_SIZE_LIMIT_MB
    except ValueError:
        logger.warning(f"Invalid value for {ENV_VAR_SIZE_LIMIT} ('{limit_mb_str}'). Using default {DEFAULT_SIZE_LIMIT_MB}MB.")
        effective_limit_mb = DEFAULT_SIZE_LIMIT_MB
    size_limit_bytes = effective_limit_mb * 1024 * 1024

    # Parse rules (could be cached externally if performance becomes an issue)
    inline_rules: Optional[Ruleset] = parse_rules("\n".join(inline_rules_str)) if inline_rules_str else None
    global_rules: Optional[Ruleset] = parse_rules("\n".join(global_rules_str)) if global_rules_str else None

    output_parts: List[str] = []
    total_size_bytes: int = 0 # Size accumulated *within this call*
    contextfile_cache: RuleCache = {} # Cache for this run

    # --- Process Target (File or Directory) ---
    if processing_target.is_file():
        logger.debug(f"Processing single file target: {processing_target}")
        content_part, size_added, _ = _process_single_file( # Unpack 3 values
            processing_target, rule_root_path, output_rel_root_path, processed_files_set,
            total_size_bytes, size_limit_bytes, effective_limit_mb, list_only,
            inline_rules, global_rules, contextfile_cache, debug_explain
        )
        if content_part:
            output_parts.append(content_part)
            total_size_bytes += size_added

    elif processing_target.is_dir():
        logger.debug(f"Processing directory target: {processing_target}")
        # Use os.walk starting from the processing_target directory
        for dirpath, dirnames, filenames in os.walk(processing_target, topdown=True, followlinks=False):
            current_dir_path = Path(dirpath)
            # Ensure dirnames are sorted for consistent processing order.
            dirnames.sort()

            # --- Prune excluded directories ---
            # Iterate over a copy of dirnames to check for exclusion
            # Modify the original dirnames list *in-place* so os.walk skips them
            dirnames_to_remove = []
            for dirname in dirnames: # Check items in the current list
                dir_full_path = (current_dir_path / dirname).resolve()

                # Skip symlinks early (check_item also does this, but good for efficiency)
                # Note: os.walk(followlinks=False) prevents walking into symlink *directories*,
                # but we still need to check if the item *itself* is a symlink file/dir link.
                if dir_full_path.is_symlink():
                    dirnames_to_remove.append(dirname)
                    if debug_explain:
                        try:
                            relative_dir_path_str = str(dir_full_path.relative_to(output_rel_root_path)).replace(os.sep, '/')
                        except ValueError:
                            relative_dir_path_str = str(dir_full_path) # Fallback
                        logger.debug(f"Pruning Directory (Symlink): {relative_dir_path_str}")
                    continue

                # Check rules using the config system
                included, reason = check_item(
                    dir_full_path,
                    rule_root_path,
                    inline_rules,
                    global_rules,
                    contextfile_cache,
                    explain_mode=debug_explain # Pass explain mode down
                )

                if not included:
                    dirnames_to_remove.append(dirname)
                    # Log pruning reason if explain_mode is on and reason is provided
                    if debug_explain and reason:
                        try:
                            relative_dir_path_str = str(dir_full_path.relative_to(output_rel_root_path)).replace(os.sep, '/')
                        except ValueError:
                            relative_dir_path_str = str(dir_full_path) # Fallback
                        logger.debug(f"Pruning Directory: {relative_dir_path_str} -> {reason}")

            # Modify the original dirnames list *in-place* after iterating
            if dirnames_to_remove:
                # Efficiently remove multiple items
                original_dirnames_set = set(dirnames)
                original_dirnames_set.difference_update(dirnames_to_remove)
                # Update dirnames IN-PLACE for os.walk(topdown=True) to take effect
                dirnames[:] = sorted(list(original_dirnames_set))
            # --- End Pruning ---

            # Process files in the current (now potentially pruned) directory
            for filename in sorted(filenames):
                file_full_path = current_dir_path / filename
                try:
                    content_part, size_added, _ = _process_single_file( # Unpack 3 values
                        file_full_path, rule_root_path, output_rel_root_path, processed_files_set,
                        total_size_bytes, size_limit_bytes, effective_limit_mb, list_only,
                        inline_rules, global_rules, contextfile_cache, debug_explain
                    )
                    if content_part:
                        output_parts.append(content_part)
                        total_size_bytes += size_added
                except ContextSizeExceededError as e:
                     logger.error(f"Context size limit exceeded while processing {file_full_path}: {e}")
                     # Re-raise to stop processing immediately
                     raise e
                except Exception as e_inner:
                     # Log unexpected errors during single file processing but continue walk
                     logger.error(f"Unexpected error processing file {file_full_path} within directory walk: {e_inner}")

    else:
         logger.warning(f"Processing target is neither a file nor a directory: {processing_target}")

    # --- Final Output Formatting ---
    # Join parts based on list_only mode
    final_output = "\n".join(output_parts) if list_only else SEPARATOR.join(output_parts)

    return final_output, processed_files_set # Return content and updated set

    # (os.walk loop and file processing logic moved inside the 'elif processing_target.is_dir():' block above)