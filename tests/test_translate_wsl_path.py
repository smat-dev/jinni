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

# Clear caches before each test function to avoid interference
@pytest.fixture(autouse=True)
def clear_lru_caches():
    _find_wslpath.cache_clear()
    _cached_wsl_to_unc.cache_clear()

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
        if posix_path == fail_path:
            return None # Simulate failure for a specific path
        return win_path # Return success path otherwise
    return func

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
    monkeypatch.setattr("jinni.utils._get_default_wsl_distro", lambda: None) # Mock no default distro
    monkeypatch.delenv("JINNI_ASSUME_WSL_DISTRO", raising=False) # Mock no env var
    # Mock Path.exists to always return False
    class MockPathFalse:
        def __init__(self, path_str): pass
        def exists(self): return False
    monkeypatch.setattr("jinni.utils.Path", MockPathFalse)
    with pytest.raises(RuntimeError, match="Cannot map POSIX path"):
        _translate_wsl_path("/home/user/project")

def test_translate_posix_path_wslpath_error(monkeypatch):
    """Test POSIX path translation when wslpath command fails (should raise RuntimeError)."""
    monkeypatch.setattr(platform, "system", mock_platform_system("Windows"))
    monkeypatch.setattr("jinni.utils._find_wslpath", mock_find_wslpath("/fake/wslpath"))
    monkeypatch.setattr("jinni.utils._cached_wsl_to_unc", mock_cached_wsl_to_unc(None)) # Mock wslpath call failure
    monkeypatch.setattr("jinni.utils._get_default_wsl_distro", lambda: None) # Mock no default distro
    monkeypatch.delenv("JINNI_ASSUME_WSL_DISTRO", raising=False) # Mock no env var
    # Mock Path.exists to always return False
    class MockPathFalse:
        def __init__(self, path_str): pass
        def exists(self): return False
    monkeypatch.setattr("jinni.utils.Path", MockPathFalse)
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
    expected_unc = r"\\wsl$\Ubuntu-20.04\mnt\c\project"
    # No wslpath mocks needed as URI translation doesn't use it
    assert _translate_wsl_path(input_uri) == expected_unc

def test_translate_percent_encoded_plus_uri_on_linux(monkeypatch):
    """Test vscode-remote URI with %2B is stripped to POSIX on Linux."""
    monkeypatch.setattr(platform, "system", mock_platform_system("Linux"))
    input_uri = "vscode-remote://wsl%2BUbuntu-20.04/mnt/c/project"
    expected_posix = "/mnt/c/project"
    assert _translate_wsl_path(input_uri) == expected_posix

# --- Parametrized Tests (Updated) ---

@pytest.mark.parametrize(
    ("input_path", "mock_system", "mock_find_wslpath_ret", "mock_cached_wsl_ret", "expected_output", "env_vars"),
    [
        # --- Standard WSL Translations ---
        # POSIX Path -> \\wsl$\... (UNC format)
        ("/home/alice/app", "Windows", "/fake/wslpath", r"\\wsl$\Ubuntu\home\alice\app", r"\\wsl$\Ubuntu\home\alice\app", None),
        # VSCode Remote wsl+ URI -> \\wsl$\... (UNC format)
        ("vscode-remote://wsl+Ubuntu/home/alice/app", "Windows", None, None, r"\\wsl$\Ubuntu\home\alice\app", None),
        # VSCode Remote wsl.localhost URI
        ("vscode-remote://wsl.localhost/Ubuntu/home/alice/app", "Windows", None, None, r"\\wsl$\Ubuntu\home\alice\app", None),
        # Alternate VSCode URI wsl+
        ("vscode://vscode-remote/wsl+Ubuntu/home/alice/app", "Windows", None, None, r"\\wsl$\Ubuntu\home\alice\app", None),

        # --- Edge Cases & New Features ---
        # Distro with spaces (wsl+)
        ("vscode-remote://wsl+Ubuntu 22.04/mnt/c/Data", "Windows", None, None, r"\\wsl$\Ubuntu 22.04\mnt\c\Data", None),
        # Distro with spaces (wsl.localhost)
        ("vscode-remote://wsl.localhost/Ubuntu 22.04/mnt/c/Data", "Windows", None, None, r"\\wsl$\Ubuntu 22.04\mnt\c\Data", None),
        # Path with URL-encoded spaces
        ("vscode-remote://wsl+Ubuntu/home/user/My%20Project", "Windows", None, None, r"\\wsl$\Ubuntu\home\user\My Project", None),
        # Alternate VSCode URI - No Path
        ("vscode://vscode-remote/wsl+Ubuntu", "Windows", None, None, "\\\\wsl$\\Ubuntu\\", None),
        # Malformed URI (empty distro)
        ("vscode-remote://wsl+/home/user/project", "Windows", None, None, "vscode-remote://wsl+/home/user/project", None),
        # Malformed localhost URI (no distro) - Expect UNC path with 'home' as distro
        ("vscode-remote://wsl.localhost//home/user/project", "Windows", None, None, r"\\wsl$\home\user\project", None),
        # SSH Remote URI (Should Not Translate)
        ("vscode-remote://ssh-remote+myhost/path/to/proj", "Windows", None, None, "vscode-remote://ssh-remote+myhost/path/to/proj", None),
        # Already translated UNC Path (Should Not Translate)
        (r"\\wsl$\Ubuntu\home\My Project\file.txt", "Windows", None, None, r"\\wsl$\Ubuntu\home\My Project\file.txt", None),
        # Already translated old UNC Path (Should Not Translate)
        (r"\\wsl$\Ubuntu\home\My Project\file.txt", "Windows", None, None, r"\\wsl$\Ubuntu\home\My Project\file.txt", None),
        # Regular Windows Path (Should Not Translate)
        (r"C:\Users\Test\Project", "Windows", None, None, r"C:\Users\Test\Project", None),

        # --- Non-Windows Platform (Should Not Translate / Should Strip) ---
        ("/home/alice/app", "Linux", None, None, "/home/alice/app", None),
        # Now expects stripping on non-Windows
        ("vscode-remote://wsl+Ubuntu/home/alice/app", "macOS", None, None, "/home/alice/app", None),
        # wsl.localhost URIs are *not* stripped by the helper, so expect original path
        ("vscode-remote://wsl.localhost/Debian/tmp", "Linux", None, None, "/tmp", None),

        # --- wslpath unavailable/error (Should Not Translate POSIX without fallback) ---
        ("/home/alice/app", "Windows", None, None, "/home/alice/app", None), # wslpath not found - Fallback will raise error if WSL/distro not found
        ("/home/alice/app", "Windows", "/fake/wslpath", None, "/home/alice/app", None), # wslpath call fails - Fallback will raise error if WSL/distro not found

        # --- Fallback via JINNI_ASSUME_WSL_DISTRO ---
        ("/home/alice/app", "Windows", None, None, r"\\wsl$\TestDistro\home\alice\app", {"JINNI_ASSUME_WSL_DISTRO": "TestDistro"}), # wslpath not found, uses env var

        # --- Env Var Disables (Should Not Translate) ---
        ("/home/alice/app", "Windows", "/fake/wslpath", r"\\wsl$\Ubuntu\home\alice\app", "/home/alice/app", {"JINNI_NO_WSL_TRANSLATE": "1"}),
        ("vscode-remote://wsl+Ubuntu/home/alice/app", "Windows", None, None, "vscode-remote://wsl+Ubuntu/home/alice/app", {"JINNI_NO_WSL_TRANSLATE": "1"}),
    ],
    ids=[
        "posix_to_unc",
        "vscode_remote_wsl_plus_uri_to_unc",
        "vscode_remote_wsl_localhost_uri_to_unc",
        "vscode_alt_uri_wsl_plus_to_unc",
        "distro_with_spaces_wsl_plus",
        "distro_with_spaces_wsl_localhost",
        "path_with_encoded_spaces",
        "vscode_alt_uri_no_path_to_unc_root",
        "malformed_uri_wsl_plus_empty_distro_raises", # Updated expected behavior
        "malformed_uri_wsl_localhost_empty_distro_raises", # Updated expected behavior
        "ssh_remote_uri_no_change",
        "unc_localhost_path_no_change",
        "unc_dollar_path_no_change",
        "windows_path_no_change",
        "posix_on_linux_no_change",
        "vscode_remote_uri_on_macos_strips", # Updated expected behavior
        "vscode_localhost_uri_on_linux_strips", # Updated expected behavior
        "posix_wslpath_not_found_fallback_raises", # Updated expected behavior
        "posix_wslpath_call_fails_fallback_raises", # Updated expected behavior
        "fallback_via_env_var", # New test case
        "env_var_disables_posix",
        "env_var_disables_vscode_uri",
    ]
)
def test_translate_wsl_path_parametrized(
    request,
    monkeypatch,
    input_path, mock_system, mock_find_wslpath_ret, mock_cached_wsl_ret, expected_output,
    env_vars
    ):

    should_translate = mock_system.lower() == "windows" and (not env_vars or env_vars.get("JINNI_NO_WSL_TRANSLATE") != "1")

    if env_vars:
        for k, v in env_vars.items():
            monkeypatch.setenv(k, v)
    else:
        # Ensure the env var is unset if not specified for the test case
        monkeypatch.delenv("JINNI_NO_WSL_TRANSLATE", raising=False)

    monkeypatch.setattr(platform, "system", mock_platform_system(mock_system))
    # Mock the internal helper functions
    monkeypatch.setattr("jinni.utils._find_wslpath", mock_find_wslpath(mock_find_wslpath_ret))
    # Only mock _cached_wsl_to_unc if wslpath is expected to be found
    if mock_find_wslpath_ret:
        monkeypatch.setattr("jinni.utils._cached_wsl_to_unc", mock_cached_wsl_to_unc(mock_cached_wsl_ret, fail_path="/fail/path"))

    # Actual urlparse might be needed for complex URIs, no mock applied here unless needed

    # Cache clearing is handled by the autouse fixture
    # _find_wslpath.cache_clear()
    # _cached_wsl_to_unc.cache_clear()

    # --- Mock Path.exists() for fallback testing ---
    # Only mock if we expect fallback to be potentially triggered
    is_windows = mock_system.lower() == "windows"
    is_posix_input = input_path.startswith("/") and not urlparse(input_path).scheme
    should_mock_exists = is_windows and is_posix_input and not mock_find_wslpath_ret

    class MockPath:
        def __init__(self, path_str):
            self._path_str = path_str
        def exists(self):
            # Simulate existence only for the expected fallback path
            expected_fallback_unc = r"\\wsl$\TestDistro\home\alice\app"
            # print(f"MockPath checking exists for: {self._path_str} against {expected_fallback_unc}") # Debug print
            return self._path_str == expected_fallback_unc

    if should_mock_exists:
        monkeypatch.setattr("jinni.utils.Path", MockPath)

    # Mock _get_default_wsl_distro to return None unless specifically testing it
    # (Parametrized tests don't cover this branch yet, added separate test below)
    monkeypatch.setattr("jinni.utils._get_default_wsl_distro", lambda: None)

    # --- Handle Expected Exceptions --- 
    # Use request.node.callspec.id to get the current test case ID
    current_test_id = request.node.callspec.id
    if "raises" in current_test_id:
        # Determine expected exception type based on ID
        expected_exception = ValueError if "malformed" in current_test_id else RuntimeError
        with pytest.raises(expected_exception):
            _translate_wsl_path(input_path)
    else:
        # Only call this if no exception is expected
        result = _translate_wsl_path(input_path)
        assert result == expected_output

    is_posix_path = input_path.startswith("/") and not urlparse(input_path).scheme

    # Test caching only if translation was expected to happen and wslpath is found and real platform is Windows
    # (Removed cache assertions; not meaningful with mocks)
    # elif is_posix_path and is_real_windows: # Check non-translate cases
    #     # If it's a POSIX path but translation shouldn't happen (Linux or Env Var)
    #     # _find_wslpath should not be called
    #     find_wslpath_info = _find_wslpath.cache_info()
    #     assert find_wslpath_info.misses == 0, f"_find_wslpath misses check failed (non-translate) ({find_wslpath_info=})"
    #     assert find_wslpath_info.hits == 0, f"_find_wslpath hits check failed (non-translate) ({find_wslpath_info=})"
    #     # _cached_wsl_to_unc should not be called
    #     cached_unc_info = _cached_wsl_to_unc.cache_info()
    #     assert cached_unc_info.misses == 0, f"_cached_wsl_to_unc misses check failed (non-translate) ({cached_unc_info=})"
    #     assert cached_unc_info.hits == 0, f"_cached_wsl_to_unc hits check failed (non-translate) ({cached_unc_info=})" 

# --- New Specific Test Cases ---

def test_strip_wsl_localhost_uri_on_linux(monkeypatch):
    """Test vscode-remote wsl.localhost URI is stripped on Linux."""
    monkeypatch.setattr(platform, "system", mock_platform_system("Linux"))
    uri = "vscode-remote://wsl.localhost/Debian/tmp/my project"
    expected_stripped_path = "/tmp/my project"
    assert _translate_wsl_path(uri) == expected_stripped_path

def test_fallback_runtime_error(monkeypatch):
    """Test RuntimeError is raised on Windows when no wslpath and no fallback works."""
    monkeypatch.setattr(platform, "system", mock_platform_system("Windows"))
    monkeypatch.setattr("jinni.utils._find_wslpath", mock_find_wslpath(None)) # No wslpath
    monkeypatch.setattr("jinni.utils._get_default_wsl_distro", lambda: None) # No default distro
    monkeypatch.delenv("JINNI_ASSUME_WSL_DISTRO", raising=False) # No env var

    # Mock Path.exists to always return False for the fallback check
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