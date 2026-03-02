"""pesa-cli test suite — no real Daraja calls."""
from __future__ import annotations

import json
import os
import pytest
from pathlib import Path
from typer.testing import CliRunner
from unittest.mock import patch, MagicMock

from pesa_cli.cli import app, load_config, save_config, _normalise_phone, _stk_password

runner = CliRunner()


class TestPhoneNormalisation:
    def test_07_prefix(self):
        assert _normalise_phone("0712345678") == "254712345678"

    def test_254_prefix(self):
        assert _normalise_phone("254712345678") == "254712345678"

    def test_plus_prefix(self):
        assert _normalise_phone("+254712345678") == "254712345678"

    def test_9_digit(self):
        assert _normalise_phone("712345678") == "254712345678"

    def test_spaces_stripped(self):
        assert _normalise_phone("0712 345 678") == "254712345678"


class TestSTKPassword:
    def test_password_is_base64(self):
        import base64
        pwd = _stk_password("174379", "testpasskey123", "20240115143022")
        decoded = base64.b64decode(pwd).decode()
        assert "174379" in decoded
        assert "testpasskey123" in decoded
        assert "20240115143022" in decoded

    def test_password_deterministic(self):
        p1 = _stk_password("174379", "passkey", "20240115143022")
        p2 = _stk_password("174379", "passkey", "20240115143022")
        assert p1 == p2


class TestConfig:
    def test_load_empty_config(self, tmp_path):
        with patch("pesa_cli.cli._config_path", return_value=tmp_path / "config.json"):
            cfg = load_config()
        assert cfg == {}

    def test_save_and_load_roundtrip(self, tmp_path):
        path = tmp_path / "config.json"
        with patch("pesa_cli.cli._config_path", return_value=path):
            save_config({"consumer_key": "test_key", "environment": "sandbox"})
            cfg = load_config()
        assert cfg["consumer_key"] == "test_key"
        assert cfg["environment"] == "sandbox"

    def test_config_file_permissions(self, tmp_path):
        path = tmp_path / "config.json"
        with patch("pesa_cli.cli._config_path", return_value=path):
            save_config({"consumer_key": "secret"})
        # Owner read/write only
        mode = oct(path.stat().st_mode)[-3:]
        assert mode == "600"


class TestConfigCommand:
    def test_config_set(self, tmp_path):
        path = tmp_path / "config.json"
        with patch("pesa_cli.cli._config_path", return_value=path):
            result = runner.invoke(app, ["config", "set", "--key", "consumer-key", "--value", "MY_KEY"])
        assert result.exit_code == 0
        assert "Set" in result.output

    def test_config_show_empty(self, tmp_path):
        with patch("pesa_cli.cli._config_path", return_value=tmp_path / "config.json"):
            result = runner.invoke(app, ["config", "show"])
        assert result.exit_code == 0

    def test_config_set_invalid_key(self, tmp_path):
        path = tmp_path / "config.json"
        with patch("pesa_cli.cli._config_path", return_value=path):
            result = runner.invoke(app, ["config", "set", "--key", "invalid-key", "--value", "val"])
        assert result.exit_code != 0 or "Unknown key" in result.output

    def test_config_show_masks_secrets(self, tmp_path):
        path = tmp_path / "config.json"
        with patch("pesa_cli.cli._config_path", return_value=path):
            save_config({"consumer_key": "verysecretkey123", "environment": "sandbox"})
            result = runner.invoke(app, ["config", "show"])
        assert "verysecretkey123" not in result.output
        assert "sandbox" in result.output


class TestAuthCommand:
    def _mock_credentials(self, tmp_path):
        path = tmp_path / "config.json"
        save_config_fn = lambda: None
        cfg = {
            "consumer_key": "test_key",
            "consumer_secret": "test_secret",
            "environment": "sandbox",
        }
        return cfg, path

    def test_auth_success(self, tmp_path):
        path = tmp_path / "config.json"
        with patch("pesa_cli.cli._config_path", return_value=path):
            save_config({"consumer_key": "k", "consumer_secret": "s", "environment": "sandbox"})
            with patch("pesa_cli.cli._get_token", return_value="mock_token_abc123"):
                result = runner.invoke(app, ["auth"])
        assert result.exit_code == 0
        assert "Authenticated" in result.output

    def test_auth_shows_environment(self, tmp_path):
        path = tmp_path / "config.json"
        with patch("pesa_cli.cli._config_path", return_value=path):
            save_config({"consumer_key": "k", "consumer_secret": "s", "environment": "production"})
            with patch("pesa_cli.cli._get_token", return_value="tok"):
                result = runner.invoke(app, ["auth"])
        assert "production" in result.output

    def test_auth_failure(self, tmp_path):
        path = tmp_path / "config.json"
        with patch("pesa_cli.cli._config_path", return_value=path):
            save_config({"consumer_key": "k", "consumer_secret": "s"})
            with patch("pesa_cli.cli._get_token", side_effect=Exception("401 Unauthorized")):
                result = runner.invoke(app, ["auth"])
        assert result.exit_code != 0 or "failed" in result.output.lower()

    def test_auth_missing_credentials(self, tmp_path):
        path = tmp_path / "config.json"
        with patch("pesa_cli.cli._config_path", return_value=path):
            result = runner.invoke(app, ["auth"])
        assert result.exit_code != 0 or "Missing" in result.output


class TestSTKPush:
    def _setup(self, tmp_path):
        path = tmp_path / "config.json"
        save_config_at = lambda: None
        cfg = {
            "consumer_key": "key", "consumer_secret": "secret",
            "shortcode": "174379", "passkey": "testpasskey",
            "environment": "sandbox",
        }
        return path, cfg

    def test_stk_push_success(self, tmp_path):
        path, cfg = self._setup(tmp_path)
        with patch("pesa_cli.cli._config_path", return_value=path):
            with open(path, "w") as f: json.dump(cfg, f)
            path.chmod(0o600)
            with patch("pesa_cli.cli._get_token", return_value="tok"),                  patch("pesa_cli.cli._daraja_post", return_value={
                     "ResponseCode": "0",
                     "CheckoutRequestID": "ws_CO_TEST123",
                     "MerchantRequestID": "29115-1",
                 }):
                result = runner.invoke(app, ["stk", "push", "0712345678", "100"])
        assert result.exit_code == 0
        assert "STK Push sent" in result.output or "sent" in result.output.lower()

    def test_stk_push_truncates_ref_at_12_chars(self, tmp_path):
        path, cfg = self._setup(tmp_path)
        captured_payload = {}
        def mock_post(endpoint, payload, token):
            captured_payload.update(payload)
            return {"ResponseCode": "0", "CheckoutRequestID": "ws_CO_X"}
        with patch("pesa_cli.cli._config_path", return_value=path):
            with open(path, "w") as f: json.dump(cfg, f)
            path.chmod(0o600)
            with patch("pesa_cli.cli._get_token", return_value="tok"),                  patch("pesa_cli.cli._daraja_post", side_effect=mock_post):
                runner.invoke(app, ["stk", "push", "0712345678", "100",
                                   "--ref", "ThisIsAVeryLongReference"])
        assert len(captured_payload.get("AccountReference", "")) <= 12

    def test_stk_push_invalid_phone(self, tmp_path):
        result = runner.invoke(app, ["stk", "push", "12345", "100"])
        assert result.exit_code != 0 or "Invalid" in result.output


class TestSTKQuery:
    def test_stk_query_success(self, tmp_path):
        path = tmp_path / "config.json"
        cfg = {"consumer_key": "k", "consumer_secret": "s",
               "shortcode": "174379", "passkey": "pk"}
        with open(path, "w") as f: json.dump(cfg, f)
        path.chmod(0o600)
        with patch("pesa_cli.cli._config_path", return_value=path),              patch("pesa_cli.cli._get_token", return_value="tok"),              patch("pesa_cli.cli._daraja_post", return_value={
                 "ResultCode": "0",
                 "ResultDesc": "The service request is processed successfully.",
             }):
            result = runner.invoke(app, ["stk", "query", "ws_CO_TEST"])
        assert result.exit_code == 0

    def test_stk_query_user_cancelled(self, tmp_path):
        path = tmp_path / "config.json"
        cfg = {"consumer_key": "k", "consumer_secret": "s",
               "shortcode": "174379", "passkey": "pk"}
        with open(path, "w") as f: json.dump(cfg, f)
        path.chmod(0o600)
        with patch("pesa_cli.cli._config_path", return_value=path),              patch("pesa_cli.cli._get_token", return_value="tok"),              patch("pesa_cli.cli._daraja_post", return_value={
                 "ResultCode": "1032",
                 "ResultDesc": "Request cancelled by user",
             }):
            result = runner.invoke(app, ["stk", "query", "ws_CO_TEST"])
        assert "1032" in result.output or "cancel" in result.output.lower()


class TestHelpText:
    def test_main_help(self):
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "auth" in result.output
        assert "stk" in result.output
        assert "b2c" in result.output
        assert "balance" in result.output

    def test_stk_help(self):
        result = runner.invoke(app, ["stk", "--help"])
        assert result.exit_code == 0
        assert "push" in result.output
        assert "query" in result.output

    def test_config_help(self):
        result = runner.invoke(app, ["config", "--help"])
        assert result.exit_code == 0
