"""
Backend – Fintoc + Google Sheets synchronization
=================================================
Framework : FastAPI
Python    : 3.9+

Flow
----
1. The Fintoc Widget (frontend/index.html) authenticates the user against
   Bancolombia, handling the MFA/Dynamic Token natively.
2. On success, the widget sends a short-lived `link_token` to POST /sync.
3. This server exchanges that token via the Fintoc SDK, fetches the last 3 days
   of movements, and appends them as new rows to a Google Sheet.

Setup
-----
See README.md for full instructions.
"""

from __future__ import annotations

import os
import logging
from datetime import date, timedelta
from typing import Any

import fintoc
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.oauth2 import service_account
from pydantic import BaseModel

# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURATION  –  edit these values or set equivalent environment variables
# ─────────────────────────────────────────────────────────────────────────────

# Your Fintoc SECRET key (starts with "sk_").
# Dashboard → Settings → API Keys → Secret key.
FINTOC_SECRET_KEY: str = os.getenv("FINTOC_SECRET_KEY", "sk_live_REPLACE_WITH_YOUR_SECRET_KEY")

# Google Sheets spreadsheet ID.
# The ID is the long string in the Sheet URL:
#   https://docs.google.com/spreadsheets/d/<SPREADSHEET_ID>/edit
SPREADSHEET_ID: str = os.getenv("SPREADSHEET_ID", "REPLACE_WITH_YOUR_SPREADSHEET_ID")

# Name (or A1 notation range) of the sheet/tab where rows will be appended.
SHEET_RANGE: str = os.getenv("SHEET_RANGE", "Movimientos!A1")

# Path to the Google Service Account credentials JSON file.
# Generate it in: Google Cloud Console → IAM & Admin → Service Accounts →
#   your account → Keys → Add Key → JSON.
# Then share the spreadsheet with the service-account e-mail address.
GOOGLE_CREDENTIALS_FILE: str = os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials.json")

# How many days back to fetch (today − DAYS_BACK).
DAYS_BACK: int = int(os.getenv("DAYS_BACK", "3"))

# Origins allowed to call this backend (add your frontend URL in production).
ALLOWED_ORIGINS: list[str] = os.getenv(
    "ALLOWED_ORIGINS", "http://localhost,http://127.0.0.1"
).split(",")

# ─────────────────────────────────────────────────────────────────────────────

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="Fintoc–Bancolombia Sync", version="1.0.0")

# Allow the frontend (served from a different origin during development) to
# reach this API.  Restrict ALLOWED_ORIGINS in production.
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["POST", "GET"],
    allow_headers=["Content-Type"],
)


# ── Request / Response models ─────────────────────────────────────────────────

class SyncRequest(BaseModel):
    link_token: str


class SyncResponse(BaseModel):
    rows_written: int
    message: str


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_fintoc_movements(link_token: str) -> list[dict[str, Any]]:
    """
    Use the Fintoc SDK to fetch bank movements.

    The SDK is initialized with the SECRET key.  The `link_token` (obtained
    from the widget) is used to retrieve the specific Link and its accounts.

    Returns a list of movement dicts with keys: id, post_date, description, amount.
    """
    if FINTOC_SECRET_KEY.startswith("sk_live_REPLACE"):
        raise ValueError(
            "FINTOC_SECRET_KEY has not been configured. "
            "Set the FINTOC_SECRET_KEY environment variable or edit main.py."
        )

    client = fintoc.Client(api_key=FINTOC_SECRET_KEY)

    # Retrieve the Link that corresponds to this widget session.
    link = client.links.get(link_token)

    since_date = date.today() - timedelta(days=DAYS_BACK)

    movements: list[dict[str, Any]] = []

    # Iterate over every account in the link (there may be multiple).
    for account in link.accounts:
        logger.info("Fetching movements for account %s (%s)", account.id, account.name)
        for movement in account.movements.all(since=since_date.isoformat()):
            movements.append(
                {
                    "id": movement.id,
                    "post_date": str(movement.post_date)[:10],  # YYYY-MM-DD
                    "description": movement.description,
                    "amount": movement.amount,
                    "currency": getattr(movement, "currency", "COP"),
                }
            )

    logger.info("Fetched %d total movement(s) from Fintoc.", len(movements))
    return movements


def _append_to_google_sheets(movements: list[dict[str, Any]]) -> int:
    """
    Authenticate with the Google Sheets API via a Service Account and append
    the movements as new rows.

    Returns the number of rows written.
    """
    if SPREADSHEET_ID.startswith("REPLACE"):
        raise ValueError(
            "SPREADSHEET_ID has not been configured. "
            "Set the SPREADSHEET_ID environment variable or edit main.py."
        )

    if not os.path.exists(GOOGLE_CREDENTIALS_FILE):
        raise FileNotFoundError(
            f"Google credentials file not found at '{GOOGLE_CREDENTIALS_FILE}'. "
            "Download it from Google Cloud Console and place it next to main.py."
        )

    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    credentials = service_account.Credentials.from_service_account_file(
        GOOGLE_CREDENTIALS_FILE, scopes=scopes
    )
    service = build("sheets", "v4", credentials=credentials)

    # Build the 2-D array of values to append.
    # Column order: Transaction ID | Date | Description | Amount | Currency
    rows: list[list[Any]] = [
        [m["id"], m["post_date"], m["description"], m["amount"], m["currency"]]
        for m in movements
    ]

    if not rows:
        logger.info("No movements to write.")
        return 0

    body = {"values": rows}

    try:
        result = (
            service.spreadsheets()
            .values()
            .append(
                spreadsheetId=SPREADSHEET_ID,
                range=SHEET_RANGE,
                valueInputOption="USER_ENTERED",
                insertDataOption="INSERT_ROWS",  # Never overwrite existing data.
                body=body,
            )
            .execute()
        )
    except HttpError as exc:
        logger.error("Google Sheets API error: %s", exc)
        raise

    updates = result.get("updates", {})
    rows_written: int = updates.get("updatedRows", len(rows))
    logger.info("Wrote %d row(s) to Google Sheets.", rows_written)
    return rows_written


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/health")
def health_check() -> dict[str, str]:
    """Simple liveness probe."""
    return {"status": "ok"}


@app.post("/sync", response_model=SyncResponse)
def sync(payload: SyncRequest) -> SyncResponse:
    """
    Receive the `link_token` from the Fintoc widget, fetch the latest bank
    movements, and append them to the configured Google Sheet.
    """
    link_token = payload.link_token.strip()

    if not link_token:
        raise HTTPException(status_code=400, detail="link_token must not be empty.")

    # ── 1. Fetch movements from Fintoc ────────────────────────────────────────
    try:
        movements = _get_fintoc_movements(link_token)
    except ValueError as exc:
        logger.error("Configuration error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("Fintoc API error: %s", exc)
        raise HTTPException(
            status_code=502,
            detail=f"Failed to retrieve movements from Fintoc: {exc}",
        ) from exc

    if not movements:
        return SyncResponse(rows_written=0, message="No new movements found for the period.")

    # ── 2. Write to Google Sheets ─────────────────────────────────────────────
    try:
        rows_written = _append_to_google_sheets(movements)
    except (ValueError, FileNotFoundError) as exc:
        logger.error("Configuration error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except HttpError as exc:
        logger.error("Google Sheets error: %s", exc)
        raise HTTPException(
            status_code=502,
            detail=f"Failed to write to Google Sheets: {exc}",
        ) from exc
    except Exception as exc:
        logger.error("Unexpected error writing to Sheets: %s", exc)
        raise HTTPException(
            status_code=500,
            detail=f"Unexpected error: {exc}",
        ) from exc

    return SyncResponse(
        rows_written=rows_written,
        message=f"Successfully appended {rows_written} row(s) to the spreadsheet.",
    )
