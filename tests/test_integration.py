import unittest
from unittest import IsolatedAsyncioTestCase # Import the async test case base class
import os
import tempfile
import shutil
import subprocess
import json
import time
import sys
import asyncio # Added for async operations
# import pytest # Removed warning filtering import
# Assuming 'jinni' command or python -m jinni.cli is executable
# Determine the path to the jinni CLI script
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
JINNI_CLI_PATH = os.path.join(PROJECT_ROOT, 'jinni', 'cli.py')
JINNI_SERVER_PATH = os.path.join(PROJECT_ROOT, 'jinni', 'server.py')
PYTHON_EXECUTABLE = sys.executable # Use the same python interpreter running the tests

# Define TimeoutExpired for asyncio context if needed (or handle asyncio.TimeoutError directly)
# from asyncio import TimeoutError as AsyncTimeoutError # Alias if needed

class TestIntegration(IsolatedAsyncioTestCase): # Change base class

    def _create_test_structure(self, base_path):
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

    def setUp(self):
        """Set up a temporary directory with complex structure for testing."""
        self.test_dir = tempfile.mkdtemp()
        self._create_test_structure(self.test_dir)
        # Store the original working directory
        self.original_cwd = os.getcwd()
        # We run commands from PROJECT_ROOT, targeting self.test_dir,
        # so no need to chdir into self.test_dir itself.

    def tearDown(self):
        """Clean up the temporary directory."""
        # Change back to the original working directory
        os.chdir(self.original_cwd)
        shutil.rmtree(self.test_dir)

    def run_jinni_cli(self, args):
        """Helper function to run the jinni CLI."""
        command = [PYTHON_EXECUTABLE, JINNI_CLI_PATH] + args
        try:
            # Run in the project root so imports work, but pass target dir as arg
            result = subprocess.run(command, capture_output=True, text=True, check=True, cwd=PROJECT_ROOT, timeout=5) # Reduced timeout
            return result.stdout, result.stderr
        except subprocess.CalledProcessError as e:
            print(f"Error running Jinni CLI: {e}")
            print(f"Stdout: {e.stdout}")
            print(f"Stderr: {e.stderr}")
            raise
        except subprocess.TimeoutExpired as e:
            print(f"Timeout running Jinni CLI: {e}")
            print(f"Stdout: {e.stdout}")
            print(f"Stderr: {e.stderr}")
            raise

    async def run_jinni_mcp(self, request_json): # Made async
        """Helper function to run the jinni MCP server and send a request using asyncio."""
        command = [PYTHON_EXECUTABLE, JINNI_SERVER_PATH]
        process = None # Initialize process to None
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=PROJECT_ROOT
            )

            request_data = (json.dumps(request_json) + '\n').encode('utf-8')

            # Write request to stdin
            process.stdin.write(request_data)
            await process.stdin.drain()
            process.stdin.close() # Close stdin to signal end of input

            # Read stdout and stderr concurrently with timeout
            async def read_stream(stream):
                lines = []
                while True:
                    try:
                        line = await asyncio.wait_for(stream.readline(), timeout=5) # 5 sec timeout per line read
                        if not line:
                            break
                        lines.append(line.decode('utf-8').strip())
                    except asyncio.TimeoutError:
                        # If readline times out, assume no more output is coming
                        # print(f"Readline timed out for stream {stream}", file=sys.stderr)
                        break
                return "\n".join(lines)

            # Wait for stdout, stderr, and process exit concurrently
            try:
                 stdout_task = asyncio.create_task(read_stream(process.stdout))
                 stderr_task = asyncio.create_task(read_stream(process.stderr))
                 await asyncio.wait_for(process.wait(), timeout=5) # Wait for process exit with timeout

                 stdout_str = await stdout_task
                 stderr_str = await stderr_task
            except asyncio.TimeoutError:
                 # If process.wait() times out, try to read whatever streams produced
                 # print("Process wait timed out, attempting to read streams...", file=sys.stderr)
                 stdout_str = await stdout_task
                 stderr_str = await stderr_task
                 if process.returncode is None: # If still running, terminate
                     print("Terminating hung MCP server process after stream read attempt...", file=sys.stderr)
                     process.terminate()
                     await process.wait()
                 raise TimeoutError("MCP Server test timed out after 5 seconds (process wait)") from None

            # stdout_data, stderr_data = await asyncio.wait_for(
            #     process.communicate(input=request_data),
            #     timeout=5 # Reduced timeout to 5 seconds
            # )

            # Decode and parse response
            # stdout_str = stdout_data.decode('utf-8').strip() # Now read directly
            # stderr_str = stderr_data.decode('utf-8').strip() # Now read directly

            if not stdout_str:
                 # Check stderr for potential startup errors if stdout is empty
                 if process.returncode != 0:
                      raise Exception(f"MCP Server exited with code {process.returncode}. Stderr: {stderr_str}")
                 else:
                      # This case might happen if the server runs but sends no response before closing stdout
                      raise Exception(f"MCP Server returned empty stdout. Stderr: {stderr_str}")

            try:
                # Assuming server sends one JSON object then closes stdout/exits
                response_json = json.loads(stdout_str)
                return response_json, stderr_str # Return stderr along with response
            except json.JSONDecodeError as e:
                 print(f"Failed to decode JSON response: {stdout_str}")
                 print(f"Stderr: {stderr_str}")
                 raise Exception(f"MCP Server JSON Decode Error: {e} - Response: {stdout_str}") from e

        # except asyncio.TimeoutError: # Timeout handled within stream reading/process wait
        #     print("MCP Server communication timed out (5s).") # Corrected print message
        #     if process and process.returncode is None:
        #         print("Terminating hung MCP server process...")
        #         process.terminate()
        #         await process.wait() # Ensure termination
        #     raise TimeoutError("MCP Server test timed out after 5 seconds") from None # Corrected exception message
        except Exception as e:
            print(f"Error during MCP communication: {e}")
            # Ensure process is terminated if it exists and is running
            if process and process.returncode is None:
                 print("Terminating MCP server process due to exception...")
                 process.terminate()
                 await process.wait()
            raise
        finally:
            # Extra check to ensure termination if communicate didn't finish or errored early
            if process and process.returncode is None:
                print("Terminating MCP server process in finally block...")
                process.terminate()
                await process.wait()

    # --- CLI Tests (Remain synchronous) ---
    def test_cli_with_contextfiles(self):
        """Test CLI run respecting hierarchical .contextfiles."""
        stdout, stderr = self.run_jinni_cli([self.test_dir])
        self.assertIn("file_root.txt", stdout)
        self.assertIn("Root file content", stdout)
        self.assertIn("dir_b/file_b1.py", stdout)
        self.assertIn("# Python content B1", stdout)
        self.assertNotIn("dir_a/file_a1.txt", stdout)
        self.assertNotIn("Content A1", stdout)
        self.assertNotIn("dir_a/file_a2.log", stdout)
        self.assertNotIn("dir_b/sub_dir_b/file_sub_b.tmp", stdout)
        self.assertNotIn(".hidden_dir/hidden_file.txt", stdout)
        self.assertNotIn(".contextfiles", stdout)
        self.assertNotIn("binary_file.bin", stdout)
        self.assertEqual(stderr.strip(), "") # Stderr should be empty now

    def test_cli_list_only(self):
        """Test the --list-only CLI flag."""
        stdout, stderr = self.run_jinni_cli(['--list-only', self.test_dir])
        expected_files = [
            "file_root.txt",
            "dir_b/file_b1.py",
        ]
        actual_files = sorted([line.strip() for line in stdout.strip().splitlines()]) # Sort for reliable comparison
        self.assertListEqual(actual_files, sorted(expected_files), f"Expected {sorted(expected_files)}, got {actual_files}")
        self.assertNotIn("Root file content", stdout)
        self.assertNotIn("# Python content B1", stdout)
        self.assertEqual(stderr.strip(), "") # Stderr should be empty now

    def test_cli_global_config(self):
        """Test the --config CLI flag for global rules."""
        global_config_path = os.path.join(self.test_dir, "global_rules.contextfiles")
        with open(global_config_path, "w") as f:
            f.write("# Global Rules\n")
            f.write("*.log\n") # Include log files (overrides root exclude)
            f.write("!dir_b/\n") # Exclude dir_b entirely
        target_dir = self.test_dir
        stdout, stderr = self.run_jinni_cli(['--config', global_config_path, target_dir])
        self.assertIn("file_root.txt", stdout)
        self.assertNotIn("dir_a/file_a2.log", stdout) # Excluded by root !*.log, which has higher precedence than global *.log
        # self.assertIn("Content A2 Log", stdout) # Content won't be present if file is excluded
        self.assertNotIn("dir_b/file_b1.py", stdout) # Excluded by global !dir_b/
        self.assertNotIn("dir_a/file_a1.txt", stdout) # Excluded by local !file_a1.txt
        self.assertNotIn("dir_b/sub_dir_b/", stdout) # Excluded by global !dir_b/
        self.assertNotIn(".hidden_dir/", stdout) # Excluded by default
        # Check that the root .contextfiles is NOT included (it's hidden)
        self.assertNotIn("File: .contextfiles\n", stdout)
        self.assertIn("global_rules.contextfiles", stdout) # Config file itself is NOT automatically excluded
        self.assertEqual(stderr.strip(), "") # Stderr should be empty now

    def test_cli_debug_explain(self):
        """Test the --debug-explain CLI flag."""
        stdout, stderr = self.run_jinni_cli(['--debug-explain', self.test_dir])
        # Check stderr for expected explanation patterns
        # Check stderr for expected explanation patterns (using logger format)
        # Note: We check for substrings as the full stderr might contain many lines
        self.assertIn("DEBUG:jinni.core_logic:Checking File: file_root.txt -> Included by default (no matching rules)", stderr)
        self.assertIn("DEBUG:jinni.core_logic:Checking Dir : dir_a/ -> Included by default (no matching rules)", stderr)
        self.assertIn("DEBUG:jinni.core_logic:Checking File: dir_a/file_a1.txt -> Excluded by Local Rule (dir_a/.contextfiles): 'file_a1.txt'", stderr)
        self.assertIn("DEBUG:jinni.core_logic:Checking File: dir_a/file_a2.log -> Excluded by Local Rule (.contextfiles): '*.log'", stderr)
        self.assertIn("DEBUG:jinni.core_logic:Checking Dir : dir_b/ -> Included by default (no matching rules)", stderr)
        self.assertIn("DEBUG:jinni.core_logic:Checking File: dir_b/file_b1.py -> Included by default (no matching rules)", stderr)
        self.assertIn("DEBUG:jinni.core_logic:Checking Dir : dir_b/sub_dir_b/ -> Excluded by Local Rule (.contextfiles): 'dir_b/sub_dir_b/'", stderr)
        self.assertIn("DEBUG:jinni.core_logic:Checking File: binary_file.bin -> Included by default (no matching rules)", stderr)
        self.assertIn("DEBUG:jinni.core_logic:Skipping File: binary_file.bin -> Detected as binary", stderr)
        self.assertIn("DEBUG:jinni.core_logic:Checking Dir : .hidden_dir/ -> Excluded by Default Rule: '.*'", stderr)
        self.assertIn("DEBUG:jinni.core_logic:Checking File: .contextfiles -> Excluded by Default Rule: '.*'", stderr)

        # Check stdout is still correct (same as test_cli_with_contextfiles)
        self.assertIn("file_root.txt", stdout)
        self.assertIn("Root file content", stdout)
        self.assertIn("dir_b/file_b1.py", stdout)
        self.assertNotIn("dir_a/file_a1.txt", stdout)
        self.assertNotIn("binary_file.bin", stdout)
        self.assertNotIn("dir_a/file_a2.log", stdout)

    # --- MCP Tests (Now async) ---
    async def test_mcp_read_context_basic(self): # Made async
        """Test basic MCP read_context respecting .contextfiles."""
        request = {
            "tool_name": "read_context",
            "arguments": { "path": self.test_dir }
        }
        response, stderr = await self.run_jinni_mcp(request) # Use await

        self.assertIn("result", response) # FastMCP wraps result
        self.assertIsInstance(response["result"], str)
        stdout = response["result"]

        # Assertions (same as CLI test)
        self.assertIn("file_root.txt", stdout)
        self.assertIn("Root file content", stdout)
        self.assertIn("dir_b/file_b1.py", stdout)
        self.assertIn("# Python content B1", stdout)
        self.assertNotIn("dir_a/file_a1.txt", stdout)
        self.assertNotIn("Content A1", stdout)
        self.assertNotIn("dir_a/file_a2.log", stdout)
        self.assertNotIn("dir_b/sub_dir_b/file_sub_b.tmp", stdout)
        self.assertNotIn(".hidden_dir/hidden_file.txt", stdout)
        self.assertNotIn(".contextfiles", stdout)
        self.assertNotIn("binary_file.bin", stdout)
        # Check stderr from server process via stderr capture
        self.assertIn("Info: Skipping likely binary file: binary_file.bin", stderr)


    async def test_mcp_read_context_list_only(self): # Made async
        """Test MCP read_context with list_only=True."""
        request = {
            "tool_name": "read_context",
            "arguments": { "path": self.test_dir, "list_only": True }
        }
        response, stderr = await self.run_jinni_mcp(request) # Use await

        self.assertIn("result", response)
        self.assertIsInstance(response["result"], str) # list_only returns a newline-separated string
        stdout = response["result"]
        actual_files = sorted([line.strip() for line in stdout.strip().splitlines()])

        expected_files = sorted([
            "file_root.txt",
            "dir_b/file_b1.py",
        ])
        self.assertListEqual(actual_files, expected_files, f"Expected {expected_files}, got {actual_files}")
        self.assertIn("Info: Skipping likely binary file: binary_file.bin", stderr)


    async def test_mcp_read_context_inline_rules(self): # Made async
        """Test MCP read_context with inline rules overriding local."""
        request = {
            "tool_name": "read_context",
            "arguments": {
                "path": self.test_dir,
                "rules": [ "!*.txt", "dir_a/file_a1.txt" ] # Inline rules
            }
        }
        response, stderr = await self.run_jinni_mcp(request) # Use await

        self.assertIn("result", response)
        self.assertIsInstance(response["result"], str)
        stdout = response["result"]

        # Assertions based on inline rules precedence:
        self.assertIn("dir_a/file_a1.txt", stdout) # Included by inline rule
        self.assertIn("Content A1", stdout)
        self.assertIn("dir_b/file_b1.py", stdout) # Still included (not txt)
        self.assertNotIn("file_root.txt", stdout) # Excluded by inline !*.txt
        self.assertNotIn("dir_a/file_a2.log", stdout) # Still excluded by root !*.log
        self.assertNotIn(".hidden_dir/", stdout) # Still excluded by default
        self.assertIn("Info: Skipping likely binary file: binary_file.bin", stderr)


    async def test_mcp_debug_explain(self): # Made async
        """Test MCP read_context with debug_explain=True."""
        request = {
            "tool_name": "read_context",
            "arguments": { "path": self.test_dir, "debug_explain": True }
        }
        response, stderr = await self.run_jinni_mcp(request) # Use await

        # Check response structure and stdout content (same as basic MCP test)
        self.assertIn("result", response)
        self.assertIsInstance(response["result"], str)
        stdout = response["result"]
        self.assertIn("file_root.txt", stdout)
        self.assertIn("Root file content", stdout)
        self.assertIn("dir_b/file_b1.py", stdout)
        self.assertNotIn("dir_a/file_a1.txt", stdout)
        self.assertNotIn("binary_file.bin", stdout)
        self.assertNotIn("dir_a/file_a2.log", stdout)

        # Check stderr for expected explanation patterns (similar to CLI test)
        self.assertIn("Debug: Checking File: file_root.txt -> Included by default", stderr)
        self.assertIn("Debug: Checking Dir : dir_a/ -> Included by default", stderr)
        self.assertIn("Debug: Checking File: dir_a/file_a1.txt -> Excluded by Local Rule (dir_a/.contextfiles): 'file_a1.txt'", stderr)
        self.assertIn("Debug: Checking File: dir_a/file_a2.log -> Excluded by Local Rule (.contextfiles): '*.log'", stderr)
        self.assertIn("Debug: Checking Dir : dir_b/ -> Included by default", stderr)
        self.assertIn("Debug: Checking File: dir_b/file_b1.py -> Included by default", stderr)
        self.assertIn("Debug: Checking Dir : dir_b/sub_dir_b/ -> Excluded by Local Rule (.contextfiles): 'dir_b/sub_dir_b/'", stderr)
        self.assertIn("Debug: Checking File: binary_file.bin -> Included by default", stderr)
        self.assertIn("Debug: Skipping File: binary_file.bin -> Detected as binary", stderr)
        self.assertIn("Debug: Checking Dir : .hidden_dir/ -> Excluded by Default Rule: '**/.*'", stderr)
        self.assertIn("Debug: Checking File: .contextfiles -> Excluded by Default Rule: '**/.*'", stderr)


if __name__ == '__main__':
    # Note: Running unittest directly might not work well with async tests.
    # Use 'pytest' which handles asyncio tests (e.g., with pytest-asyncio).
    unittest.main()
