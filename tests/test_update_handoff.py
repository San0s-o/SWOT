from __future__ import annotations

import importlib
import sys
import types

if "requests" not in sys.modules:
    sys.modules["requests"] = types.SimpleNamespace(RequestException=Exception)

uh = importlib.import_module("app.services.update_handoff")
us = importlib.import_module("app.services.update_service")


def _sample_check_result() -> us.UpdateCheckResult:
    return us.UpdateCheckResult(
        checked=True,
        update_available=True,
        current_version="1.0.0",
        latest_version="1.0.1",
        release=us.ReleaseInfo(
            version="1.0.1",
            tag_name="v1.0.1",
            name="v1.0.1",
            body="notes",
            html_url="https://github.com/x/y/releases/tag/v1.0.1",
            published_at="2026-01-01T00:00:00Z",
            asset=us.ReleaseAsset(
                name="setup.zip",
                download_url="https://github.com/x/y/releases/download/v1.0.1/setup.zip",
            ),
            checksum_asset=us.ReleaseAsset(
                name="setup.zip.sha256",
                download_url="https://github.com/x/y/releases/download/v1.0.1/setup.zip.sha256",
            ),
        ),
        message="",
    )


def test_write_and_load_updater_state_roundtrip(tmp_path) -> None:
    original = _sample_check_result()
    state_path = uh.write_updater_state(original, state_dir=tmp_path)
    loaded = uh.load_updater_state(state_path)

    assert loaded.checked is True
    assert loaded.update_available is True
    assert loaded.current_version == "1.0.0"
    assert loaded.latest_version == "1.0.1"
    assert loaded.release is not None
    assert loaded.release.asset is not None
    assert loaded.release.asset.name == "setup.zip"
    assert loaded.release.checksum_asset is not None
    assert loaded.release.checksum_asset.name == "setup.zip.sha256"


def test_launch_updater_process_starts_subprocess(monkeypatch, tmp_path) -> None:
    state_path = tmp_path / "state.json"
    state_path.write_text("{}", encoding="utf-8")
    calls: dict[str, object] = {}

    monkeypatch.setattr(uh, "write_updater_state", lambda *_a, **_k: state_path)

    def _fake_popen(cmd, **kwargs):
        calls["cmd"] = cmd
        calls["kwargs"] = kwargs
        return object()

    monkeypatch.setattr(uh.subprocess, "Popen", _fake_popen)
    monkeypatch.setattr(uh.sys, "executable", r"C:\Tools\SWOT.exe")
    monkeypatch.setattr(uh.sys, "frozen", True, raising=False)

    ok, message = uh.launch_updater_process(_sample_check_result())
    assert ok is True
    assert message == ""
    assert calls["cmd"] == [r"C:\Tools\SWOT.exe", "--updater-state", str(state_path)]
    assert isinstance(calls["kwargs"], dict)
    assert calls["kwargs"].get("close_fds") is True


def test_launch_updater_process_deletes_state_file_on_failure(monkeypatch, tmp_path) -> None:
    state_path = tmp_path / "state.json"
    state_path.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(uh, "write_updater_state", lambda *_a, **_k: state_path)
    monkeypatch.setattr(uh.sys, "executable", r"C:\Tools\SWOT.exe")
    monkeypatch.setattr(uh.sys, "frozen", True, raising=False)

    def _fake_popen(*_args, **_kwargs):
        raise OSError("boom")

    monkeypatch.setattr(uh.subprocess, "Popen", _fake_popen)

    ok, message = uh.launch_updater_process(_sample_check_result())
    assert ok is False
    assert bool(message)
    assert state_path.exists() is False
