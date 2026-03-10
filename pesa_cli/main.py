"""
pesa — command-line tool for M-Pesa Daraja v3.

Commands:
  pesa stk-push   — trigger STK Push payment prompt
  pesa stk-query  — check STK Push status
  pesa b2c        — send money to phone (B2C)
  pesa balance    — check shortcode balance
  pesa config     — show/set environment configuration

Usage:
    export MPESA_CONSUMER_KEY=...
    export MPESA_CONSUMER_SECRET=...
    export MPESA_SHORTCODE=174379
    export MPESA_PASSKEY=...
    export MPESA_CALLBACK_URL=https://example.com/callback
    export MPESA_SANDBOX=true

    pesa stk-push --phone 0712345678 --amount 100 --ref "Order1"
    pesa stk-query --id ws_CO_...
    pesa balance
"""

from __future__ import annotations

import base64
import os
import sys
import time
from datetime import datetime
from typing import Optional

import requests
import typer

app = typer.Typer(
    name="pesa",
    help="Command-line tool for M-Pesa Daraja v3.",
    no_args_is_help=True,
)

_token_cache: dict = {"token": None, "expires_at": 0.0}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _base_url() -> str:
    sandbox = os.environ.get("MPESA_SANDBOX", "true").lower() == "true"
    return "https://sandbox.safaricom.co.ke" if sandbox else "https://api.safaricom.co.ke"


def _get_token() -> str:
    if time.time() < _token_cache.get("expires_at", 0) - 30:
        return _token_cache["token"]  # type: ignore[return-value]
    key    = _require("MPESA_CONSUMER_KEY")
    secret = _require("MPESA_CONSUMER_SECRET")
    creds  = base64.b64encode(f"{key}:{secret}".encode()).decode()
    resp   = requests.get(
        f"{_base_url()}/oauth/v1/generate?grant_type=client_credentials",
        headers={"Authorization": f"Basic {creds}"},
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    _token_cache["token"]      = data["access_token"]
    _token_cache["expires_at"] = time.time() + int(data["expires_in"])
    return _token_cache["token"]  # type: ignore[return-value]


def _require(var: str) -> str:
    val = os.environ.get(var)
    if not val:
        typer.echo(f"Error: {var} not set. Run: pesa config", err=True)
        raise typer.Exit(1)
    return val


def _normalize(phone: str) -> str:
    phone = phone.strip().lstrip("+").replace(" ", "")
    if phone.startswith("0"):
        phone = "254" + phone[1:]
    elif not phone.startswith("254"):
        phone = "254" + phone
    return phone


def _password_ts() -> tuple[str, str]:
    shortcode = _require("MPESA_SHORTCODE")
    passkey   = _require("MPESA_PASSKEY")
    ts        = datetime.now().strftime("%Y%m%d%H%M%S")
    pw        = base64.b64encode(f"{shortcode}{passkey}{ts}".encode()).decode()
    return pw, ts


def _post(path: str, payload: dict) -> dict:
    token = _get_token()
    resp  = requests.post(
        f"{_base_url()}{path}",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def _print_result(data: dict, success_key: str = "ResponseCode", success_val: str = "0") -> None:
    is_ok = data.get(success_key) == success_val
    icon  = "✓" if is_ok else "✗"
    for k, v in data.items():
        typer.echo(f"  {k}: {v}")
    typer.echo(f"\n{icon} {'Success' if is_ok else 'Failed'}")


# ── Commands ──────────────────────────────────────────────────────────────────

@app.command("stk-push")
def stk_push(
    phone:  str = typer.Option(..., "--phone", "-p", help="Phone number (07xx, 254xx, or +254xx)"),
    amount: int = typer.Option(..., "--amount", "-a", help="Amount in KES (whole number)"),
    ref:    str = typer.Option("Payment", "--ref", "-r", help="Account reference (max 12 chars)"),
    desc:   str = typer.Option("Payment", "--desc", "-d", help="Transaction description"),
):
    """Trigger an M-Pesa STK Push payment prompt on the customer's phone."""
    shortcode = _require("MPESA_SHORTCODE")
    callback  = _require("MPESA_CALLBACK_URL")
    pw, ts    = _password_ts()
    phone     = _normalize(phone)

    typer.echo(f"Sending STK Push: KES {amount} → {phone}")
    data = _post("/mpesa/stkpush/v1/processrequest", {
        "BusinessShortCode": shortcode,
        "Password":          pw,
        "Timestamp":         ts,
        "TransactionType":   "CustomerPayBillOnline",
        "Amount":            amount,
        "PartyA":            phone,
        "PartyB":            shortcode,
        "PhoneNumber":       phone,
        "CallBackURL":       callback,
        "AccountReference":  ref[:12],
        "TransactionDesc":   desc[:13],
    })
    _print_result(data)
    checkout_id = data.get("CheckoutRequestID")
    if checkout_id:
        typer.echo(f"\nCheckoutRequestID: {checkout_id}")
        typer.echo(f"Run: pesa stk-query --id {checkout_id}")


@app.command("stk-query")
def stk_query(
    checkout_id: str = typer.Option(..., "--id", "-i", help="CheckoutRequestID from stk-push"),
    wait:        int = typer.Option(0, "--wait", "-w", help="Seconds to wait before querying (0=immediate)"),
):
    """Check the status of an STK Push request."""
    if wait:
        typer.echo(f"Waiting {wait}s...")
        time.sleep(wait)

    shortcode = _require("MPESA_SHORTCODE")
    pw, ts    = _password_ts()

    data = _post("/mpesa/stkpushquery/v1/query", {
        "BusinessShortCode": shortcode,
        "Password":          pw,
        "Timestamp":         ts,
        "CheckoutRequestID": checkout_id,
    })

    result_code = data.get("ResultCode", "-1")
    status_map  = {
        "0":    "✓ SUCCESS",
        "1":    "✗ INSUFFICIENT FUNDS",
        "1032": "✗ CANCELLED BY USER",
        "1037": "✗ TIMED OUT",
        "2001": "✗ WRONG PIN",
    }
    typer.echo(f"Status: {status_map.get(result_code, f'Code {result_code}')}")
    typer.echo(f"Description: {data.get('ResultDesc')}")


@app.command("b2c")
def b2c(
    phone:  str = typer.Option(..., "--phone", "-p", help="Recipient phone number"),
    amount: int = typer.Option(..., "--amount", "-a", help="Amount in KES"),
    reason: str = typer.Option("SalaryPayment", "--reason", "-r",
                               help="CommandID: SalaryPayment | BusinessPayment | PromotionPayment"),
):
    """Send money from shortcode to a phone number (B2C)."""
    initiator  = _require("MPESA_INITIATOR_NAME")
    security   = _require("MPESA_SECURITY_CREDENTIAL")
    shortcode  = _require("MPESA_SHORTCODE")
    callback   = _require("MPESA_CALLBACK_URL")
    phone      = _normalize(phone)

    typer.echo(f"Sending B2C: KES {amount} → {phone}")
    data = _post("/mpesa/b2c/v3/paymentrequest", {
        "InitiatorName":        initiator,
        "SecurityCredential":   security,
        "CommandID":            reason,
        "Amount":               amount,
        "PartyA":               shortcode,
        "PartyB":               phone,
        "Remarks":              f"B2C {reason}",
        "QueueTimeOutURL":      callback,
        "ResultURL":            callback,
        "Occassion":            "",
    })
    _print_result(data)


@app.command("balance")
def balance():
    """Query the M-Pesa shortcode account balance."""
    initiator = _require("MPESA_INITIATOR_NAME")
    security  = _require("MPESA_SECURITY_CREDENTIAL")
    shortcode = _require("MPESA_SHORTCODE")
    callback  = _require("MPESA_CALLBACK_URL")

    typer.echo("Querying balance (result delivered async to callback URL)...")
    data = _post("/mpesa/accountbalance/v1/query", {
        "Initiator":          initiator,
        "SecurityCredential": security,
        "CommandID":          "AccountBalance",
        "PartyA":             shortcode,
        "IdentifierType":     "4",
        "Remarks":            "Balance query",
        "QueueTimeOutURL":    callback,
        "ResultURL":          callback,
    })
    _print_result(data)


@app.command("config")
def config():
    """Show current M-Pesa configuration (keys masked)."""
    env_vars = [
        "MPESA_CONSUMER_KEY",
        "MPESA_CONSUMER_SECRET",
        "MPESA_SHORTCODE",
        "MPESA_PASSKEY",
        "MPESA_CALLBACK_URL",
        "MPESA_INITIATOR_NAME",
        "MPESA_SANDBOX",
    ]
    typer.echo("Current pesa configuration:\n")
    for var in env_vars:
        val = os.environ.get(var)
        if val:
            if "KEY" in var or "SECRET" in var or "CREDENTIAL" in var or "PASSKEY" in var:
                display = val[:4] + "****" + val[-4:] if len(val) > 8 else "****"
            else:
                display = val
        else:
            display = "(not set)"
        typer.echo(f"  {var:<32} {display}")

    sandbox = os.environ.get("MPESA_SANDBOX", "true").lower() == "true"
    typer.echo(f"\n  Mode: {'SANDBOX' if sandbox else 'PRODUCTION'}")
    typer.echo(f"  Base URL: {_base_url()}")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
