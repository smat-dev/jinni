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
# Import from refactored modules
from jinni.core_logic import read_context, DEFAULT_SIZE_LIMIT_MB, ENV_VAR_SIZE_LIMIT # Re-add ENV_VAR_SIZE_LIMIT
from jinni.exceptions import ContextSizeExceededError, DetailedContextSizeError # Exceptions moved
from jinni.utils import ESSENTIAL_USAGE_DOC # Import the shared usage doc constant
# ENV_VAR_SIZE_LIMIT is likely handled internally now
import pyperclip # Added for clipboard functionality

# Setup logger for CLI - will be configured in main()
logger = logging.getLogger("jinni.cli")
DEBUG_LOG_FILENAME = "jinni_debug.log"

# --- Command Handlers ---

def handle_usage_command(args):
    """Handles displaying the essential usage documentation."""
    logger.debug("Executing essential usage display.")
    # Use the imported constant from utils.py
    print(ESSENTIAL_USAGE_DOC)

def handle_read_command(args):
    """Handles the context reading logic."""
    logger.debug("Executing context read logic.")
    # --- Input Validation ---
    input_paths = args.paths # Use 'paths' from main parser (list)
    output_file = args.output
    list_only = args.list_only
    overrides_file = args.overrides
    size_limit_mb = args.size_limit_mb
    debug_explain = args.debug_explain
    project_root = args.project_root # Optional root from main parser
    no_copy_flag = args.no_copy

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
    if overrides_file:
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

    # --- Determine Effective Target Paths ---
    # If default paths=['.'] is used AND a project_root is given, target the root.
    # Otherwise, use the provided paths (or '.' if no root and no paths).
    effective_target_paths = input_paths
    if input_paths == ['.'] and project_root:
         effective_target_paths = [project_root]
         logger.debug(f"No explicit paths provided; targeting specified project root: {project_root}")
    elif input_paths == ['.'] and not project_root:
         logger.debug("No explicit paths or project root provided; targeting default '.'")
         # Keep effective_target_paths as ['.']
    else:
         logger.debug(f"Using explicitly provided paths: {input_paths}")
         # Keep effective_target_paths as input_paths

    # --- Call Core Logic ---
    try:
        # Call the refactored core_logic function
        # Call the core logic function, passing the list of paths and optional root
        result_content = read_context(
            target_paths_str=effective_target_paths, # Use adjusted target paths
            project_root_str=project_root,           # Pass the optional project_root
            override_rules=override_rules_list,
            list_only=list_only,
            size_limit_mb=size_limit_mb,
            debug_explain=debug_explain,
            include_size_in_list=args.size # Pass the CLI arg value
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
    # --- Updated Error Handling ---
    except DetailedContextSizeError as e:
        # Print the detailed message from the exception
        print(f"\n{e.detailed_message}", file=sys.stderr)
        sys.exit(1)
    except ContextSizeExceededError as e: # Keep this as a fallback? core_logic should raise Detailed now.
        print(f"\nError: {e}", file=sys.stderr) # Generic message if Detailed isn't caught somehow
        sys.exit(1)
    # --- End Updated Error Handling ---
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


def main():
    parser = argparse.ArgumentParser(
        description="Jinni: Process project files for LLM context or view documentation.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  jinni ./my_project                  # Process context for my_project
  jinni ./src ../docs/README.md       # Process multiple targets
  jinni -l .                          # List files in current directory
  jinni -o ctx.txt ./src              # Write src context to file
  jinni -r /abs/path/root ./project   # Use specific root for output paths
  jinni --usage                       # Display usage documentation
"""
    )

    # --- Define Arguments for Main Parser (No Subparsers) ---
    parser.add_argument(
        "paths",
        nargs='*', # 0 or more paths
        default=['.'], # Default to current directory
        help="Paths to project directories or files to analyze (default: '.')."
    )
    parser.add_argument(
        "-r",
        "--root",
        dest="project_root",
        metavar="<dir>",
        default=None, # Optional
        help="Specify the project root directory for output path relativity (Default: common ancestor of targets)."
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
    parser.add_argument(
        "--overrides",
        metavar="<file>",
        help="Specify an overrides file (using .contextfiles format). If provided, all .contextfiles are ignored."
    )
    parser.add_argument(
        "-s",
        "--size-limit-mb",
        type=int,
        default=None,
        help=f"Override the maximum total context size in MB (Default: ${ENV_VAR_SIZE_LIMIT} or {DEFAULT_SIZE_LIMIT_MB}MB)."
    )
    parser.add_argument(
        "--debug-explain",
        action="store_true",
        help="Print detailed explanation for file/directory inclusion/exclusion to stderr."
    )
    parser.add_argument(
        "--no-copy",
        action="store_true",
        help="Do not automatically copy the output content to the clipboard when printing to stdout."
    )
    parser.add_argument(
        "--usage",
        action="store_true",
        help="Display the Jinni usage documentation (README.md) and exit."
    )

    # --- Parse Arguments ---
    args = parser.parse_args()

    # --- Execute based on args ---
    if args.usage:
        # If --usage is used, ignore other arguments and show usage
        handle_usage_command(args)
    else:
        # Otherwise, proceed with reading context
        handle_read_command(args)

if __name__ == "__main__":
    main()
# Removed duplicated code block from previous failed diff