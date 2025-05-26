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
from jinni.utils import _translate_wsl_path # Import the WSL path translator
from jinni.utils import ensure_no_nul
from jinni.exclusion_parser import create_exclusion_patterns
# ENV_VAR_SIZE_LIMIT is likely handled internally now
import pyperclip # Added for clipboard functionality
import tiktoken # Added for token counting

# Setup logger for CLI - will be configured in main()
logger = logging.getLogger("jinni.cli")
DEBUG_LOG_FILENAME = "jinni_debug.log"

# --- Command Handlers ---

def handle_usage_command(args):
    """Handles displaying the essential usage documentation."""
    logger.debug("Executing essential usage display.")
    # Use the imported constant from utils.py
    print(ESSENTIAL_USAGE_DOC)

def handle_list_token_command(args):
    """Handles listing files with token counts."""
    logger.debug("Executing list token logic.")
    # Reuse setup from handle_read_command
    translated_input_paths = [_translate_wsl_path(p) for p in args.paths]
    translated_project_root = _translate_wsl_path(args.project_root) if args.project_root else None
    translated_overrides_file = _translate_wsl_path(args.overrides) if args.overrides else None

    if translated_project_root:
        ensure_no_nul(translated_project_root, "project_root")
    for p in translated_input_paths:
        ensure_no_nul(p, "input path")

    input_paths = translated_input_paths
    overrides_file = translated_overrides_file
    size_limit_mb = args.size_limit_mb
    debug_explain = args.debug_explain
    project_root = translated_project_root

    # Minimal logging setup for this command
    logging.basicConfig(level=logging.DEBUG if debug_explain else logging.INFO, format='%(levelname)s:%(name)s:%(message)s')
    if debug_explain:
        logger.info("Debug mode enabled for list-token.")

    override_rules_list: Optional[List[str]] = None
    if overrides_file:
        override_path = Path(overrides_file)
        if not override_path.is_file():
            print(f"Error: Overrides file not found: {overrides_file}", file=sys.stderr)
            sys.exit(1)
        try:
            with open(override_path, 'r', encoding='utf-8') as f:
                override_rules_list = [line for line in (l.strip() for l in f) if line and not line.startswith('#')]
            logger.info(f"Loaded {len(override_rules_list)} override rules from {overrides_file}.")
        except Exception as e:
            print(f"Error reading overrides file '{overrides_file}': {e}", file=sys.stderr)
            sys.exit(1)

    # --- Process Exclusion Arguments ---
    keep_only_modules = None
    if args.keep_only:
        keep_only_modules = [m.strip() for m in args.keep_only.split(',') if m.strip()]
    
    exclusion_patterns, exclusion_parser = create_exclusion_patterns(
        not_keywords=args.not_keywords,
        not_in_scoped=args.not_in_scoped,
        not_files=args.not_files,
        keep_only_modules=keep_only_modules
    )
    
    # If we have any exclusions (including scoped ones), we need to use override mode
    if exclusion_patterns or exclusion_parser:
        if override_rules_list is None:
            # When using exclusions without an override file, start with empty list
            # The walker will apply defaults, gitignore, and contextfiles first
            override_rules_list = []
        if exclusion_patterns:
            override_rules_list.extend(exclusion_patterns)
            logger.info(f"Added {len(exclusion_patterns)} exclusion patterns from CLI flags")
            for pattern in exclusion_patterns:
                logger.debug(f"Exclusion pattern: {pattern}")

    effective_target_paths = input_paths
    if input_paths == ['.'] and project_root:
         effective_target_paths = [project_root]
         logger.debug(f"Targeting specified project root: {project_root}")
    elif input_paths == ['.'] and not project_root:
         logger.debug("Targeting default '.'")
    else:
         logger.debug(f"Using explicitly provided paths: {input_paths}")

    try:
        # First, get the list of files using list_only=True
        file_list_str = read_context(
            target_paths_str=effective_target_paths,
            project_root_str=project_root,
            override_rules=override_rules_list,
            list_only=True, # Use list_only=True to get the file paths
            size_limit_mb=size_limit_mb,
            debug_explain=debug_explain,
            include_size_in_list=False, # We don't need size here
            exclusion_parser=exclusion_parser # Add exclusion parser support
        )

        file_paths_relative = [line.strip() for line in file_list_str.splitlines() if line.strip()]

        if not file_paths_relative:
            print("No files found matching the criteria.", file=sys.stderr)
            return

        # Determine the absolute project root path for resolving relative paths
        if project_root:
            abs_project_root = Path(project_root).resolve()
        else:
            # Infer root if not provided (similar logic to core_logic)
            abs_target_paths = [Path(p).resolve() for p in effective_target_paths]
            try:
                common_ancestor = Path(os.path.commonpath([str(p) for p in abs_target_paths]))
                abs_project_root = common_ancestor if common_ancestor.is_dir() else common_ancestor.parent
            except ValueError:
                abs_project_root = Path.cwd().resolve()
            logger.debug(f"Inferred absolute project root for token counting: {abs_project_root}")


        # Initialize tiktoken encoder
        try:
            # Using cl100k_base as it's common for gpt-4 and related models
            enc = tiktoken.get_encoding("cl100k_base")
        except Exception as e:
            logger.info(
                "tiktoken unavailable, using naive token count: %s", e
            )
            enc = None

        total_tokens = 0
        output_lines = []

        for rel_path_str in file_paths_relative:
            abs_file_path = abs_project_root / rel_path_str
            if not abs_file_path.is_file():
                logger.warning(f"Skipping non-file path from list: {rel_path_str}")
                continue

            try:
                # Read file content - try common encodings
                content_bytes = abs_file_path.read_bytes()
                content_str: Optional[str] = None
                encodings_to_try = ['utf-8', 'latin-1', 'cp1252']
                for enc_name in encodings_to_try:
                    try:
                        content_str = content_bytes.decode(enc_name)
                        logger.debug(f"Decoded {rel_path_str} using {enc_name}")
                        break
                    except UnicodeDecodeError:
                        continue

                if content_str is None:
                    logger.warning(f"Could not decode {rel_path_str} with tried encodings. Skipping token count.")
                    output_lines.append(f"{rel_path_str}: Error decoding")
                    continue

                # Count tokens (fallback to word count if tiktoken unavailable)
                num_tokens = (
                    len(enc.encode(content_str)) if enc else len(content_str.split())
                )
                total_tokens += num_tokens
                output_lines.append(f"{rel_path_str}: {num_tokens} tokens")

            except OSError as e:
                logger.warning(f"Error reading file {rel_path_str} for token counting: {e}")
                output_lines.append(f"{rel_path_str}: Error reading")
            except Exception as e:
                logger.error(f"Unexpected error processing file {rel_path_str} for token counting: {e}", exc_info=debug_explain)
                output_lines.append(f"{rel_path_str}: Error processing")

        # Print results
        for line in output_lines:
            print(line)
        print("---")
        print(f"Total: {total_tokens} tokens")

    except Exception as e:
        # Catch errors from the initial read_context call or path handling
        print(f"An error occurred during the list-token process: {e}", file=sys.stderr)
        if debug_explain:
             import traceback
             logger.error("Traceback:", exc_info=True)
        sys.exit(1)

def handle_read_command(args):
    """Handles the context reading logic."""
    logger.debug("Executing context read logic.")
    # --- Translate WSL Paths First ---
    # Translate input paths *before* any Path object creation or validation
    translated_input_paths = [_translate_wsl_path(p) for p in args.paths]
    translated_project_root = _translate_wsl_path(args.project_root) if args.project_root else None
    translated_overrides_file = _translate_wsl_path(args.overrides) if args.overrides else None # Translate overrides path
    logger.debug(f"Original input paths: {args.paths} -> Translated: {translated_input_paths}")
    if args.project_root:
        logger.debug(f"Original project root: {args.project_root} -> Translated: {translated_project_root}")
    if args.overrides:
        logger.debug(f"Original overrides file: {args.overrides} -> Translated: {translated_overrides_file}")

    # Defensive NUL check on all incoming paths
    if translated_project_root:
        ensure_no_nul(translated_project_root, "project_root")
    for p in translated_input_paths:
        ensure_no_nul(p, "input path")

    # --- Use Translated Paths for Input Validation ---
    input_paths = translated_input_paths # Use translated paths from now on
    output_file = args.output
    list_only = args.list_only
    overrides_file = translated_overrides_file # Use translated overrides path
    size_limit_mb = args.size_limit_mb
    debug_explain = args.debug_explain
    project_root = translated_project_root # Use translated root from now on
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
            logger.info(f"Loaded {len(override_rules_list)} override rules from {overrides_file}.")
        except Exception as e:
            print(f"Error reading overrides file '{overrides_file}': {e}", file=sys.stderr)
            sys.exit(1)

    # --- Process Exclusion Arguments ---
    keep_only_modules = None
    if args.keep_only:
        keep_only_modules = [m.strip() for m in args.keep_only.split(',') if m.strip()]
    
    exclusion_patterns, exclusion_parser = create_exclusion_patterns(
        not_keywords=args.not_keywords,
        not_in_scoped=args.not_in_scoped,
        not_files=args.not_files,
        keep_only_modules=keep_only_modules
    )
    
    # If we have any exclusions (including scoped ones), we need to use override mode
    if exclusion_patterns or exclusion_parser:
        if override_rules_list is None:
            # When using exclusions without an override file, start with empty list
            # The walker will apply defaults, gitignore, and contextfiles first
            override_rules_list = []
        if exclusion_patterns:
            override_rules_list.extend(exclusion_patterns)
            logger.info(f"Added {len(exclusion_patterns)} exclusion patterns from CLI flags")
            for pattern in exclusion_patterns:
                logger.debug(f"Exclusion pattern: {pattern}")

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
            include_size_in_list=args.size, # Pass the CLI arg value
            exclusion_parser=exclusion_parser # Add exclusion parser support
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
                    # Log as debug, as clipboard failure is usually non-critical and only relevant for debugging
                    logger.debug(f"Failed to copy output to clipboard: {e}")


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
    # --- Mutually Exclusive Group for Listing Options ---
    list_group = parser.add_mutually_exclusive_group()
    list_group.add_argument(
        "-l",
        "--list-only",
        action="store_true",
        help="Only list file paths found, do not include content."
    )
    list_group.add_argument(
        "-L",
        "--list-token",
        action="store_true",
        help="List file paths with token counts (using tiktoken cl100k_base) and a total sum."
    )
    # --- End Mutually Exclusive Group ---
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
    # --- Exclusion Arguments ---
    parser.add_argument(
        "--not",
        dest="not_keywords",
        action="append",
        metavar="<keyword>",
        help="Exclude modules/directories matching keyword (e.g., --not tests --not vendor). Can be used multiple times."
    )
    parser.add_argument(
        "--not-in", 
        dest="not_in_scoped",
        action="append",
        metavar="<path:keywords>",
        help="Exclude specific keywords within a path (e.g., --not-in src/legacy:old,deprecated). Can be used multiple times."
    )
    parser.add_argument(
        "--not-files",
        dest="not_files",
        action="append", 
        metavar="<pattern>",
        help="Exclude files matching pattern (e.g., --not-files '*.test.js' --not-files '*_old.*'). Can be used multiple times."
    )
    parser.add_argument(
        "--keep-only",
        metavar="<modules>",
        help="Keep only specified modules/directories, exclude everything else (comma-separated, e.g., --keep-only src,lib,docs)"
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
    elif args.list_token:
        # Handle the new list-token command
        handle_list_token_command(args)
    else:
        # Otherwise, proceed with reading context
        handle_read_command(args)

if __name__ == "__main__":
    main()
# Removed duplicated code block from previous failed diff