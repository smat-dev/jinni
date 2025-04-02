# Product Context

This file provides a high-level overview of the project and the expected product that will be created. Initially it is based upon projectBrief.md (if provided) and all other available project-related information in the working directory. This file is intended to be updated as the project evolves, and should be used to inform all other modes of the project's goals and context.
2025-04-02 18:07:24 - Log of updates made will be appended as footnotes to the end of this file.

*

## Project Goal

*   Create a tool (MCP server and CLI utility named "jinni") to help LLMs efficiently read and understand project context by providing a concatenated view of relevant files, overcoming limitations of piecemeal file reading.

## Key Features

*   MCP Server providing a `dump_code` tool.
*   `jinni` command-line utility for manual context dumping.
*   Hierarchical whitelisting/blacklisting of files/directories using `.contextfiles` and regex.
*   Sensible default exclusions for common development artifacts.
*   Ability to list files only (`list_only` parameter).
*   Handles large context sizes (mentions aborting if >100MB).
*   Skips common build artifacts, logs, VCS folders, binaries.
*   Includes file metadata (path, size, modification time) in output (unless `list_only`).
*   Handles different text encodings.

## Overall Architecture

*   Python-based MCP server using the `mcp.server.fastmcp` library.
*   Communicates via stdio transport.
*   Core logic involves walking directory trees (`os.walk`), filtering files/directories based on rules (`should_skip`), reading file content, and formatting output.
*   Includes a separate CLI component (`jinni`).

---
*Footnotes:*
[2025-04-02 18:13:08] - Updated Project Goal, Key Features, and Overall Architecture based on README.md and prototype.py analysis after initial codedump.