import os
import tempfile
import shutil
import subprocess
import json
import time
import sys
import asyncio
import pytest # Use pytest
import logging
from pathlib import Path # Use pathlib
from typing import List, Optional, Set, Tuple

# Attempt import, needed for testing the module that uses it
try:
    import pathspec
except ImportError:
    pytest.skip("pathspec library not found, skipping integration tests", allow_module_level=True)

from mcp import ClientSession, StdioServerParameters, types # MCP Client SDK
from mcp.client.stdio import stdio_client # MCP Client SDK

# Assuming 'jinni' command or python -m jinni.cli is executable
PROJECT_ROOT = Path(__file__).parent.parent.resolve() # Use pathlib
JINNI_CLI_PATH = PROJECT_ROOT / 'jinni' / 'cli.py'
JINNI_SERVER_PATH = PROJECT_ROOT / 'jinni' / 'server.py'
PYTHON_EXECUTABLE = sys.executable # Use the same python interpreter running the tests
CONTEXT_FILENAME = ".contextfiles" # Consistent filename

# Setup logger for test helpers if needed
logger = logging.getLogger("jinni.test_integration_helpers") # Renamed logger
if not logger.handlers and not logging.getLogger().handlers:
     logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')


# --- Helper Functions ---

def _create_test_structure(base_path: Path):
    """Creates the complex test directory structure with gitignore-style inclusion rules."""
    # Root level files and dirs
    (base_path / "file_root.txt").write_text("Root file content", encoding='utf-8')
    (base_path / "README.md").write_text("# Readme", encoding='utf-8')
    (base_path / "main.py").write_text("print('main')", encoding='utf-8')
    (base_path / ".hidden_root_file").write_text("Hidden Root", encoding='utf-8')
    (base_path / "temp.tmp").touch()
    (base_path / "root.log").write_text("Root log", encoding='utf-8')
    (base_path / "binary_file.bin").write_bytes(b"Some text\x00followed by a null byte.")

    # Root .contextfiles (Include specific files/dirs, exclude logs/tmp)
    (base_path / CONTEXT_FILENAME).write_text(
        "# Root context rules (gitignore-style inclusion)\n"
        "file_root.txt\n"      # Include root file
        "*.md\n"               # Include all markdown files recursively
        "main.py\n"            # Include main.py at root
        "src/\n"               # Include the src directory (and its contents unless excluded below)
        "dir_c/\n"             # Include dir_c
        "dir_e/\n"             # Include dir_e
        "dir_f/\n"             # Include dir_f
        "!*.log\n"             # Exclude all log files
        "!*.tmp\n"             # Exclude all temp files
        # Explicitly exclude dotfiles for testing robustness
        "!.contextfiles\n"
        "!*/.contextfiles\n"
        "!.hidden_root_file\n"
        "!src/.hidden_in_src\n"
        # Note: No explicit rule for dir_b, dir_d - they rely on default '*' inclusion now
        # Note: Binary files are excluded by core_logic check, not rules here.
        , encoding='utf-8'
    )

    # dir_a: Test local include/exclude, overriding root *.md exclusion if any
    dir_a = base_path / "dir_a"
    dir_a.mkdir(exist_ok=True)
    (dir_a / "file_a1.txt").write_text("Content A1", encoding='utf-8')
    (dir_a / "file_a2.log").write_text("Content A2 Log", encoding='utf-8') # Excluded by root !*.log
    (dir_a / "important.log").write_text("Important Log Content", encoding='utf-8') # Excluded by root !*.log unless overridden
    (dir_a / "local.md").write_text("Local MD", encoding='utf-8') # Included by root *.md
    (dir_a / CONTEXT_FILENAME).write_text(
        "# dir_a context rules\n"
        "*.txt\n"              # Include .txt files in dir_a
        "!file_a1.txt\n"       # BUT specifically exclude file_a1.txt
        "important.log\n"      # Include this specific log file (overrides root !*.log)
        "!local.md\n"          # Exclude local markdown (overrides root *.md)
        , encoding='utf-8'
    )

    # dir_b: Test including files in a directory NOT included by root rules
    dir_b = base_path / "dir_b"
    dir_b.mkdir(exist_ok=True)
    (dir_b / "file_b1.py").write_text("# Python content B1", encoding='utf-8') # Excluded (dir_b not included)
    sub_dir_b = dir_b / "sub_dir_b"
    sub_dir_b.mkdir(exist_ok=True)
    (sub_dir_b / "file_sub_b.tmp").touch() # Excluded (dir_b not included, and tmp excluded)
    (sub_dir_b / "include_me.txt").write_text("Include me content", encoding='utf-8') # Excluded (dir_b not included)
    (sub_dir_b / CONTEXT_FILENAME).write_text(
        "# sub_dir_b context rules\n"
        "include_me.txt\n"     # This rule won't apply if dir_b isn't included higher up
        , encoding='utf-8'
    )

    # dir_c: Test exclusion overriding parent inclusion (root includes dir_c/)
    dir_c = base_path / "dir_c"
    dir_c.mkdir(exist_ok=True)
    (dir_c / "file_c1.txt").write_text("Content C1", encoding='utf-8') # Included via root dir_c/
    (dir_c / "file_c2.data").write_text("Content C2 Data", encoding='utf-8') # Included via root dir_c/ unless excluded locally
    (dir_c / CONTEXT_FILENAME).write_text(
        "# dir_c context rules\n"
        "!*.data\n"            # Exclude .data files (overrides root dir_c/)
        , encoding='utf-8'
    )

    # dir_d: Test local inclusion when parent dir is not included by root
    dir_d = base_path / "dir_d"
    dir_d.mkdir(exist_ok=True)
    (dir_d / "file_d.txt").write_text("Content D", encoding='utf-8') # Excluded (dir_d not included)
    (dir_d / CONTEXT_FILENAME).write_text(
        "# dir_d context rules\n"
        "file_d.txt\n"         # This rule won't apply if dir_d isn't included higher up
        , encoding='utf-8'
    )

    # dir_e: Test last rule precedence (root includes dir_e/)
    dir_e = base_path / "dir_e"
    dir_e.mkdir(exist_ok=True)
    (dir_e / "last_rule.txt").write_text("Last Rule Content", encoding='utf-8') # Included via root dir_e/ unless excluded locally
    (dir_e / CONTEXT_FILENAME).write_text(
        "# dir_e context rules\n"
        "last_rule.txt\n"      # Include rule
        "!last_rule.txt\n"     # Exclude rule (takes precedence)
        , encoding='utf-8'
    )

    # dir_f: Test empty context file (root includes dir_f/)
    dir_f = base_path / "dir_f"
    dir_f.mkdir(exist_ok=True)
    (dir_f / "file_f.txt").write_text("Content F", encoding='utf-8') # Included via root dir_f/
    (dir_f / CONTEXT_FILENAME).write_text("", encoding='utf-8') # Empty file

    # src directory (included by root src/)
    src_dir = base_path / "src"
    src_dir.mkdir(exist_ok=True)
    (src_dir / "app.py").write_text("print('app')", encoding='utf-8')
    (src_dir / "utils.py").write_text("def helper(): pass", encoding='utf-8')
    (src_dir / "config.log").write_text("Src log", encoding='utf-8') # Excluded by root !*.log
    (src_dir / ".hidden_in_src").write_text("Hidden Src", encoding='utf-8') # Excluded by default

    # Lib directory (to be excluded)
    lib_dir = base_path / "lib"
    lib_dir.mkdir(exist_ok=True)
    (lib_dir / "somelib.py").write_text("# Library code", encoding='utf-8') # Create the missing file

    # Docs directory
    docs_dir = base_path / "docs"
    docs_dir.mkdir(exist_ok=True)
    (docs_dir / "index.md").write_text("Docs index", encoding='utf-8')
    (docs_dir / "config").mkdir(exist_ok=True)
    (docs_dir / "config" / "options.md").write_text("Config options", encoding='utf-8')

    # Nested directory to test hierarchy
    nested_dir = src_dir / "nested"
    nested_dir.mkdir(exist_ok=True)
    (src_dir / "nested" / "deep.py").write_text("# Deep", encoding='utf-8')
    (src_dir / "nested" / "data.log").write_text("Nested log", encoding='utf-8') # Excluded by root !*.log

    # Hidden dir (excluded by default)
    hidden_dir = base_path / ".hidden_dir"
    hidden_dir.mkdir(exist_ok=True)
    (hidden_dir / "hidden_file.txt").write_text("Hidden content", encoding='utf-8')


def run_jinni_cli(args: List[str]):
    """Helper function to run the jinni CLI."""
    command = [PYTHON_EXECUTABLE, str(JINNI_CLI_PATH)] + args
    try:
        # Run in the project root so imports work
        result = subprocess.run(command, capture_output=True, text=True, check=True, cwd=str(PROJECT_ROOT), timeout=10) # Increased timeout slightly
        # Print stderr for debugging purposes, especially when tests fail on stdout checks
        print(f"--- Captured Stderr ---\n{result.stderr}\n--- End Captured Stderr ---", file=sys.stderr)
        # Normalize stderr newlines for comparison
        stderr_normalized = "\n".join(result.stderr.splitlines())
        return result.stdout, stderr_normalized
    except subprocess.CalledProcessError as e:
        logger.error(f"Error running Jinni CLI: {e}")
        logger.error(f"CLI Stdout:\n{e.stdout}")
        logger.error(f"CLI Stderr:\n{e.stderr}")
        raise
    except subprocess.TimeoutExpired as e:
        logger.error(f"Timeout running Jinni CLI: {e}")
        logger.error(f"CLI Stdout:\n{e.stdout}")
        logger.error(f"CLI Stderr:\n{e.stderr}")
        raise

async def run_mcp_tool_call(tool_name: str, arguments: dict):
   """Helper function to run the jinni MCP server and call a tool."""
   server_params = StdioServerParameters(
       command=PYTHON_EXECUTABLE,
       args=["-m", "jinni.server"], # Run server as module
       cwd=str(PROJECT_ROOT),
   )
   logger.debug(f"Starting MCP server with command: {server_params.command} {' '.join(server_params.args)}")
   try:
       async with stdio_client(server_params) as (read, write):
           logger.debug("stdio_client connected.")
           async with ClientSession(read, write) as session:
               logger.debug("ClientSession created. Initializing...")
               init_response = await session.initialize()
               logger.debug(f"MCP Session Initialized: {init_response}")
               logger.debug(f"Calling tool '{tool_name}' with arguments: {arguments}")
               result = await session.call_tool(tool_name, arguments=arguments)
               logger.debug(f"Tool '{tool_name}' returned result: {type(result)}")
               return result
   except Exception as e:
       logger.error(f"Error during MCP client communication or tool call: {e}", exc_info=True)
       raise

# --- Pytest Fixture for Test Environment ---

@pytest.fixture(scope="function")
def test_environment(tmp_path_factory): # Use tmp_path_factory for unique base dir
    """Pytest fixture to set up and tear down the test directory structure."""
    # Create a base directory within the pytest tmp area
    base_dir = tmp_path_factory.mktemp("jinni_integration_test")
    logger.debug(f"Created test directory: {base_dir}")
    _create_test_structure(base_dir)
    original_cwd = os.getcwd()
    # Change to project root so jinni module can be found when run via python -m
    os.chdir(PROJECT_ROOT)
    yield base_dir # Provide the test directory path to the test function
    # Teardown: Change back and remove directory (handled by pytest tmp_path_factory)
    logger.debug(f"Cleaning up test directory: {base_dir}")
    os.chdir(original_cwd)