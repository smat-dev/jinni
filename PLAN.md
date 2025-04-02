# Jinni Project Plan (Approved: 2025-04-02)

## 1. Project Goal

Create a tool (MCP server and CLI utility named "jinni") to help LLMs efficiently read and understand project context by providing a concatenated view of relevant files, overcoming limitations of piecemeal file reading.

## 2. Core Components

*   **`jinni` MCP Server:** Python-based, using `mcp.server.fastmcp`, stdio transport, exposing `read_context` tool (takes single path, optional inline rules). (Note: Implementation in `dev-reference/prototype.py` needs updates for server name, tool name, and arguments).
*   **`jinni` CLI:** Python CLI for manual context dumping with configuration options.
*   **Core Logic Module:** Python module(s) for file discovery, filtering (using defaults and `.contextfiles`), content reading (handling encodings), output formatting, and large context handling.
*   **Configuration System:** Logic to find, parse, and apply rules from `.contextfiles`.

## 3. High-Level Tasks (Ordered)

1.  **Detailed Design & Documentation:**
    *   Finalize the design of the Core Logic Module, Configuration System, MCP Server interface, and CLI arguments.
    *   Document the `.contextfiles` format and rule syntax.
    *   Outline the overall architecture and component interactions.
    *   Update `README.md` with design overview and initial usage concepts.
2.  **Develop Tests:**
    *   Write unit tests for the Core Logic (filtering, encoding handling, concatenation).
    *   Write unit tests for the Configuration System (rule parsing, application).
    *   Prepare integration test setups for the MCP server and CLI.
3.  **Implement Core Logic & Configuration System:**
    *   Refine and implement the file processing logic based on `dev-reference/prototype.py` and the detailed design.
    *   Implement the Configuration System (`.contextfiles` parsing and rule application).
    *   Ensure unit tests pass.
4.  **Implement `jinni` MCP Server:**
    *   Package the server, ensuring the server name is "jinni".
    *   Ensure full MCP compliance (tool definitions, capabilities, error handling).
    *   Run integration tests.
5.  **Implement `jinni` CLI:**
    *   Implement the CLI wrapper around the Core Logic Module based on the detailed design.
    *   Implement user-friendly output and error reporting.
    *   Run integration tests.
6.  **Finalize Documentation:**
    *   Complete `README.md` with detailed usage instructions for both server and CLI.
    *   Add examples.
    *   Generate API documentation if applicable.

## 4. Architecture Diagram

```mermaid
graph TD
    subgraph Jinni Project
        A[User/Client] --> B(jinni CLI);
        A --> C{MCP Host};
        C --> D(jinni MCP Server); // Renamed from codedump
        B --> E{Core Logic Module};
        D --> E;
        E --> F[File System];
        E --> G(Configuration System);
        G --> H[.contextfiles];
    end