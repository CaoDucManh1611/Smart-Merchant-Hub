import importlib.util
import sqlite3
from pathlib import Path

import pytest


_MODULE_PATH = Path(__file__).parents[2] / "scripts" / "lttk" / "browsercookies.py"
if not _MODULE_PATH.is_file():
    pytest.skip(
        "TikTok runtime is intentionally ignored; browser-profile tests run when it is present locally.",
        allow_module_level=True,
    )
_SPEC = importlib.util.spec_from_file_location("smartmerchant_browsercookies", _MODULE_PATH)
browsercookies = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(browsercookies)


def _cookie_db(path, cookies):
    path.parent.mkdir(parents=True)
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE cookies (name TEXT, encrypted_value BLOB, host_key TEXT)")
        db.executemany(
            "INSERT INTO cookies VALUES (?, ?, '.tiktok.com')",
            [(name, value.encode()) for name, value in cookies.items()],
        )


def test_lists_profiles_and_refuses_to_guess_when_multiple_have_sessions(tmp_path, monkeypatch):
    user_data = tmp_path / "Chrome" / "User Data"
    default_cookies = user_data / "Default" / "Network" / "Cookies"
    other_cookies = user_data / "Profile 1" / "Network" / "Cookies"
    _cookie_db(default_cookies, {"sessionid": "default-session"})
    _cookie_db(other_cookies, {"sessionid": "profile-1-session"})
    monkeypatch.setitem(browsercookies._CHROMIUM_PATHS, "chrome", str(default_cookies))
    monkeypatch.delenv("TIKTOK_BROWSER_PROFILE", raising=False)
    monkeypatch.setattr(browsercookies, "_read_locked_file", lambda path, _: Path(path).read_bytes())
    monkeypatch.setattr(browsercookies, "_decrypt_chromium", lambda encrypted, _: encrypted.decode())

    profiles = browsercookies.get_tiktok_cookie_profiles("chrome")
    assert [profile for profile, _ in profiles] == ["Default", "Profile 1"]
    with pytest.raises(RuntimeError, match="multiple browser profiles"):
        browsercookies.get_tiktok_cookies("chrome")

    monkeypatch.setenv("TIKTOK_BROWSER_PROFILE", "Profile 1")
    assert browsercookies.get_tiktok_cookies("chrome")["sessionid"] == "profile-1-session"


def test_locked_cookie_file_never_terminates_browser_and_explains_recovery(monkeypatch):
    def locked_open(*args, **kwargs):
        raise PermissionError("locked")

    monkeypatch.setattr("builtins.open", locked_open)
    with pytest.raises(PermissionError, match="Microsoft Edge.*tự đóng trình duyệt"):
        browsercookies._read_locked_file("cookies.db", "edge")


def test_locked_edge_profile_does_not_prevent_scanning_other_profiles(tmp_path, monkeypatch):
    user_data = tmp_path / "Edge" / "User Data"
    default_cookies = user_data / "Default" / "Network" / "Cookies"
    other_cookies = user_data / "Profile 3" / "Network" / "Cookies"
    _cookie_db(default_cookies, {"sessionid": "default-session"})
    _cookie_db(other_cookies, {"sessionid": "profile-3-session"})
    monkeypatch.setitem(browsercookies._CHROMIUM_PATHS, "edge", str(default_cookies))
    monkeypatch.delenv("TIKTOK_BROWSER_PROFILE", raising=False)

    def read_unlocked_profiles(path, _browser):
        if "Default" in path:
            raise PermissionError("Edge is using this profile")
        return Path(path).read_bytes()

    monkeypatch.setattr(browsercookies, "_read_locked_file", read_unlocked_profiles)
    monkeypatch.setattr(browsercookies, "_decrypt_chromium", lambda encrypted, _: encrypted.decode())

    profiles = browsercookies.get_tiktok_cookie_profiles("edge")
    assert profiles == [("Profile 3", {"sessionid": "profile-3-session"})]
