# System Patterns *Optional*

This file documents recurring patterns and standards used in the project.
It is optional, but recommended to be updated as the project evolves.
2025-04-02 18:07:49 - Log of updates made.

*

## Coding Patterns

*   

## Architectural Patterns

*   [2025-04-03 17:24:00] - **Path Specification (`pathspec` library):** The `pathspec` library (using `gitwildmatch` syntax) is used for parsing and matching file paths against `.gitignore`-style patterns defined in `.contextfiles`, global configs, and inline rules. This provides a robust and standard way to handle hierarchical file filtering, where files are included by default but can be excluded by built-in or custom rules.

## Testing Patterns

*