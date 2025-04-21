# tests/test_utils_wsl.py
import sys
import os
import platform
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
import subprocess

# Add project root to sys.path to allow importing 'jinni'
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Conditional import based on platform
if platform.system() == "Windows":
    from jinni.utils import _translate_wsl_path, _find_wslpath, _get_default_wsl_distro, _build_unc_path

# --- Test Setup ---

# Mark all tests in this module to be skipped if not on Windows
pytestmark = pytest.mark.skipif(platform.system() != "Windows", reason="WSL tests require Windows host")

# Known path created by the CI workflow inside WSL
# This needs to exist for the tests to pass in the CI environment.
# We use the path relative to the repo root as seen from Windows host via UNC.
# Needs the distro name used in windows.yml (Ubuntu-22.04)
CI_WSL_DISTRO = "Ubuntu-22.04" # Matches windows.yml
CI_WSL_EXISTING_FILE_POSIX = "/home/runner/testproj/hello.txt"
CI_WSL_EXISTING_DIR_POSIX = "/home/runner/testproj"
CI_WSL_NONEXISTENT_POSIX = "/home/runner/no/such/path/exists"

# Helper to build the expected UNC path - mirrors _build_unc_path logic for test verification
def build_expected_unc(distro: str, posix_path: str) -> str:
    # Simplified version for testing - assumes valid inputs
    safe_distro = distro # Assume CI distro name is safe
    if not posix_path.startswith("/"):
        posix_path = "/" + posix_path
    return rf"\\wsl$\{safe_distro}{posix_path}".replace("/", "\\")

EXPECTED_UNC_FILE = build_expected_unc(CI_WSL_DISTRO, CI_WSL_EXISTING_FILE_POSIX)
EXPECTED_UNC_DIR = build_expected_unc(CI_WSL_DISTRO, CI_WSL_EXISTING_DIR_POSIX)

# --- Test Cases ---

@pytest.fixture(autouse=True)
def clear_caches():
    """Fixture to clear LRU caches before each test."""
    # Ensure functions exist before trying to clear cache (only relevant on Windows)
    if platform.system() == "Windows":
        _find_wslpath.cache_clear()
        _get_default_wsl_distro.cache_clear()
        # We don't directly import _cached_wsl_to_unc, but it's called by _translate_wsl_path
        # Need to import it specifically for cache clearing if that level is needed,
        # but clearing the top-level callers might suffice.
        # Let's assume clearing callers is enough for now.
        # If tests show interference, we might need `from jinni.utils import _cached_wsl_to_unc`
        # and `_cached_wsl_to_unc.cache_clear()` here.


def test_translate_valid_posix_path_file():
    """Test translation of an existing POSIX file path."""
    translated = _translate_wsl_path(CI_WSL_EXISTING_FILE_POSIX)
    # Manual construction is now always returned – existence is not guaranteed
    assert translated.lower() == EXPECTED_UNC_FILE.lower()


def test_translate_valid_posix_path_dir():
    """Test translation of an existing POSIX directory path."""
    translated = _translate_wsl_path(CI_WSL_EXISTING_DIR_POSIX)
    assert translated.lower() == EXPECTED_UNC_DIR.lower()
    assert translated.lower().startswith(r"\\wsl$".lower())


def test_translate_nonexistent_posix_path():
    """Test translation of a non-existent POSIX path.
       Should attempt wslpath, fail existence check, then try manual fallback.
       Manual fallback should also fail existence check, raising RuntimeError.
    """
    # We expect this to fail the Path(unc).exists() check inside _cached_wsl_to_unc
    # AND fail the Path(candidate_unc_path).exists() check in the manual fallback.
    with pytest.raises(RuntimeError, match=r"Cannot map POSIX path.*to Windows"): # Check for specific error
        _translate_wsl_path(CI_WSL_NONEXISTENT_POSIX)


def test_translate_valid_uri_file():
    """Test translation of a valid vscode-remote URI for an existing file."""
    uri = f"vscode-remote://wsl+{CI_WSL_DISTRO}{CI_WSL_EXISTING_FILE_POSIX}"
    translated = _translate_wsl_path(uri)
    assert translated.lower() == EXPECTED_UNC_FILE.lower()


def test_translate_valid_uri_localhost_file():
    """Test translation of a valid vscode-remote wsl.localhost URI."""
    uri = f"vscode-remote://wsl.localhost/{CI_WSL_DISTRO}{CI_WSL_EXISTING_FILE_POSIX}"
    translated = _translate_wsl_path(uri)
    assert translated.lower() == EXPECTED_UNC_FILE.lower()


def test_translate_valid_uri_alternate_scheme_file():
    """Test translation of a valid vscode://vscode-remote URI."""
    uri = f"vscode://vscode-remote/wsl+{CI_WSL_DISTRO}{CI_WSL_EXISTING_FILE_POSIX}"
    translated = _translate_wsl_path(uri)
    assert translated.lower() == EXPECTED_UNC_FILE.lower()


def test_translate_invalid_uri_missing_distro():
    """Test translation of vscode-remote URI missing the distro name."""
    uri = f"vscode-remote://wsl+{CI_WSL_EXISTING_FILE_POSIX}" # Missing distro
    with pytest.raises(ValueError, match="missing distro name"): # Different error type
        _translate_wsl_path(uri)


def test_translate_invalid_uri_localhost_missing_distro():
    """Test translation of wsl.localhost URI missing the distro name in path."""
    uri = f"vscode-remote://wsl.localhost{CI_WSL_EXISTING_FILE_POSIX}" # Distro missing from path
    with pytest.raises(ValueError, match="missing or invalid distro/path"): 
        _translate_wsl_path(uri)


def test_translate_non_wsl_uri():
    """Test that non-WSL URIs are returned unchanged."""
    uri = "file:///C:/Users/test/file.txt"
    assert _translate_wsl_path(uri) == uri


def test_translate_windows_path():
    """Test that standard Windows paths are returned unchanged."""
    path = "C:\\Users\\test\\file.txt"
    assert _translate_wsl_path(path) == path


def test_translate_unc_path():
    """Test that existing UNC paths (WSL or otherwise) are returned unchanged."""
    # Use the expected UNC path which should exist in CI
    assert _translate_wsl_path(EXPECTED_UNC_FILE) == EXPECTED_UNC_FILE
    # Test a generic UNC path
    generic_unc = "\\\\fileserver\\share\\file.txt"
    assert _translate_wsl_path(generic_unc) == generic_unc


# --- Tests for wslpath failure / manual fallback ---

@patch('jinni.utils._find_wslpath', return_value=None)
def test_translate_posix_no_wslpath_fallback_success(mock_find_wslpath):
    """Test manual fallback when wslpath isn't found, default distro works."""
    with patch('jinni.utils._get_default_wsl_distro', return_value=CI_WSL_DISTRO):
        translated = _translate_wsl_path(CI_WSL_EXISTING_FILE_POSIX)
        assert translated.lower() == EXPECTED_UNC_FILE.lower()
        mock_find_wslpath.assert_called_once()


@patch('jinni.utils._find_wslpath', return_value=None)
@patch('jinni.utils._get_default_wsl_distro', return_value=None)
def test_translate_posix_no_wslpath_no_distro_fails(mock_get_distro, mock_find_wslpath):
    """Test failure when wslpath and default distro are unavailable."""
    with pytest.raises(RuntimeError, match=r"Cannot map POSIX path.*to Windows"):
        _translate_wsl_path(CI_WSL_EXISTING_FILE_POSIX)
    mock_find_wslpath.assert_called_once()
    mock_get_distro.assert_called_once()


# Mock subprocess.check_output used by _cached_wsl_to_unc
@patch('subprocess.check_output')
def test_translate_posix_wslpath_fails_fallback_success(mock_check_output):
    """Test fallback when wslpath exists but fails (e.g., returns error)."""
    mock_check_output.side_effect = subprocess.CalledProcessError(1, 'wslpath', stderr='Forced error')
    with patch('jinni.utils._get_default_wsl_distro', return_value=CI_WSL_DISTRO):
        with patch('jinni.utils._find_wslpath', return_value="/fake/wslpath"):
            translated = _translate_wsl_path(CI_WSL_EXISTING_FILE_POSIX)
            # Should fall back to manual construction
            assert translated.lower() == EXPECTED_UNC_FILE.lower()
            # both -u and -w attempted
            assert mock_check_output.call_count >= 2
            mock_check_output.assert_any_call(['/fake/wslpath', '-u', '--', CI_WSL_EXISTING_FILE_POSIX], text=True, stderr=subprocess.PIPE, timeout=5)
            mock_check_output.assert_any_call(['/fake/wslpath', '-w', '--', CI_WSL_EXISTING_FILE_POSIX], text=True, stderr=subprocess.PIPE, timeout=5)


@patch('subprocess.check_output')
@patch('jinni.utils._get_default_wsl_distro', return_value=None)
def test_translate_posix_wslpath_fails_no_distro_fails(mock_get_distro, mock_check_output):
    """Test failure when wslpath fails and default distro is unavailable."""
    mock_check_output.side_effect = subprocess.CalledProcessError(1, 'wslpath', stderr='Forced error')

    with patch('jinni.utils._find_wslpath', return_value="/fake/wslpath"):
        with pytest.raises(RuntimeError, match=r"Cannot map POSIX path.*to Windows"):
            _translate_wsl_path(CI_WSL_EXISTING_FILE_POSIX)

        assert mock_check_output.call_count >= 2 # Should still try both flags
        mock_get_distro.assert_called_once() # Should attempt manual fallback 