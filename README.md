<img src="assets/jinni_banner_1280x640.png" alt="Jinni Banner" width="400"/>

# Jinni: Bring Your Project Into LLM Context

Jinni is a tool designed to help Large Language Models (LLMs) efficiently understand the context of your software projects. It provides a consolidated view of relevant project files, overcoming the limitations and inefficiencies of reading files one by one.

Jinni achieves this through two main components: an MCP (Model Context Protocol) server for integration with AI tools and a command-line utility (CLI) for manual use.

## Components

1.  **`jinni` MCP Server:**
    *   Integrates with MCP-compatible clients (like Claude Desktop, Continue.dev, etc.).
    *   Exposes a `read_context` tool that returns a concatenated string of relevant file contents from a specified project directory.
    *   Uses intelligent filtering based on default rules and custom `.contextfiles`.
    *   Communicates via stdio.

2.  **`jinni` CLI:**
    *   A command-line tool for manually generating the project context dump.
    *   Useful for scripting, local analysis, or feeding context to LLMs via copy-paste or file input.
    *   Provides similar filtering and output capabilities as the MCP server.

## Features

*   **Efficient Context Gathering:** Reads and concatenates relevant project files in one operation.
*   **Intelligent Filtering (Gitignore-Style Inclusion):**
    *   Uses a system based on `.gitignore` syntax (`pathspec` library's `gitwildmatch`).
    *   Supports hierarchical configuration using `.contextfiles` placed within your project directories. Rules are applied dynamically based on the file/directory being processed.
    *   **Overrides:** Supports `--overrides` (CLI) or `rules` (MCP) to completely replace `.contextfiles` logic for specific runs.
    *   **Explicit Target Inclusion:** Files/directories explicitly provided as input paths are *always* included/traversed.
   *   **Customizable Configuration (`.contextfiles` / Overrides):**
       *   Define precisely which files/directories to include or exclude using `.gitignore`-style patterns.
       *   Patterns starting with `!` negate the match (an exclusion pattern). (See Configuration section below).
*   **Large Context Handling:** Aborts with an error if the total size of included files exceeds a configurable limit (default: 100MB) to prevent excessive output.
*   **Metadata Headers:** Output includes file path, size, and modification time for each included file (can be disabled with `list_only`).
*   **Encoding Handling:** Attempts multiple common text encodings (UTF-8, Latin-1, etc.).
*   **List Only Mode:** Option to only list the relative paths of files that would be included, without their content.

## Usage

### MCP Server (`read_context` tool)

1.  **Setup:** Configure your MCP client (e.g., Claude Desktop's `claude_desktop_config.json`) to run the `jinni` server executable.
2.  **Invocation:** When interacting with your LLM via the MCP client, the model can invoke the `read_context` tool.
    *   **`path` (string, required):** The absolute path to the target file or directory to analyze.
    *   **`rules` (array of strings, optional):** A list of inline filtering rules (using `.gitignore`-style syntax, e.g., `["src/**/*.py", "!*.tmp"]`). If provided, these rules **override** and replace any `.contextfiles` logic.
    *   **`list_only` (boolean, optional):** If true, returns only the list of relative file paths instead of content.
    *   **`size_limit_mb` (integer, optional):** Override the context size limit in MB.
    *   **`debug_explain` (boolean, optional):** Enable debug logging on the server.
    3.  **Output:** The tool returns a single string containing the concatenated content (with headers) or the file list. Paths in headers are relative to the common ancestor of the target(s) or the server's `--root` if set.

*(Detailed server setup instructions will vary depending on your MCP client. Generally, you need to configure the client to execute the `jinni-server` command. For example, in Claude Desktop's `claude_desktop_config.json`):*

```json
{
  "mcpServers": {
    "jinni": {
      "command": "jinni-server"
      // Note: You can optionally start the server to only read files from a specific directory tree (recommended for security/safety):
      // "command": "jinni-server --root /absolute/path/"
    }
  }
}
```

*Consult your specific MCP client's documentation for precise setup steps. Ensure `jinni-server` (installed via `npm install -g jinni`) is accessible in your system's PATH.*

### Command-Line Utility (`jinni` CLI)

```bash
jinni [OPTIONS] <PATH...>
```

*   **`<PATH...>` (optional):** One or more paths to the project directories or files to analyze. Defaults to the current directory (`.`) if none are provided.
*   **`--output <FILE>` / `-o <FILE>` (optional):** Write the output to `<FILE>` instead of printing to standard output.
*   **`--list-only` / `-l` (optional):** Only list the relative paths of files that would be included.
*   **`--overrides <FILE>` (optional):** Use rules from `<FILE>` instead of discovering `.contextfiles`.
*   **`--size-limit-mb <MB>` / `-s <MB>` (optional):** Override the maximum context size in MB.
*   **`--debug-explain` (optional):** Print detailed inclusion/exclusion reasons to stderr and `jinni_debug.log`.
*   **`--output-relative-to <DIR>` (optional):** Make output file paths relative to `<DIR>` instead of the default (common ancestor or CWD).
*   **`--no-copy` (optional):** Prevent automatically copying the output content to the system clipboard when printing to standard output (the default is to copy).

### Installation

You can install Jinni globally using npm:

```bash
npm install -g jinni
```

This will make the `jinni` CLI and `jinni-server` MCP server command available in your system PATH.

Alternatively, you can run the CLI directly without global installation using `npx`:

```bash
npx jinni [OPTIONS] <PATH>
```

### Examples

*   **Dump context of `my_project/` to the console:**
    ```bash
    jinni ./my_project/ # Process a single directory
    jinni ./src ./docs/README.md # Process multiple targets
    jinni # Process current directory (.)
    ```

*   **List files that would be included in `my_project/` without content:**
    ```bash
    jinni -l ./my_project/
    jinni --list-only ./src ./docs/README.md
    ```

*   **Dump context of `my_project/` to a file named `context_dump.txt`:**
    ```bash
    jinni -o context_dump.txt ./my_project/
    ```

*   **Use override rules from `custom.rules` instead of `.contextfiles`:**
    ```bash
    jinni --overrides custom.rules ./my_project/
    ```
*   **Show debug information:**
    ```bash
    jinni --debug-explain ./src
    ```
*   **Dump context (output is automatically copied to clipboard by default):**
    ```bash
    jinni ./my_project/
    ```
*   **Dump context but *do not* copy to clipboard:**
    ```bash
    jinni --no-copy ./my_project/
    ```

## Configuration (`.contextfiles` & Overrides)

Jinni uses `.contextfiles` (or an override file) to determine which files and directories to include or exclude, based on `.gitignore`-style patterns.

*   **Core Principle:** Rules are applied dynamically during traversal. The effective rules for any given file/directory depend on the `.contextfiles` found in its parent directories (up to a common root) or the override rules.
*   **Location (`.contextfiles`):** Place `.contextfiles` in any directory. Rules apply to that directory and its subdirectories, inheriting rules from parent directories.
*   **Format:** Plain text, UTF-8 encoded, one pattern per line.
*   **Syntax:** Uses standard `.gitignore` pattern syntax (specifically `pathspec`'s `gitwildmatch` implementation).
    *   **Comments:** Lines starting with `#` are ignored.
    *   **Inclusion Patterns:** Specify files/directories to include (e.g., `src/**/*.py`, `*.md`, `/config.yaml`).
    *   **Exclusion Patterns:** Lines starting with `!` indicate that a matching file should be excluded (negates the pattern).
    *   **Anchoring:** A leading `/` anchors the pattern to the directory containing the `.contextfiles`.
    *   **Directory Matching:** A trailing `/` matches directories only.
    *   **Wildcards:** `*`, `**`, `?` work as in `.gitignore`.
*   **Rule Application Logic:**
    1.  **Override Check:** If `--overrides` (CLI) or `rules` (MCP) are provided, these rules (combined with built-in defaults) are used exclusively. All `.contextfiles` are ignored.
    2.  **Dynamic Context Rules (No Overrides):** When processing a file or directory, Jinni:
        *   Finds all `.contextfiles` starting from a common root directory down to the current item's directory.
        *   Combines the rules from these files (parent rules first, child rules last) along with built-in default rules.
        *   Compiles these combined rules into a temporary specification (`PathSpec`).
        *   Matches the current file/directory path (relative to the common root) against this specification.
    3.  **Matching:** The **last pattern** in the combined rule set that matches the item determines its fate. If the last matching pattern starts with `!`, the item is excluded. Otherwise, it's included. If no user-defined pattern in the combined rule set matches the item, it is included *unless* it matches one of the built-in default exclusion patterns (e.g., `.git/`, `node_modules/`, common binary extensions). If no pattern matches at all (neither user nor default), the item is included. Explicitly provided targets are always included regardless of rules.
    4.  **Explicit Target Inclusion:** Any file or directory path explicitly provided as a command-line argument is *always* included or traversed, regardless of matching rules. Rules *are* still applied to *contents* of explicitly included directories.

### Examples (`.contextfiles`)

**Example 1: Include Python Source and Root Config**

Located at `my_project/.contextfiles`:

```
# Include all Python files in the src directory and subdirectories
src/**/*.py

# Include the main config file at the root of the project
/config.json

# Include all markdown files anywhere
*.md

# Exclude any test data directories found anywhere
!**/test_data/
```

**Example 2: Overriding in a Subdirectory**

Located at `my_project/src/.contextfiles`:

```
# In addition to rules inherited from parent .contextfiles...

# Include specific utility scripts in this directory
utils/*.sh

# Exclude a specific generated file within src, even if *.py is included elsewhere
!generated_parser.py
```

## Development

*   **Project Plan:** [PLAN.md](PLAN.md)
*   **Design Details:** [DESIGN.md](DESIGN.md)

*(Contribution guidelines can be added here if needed)*