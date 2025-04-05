# jinni/context_walker.py
"""Handles directory traversal, rule application, and context gathering."""

import os
import logging
from pathlib import Path
from typing import List, Tuple, Dict, Optional, Any, Set

# Attempt to import pathspec
try:
    import pathspec
except ImportError:
    pathspec = None # Allow import but functions using it will fail

# Import necessary components from other modules
from .config_system import (
    load_rules_from_file,
    compile_spec_from_rules,
    DEFAULT_RULES,
    CONTEXT_FILENAME,
)
from .utils import _find_context_files_for_dir # Assuming utils.py exists
from .file_processor import process_file # Assuming file_processor.py exists
from .exceptions import ContextSizeExceededError # Assuming exceptions.py exists

# Setup logger for this module
logger = logging.getLogger("jinni.context_walker")
if not logger.handlers and not logging.getLogger().handlers:
     logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

def walk_and_process(
    walk_target_path: Path,
    rule_discovery_root: Path,
    output_rel_root: Path,
    initial_target_paths_set: Set[Path], # Set of explicitly provided targets (for always-include logic)
    use_overrides: bool,
    override_spec: Optional['pathspec.PathSpec'], # Forward reference PathSpec
    size_limit_bytes: int,
    list_only: bool,
    include_size_in_list: bool,
    debug_explain: bool
) -> Tuple[List[str], int, Set[Path]]:
    """
    Walks a directory, applies rules, processes files, and returns results.

    Args:
        walk_target_path: The directory path to start walking from.
        rule_discovery_root: The root directory boundary for discovering .contextfiles upwards.
        output_rel_root: The root directory for calculating relative output paths.
        initial_target_paths_set: Set of absolute paths provided as initial targets.
        use_overrides: Whether to use override rules instead of .contextfiles.
        override_spec: The compiled PathSpec from override rules (if use_overrides is True).
        size_limit_bytes: Maximum total context size allowed.
        list_only: If True, only collect file paths.
        include_size_in_list: If True and list_only, prepend size to path.
        debug_explain: If True, log detailed processing steps.

    Returns:
        A tuple containing:
        - List of output strings (formatted file content or paths).
        - Total size in bytes of the processed file content (0 if list_only).
        - Set of absolute paths of the files processed.
    """
    if pathspec is None and not use_overrides:
        raise ImportError("pathspec library is required for rule processing but not installed.")

    output_parts: List[str] = []
    processed_files_set: Set[Path] = set()
    total_size_bytes: int = 0

    for dirpath_str, dirnames, filenames in os.walk(str(walk_target_path), topdown=True, followlinks=False):
        current_dir_path = Path(dirpath_str).resolve()
        dirnames.sort()
        filenames.sort()
        if debug_explain: logger.debug(f"--- Walking directory: {current_dir_path} ---")

        # --- Determine Active Spec for this Directory ---
        active_spec: Optional['pathspec.PathSpec'] = None # Forward reference
        spec_source_desc: str = "N/A"
        if use_overrides:
            active_spec = override_spec
            spec_source_desc = "Overrides"
        else:
            # Find context files from rule_discovery_root down to current_dir_path
            # Find context files from walk_target_path down to current_dir_path
            # Find context files from rule_discovery_root down to current_dir_path
            context_files_in_path = _find_context_files_for_dir(current_dir_path, rule_discovery_root)
            if debug_explain: logger.debug(f"Found context files for {current_dir_path}: {context_files_in_path}")
            # Load rules from all found context files
            current_rules = list(DEFAULT_RULES) # Start with defaults
            for cf_path in context_files_in_path:
                current_rules.extend(load_rules_from_file(cf_path))
            # Compile spec for this specific directory
            try:
                # Path description relative to the rule discovery root for clarity
                relative_dir_desc = current_dir_path.relative_to(rule_discovery_root)
                spec_source_desc = f"Context files up to ./{relative_dir_desc}" if str(relative_dir_desc) != '.' else "Context files at root"
            except ValueError:
                spec_source_desc = f"Context files up to {current_dir_path}" # Fallback
            if debug_explain: logger.debug(f"Combined rules for {current_dir_path}: {current_rules}")
            active_spec = compile_spec_from_rules(current_rules, spec_source_desc)
            if debug_explain: logger.debug(f"Compiled spec for {current_dir_path} from {spec_source_desc} ({len(active_spec.patterns)} patterns)")

        if active_spec is None:
             logger.error(f"Could not determine active pathspec for directory {current_dir_path}. Skipping directory content.")
             dirnames[:] = [] # Prevent further traversal into this branch
             continue

        # --- Prune Directories ---
        dirnames_to_remove = []
        for dirname in dirnames:
            sub_dir_path = (current_dir_path / dirname).resolve()

            # Skip symlinks
            if sub_dir_path.is_symlink():
                dirnames_to_remove.append(dirname)
                if debug_explain: logger.debug(f"Pruning Directory (Symlink): {sub_dir_path}")
                continue

            # Check directory against active spec ONLY if not using overrides
            if not use_overrides:
                try:
                    # Path for matching should be relative to the rule discovery root
                    # Path for matching should be relative to the rule discovery root
                    path_for_match = str(sub_dir_path.relative_to(rule_discovery_root)).replace(os.sep, '/') + '/'
                    if not active_spec.match_file(path_for_match):
                        dirnames_to_remove.append(dirname)
                        if debug_explain: logger.debug(f"Pruning Directory: {sub_dir_path} (excluded by {spec_source_desc} matching '{path_for_match}')")
                    elif debug_explain:
                         logger.debug(f"Keeping Directory: {sub_dir_path} (included by {spec_source_desc} matching '{path_for_match}')")
                except ValueError:
                     logger.warning(f"Could not make directory path {sub_dir_path} relative to rule discovery root {rule_discovery_root} for pruning check.")
                except Exception as e_prune:
                     logger.error(f"Error checking directory {sub_dir_path} against spec: {e_prune}")
            elif debug_explain:
                # When using overrides, we generally don't prune dirs based on the spec,
                # unless there's an explicit '!dir/' rule (which pathspec handles implicitly).
                # Log that we are keeping it because overrides are active.
                logger.debug(f"Keeping Directory (Overrides Active): {sub_dir_path}")

        if dirnames_to_remove:
            dirnames[:] = [d for d in dirnames if d not in dirnames_to_remove]
        # --- End Pruning ---


        # --- Process Files in Current Directory ---
        for filename in filenames:
            file_path = (current_dir_path / filename).resolve()

            if file_path in processed_files_set:
                if debug_explain: logger.debug(f"Skipping File: {file_path} -> Already processed")
                continue

            # Check if file should be included based on rules
            # Explicit target check is handled before calling walk_and_process
            should_include = False
            reason = ""
            try:
                # Path for matching should be relative to the rule discovery root
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
                 logger.warning(f"Could not make file path {file_path} relative to rule discovery root {rule_discovery_root} for rule check.")
                 reason = "Error calculating relative path for rule check"
            except Exception as e_match:
                 logger.error(f"Error checking file {file_path} against spec: {e_match}")
                 reason = f"Error during rule check: {e_match}"


            if not should_include:
                continue

            # --- Passed Rule Check ---
            # Call file processor
            try:
                file_output, file_size_added = process_file(
                    file_path=file_path,
                    output_rel_root=output_rel_root,
                    size_limit_bytes=size_limit_bytes,
                    total_size_bytes=total_size_bytes,
                    list_only=list_only,
                    include_size_in_list=include_size_in_list,
                    debug_explain=debug_explain
                )

                if file_output is not None:
                    output_parts.append(file_output)
                    processed_files_set.add(file_path)
                    total_size_bytes += file_size_added

            except ContextSizeExceededError:
                 # Re-raise to be caught by the main function
                 raise
            except Exception as e_proc:
                 logger.error(f"Error processing file {file_path} via file_processor: {e_proc}")

        # --- End File Loop ---
    # --- End os.walk Loop ---

    return output_parts, total_size_bytes, processed_files_set