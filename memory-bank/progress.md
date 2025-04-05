# Progress

This file tracks the project's progress using a task list format.
[2025-04-04 15:57:00] - Cleaned up task list for clarity.

*

## Completed Tasks

*   [2025-04-02 18:46:33] - Task 1: Detailed Design & Documentation - Initial version completed. [2025-04-03 17:23:00] - Updated DESIGN.md and README.md significantly to reflect major `.contextfiles` redesign (Gitignore-style inclusion).
*   [2025-04-04 15:45:00] - Task 8: Implement Binary File Detection - Verified implementation using `mimetypes` and null-byte fallback in `core_logic.py`. [2025-04-04 15:46:00] - Refined: Binary check now applies even when `-l`/`--list-only` flag is used, ensuring list output matches content output regarding binary exclusion.
*   [2025-04-04 15:50:00] - Task 16: Implement CLI Clipboard Copy Feature - Added `-c`/`--copy` flag to `jinni/cli.py` using `pyperclip`. Updated `requirements.txt`, `README.md`, `DESIGN.md`, and `decisionLog.md`. [2025-04-04 15:51:00] - Refined: Changed to copy-by-default for stdout, added `--no-copy` flag. Updated CLI script and documentation.
*   [2025-04-04 15:55:00] - Task 17: Default CLI Path Argument to Current Directory - Modified `jinni/cli.py` to make the `paths` argument optional (nargs='*', default=['.']). Updated `README.md`, `DESIGN.md`, and `decisionLog.md`.
*   [2025-04-04 15:58:00] - Task 10: Implement Multi-Path CLI Input - Completed as part of Task 17 (changing `paths` nargs to `'*'`).
*   [2025-04-04 22:35:54] - Task 18: Implement `jinni doc` / `jinni_doc` and Context Size Error Handling - Added `jinni doc` CLI command and `jinni_doc` MCP tool. Implemented `DetailedContextSizeError` in `core_logic.py` to report the 10 largest files when the size limit is exceeded. Updated CLI, server, and documentation (`README.md`, Memory Bank).
*   [2025-04-05 12:55:00] - Task 19: Refactor `read_context` Arguments (Mandatory `project_root`, Optional `target`) - Changed `read_context` signature in `core_logic.py`, made `-r`/`--root` required in `cli.py`, updated MCP tool schema in `server.py`. Updated `README.md` and Memory Bank files.

## Current Major Task

*   [2025-04-06 00:48:19] - **Task 20: Migrate Distribution from npm/npx to uv/PyPI**
    *   **Goal:** Remove Node.js artifacts, establish Python packaging with `pyproject.toml`, update documentation (`README.md`) for `uv`/`pip`/`uvx` installation and usage.
    *   **Includes:** Modifying `.gitignore`, creating `pyproject.toml`, updating `README.md`, updating Memory Bank.
        *   [2025-04-06 01:03:00] - Added `jinni-server` to `[project.scripts]` in `pyproject.toml` for direct execution.

## Pending Tasks (Post-Refactor / Migration)

*   [2025-04-04 13:05:00] - **Task 15: Re-architect Config System & Core Logic (Dynamic Traversal)** - *Review/Finalize after migration.*
    *   **Goal:** Implement dynamic `PathSpec` compilation during traversal (`core_logic.py`), handle `.contextfiles` hierarchy, implement overrides, ensure explicit target inclusion.
    *   **Includes:** Updating CLI (`--overrides`), server, unit tests (Task 2), integration tests (Task 7), and documentation (Task 6) to align with the new architecture.
    *   *(Note: Tasks 3, 4, 5, 11, 12, 13, 14 are effectively superseded or incorporated into this task).*

*   [2025-04-02 19:52:56] - Task 9: Implement Debug Explain Option (`--debug-explain`).
*   Task 6: Final review and update of all documentation (`README.md`, `DESIGN.md`).
*   [2025-04-06 00:48:19] - Task TBD: Address distribution/installation method (Python/pip vs Node.js/npm) - **Resolved:** Decision made to use Python (`uv`/PyPI). See Task 20.