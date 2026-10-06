import json
import os
import stat
from pathlib import Path

from shokz_refill.media import _download_auth_options


def test_download_auth_uses_scoped_cookie_file(tmp_path: Path) -> None:
    auth = tmp_path / "browser.json"
    auth.write_text(
        json.dumps(
            {
                "Cookie": "SID=secret-one; __Secure-3PSID=secret=two",
                "Authorization": "SAPISIDHASH must-not-be-forwarded",
                "User-Agent": "Test browser",
            }
        ),
        encoding="utf-8",
    )

    options, cookie_path = _download_auth_options(auth, tmp_path / "job")

    assert options["http_headers"] == {"User-Agent": "Test browser"}
    assert cookie_path == tmp_path / "job" / "youtube-cookies.txt"
    assert options["cookiefile"] == str(cookie_path)
    assert cookie_path is not None
    cookie_text = cookie_path.read_text(encoding="utf-8")
    assert ".youtube.com\tTRUE\t/\tTRUE\t0\tSID\tsecret-one" in cookie_text
    assert ".youtube.com\tTRUE\t/\tTRUE\t0\t__Secure-3PSID\tsecret=two" in cookie_text
    assert "Authorization" not in cookie_text
    if os.name == "posix":
        assert stat.S_IMODE(cookie_path.stat().st_mode) == 0o600
