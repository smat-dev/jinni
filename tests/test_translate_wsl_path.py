import pytest
import os # Added os for environ manipulation
import platform
import subprocess
import shutil
from urllib.parse import urlparse, ParseResult, quote # Added quote
from typing import Optional # Added Optional
from jinni.utils import _translate_wsl_path, _find_wslpath, _cached_wsl_to_unc, _get_default_wsl_distro # Import new helpers
from functools import lru_cache # Import lru_cache
import platform as real_platform
from jinni.utils import ensure_no_nul

# --- Test Cases for _translate_wsl_path ---

# Helper to mock platform.system
def mock_platform_system(system_name="Windows"):
    def func():
        return system_name.capitalize() # Ensure consistent capitalization
    return func

# Helper to mock urlparse
def mock_urlparse(scheme="vscode-remote", netloc="wsl+Ubuntu", path="/home/user/project"):
    # Return a simple object that mimics ParseResult enough for the function
    class MockParseResult:
        def __init__(self, scheme, netloc, path):
            self.scheme = scheme
            self.netloc = netloc
            self.path = path
    return lambda url_str: MockParseResult(scheme, netloc, path)

# --- Mocks for new internal functions ---

# Mock _find_wslpath
def mock_find_wslpath(path: Optional[str] = "/fake/wslpath"):
    @lru_cache(maxsize=1)
    def func():
        return path
    return func

# Mock _cached_wsl_to_unc
def mock_cached_wsl_to_unc(win_path: Optional[str], fail_path: Optional[str] = None):
    @lru_cache(maxsize=256)
    def func(wslpath_exe, posix_path):
        if fail_path is not None and posix_path == fail_path:
            return None # Simulate failure for a specific path
        return win_path # Return success path otherwise
    return func

# Mock for _get_default_wsl_distro
def mock_get_default_wsl_distro(distro_name: Optional[str]):
    @lru_cache(maxsize=1)
    def func():
        return distro_name
    return func

# Mock for pathlib.Path().exists() used in fallback
class MockPathExists:
    def __init__(self, path_str):
        self.path_str = str(path_str) # Ensure it's a string

    def exists(self):
        # This mock is specifically for the fallback logic.
        # It should return True only if the path being checked matches
        # the manually constructed UNC path expected in a fallback scenario.
        # We need to know the expected fallback path for the current test case.
        # This is tricky to do generically here. Instead, we'll rely on
        # specific mocking within the tests that need fallback verification.
        # By default, return False for simplicity in tests not explicitly testing fallback success.
        print(f"DEBUG: MockPathExists.exists called for: {self.path_str}") # Debug print
        return False

# --- Existing Simple Tests (Adapt if needed) ---

def test_translate_windows_path_no_change(monkeypatch):
    """Test a Windows path is not translated on Windows."""
    monkeypatch.setattr(platform, "system", mock_platform_system("Windows"))
    win_path = "C:\\Users\\User\\Project"
    assert _translate_wsl_path(win_path) == win_path

def test_translate_posix_path_wslpath_not_found(monkeypatch):
    """Test POSIX path translation when wslpath is not found (should raise RuntimeError)."""
    monkeypatch.setattr(platform, "system", mock_platform_system("Windows"))
    monkeypatch.setattr("jinni.utils._find_wslpath", mock_find_wslpath(None)) # Mock find failure
    monkeypatch.setattr("jinni.utils._get_default_wsl_distro", mock_get_default_wsl_distro(None)) # Mock no default distro
    monkeypatch.delenv("JINNI_ASSUME_WSL_DISTRO", raising=False) # Mock no env var
    # Mock Path(...).exists to always return False for the fallback check
    monkeypatch.setattr("jinni.utils.Path", MockPathExists) # Use the refined mock

    with pytest.raises(RuntimeError, match="Cannot map POSIX path"):
        _translate_wsl_path("/home/user/project")

def test_translate_posix_path_wslpath_error(monkeypatch):
    """Test POSIX path translation when wslpath command fails (should raise RuntimeError)."""
    monkeypatch.setattr(platform, "system", mock_platform_system("Windows"))
    monkeypatch.setattr("jinni.utils._find_wslpath", mock_find_wslpath("/fake/wslpath"))
    monkeypatch.setattr("jinni.utils._cached_wsl_to_unc", mock_cached_wsl_to_unc(None)) # Mock wslpath call failure
    monkeypatch.setattr("jinni.utils._get_default_wsl_distro", mock_get_default_wsl_distro(None)) # Mock no default distro
    monkeypatch.delenv("JINNI_ASSUME_WSL_DISTRO", raising=False) # Mock no env var
    # Mock Path(...).exists to always return False for the fallback check
    monkeypatch.setattr("jinni.utils.Path", MockPathExists) # Use the refined mock

    with pytest.raises(RuntimeError, match="Cannot map POSIX path"):
        _translate_wsl_path("/home/user/project")

def test_translate_vscode_non_wsl_uri_no_change(monkeypatch):
    """Test a non-WSL vscode-remote URI is not translated."""
    monkeypatch.setattr(platform, "system", mock_platform_system("Windows"))
    # Standard urlparse is fine here, relies on scheme/netloc check
    uri = "vscode-remote://ssh+server/path/on/remote"
    assert _translate_wsl_path(uri) == uri

def test_translate_posix_path_on_linux_no_change(monkeypatch):
    """Test POSIX path is not translated when running on Linux."""
    monkeypatch.setattr(platform, "system", mock_platform_system("Linux"))
    path = "/home/user/project"
    assert _translate_wsl_path(path) == path

def test_translate_vscode_wsl_uri_on_linux_no_change(monkeypatch):
    """Test vscode-remote WSL URI is STRIPPED when running on Linux/non-Windows."""
    monkeypatch.setattr(platform, "system", mock_platform_system("Linux"))
    uri = "vscode-remote://wsl+Ubuntu/home/user/project"
    expected_stripped_path = "/home/user/project"
    assert _translate_wsl_path(uri) == expected_stripped_path

def test_translate_unc_path_no_change(monkeypatch):
    """Test a UNC path (potentially already translated) is not re-translated."""
    monkeypatch.setattr(platform, "system", mock_platform_system("Windows"))
    unc_path = r"\\wsl$\Ubuntu\home\user"
    assert _translate_wsl_path(unc_path) == unc_path
    unc_path_localhost = r"\\wsl.localhost\Ubuntu\home\user"
    assert _translate_wsl_path(unc_path_localhost) == unc_path_localhost

def test_translate_empty_string_no_change(monkeypatch):
    """Test an empty string is handled gracefully."""
    monkeypatch.setattr(platform, "system", mock_platform_system("Windows"))
    assert _translate_wsl_path("") == ""

def test_translate_env_var_disables_translation(monkeypatch):
    """Test setting JINNI_NO_WSL_TRANSLATE=1 disables translation."""
    monkeypatch.setenv("JINNI_NO_WSL_TRANSLATE", "1")
    monkeypatch.setattr(platform, "system", mock_platform_system("Windows"))
    posix_path = "/home/user/project"
    vscode_uri = "vscode-remote://wsl+Ubuntu/home/user/project"
    # No mocks for wslpath needed, should exit early
    assert _translate_wsl_path(posix_path) == posix_path
    assert _translate_wsl_path(vscode_uri) == vscode_uri

def test_translate_platform_windows_lowercase(monkeypatch):
    """Test translation works if platform.system() returns lowercase 'windows'."""
    monkeypatch.setattr(platform, "system", mock_platform_system("windows"))
    monkeypatch.setattr("jinni.utils._find_wslpath", mock_find_wslpath("/fake/wslpath"))
    monkeypatch.setattr("jinni.utils._cached_wsl_to_unc", mock_cached_wsl_to_unc(r"\\wsl$\Ubuntu\home\user\project"))
    assert _translate_wsl_path("/home/user/project") == r"\\wsl$\Ubuntu\home\user\project"

def test_strip_wsl_uri_to_posix_on_linux(monkeypatch):
    """Test that percent-encoded + in authority is handled and VSCode WSL URIs are stripped to POSIX on Linux."""
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    # Should decode %2B to + and strip to /home/x
    assert _translate_wsl_path("vscode-remote://wsl%2Bubuntu/home/x") == "/home/x"
    # Should also work for normal +
    assert _translate_wsl_path("vscode-remote://wsl+ubuntu/home/y") == "/home/y"
    # Should also work for alternate vscode URI
    assert _translate_wsl_path("vscode://vscode-remote/wsl+ubuntu/home/z") == "/home/z"
    # Should return unchanged for normal POSIX path
    assert _translate_wsl_path("/home/unchanged") == "/home/unchanged"

def test_translate_percent_encoded_plus_uri_on_windows(monkeypatch):
    """Test vscode-remote URI with %2B is translated to UNC on Windows."""
    monkeypatch.setattr(platform, "system", mock_platform_system("Windows"))
    input_uri = "vscode-remote://wsl%2BUbuntu-20.04/mnt/c/project"
    # Use raw string for expected UNC path
    expected_unc = r"\\wsl$\Ubuntu-20.04\mnt\c\project"
    assert _translate_wsl_path(input_uri) == expected_unc

def test_translate_percent_encoded_plus_uri_on_linux(monkeypatch):
    """Test vscode-remote URI with %2B is stripped to POSIX on Linux."""
    monkeypatch.setattr(platform, "system", mock_platform_system("Linux"))
    input_uri = "vscode-remote://wsl%2BUbuntu-20.04/mnt/c/project"
    expected_posix = "/mnt/c/project"
    assert _translate_wsl_path(input_uri) == expected_posix

# --- Parametrized Tests (Corrected with Raw Strings) ---

@pytest.mark.parametrize(
    ("input_path", "mock_system", "mock_find_wslpath_ret", "mock_cached_wsl_ret", "expected_output", "env_vars", "mock_default_distro", "expected_fallback_exists_path", "expected_exception_type", "expected_exception_msg"),
    [
        # --- Standard WSL Translations (Success) ---
        ("/home/alice/app", "Windows", "/fake/wslpath", r"\\wsl$\Ubuntu\home\alice\app", r"\\wsl$\Ubuntu\home\alice\app", None, None, None, None, None),
        ("vscode-remote://wsl+Ubuntu/home/alice/app", "Windows", None, None, r"\\wsl$\Ubuntu\home\alice\app", None, None, None, None, None),
        ("vscode-remote://wsl.localhost/Ubuntu/home/alice/app", "Windows", None, None, r"\\wsl$\Ubuntu\home\alice\app", None, None, None, None, None),
        ("vscode://vscode-remote/wsl+Ubuntu/home/alice/app", "Windows", None, None, r"\\wsl$\Ubuntu\home\alice\app", None, None, None, None, None),

        # --- Edge Cases & New Features (Success) ---
        ("vscode-remote://wsl+Ubuntu 22.04/mnt/c/Data", "Windows", None, None, r"\\wsl$\Ubuntu 22.04\mnt\c\Data", None, None, None, None, None),
        ("vscode-remote://wsl.localhost/Ubuntu 22.04/mnt/c/Data", "Windows", None, None, r"\\wsl$\Ubuntu 22.04\mnt\c\Data", None, None, None, None, None),
        ("vscode-remote://wsl+Ubuntu/home/user/My%20Project", "Windows", None, None, r"\\wsl$\Ubuntu\home\user\My Project", None, None, None, None, None),
        ("vscode://vscode-remote/wsl+Ubuntu", "Windows", None, None, r"\\wsl$\Ubuntu\\", None, None, None, None, None),
        ("vscode-remote://ssh-remote+myhost/path/to/proj", "Windows", None, None, "vscode-remote://ssh-remote+myhost/path/to/proj", None, None, None, None, None),
        (r"\\wsl$\Ubuntu\home\My Project\file.txt", "Windows", None, None, r"\\wsl$\Ubuntu\home\My Project\file.txt", None, None, None, None, None),
        ("vscode://vscode-remote/wsl+Ubuntu/home/user/.bashrc", "Windows", None, None, r"\\wsl$\Ubuntu\home\user\.bashrc", None, None, None, None, None),
        ("vscode://vscode-remote/wsl+Ubuntu", "Windows", None, None, r"\\wsl$\Ubuntu\\", None, None, None, None, None),
        ("vscode://vscode-remote/wsl+Ubuntu/", "Windows", None, None, r"\\wsl$\Ubuntu\\", None, None, None, None, None),
        ("vscode-remote://wsl.localhost/Debian/etc/passwd", "Windows", None, None, r"\\wsl$\Debian\etc\passwd", None, None, None, None, None),

        # --- Malformed URIs (ValueError expected) ---
        ("vscode-remote://wsl+/home/user/project", "Windows", None, None, None, None, None, None, ValueError, "missing distro name in WSL URI"),
        ("vscode-remote://wsl.localhost//home/user/project", "Windows", None, None, None, None, None, None, ValueError, "missing distro name in wsl.localhost URI path"),
        ("vscode://vscode-remote/wsl+/home/user", "Windows", None, None, None, None, None, None, ValueError, "missing distro name in alternate vscode URI authority"),
        ("vscode-remote://wsl.localhost/", "Windows", None, None, None, None, None, None, ValueError, "missing or invalid distro/path in wsl.localhost URI path"),

        # --- Non-Windows Platform (Should Strip/Not Translate - Success) ---
        ("/home/alice/app", "Linux", None, None, "/home/alice/app", None, None, None, None, None),
        ("vscode-remote://wsl+Ubuntu/home/alice/app", "macOS", None, None, "/home/alice/app", None, None, None, None, None),
        ("vscode-remote://wsl.localhost/Debian/tmp/file", "Linux", None, None, "/tmp/file", None, None, None, None, None),

        # --- Fallback Tests (Success) ---
        ("/home/alice/app", "Windows", None, None, r"\\wsl$\TestDistro\home\alice\app", {"JINNI_ASSUME_WSL_DISTRO": "TestDistro"}, None, r"\\wsl$\TestDistro\home\alice\app", None, None),
        ("/home/alice/app", "Windows", None, None, r"\\wsl$\DefaultDistro\home\alice\app", None, "DefaultDistro", r"\\wsl$\DefaultDistro\home\alice\app", None, None),
        ("/home/alice/app", "Windows", None, None, r"\\wsl$\TestDistro\home\alice\app", {"JINNI_ASSUME_WSL_DISTRO": "TestDistro"}, None, None, None, None),
        ("/home/alice/app", "Windows", None, None, r"\\wsl$\DefaultDistro\home\alice\app", None, "DefaultDistro", None, None, None),

        # --- Env Var Disables (Success, No Translation) ---
        ("/home/alice/app", "Windows", "/fake/wslpath", None, "/home/alice/app", {"JINNI_NO_WSL_TRANSLATE": "1"}, None, None, None, None),
        ("vscode-remote://wsl+Ubuntu/home/alice/app", "Windows", None, None, "vscode-remote://wsl+Ubuntu/home/alice/app", {"JINNI_NO_WSL_TRANSLATE": "1"}, None, None, None, None),
    ],
    ids=[
        "posix_to_unc_wslpath_ok",
        "vscode_remote_wsl_plus_uri_to_unc",
        "vscode_remote_wsl_localhost_uri_to_unc",
        "vscode_alt_uri_wsl_plus_to_unc",
        "distro_with_spaces_wsl_plus",
        "distro_with_spaces_wsl_localhost",
        "path_with_encoded_spaces",
        "vscode_alt_uri_no_path_to_unc_root",
        "ssh_remote_uri_no_change",
        "unc_dollar_path_no_change",
        "vscode_uri_bashrc_to_unc",
        "vscode_uri_distro_only_to_unc_root",
        "vscode_uri_distro_slash_to_unc_root",
        "vscode_localhost_uri_path_to_unc",
        "malformed_uri_wsl_plus_empty_distro_raises_valueerror",
        "malformed_uri_wsl_localhost_empty_distro_raises_valueerror",
        "malformed_uri_alt_vscode_empty_distro_raises_valueerror",
        "malformed_uri_wsl_localhost_root_only_raises_valueerror",
        "posix_on_linux_no_change",
        "vscode_remote_uri_on_macos_strips",
        "vscode_localhost_uri_on_linux_strips",
        "fallback_success_no_wslpath_env_var_exists_ok",
        "fallback_success_no_wslpath_default_distro_exists_ok",
        "fallback_success_no_wslpath_env_var_exists_false",
        "fallback_success_no_wslpath_default_distro_exists_false",
        "env_var_disables_posix",
        "env_var_disables_vscode_uri",
    ]
)
def test_translate_wsl_path_parametrized(
    request,
    monkeypatch,
    input_path,
    mock_system,
    mock_find_wslpath_ret,
    mock_cached_wsl_ret,
    expected_output,
    env_vars,
    mock_default_distro,
    expected_fallback_exists_path,
    expected_exception_type,
    expected_exception_msg
):
    """Parametrized test covering various inputs for _translate_wsl_path."""

    # --- Environment Variables ---
    orig_env = os.environ.copy()
    if env_vars:
        for k, v in env_vars.items():
            monkeypatch.setenv(k, v)
    else:
        # Ensure potentially interfering env vars are unset
        monkeypatch.delenv("JINNI_NO_WSL_TRANSLATE", raising=False)
        monkeypatch.delenv("JINNI_ASSUME_WSL_DISTRO", raising=False)

    # --- System and Helper Mocks ---
    monkeypatch.setattr(platform, "system", mock_platform_system(mock_system))
    monkeypatch.setattr("jinni.utils._find_wslpath", mock_find_wslpath(mock_find_wslpath_ret))
    monkeypatch.setattr("jinni.utils._get_default_wsl_distro", mock_get_default_wsl_distro(mock_default_distro))

    # Mock _cached_wsl_to_unc behavior based on parameters
    # If mock_cached_wsl_ret is None, it means the call should fail (return None)
    monkeypatch.setattr("jinni.utils._cached_wsl_to_unc", mock_cached_wsl_to_unc(mock_cached_wsl_ret))

    # --- Mock Path.exists() specifically for fallback testing ---
    class MockPath:
        def __init__(self, path_str):
            self.path_str = str(path_str)

        def exists(self):
            # Called ONLY during the manual fallback logic in _translate_wsl_path
            # Return True only if the path matches the specific expected UNC path for fallback success tests
            if expected_fallback_exists_path is not None and self.path_str == expected_fallback_exists_path:
                return True
            return False # Default to False for all other cases (incl. fallback failure tests)

    # Determine if this test case involves the manual fallback logic for POSIX paths on Windows
    is_windows = mock_system.lower() == "windows"
    is_posix_input = isinstance(input_path, str) and input_path.startswith("/") and not urlparse(input_path).scheme
    # Fallback happens if wslpath isn't found OR if it is found but _cached_wsl_to_unc returns None
    triggers_fallback = is_windows and is_posix_input and (not mock_find_wslpath_ret or mock_cached_wsl_ret is None)
    if triggers_fallback:
        monkeypatch.setattr("jinni.utils.Path", MockPath)

    # --- Patch _get_default_wsl_distro for specific cases ---
    if request.node.callspec.id in [
        "fallback_success_no_wslpath_env_var_exists_ok",
        "fallback_success_no_wslpath_env_var_exists_false",
    ]:
        monkeypatch.setattr("jinni.utils._get_default_wsl_distro", lambda: "TestDistro")

    # --- Perform the Call and Assert ---
    if expected_exception_type:
        # Expecting an exception
        with pytest.raises(expected_exception_type, match=expected_exception_msg):
            _translate_wsl_path(input_path)
    else:
        # Expecting a successful return value
        result = _translate_wsl_path(input_path)
        assert result == expected_output

    # Restore environment (optional, monkeypatch usually handles this)
    for k, v in orig_env.items():
        os.environ[k] = v
    for k in env_vars if env_vars else {}:
        if k not in orig_env:
            monkeypatch.delenv(k, raising=False)

# --- New Specific Test Cases ---

def test_strip_wsl_localhost_uri_on_linux(monkeypatch):
    """Test vscode-remote wsl.localhost URI is stripped on Linux."""
    monkeypatch.setattr(platform, "system", mock_platform_system("Linux"))
    uri = "vscode-remote://wsl.localhost/Debian/tmp/my project"
    expected_stripped_path = "/tmp/my project"
    assert _translate_wsl_path(uri) == expected_stripped_path

def test_fallback_runtime_error(monkeypatch):
    """Test RuntimeError is raised on Windows when no wslpath and no fallback works (mocked Path.exists=False)."""
    monkeypatch.setattr(platform, "system", mock_platform_system("Windows"))
    monkeypatch.setattr("jinni.utils._find_wslpath", mock_find_wslpath(None)) # No wslpath
    monkeypatch.setattr("jinni.utils._get_default_wsl_distro", mock_get_default_wsl_distro(None)) # No default distro
    monkeypatch.delenv("JINNI_ASSUME_WSL_DISTRO", raising=False) # No env var

    # Mock Path.exists to always return False for the fallback check
    # Simpler mock is sufficient here
    class MockPathFalse:
        def __init__(self, path_str): pass
        def exists(self): return False
    monkeypatch.setattr("jinni.utils.Path", MockPathFalse)

    with pytest.raises(RuntimeError, match="Cannot map POSIX path"):
        _translate_wsl_path("/home/user/some/path")

def test_malformed_uri_value_error(monkeypatch):
    """Test ValueError is raised for malformed URIs with missing distros."""
    monkeypatch.setattr(platform, "system", mock_platform_system("Windows"))
    # Test vscode-remote://wsl+
    with pytest.raises(ValueError, match="missing distro name in WSL URI"):
        _translate_wsl_path("vscode-remote://wsl+/home/user")
    # Test vscode-remote://wsl.localhost/
    with pytest.raises(ValueError, match="missing distro name in wsl.localhost URI path"):
        _translate_wsl_path("vscode-remote://wsl.localhost//home/user")
    # Test vscode://vscode-remote/wsl+
    with pytest.raises(ValueError, match="missing distro name in alternate vscode URI authority"):
        _translate_wsl_path("vscode://vscode-remote/wsl+/home/user")
    # Test wsl.localhost with only root / (missing distro)
    with pytest.raises(ValueError, match="missing or invalid distro/path in wsl.localhost URI path"):
        _translate_wsl_path("vscode-remote://wsl.localhost/")

# --- Test ensure_no_nul utility ---
def test_ensure_no_nul():
    # Should not raise
    ensure_no_nul("abc", "test-field")
    # Should raise ValueError on NUL
    with pytest.raises(ValueError):
        ensure_no_nul("a\x00b", "test-field") 