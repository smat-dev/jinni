# Jinni Project - Detailed Design

This document outlines the detailed design for the components of the Jinni project, expanding on the high-level plan in `PLAN.md`.

## 1. Introduction

This document details the internal design of the `jinni` MCP Server, `jinni` CLI, Core Logic Module, and Configuration System.

## 2. Core Logic Module Design

*(Based on `dev-reference/prototype.py` and `PLAN.md`)*

*   **File Discovery:**
    *   Utilizes `os.walk` for recursive traversal starting from a single root path.
    *   Symbolic links encountered during traversal will be **skipped** by default to prevent loops and unexpected directory traversal. `os.walk(followlinks=False)`.
*   **Filtering:**
    *   Applies default exclusion rules (VCS, build artifacts, logs, etc. - see `prototype.py`).
    *   Integrates with Configuration System to apply rules from `.contextfiles` and potential inline rules provided via MCP tool arguments.
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

## 3. Configuration System (`.contextfiles`) Design

*   **File Format:**
    *   Simple text file named `.contextfiles`.
    *   One rule per line.
    *   Encoding: UTF-8.
*   **Rule Syntax:**
    *   Lines starting with `#` are ignored (comments).
    *   Empty lines or lines containing only whitespace are ignored.
    *   Lines starting with `!` denote an **exclusion** rule (files/dirs matching the pattern should be skipped).
    *   All other non-comment, non-empty lines denote an **inclusion** rule (files/dirs matching the pattern should be included, potentially overriding broader exclusion rules or defaults).
    *   The pattern itself is a [glob pattern](https://docs.python.org/3/library/fnmatch.html) (e.g., `*.log`, `__pycache__/`, `docs/*.md`).
    *   Patterns are matched against the **relative path** from the directory containing the `.contextfiles`.
    *   Patterns ending with `/` apply only to directories.
    *   Example `.contextfiles`:
        ```
        # Ignore all log files
        !*.log

        # But specifically include important_service.log
        important_service.log

        # Exclude all test directories
        !tests/

        # Include all markdown files in docs
        docs/*.md
        ```
*   **Parsing Logic:**
    *   Read the file line by line.
    *   Skip lines matching comment/empty criteria.
    *   Check for `!` prefix to determine rule type (include/exclude).
    *   Store the rule type and the glob pattern.
*   **Rule Hierarchy & Application:**
    1.  **Initialization:** Start with rules provided inline via MCP tool arguments (if any). These have the highest precedence. If no inline rules, start empty.
    2.  **Global Config:** Apply rules from a global config file if specified via CLI (`--config`). These have precedence over defaults but below inline rules.
    3.  **Defaults:** Apply the hardcoded default exclusion rules (like in `prototype.py`). These have lower precedence than inline and global rules. No default inclusion rules.
    4.  **Traversal & `.contextfiles`:** During `os.walk`, before processing files/directories in a specific directory `D`:
        a. Check if a `.contextfiles` exists in `D`.
        b. If yes, parse its rules. These rules apply locally and recursively *unless overridden by rules in deeper subdirectories*. They have precedence over default, global, and parent `.contextfiles` rules, but lower precedence than inline rules.
        c. Store the rules associated with the directory level `D`.
    3.  **Filtering Decision (for an item `I` in directory `D`):**
        a. Check rules from inline arguments (highest precedence). If a match: apply rule (skip if `!`, include otherwise) and stop.
        b. Check rules from `D`'s `.contextfiles`. If a match: apply rule and stop.
        c. Check rules from parent directories' `.contextfiles` upwards. If a match: apply rule and stop.
        d. Check rules from global config file (if provided via CLI). If a match: apply rule and stop.
        e. Check default exclusion rules. If a match: **skip** `I` and stop.
        f. If no rules matched, **include** `I`.
    5.  **Precedence Summary (Highest to Lowest):** Inline Rules -> Subdirectory `.contextfiles` -> Parent Directory `.contextfiles` -> Global Config (`--config`) -> Default Exclusions. Within the same rule source, `!` exclusions override inclusions.

## 4. `jinni` MCP Server Design

*   **Server Name:** `jinni` (Update from `codedump` in `prototype.py`).
*   **Transport:** Stdio.
*   **Library:** `mcp.server.fastmcp`.
*   **Tool: `read_context`**
    *   **Description:** Generates a concatenated view of relevant code files from a specified directory, applying filtering rules from defaults, `.contextfiles`, and optional inline rules.
    *   **Input Schema:**
        *   `path` (string, required): Absolute path to the directory to process.
        *   `rules` (array of strings, optional): List of inline filtering rules (using `.contextfiles` syntax, e.g., `["!*.log", "src/"]`) that override file-based rules.
        *   `list_only` (boolean, optional, default: false): Only list file paths.
    *   **Output:** String containing concatenated content or file list.
    *   **Error Handling:** Returns standard MCP errors for invalid input or internal failures.
*   **Capabilities:** Reports `tools` capability.

## 5. `jinni` CLI Design

*   **Command:** `jinni`
*   **Arguments:**
    *   `<path>` (required): Target directory path.
    *   `--output <file>` (optional): Write output to a file instead of stdout.
    *   `--list-only` (optional): Only list file paths found.
    *   `--config <file>` (optional): Specify a global config file (using `.contextfiles` format). Rules from this file are applied *before* default rules. `.contextfiles` found during traversal override both global and default rules per the hierarchy in Section 3.
*   **Output:** Prints concatenated content or file list to stdout or specified output file.
*   **Error Handling:** Prints user-friendly error messages to stderr.

## 6. Data Flow / Interaction

*   Both the `jinni` MCP Server (when `read_context` is called with a path and optional inline rules) and the `jinni` CLI utilize the Core Logic Module.
*   The Core Logic Module interacts with the File System (traversing the specified path) and uses the Configuration System (processing inline rules, global config, and `.contextfiles`) to determine which files to process.