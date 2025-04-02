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

async def run_jinni_mcp(request_json):
    """
    Helper function to run the jinni MCP server, send a single request,
    read the JSON response using communicate(), and return results.
    """
    # Run server as a module to ensure consistent path handling
    command = [PYTHON_EXECUTABLE, "-m", "jinni.server"]
    process = None
    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=PROJECT_ROOT
        )
        logger.debug(f"MCP server process created with PID: {process.pid}")

        request_data = (json.dumps(request_json) + '\n').encode('utf-8')
        logger.debug(f"Sending request to MCP server: {request_data.decode()}")

        # Write request to stdin
        process.stdin.write(request_data)
        await process.stdin.drain()
        logger.debug("Request sent.")
        # process.stdin.close() # REMOVED - Keep stdin open for now

        # Read response from stdout line by line with timeout
        response_lines = []
        stderr_lines = []
        response_json = None
        stderr_str = ""

        async def read_stream(stream, lines_list, stream_name):
            """Helper to read lines from a stream."""
            while True:
                try:
                    line = await asyncio.wait_for(stream.readline(), timeout=0.1) # Short timeout for each line read
                    if not line:
                        logger.debug(f"{stream_name} stream ended.")
                        break
                    decoded_line = line.decode('utf-8', errors='ignore').strip()
                    logger.debug(f"Read from {stream_name}: {decoded_line}")
                    lines_list.append(decoded_line)
                except asyncio.TimeoutError:
                    # No more data on this stream for now
                    break
                except Exception as e:
                    logger.error(f"Error reading {stream_name}: {e}")
                    break

        async def read_output(timeout=5.0):
            """Read stdout and stderr concurrently."""
            nonlocal response_json, stderr_str
            start_time = time.monotonic()
            stdout_task = None
            stderr_task = None
            try:
                while time.monotonic() - start_time < timeout:
                    # Start or restart read tasks if not running or finished
                    if stdout_task is None or stdout_task.done():
                         if process.stdout:
                              stdout_task = asyncio.create_task(read_stream(process.stdout, response_lines, "stdout"))
                         else: stdout_task = asyncio.Future(); stdout_task.set_result(None) # Dummy task if no stdout

                    if stderr_task is None or stderr_task.done():
                         if process.stderr:
                              stderr_task = asyncio.create_task(read_stream(process.stderr, stderr_lines, "stderr"))
                         else: stderr_task = asyncio.Future(); stderr_task.set_result(None) # Dummy task if no stderr

                    # Wait for either task to complete or a short delay
                    done, pending = await asyncio.wait(
                        [stdout_task, stderr_task],
                        timeout=0.2, # Check frequently
                        return_when=asyncio.FIRST_COMPLETED
                    )

                    # Try to parse stdout if it has content
                    stdout_full = "\n".join(response_lines).strip()
                    if stdout_full:
                        try:
                            response_json = json.loads(stdout_full)
                            logger.debug("Successfully parsed JSON response from stdout.")
                            # Got the full response, stop reading
                            return
                        except json.JSONDecodeError:
                            # Incomplete JSON, keep reading
                            logger.debug("Incomplete JSON received, continuing read...")
                            pass # Continue loop

                    # Check if process exited unexpectedly
                    if process.returncode is not None:
                        logger.warning(f"MCP Server process exited unexpectedly with code {process.returncode} during read.")
                        break # Exit read loop

                    # If no tasks completed and timeout not reached, continue loop
                    if not done and time.monotonic() - start_time < timeout:
                         continue

                    # If both tasks are done and we still haven't parsed JSON, break
                    if stdout_task.done() and stderr_task.done() and response_json is None:
                         logger.warning("Both streams closed but no complete JSON response found.")
                         break

                # If loop finishes due to timeout
                if response_json is None and time.monotonic() - start_time >= timeout:
                    stderr_str = "\n".join(stderr_lines).strip()
                    logger.error(f"Timeout ({timeout}s) waiting for MCP response.")
                    logger.error(f"Partial stdout received: {'\n'.join(response_lines)}")
                    logger.error(f"Partial stderr received: {stderr_str}")
                    raise TimeoutError(f"MCP Server test timed out after {timeout}s waiting for JSON response")

            finally:
                # Ensure tasks are cancelled if read_output exits
                if stdout_task and not stdout_task.done(): stdout_task.cancel()
                if stderr_task and not stderr_task.done(): stderr_task.cancel()
                # Wait briefly for cancellation to propagate
                await asyncio.sleep(0.01)


        await read_output(timeout=5.0) # Use the 5-second timeout

        stderr_str = "\n".join(stderr_lines).strip()
        logger.debug(f"MCP stderr final: {stderr_str}")

        if response_json is None:
             # This case should ideally be caught by the timeout, but as a fallback:
             raise Exception(f"MCP Server did not return a valid JSON response. Stderr: {stderr_str}")

        return response_json, stderr_str

    except Exception as e:
        logger.error(f"Error during MCP communication: {e}", exc_info=True)
        if process and process.returncode is None:
             logger.warning("Terminating MCP server process due to exception...")
             process.terminate()
             await process.wait()
        raise
    finally:
        # Close stdin if it's still open before terminating
        if process and process.stdin and not process.stdin.is_closing():
             try:
                  logger.debug("Closing server stdin in finally block...")
                  process.stdin.close()
                  await process.stdin.wait_closed() # Ensure it's closed
             except Exception as close_err:
                  logger.error(f"Error closing stdin in finally: {close_err}")

        # Terminate the process if it's still running
        if process and process.returncode is None:
            logger.warning("Ensuring MCP server process termination in finally block...")
            try:
                process.terminate()
                # Wait for termination with a timeout
                await asyncio.wait_for(process.wait(), timeout=2.0)
                logger.debug("MCP server process terminated successfully after wait.")
            except asyncio.TimeoutError:
                logger.error("Timeout (2s) waiting for MCP server process to terminate gracefully. Forcing kill.")
                try:
                    process.kill()
                    await process.wait() # Wait for kill to complete
                    logger.debug("MCP server process killed successfully.")
                except ProcessLookupError:
                     logger.warning("Process already gone when attempting kill.")
                except Exception as kill_e:
                     logger.error(f"Error during process kill: {kill_e}")
            except ProcessLookupError:
                 logger.warning("Process already terminated before finally block's explicit wait.")
            except Exception as e:
                 logger.error(f"Error during final process termination attempt: {e}")

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
    request = {
        "tool_name": "read_context",
        "arguments": { "path": test_dir }
    }
    response, stderr = await run_jinni_mcp(request)

    assert "result" in response # FastMCP wraps result
    assert isinstance(response["result"], str)
    stdout = response["result"]

    # Assertions (same as CLI test)
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
    # Check stderr from server process via stderr capture
    # Note: stderr from server might include logging setup messages now
    assert "INFO:jinni.core_logic:Skipping likely binary file: binary_file.bin" in stderr


@pytest.mark.asyncio
async def test_mcp_read_context_list_only(test_environment):
    """Test MCP read_context with list_only=True."""
    test_dir = test_environment
    request = {
        "tool_name": "read_context",
        "arguments": { "path": test_dir, "list_only": True }
    }
    response, stderr = await run_jinni_mcp(request)

    assert "result" in response
    assert isinstance(response["result"], str) # list_only returns a newline-separated string
    stdout = response["result"]
    actual_files = sorted([line.strip() for line in stdout.strip().splitlines()])

    expected_files = sorted([
        "file_root.txt",
        "dir_b/file_b1.py",
    ])
    assert actual_files == expected_files, f"Expected {expected_files}, got {actual_files}"
    assert "INFO:jinni.core_logic:Skipping likely binary file: binary_file.bin" in stderr


@pytest.mark.asyncio
async def test_mcp_read_context_inline_rules(test_environment):
    """Test MCP read_context with inline rules overriding local."""
    test_dir = test_environment
    request = {
        "tool_name": "read_context",
        "arguments": {
            "path": test_dir,
            "rules": [ "!*.txt", "dir_a/file_a1.txt" ] # Inline rules
        }
    }
    response, stderr = await run_jinni_mcp(request)

    assert "result" in response
    assert isinstance(response["result"], str)
    stdout = response["result"]

    # Assertions based on inline rules precedence:
    assert "dir_a/file_a1.txt" in stdout # Included by inline rule
    assert "Content A1" in stdout
    assert "dir_b/file_b1.py" in stdout # Still included (not txt)
    assert "file_root.txt" not in stdout # Excluded by inline !*.txt
    assert "dir_a/file_a2.log" not in stdout # Still excluded by root !*.log
    assert ".hidden_dir/" not in stdout # Still excluded by default
    assert "INFO:jinni.core_logic:Skipping likely binary file: binary_file.bin" in stderr


@pytest.mark.asyncio
async def test_mcp_debug_explain(test_environment):
    """Test MCP read_context with debug_explain=True."""
    test_dir = test_environment
    request = {
        "tool_name": "read_context",
        "arguments": { "path": test_dir, "debug_explain": True }
    }
    response, stderr = await run_jinni_mcp(request)

    # Check response structure and stdout content (same as basic MCP test)
    assert "result" in response
    assert isinstance(response["result"], str)
    stdout = response["result"]
    assert "file_root.txt" in stdout
    assert "Root file content" in stdout
    assert "dir_b/file_b1.py" in stdout
    assert "dir_a/file_a1.txt" not in stdout
    assert "binary_file.bin" not in stdout
    assert "dir_a/file_a2.log" not in stdout

    # Check stderr for expected explanation patterns (similar to CLI test)
    # Note: stderr from server might include logging setup messages now
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
