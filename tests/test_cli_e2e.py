"""End-to-end tests of the CLI that actually ships (`pesa = "pesa_cli.cli:app"`), driven against the daraja-mock test server.

Why this exists: pesa_cli/cli.py had a SyntaxError from its first commit, so the published `pesa` command could not start, while the old tests passed because
they imported a sibling module (pesa_cli.main). These tests exercise the real entry point, every command, and the documented PESA_BASE_URL override."""
import importlib
import py_compile
import re
import socket
from pathlib import Path

import pytest
from typer.testing import CliRunner

from daraja_mock import DarajaMock

ROOT = Path(__file__).resolve().parents[1]
runner = CliRunner()


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def mock():
    m = DarajaMock(consumer_key="testkey", consumer_secret="testsecret")
    m.base_url = m.run_thread(port=_free_port())
    return m


@pytest.fixture
def env(mock, tmp_path):
    mock.reset()
    return {
        "PESA_BASE_URL": mock.base_url, "PESA_CONFIG": str(tmp_path / "cfg.json"),
        "DARAJA_CONSUMER_KEY": "testkey", "DARAJA_CONSUMER_SECRET": "testsecret", "DARAJA_SHORTCODE": "174379", "DARAJA_PASSKEY": "testpasskey",
        "DARAJA_INITIATOR_NAME": "testapi", "DARAJA_SECURITY_CREDENTIAL": "testcred",
    }


def _app():
    return importlib.import_module("pesa_cli.cli").app


def _posts(mock, path):
    return [e for e in mock.request_log() if e["path"] == path]


# ── guards against shipping something that cannot start ────────────────────────────────────────────────────────────────
def test_every_module_in_the_package_compiles():
    for f in sorted((ROOT / "pesa_cli").glob("*.py")):
        py_compile.compile(str(f), doraise=True)


def test_the_declared_entry_point_resolves():
    target = re.search(r'^\s*pesa\s*=\s*"([\w.]+):(\w+)"', (ROOT / "pyproject.toml").read_text(encoding="utf-8"), re.M)
    assert target, "no `pesa` entry point in pyproject.toml"
    assert getattr(importlib.import_module(target.group(1)), target.group(2)) is _app()


def test_help_lists_every_command():
    out = runner.invoke(_app(), ["--help"]).output
    for cmd in ("auth", "b2c", "balance", "stk", "config"):
        assert cmd in out


# ── every command against the mock ────────────────────────────────────────────────────────────────────────────────────
def test_auth(mock, env):
    r = runner.invoke(_app(), ["auth"], env=env)
    assert r.exit_code == 0 and "Authenticated" in r.output
    assert _posts(mock, "/oauth/v1/generate")


def test_stk_push_sends_the_normalised_payload(mock, env):
    r = runner.invoke(_app(), ["stk", "push", "0712345678", "100", "--ref", "E2E"], env=env)
    assert r.exit_code == 0 and "STK Push sent" in r.output
    body = _posts(mock, "/mpesa/stkpush/v1/processrequest")[-1]["body"]
    assert str(body["PhoneNumber"]) == "254712345678" and str(body["Amount"]) == "100" and body["AccountReference"] == "E2E"


def test_stk_query_reports_success_and_cancellation(mock, env):
    ok = runner.invoke(_app(), ["stk", "query", "ws_CO_TEST"], env=env)
    assert ok.exit_code == 0 and "Result Code: 0" in ok.output
    mock.set_stk_result(1032)
    cancelled = runner.invoke(_app(), ["stk", "query", "ws_CO_TEST"], env=env)
    assert "Result Code: 1032" in cancelled.output


def test_b2c_and_balance_are_accepted(mock, env):
    assert "B2C request accepted" in runner.invoke(_app(), ["b2c", "0712345678", "50"], env=env).output
    assert "Balance request accepted" in runner.invoke(_app(), ["balance"], env=env).output
    assert _posts(mock, "/mpesa/b2c/v3/paymentrequest") and _posts(mock, "/mpesa/accountbalance/v1/query")


def test_missing_credentials_fail_cleanly(env):
    bare = {k: "" for k in env if k.startswith("DARAJA_")}
    bare.update(PESA_BASE_URL=env["PESA_BASE_URL"], PESA_CONFIG=env["PESA_CONFIG"])
    r = runner.invoke(_app(), ["stk", "push", "0712345678", "100"], env=bare)
    assert r.exit_code == 1 and "Traceback" not in r.output


@pytest.mark.parametrize("raw,expected", [("0712345678", "254712345678"), ("+254712345678", "254712345678"), ("712345678", "254712345678"),
                                          ("0112345678", "254112345678"), ("+254110123456", "254110123456")])
def test_phone_normalisation(raw, expected):
    assert importlib.import_module("pesa_cli.cli")._normalise_phone(raw) == expected


def test_invalid_phone_is_rejected():
    import typer

    with pytest.raises(typer.Exit):
        importlib.import_module("pesa_cli.cli")._normalise_phone("12345")
