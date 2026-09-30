import sys
from pathlib import Path

import pytest


_SCRIPTS = Path(__file__).parents[2] / "scripts"
sys.path.insert(0, str(_SCRIPTS))
from tiktok_bot import _parse_cookie_input


def test_parses_cookie_header():
    assert _parse_cookie_input("Cookie: sessionid=abc; msToken=xyz") == {
        "sessionid": "abc",
        "msToken": "xyz",
    }


def test_parses_tiktok_json_and_ignores_other_domains():
    cookies = _parse_cookie_input(
        '[{"name":"sessionid","value":"abc","domain":".tiktok.com"},'
        '{"name":"sid","value":"unrelated","domain":"example.com"}]'
    )
    assert cookies == {"sessionid": "abc"}


def test_rejects_cookie_without_tiktok_session():
    with pytest.raises(ValueError, match="sessionid"):
        _parse_cookie_input("ttwid=abc")
