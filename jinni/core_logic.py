import sys
import os
import datetime
import logging
import mimetypes # Added for better binary detection
import puremagic # Added for pure-python binary detection
from pathlib import Path
from typing import List, Tuple, Dict, Optional, Any, Set, Iterable
import fnmatch # For simple default matching if needed, though pathspec is preferred

# Attempt to import pathspec needed by config_system
try:
    import pathspec
except ImportError:
    print("Error: 'pathspec' library not found. Required by config_system.")
    print("Please install it: pip install pathspec")
    raise

# Import from the sibling module - updated imports
from .config_system import (
    load_rules_from_file,
    compile_spec_from_rules,
    DEFAULT_RULES,
    CONTEXT_FILENAME,
)

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
        size = int(stats.st_size)
        last_modified = datetime.datetime.fromtimestamp(stats.st_mtime).strftime('%Y-%m-%d %H:%M:%S')
        return {'size': size, 'last_modified': last_modified}
    except Exception as e:
        logger.warning(f"Could not get stats for {file_path}: {e}")
        return {'size': 0, 'last_modified': 'N/A'}

# Corrected _is_binary function starts here
def _is_binary(file_path: Path) -> bool:
    """
    Check if a file appears to be binary.
    Uses puremagic first. If inconclusive, falls back to null-byte check.
    Requires the 'puremagic' library to be installed.
    """
    filepath_str = str(file_path)
    mime_type = None
    puremagic_failed = False

    # 1. Try puremagic detection
    try:
        mime_type = puremagic.from_file(filepath_str, mime=True)
        logger.debug(f"Detected MIME type for {file_path} via puremagic: {mime_type}")

        if mime_type and isinstance(mime_type, str):
            if mime_type.startswith('text/'):
                logger.debug(f"File {file_path} identified as text by MIME type.")
                return False  # Definitely text
            else:
                # If puremagic gives a non-text MIME type, treat as binary
                logger.debug(f"File {file_path} identified as binary by MIME type: {mime_type}")
                return True  # Definitely binary (based on puremagic)
        # If mime_type is None here, puremagic was inconclusive, proceed to fallback

    except puremagic.main.PureError as e:
        logger.debug(f"puremagic detection failed for {file_path}: {e}. Falling back to null byte check.")
        puremagic_failed = True
    except OSError as e:  # File access error during puremagic
        logger.warning(f"Could not perform puremagic check (read error) on {file_path}: {e}. Assuming binary as safe fallback.")
        return True # Assume binary if we can't even read it for puremagic
    except Exception as e:  # Other errors during puremagic
        logger.warning(f"Unexpected error during puremagic check for {file_path}: {e}. Falling back to null byte check.")
        puremagic_failed = True

    # 2. Fallback to Null Byte Check if puremagic was inconclusive (returned None) or failed
    if mime_type is None or puremagic_failed:
        logger.debug(f"puremagic inconclusive/failed for {file_path}. Falling back to null byte check.")
        try:
            with open(file_path, 'rb') as f:
                # Assuming BINARY_CHECK_CHUNK_SIZE is defined globally (e.g., 1024)
                chunk = f.read(BINARY_CHECK_CHUNK_SIZE)
                has_null_byte = b'\x00' in chunk
                if has_null_byte:
                    logger.debug(f"File {file_path} detected as binary by null byte check.")
                else:
                    logger.debug(f"File {file_path} not detected as binary by null byte check.")
                return has_null_byte  # True if null byte found (binary), False otherwise (likely text)
        except OSError as e:  # File access error during null byte check
            logger.warning(f"Could not perform null byte check (read error) on {file_path}: {e}. Assuming binary as safe fallback.")
            return True # Assume binary if we can't read it for null byte check
        except Exception as e:  # Other errors during null byte check
            logger.warning(f"Unexpected error during null byte check for {file_path}: {e}. Assuming binary as safe fallback.")
            return True # Assume binary on unexpected error

    # Should not be reached if logic is correct, but as a final safety net
    logger.warning(f"Reached unexpected end of _is_binary logic for {file_path}. Assuming binary.")
    return True
# Corrected _is_binary function ends here

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

# --- Main Processing Function ---
def read_context(
    target_paths_str: List[str],
    output_relative_to_str: Optional[str] = None,
    override_rules: Optional[List[str]] = None,
    list_only: bool = False,
    size_limit_mb: Optional[int] = None,
    debug_explain: bool = False,
    include_size_in_list: bool = False # Added for CLI --size option
) -> str:
    """
    Processes target files/directories, applying context rules dynamically.

    Args:
        target_paths_str: List of target file or directory paths (can be relative or absolute).
        output_relative_to_str: Optional path to make output paths relative to.
                                If None, uses the common ancestor of targets or CWD.
        override_rules: Optional list of rule strings to use instead of .contextfiles.
        list_only: If True, only return a list of relative file paths.
        size_limit_mb: Optional override for the size limit in MB.
        debug_explain: If True, log inclusion/exclusion reasons.

    Returns:
        A formatted string (concatenated content or file list).

    Raises:
        FileNotFoundError: If any target path does not exist.
        ContextSizeExceededError: If the total size of included files exceeds the limit.
        ValueError: If paths have issues or cannot be made relative.
    """
    # --- Initial Setup & Validation ---
    # --- Initial Setup & Validation ---
    target_paths: List[Path] = []
    for p_str in target_paths_str:
        p = Path(p_str).resolve()
        if not p.exists():
            raise FileNotFoundError(f"Target path does not exist: {p_str} (resolved to {p})")
        target_paths.append(p)

    if not target_paths:
        logger.warning("No valid target paths provided.")
        return ""

    # Determine the root for output relative paths
    output_rel_root: Path
    if output_relative_to_str:
        output_rel_root = Path(output_relative_to_str).resolve()
        if not output_rel_root.is_dir():
             logger.warning(f"Output relative path '{output_relative_to_str}' is not a directory. Using CWD.")
             output_rel_root = Path.cwd().resolve()
    else:
        # Determine the root for rule discovery (common ancestor of targets) first
        # This is the highest point we look for .contextfiles
        try:
            # Use all target paths (files and dirs) to find the highest common point
            common_ancestor_rule = Path(os.path.commonpath([str(p) for p in target_paths]))
            rule_discovery_root = common_ancestor_rule if common_ancestor_rule.is_dir() else common_ancestor_rule.parent
        except ValueError:
            logger.warning("Could not find common ancestor for rule discovery. Using CWD.")
            rule_discovery_root = Path.cwd().resolve()
        logger.debug(f"Using rule discovery root: {rule_discovery_root}")

        # Use the rule discovery root as the default for output relative paths
        output_rel_root = rule_discovery_root
        logger.debug(f"Using output relative root (derived from rule discovery root): {output_rel_root}")


    # rule_discovery_root is now determined above when output_relative_to_str is None
    # If output_relative_to_str *was* provided, we still need rule_discovery_root
    if output_relative_to_str:
         try:
             common_ancestor_rule = Path(os.path.commonpath([str(p) for p in target_paths]))
             rule_discovery_root = common_ancestor_rule if common_ancestor_rule.is_dir() else common_ancestor_rule.parent
         except ValueError:
             logger.warning("Could not find common ancestor for rule discovery. Using CWD.")
             rule_discovery_root = Path.cwd().resolve()
         logger.debug(f"Using rule discovery root: {rule_discovery_root}")


    # Store initial targets for the "always include" rule
    initial_target_paths_set: Set[Path] = set(target_paths)

    # --- Size Limit ---
    limit_mb_str = os.environ.get(ENV_VAR_SIZE_LIMIT)
    try:
        effective_limit_mb = size_limit_mb if size_limit_mb is not None \
                             else int(limit_mb_str) if limit_mb_str else DEFAULT_SIZE_LIMIT_MB
    except ValueError:
        logger.warning(f"Invalid value for {ENV_VAR_SIZE_LIMIT} ('{limit_mb_str}'). Using default {DEFAULT_SIZE_LIMIT_MB}MB.")
        effective_limit_mb = DEFAULT_SIZE_LIMIT_MB
    size_limit_bytes = effective_limit_mb * 1024 * 1024
    logger.debug(f"Effective size limit: {effective_limit_mb}MB ({size_limit_bytes} bytes)")

    # --- Override Handling ---
    use_overrides = override_rules is not None
    override_spec: Optional[pathspec.PathSpec] = None
    if use_overrides:
        logger.info("Override rules provided. Ignoring all .contextfiles.")
        all_override_rules = DEFAULT_RULES + override_rules
        override_spec = compile_spec_from_rules(all_override_rules, "Defaults + Overrides")
        if debug_explain: logger.debug(f"Compiled override spec with {len(override_spec.patterns)} patterns.")

    # --- Processing State ---
    output_parts: List[str] = []
    processed_files_set: Set[Path] = set() # Absolute paths of files added to output
    total_size_bytes: int = 0

    # --- Process Each Target ---
    for target_path in target_paths:
        # Skip if target itself was already processed (e.g., file listed twice or processed during a dir walk)
        if target_path in processed_files_set:
             if debug_explain: logger.debug(f"Skipping target {target_path} as it was already processed.")
             continue

        # --- Single File Target ---
        if target_path.is_file():
            if debug_explain: logger.debug(f"Processing explicit file target: {target_path}")
            # Explicit targets are always included, skip rule checks but do others
            if target_path in processed_files_set: # Double check, might have been added during walk
                if debug_explain: logger.debug(f"Skipping File: {target_path} -> Already processed")
                continue

            file_info = get_file_info(target_path)
            file_stat_size = file_info['size']

            # Check size limit
            if total_size_bytes + file_stat_size > size_limit_bytes:
                 if file_stat_size > size_limit_bytes and total_size_bytes == 0:
                     logger.warning(f"Explicit target file {target_path} ({file_stat_size} bytes) exceeds size limit of {effective_limit_mb}MB. Skipping.")
                     continue
                 else:
                     raise ContextSizeExceededError(effective_limit_mb, total_size_bytes + file_stat_size)

            # Binary check (only if not list_only)
            # Binary check (now runs even if list_only is True)
            if _is_binary(target_path):
                 if debug_explain: logger.debug(f"Skipping File: {target_path} -> Detected as binary (check applied for list_only={list_only})")
                 continue

            # Get relative path for output
            try:
                relative_path_str = str(target_path.relative_to(output_rel_root)).replace(os.sep, '/')
            except ValueError:
                relative_path_str = str(target_path) # Fallback

            if list_only:
                output_line = f"{file_stat_size}\t{relative_path_str}" if include_size_in_list else relative_path_str
                output_parts.append(output_line)
                processed_files_set.add(target_path)
                # Size doesn't increase in list_only mode after initial check (size already checked)
            else:
                # Read content
                try:
                    file_bytes = target_path.read_bytes()
                    actual_file_size = len(file_bytes)
                    # Double check size after reading
                    if total_size_bytes + actual_file_size > size_limit_bytes:
                         if actual_file_size > size_limit_bytes and total_size_bytes == 0:
                             logger.warning(f"Explicit target file {target_path} ({actual_file_size} bytes) exceeds size limit of {effective_limit_mb}MB after read. Skipping.")
                             continue
                         else:
                             raise ContextSizeExceededError(effective_limit_mb, total_size_bytes + actual_file_size)

                    content: Optional[str] = None
                    encodings_to_try = ['utf-8', 'latin-1', 'cp1252']
                    for enc in encodings_to_try:
                        try:
                            content = file_bytes.decode(enc)
                            break
                        except UnicodeDecodeError:
                            continue
                    if content is None:
                         logger.warning(f"Could not decode explicit target file {target_path} using {encodings_to_try}. Skipping content.")
                         continue

                    header = (
                        f"File: {relative_path_str}\n"
                        f"Size: {actual_file_size} bytes\n"
                        f"Last Modified: {file_info['last_modified']}\n"
                        f"{'=' * 80}\n"
                    )
                    output_parts.append(header + "\n" + content)
                    processed_files_set.add(target_path)
                    total_size_bytes += actual_file_size
                    if debug_explain: logger.debug(f"Included explicit file target: {relative_path_str}")

                except OSError as e_read:
                    logger.warning(f"Error reading explicit target file {target_path}: {e_read}")
                except Exception as e_general:
                     logger.warning(f"Unexpected error processing explicit target file {target_path}: {e_general}")

        # --- Directory Target ---
        elif target_path.is_dir():
            if debug_explain: logger.debug(f"Processing directory target: {target_path}")
            # Walk the directory
            for dirpath_str, dirnames, filenames in os.walk(str(target_path), topdown=True, followlinks=False):
                current_dir_path = Path(dirpath_str).resolve()
                dirnames.sort()
                filenames.sort()
                if debug_explain: logger.debug(f"--- Walking directory: {current_dir_path} ---")

                # --- Determine Active Spec for this Directory ---
                active_spec: pathspec.PathSpec
                spec_source_desc: str
                if use_overrides:
                    active_spec = override_spec # Use the pre-compiled override spec
                    spec_source_desc = "Overrides"
                else:
                    # Find context files from rule_discovery_root down to current_dir_path
                    context_files_in_path = _find_context_files_for_dir(current_dir_path, rule_discovery_root)
                    if debug_explain: logger.debug(f"Found context files for {current_dir_path}: {context_files_in_path}")
                    # Load rules from all found context files
                    current_rules = list(DEFAULT_RULES) # Start with defaults
                    for cf_path in context_files_in_path:
                        current_rules.extend(load_rules_from_file(cf_path))
                    # Compile spec for this specific directory
                    try:
                        relative_dir_desc = current_dir_path.relative_to(rule_discovery_root)
                        spec_source_desc = f"Context files up to ./{relative_dir_desc}" if str(relative_dir_desc) != '.' else "Context files at root"
                    except ValueError:
                        spec_source_desc = f"Context files up to {current_dir_path}" # Fallback if not relative
                    if debug_explain: logger.debug(f"Combined rules for {current_dir_path}: {current_rules}")
                    active_spec = compile_spec_from_rules(current_rules, spec_source_desc)
                    if debug_explain: logger.debug(f"Compiled spec for {current_dir_path} from {spec_source_desc} ({len(active_spec.patterns)} patterns)")


                # --- Prune Directories ---
                dirnames_to_remove = []
                for dirname in dirnames:
                    sub_dir_path = (current_dir_path / dirname).resolve()

                    # Always keep explicit targets
                    if sub_dir_path in initial_target_paths_set:
                        if debug_explain: logger.debug(f"Keeping explicit directory target: {sub_dir_path}")
                        continue

                    # Skip symlinks
                    if sub_dir_path.is_symlink():
                        dirnames_to_remove.append(dirname)
                        if debug_explain: logger.debug(f"Pruning Directory (Symlink): {sub_dir_path}")
                        continue

                    # Check against active spec
                    try:
                        # Path for matching should be relative to the rule discovery root
                        path_for_match = str(sub_dir_path.relative_to(rule_discovery_root)).replace(os.sep, '/') + '/'
                        if not active_spec.match_file(path_for_match):
                            dirnames_to_remove.append(dirname)
                            if debug_explain: logger.debug(f"Pruning Directory: {sub_dir_path} (excluded by {spec_source_desc} matching '{path_for_match}')")
                        elif debug_explain:
                             logger.debug(f"Keeping Directory: {sub_dir_path} (included by {spec_source_desc} matching '{path_for_match}')")
                    except ValueError:
                         logger.warning(f"Could not make directory path {sub_dir_path} relative to rule root {rule_discovery_root} for pruning check.")
                    except Exception as e_prune:
                         logger.error(f"Error checking directory {sub_dir_path} against spec: {e_prune}")


                if dirnames_to_remove:
                    dirnames[:] = [d for d in dirnames if d not in dirnames_to_remove]
                # --- End Pruning ---


                # --- Process Files in Current Directory ---
                for filename in filenames:
                    file_path = (current_dir_path / filename).resolve()

                    if file_path in processed_files_set:
                        if debug_explain: logger.debug(f"Skipping File: {file_path} -> Already processed")
                        continue

                    # Always include explicit targets
                    is_explicit_target = file_path in initial_target_paths_set
                    should_include = False
                    reason = ""

                    if is_explicit_target:
                        should_include = True
                        reason = "Explicitly targeted"
                        if debug_explain: logger.debug(f"Including File: {file_path} ({reason})")
                    else:
                        # Check rules if not explicit target
                        try:
                            # Path for matching should be relative to the rule discovery root
                            path_for_match = str(file_path.relative_to(rule_discovery_root)).replace(os.sep, '/')
                            if debug_explain: logger.debug(f"Checking file: {file_path} against spec {spec_source_desc} using path: '{path_for_match}'")
                            if active_spec.match_file(path_for_match):
                                should_include = True
                                reason = f"Included by {spec_source_desc}"
                                if debug_explain: logger.debug(f"Including File: {file_path} ({reason} matching '{path_for_match}')")
                            else:
                                reason = f"Excluded by {spec_source_desc}"
                                if debug_explain: logger.debug(f"Excluding File: {file_path} ({reason} matching '{path_for_match}')")
                        except ValueError:
                             logger.warning(f"Could not make file path {file_path} relative to rule root {rule_discovery_root} for rule check.")
                             reason = "Error calculating relative path for rule check"
                        except Exception as e_match:
                             logger.error(f"Error checking file {file_path} against spec: {e_match}")
                             reason = f"Error during rule check: {e_match}"


                    if not should_include:
                        continue

                    # --- Passed Rule Check (or explicit target) ---
                    # Perform binary check first
                    if _is_binary(file_path):
                         if debug_explain: logger.debug(f"Skipping File: {file_path} -> Detected as binary (check applied for list_only={list_only})")
                         continue

                    # Binary check passed, now get info and check size
                    file_info = get_file_info(file_path)
                    file_stat_size = file_info['size']

                    if total_size_bytes + file_stat_size > size_limit_bytes:
                         if file_stat_size > size_limit_bytes and total_size_bytes == 0:
                             # Log warning only if size check fails *after* passing binary check
                             logger.warning(f"File {file_path} ({file_stat_size} bytes) exceeds size limit of {effective_limit_mb}MB. Skipping.")
                             continue
                         else:
                             raise ContextSizeExceededError(effective_limit_mb, total_size_bytes + file_stat_size)

                    # --- Both binary and size checks passed ---

                    # Get relative path for output
                    try:
                        relative_path_str = str(file_path.relative_to(output_rel_root)).replace(os.sep, '/')
                    except ValueError:
                        relative_path_str = str(file_path) # Fallback

                    # Add to output
                    if list_only:
                        output_line = f"{file_stat_size}\t{relative_path_str}" if include_size_in_list else relative_path_str
                        output_parts.append(output_line)
                        processed_files_set.add(file_path)
                    else:
                        try:
                            file_bytes = file_path.read_bytes()
                            actual_file_size = len(file_bytes)
                            # Double check size after reading
                            if total_size_bytes + actual_file_size > size_limit_bytes:
                                 if actual_file_size > size_limit_bytes and total_size_bytes == 0:
                                     logger.warning(f"File {file_path} ({actual_file_size} bytes) exceeds size limit of {effective_limit_mb}MB after read. Skipping.")
                                     continue
                                 else:
                                     raise ContextSizeExceededError(effective_limit_mb, total_size_bytes + actual_file_size)

                            content: Optional[str] = None
                            encodings_to_try = ['utf-8', 'latin-1', 'cp1252']
                            for enc in encodings_to_try:
                                try:
                                    content = file_bytes.decode(enc)
                                    break
                                except UnicodeDecodeError:
                                    continue
                            if content is None:
                                 logger.warning(f"Could not decode file {file_path} using {encodings_to_try}. Skipping content.")
                                 continue

                            header = (
                                f"File: {relative_path_str}\n"
                                f"Size: {actual_file_size} bytes\n"
                                f"Last Modified: {file_info['last_modified']}\n"
                                f"{'=' * 80}\n"
                            )
                            output_parts.append(header + "\n" + content)
                            processed_files_set.add(file_path)
                            total_size_bytes += actual_file_size

                        except OSError as e_read:
                            logger.warning(f"Error reading file {file_path}: {e_read}")
                        except Exception as e_general:
                             logger.warning(f"Unexpected error processing file {file_path}: {e_general}")
                # --- End File Loop ---
            # --- End os.walk Loop ---
        else:
             logger.warning(f"Target path is neither a file nor a directory: {target_path}")
    # --- End Target Loop ---

    # --- Final Output Formatting ---
    final_output = "\n".join(output_parts) if list_only else SEPARATOR.join(output_parts)

    logger.info(f"Processed {len(processed_files_set)} files, total size: {total_size_bytes} bytes.")
    return final_output