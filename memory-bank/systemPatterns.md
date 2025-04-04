# System Patterns *Optional*

This file documents recurring patterns and standards used in the project.
It is optional, but recommended to be updated as the project evolves.
2025-04-02 18:07:49 - Log of updates made.

*

## Coding Patterns

*   [2025-04-04 22:35:39] - **Detailed Error Reporting via Custom Exception:** For specific, actionable errors like exceeding the context size limit, a custom exception class (`DetailedContextSizeError`) is used. This exception carries additional diagnostic information (e.g., a list of the largest files) directly, allowing the caller (CLI or MCP server) to present more helpful error messages to the user without needing complex logic outside the core function.

## Architectural Patterns

*   [2025-04-03 17:24:00] - **Path Specification (`pathspec` library):** The `pathspec` library (using `gitwildmatch` syntax) is used for parsing and matching file paths against `.gitignore`-style patterns defined in `.contextfiles`, global configs, and inline rules. This provides a robust and standard way to handle hierarchical file filtering, where files are included by default but can be excluded by built-in or custom rules.

## Testing Patterns

*