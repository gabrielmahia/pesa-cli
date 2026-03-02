"""
pesa-cli — Command-line tool for M-Pesa Daraja v3.

Commands:
    pesa auth        Test credentials and show token expiry
    pesa stk         Initiate STK Push to a phone number
    pesa stk query   Poll the status of an STK Push
    pesa b2c         Send money to a phone (B2C)
    pesa balance     Check account balance
    pesa config      View or set credentials

Credentials are stored in ~/.pesa/config.json (or PESA_CONFIG env var).
All sensitive values can also be provided as environment variables:
    DARAJA_CONSUMER_KEY, DARAJA_CONSUMER_SECRET, DARAJA_SHORTCODE,
    DARAJA_PASSKEY, DARAJA_ENV (sandbox | production)

Usage:
    pesa config set --key consumer-key --value YOUR_KEY
    pesa auth
    pesa stk 0712345678 500 --ref "Order001" --desc "Payment"
    pesa stk query ws_CO_...
    pesa b2c 0712345678 1000 --remarks "Disbursement"
    pesa balance
"""
from __future__ import annotations

import json
import os
import sys
import time
import hashlib
import base64
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime
from pathlib import Path
from typing import Optional

import typer
from rich import print as rprint
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text

app = typer.Typer(
    name="pesa",
    help="M-Pesa Daraja v3 command-line tool.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)
stk_app = typer.Typer(help="STK Push operations.", no_args_is_help=True)
app.add_typer(stk_app, name="stk")

console = Console()


# ── Config management ──────────────────────────────────────────────────────────

DEFAULT_CONFIG_PATH = Path.home() / ".pesa" / "config.json"

CREDENTIAL_KEYS = [
    "consumer_key", "consumer_secret", "shortcode",
    "passkey", "initiator_name", "security_credential",
    "environment",  # sandbox | production
]


def _config_path() -> Path:
    env_path = os.environ.get("PESA_CONFIG")
    return Path(env_path) if env_path else DEFAULT_CONFIG_PATH


def load_config() -> dict:
    path = _config_path()
    if path.exists():
        return json.loads(path.read_text())
    return {}


def save_config(cfg: dict) -> None:
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cfg, indent=2))
    path.chmod(0o600)  # Owner read/write only — credentials file


def get_credential(key: str) -> Optional[str]:
    """Resolve credential: env var > config file."""
    env_key = f"DARAJA_{key.upper()}"
    val = os.environ.get(env_key)
    if val:
        return val
    cfg = load_config()
    return cfg.get(key)


def require_credential(key: str, label: str) -> str:
    val = get_credential(key)
    if not val:
        rprint(f"[red]✗[/red] Missing {label}. Run [cyan]pesa config set --key {key.replace('_','-')} --value VALUE[/cyan]")
        raise typer.Exit(1)
    return val


# ── Daraja HTTP layer ──────────────────────────────────────────────────────────

def _base_url() -> str:
    env = get_credential("environment") or "sandbox"
    if env == "production":
        return "https://api.safaricom.co.ke"
    return "https://sandbox.safaricom.co.ke"


def _get_token(consumer_key: str, consumer_secret: str) -> str:
    credentials = base64.b64encode(f"{consumer_key}:{consumer_secret}".encode()).decode()
    url = f"{_base_url()}/oauth/v1/generate?grant_type=client_credentials"
    req = urllib.request.Request(url, headers={"Authorization": f"Basic {credentials}"})
    with urllib.request.urlopen(req, timeout=15) as r:
        data = json.loads(r.read())
    token = data.get("access_token")
    if not token:
        raise RuntimeError(f"No access_token in response: {data}")
    return token


def _stk_password(shortcode: str, passkey: str, timestamp: str) -> str:
    return base64.b64encode(f"{shortcode}{passkey}{timestamp}".encode()).decode()


def _daraja_post(endpoint: str, payload: dict, token: str) -> dict:
    url = f"{_base_url()}{endpoint}"
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        url, data=body,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        error_body = e.read().decode()
        try:
            return json.loads(error_body)
        except Exception:
            raise RuntimeError(f"HTTP {e.code}: {error_body[:200]}")


def _normalise_phone(raw: str) -> str:
    phone = raw.strip().replace(" ", "").lstrip("+")
    if phone.startswith("07") or phone.startswith("01"):
        phone = "254" + phone[1:]
    elif len(phone) == 9 and phone[0] == "7":
        phone = "254" + phone
    if not (phone.startswith("254") and phone.isdigit() and len(phone) == 12):
        rprint(f"[red]✗[/red] Invalid Kenyan phone number: {raw!r}")
        raise typer.Exit(1)
    return phone


# ── Commands ───────────────────────────────────────────────────────────────────

config_app = typer.Typer(help="View and set Daraja credentials.", no_args_is_help=True)
app.add_typer(config_app, name="config")


@config_app.command("show")
def config_show():
    """Show current configuration (secrets masked)."""
    cfg = load_config()
    env_overrides = {k: os.environ.get(f"DARAJA_{k.upper()}") for k in CREDENTIAL_KEYS}
    if not cfg and not any(env_overrides.values()):
        rprint("[yellow]No configuration found.[/yellow] Run [cyan]pesa config set[/cyan] to add credentials.")
        return
    table = Table(title="pesa configuration", show_header=True)
    table.add_column("Key", style="cyan")
    table.add_column("Source")
    table.add_column("Value")
    for key in CREDENTIAL_KEYS:
        env_val = env_overrides.get(key)
        cfg_val = cfg.get(key)
        val = env_val or cfg_val
        source = "env var" if env_val else ("config file" if cfg_val else "—")
        is_secret = key not in ("shortcode", "environment", "initiator_name")
        display = ("*" * 8 + val[-4:] if val and is_secret and len(val) > 4 else val or "—")
        table.add_row(key, source, display)
    console.print(table)
    rprint(f"
[dim]Config file: {_config_path()}[/dim]")


@config_app.command("set")
def config_set(
    key: str = typer.Option(..., help="Credential key (e.g. consumer-key)"),
    value: str = typer.Option(..., help="Credential value"),
):
    """Set a credential in ~/.pesa/config.json."""
    key = key.replace("-", "_")
    if key not in CREDENTIAL_KEYS:
        rprint(f"[red]✗[/red] Unknown key {key!r}. Valid keys: {CREDENTIAL_KEYS}")
        raise typer.Exit(1)
    cfg = load_config()
    cfg[key] = value
    save_config(cfg)
    rprint(f"[green]✓[/green] Set [cyan]{key}[/cyan]")


@app.command()
def auth():
    """Test credentials — fetch an OAuth token and show expiry."""
    consumer_key    = require_credential("consumer_key",    "Consumer Key")
    consumer_secret = require_credential("consumer_secret", "Consumer Secret")
    with console.status("Authenticating..."):
        try:
            token = _get_token(consumer_key, consumer_secret)
        except Exception as e:
            rprint(f"[red]✗ Authentication failed:[/red] {e}")
            raise typer.Exit(1)
    env = get_credential("environment") or "sandbox"
    rprint(Panel(
        f"[green]✓ Authenticated[/green]
"
        f"Environment: [cyan]{env}[/cyan]
"
        f"Token: [dim]{token[:12]}...{token[-4:]}[/dim]
"
        f"Expires in: [cyan]~60 minutes[/cyan]",
        title="pesa auth", border_style="green",
    ))


@stk_app.command("push")
def stk_push(
    phone: str = typer.Argument(..., help="Kenyan phone number (any format)"),
    amount: int = typer.Argument(..., help="Amount in KES (must be integer)"),
    ref: str = typer.Option("pesa-cli", "--ref", help="AccountReference (max 12 chars)"),
    desc: str = typer.Option("Payment", "--desc", help="TransactionDesc"),
):
    """Initiate an STK Push payment request."""
    phone = _normalise_phone(phone)
    consumer_key    = require_credential("consumer_key",    "Consumer Key")
    consumer_secret = require_credential("consumer_secret", "Consumer Secret")
    shortcode       = require_credential("shortcode",       "Shortcode")
    passkey         = require_credential("passkey",         "Passkey")
    callback_url    = get_credential("callback_url") or "https://example.com/mpesa/callback"
    ref = ref[:12]  # Daraja hard limit

    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    password  = _stk_password(shortcode, passkey, timestamp)

    with console.status(f"Sending STK Push to +{phone}..."):
        try:
            token = _get_token(consumer_key, consumer_secret)
            response = _daraja_post("/mpesa/stkpush/v1/processrequest", {
                "BusinessShortCode": shortcode,
                "Password":          password,
                "Timestamp":         timestamp,
                "TransactionType":   "CustomerPayBillOnline",
                "Amount":            amount,
                "PartyA":            phone,
                "PartyB":            shortcode,
                "PhoneNumber":       phone,
                "CallBackURL":       callback_url,
                "AccountReference":  ref,
                "TransactionDesc":   desc,
            }, token)
        except Exception as e:
            rprint(f"[red]✗ STK Push failed:[/red] {e}")
            raise typer.Exit(1)

    if response.get("ResponseCode") == "0":
        checkout_id = response.get("CheckoutRequestID", "")
        rprint(Panel(
            f"[green]✓ STK Push sent[/green]
"
            f"Phone:       [cyan]+{phone}[/cyan]
"
            f"Amount:      [cyan]KES {amount:,}[/cyan]
"
            f"Reference:   [cyan]{ref}[/cyan]
"
            f"Checkout ID: [dim]{checkout_id}[/dim]

"
            f"[dim]The customer will receive a PIN prompt on their phone.[/dim]
"
            f"[dim]Run: pesa stk query {checkout_id}[/dim]",
            title="STK Push", border_style="green",
        ))
    else:
        rprint(Panel(
            f"[red]✗ Request rejected[/red]
{json.dumps(response, indent=2)}",
            title="STK Push", border_style="red",
        ))
        raise typer.Exit(1)


@stk_app.command("query")
def stk_query(
    checkout_id: str = typer.Argument(..., help="CheckoutRequestID from stk push"),
):
    """Poll the status of an STK Push request."""
    consumer_key    = require_credential("consumer_key",    "Consumer Key")
    consumer_secret = require_credential("consumer_secret", "Consumer Secret")
    shortcode       = require_credential("shortcode",       "Shortcode")
    passkey         = require_credential("passkey",         "Passkey")

    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    password  = _stk_password(shortcode, passkey, timestamp)

    with console.status("Querying status..."):
        try:
            token    = _get_token(consumer_key, consumer_secret)
            response = _daraja_post("/mpesa/stkpushquery/v1/query", {
                "BusinessShortCode": shortcode,
                "Password":          password,
                "Timestamp":         timestamp,
                "CheckoutRequestID": checkout_id,
            }, token)
        except Exception as e:
            rprint(f"[red]✗ Query failed:[/red] {e}")
            raise typer.Exit(1)

    result_code = response.get("ResultCode", "?")
    result_desc = response.get("ResultDesc", "Unknown")
    STATUS_COLORS = {"0": "green", "1032": "yellow", "1037": "yellow"}
    color = STATUS_COLORS.get(str(result_code), "red")
    symbol = "✓" if str(result_code) == "0" else "✗"
    rprint(Panel(
        f"[{color}]{symbol} {result_desc}[/{color}]
"
        f"Result Code: [cyan]{result_code}[/cyan]
"
        f"Checkout ID: [dim]{checkout_id}[/dim]",
        title="STK Query", border_style=color,
    ))


@app.command()
def b2c(
    phone: str = typer.Argument(..., help="Recipient phone number"),
    amount: int = typer.Argument(..., help="Amount in KES"),
    remarks: str = typer.Option("Payment", "--remarks", help="Transaction remarks"),
    occasion: str = typer.Option("", "--occasion", help="Optional occasion"),
):
    """Send money from shortcode to a phone number (B2C)."""
    phone = _normalise_phone(phone)
    consumer_key      = require_credential("consumer_key",          "Consumer Key")
    consumer_secret   = require_credential("consumer_secret",       "Consumer Secret")
    shortcode         = require_credential("shortcode",              "Shortcode")
    initiator         = require_credential("initiator_name",         "Initiator Name")
    security_cred     = require_credential("security_credential",    "Security Credential")
    result_url        = get_credential("result_url")    or "https://example.com/b2c/result"
    timeout_url       = get_credential("timeout_url")   or "https://example.com/b2c/timeout"

    with console.status(f"Sending KES {amount:,} to +{phone}..."):
        try:
            token    = _get_token(consumer_key, consumer_secret)
            response = _daraja_post("/mpesa/b2c/v3/paymentrequest", {
                "InitiatorName":      initiator,
                "SecurityCredential": security_cred,
                "CommandID":          "BusinessPayment",
                "Amount":             amount,
                "PartyA":             shortcode,
                "PartyB":             f"+{phone}",
                "Remarks":            remarks,
                "QueueTimeOutURL":    timeout_url,
                "ResultURL":          result_url,
                "Occasion":           occasion,
                "OriginatorConversationID": f"pesa-cli-{int(time.time())}",
            }, token)
        except Exception as e:
            rprint(f"[red]✗ B2C failed:[/red] {e}")
            raise typer.Exit(1)

    if response.get("ResponseCode") == "0":
        rprint(Panel(
            f"[green]✓ B2C request accepted[/green]
"
            f"Phone:           [cyan]+{phone}[/cyan]
"
            f"Amount:          [cyan]KES {amount:,}[/cyan]
"
            f"Conversation ID: [dim]{response.get('ConversationID', '')}[/dim]

"
            f"[dim]Result will be posted to your ResultURL.[/dim]",
            title="B2C", border_style="green",
        ))
    else:
        rprint(Panel(
            f"[red]✗ B2C rejected[/red]
{json.dumps(response, indent=2)}",
            title="B2C", border_style="red",
        ))
        raise typer.Exit(1)


@app.command()
def balance():
    """Check account balance for the configured shortcode."""
    consumer_key    = require_credential("consumer_key",          "Consumer Key")
    consumer_secret = require_credential("consumer_secret",       "Consumer Secret")
    shortcode       = require_credential("shortcode",              "Shortcode")
    initiator       = require_credential("initiator_name",         "Initiator Name")
    security_cred   = require_credential("security_credential",    "Security Credential")
    result_url      = get_credential("result_url")  or "https://example.com/balance/result"
    timeout_url     = get_credential("timeout_url") or "https://example.com/balance/timeout"

    with console.status("Requesting balance..."):
        try:
            token    = _get_token(consumer_key, consumer_secret)
            response = _daraja_post("/mpesa/accountbalance/v1/query", {
                "InitiatorName":      initiator,
                "SecurityCredential": security_cred,
                "CommandID":          "AccountBalance",
                "PartyA":             shortcode,
                "IdentifierType":     "4",
                "Remarks":            "Balance query from pesa-cli",
                "QueueTimeOutURL":    timeout_url,
                "ResultURL":          result_url,
            }, token)
        except Exception as e:
            rprint(f"[red]✗ Balance query failed:[/red] {e}")
            raise typer.Exit(1)

    if response.get("ResponseCode") == "0":
        rprint(Panel(
            f"[green]✓ Balance request accepted[/green]
"
            f"Shortcode:       [cyan]{shortcode}[/cyan]
"
            f"Conversation ID: [dim]{response.get('ConversationID', '')}[/dim]

"
            f"[dim]Balance will be posted to your ResultURL asynchronously.[/dim]",
            title="Account Balance", border_style="green",
        ))
    else:
        rprint(Panel(
            f"[red]✗ Request rejected[/red]
{json.dumps(response, indent=2)}",
            title="Account Balance", border_style="red",
        ))
        raise typer.Exit(1)
