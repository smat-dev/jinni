# jinni/cli.py
import sys
import argparse # Keep only one import
import os
from pathlib import Path
from typing import List, Optional

# Ensure jinni package is importable if running script directly
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import logging # Added
import logging.handlers # Added for FileHandler
from jinni.core_logic import process_directory, ContextSizeExceededError, DEFAULT_SIZE_LIMIT_MB, ENV_VAR_SIZE_LIMIT
# No longer need parse_rules here as core_logic handles string lists

# Setup logger for CLI - will be configured in main()
logger = logging.getLogger("jinni.cli")
DEBUG_LOG_FILENAME = "jinni_debug.log"
def main():
    parser = argparse.ArgumentParser(
        description="Jinni: Concatenate relevant project files for LLM context.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  jinni ./my_project                  # Dump context of my_project to stdout
  jinni -l ./my_project               # List files that would be included
  jinni -o context.txt ./my_project   # Write context to context.txt
  jinni --config ../global.rules .    # Use global rules from ../global.rules
  jinni --debug-explain .             # Show reasons for inclusion/exclusion on stderr
"""
    )
    parser.add_argument(
        "paths", # Renamed argument
        nargs='+', # Accept one or more arguments
        help="One or more paths to project directories or files to analyze."
    )
    parser.add_argument(
        "--output",
        "-o",
        metavar="<file>",
        help="Write output to a file instead of stdout."
    )
    parser.add_argument(
        "-l",
        "--list",
        action="store_true",
        help="Only list file paths found, do not include content."
    )
    parser.add_argument(
        "--config",
        metavar="<file>",
        help="Specify a global config file (using .contextfiles format). Applied before defaults."
    )
    parser.add_argument(
        "-s",
        "--size-limit-mb",
        type=int,
        default=None, # Will use ENV or default if not provided
        help=f"Override the maximum total context size in MB (Default: ${ENV_VAR_SIZE_LIMIT} or {DEFAULT_SIZE_LIMIT_MB}MB)."
    )
    parser.add_argument(
        "--debug-explain",
        action="store_true",
        help="Print detailed explanation for file/directory inclusion/exclusion to stderr."
    )
    args = parser.parse_args()

    # --- Input Validation ---
    # target_path = args.path # Removed old single path access
    input_paths = args.paths # Get the list of paths
    output_file = args.output
    list_only = args.list # Update variable assignment
    config_file = args.config
    size_limit_mb = args.size_limit_mb
    debug_explain = args.debug_explain
    # --- Configure Logging ---
    # Basic config for stderr at INFO level
    # Use a specific format for console output
    stderr_formatter = logging.Formatter('%(levelname)s:%(name)s:%(message)s')
    stderr_handler = logging.StreamHandler(sys.stderr)
    # Set stderr handler level based on debug flag
    stderr_handler.setLevel(logging.DEBUG if debug_explain else logging.INFO)
    stderr_handler.setFormatter(stderr_formatter)

    # Get the root logger and remove existing handlers to avoid duplicates/conflicts
    root_logger = logging.getLogger()
    # Clear existing handlers (important if run multiple times or by test runners)
    if root_logger.hasHandlers():
        root_logger.handlers.clear()

    root_logger.addHandler(stderr_handler)
    root_logger.setLevel(logging.INFO) # Default level for root

    if debug_explain:
        # If debug explain is on, set root level to DEBUG *before* adding file handler
        root_logger.setLevel(logging.DEBUG)
        logger.debug("Debug mode enabled. Setting root logger level to DEBUG.") # Add log confirmation
        # Add a file handler specifically for DEBUG messages
        try:
            # Create a file handler for the debug log
            # Use 'w' mode to clear the log on each run with --debug-explain
            file_handler = logging.FileHandler(DEBUG_LOG_FILENAME, mode='w')
            file_handler.setLevel(logging.DEBUG)
            # Use a more detailed format for the debug file
            file_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
            file_handler.setFormatter(file_formatter)
            root_logger.addHandler(file_handler)
            logger.debug(f"Also writing DEBUG logs to {DEBUG_LOG_FILENAME}")
        except Exception as e:
            logger.error(f"Failed to configure debug log file handler: {e}")
            # Continue without file logging if handler setup fails
    # else: # Remove the else block, no need to log specifically when INFO is default
         # logger.debug(f"Log level set to INFO (stderr only)") # Changed to DEBUG if we wanted it

    # --- Load Global Rules if specified ---
    global_rules_str_list: Optional[List[str]] = None
    if config_file: # Use args.config here
        config_path = Path(config_file)
        if not config_path.is_file():
            print(f"Error: Global config file not found: {config_file}", file=sys.stderr)
            sys.exit(1)
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                # Read lines, strip whitespace, filter empty lines/comments
                global_rules_str_list = [
                    line for line in (l.strip() for l in f)
                    if line and not line.startswith('#')
                ]
        except Exception as e:
            print(f"Error reading global config file '{config_file}': {e}", file=sys.stderr)
            sys.exit(1)

    # --- Process Multiple Paths ---
    all_results: List[str] = []
    processed_files: Set[Path] = set() # Keep track of processed files to avoid duplicates
    output_rel_root: Optional[Path] = None # Root for calculating OUTPUT relative paths
    project_root_for_rules: Optional[Path] = None # Root boundary for rule discovery

    for target_path_str in input_paths:
        logger.debug(f"--- Processing path: {target_path_str} ---")
        # --- Resolve and Validate Each Path ---
        if not os.path.isabs(target_path_str):
            target_path_abs = Path(target_path_str).resolve()
            logger.debug(f"Resolved relative path '{target_path_str}' to '{target_path_abs}'")
        else:
            target_path_abs = Path(target_path_str).resolve() # Resolve to normalize (e.g., remove '..')

        if not target_path_abs.exists():
             logger.error(f"Error: Path does not exist: {target_path_abs}")
             # Continue to next path instead of exiting? Or exit? Let's continue for now.
             continue

        # Determine the root for context file searching.
        # If the path is a file, the root is its parent directory.
        # If the path is a directory, the root is the directory itself.
        # This assumes .contextfiles apply from the directory containing the item or its parents.
        if target_path_abs.is_file():
            effective_root_path = target_path_abs.parent
        elif target_path_abs.is_dir():
            effective_root_path = target_path_abs
        else:
            logger.error(f"Error: Path is not a file or directory: {target_path_abs}")
            continue

        # --- Determine Roots (Once) ---
        if output_rel_root is None or project_root_for_rules is None:
            # Find the first valid path to base roots on
            first_valid_path_str = None
            for p_str in input_paths:
                # Check existence relative to CWD if path is relative
                p = Path(p_str)
                check_path = p if p.is_absolute() else Path.cwd() / p
                if check_path.exists():
                    first_valid_path_str = p_str
                    break

            if first_valid_path_str:
                first_path_abs = Path(first_valid_path_str).resolve()
                # For simplicity, use the first valid path's location to determine both roots.
                # Rule root is the directory itself, or parent if it's a file.
                # Output root is the same for consistent relative paths.
                if first_path_abs.is_file():
                    determined_root = first_path_abs.parent
                elif first_path_abs.is_dir():
                    determined_root = first_path_abs
                else: # Should not happen if exists() passed, but safety fallback
                    logger.warning(f"First valid path '{first_valid_path_str}' is neither file nor directory? Falling back to CWD.")
                    determined_root = Path.cwd()

                if output_rel_root is None:
                     output_rel_root = determined_root
                     logger.debug(f"Setting output relative root for all paths to: {output_rel_root}")
                if project_root_for_rules is None:
                     project_root_for_rules = determined_root
                     logger.debug(f"Setting project root boundary for rule discovery to: {project_root_for_rules}")
            else:
                # If no valid input paths found, fallback to CWD for both
                logger.warning("No valid input paths found. Falling back to CWD for roots.")
                if output_rel_root is None: output_rel_root = Path.cwd()
                if project_root_for_rules is None: project_root_for_rules = Path.cwd()

        # Ensure roots are set before proceeding (should always be true after above logic)
        if output_rel_root is None or project_root_for_rules is None:
             logger.error("Critical error: Root paths could not be determined. Exiting.")
             sys.exit(1)

        # --- Call Core Logic ---
        try:
            result_part, processed_files = process_directory( # Capture updated set
                # root_path_str defines the *boundary* for rule discovery.
                root_path_str=str(project_root_for_rules),
                # output_rel_root_str defines the base for relative paths in output headers.
                output_rel_root_str=str(output_rel_root),
                processing_target_str=str(target_path_abs),
                processed_files_set=processed_files, # Pass the current set
                list_only=list_only,
                inline_rules_str=None,
                global_rules_str=global_rules_str_list,
                size_limit_mb=size_limit_mb,
                debug_explain=debug_explain
            )
            # Ensure result_part is not None before appending (important for list_only too)
            if result_part is not None:
                all_results.append(result_part)
            # The processed_files set is updated in-place by the function call

        except FileNotFoundError as e:
            logger.error(f"Error processing {target_path_abs}: {e}")
            # Continue to next path

        except FileNotFoundError as e:
            logger.error(f"Error processing {target_path_abs}: {e}")
            # Continue to next path
        except ContextSizeExceededError as e:
            logger.error(f"Error processing {target_path_abs}: {e}")
            sys.exit(1) # Exit if size limit hit anywhere
        except ValueError as e:
            logger.error(f"Error processing {target_path_abs}: {e}")
            # Continue to next path
        except Exception as e:
            logger.error(f"An unexpected error occurred processing {target_path_abs}: {type(e).__name__}: {e}")
            # Continue to next path? Or exit? Let's continue.

    # Combine results
    if list_only:
        # For list_only, just join with newlines
        result_content = "\n".join(all_results)
    else:
        # For content mode, join with the standard separator
        result_content = ("\n\n" + "=" * 80 + "\n\n").join(all_results) if all_results else ""
    # No need to remove leading separator as join handles it correctly

    # --- Output ---
    # (This part remains largely the same, operating on the final result_content)
    try:

        # --- Output ---
        if output_file:
            try:
                output_path = Path(output_file)
                output_path.parent.mkdir(parents=True, exist_ok=True) # Ensure dir exists
                output_path.write_text(result_content, encoding='utf-8')
                print(f"Output successfully written to {output_file}", file=sys.stderr)
            except Exception as e:
                print(f"Error writing output to file {output_file}: {e}", file=sys.stderr)
                sys.exit(1)
        else:
            # Print directly to stdout
            # Ensure consistent newline handling
            if not result_content.endswith('\n'):
                 print(result_content)
            else:
                 # Use sys.stdout.write to avoid extra newline from print()
                 sys.stdout.write(result_content)


    except FileNotFoundError as e:
        # Should be caught by initial validation, but handle defensively
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except ContextSizeExceededError as e:
        print(f"\nError: {e}", file=sys.stderr) # Add newline for separation from debug output
        sys.exit(1)
    except ValueError as e:
        # e.g., from absolute path check if validation missed it
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        # Catch-all for unexpected errors during processing
        print(f"An unexpected error occurred: {type(e).__name__}: {e}", file=sys.stderr)
        # Consider adding traceback here for debugging
        sys.exit(1)

if __name__ == "__main__":
    main()