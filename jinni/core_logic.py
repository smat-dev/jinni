import sys
import os
import datetime
import logging
import mimetypes
import string
import importlib.resources # Added for portable resource access
# import puremagic # No longer used for binary detection
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
BINARY_CHECK_CHUNK_SIZE = 1024 # Bytes to read for binary check (used in is_human_readable)

# HUMAN_READABLE_MIMES set removed. Using text/* matching and explicit binary list.
# Define specific application MIME types that should be treated as text
APPLICATION_TEXT_MIMES = {
    'application/json',
    'application/xml',
    'application/xhtml+xml',
    'application/rtf',
    'application/atom+xml',
    'application/rss+xml',
    'application/x-yaml',
    'application/x-www-form-urlencoded',
    'application/javascript',
    'application/ecmascript',
    'application/sql',
    'application/graphql',
    'application/ld+json',
    'application/csv',
}

# --- Custom Exceptions ---
class ContextSizeExceededError(Exception):
    """Custom exception for when context size limit is reached during processing."""
    def __init__(self, limit_mb: int, current_size_bytes: int, file_path: Optional[Path] = None):
        self.limit_mb = limit_mb
        self.current_size_bytes = current_size_bytes
        self.file_path = file_path # The file that potentially caused the exceedance
        message = f"Total content size exceeds limit of {limit_mb}MB"
        if file_path:
            message += f" while processing or checking {file_path}"
        message += ". Processing aborted."
        super().__init__(message)

class DetailedContextSizeError(Exception):
    """Custom exception raised after ContextSizeExceededError, including details."""
    def __init__(self, detailed_message: str):
        self.detailed_message = detailed_message
        super().__init__(detailed_message)
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
            is_readable_heuristic = is_human_readable(file_path) # Re-uses the read chunk implicitly via file pointer? No, need to pass chunk or re-read. Let's re-read for simplicity.
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


def get_jinni_doc() -> str:
    """
    Reads and returns the content of the project's README.md file in a portable way,
    suitable for distribution via npm where file layout is predictable relative to scripts.
    Assumes README.md is located one level above the directory containing this script.
    """
    try:
        # Get the directory containing this script (core_logic.py)
        script_dir = Path(__file__).resolve().parent
        # Assume README.md is in the parent directory of the script's directory
        # e.g., if script is /path/to/node_modules/jinni/jinni/core_logic.py,
        # look for /path/to/node_modules/jinni/README.md
        readme_path = script_dir.parent / 'README.md'

        logger.debug(f"Attempting to read README from script-relative path: {readme_path}")

        if readme_path.is_file():
            return readme_path.read_text(encoding='utf-8')
        else:
            logger.error(f"README.md not found at expected script-relative location: {readme_path}")
            # Try one level higher just in case structure is different (e.g., src layout)
            readme_path_alt = script_dir.parent.parent / 'README.md'
            logger.debug(f"Attempting alternative script-relative path: {readme_path_alt}")
            if readme_path_alt.is_file():
                 return readme_path_alt.read_text(encoding='utf-8')
            else:
                 logger.error(f"README.md also not found at alternative script-relative location: {readme_path_alt}")
                 return f"Error: README.md not found at expected script-relative locations ({readme_path} or {readme_path_alt}). Ensure it's copied correctly during npm packaging."

    except Exception as e:
         logger.exception(f"Error accessing README.md via script-relative path: {e}")
         return f"Error accessing package documentation (README.md): {e}"


def get_large_files(root_dir_str: str = ".", top_n: int = 10) -> List[Tuple[str, int]]:
    """
    Finds the largest files in the project directory, ignoring .git and applying default rules.

    Args:
        root_dir_str: The root directory to search (defaults to current).
        top_n: The number of largest files to return.

    Returns:
        A list of tuples: (relative_path_str, size_in_bytes), sorted descending by size.
    """
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
        DetailedContextSizeError: If context size limit is exceeded, containing details.
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
    try: # Wrap the main processing loop to catch ContextSizeExceededError
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
                         raise ContextSizeExceededError(effective_limit_mb, total_size_bytes + file_stat_size, target_path)

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
                                 raise ContextSizeExceededError(effective_limit_mb, total_size_bytes + actual_file_size, target_path)

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
                                 raise ContextSizeExceededError(effective_limit_mb, total_size_bytes + file_stat_size, file_path)

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
                                         raise ContextSizeExceededError(effective_limit_mb, total_size_bytes + actual_file_size, file_path)

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

    except ContextSizeExceededError as e:
            logger.error(f"Context size limit exceeded: {e}")
            # Find large files starting from the rule discovery root
            large_files = get_large_files(str(rule_discovery_root))
            error_message = (
                f"Error: Context size limit of {e.limit_mb}MB exceeded.\n"
                f"Processing stopped near file: {e.file_path}\n\n"
                "Consider excluding large files or directories using a `.contextfiles` file.\n"
                "Consult README.md (or use `jinni_doc`) for more details on exclusion rules.\n\n"
                "Potential large files found (relative to project root):\n"
            )
            if large_files:
                for fname, fsize in large_files:
                    size_mb = fsize / (1024 * 1024)
                    error_message += f" - {fname} ({size_mb:.2f} MB)\n"
            else:
                error_message += " - Could not identify specific large files.\n"

            raise DetailedContextSizeError(error_message) from e