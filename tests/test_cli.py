"""Tests for pesa-cli — config and normalize logic without live calls."""
import os
import pytest
from typer.testing import CliRunner
from pesa_cli import app
from pesa_cli.main import _normalize

runner = CliRunner()

def test_normalize_07xx():
    assert _normalize("0712345678") == "254712345678"

def test_normalize_plus():
    assert _normalize("+254712345678") == "254712345678"

def test_normalize_already_254():
    assert _normalize("254712345678") == "254712345678"

def test_normalize_no_leading_zero():
    assert _normalize("712345678") == "254712345678"

def test_config_no_env():
    env = {k: v for k, v in os.environ.items() if "MPESA" not in k}
    result = runner.invoke(app, ["config"], env=env)
    assert result.exit_code == 0
    assert "(not set)" in result.output

def test_config_with_env():
    env = {
        "MPESA_SHORTCODE":    "174379",
        "MPESA_SANDBOX":      "true",
        "MPESA_CONSUMER_KEY": "sk_test_abcd1234",
        "MPESA_CALLBACK_URL": "https://example.com/cb",
        **{k: v for k, v in os.environ.items()},
    }
    result = runner.invoke(app, ["config"], env=env)
    assert result.exit_code == 0
    assert "174379" in result.output
    assert "SANDBOX" in result.output
    # Key should be masked
    assert "sk_test_abcd1234" not in result.output

def test_stk_push_missing_env():
    env = {k: v for k, v in os.environ.items() if "MPESA" not in k}
    result = runner.invoke(app, [
        "stk-push", "--phone", "0712345678", "--amount", "100"
    ], env=env)
    assert result.exit_code != 0 or "not set" in result.output

def test_help():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "stk-push" in result.output

def test_stk_push_help():
    result = runner.invoke(app, ["stk-push", "--help"])
    assert "phone" in result.output.lower()
    assert "amount" in result.output.lower()
