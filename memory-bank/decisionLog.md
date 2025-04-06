# Decision Log

This file records key architectural and implementation decisions.
[2025-04-06 15:55:00] - Log finalized and cleaned per user instruction.

*

## Decisions

*   [2025-04-02 18:29:42] - Adopted the initial project plan for 'jinni'.
*   [2025-04-02 18:36:52] - Initial Design: MCP tool `read_context`, abort on size limit, skip symlinks.
*   [2025-04-03 17:20:00] - Adopted `.gitignore`-style filtering (`pathspec` library), include-by-default logic.
*   [2025-04-04 15:51:00] - Added CLI clipboard copy feature (`--no-copy` opt-out).
*   [2025-04-04 15:55:00] - Made CLI `paths` argument optional, defaulting to `.`.
*   [2025-04-04 19:48:00] - Finalized binary file detection: Multi-stage heuristic (`mimetypes` -> null-byte -> printable ratio).
*   [2025-04-04 20:05:00] - Added CLI option `-S`/`--size` for list output.
*   [2025-04-04 22:36:08] - Implemented enhanced context size error (`DetailedContextSizeError`) reporting the 10 largest files.
*   [2025-04-05 02:13:00] - Refactored `core_logic.py` into smaller modules (`utils`, `exceptions`, `file_processor`, `context_walker`, new `core_logic`) to handle CLI/Server differences. Kept flexible CLI args.
*   [2025-04-05 12:20:00] - Override rules (CLI `--overrides` or MCP `rules`) replace built-in defaults entirely (standard `.gitignore` behavior).
*   [2025-04-05 22:45:00] - Final MCP `read_context` parameters: `project_root` (mandatory string), `targets` (mandatory list, `[]` means root), `rules` (mandatory list, `[]` means defaults). (Note: Previous iterations involving optional `targets` or single `target` param were superseded).
*   [2025-04-05 23:01:00] - Refactored MCP tool signature to use Pydantic `Field` for argument descriptions.
*   [2025-04-05 23:09:00] - Renamed documentation tool/command to `usage`.
*   [2025-04-06 00:47:35] - Migrated project distribution from Node.js (`npm`/`npx`) to Python (`uv`/`uvx`/PyPI).
*   [2025-04-06 01:03:00] - Added `jinni-server` direct executable script entry point in `pyproject.toml`.

## Key Rationale

*   `.gitignore` pattern syntax (`pathspec`) is standard and robust for file filtering.
*   Override rules replacing defaults aligns with user expectations and standard behavior.
*   Refactoring `core_logic.py` allowed supporting different input styles (flexible CLI, stricter MCP) cleanly.
*   Detailed context size errors provide actionable feedback to users.
*   Final MCP parameter structure (`project_root`, `targets`, `rules` all mandatory) provides clarity and consistency, with `[]` allowing default behavior for `targets` and `rules`.
*   Migrating to Python tooling (`uv`/PyPI) simplifies setup and installation.