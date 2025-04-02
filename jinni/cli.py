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
        "path",
        help="The path to the project directory or file to analyze."
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
    target_path = args.path # Rename for clarity
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
        # If debug explain is on, set root level to DEBUG
        # and add a file handler specifically for DEBUG messages
        root_logger.setLevel(logging.DEBUG)
        try:
            # Create a file handler for the debug log
            # Use 'w' mode to clear the log on each run with --debug-explain
            file_handler = logging.FileHandler(DEBUG_LOG_FILENAME, mode='w')
            file_handler.setLevel(logging.DEBUG)
            # Use a more detailed format for the debug file
            file_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
            file_handler.setFormatter(file_formatter)
            root_logger.addHandler(file_handler)
            logger.debug(f"DEBUG level logging enabled, writing to {DEBUG_LOG_FILENAME}") # Change to DEBUG
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

    # --- Resolve Target Path ---
    if not os.path.isabs(target_path):
        target_path = os.path.abspath(target_path)

    if not os.path.exists(target_path):
         print(f"Error: Path does not exist: {target_path}", file=sys.stderr)
         sys.exit(1)
    # Note: process_directory can handle if target_path is a file, but os.walk starts from its parent.

    # --- Call Core Logic ---
    try:
        result_content = process_directory(
            root_path_str=target_path, # Pass resolved absolute path string
            list_only=list_only,
            inline_rules_str=None, # CLI doesn't support inline rules directly
            global_rules_str=global_rules_str_list,
            size_limit_mb=size_limit_mb,
            debug_explain=debug_explain # Pass the new flag
        )

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