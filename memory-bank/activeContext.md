# Active Context

  This file tracks the project's current status, including recent changes, current goals, and open questions.
  2025-04-02 18:07:33 - Log of updates made.

*

## Current Focus

*   [2025-04-06 00:48:03] - Current focus is migrating the project distribution from Node.js (`npm`/`npx`) to Python (`uv`/`uvx`/PyPI). This involves removing Node.js artifacts, creating `pyproject.toml`, updating documentation (`README.md`), and updating Memory Bank files.

## Recent Changes

*   [2025-04-02 18:07:54] - Initialized Memory Bank files (productContext.md, activeContext.md, progress.md, decisionLog.md, systemPatterns.md).
*   [2025-04-02 18:13:48] - Updated productContext.md with initial project details based on codedump analysis (README.md, prototype.py).
*   [2025-04-02 18:29:10] - Finalized project plan (see PLAN.md) and updated Memory Bank (decisionLog, progress, activeContext).
*   [2025-04-02 18:36:19] - Refined design details in DESIGN.md (Tool name -> `read_context`, abort on size limit, skip symlinks, global CLI config). Updated PLAN.md and decisionLog.md accordingly.
*   [2025-04-02 18:45:37] - Further refined `read_context` tool design (single path, optional inline rules). Updated DESIGN.md, PLAN.md, README.md, and decisionLog.md.
*   [2025-04-02 18:46:44] - Completed Task 1 (Detailed Design & Documentation). Updated progress.md.
*   [2025-04-02 18:50:49] - Created initial unit test files (`tests/test_config_system.py`, `tests/test_core_logic.py`) with basic parsing, hierarchy, and formatting tests (Task 2).
*   [2025-04-02 18:53:33] - Created initial implementation files (`jinni/config_system.py`, `jinni/core_logic.py`) based on DESIGN.md (Task 3). Updated progress.md.
*   [2025-04-02 18:57:54] - Executed initial unit tests. Result: 2 Errors, 1 Failure. See terminal output for details.
*   [2025-04-02 19:07:54] - Debug mode successfully fixed failing unit tests in `core_logic.py` and `config_system.py`. All 10 tests now pass.
*   [2025-04-02 19:13:08] - Code mode created initial `jinni/server.py` implementing the MCP server based on DESIGN.md (Task 4).
*   [2025-04-02 19:14:20] - Code mode created initial `jinni/cli.py` implementing the command-line interface based on DESIGN.md (Task 5).
*   [2025-04-02 19:29:52] - Completed initial update of README.md (Task 6).
*   [2025-04-02 19:30:16] - Added Task 7: Implement Integration Tests (High Priority) based on user feedback.
*   [2025-04-03 16:27:00] - Approved plan to redesign `core_logic.py` directory traversal logic. Updated `decisionLog.md`.
*   [2025-04-03 17:22:00] - Approved major redesign of `.contextfiles` system (see `decisionLog.md`). Updated `DESIGN.md`, `README.md`, `productContext.md`, and `decisionLog.md`.
*   [2025-04-04 01:24:12] - Changed rule precedence logic based on user feedback: Inline rules now completely override local `.contextfiles`. Updated `config_system.py`, `DESIGN.md`, `README.md`, `decisionLog.md`.
*   [2025-04-04 12:33:00] - Approved major re-architecture of config system and core logic (see `decisionLog.md`). This involves factoring out rule building, using `pathlib`, unifying CLI/MCP override behavior, and updating related components (CLI, docs, tests).
*   [2025-04-04 13:04:30] - Finalized the re-architecture plan (see `decisionLog.md`) to use dynamic `PathSpec` compilation during traversal, incorporating feedback on `.contextfile` handling and explicit target inclusion.
*   [2025-04-04 17:49:34] - Updated `DEFAULT_RULES` in `config_system.py` to include more common exclusion patterns for directories (target, out, bin, obj, output, logs, .svn, .hg, .idea, .vscode, *.egg-info) and files (log.*, *.bak, *.tmp, *.temp, *.swp, *~).
*   [2025-04-04 22:37:09] - Updated documentation (`README.md`) and Memory Bank files (`productContext.md`, `systemPatterns.md`, `progress.md`, `decisionLog.md`, `activeContext.md`) to reflect the addition of the `jinni_doc` command/tool and the enhanced context size error handling (`DetailedContextSizeError`).
*   [2025-04-05 12:55:00] - Refactored `read_context` arguments: `project_root` is now mandatory (CLI: `-r`/`--root`, MCP: `project_root`), and an optional `target` argument specifies the item within the root. Updated `core_logic.py`, `cli.py`, `server.py`, `README.md`, and Memory Bank files (`decisionLog.md`, `productContext.md`).
*   [2025-04-05 01:53:00] - Corrected MCP server (`jinni/server.py`) implementation and integration tests (`tests/test_integration_mcp.py`) to properly use the mandatory `project_root` and optional `target` arguments.
*   [2025-04-05 02:13:00] - Refactored `core_logic.py` into smaller modules (`utils`, `exceptions`, `file_processor`, `context_walker`, new `core_logic`). Updated core `read_context` signature to handle both CLI (optional root, multiple paths) and Server (mandatory root, optional target) inputs. Fixed calls in CLI and Server handlers. Updated `README.md` and `decisionLog.md`.
*   [2025-04-05 12:20:00] - Changed override rule behavior in `core_logic.py` to replace default rules entirely, ensuring standard `.gitignore` precedence. Updated `README.md`, `DESIGN.md`, and `decisionLog.md`.
*   [2025-04-05 13:45:04] - Added optional `target` parameter to `read_context` MCP tool in `jinni/server.py` for single target convenience. Updated server logic to process union of `target` and `targets`. Updated `README.md` and Memory Bank files (`productContext.md`, `decisionLog.md`).
*   [2025-04-05 15:50:39] - Removed optional `target` parameter and made `targets` parameter mandatory for `read_context` MCP tool in `jinni/server.py`. Updated documentation and Memory Bank files (`productContext.md`, `decisionLog.md`).
*   [2025-04-05 15:59:17] - Fixed relative path resolution for `targets` in `read_context` MCP tool handler (`jinni/server.py`). Relative paths are now correctly resolved against the provided `project_root`. Updated `decisionLog.md`.
*   [2025-04-05 18:08:00] - Reverted `targets` parameter to optional for `read_context` MCP tool in `jinni/server.py`. Tool now defaults to processing `project_root` if `targets` is omitted or empty. Updated documentation and Memory Bank files (`productContext.md`, `decisionLog.md`).
*   [2025-04-05 22:45:00] - Reverted MCP `read_context` tool behavior: `targets` is mandatory but allows empty list (`[]`) to process project root. `rules` remains mandatory (allows `[]`). Updated server code, `README.md`, and Memory Bank files (`productContext.md`, `decisionLog.md`).
*   [2025-04-05 23:01:00] - Refactored `read_context` MCP tool signature in `jinni/server.py` to use Pydantic `Field` for argument descriptions (`project_root`, `targets`, `rules`), moving details from docstring/description. Updated Memory Bank (`decisionLog.md`).
*   [2025-04-05 23:09:00] - Renamed MCP tool `jinni_doc` to `usage` and CLI command `jinni doc` to `jinni usage`. Updated `jinni/server.py`, `jinni/core_logic.py`, `jinni/utils.py`, `jinni/cli.py`, `README.md`, and Memory Bank files (`decisionLog.md`, `productContext.md`).
*   [2025-04-06 00:47:59] - Approved plan and updated `decisionLog.md` to reflect the decision to migrate project distribution from Node.js (`npm`/`npx`) to Python (`uv`/`uvx`/PyPI).
*   [2025-04-06 01:03:00] - Added `jinni-server` script entry point to `pyproject.toml` based on user request, making the server directly executable via PATH alongside `uvx jinni-server`.
## Open Questions/Issues
*   [2025-04-02 19:16:35] - Feature Request: Allow CLI to accept multiple directory/file paths as positional arguments, avoiding duplicate output.
*   [2025-04-02 19:16:35] - Feature Request: Add new MCP tool `read_context_list` to handle multiple paths and avoid duplicates, similar to the CLI request.
*   [2025-04-06 00:48:03] - Resolved: Decision made to use Python (`uv`/`uvx`/PyPI) for distribution, removing Node.js components.
*