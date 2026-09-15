"""Telegram notification remains fail-safe when Windows networking stalls."""
import json
import time

from desk import telegram_notify


def _secrets(tmp_path):
    path = tmp_path / "telegram.json"
    path.write_text(json.dumps({"bot_token": "test-token", "chat_id": "1"}),
                    encoding="utf-8")
    return path


def test_send_message_has_hard_wall_clock_timeout(tmp_path, monkeypatch):
    def stalled(*args, **kwargs):
        time.sleep(0.5)
        raise AssertionError("stalled call should outlive the hard timeout")

    monkeypatch.setattr(telegram_notify.urllib.request, "urlopen", stalled)
    started = time.monotonic()
    ok, err = telegram_notify.send_message(
        "test", secrets_path=_secrets(tmp_path), timeout=0.05)

    assert not ok
    assert "timed out" in err
    assert time.monotonic() - started < 0.3
