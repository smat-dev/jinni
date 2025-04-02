# Decision Log

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

## Rationale

*   The plan provides a clear roadmap based on initial context gathering and user feedback, outlining core components and ordered tasks (Design/Docs -> Tests -> Implementation).
*   Aborting on size limit is safer than potentially providing incomplete context. `read_context` is a more descriptive tool name. Skipping symlinks is a safer default. Global config provides flexibility.
*   Keeping a single root path simplifies the core logic while inline rules still allow flexible configuration directly from the MCP client if needed, balancing simplicity and power.

## Implementation Details

*   The plan involves refining the prototype code, building a CLI, implementing a configuration system, testing, and documentation. Implementation will start with detailed design and documentation.
*   Specific design choices for `.contextfiles` format/hierarchy, size limit handling, symlink skipping, global config interaction, and `read_context` arguments (single path, optional inline rules) are documented in `DESIGN.md`.
*   The plan involves refining the prototype code, building a CLI, implementing a configuration system, testing, and documentation. Implementation will start with detailed design and documentation.
*   [2025-04-02 19:29:52] - User feedback suggests shifting distribution/installation from Python/`pip` to Node.js/`npm`/`npx`. This requires architectural review.
*   [2025-04-02 19:52:56] - Refactored default exclusion logic in `config_system.py` to use a unified glob pattern list (`DEFAULT_EXCLUDE_RULESET`) instead of separate sets/regex, integrating it into the standard rule precedence check (`check_item`). This simplifies the system and makes defaults behave consistently with other rules.
*   [2025-04-02 19:29:52] - User feedback suggests shifting distribution/installation from Python/`pip` to Node.js/`npm`/`npx`. This requires architectural review.