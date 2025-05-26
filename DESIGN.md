# Jinni Project - Detailed Design

This document outlines the detailed design for the components of the Jinni project, expanding on the high-level plan in `PLAN.md`.

## 1. Introduction

This document details the internal design of the `jinni` MCP Server, `jinni` CLI, Core Logic Module, and Configuration System.

## 2. Core Logic Module Design

*(Based on `dev-reference/prototype.py` and `PLAN.md`)*

*   **File Discovery:**
    *   Utilizes `os.walk(topdown=True)` for recursive traversal starting from one or more target paths provided by the user.
    *   Symbolic links encountered during traversal will be **skipped**.
   *   **Filtering (Dynamic Rule Application):**
       *   Determines the `walk_target_path` (explicit target directory or project root). This path serves as the root for rule discovery and path matching.
       *   Determines the `output_rel_root` (explicit project root or common ancestor) for final output path relativity.
       *   For each directory visited during `os.walk` starting from `walk_target_path`:
           *   If overrides are active (CLI `--overrides` or MCP `rules`): Uses a pre-compiled `PathSpec` based exclusively on the provided override rules. Path matching is relative to `walk_target_path`.
           *   If no overrides: Finds relevant `.contextfiles` from `walk_target_path` down to the current directory, loads rules, combines with defaults, and compiles a `PathSpec` specific to that directory's context. Path matching is relative to `walk_target_path`.
       *   Applies the active `PathSpec` to filter files and prune subdirectories.
       *   **Explicit Target Inclusion:** Explicitly provided file targets bypass rule checks (but not binary/size checks). Explicitly provided directory targets become the `walk_target_path` (root for rule discovery/matching).
       *   Handles `list_only` flag.
*   **File Reading:**
    *   Attempts multiple encodings (UTF-8, Latin-1, CP1252).
    *   Handles file read errors gracefully (permissions, non-existent files).
*   **Output Formatting:**
    *   Concatenates file content.
    *   Prepends a path header (e.g., ````path=src/app.py`) for each file unless `list_only` is true. Content is enclosed in triple backticks.
    *   When not `list_only`, file entries are separated by a blank line.
*   **Large Context Handling:**
    *   Implement a configurable total content size limit (default: 100MB, configurable via `JINNI_MAX_SIZE_MB` env var). Accumulate file sizes during traversal. If the limit is exceeded, **abort** processing and return/print an explanatory error message (e.g., "Error: Total content size exceeds limit of 100MB").

## 3. Configuration System (`.contextfiles` & Overrides) Design

*   **Core Principle:** Files and directories are filtered based on `.gitignore`-style rules. Files are included by default, but filtered by built-in defaults and custom rules. The effective rules are determined dynamically during traversal.
*   **Implementation Library:** `pathspec` (using `'gitwildmatch'` syntax).
*   **File Format:**
    *   Plain text file named `.contextfiles`.
    *   One pattern per line.
    *   Encoding: UTF-8.
*   **Rule Syntax (`gitwildmatch`):**
    *   Follows standard `.gitignore` syntax rules. See `pathspec` documentation and `.gitignore` documentation for full details.
    *   Lines starting with `#` are comments.
    *   Empty lines or lines with only whitespace are ignored.
    *   Patterns specify files/directories to match. By default, matching an item includes it, unless the pattern starts with `!`.
    *   Patterns starting with `!` denote an **exclusion** rule (these files/dirs should be skipped, even if matched by an inclusion pattern).
    *   Patterns are matched against the path relative to the **target directory** being processed (or the project root if no specific target is given).
    *   A leading `/` anchors the pattern to the directory containing the `.contextfiles`.
    *   A trailing `/` indicates the pattern applies only to directories.
    *   `**` matches zero or more directories (recursive wildcard).
    *   Example `.contextfiles` (Inclusion-focused):
        ```
        # Include all Python files in the src directory and subdirectories
        src/**/*.py

        # Include all Markdown files anywhere
        *.md

        # Exclude temporary files anywhere, even if they are .py or .md
        !*.tmp

        # Include the specific config file at the root of this context
        /config.yaml

        # Exclude the entire build directory relative to this file
        build/
        ```
*   **Rule Loading & Compilation (`config_system.py`):**
    *   Provides helper functions:
        *   `load_rules_from_file(path)`: Reads lines from a `.contextfile` or override file.
        *   `compile_spec_from_rules(rules_list)`: Compiles a list of rule strings into a `pathspec.PathSpec` object.
    *   Defines `DEFAULT_RULES` (common excludes like `.git/`, `node_modules/`, etc.).
*   **Rule Application Logic (`context_walker.py`):**
    1.  **Determine Target Root:** The `walk_target_path` (explicit target directory or project root) is established as the root for rule discovery and path matching.
    2.  **Override Check:** Determines if override rules are provided (CLI `--overrides <file>` or MCP `rules` argument).
    3.  **Dynamic Spec Generation (During `os.walk`):** For each directory visited:
        *   Finds all `.contextfiles` and `.gitignore` files starting from `walk_target_path` down to the current directory.
        *   Loads rules from these files.
        *   Combines rules in order:
            *   `DEFAULT_RULES` (common excludes like `.git/`, `node_modules/`, etc.)
            *   `.gitignore` rules (converted to Jinni-style patterns)
            *   `.contextfiles` rules (respecting order: target root rules first, current dir rules last)
            *   **If overrides are provided:** Override rules are added as high-priority rules at the end
        *   Compiles a new `PathSpec` object specific to this directory's context.
    4.  **Filtering Decision:**
        *   The active `PathSpec` for the current directory is used to match files and subdirectories.
        *   The path used for matching is calculated **relative to `walk_target_path`**.
        *   Standard `pathspec` matching applies (last matching pattern wins, `!` negates). If no user-defined pattern matches, the item is included unless it matches a built-in default exclusion. If no pattern matches at all, it's included.
    5.  **Explicit Target Inclusion:** Explicitly provided file targets bypass rule checks (but not binary/size checks). Explicitly provided directory targets become the `walk_target_path`.
    6.  **Directory Pruning:** During `os.walk` (`topdown=True`), subdirectories are checked against the active `PathSpec` (using the path relative to `walk_target_path`). If a subdirectory doesn't match (is excluded) and wasn't an explicit target, it's removed from `dirnames` to prevent traversal.
    7.  **Output Path Relativity:** Final output paths (in headers or list mode) are always calculated relative to the original `output_rel_root` determined in `core_logic.py`.

## 4. `jinni` MCP Server Design

*   **Server Name:** `jinni` (Update from `codedump` in `prototype.py`).
*   **Transport:** Stdio.
*   **Library:** `mcp.server.fastmcp`.
*   **Tool: `read_context`**
    *   **Description:** Generates a concatenated view of relevant code files from a specified directory, applying filtering rules from defaults, `.contextfiles`, and optional inline rules.
    *   **Input Schema:**
        *   `project_root` (string, required): The absolute path to the project root directory. Rule discovery and output paths are relative to this root.
        *   `targets` (JSON array of strings, **required**): Specifies the file(s)/director(y/ies) within `project_root` to process. Must be a JSON array of string paths (e.g., `["path/to/file1", "path/to/dir2"]`). Paths can be absolute or relative to CWD. If an empty list `[]` is provided, the entire `project_root` is processed. All target paths must resolve to locations inside `project_root`.
        *   `rules` (JSON array of strings, **required**): A list of inline filtering rules (using `.gitignore`-style syntax, e.g., `["src/**/*.py", "!*.tmp"]`). Provide an empty list `[]` if no specific rules are needed (uses built-in defaults). If non-empty, these rules are used exclusively, ignoring built-in defaults and `.contextfiles`.
        *   `list_only` (boolean, optional, default: false): Only list file paths.
        *   `size_limit_mb` (integer, optional): Override context size limit.
        *   `debug_explain` (boolean, optional, default: false): Enable debug logging on server stderr.
    *   **Output:** String containing concatenated content or file list.
    *   **Error Handling:** Returns standard MCP errors for invalid input or internal failures.
*   **Capabilities:** Reports `tools` capability.

## 5. `jinni` CLI Design

*   **Command:** `jinni`
*   **Arguments:**
    *   `paths` (optional, positional, zero or more): Target directory or file paths to process. Defaults to `['.']` if none provided.
    *   `--root <DIR>` / `-r <DIR>` (optional): Specify the project root directory. This primarily affects the base for calculating relative output paths. If omitted, the root is inferred from the common ancestor of the `<PATH...>` arguments. Rule discovery and matching are relative to the target path(s).
    *   `--output <file>` / `-o <file>` (optional): Write output to a file instead of stdout.
    *   `--list-only` / `-l` (optional): Only list file paths found.
    *   `--overrides <file>` (optional): Specify an overrides file. If provided, rules from this file are used exclusively, ignoring built-in defaults and all `.contextfiles`.
    *   `--size-limit-mb <int>` / `-s <int>` (optional): Override context size limit.
    *   `--debug-explain` (optional): Enable detailed debug logging to stderr and `jinni_debug.log`.
    *   `--no-copy` (optional): Prevent automatically copying output content to the clipboard when printing to stdout (default is to copy).
*   **Output:** Prints concatenated content or file list to stdout or specified output file.
*   **Error Handling:** Prints user-friendly error messages to stderr.

## 6. Data Flow / Interaction

*   Both the `jinni` MCP Server (`read_context` tool) and the `jinni` CLI utilize the `core_logic.read_context` function.
*   The `core_logic.read_context` function handles target validation, determines the `output_rel_root` for output paths, and determines the initial `walk_target_path`(s).
*   It calls `context_walker.walk_and_process` for each target directory.
*   `context_walker.walk_and_process` manages the directory traversal (`os.walk`), determines if overrides are active, discovers `.contextfiles` relative to the `walk_target_path`, compiles the `PathSpec`, and applies it to filter files/directories using paths relative to `walk_target_path`. It calls `file_processor.process_file` for included files.