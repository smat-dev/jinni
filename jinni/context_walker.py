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
    load_gitignore_as_context_rules,
    compile_spec_from_rules,
    DEFAULT_RULES,
    CONTEXT_FILENAME,
)
from .utils import _find_context_files_for_dir, _find_gitignore_files_for_dir
from .file_processor import process_file
from .exceptions import ContextSizeExceededError

# Setup logger for this module
logger = logging.getLogger("jinni.context_walker")

def walk_and_process(
    walk_target_path: Path, # The directory path to start walking from
    rule_root: Path, # The root for rule discovery - no rules above this point will be considered
    output_rel_root: Path, # Root for calculating final relative output paths
    initial_target_paths_set: Set[Path], # Set of explicitly provided targets (for always-include logic)
    use_overrides: bool,
    override_spec: Optional['pathspec.PathSpec'], # Compiled override spec
    size_limit_bytes: int,
    list_only: bool,
    include_size_in_list: bool,
    debug_explain: bool,
    exclusion_parser: Optional[Any] = None  # ExclusionParser instance for scoped exclusions
) -> Tuple[List[str], int, Set[Path]]:
    """
    Walks a directory, applies rules, processes files, and returns results.

    Args:
        walk_target_path: The directory path to start walking from.
        rule_root: The root for rule discovery - no rules above this point will be considered.
                   This ensures that external targets have self-contained rule sets.
        output_rel_root: The root directory for calculating the final relative output paths
                         that appear in headers or the list output.
        initial_target_paths_set: Set of absolute paths provided as initial targets.
        use_overrides: Whether to use override rules instead of .contextfiles.
        override_spec: The compiled PathSpec from override rules (if use_overrides is True).
        size_limit_bytes: Maximum total context size allowed.
        list_only: If True, only collect file paths.
        include_size_in_list: If True and list_only, prepend size to path.
        debug_explain: If True, log detailed processing steps.
        exclusion_parser: ExclusionParser instance for scoped exclusions.

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

    if debug_explain:
        try:
            logger.debug(f"Pre-walk listdir for {walk_target_path}: {os.listdir(str(walk_target_path))}")
        except Exception as e_list:
            logger.warning(f"Pre-walk listdir failed for {walk_target_path}: {e_list}")

    for dirpath_str, dirnames, filenames in os.walk(str(walk_target_path), topdown=True, followlinks=False):
        current_dir_path = Path(dirpath_str).resolve()
        dirnames.sort()
        filenames.sort()
        if debug_explain: logger.debug(f"--- Walking directory: {current_dir_path} ---")

        # --- Determine Active Spec and Path Match Root ---
        active_spec: Optional['pathspec.PathSpec'] = None
        spec_source_desc: str = "N/A"
        # Path matching is always relative to the walk_target_path
        path_match_root = walk_target_path
        if debug_explain: logger.debug(f"Path matching relative to: {path_match_root}")

        # Always discover rules from contextfiles and gitignore
        context_files_in_path = _find_context_files_for_dir(current_dir_path, rule_root)
        gitignore_files_in_path = _find_gitignore_files_for_dir(current_dir_path, rule_root)
        
        if debug_explain:
            logger.debug(f"Found context files for {current_dir_path} (relative to {rule_root}): {context_files_in_path}")
            logger.debug(f"Found gitignore files for {current_dir_path} (relative to {rule_root}): {gitignore_files_in_path}")

        # Combine default rules, gitignore rules, and rules from discovered files
        current_rules = list(DEFAULT_RULES)  # Start with defaults
        
        # Add gitignore rules
        for gi_path in gitignore_files_in_path:
            current_rules.extend(load_gitignore_as_context_rules(gi_path))
        
        # Add context files rules
        for cf_path in context_files_in_path:
            current_rules.extend(load_rules_from_file(cf_path))

        # If we have overrides, add them as high-priority rules at the end
        if use_overrides:
            override_rules = getattr(override_spec, '_original_rules', [])
            if not override_rules and hasattr(override_spec, 'patterns'):
                override_rules = []
            current_rules.extend(override_rules)
            if debug_explain:
                logger.debug(f"Added {len(override_rules)} override rules as high-priority additions")

        # Add scoped exclusion patterns if applicable
        if exclusion_parser:
            scoped_patterns = exclusion_parser.get_scoped_patterns(current_dir_path, rule_root)
            if scoped_patterns:
                current_rules.extend(scoped_patterns)
                if debug_explain:
                    logger.debug(f"Applied {len(scoped_patterns)} scoped exclusion patterns to {current_dir_path}")
                    for pattern in scoped_patterns:
                        logger.debug(f"  Scoped pattern: {pattern}")

        # Compile spec for this specific directory context
        # Build the source description
        source_parts = ["Default", "Gitignore", "Contextfiles"]
        if use_overrides:
            source_parts.append("Overrides")
        if exclusion_parser and scoped_patterns:
            source_parts.append("ScopedExclusions")
        source_type = "+".join(source_parts)
        
        try:
            relative_dir_desc = current_dir_path.relative_to(walk_target_path)
            if str(relative_dir_desc) == '.':
                spec_source_desc = f"{source_type} at root"
            else:
                spec_source_desc = f"{source_type} up to ./{relative_dir_desc}"
        except ValueError:
            spec_source_desc = f"{source_type} up to {current_dir_path}"

        if debug_explain:
            logger.debug(f"Combined rules for {current_dir_path}: {current_rules}") # Log the combined rules list
        active_spec = compile_spec_from_rules(current_rules, spec_source_desc)
        if debug_explain:
            logger.debug(f"Compiled spec for {current_dir_path} from {spec_source_desc} ({len(active_spec.patterns)} patterns)")
            if active_spec:
                 logger.debug(f"Active spec patterns: {[str(p.regex) for p in active_spec.patterns]}") # Log context patterns

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

            # If the directory is an explicit target, don't prune it based on rules
            if sub_dir_path in initial_target_paths_set:
                if debug_explain: logger.debug(f"Keeping Directory (Explicit Target): {sub_dir_path}")
                continue # Move to the next directory without rule checks

            # Check directory against active spec ONLY if not an explicit target
            try:
                # Path for matching should be relative to path_match_root (walk_target_path)
                path_for_match = str(sub_dir_path.relative_to(path_match_root)).replace(os.sep, '/') + '/'
                is_matched = active_spec.match_file(path_for_match)
                if debug_explain: logger.debug(f"DIR MATCH CHECK: path='{path_for_match}', spec_source='{spec_source_desc}', matched={is_matched}")

                # Determine if we should prune
                should_prune = False
                if not is_matched:
                    # If the directory itself doesn't match, check if we should still keep it
                    # because overrides are active and contain a recursive pattern.
                    # Note: We check patterns in the *original* override_spec if use_overrides is True
                    spec_to_check_for_recursion = override_spec if use_overrides else active_spec
                    contains_recursive_pattern = any('**' in str(p.pattern) for p in spec_to_check_for_recursion.patterns if p.include)

                    if use_overrides and contains_recursive_pattern:
                        if debug_explain: logger.debug(f"Keeping directory {sub_dir_path} despite no direct match, due to recursive override pattern.")
                        should_prune = False # Keep the directory
                    else:
                        # Prune if no direct match AND (not using overrides OR no recursive override pattern)
                        should_prune = True

                if should_prune:
                    dirnames_to_remove.append(dirname)
                    if debug_explain: logger.debug(f"Pruning Directory: {sub_dir_path} (excluded by {spec_source_desc} matching '{path_for_match}' relative to {path_match_root})")
                elif debug_explain:
                     # Log keeping, whether by direct match or recursive override exception
                     reason = f"included by {spec_source_desc}" if is_matched else "kept for recursive override pattern"
                     logger.debug(f"Keeping Directory: {sub_dir_path} ({reason} matching '{path_for_match}' relative to {path_match_root})")

            except ValueError:
                 logger.warning(f"Could not make directory path {sub_dir_path} relative to path match root {path_match_root} for pruning check. Keeping directory.")
            except Exception as e_prune:
                 logger.error(f"Error checking directory {sub_dir_path} against spec: {e_prune}")

        if dirnames_to_remove:
            dirnames[:] = [d for d in dirnames if d not in dirnames_to_remove]
        # --- End Pruning ---


        # --- Process Files in Current Directory ---
        if debug_explain: logger.debug(f"Files in {current_dir_path}: {filenames}") # Log the list of filenames
        for filename in filenames:
            file_path = (current_dir_path / filename).resolve()

            if file_path in processed_files_set:
                if debug_explain: logger.debug(f"Skipping File: {file_path} -> Already processed")
                continue

            # Check if file should be included based on rules OR if it's an explicit target
            should_include = False
            reason = ""

            # Always include if it's an explicitly provided target
            if file_path in initial_target_paths_set:
                should_include = True
                reason = "Explicitly targeted"
                if debug_explain: logger.debug(f"Including File: {file_path} ({reason})")
            else:
                # Otherwise, check against rules. Path matching is always relative to path_match_root (walk_target_path).
                try:
                    # Path for matching should be relative to path_match_root (walk_target_path)
                    path_for_match = str(file_path.relative_to(path_match_root)).replace(os.sep, '/')
                    # if debug_explain: logger.debug(f"Checking file: {file_path} against spec {spec_source_desc} using path: '{path_for_match}' relative to {path_match_root}")
                    is_matched = active_spec.match_file(path_for_match)
                    if debug_explain: logger.debug(f"FILE MATCH CHECK: path='{path_for_match}', spec_source='{spec_source_desc}', matched={is_matched}")
                    if is_matched:
                        should_include = True
                        reason = f"Included by {spec_source_desc}"
                        if debug_explain: logger.debug(f"Including File: {file_path} ({reason} matching '{path_for_match}' relative to {path_match_root})")
                    else:
                        reason = f"Excluded by {spec_source_desc}"
                        if debug_explain: logger.debug(f"Excluding File: {file_path} ({reason} matching '{path_for_match}' relative to {path_match_root})")
                except ValueError:
                     logger.warning(f"Could not make file path {file_path} relative to path match root {path_match_root} for rule check. Excluding file.")
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