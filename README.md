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
*   **Intelligent Filtering:**
    *   Applies sensible default exclusions for common development artifacts (VCS directories, build outputs, logs, dependencies like `node_modules`, `venv`, etc.).
    *   Supports hierarchical configuration using `.contextfiles` placed within your project directories.
*   **Customizable Configuration (`.contextfiles`):**
    *   Fine-tune file/directory inclusion and exclusion using glob patterns.
    *   Override default rules on a per-directory basis. (See Configuration section below).
*   **Large Context Handling:** Aborts with an error if the total size of included files exceeds a configurable limit (default: 100MB) to prevent excessive output.
*   **Metadata Headers:** Output includes file path, size, and modification time for each included file (can be disabled with `list_only`).
*   **Encoding Handling:** Attempts multiple common text encodings (UTF-8, Latin-1, etc.).
*   **List Only Mode:** Option to only list the relative paths of files that would be included, without their content.

## Usage

### MCP Server (`read_context` tool)

1.  **Setup:** Configure your MCP client (e.g., Claude Desktop's `claude_desktop_config.json`) to run the `jinni` server executable.
2.  **Invocation:** When interacting with your LLM via the MCP client, the model can invoke the `read_context` tool.
    *   **`path` (string, required):** The absolute path to the project directory to analyze.
    *   **`rules` (array of strings, optional):** A list of inline filtering rules (using `.contextfiles` syntax, e.g., `["!*.tmp", "include_this/"]`). These rules have the highest precedence, overriding any found in `.contextfiles` or global configs.
    *   **`list_only` (boolean, optional):** If true, returns only the list of relative file paths instead of content.
3.  **Output:** The tool returns a single string containing the concatenated content (with headers) or the file list.

*(Detailed server setup instructions will vary depending on your MCP client. Generally, you need to configure the client to execute the `jinni` server script. For example, in a hypothetical `mcp_client_config.json`):*

```json
{
  "servers": [
    {
      "name": "jinni-context-server",
      "command": ["python", "-m", "jinni.server"], // Or the path to your jinni server executable/script
      "transport": "stdio"
    }
  ]
}
```

*Consult your specific MCP client's documentation for precise setup steps.*

### Command-Line Utility (`jinni` CLI)

```bash
jinni [OPTIONS] <PATH>
```

*   **`<PATH>` (required):** The path to the project directory to analyze.
*   **`--output <FILE>` (optional):** Write the output to `<FILE>` instead of printing to standard output.
*   **`--list-only` (optional):** Only list the relative paths of files that would be included.
*   **`--config <FILE>` (optional):** Use a global configuration file (in `.contextfiles` format) applied before defaults and local `.contextfiles`.

### Installation

*(Assuming standard Python packaging)*

```bash
pip install .  # From the project root directory
# Or, if distributed via PyPI:
# pip install jinni-context-tool
```

### Examples

*   **Dump context of `my_project/` to the console:**
    ```bash
    jinni ./my_project/
    ```

*   **List files that would be included in `my_project/` without content:**
    ```bash
    jinni --list-only ./my_project/
    ```

*   **Dump context of `my_project/` to a file named `context_dump.txt`:**
    ```bash
    jinni --output context_dump.txt ./my_project/
    ```

*   **Use a global rule set from `~/global_rules.contextfiles`:**
    ```bash
    jinni --config ~/global_rules.contextfiles ./my_project/
    ```

## Configuration (`.contextfiles`)

You can customize Jinni's filtering behavior by placing a file named `.contextfiles` in any directory within your project.

*   **Format:** Plain text, UTF-8 encoded, one rule per line.
*   **Comments:** Lines starting with `#` are ignored.
*   **Exclusion Rules:** Lines starting with `!` exclude matching files/directories (e.g., `!*.log`, `!temp/`).
*   **Inclusion Rules:** All other non-comment lines include matching files/directories, potentially overriding broader exclusions or defaults (e.g., `important.log`, `src/`).
*   **Patterns:** Rules use standard [glob patterns](https://docs.python.org/3/library/fnmatch.html). Patterns ending with `/` match directories only. Patterns match relative paths from the directory containing the `.contextfiles`.
*   **Hierarchy:** Inline rules (from MCP tool call) > Subdirectory `.contextfiles` > Parent Directory `.contextfiles` > Global Config (`--config` CLI option) > Default Exclusions. Within the same rule source, `!` exclusions override inclusions.

### Examples

**Example 1: Basic Exclusions**

Located at `my_project/.contextfiles`:

```
# Exclude all log files and the build directory
!*.log
!build/
```

**Example 2: Including Specific Files/Directories**

Located at `my_project/src/.contextfiles`:

```
# Include everything in src by default (overrides potential parent exclusions)
*

# But exclude temporary files within src
!*.tmp

# Explicitly include a specific config file even if logs are excluded elsewhere
important_config.log
```

## Development

*   **Project Plan:** [PLAN.md](PLAN.md)
*   **Design Details:** [DESIGN.md](DESIGN.md)

*(Contribution guidelines can be added here if needed)*