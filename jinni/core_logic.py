# jinni/core_logic.py
"""
Core orchestration logic for Jinni context processing.
Handles flexible root/target inputs from CLI and Server, validates inputs,
and delegates processing to walker and file processor modules.
"""

import sys
import os
import logging
from pathlib import Path
from typing import List, Tuple, Dict, Optional, Any, Set

# Attempt to import pathspec (needed for override spec compilation)
try:
    import pathspec
except ImportError:
    pathspec = None

# Import from sibling modules
from .config_system import (
    compile_spec_from_rules,
    DEFAULT_RULES,
)
from .exceptions import (
    ContextSizeExceededError,
    DetailedContextSizeError,
)
from .utils import (
    get_large_files,
    get_usage_doc, # Renamed from get_jinni_doc
    _find_context_files_for_dir, # Needed by context_walker, but keep import here for now? No, walker imports it.
)
from .file_processor import process_file
from .context_walker import walk_and_process

# Setup logger for this module
logger = logging.getLogger("jinni.core_logic")
if not logger.handlers and not logging.getLogger().handlers:
     logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# --- Constants ---
DEFAULT_SIZE_LIMIT_MB = 100
ENV_VAR_SIZE_LIMIT = 'JINNI_MAX_SIZE_MB'
SEPARATOR = "\n\n" + "=" * 80 + "\n"

# --- Main Processing Function ---
def read_context(
    target_paths_str: List[str], # List of targets from CLI or constructed by Server
    project_root_str: Optional[str] = None, # Optional from CLI, Mandatory from Server (used as base)
    override_rules: Optional[List[str]] = None,
    list_only: bool = False,
    size_limit_mb: Optional[int] = None,
    debug_explain: bool = False,
    include_size_in_list: bool = False
) -> str:
    """
    Orchestrates the context reading process, handling flexible inputs.

    Validates inputs, determines the effective roots for rule discovery and output,
    resolves targets, and delegates processing to file_processor or context_walker.

    Args:
        target_paths_str: List of target file/directory paths (relative or absolute).
        project_root_str: Optional path to the project root. If provided, it's used as the
                          base for rule discovery and output relativity. If None, it's
                          inferred from the common ancestor of targets.
        override_rules: Optional list of rule strings to use instead of .contextfiles.
        list_only: If True, only return a list of relative file paths.
        size_limit_mb: Optional override for the size limit in MB.
        debug_explain: If True, log inclusion/exclusion reasons.
        include_size_in_list: If True and list_only, prepend size to path.

    Returns:
        A formatted string (concatenated content or file list).

    Raises:
        FileNotFoundError: If any target path does not exist.
        ValueError: If paths have issues (e.g., target outside explicit root).
        DetailedContextSizeError: If context size limit is exceeded.
        ImportError: If pathspec is required but not installed.
    """
    # --- Initial Setup & Validation ---

    # Validate project_root_str FIRST if provided, and set roots
    output_rel_root: Path
    rule_discovery_root: Path
    project_root_path: Optional[Path] = None # Store resolved explicit project_root

    if project_root_str:
        project_root_path = Path(project_root_str).resolve()
        if not project_root_path.is_dir():
            # Raise ValueError immediately if explicit root is invalid
            raise ValueError(f"Provided project root '{project_root_str}' does not exist or is not a directory.")
        output_rel_root = project_root_path
        rule_discovery_root = project_root_path
        logger.debug(f"Using provided project root for output relativity and rule discovery boundary: {output_rel_root}")
    # else: Roots will be determined after resolving targets

    # Resolve target paths (relative to CWD by default)
    target_paths: List[Path] = []
    if not target_paths_str:
         # Handle case where CLI provides no paths (defaults to ['.'])
         # or Server provides no target (meaning process root)
         if project_root_str:
              # If root is given but no targets, process the root
              target_paths_str = [project_root_str]
              logger.debug("No specific targets provided; processing project root.")
         else:
              # If no root and no targets, default to current dir '.'
              target_paths_str = ['.']
              logger.debug("No specific targets or project root provided; processing current directory '.'")

    for p_str in target_paths_str:
        p = Path(p_str).resolve() # Resolve paths here to ensure they are absolute
        if not p.exists():
            raise FileNotFoundError(f"Target path does not exist: {p_str} (resolved to {p})")
        target_paths.append(p)

    if not target_paths:
        logger.warning("No valid target paths could be determined.")
        return ""

    # Determine roots IF project_root wasn't provided explicitly
    if not project_root_path:
        try:
            common_ancestor = Path(os.path.commonpath([str(p) for p in target_paths]))
            calculated_root = common_ancestor if common_ancestor.is_dir() else common_ancestor.parent
        except ValueError:
            logger.warning("Could not find common ancestor for targets. Using CWD as root.")
            calculated_root = Path.cwd().resolve()
        output_rel_root = calculated_root
        rule_discovery_root = calculated_root
        logger.debug(f"Using common ancestor/CWD as output relativity and rule discovery boundary root: {output_rel_root}")
    # else: Roots were already set from the valid project_root_path

    # Ensure roots are set (safeguard)
    if 'output_rel_root' not in locals() or 'rule_discovery_root' not in locals():
         logger.error("Critical error: Output/Rule discovery root could not be determined.")
         raise ValueError("Could not determine a root directory.")

    # Validate targets are within explicit root (if provided) AFTER resolving roots
    if project_root_path:
        for tp in target_paths:
            try:
                # Use is_relative_to for Python 3.9+ or fallback
                if sys.version_info >= (3, 9):
                    if not tp.is_relative_to(project_root_path):
                        raise ValueError(f"Target path {tp} is outside the specified project root {project_root_path}")
                else:
                    tp.relative_to(project_root_path) # Check raises ValueError if not relative
            except ValueError:
                raise ValueError(f"Target path {tp} is outside the specified project root {project_root_path}")

    # (Logic moved above)

    # --- Size Limit (Moved up slightly, no functional change) ---
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
    # Override rules are used only if the list is provided AND non-empty
    use_overrides = bool(override_rules) # bool([]) is False, bool(['rule']) is True
    override_spec: Optional['pathspec.PathSpec'] = None
    if use_overrides:
        if pathspec is None:
             raise ImportError("pathspec library is required for override rules but not installed.")
        logger.info("Override rules provided. Ignoring all .contextfiles.")
        # When overriding, use ONLY the provided rules, not combined with defaults
        override_spec = compile_spec_from_rules(override_rules, "Overrides")
        if debug_explain: logger.debug(f"Compiled override spec with {len(override_spec.patterns)} patterns.")

    # --- Processing State ---
    output_parts: List[str] = []
    processed_files_set: Set[Path] = set()
    total_size_bytes: int = 0
    # Use the resolved target_paths as the initial set for "always include" logic within walker/processor
    initial_target_paths_set: Set[Path] = set(target_paths)

    # --- Delegate Processing ---
    try:
        for current_target_path in target_paths:
            # Skip if already processed (e.g., listed twice or handled by a previous dir walk)
            if current_target_path in processed_files_set:
                 if debug_explain: logger.debug(f"Skipping target {current_target_path} as it was already processed.")
                 continue

            if current_target_path.is_file():
                if debug_explain: logger.debug(f"Processing file target: {current_target_path}")
                file_output, file_size_added = process_file(
                    file_path=current_target_path,
                    output_rel_root=output_rel_root,
                    size_limit_bytes=size_limit_bytes,
                    total_size_bytes=total_size_bytes,
                    list_only=list_only,
                    include_size_in_list=include_size_in_list,
                    debug_explain=debug_explain
                )
                if file_output is not None:
                    # Check if adding this file *content* exceeds limit (only if not list_only)
                    if not list_only and (total_size_bytes + file_size_added > size_limit_bytes):
                         # Check if file alone exceeds limit
                         if file_size_added > size_limit_bytes and total_size_bytes == 0:
                              logger.warning(f"File {current_target_path} ({file_size_added} bytes) content exceeds size limit of {effective_limit_mb}MB. Skipping.")
                              continue # Skip this file
                         else:
                              # Adding this file pushes over the limit
                              raise ContextSizeExceededError(effective_limit_mb, total_size_bytes + file_size_added, current_target_path)

                    output_parts.append(file_output)
                    processed_files_set.add(current_target_path)
                    total_size_bytes += file_size_added # Add size only if content included

            elif current_target_path.is_dir():
                if debug_explain: logger.debug(f"Processing directory target: {current_target_path}")
                dir_output_parts, dir_total_size, dir_processed_files = walk_and_process(
                    walk_target_path=current_target_path,
                    rule_discovery_root=rule_discovery_root,
                    output_rel_root=output_rel_root,
                    initial_target_paths_set=initial_target_paths_set, # Pass initial targets
                    use_overrides=use_overrides,
                    override_spec=override_spec,
                    size_limit_bytes=size_limit_bytes - total_size_bytes, # Pass remaining budget
                    list_only=list_only,
                    include_size_in_list=include_size_in_list,
                    debug_explain=debug_explain
                )
                output_parts.extend(dir_output_parts)
                processed_files_set.update(dir_processed_files)
                total_size_bytes += dir_total_size # Accumulate size from walker
            else:
                 logger.warning(f"Target path is neither a file nor a directory: {current_target_path}")

        # --- Final Output Formatting ---
        final_output = "\n".join(output_parts) if list_only else SEPARATOR.join(output_parts)
        logger.info(f"Processed {len(processed_files_set)} files, total size: {total_size_bytes} bytes.")
        return final_output

    except ContextSizeExceededError as e:
            # Catch error, format with large files list, and raise Detailed error
            logger.error(f"Context size limit exceeded: {e}")
            # Use output_rel_root as the base for finding large files
            large_files = get_large_files(str(output_rel_root))
            error_message = (
                f"Error: Context size limit of {e.limit_mb}MB exceeded.\n"
                f"Processing stopped near file: {e.file_path}\n\n"
                "Consider excluding large files or directories using a `.contextfiles` file.\n"
                "Consult README.md (or use `jinni doc`) for more details on exclusion rules.\n\n"
                "Potential large files found (relative to project root):\n"
            )
            if large_files:
                for fname, fsize in large_files:
                    size_mb = fsize / (1024 * 1024)
                    error_message += f" - {fname} ({size_mb:.2f} MB)\n"
            else:
                error_message += " - Could not identify specific large files.\n"

            raise DetailedContextSizeError(error_message) from e
