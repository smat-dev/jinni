# jinni/cli.py
import argparse
import sys
import os
from pathlib import Path
from typing import List, Optional

# Ensure jinni package is importable if running script directly
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jinni.core_logic import process_directory, ContextSizeExceededError
from jinni.config_system import parse_rules, Ruleset # Needed for parsing global config

def main():
    parser = argparse.ArgumentParser(
        description="Jinni: Process and concatenate context from a directory based on rules."
    )
    parser.add_argument(
        "path",
        help="Absolute path to the target directory to process."
    )
    parser.add_argument(
        "--output",
        "-o",
        metavar="<file>",
        help="Write output to a file instead of stdout."
    )
    parser.add_argument(
        "--list-only",
        action="store_true",
        help="Only list file paths found, do not include content."
    )
    parser.add_argument(
        "--config",
        metavar="<file>",
        help="Specify a global config file (using .contextfiles format). Applied before defaults."
    )
    # Add argument for size limit override? DESIGN.md mentions env var, maybe CLI flag too?
    # For now, stick to DESIGN.md spec.

    args = parser.parse_args()

    # --- Input Validation ---
    root_path_str = args.path
    if not os.path.isabs(root_path_str):
        print(f"Error: Path must be absolute: {root_path_str}", file=sys.stderr)
        sys.exit(1)

    root_path = Path(root_path_str)
    if not root_path.is_dir():
        print(f"Error: Path is not a valid directory: {root_path_str}", file=sys.stderr)
        sys.exit(1)

    # --- Load Global Config ---
    global_rules: Optional[Ruleset] = None
    global_rules_str_list: Optional[List[str]] = None # For passing to core_logic
    if args.config:
        config_path = Path(args.config)
        if not config_path.is_file():
            print(f"Error: Global config file not found: {args.config}", file=sys.stderr)
            sys.exit(1)
        try:
            config_content = config_path.read_text(encoding='utf-8')
            # Store as list of strings for core_logic compatibility for now
            global_rules_str_list = config_content.splitlines()
            # We could parse here too, but core_logic expects strings currently
            # global_rules = parse_rules(config_content)
        except Exception as e:
            print(f"Error reading or parsing global config file {args.config}: {e}", file=sys.stderr)
            sys.exit(1)

    # --- Call Core Logic ---
    try:
        result_content = process_directory(
            root_path_str=str(root_path), # Pass resolved absolute path string
            list_only=args.list_only,
            inline_rules_str=None, # CLI doesn't support inline rules per DESIGN.md
            global_rules_str=global_rules_str_list,
            size_limit_mb=None # Use default/env var
        )

        # --- Output ---
        if args.output:
            try:
                output_path = Path(args.output)
                output_path.parent.mkdir(parents=True, exist_ok=True) # Ensure dir exists
                output_path.write_text(result_content, encoding='utf-8')
                print(f"Output successfully written to {args.output}", file=sys.stderr)
            except Exception as e:
                print(f"Error writing output to file {args.output}: {e}", file=sys.stderr)
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
        print(f"Error: {e}", file=sys.stderr)
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