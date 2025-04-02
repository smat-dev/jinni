import os
import tempfile
import shutil
import subprocess
import json
import time
import sys
import asyncio
import pytest # Use pytest
import logging # Added for logger access in helpers
from mcp import ClientSession, StdioServerParameters, types # MCP Client SDK
from mcp.client.stdio import stdio_client # MCP Client SDK

# Assuming 'jinni' command or python -m jinni.cli is executable
# Determine the path to the jinni CLI script
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
JINNI_CLI_PATH = os.path.join(PROJECT_ROOT, 'jinni', 'cli.py')
JINNI_SERVER_PATH = os.path.join(PROJECT_ROOT, 'jinni', 'server.py')
PYTHON_EXECUTABLE = sys.executable # Use the same python interpreter running the tests

# Setup logger for test helpers if needed
logger = logging.getLogger("jinni.test_integration")
if not logger.handlers and not logging.getLogger().handlers:
     logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')


# --- Helper Functions ---

def _create_test_structure(base_path):
    """Creates the complex test directory structure."""
    # Root level
    with open(os.path.join(base_path, "file_root.txt"), "w") as f:
        f.write("Root file content")
    with open(os.path.join(base_path, ".contextfiles"), "w") as f:
        f.write("# Root context rules\n")
        f.write("!*.log\n")         # Exclude all log files
        f.write("!*.tmp\n")         # Exclude all temp files
        f.write("!**/.*/**\n")      # Exclude hidden files/dirs contents (using original pattern)
        f.write("!**/.*\n")         # Exclude hidden files/dirs themselves (using original pattern)
        f.write("!**/.git/\n")      # Exclude .git dir (using original pattern)
        f.write("!.git/\n")         # Exclude .git dir at root specifically too
        f.write("!dir_b/sub_dir_b/\n") # Exclude specific subdirectory

    # dir_a
    dir_a = os.path.join(base_path, "dir_a")
    os.makedirs(dir_a)
    with open(os.path.join(dir_a, "file_a1.txt"), "w") as f:
        f.write("Content A1")
    with open(os.path.join(dir_a, "file_a2.log"), "w") as f: # Should be excluded by root rules
        f.write("Content A2 Log")
    with open(os.path.join(dir_a, ".contextfiles"), "w") as f:
        f.write("# dir_a context rules\n")
        f.write("*.txt\n")          # Include only .txt files in dir_a by default
        f.write("!file_a1.txt\n")   # BUT specifically exclude file_a1.txt

    # dir_b
    dir_b = os.path.join(base_path, "dir_b")
    os.makedirs(dir_b)
    with open(os.path.join(dir_b, "file_b1.py"), "w") as f:
        f.write("# Python content B1")
    sub_dir_b = os.path.join(dir_b, "sub_dir_b")
    os.makedirs(sub_dir_b)
    with open(os.path.join(sub_dir_b, "file_sub_b.tmp"), "w") as f: # Should be excluded by root rules
        f.write("Temp content Sub B")

    # Hidden dir
    hidden_dir = os.path.join(base_path, ".hidden_dir")
    os.makedirs(hidden_dir)
    with open(os.path.join(hidden_dir, "hidden_file.txt"), "w") as f: # Should be excluded by root rules
        f.write("Hidden content")

    # Binary file
    with open(os.path.join(base_path, "binary_file.bin"), "wb") as f:
        f.write(b"Some text\x00followed by a null byte.")

def run_jinni_cli(args):
    """Helper function to run the jinni CLI."""
    command = [PYTHON_EXECUTABLE, JINNI_CLI_PATH] + args
    try:
        # Run in the project root so imports work, but pass target dir as arg
        result = subprocess.run(command, capture_output=True, text=True, check=True, cwd=PROJECT_ROOT, timeout=5) # Reduced timeout
        return result.stdout, result.stderr
    except subprocess.CalledProcessError as e:
        logger.error(f"Error running Jinni CLI: {e}")
        logger.error(f"CLI Stdout: {e.stdout}")
        logger.error(f"CLI Stderr: {e.stderr}")
        raise
    except subprocess.TimeoutExpired as e:
        logger.error(f"Timeout running Jinni CLI: {e}")
        logger.error(f"CLI Stdout: {e.stdout}")
        logger.error(f"CLI Stderr: {e.stderr}")
        raise

async def run_mcp_tool_call(tool_name: str, arguments: dict):
   """
   Helper function to run the jinni MCP server via stdio_client,
   connect using ClientSession, call a tool, and return the result.
   """
   server_params = StdioServerParameters(
       command=PYTHON_EXECUTABLE,
       args=["-m", "jinni.server"], # Run server as module
       cwd=PROJECT_ROOT,
       # Note: Capturing server stderr directly is not straightforward with stdio_client
   )
   logger.debug(f"Starting MCP server with command: {server_params.command} {' '.join(server_params.args)}")

   try:
       async with stdio_client(server_params) as (read, write):
           logger.debug("stdio_client connected.")
           async with ClientSession(read, write) as session:
               logger.debug("ClientSession created. Initializing...")
               # Initialize the connection (sends initialization request/response)
               init_response = await session.initialize()
               logger.debug(f"MCP Session Initialized: {init_response}")

               # Call the specified tool
               logger.debug(f"Calling tool '{tool_name}' with arguments: {arguments}")
               result = await session.call_tool(tool_name, arguments=arguments)
               logger.debug(f"Tool '{tool_name}' returned result: {type(result)}") # Log type for clarity
               return result # Return the direct result payload from the tool

   except Exception as e:
       logger.error(f"Error during MCP client communication or tool call: {e}", exc_info=True)
       raise # Re-raise the exception to fail the test

# --- Pytest Fixture for Test Environment ---

@pytest.fixture(scope="function") # Create new env for each test function
def test_environment():
    """Pytest fixture to set up and tear down the test directory structure."""
    test_dir = tempfile.mkdtemp()
    logger.debug(f"Created test directory: {test_dir}")
    _create_test_structure(test_dir)
    original_cwd = os.getcwd()
    yield test_dir # Provide the test directory path to the test function
    # Teardown: Change back and remove directory
    logger.debug(f"Cleaning up test directory: {test_dir}")
    os.chdir(original_cwd)
    shutil.rmtree(test_dir)


# --- CLI Tests (Synchronous) ---

def test_cli_with_contextfiles(test_environment):
    """Test CLI run respecting hierarchical .contextfiles."""
    test_dir = test_environment
    stdout, stderr = run_jinni_cli([test_dir])
    assert "file_root.txt" in stdout
    assert "Root file content" in stdout
    assert "dir_b/file_b1.py" in stdout
    assert "# Python content B1" in stdout
    assert "dir_a/file_a1.txt" not in stdout
    assert "Content A1" not in stdout
    assert "dir_a/file_a2.log" not in stdout
    assert "dir_b/sub_dir_b/file_sub_b.tmp" not in stdout
    assert ".hidden_dir/hidden_file.txt" not in stdout
    assert ".contextfiles" not in stdout
    assert "binary_file.bin" not in stdout
    assert stderr.strip() == "" # Stderr should be empty now

def test_cli_list_only(test_environment):
    """Test the --list-only CLI flag."""
    test_dir = test_environment
    stdout, stderr = run_jinni_cli(['-l', test_dir]) # Use the new short flag -l
    expected_files = [
        "file_root.txt",
        "dir_b/file_b1.py",
    ]
    actual_files = sorted([line.strip() for line in stdout.strip().splitlines()]) # Sort for reliable comparison
    assert actual_files == sorted(expected_files), f"Expected {sorted(expected_files)}, got {actual_files}"
    assert "Root file content" not in stdout
    assert "# Python content B1" not in stdout
    assert stderr.strip() == "" # Stderr should be empty now

def test_cli_global_config(test_environment):
    """Test the --config CLI flag for global rules."""
    test_dir = test_environment
    global_config_path = os.path.join(test_dir, "global_rules.contextfiles")
    with open(global_config_path, "w") as f:
        f.write("# Global Rules\n")
        f.write("*.log\n") # Include log files (overrides root exclude)
        f.write("!dir_b/\n") # Exclude dir_b entirely
    target_dir = test_dir
    stdout, stderr = run_jinni_cli(['--config', global_config_path, target_dir])
    assert "file_root.txt" in stdout
    assert "dir_a/file_a2.log" not in stdout # Excluded by root !*.log, which has higher precedence than global *.log
    # assert "Content A2 Log" not in stdout # Content won't be present if file is excluded
    assert "dir_b/file_b1.py" not in stdout # Excluded by global !dir_b/
    assert "dir_a/file_a1.txt" not in stdout # Excluded by local !file_a1.txt
    assert "dir_b/sub_dir_b/" not in stdout # Excluded by global !dir_b/
    assert ".hidden_dir/" not in stdout # Excluded by default
    # Check that the root .contextfiles is NOT included (it's hidden)
    assert "File: .contextfiles\n" not in stdout
    assert "global_rules.contextfiles" in stdout # Config file itself is NOT automatically excluded
    assert stderr.strip() == "" # Stderr should be empty now

def test_cli_debug_explain(test_environment):
    """Test the --debug-explain CLI flag."""
    test_dir = test_environment
    stdout, stderr = run_jinni_cli(['--debug-explain', test_dir])
    # Check stderr for expected explanation patterns (using logger format)
    # Note: We check for substrings as the full stderr might contain many lines
    assert "DEBUG:jinni.core_logic:Checking File: file_root.txt -> Included by default (no matching rules)" in stderr
    assert "DEBUG:jinni.core_logic:Checking Dir : dir_a/ -> Included by default (no matching rules)" in stderr
    assert "DEBUG:jinni.core_logic:Checking File: dir_a/file_a1.txt -> Excluded by Local Rule (dir_a/.contextfiles): 'file_a1.txt'" in stderr
    assert "DEBUG:jinni.core_logic:Checking File: dir_a/file_a2.log -> Excluded by Local Rule (.contextfiles): '*.log'" in stderr
    assert "DEBUG:jinni.core_logic:Checking Dir : dir_b/ -> Included by default (no matching rules)" in stderr
    assert "DEBUG:jinni.core_logic:Checking File: dir_b/file_b1.py -> Included by default (no matching rules)" in stderr
    assert "DEBUG:jinni.core_logic:Checking Dir : dir_b/sub_dir_b/ -> Excluded by Local Rule (.contextfiles): 'dir_b/sub_dir_b/'" in stderr
    assert "DEBUG:jinni.core_logic:Checking File: binary_file.bin -> Included by default (no matching rules)" in stderr
    assert "DEBUG:jinni.core_logic:Skipping File: binary_file.bin -> Detected as binary" in stderr
    assert "DEBUG:jinni.core_logic:Checking Dir : .hidden_dir/ -> Excluded by Default Rule: '.*'" in stderr
    assert "DEBUG:jinni.core_logic:Checking File: .contextfiles -> Excluded by Default Rule: '.*'" in stderr

    # Check stdout is still correct (same as test_cli_with_contextfiles)
    assert "file_root.txt" in stdout
    assert "Root file content" in stdout
    assert "dir_b/file_b1.py" in stdout
    assert "dir_a/file_a1.txt" not in stdout
    assert "binary_file.bin" not in stdout
    assert "dir_a/file_a2.log" not in stdout

# --- MCP Tests (Asynchronous) ---

@pytest.mark.asyncio
async def test_mcp_read_context_basic(test_environment):
    """Test basic MCP read_context respecting .contextfiles."""
    test_dir = test_environment
    tool_name = "read_context"
    arguments = { "path": test_dir }
    result = await run_mcp_tool_call(tool_name, arguments)

    assert isinstance(result, types.CallToolResult)
    assert not result.isError
    assert len(result.content) == 1 and isinstance(result.content[0], types.TextContent)
    stdout_text = result.content[0].text # Extract text content

    # Assertions (same as CLI test)
    assert "file_root.txt" in stdout_text
    assert "Root file content" in stdout_text
    assert "dir_b/file_b1.py" in stdout_text
    assert "# Python content B1" in stdout_text
    assert "dir_a/file_a1.txt" not in stdout_text
    assert "Content A1" not in stdout_text
    assert "dir_a/file_a2.log" not in stdout_text
    assert "dir_b/sub_dir_b/file_sub_b.tmp" not in stdout_text
    assert ".hidden_dir/hidden_file.txt" not in stdout_text
    assert ".contextfiles" not in stdout_text
    assert "binary_file.bin" not in stdout_text
    # Note: Stderr assertion removed as stdio_client doesn't easily expose server stderr

@pytest.mark.asyncio
async def test_mcp_read_context_list_only(test_environment):
    """Test MCP read_context with list_only=True."""
    test_dir = test_environment
    tool_name = "read_context"
    arguments = { "path": test_dir, "list_only": True }
    result = await run_mcp_tool_call(tool_name, arguments)

    assert isinstance(result, types.CallToolResult)
    assert not result.isError
    assert len(result.content) == 1 and isinstance(result.content[0], types.TextContent)
    stdout_text = result.content[0].text # Extract text content
    actual_files = sorted([line.strip() for line in stdout_text.strip().splitlines()])

    expected_files = sorted([
        "file_root.txt",
        "dir_b/file_b1.py",
    ])
    assert actual_files == expected_files, f"Expected {expected_files}, got {actual_files}"
    # Note: Stderr assertion removed


@pytest.mark.asyncio
async def test_mcp_read_context_inline_rules(test_environment):
    """Test MCP read_context with inline rules overriding local."""
    test_dir = test_environment
    tool_name = "read_context"
    arguments = {
        "path": test_dir,
        "rules": [ "!*.txt", "dir_a/file_a1.txt" ] # Inline rules
    }
    result = await run_mcp_tool_call(tool_name, arguments)

    assert isinstance(result, types.CallToolResult)
    assert not result.isError
    assert len(result.content) == 1 and isinstance(result.content[0], types.TextContent)
    stdout_text = result.content[0].text # Extract text content

    # Assertions based on inline rules precedence:
    assert "dir_a/file_a1.txt" in stdout_text # Included by inline rule
    assert "Content A1" in stdout_text
    assert "dir_b/file_b1.py" in stdout_text # Still included (not txt)
    assert "file_root.txt" not in stdout_text # Excluded by inline !*.txt
    assert "dir_a/file_a2.log" not in stdout_text # Still excluded by root !*.log
    assert ".hidden_dir/" not in stdout_text # Still excluded by default
    # Note: Stderr assertion removed


@pytest.mark.asyncio
async def test_mcp_debug_explain(test_environment):
    """Test MCP read_context with debug_explain=True."""
    test_dir = test_environment
    tool_name = "read_context"
    arguments = { "path": test_dir, "debug_explain": True }
    result = await run_mcp_tool_call(tool_name, arguments)

    # Check stdout content (same as basic MCP test)
    assert isinstance(result, types.CallToolResult)
    assert not result.isError
    assert len(result.content) == 1 and isinstance(result.content[0], types.TextContent)
    stdout_text = result.content[0].text # Extract text content
    assert "file_root.txt" in stdout_text
    assert "Root file content" in stdout_text
    assert "dir_b/file_b1.py" in stdout_text
    assert "dir_a/file_a1.txt" not in stdout_text
    assert "binary_file.bin" not in stdout_text
    assert "dir_a/file_a2.log" not in stdout_text

    # Note: Stderr assertions removed as stdio_client doesn't easily expose server stderr.
    # The debug_explain flag should still cause the server to LOG the explanations,
    # but we can't easily verify them here via stderr capture with the SDK client.
    # We rely on the stdout check to ensure the tool ran correctly.
