# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed
- Changed context output header to ````path=<path>` format, followed by file content enclosed in triple backticks, to reduce token usage. Removed size and last modified time from the header.

### Added
- WSL path translation now always uses `\\wsl$\<distro>\...` for maximum compatibility (no more `wsl.localhost`).
- Distro names are sanitized: only illegal UNC characters are replaced with `_`, spaces are allowed.
- WSL path lookups and conversions are cached for performance.
- New environment variable: `JINNI_NO_WSL_TRANSLATE=1` disables all WSL path translation logic.
- Automatic fallback for WSL path translation on Windows when `wslpath` is unavailable. Jinni now attempts to determine the default distro using `wsl -l -q` and constructs the UNC path (`\\wsl$\...`) manually.
- Environment variable `JINNI_ASSUME_WSL_DISTRO` allows overriding the automatically detected default distro for the manual fallback.
- Added support for stripping `vscode-remote://wsl.localhost/Distro/...` URIs to `/...` on non-Windows platforms.
- Context gathering now respects `.gitignore` files (lower priority than `.contextfiles`).

### Changed
- If you install WSL while Jinni is running, restart Jinni to pick up the new `wslpath`.
- WSL path translation (`_translate_wsl_path`) now raises `ValueError` for malformed WSL URIs missing a distribution name (e.g., `vscode-remote://wsl+/...`).
- WSL path translation (`_translate_wsl_path`) now raises `RuntimeError` on Windows if a POSIX path is given but cannot be translated (e.g., `wslpath` fails and manual fallback also fails due to no WSL/distro found or constructed path not existing).

### Fixed
- Fixed crash on Windows when WSL distro name contains embedded NULs due to UTF-16LE output from wsl -l -q. Now raises ValueError with a clear message.

## [0.1.7] - YYYY-MM-DD
### Added
- Windows + WSL & VS Code-Remote path support: Jinni now auto-converts WSL paths (`/home/user/project`) and `vscode-remote://wsl+Distro/...` URIs to the correct `\\wsl$\Distro\...` UNC form when running on Windows. This applies to paths provided via CLI arguments (`paths`, `--root`, `--overrides`) and the MCP `read_context` tool arguments (`project_root`, `targets`).

## [0.2.4] - YYYY-MM-DD

### Added
- Added `--list-token` / `-L` CLI option to list files with token counts (using tiktoken cl100k_base) and a total sum. This is mutually exclusive with `--list-only` / `-l`.
- WSL path translation now always uses `\\wsl$\<distro>\...` for maximum compatibility (no more `wsl.localhost`).
- Distro names are sanitized: only illegal UNC characters are replaced with `_`, spaces are allowed.

[Unreleased]: https://github.com/smat-dev/jinni/compare/v0.1.7...HEAD
[0.1.7]: https://github.com/smat-dev/jinni/releases/tag/v0.1.7
[0.2.4]: https://github.com/smat-dev/jinni/compare/v0.1.7...v0.2.4 