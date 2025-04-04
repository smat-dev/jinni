!# Decision Log

This file records architectural and implementation decisions using a list format.
2025-04-02 18:07:44 - Log of updates made.

*

## Decision

*   [2025-04-02 18:29:42] - Adopted the finalized project plan for 'jinni' (see PLAN.md).
*   [2025-04-02 18:36:52] - Refined design details (see DESIGN.md):
    *   MCP tool name confirmed as `read_context`.
    *   Large context handling will abort with an error message, not truncate.
    *   Symbolic links will be skipped.
    *   CLI `--config` flag provides global rules applied before defaults and `.contextfiles`.
*   [2025-04-02 18:45:42] - Further refined `read_context` tool design: reverted to single `path` argument but kept optional inline `rules` argument.
*   [2025-04-03 16:26:00] - Approved plan to redesign `core_logic.py` to correctly prune directory traversal using `check_item` on directories within the `os.walk` loop.
*   [2025-04-03 17:20:00] - Approved major redesign of the `.contextfiles` system to use `.gitignore`-style filtering logic, leveraging the `pathspec` library. Files/directories are now included by default, with exclusions handled by built-in defaults and `.contextfiles` rules.
 *   [2025-04-04 15:39:00] - Enhanced binary file detection logic in `_is_binary` function.
 *   [2025-04-04 15:46:00] - Changed behavior of `-l`/`--list-only` flag to apply binary check.
 *   [2025-04-04 15:50:00] - Added CLI feature to copy output to clipboard. [2025-04-04 15:51:00] - Changed to default behavior with `--no-copy` opt-out.
 *   [2025-04-04 15:55:00] - Made CLI `paths` argument optional, defaulting to `.` (current directory).
 *   [2025-04-04 19:48:00] - Reverted binary file detection logic. Now uses a multi-stage heuristic: 1) `mimetypes.guess_type()`, 2) Fallback to null-byte check in first chunk, 3) If no null bytes, fallback to printable character ratio heuristic (`is_human_readable`). (Note: `puremagic` library is no longer used for this).
 *   [2025-04-04 20:05:00] - Added CLI option `-S`/`--size` to display file sizes alongside paths when using `-l`/`--list-only`.
*   [2025-04-04 22:36:08] - Added `jinni doc` CLI command and `jinni_doc` MCP tool to display README content.
*   [2025-04-04 22:36:08] - Implemented enhanced context size error handling using `DetailedContextSizeError` to report the 10 largest files.
*   [2025-04-05 12:54:00] - Refactored `read_context` arguments: `project_root` (string) is now mandatory, `target` (string) is optional (replaces previous `path`/`target_paths`).
*   [2025-04-05 01:52:00] - Corrected MCP server `read_context` tool implementation to align with the refactored arguments (mandatory `project_root`, optional `target`). (Note: Core logic alignment pending further refactor).
*   [2025-04-05 02:13:00] - Reversed decision on CLI structure. Kept existing CLI args (optional root, multiple paths) based on user feedback. Refactored `core_logic.py` into `utils.py`, `exceptions.py`, `file_processor.py`, `context_walker.py`, and a new `core_logic.py` orchestrator to handle both CLI and Server input styles.

## Rationale

*   The plan provides a clear roadmap based on initial context gathering and user feedback, outlining core components and ordered tasks (Design/Docs -> Tests -> Implementation).
*   Aborting on size limit is safer than potentially providing incomplete context. `read_context` is a more descriptive tool name. Skipping symlinks is a safer default. Global config provides flexibility.
*   Keeping a single root path simplifies the core logic while inline rules still allow flexible configuration directly from the MCP client if needed, balancing simplicity and power.
*   [2025-04-03 16:26:00] - Current `core_logic.py` implementation traverses into directories before checking exclusion rules, leading to incorrect behavior (e.g., entering `node_modules`). Checking directories within `os.walk` (using `topdown=True`) and pruning `dirnames` is the standard way to prevent unwanted traversal.
*   [2025-04-03 17:20:00] - The `.gitignore` pattern syntax is widely understood by developers. Using `pathspec` provides a robust, well-tested implementation. Shifting from exclude-by-default to include-by-default provides more explicit control over what context is shared, reducing the risk of accidentally including sensitive or irrelevant files while relying on default and custom exclusions.
*   [2025-04-04 13:00:00] - Rationale for dynamic spec: Directly implements user requirement of discovering context "while walking". Avoids initial upward pass. Ensures rules are precisely scoped to the current directory's context hierarchy. Explicit target inclusion guarantees user-specified items are processed. Override consistency maintained.
 *   [2025-04-04 15:39:00] - The previous null-byte check was insufficient for some binary types (e.g., PNG). Using `mimetypes.guess_type` provides a more robust initial check based on file extension, falling back to the null-byte check for ambiguous cases. This avoids adding external dependencies like `python-magic`.
*   [2025-04-04 15:46:00] - User requested that the `-l` output exactly match the files whose content would be included in a normal run. Previously, `-l` skipped the binary check.
*   [2025-04-04 15:50:00] - User requested a convenient way to get CLI output into the clipboard. Added dependency `pyperclip`. [2025-04-04 15:51:00] - User preferred copy-by-default for stdout.
*   [2025-04-04 15:55:00] - User requested simpler invocation for the common case of processing the current directory.
*   [2025-04-04 19:48:00] - The `puremagic` approach was reverted. The current multi-stage heuristic (`mimetypes` -> null-byte -> printable ratio) aims for a balance between performance, standard library usage, and reasonable accuracy without relying on external magic number databases or libraries like `libmagic`. It prioritizes speed and simplicity over guaranteed accuracy for all edge-case binary formats.
*   [2025-04-04 20:05:00] - User requested the ability to see file sizes in the list output, which is useful for quickly assessing the contribution of different files to the total context size without needing to run the full context dump.
*   [2025-04-04 22:36:08] - `jinni doc`/`jinni_doc` provides convenient access to documentation (README) directly via CLI or MCP, useful for reference during usage or troubleshooting.
*   [2025-04-04 22:36:08] - Simply aborting on context size limit wasn't user-friendly. Raising a specific error (`DetailedContextSizeError`) and including the list of largest files gives the user actionable information to configure exclusions effectively.
*   [2025-04-05 12:54:00] - Clarifies the primary input as the project scope (`project_root`), making the specific file/directory (`target`) secondary. Aligns better with the concept of providing context for a whole project, optionally focusing on a part.
*   [2025-04-05 01:52:00] - The previous refactoring (Task 19) was not fully applied to the MCP server implementation (`jinni/server.py`), leaving it with incorrect arguments (`path` mandatory, `project_root` optional). This correction ensures consistency between the server tool definition and the underlying core logic (at the time).
*   [2025-04-05 02:13:00] - User preferred the existing flexible CLI argument structure. Refactoring `core_logic.py` allows supporting this while maintaining a stricter interface for the MCP server. This avoids breaking CLI user experience while enabling clearer programmatic use via MCP.



## Implementation Details

*   The plan involves refining the prototype code, building a CLI, implementing a configuration system, testing, and documentation. Implementation will start with detailed design and documentation.
*   Specific design choices for `.contextfiles` format/hierarchy, size limit handling, symlink skipping, global config interaction, and `read_context` arguments (single path, optional inline rules) are documented in `DESIGN.md`.
*   The plan involves refining the prototype code, building a CLI, implementing a configuration system, testing, and documentation. Implementation will start with detailed design and documentation.
*   [2025-04-02 19:29:52] - User feedback suggests shifting distribution/installation from Python/`pip` to Node.js/`npm`/`npx`. This requires architectural review.
*   [2025-04-02 19:52:56] - Refactored default exclusion logic in `config_system.py` to use a unified glob pattern list (`DEFAULT_EXCLUDE_RULESET`) instead of separate sets/regex, integrating it into the standard rule precedence check (`check_item`). This simplifies the system and makes defaults behave consistently with other rules.
*   [2025-04-02 19:29:52] - User feedback suggests shifting distribution/installation from Python/`pip` to Node.js/`npm`/`npx`. This requires architectural review.
*   [2025-04-03 16:26:00] - Modify the `os.walk` loop in `jinni/core_logic.py` to iterate through `dirnames`, call `check_item` for each directory path, and remove the directory name from the original `dirnames` list if `check_item` returns `False`.
*   [2025-04-03 17:20:00] - Refactor `jinni/config_system.py` to use `pathspec.PathSpec.from_lines('gitwildmatch', ...)` for parsing rules. Refactor `jinni/core_logic.py`'s `os.walk` loop to load hierarchical `PathSpec` objects and apply the new inclusion/exclusion logic, including directory pruning. Update `DESIGN.md` and `README.md` accordingly. Update unit and integration tests.
*   [2025-04-04 01:23:50] - Changed rule precedence: Inline rules (MCP `rules` argument) now act as a strict alternative, completely overriding and ignoring local `.contextfiles` when provided. Rationale: User request for simpler, alternative behavior. Implementation: Modified `jinni/config_system.py::check_item` logic, updated `DESIGN.md` and `README.md`. Tests require updating.
*   [2025-04-04 13:00:00] - Implementation Details: `core_logic.py` manages traversal (`os.walk`), finds relevant `.contextfiles` for the current directory during the walk (if overrides not active), calls `config_system.py` helpers to load/compile `PathSpec` for the current scope. `core_logic` also enforces explicit target inclusion before applying the spec. Update CLI/Server/Docs/Tests accordingly.
*   [2025-04-04 13:00:00] - Finalized re-architecture plan: Dynamically determine and compile the applicable `PathSpec` within each directory during `os.walk` traversal based on `.contextfiles` found from root down to the current directory. Explicitly provided target paths are always included/traversed regardless of rules. Overrides (CLI file or MCP list) replace `.contextfile` lookups entirely. Remove CLI `--config`, add `--overrides`. Use `pathlib`.
*   [2025-04-04 15:39:00] - Modified `jinni/core_logic.py::_is_binary`: Imported `mimetypes`. Added logic to first check `mimetypes.guess_type(file_path)`. If the type starts with 'text/', return `False`. Otherwise, proceed with the existing null-byte check on the first `BINARY_CHECK_CHUNK_SIZE` bytes.
*   [2025-04-04 15:46:00] - Modified `jinni/core_logic.py::read_context`: Removed `not list_only and` from the conditions checking the result of `_is_binary` (lines ~255 and ~434 in the previous version) so the check runs unconditionally.
*   [2025-04-04 15:50:00] - Added `pyperclip` to `requirements.txt`. Modified `jinni/cli.py`: added `-c`/`--copy` argument, imported `pyperclip`, added logic to call `pyperclip.copy(result_content)` if the flag is set and output is going to stdout. Updated `README.md` and `DESIGN.md`. [2025-04-04 15:51:00] - Changed CLI argument to `--no-copy` (action='store_true') and updated clipboard logic to copy unless `--no-copy` is present and output is stdout. Updated docs again.
*   [2025-04-04 15:55:00] - Modified `jinni/cli.py`: Changed `paths` argument `nargs` from `'+'` to `'*'` and added `default=['.']`. Updated `README.md` and `DESIGN.md`. (Note: Changing `nargs` to `'*'` also implicitly implemented Task 10: Multi-Path CLI Input).
*   [2025-04-04 19:48:00] - Removed `puremagic` dependency (if added). Updated `_is_binary` function in `jinni/core_logic.py` to implement the multi-stage heuristic: Check `mimetypes`, then check for null bytes in the first chunk, then call `is_human_readable` heuristic if no null bytes are found. Defaults to assuming text on read errors during fallback.
*   [2025-04-04 20:05:00] - Added `-S`/`--size` argument (action='store_true') to `jinni/cli.py`. Added `include_size_in_list` boolean parameter to `jinni/core_logic.py::read_context`. Modified `read_context` to prepend `f"{file_stat_size}\t"` to the output line when both `list_only` and `include_size_in_list` are true. Passed `args.size` from `cli.py` to `read_context`.
*   [2025-04-04 22:36:45] - Added `doc` subcommand to `jinni/cli.py`. Added `jinni_doc` tool handler to `jinni/server.py`. Both read and return `README.md`.
*   [2025-04-04 22:36:45] - Defined `DetailedContextSizeError` in `jinni/core_logic.py`. Modified `read_context` to calculate total size, check against limit, find the 10 largest files if limit exceeded, and raise `DetailedContextSizeError` with the list. Updated error handling in `jinni/cli.py` and `jinni/server.py` to catch this specific error and display the file list.
*   [2025-04-05 12:54:00] - (Partially Superseded) Attempted refactor of `core_logic.py` and CLI arguments. CLI changes reverted.
*   [2025-04-05 01:52:00] - Corrected `jinni/server.py` MCP tool arguments (`project_root`, `target`).
*   [2025-04-05 02:13:00] - Refactored original `jinni/core_logic.py` into `exceptions.py`, `utils.py`, `file_processor.py`, `context_walker.py`. Created new `jinni/core_logic.py` with `read_context(target_paths_str, project_root_str)` signature to handle CLI/Server differences and orchestrate calls to new modules. Updated imports in `cli.py`, `server.py`, `tests/test_utils.py`. Corrected `README.md` CLI documentation. Fixed CLI call to `read_context`. Updated Server call to adapt arguments.