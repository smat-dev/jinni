# Product Context

This file provides a high-level overview of the project and the expected product that will be created. Initially it is based upon projectBrief.md (if provided) and all other available project-related information in the working directory. This file is intended to be updated as the project evolves, and should be used to inform all other modes of the project's goals and context.
2025-04-02 18:07:24 - Log of updates made will be appended as footnotes to the end of this file.

*

## Project Goal

*   Create a tool (MCP server and CLI utility named "jinni") to help LLMs efficiently read and understand project context by providing a concatenated view of relevant files, overcoming limitations of piecemeal file reading.

## Key Features

*   MCP Server providing a `read_context` tool (previously `dump_code`).
*   `jinni` command-line utility for manual context dumping.
*   Hierarchical, `.gitignore`-style filtering using `.contextfiles` and the `pathspec` library (`gitwildmatch` syntax). Files are included by default, but common patterns (like `.git/`, `node_modules/`, dotfiles) are excluded by built-in rules unless explicitly included by user rules.
*   Exclusion patterns (`!`) override inclusion patterns.
*   Ability to list files only (`list_only` parameter).
*   Handles large context sizes: Aborts with a `DetailedContextSizeError` if >100MB (configurable), providing a list of the 10 largest files to aid exclusion configuration.
*   Skips common build artifacts, logs, VCS folders, binaries.
*   Includes file metadata (path, size, modification time) in output (unless `list_only`).
*   Handles different text encodings.
*   Provides a `jinni usage` CLI command and `usage` MCP tool to display the README content.
*   Mandatory `project_root` argument (CLI: `-r`/`--root`, MCP: `project_root`) defines the scope for context processing and relative paths.
*   Mandatory `targets` argument (CLI: `<TARGET...>`, MCP: `targets`) specifies a list of file(s)/director(y/ies) within the `project_root` to focus on. The MCP `targets` parameter accepts a JSON array of string paths (e.g., `["path/to/file1", "path/to/dir2"]`). If empty (`[]`), the entire `project_root` is processed. The MCP `rules` parameter is also **mandatory** and expects a JSON array of strings (provide `[]` if no specific rules are needed).

## Overall Architecture

*   Python-based MCP server using the `mcp.server.fastmcp` library.
*   Communicates via stdio transport.
*   Core logic involves traversing directory trees (`os.walk`) starting from the `project_root` or the specified `targets` within it. Dynamically determines the applicable rule set (`pathspec`) for each directory based on `.contextfiles` encountered from the `project_root` down, combined with built-in defaults. If overrides are active (CLI `--overrides` or MCP `rules`), these are used exclusively, ignoring defaults and `.contextfiles`. Applies these rules for filtering. Uses `pathlib`.
*   Includes a separate CLI component (`jinni`) with override behavior (`--overrides` flag) that mirrors MCP server override behavior.

---
*Footnotes:*
[2025-04-02 18:13:08] - Updated Project Goal, Key Features, and Overall Architecture based on README.md and prototype.py analysis after initial codedump.
[2025-04-03 17:21:00] - Updated Key Features and Overall Architecture to reflect the major redesign of the configuration system to use `.gitignore`-style inclusion logic via `pathspec`.
[2025-04-04 12:32:00] - Updated Overall Architecture to reflect the re-design of rule building (unified set per target) and unified override handling for CLI/MCP.
[2025-04-04 13:04:00] - Further updated Overall Architecture to reflect dynamic rule compilation during traversal based on `.contextfiles` hierarchy, and the explicit inclusion of target paths.
[2025-04-04 22:35:21] - Updated Key Features to include the `jinni doc` command/tool (now `jinni usage`/`usage`) and the enhanced context size error reporting (`DetailedContextSizeError` with largest files list).
[2025-04-05 12:55:00] - Updated Key Features and Overall Architecture to reflect the change to a mandatory `project_root` and optional `target` argument structure.
[2025-04-05 12:43:00] - Updated Key Features and Overall Architecture to reflect the exclusive nature of override rules and the enhancement of the MCP `read_context` tool's `target` parameter to accept a JSON array of strings.
[2025-04-05 13:44:00] - Updated Key Features to include the new optional `target` parameter in the MCP `read_context` tool for specifying a single target path.
[2025-04-05 15:50:00] - Updated Key Features to remove the optional `target` parameter and make the `targets` parameter mandatory for the MCP `read_context` tool. (Superseded)
[2025-04-05 18:06:00] - Updated Key Features to clarify that providing an empty list `[]` for the mandatory `targets` MCP parameter defaults to processing the entire `project_root`. (Superseded by making targets optional)
[2025-04-05 22:23:00] - Reverted Key Features description for MCP `targets` parameter to be optional, defaulting to project root if omitted or empty.
[2025-04-05 22:45:00] - Reverted Key Features: MCP `read_context` tool parameter `targets` is mandatory but allows an empty list (`[]`) to process the entire project root. `rules` remains mandatory (allow `[]`).
[2025-04-05 23:09:00] - Updated Key Features: Renamed `jinni doc`/`jinni_doc` to `jinni usage`/`usage`.