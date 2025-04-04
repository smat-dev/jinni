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