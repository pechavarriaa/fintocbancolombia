"""
Tests for the Fintoc–Bancolombia backend (main.py).

Run with:
    pip install pytest pytest-mock httpx
    pytest tests/test_main.py -v

These tests mock both the Fintoc SDK and the Google Sheets API so that no
real credentials are required.
"""

from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


# ── Import the app after patching heavy imports ───────────────────────────────
# We import main here; the module-level code only sets config variables and
# creates the FastAPI app — no credentials are touched at import time.
import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from main import app  # noqa: E402

client = TestClient(app)


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _make_movement(idx: int) -> MagicMock:
    """Return a mock Fintoc movement object."""
    m = MagicMock()
    m.id = f"mov_{idx}"
    m.post_date = date.today() - timedelta(days=idx)
    m.description = f"Test movement {idx}"
    m.amount = 100_000 * idx
    m.currency = "COP"
    return m


def _mock_fintoc_link(num_movements: int = 2) -> MagicMock:
    """Return a mock Fintoc Link with one account containing `num_movements`."""
    movements = [_make_movement(i) for i in range(num_movements)]

    account = MagicMock()
    account.id = "acc_test"
    account.name = "Bancolombia Ahorros"
    account.movements.all.return_value = iter(movements)

    link = MagicMock()
    link.accounts = [account]
    return link


def _mock_sheets_service(rows_written: int = 2) -> MagicMock:
    """Return a mock Google Sheets service that reports `rows_written`."""
    updates = {"updatedRows": rows_written}
    append_result = {"updates": updates}

    append_mock = MagicMock()
    append_mock.execute.return_value = append_result

    values_mock = MagicMock()
    values_mock.append.return_value = append_mock

    spreadsheets_mock = MagicMock()
    spreadsheets_mock.values.return_value = values_mock

    service = MagicMock()
    service.spreadsheets.return_value = spreadsheets_mock
    return service


# ── Health check ──────────────────────────────────────────────────────────────

def test_health_check():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


# ── /sync – happy path ────────────────────────────────────────────────────────

@patch("main.FINTOC_SECRET_KEY", "sk_live_TEST_KEY")
@patch("main.SPREADSHEET_ID", "sheet_test_id")
@patch("main.GOOGLE_CREDENTIALS_FILE", "credentials.json")
@patch("main._get_fintoc_movements")
@patch("main._append_to_google_sheets")
def test_sync_success(mock_sheets, mock_fintoc):
    """Happy path: Fintoc returns movements, Sheets writes them."""
    fake_movements = [
        {"id": "mv1", "post_date": "2024-01-01", "description": "Compra", "amount": 50000, "currency": "COP"},
        {"id": "mv2", "post_date": "2024-01-02", "description": "Retiro", "amount": 20000, "currency": "COP"},
    ]
    mock_fintoc.return_value = fake_movements
    mock_sheets.return_value = 2

    response = client.post("/sync", json={"link_token": "lt_test_token"})

    assert response.status_code == 200
    data = response.json()
    assert data["rows_written"] == 2
    mock_fintoc.assert_called_once_with("lt_test_token")
    mock_sheets.assert_called_once_with(fake_movements)


# ── /sync – no movements ──────────────────────────────────────────────────────

@patch("main._get_fintoc_movements")
def test_sync_no_movements(mock_fintoc):
    """When Fintoc returns zero movements the endpoint still succeeds."""
    mock_fintoc.return_value = []

    response = client.post("/sync", json={"link_token": "lt_empty"})

    assert response.status_code == 200
    data = response.json()
    assert data["rows_written"] == 0
    assert "No new movements" in data["message"]


# ── /sync – validation ────────────────────────────────────────────────────────

def test_sync_empty_token():
    """An empty link_token must be rejected with 400."""
    response = client.post("/sync", json={"link_token": "   "})
    assert response.status_code == 400


def test_sync_missing_token():
    """A missing link_token field must be rejected with 422 (FastAPI validation)."""
    response = client.post("/sync", json={})
    assert response.status_code == 422


# ── /sync – Fintoc error handling ────────────────────────────────────────────

@patch("main._get_fintoc_movements", side_effect=Exception("Fintoc SDK error"))
def test_sync_fintoc_error(mock_fintoc):
    """A Fintoc SDK error should surface as HTTP 502."""
    response = client.post("/sync", json={"link_token": "lt_bad"})
    assert response.status_code == 502
    assert "Fintoc" in response.json()["detail"]


# ── /sync – Google Sheets error handling ─────────────────────────────────────

@patch("main._get_fintoc_movements")
@patch("main._append_to_google_sheets", side_effect=FileNotFoundError("credentials.json not found"))
def test_sync_sheets_missing_credentials(mock_sheets, mock_fintoc):
    """Missing credentials.json should surface as HTTP 500."""
    mock_fintoc.return_value = [
        {"id": "mv1", "post_date": "2024-01-01", "description": "Test", "amount": 1000, "currency": "COP"}
    ]
    response = client.post("/sync", json={"link_token": "lt_test"})
    assert response.status_code == 500
