# Product Context

This file provides a high-level overview of the project and the expected product that will be created. Initially it is based upon projectBrief.md (if provided) and all other available project-related information in the working directory. This file is intended to be updated as the project evolves, and should be used to inform all other modes of the project's goals and context.
2025-04-02 18:07:24 - Log of updates made will be appended as footnotes to the end of this file.

*

## Project Goal

*   Create a tool (MCP server and CLI utility named "jinni") to help LLMs efficiently read and understand project context by providing a concatenated view of relevant files, overcoming limitations of piecemeal file reading.

## Key Features

*   MCP Server providing a `dump_code` tool.
*   `jinni` command-line utility for manual context dumping.
*   Hierarchical, `.gitignore`-style filtering using `.contextfiles` and the `pathspec` library (`gitwildmatch` syntax). Files are included by default, but common patterns (like `.git/`, `node_modules/`, dotfiles) are excluded by built-in rules unless explicitly included by user rules.
*   Exclusion patterns (`!`) override inclusion patterns.
*   Ability to list files only (`list_only` parameter).
*   Handles large context sizes (mentions aborting if >100MB).
*   Skips common build artifacts, logs, VCS folders, binaries.
*   Includes file metadata (path, size, modification time) in output (unless `list_only`).
*   Handles different text encodings.

## Overall Architecture

*   Python-based MCP server using the `mcp.server.fastmcp` library.
*   Communicates via stdio transport.
*   Core logic involves traversing directory trees (`os.walk`), dynamically determining the applicable rule set (`pathspec`) for each directory based on `.contextfiles` encountered from the root down (unless overrides are active), and applying these rules for filtering. Explicitly specified targets are always included. Uses `pathlib`.
*   Includes a separate CLI component (`jinni`) with override behavior (`--overrides` flag) that mirrors MCP server override behavior.

---
*Footnotes:*
[2025-04-02 18:13:08] - Updated Project Goal, Key Features, and Overall Architecture based on README.md and prototype.py analysis after initial codedump.
[2025-04-03 17:21:00] - Updated Key Features and Overall Architecture to reflect the major redesign of the configuration system to use `.gitignore`-style inclusion logic via `pathspec`.
[2025-04-04 12:32:00] - Updated Overall Architecture to reflect the re-design of rule building (unified set per target) and unified override handling for CLI/MCP.
[2025-04-04 13:04:00] - Further updated Overall Architecture to reflect dynamic rule compilation during traversal based on `.contextfiles` hierarchy, and the explicit inclusion of target paths.