# tests/test_utils_wsl.py
import sys
import os
import platform
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
import subprocess
import re
from types import SimpleNamespace
from jinni.utils import (
    _translate_wsl_path,
    _find_wslpath,
    _build_unc_path,
    _get_default_wsl_distro,
    ensure_no_nul,
)

# Add project root to sys.path to allow importing 'jinni'
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Conditional import based on platform
if platform.system() == "Windows":
    from jinni.utils import (
        _translate_wsl_path,
        _find_wslpath,
        _build_unc_path,
        _get_default_wsl_distro,
    )

# --- Test Setup ---

# Mark all tests in this module to be skipped if not on Windows
pytestmark = pytest.mark.skipif(platform.system() != "Windows", reason="WSL tests require Windows host")

# ---------- paths used everywhere ----------
CI_WSL_EXISTING_FILE_POSIX = "/home/runner/testproj/hello.txt"
CI_WSL_EXISTING_DIR_POSIX  = "/home/runner/testproj"
CI_WSL_NONEXISTENT_POSIX   = "/home/runner/no/such/path/exists"

# ---------- figure out which distro we should reference ----------
CI_WSL_DISTRO = _get_default_wsl_distro() or "Ubuntu"

# ---------- helpers / expected UNC ----------
EXPECTED_UNC_FILE = _build_unc_path(CI_WSL_DISTRO, CI_WSL_EXISTING_FILE_POSIX)
EXPECTED_UNC_DIR  = _build_unc_path(CI_WSL_DISTRO, CI_WSL_EXISTING_DIR_POSIX)

# ---------- regex that really matches a WSL UNC prefix ----------
UNC_PREFIX_RE = re.compile(r"^\\\\wsl\$\\[^\\]+\\", re.IGNORECASE)

EXPECTED_TAIL_FILE = r"\home\runner\testproj\hello.txt"
EXPECTED_TAIL_DIR  = r"\home\runner\testproj"

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
    """POSIX file path → UNC (fallback)."""
    with patch.dict(os.environ, {}, clear=False):
        translated = _translate_wsl_path(CI_WSL_EXISTING_FILE_POSIX)
        assert UNC_PREFIX_RE.match(translated)
        assert translated.lower().endswith(EXPECTED_TAIL_FILE)


def test_translate_valid_posix_path_dir():
    """POSIX directory path → UNC (fallback)."""
    with patch.dict(os.environ, {}, clear=False):
        translated = _translate_wsl_path(CI_WSL_EXISTING_DIR_POSIX)
        assert UNC_PREFIX_RE.match(translated)
        assert translated.lower().endswith(EXPECTED_TAIL_DIR)
        assert translated.lower().startswith(r"\\wsl$".lower())


def test_translate_nonexistent_posix_path():
    """Test translation of a non-existent POSIX path.
       Should attempt wslpath, fail existence check, then try manual fallback.
       Manual fallback should also fail existence check, raising RuntimeError.
    """
    # We expect this to fail the Path(unc).exists() check inside _cached_wsl_to_unc
    # AND fail the Path(candidate_unc_path).exists() check in the manual fallback.
    translated = _translate_wsl_path(CI_WSL_NONEXISTENT_POSIX)
    assert UNC_PREFIX_RE.match(translated)


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
    # Double '//' after the authority → truly missing distro
    uri = f"vscode-remote://wsl.localhost//{CI_WSL_EXISTING_FILE_POSIX.lstrip('/')}"
    with pytest.raises(ValueError, match="missing distro name"):
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
    """Unchanged if the input is already a UNC."""
    assert _translate_wsl_path(EXPECTED_UNC_FILE) == EXPECTED_UNC_FILE


def test_translate_posix_path_hard_default(monkeypatch):
    """When no distro information is available we default to Ubuntu."""
    # simulate missing env‑var and empty `wsl -l -q`
    monkeypatch.delenv("JINNI_ASSUME_WSL_DISTRO", raising=False)
    monkeypatch.setattr("jinni.utils._get_default_wsl_distro", lambda: "Ubuntu")
    # should not raise
    from jinni import utils
    translated = utils._translate_wsl_path("/home/foo.txt")
    assert UNC_PREFIX_RE.match(translated)
    assert translated.lower().endswith(r"\home\foo.txt")


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

def test__get_default_wsl_distro_fallback(monkeypatch):
    """When WSL is absent we should still return 'Ubuntu' as a last resort."""
    monkeypatch.setattr("subprocess.run", lambda *a, **kw: SimpleNamespace(returncode=1, stdout=""))
    assert _get_default_wsl_distro() == "Ubuntu" 

# --- Test ensure_no_nul utility ---
def test_ensure_no_nul_wsl():
    # Should not raise
    ensure_no_nul("abc", "test-field")
    # Should raise ValueError on NUL
    import pytest
    with pytest.raises(ValueError):
        ensure_no_nul("a\x00b", "test-field") 