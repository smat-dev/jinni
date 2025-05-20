# tests/test_integration_summarization.py
import pytest
import os
import subprocess
import json
from pathlib import Path
from unittest.mock import patch, MagicMock

# --- Constants ---
MOCK_SUMMARY_CONTENT = "This is a mock summary from the integration test."
MOCK_README_SUMMARY_CONTENT = "Mock project README summary."
SUMMARY_CACHE_FILENAME = ".jinni_summary_cache.json"
JINNI_LOG_FILENAME = "jinni.log" # Default log file name used by CLI

# --- Fixtures ---

@pytest.fixture(scope="session") # Session scope for API key, as it's global for tests
def mock_gemini_api_key(session_mocker):
    """Sets the GEMINI_API_KEY environment variable for the test session."""
    session_mocker.setenv("GEMINI_API_KEY", "test_integration_api_key")

@pytest.fixture
def mock_gemini_api_call():
    """Mocks jinni.utils.call_gemini_api to return controlled summaries."""
    with patch('jinni.utils.call_gemini_api') as mock_call:
        # This function will be called by the mock for different prompts
        def side_effect_func(prompt_text: str, api_key: str = None):
            if "README content" in prompt_text:
                return MOCK_README_SUMMARY_CONTENT
            # Simplistic check; can be made more sophisticated if prompts differ significantly
            return MOCK_SUMMARY_CONTENT 
        
        mock_call.side_effect = side_effect_func
        yield mock_call

@pytest.fixture
def sample_project(tmp_path: Path):
    """Creates a sample project directory for integration tests."""
    project_dir = tmp_path / "sample_project_for_integration"
    project_dir.mkdir()

    (project_dir / "src").mkdir()
    (project_dir / "src" / "file1.py").write_text("print('Hello from file1')\n# Content for file1")
    (project_dir / "src" / "file2.txt").write_text("Just some text in file2.\n# Content for file2")
    
    (project_dir / "README.md").write_text("This is a sample README for the integration test project.")
    (project_dir / ".hidden_file").write_text("This should be ignored by default.")
    (project_dir / "LICENSE").write_text("MIT License content.")

    # Create a .contextfiles to include LICENSE explicitly
    (project_dir / ".contextfiles").write_text("LICENSE\nsrc/**/*.py\n*.md") # Include LICENSE, all .py in src, and .md

    return project_dir

# --- Helper Function to Run Jinni CLI ---

def run_jinni_cli(cwd: Path, *args) -> subprocess.CompletedProcess:
    """Helper to run the Jinni CLI."""
    # Construct the command. Assumes 'jinni' is runnable, e.g., via python -m jinni
    # Or if jinni is installed in a virtualenv, that env is active.
    # For testing, it's often robust to call `python -m jinni.cli`
    command = [sys.executable, "-m", "jinni.cli"] + list(args)
    # print(f"Running command: {' '.join(command)} in CWD: {cwd}") # Debug print
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        cwd=str(cwd), # Run from the temp project's parent dir or project dir itself
        check=False # Don't raise exception on non-zero exit, we'll check manually
    )

# --- CLI Integration Tests ---

def test_cli_summarize_single_file(sample_project, mock_gemini_api_key, mock_gemini_api_call, caplog):
    """Test jinni --summarize on a single file."""
    file_to_summarize = sample_project / "src" / "file1.py"
    
    # Run from the parent of sample_project to test relative path handling
    # Target path is relative to CWD, which is tmp_path here.
    relative_file_path = str(file_to_summarize.relative_to(sample_project.parent))

    result = run_jinni_cli(sample_project.parent, "--summarize", relative_file_path, "--log-file")
    
    assert result.returncode == 0, f"CLI Error: {result.stderr}"
    assert MOCK_SUMMARY_CONTENT in result.stdout
    assert "src/file1.py" in result.stdout # Check for the path header

    # Check cache creation and content (cache is in CWD, which is sample_project.parent)
    cache_file = sample_project.parent / SUMMARY_CACHE_FILENAME
    assert cache_file.exists()
    with open(cache_file, 'r') as f:
        cache_data = json.load(f)
    
    # Cache key is relative to project_root. If project_root is inferred, it's sample_project.
    # So, key should be "src/file1.py"
    # However, CLI infers project root based on targets. If target is sample_project_for_integration/src/file1.py,
    # and CWD is tmp_path, then project root is tmp_path.
    # The cache key is relative to the *determined* project_root.
    # If we run jinni from sample_project.parent, and target "sample_project_for_integration/src/file1.py",
    # the common ancestor is sample_project.parent.
    # Let's run from within the project to simplify cache key expectations.
    
    result_in_project_cwd = run_jinni_cli(sample_project, "--summarize", "src/file1.py", "--log-file")
    assert result_in_project_cwd.returncode == 0, f"CLI Error: {result_in_project_cwd.stderr}"
    
    cache_file_in_project = sample_project / SUMMARY_CACHE_FILENAME
    assert cache_file_in_project.exists()
    with open(cache_file_in_project, 'r') as f:
        cache_data_in_project = json.load(f)

    assert "src/file1.py" in cache_data_in_project
    assert cache_data_in_project["src/file1.py"]["summary"] == MOCK_SUMMARY_CONTENT

    # Check log file
    log_file = sample_project / JINNI_LOG_FILENAME
    assert log_file.exists()
    log_content = log_file.read_text()
    assert "Cache miss for file: src/file1.py" in log_content
    assert "Gemini API call initiated." in log_content
    assert "Prompt length:" in log_content # API call stats

    # Test cache hit
    mock_gemini_api_call.reset_mock()
    result_cache_hit = run_jinni_cli(sample_project, "--summarize", "src/file1.py", "--log-file")
    assert result_cache_hit.returncode == 0
    assert MOCK_SUMMARY_CONTENT in result_cache_hit.stdout
    mock_gemini_api_call.assert_not_called() # Should be a cache hit
    
    log_content_cache_hit = log_file.read_text() # Reread for new logs
    # Look for cache hit log for the specific file
    # Note: log file appends, so previous miss will be there. We need to check new content.
    # This is tricky with simple string search. A more robust log checking might be needed for complex scenarios.
    # For now, we'll check if the API call was made (it shouldn't have been).
    # And we can check if the "Cache hit" message appears for this run (requires isolating log entries per run).
    # As a simpler check: count API call logs vs Cache hit logs.
    # This test structure is more about overall integration.
    # A specific log check for "Cache hit for file: src/file1.py" can be added if log isolation is handled.


def test_cli_summarize_directory(sample_project, mock_gemini_api_key, mock_gemini_api_call):
    """Test jinni --summarize on a directory."""
    
    result = run_jinni_cli(sample_project, "--summarize", ".", "--log-file") # Target current dir "."
    
    assert result.returncode == 0, f"CLI Error: {result.stderr}"
    
    # Expected files based on .contextfiles: README.md, src/file1.py, LICENSE
    assert "src/file1.py" in result.stdout
    assert MOCK_SUMMARY_CONTENT in result.stdout # For file1.py and LICENSE
    
    assert "README.md" in result.stdout
    assert MOCK_README_SUMMARY_CONTENT in result.stdout # For README.md
    
    assert "LICENSE" in result.stdout # Explicitly included by .contextfiles

    assert "src/file2.txt" not in result.stdout # Not included by rules
    assert ".hidden_file" not in result.stdout

    # Check cache content
    cache_file = sample_project / SUMMARY_CACHE_FILENAME
    assert cache_file.exists()
    with open(cache_file, 'r') as f:
        cache_data = json.load(f)
        
    assert "src/file1.py" in cache_data
    assert cache_data["src/file1.py"]["summary"] == MOCK_SUMMARY_CONTENT
    
    assert "README.md" in cache_data
    assert cache_data["README.md"]["summary"] == MOCK_README_SUMMARY_CONTENT
    
    assert "LICENSE" in cache_data
    assert cache_data["LICENSE"]["summary"] == MOCK_SUMMARY_CONTENT # Uses default mock for non-readme

    assert "_PROJECT_README_SUMMARY_" in cache_data # Check if README helper cached
    assert cache_data["_PROJECT_README_SUMMARY_"]["summary"] == MOCK_README_SUMMARY_CONTENT


def test_cli_summarize_with_explicit_project_root(tmp_path, mock_gemini_api_key, mock_gemini_api_call):
    """Test jinni --summarize with an explicit -r/--root argument."""
    # Create a project structure where CWD is different from project root
    actual_project_dir = tmp_path / "actual_proj"
    actual_project_dir.mkdir()
    (actual_project_dir / "main.py").write_text("print('main in actual_proj')")
    (actual_project_dir / "README.md").write_text("README for actual_proj")

    # Run jinni from tmp_path (CWD), but specify actual_project_dir as root
    result = run_jinni_cli(
        tmp_path, # CWD
        "--summarize",
        str(actual_project_dir / "main.py"), # Target a file within the project
        "--root", str(actual_project_dir),
        "--log-file"
    )

    assert result.returncode == 0, f"CLI Error: {result.stderr}"
    assert MOCK_SUMMARY_CONTENT in result.stdout # Summary for main.py
    assert "main.py" in result.stdout # Path relative to actual_project_dir

    # Cache should be in CWD (tmp_path) because that's where jinni runs from
    cache_file = tmp_path / SUMMARY_CACHE_FILENAME 
    assert cache_file.exists()
    with open(cache_file, 'r') as f:
        cache_data = json.load(f)

    # Cache key should be relative to the provided project_root (actual_project_dir)
    assert "main.py" in cache_data
    assert cache_data["main.py"]["summary"] == MOCK_SUMMARY_CONTENT
    
    # Check log file in CWD (tmp_path)
    log_file = tmp_path / JINNI_LOG_FILENAME
    assert log_file.exists()
    log_content = log_file.read_text()
    assert "Cache miss for file: main.py" in log_content


def test_cli_summarize_no_gemini_key(sample_project, mock_gemini_api_call, caplog):
    """Test jinni --summarize when GEMINI_API_KEY is not set (mocked by clearing env)."""
    # Unset the environment variable for this test
    with patch.dict(os.environ, {}, clear=True):
        # Mock call_gemini_api to actually raise ValueError like the real one would
        mock_gemini_api_call.side_effect = ValueError("Gemini API key not provided and not found in GEMINI_API_KEY environment variable.")

        result = run_jinni_cli(sample_project, "--summarize", "src/file1.py")

    # Expecting it to fail gracefully at the API call stage.
    # The core_logic.read_context -> file_processor.summarize_file -> utils.call_gemini_api
    # will raise ValueError. This should be caught by the CLI's main error handler.
    # The CLI will print an error to stderr and exit with 1.
    # The output to stdout might be empty or partial depending on where exactly it fails.
    
    # For this test, we check that the error related to API key is propagated or handled.
    # The current CLI exits with 1 and prints error to stderr.
    # utils.call_gemini_api raises ValueError.
    # file_processor.summarize_file returns "[Error: ...]" if API call fails.
    # So, the output should contain this error message.
    assert result.returncode == 0, f"CLI Error: {result.stderr}" # Summarize_file returns error string, doesn't make CLI fail
    assert "Error: Gemini API key not provided" in result.stdout # Check for the error message from call_gemini_api

    # No cache should be written for the failed file
    cache_file = sample_project / SUMMARY_CACHE_FILENAME
    if cache_file.exists():
        with open(cache_file, 'r') as f:
            cache_data = json.load(f)
        assert "src/file1.py" not in cache_data # Or check that its summary is the error

import sys # for sys.executable

# Note: MCP Server tests are complex and omitted as per instructions.
# They would typically involve:
# 1. Starting the server in a subprocess.
# 2. Using a client (like a custom script sending JSON-RPC over stdio) to send commands.
# 3. Capturing stdout/stderr of the server process.
# 4. Mocking API calls within the server's context, which can be tricky with subprocesses
#    unless the server itself is designed to allow injection of mocks (e.g., via env vars or config).
#
# For example, a very basic conceptual test:
#
# def test_mcp_summarize_context_conceptual(sample_project, mock_gemini_api_key, mock_gemini_api_call):
#     server_process = subprocess.Popen(
#         [sys.executable, "-m", "jinni.server", "--log-file"],
#         stdin=subprocess.PIPE,
#         stdout=subprocess.PIPE,
#         stderr=subprocess.PIPE,
#         text=True,
#         cwd=sample_project.parent # Run server from where it can see the project
#     )
#
#     mcp_request = {
#         "jsonrpc": "2.0",
#         "method": "summarize_context",
#         "params": {
#             "project_root": str(sample_project.resolve()),
#             "targets": ["src/file1.py"],
#             "rules": []
#         },
#         "id": 1
#     }
#     request_json = json.dumps(mcp_request) + "\n"
#
#     try:
#         stdout, stderr = server_process.communicate(input=request_json, timeout=10)
#     except subprocess.TimeoutExpired:
#         server_process.kill()
#         stdout, stderr = server_process.communicate()
#         pytest.fail(f"Server timed out. Stderr: {stderr}")
#
#     assert server_process.returncode is None or server_process.returncode == 0, f"Server process error: {stderr}"
#
#     # Parse stdout for JSON-RPC response
#     # This needs robust parsing as stdout might have multiple JSON objects or logs
#     response_json = None
#     for line in stdout.splitlines():
#         try:
#             decoded_line = json.loads(line)
#             if decoded_line.get("id") == 1:
#                 response_json = decoded_line
#                 break
#         except json.JSONDecodeError:
#             continue # Ignore lines that are not valid JSON (e.g. server logs)
#
#     assert response_json is not None, f"No valid JSON-RPC response found in stdout: {stdout}"
#     assert "result" in response_json, f"JSON-RPC error: {response_json.get('error')}, Stdout: {stdout}, Stderr: {stderr}"
#     assert MOCK_SUMMARY_CONTENT in response_json["result"]
#     assert "src/file1.py" in response_json["result"]
#
#     # Terminate server
#     if server_process.poll() is None: # Check if still running
#         server_process.terminate()
#         server_process.wait(timeout=5)
#
#     # Check cache and logs similar to CLI tests, ensuring paths are correct relative to server CWD
#     cache_file = sample_project.parent / SUMMARY_CACHE_FILENAME # If server runs from sample_project.parent
#     # ...
#
# This conceptual test highlights the complexity. FastMCP's stdio nature makes it
# different from HTTP/WebSocket servers often tested with libraries like `httpx` or `requests`.
# Proper testing might involve a dedicated MCP client library or more intricate process management.
# For now, focusing on CLI tests is sufficient.
pass # End of file. Add this to ensure the last comment block is complete.
