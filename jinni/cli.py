# jinni/cli.py
import sys
import argparse
import os
from pathlib import Path
from typing import List, Optional, Set # Added Set

# Ensure jinni package is importable if running script directly
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import logging
import logging.handlers
# Updated import: core_logic now likely exposes a single main function
from jinni.core_logic import read_context, ContextSizeExceededError, DEFAULT_SIZE_LIMIT_MB, ENV_VAR_SIZE_LIMIT
import pyperclip # Added for clipboard functionality

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
  jinni ./src ../docs/README.md       # Dump context for multiple targets
  jinni -l ./my_project               # List files that would be included
  jinni -o context.txt ./my_project   # Write context to context.txt
  jinni --overrides ../custom.rules . # Use override rules from ../custom.rules
  jinni --debug-explain .             # Show reasons for inclusion/exclusion on stderr
"""
    )
    parser.add_argument(
        "paths",
        nargs='*', # Changed from '+' to '*' to allow zero arguments
        default=['.'], # Default to current directory if no paths are given
        help="Paths to project directories or files to analyze (default: '.')."
    )
    parser.add_argument(
        "--output",
        "-o",
        metavar="<file>",
        help="Write output to a file instead of stdout."
    )
    parser.add_argument(
        "-l",
        "--list-only",
        action="store_true",
        help="Only list file paths found, do not include content."
    )
    parser.add_argument(
        "-S",
        "--size",
        action="store_true",
        help="Show file sizes when using --list-only."
    )
    # Removed --config argument
    parser.add_argument(
        "--overrides", # Added --overrides argument
        metavar="<file>",
        help="Specify an overrides file (using .contextfiles format). If provided, all .contextfiles are ignored."
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
    # Add argument to specify the root for relative path calculation in output
    parser.add_argument(
        "--output-relative-to",
        metavar="<dir>",
        default=None,
        help="Specify a directory path to make output file paths relative to (Default: common ancestor or CWD)."
    )
    parser.add_argument(
        "--no-copy",
        action="store_true",
        help="Do not automatically copy the output content to the clipboard when printing to stdout."
    )

    args = parser.parse_args()

    # --- Input Validation ---
    input_paths = args.paths
    output_file = args.output
    list_only = args.list_only
    overrides_file = args.overrides # Use new argument
    size_limit_mb = args.size_limit_mb
    debug_explain = args.debug_explain
    output_relative_to = args.output_relative_to # Get the new argument value
    no_copy_flag = args.no_copy # Get the new argument value

    # --- Configure Logging ---
    stderr_formatter = logging.Formatter('%(levelname)s:%(name)s:%(message)s')
    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setLevel(logging.DEBUG if debug_explain else logging.WARNING) # Only show WARNING+ on stderr by default
    stderr_handler.setFormatter(stderr_formatter)

    root_logger = logging.getLogger()
    if root_logger.hasHandlers():
        root_logger.handlers.clear()

    root_logger.addHandler(stderr_handler)
    root_logger.setLevel(logging.DEBUG if debug_explain else logging.INFO) # Set root level based on debug

    if debug_explain:
        logger.debug("Debug mode enabled.")
        try:
            file_handler = logging.FileHandler(DEBUG_LOG_FILENAME, mode='w')
            file_handler.setLevel(logging.DEBUG)
            file_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
            file_handler.setFormatter(file_formatter)
            root_logger.addHandler(file_handler)
            logger.debug(f"Also writing DEBUG logs to {DEBUG_LOG_FILENAME}")
        except Exception as e:
            logger.error(f"Failed to configure debug log file handler: {e}")

    # --- Load Override Rules if specified ---
    override_rules_list: Optional[List[str]] = None
    if overrides_file: # Check the new argument
        override_path = Path(overrides_file)
        if not override_path.is_file():
            print(f"Error: Overrides file not found: {overrides_file}", file=sys.stderr)
            sys.exit(1)
        try:
            with open(override_path, 'r', encoding='utf-8') as f:
                # Read lines, strip whitespace, filter empty lines/comments
                override_rules_list = [
                    line for line in (l.strip() for l in f)
                    if line and not line.startswith('#')
                ]
            logger.info(f"Loaded {len(override_rules_list)} override rules from {overrides_file}. .contextfiles will be ignored.")
        except Exception as e:
            print(f"Error reading overrides file '{overrides_file}': {e}", file=sys.stderr)
            sys.exit(1)

    # --- Call Core Logic ---
    try:
        # Call the refactored core_logic function once with all targets
        result_content = read_context(
            target_paths_str=input_paths,
            output_relative_to_str=output_relative_to, # Pass the new argument
            override_rules=override_rules_list, # Pass loaded override rules
            list_only=list_only,
            size_limit_mb=size_limit_mb,
            debug_explain=debug_explain,
            include_size_in_list=args.size # Pass the new CLI arg value
        )

        # --- Output ---
        if output_file:
            try:
                output_path = Path(output_file)
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_text(result_content, encoding='utf-8')
                print(f"Output successfully written to {output_file}", file=sys.stderr)
            except Exception as e:
                print(f"Error writing output to file {output_file}: {e}", file=sys.stderr)
                sys.exit(1)
        else:
            # Print directly to stdout, handling potential trailing newline
            if result_content: # Avoid printing extra newline if content is empty
                 if not result_content.endswith('\n'):
                     print(result_content)
                 else:
                     sys.stdout.write(result_content)
            # Copy to clipboard by default if outputting to stdout, unless --no-copy is specified
            if not no_copy_flag and not output_file:
                try:
                    pyperclip.copy(result_content)
                    # Log as debug unless there's an error, as it's default behavior
                    logger.debug("Output successfully copied to clipboard.")
                except Exception as e:
                    # Pyperclip might raise various errors depending on the OS and setup
                    logger.error(f"Failed to copy output to clipboard: {e}") # Keep error log level


    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except ContextSizeExceededError as e:
        print(f"\nError: {e}", file=sys.stderr)
        sys.exit(1)
    except ValueError as e: # Catch potential errors from core_logic path handling
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"An unexpected error occurred: {type(e).__name__}: {e}", file=sys.stderr)
        # Consider adding traceback logging here if debug_explain is on
        if debug_explain:
            import traceback
            logger.error("Traceback:", exc_info=True) # Log full traceback to debug file
        sys.exit(1)

if __name__ == "__main__":
    main()