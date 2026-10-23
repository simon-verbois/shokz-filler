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


def test_process_drains_large_stderr_without_deadlock() -> None:
    import sys

    from shokz_refill.media import run_process

    run_process([sys.executable, "-c", "import sys; sys.stderr.write('x' * 200000)"], lambda: False)


def test_process_failure_reports_tail() -> None:
    import sys

    import pytest

    from shokz_refill.media import run_process

    with pytest.raises(RuntimeError, match="specific failure"):
        run_process(
            [sys.executable, "-c", "import sys; sys.stderr.write('specific failure'); sys.exit(3)"],
            lambda: False,
        )


def test_process_cancellation_terminates_and_reaps_child(tmp_path: Path) -> None:
    import sys

    import pytest

    from shokz_refill.media import DownloadCancelled, run_process

    ready = tmp_path / "ready"
    command = [
        sys.executable,
        "-c",
        "import pathlib,time,sys; pathlib.Path(sys.argv[1]).touch(); time.sleep(20)",
        str(ready),
    ]
    with pytest.raises(DownloadCancelled):
        run_process(command, ready.exists)
    assert ready.exists()


def test_process_kills_child_that_ignores_termination(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    import subprocess

    import pytest

    from shokz_refill.media import DownloadCancelled, run_process

    class StubbornProcess:
        terminated = False
        killed = False
        reaped = False

        def poll(self):  # type: ignore[no-untyped-def]
            return 0 if self.reaped else None

        def terminate(self):  # type: ignore[no-untyped-def]
            self.terminated = True

        def kill(self):  # type: ignore[no-untyped-def]
            self.killed = True

        def wait(self, timeout=None):  # type: ignore[no-untyped-def]
            if not self.killed:
                raise subprocess.TimeoutExpired("fake", timeout)
            self.reaped = True
            return 0

    child = StubbornProcess()
    monkeypatch.setattr("shokz_refill.media.subprocess.Popen", lambda *a, **k: child)
    checks = 0

    def cancelled() -> bool:
        nonlocal checks
        checks += 1
        return checks > 1

    with pytest.raises(DownloadCancelled):
        run_process(["fake"], cancelled)
    assert child.terminated and child.killed and child.reaped
