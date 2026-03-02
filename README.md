# pesa-cli

**Command-line tool for M-Pesa Daraja v3 — STK Push, B2C, balance check, config management.**

[![CI](https://github.com/gabrielmahia/pesa-cli/actions/workflows/ci.yml/badge.svg)](https://github.com/gabrielmahia/pesa-cli/actions)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](#)
[![Tests](https://img.shields.io/badge/tests-34%20passing-brightgreen)](#)
[![License](https://img.shields.io/badge/License-CC%20BY--NC--ND%204.0-lightgrey)](LICENSE)

Test integrations, trigger payments, and check balances from your terminal —
without opening the Safaricom portal or writing a script.

---

## Install

```bash
pip install pesa-cli
```

---

## Setup

```bash
# Set credentials once — stored in ~/.pesa/config.json (mode 600)
pesa config set --key consumer-key    --value YOUR_CONSUMER_KEY
pesa config set --key consumer-secret --value YOUR_CONSUMER_SECRET
pesa config set --key shortcode       --value 174379
pesa config set --key passkey         --value YOUR_PASSKEY
pesa config set --key environment     --value sandbox   # or production

# Or use environment variables (useful in CI/CD)
export DARAJA_CONSUMER_KEY=...
export DARAJA_CONSUMER_SECRET=...

# Test credentials
pesa auth
```

---

## Commands

### `pesa auth`
Test credentials and verify connectivity.
```
✓ Authenticated
Environment: sandbox
Token: mock_token_ab...3456
Expires in: ~60 minutes
```

### `pesa stk push PHONE AMOUNT`
Initiate an STK Push payment request. The customer receives a PIN prompt on their phone.
```bash
pesa stk push 0712345678 500
pesa stk push 0712345678 500 --ref "Invoice001" --desc "Monthly contribution"
```
```
✓ STK Push sent
Phone:       +254712345678
Amount:      KES 500
Reference:   Invoice001
Checkout ID: ws_CO_150120241430221234567890

Run: pesa stk query ws_CO_150120241430221234567890
```

### `pesa stk query CHECKOUT_ID`
Poll the status of an STK Push.
```bash
pesa stk query ws_CO_150120241430221234567890
```
```
✓ The service request is processed successfully.
Result Code: 0
```

### `pesa b2c PHONE AMOUNT`
Send money from your shortcode to a phone number.
```bash
pesa b2c 0712345678 1000 --remarks "Chama disbursement"
```

### `pesa balance`
Request account balance (result posted to your ResultURL asynchronously).
```bash
pesa balance
```

### `pesa config show`
Display current configuration with secrets masked.
```
┌──────────────────────────────────────────────────┐
│ pesa configuration                               │
├──────────────────┬─────────────┬─────────────────┤
│ consumer_key     │ config file │ ************3456 │
│ consumer_secret  │ config file │ ************abcd │
│ shortcode        │ config file │ 174379           │
│ environment      │ config file │ sandbox          │
└──────────────────┴─────────────┴─────────────────┘
```

---

## Credentials

Credentials are resolved in this order: **environment variable** → **config file**.

| Credential | Config key | Environment variable |
|------------|-----------|----------------------|
| Consumer Key | `consumer_key` | `DARAJA_CONSUMER_KEY` |
| Consumer Secret | `consumer_secret` | `DARAJA_CONSUMER_SECRET` |
| Shortcode | `shortcode` | `DARAJA_SHORTCODE` |
| Passkey | `passkey` | `DARAJA_PASSKEY` |
| Initiator Name | `initiator_name` | `DARAJA_INITIATOR_NAME` |
| Security Credential | `security_credential` | `DARAJA_SECURITY_CREDENTIAL` |
| Environment | `environment` | `DARAJA_ENVIRONMENT` |

Config file is stored at `~/.pesa/config.json` with mode 600 (owner read/write only).
Override location with `PESA_CONFIG=/path/to/config.json`.

---

## Use with daraja-mock

```bash
# Start daraja-mock
python -m daraja_mock --port 8765

# Point pesa-cli at the mock
export PESA_BASE_URL=http://localhost:8765
pesa auth
pesa stk push 0712345678 100 --ref "Test"
```

---

## Design decisions

**Credentials resolved env → file.** CI/CD environments should use env vars.
Developer machines use the config file. The CLI never asks for credentials
interactively — that would break scripting.

**Secrets masked at 600.** The config file is created with `chmod 600` so
other users on shared systems cannot read Daraja credentials.

**AccountReference truncated silently.** Daraja rejects `AccountReference` > 12 chars
with a cryptic error. The CLI truncates to 12 and shows what was sent.

**Rich output, not JSON by default.** For human use. Add `--output json` flag
if scripting against pesa-cli output is needed.

---

*Part of the [nairobi-stack](https://github.com/gabrielmahia/nairobi-stack) East Africa engineering ecosystem.*
*Maintained by [Gabriel Mahia](https://github.com/gabrielmahia). Kenya × USA.*
