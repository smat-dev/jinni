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
       *   Determines a `rule_discovery_root` (common ancestor of targets or CWD).
       *   For each directory visited during `os.walk`:
           *   If overrides are active (CLI `--overrides` or MCP `rules`): Uses a pre-compiled `PathSpec` based exclusively on the provided override rules (built-in defaults and `.contextfiles` are ignored).
           *   If no overrides: Finds relevant `.contextfiles` from `rule_discovery_root` down to the current directory, loads rules, combines with defaults, and compiles a `PathSpec` specific to that directory's context.
       *   Applies the active `PathSpec` to filter files and prune subdirectories.
       *   **Explicit Target Inclusion:** Explicitly provided file targets are always processed (subject to binary/size checks), bypassing rule checks. Explicitly provided directory targets ensure traversal starts within them, but files/subdirectories found during the walk are still subject to rule checks relative to the rule discovery root.
       *   Handles `list_only` flag.
*   **File Reading:**
    *   Attempts multiple encodings (UTF-8, Latin-1, CP1252).
    *   Handles file read errors gracefully (permissions, non-existent files).
*   **Output Formatting:**
    *   Concatenates file content.
    *   Prepends metadata headers (path, size, modified time) unless `list_only` is true.
    *   Uses consistent separators (`========`).
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
    *   Patterns are matched against the path relative to the directory containing the `.contextfiles`.
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
*   **Rule Application Logic (`core_logic.py`):**
    1.  **Override Check:** Determines if override rules are provided (CLI `--overrides <file>` or MCP `rules` argument).
    2.  **Dynamic Spec Generation (During `os.walk`):**
        *   **If Overrides Active:** Uses a single `PathSpec` compiled exclusively from the provided `override_rules` for the entire traversal. All `.contextfiles` and built-in default rules are ignored.
        *   **If No Overrides:** For each directory visited:
            *   Finds all `.contextfiles` from the `rule_discovery_root` down to the current directory.
            *   Loads rules from these files.
            *   Combines rules: `DEFAULT_RULES + rules_from_all_found_contextfiles` (respecting order: root rules first, current dir rules last).
            *   Compiles a new `PathSpec` object specific to this directory's context.
    3.  **Filtering Decision:**
        *   The active `PathSpec` for the current directory is used to match files and subdirectories (relative to the `rule_discovery_root`).
        *   Standard `pathspec` matching applies (last matching pattern wins, `!` negates). If no user-defined pattern matches, the item is included unless it matches a built-in default exclusion. If no pattern matches at all, it's included.
    4.  **Explicit Target Inclusion:** Explicitly provided file targets bypass rule checks (but not binary/size checks). Explicitly provided directory targets ensure traversal starts there, with rules still applying to items found within during the walk relative to the rule discovery root.
    5.  **Directory Pruning:** During `os.walk` (`topdown=True`), subdirectories are checked against the active `PathSpec`. If a subdirectory doesn't match (is excluded) and wasn't an explicit target, it's removed from `dirnames` to prevent traversal.

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
    *   `--root <DIR>` / `-r <DIR>` (optional): Specify the project root directory. Rule discovery starts here, and output paths are relative to this directory. If omitted, the root is inferred from the common ancestor of the `paths` arguments.
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
*   The `core_logic.read_context` function handles target validation, determines the appropriate relative root for output, manages the directory traversal (`os.walk`), and interacts with the `config_system` module.
*   During traversal, `core_logic` determines if overrides are active. If not, it finds relevant `.contextfiles` for the current directory. It calls `config_system.load_rules_from_file` and `config_system.compile_spec_from_rules` to get the active `PathSpec` for filtering. It applies this spec, respecting explicit targets, to filter files and prune directories.