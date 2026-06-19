# Fintoc × Bancolombia → Google Sheets

Sincroniza los movimientos de tu cuenta Bancolombia con Google Sheets de forma manual (on-demand), gestionando el Token Dinámico / MFA a través del widget oficial de Fintoc.

```
┌──────────────────┐    link_token    ┌─────────────────────┐    append rows    ┌──────────────────┐
│  Browser         │ ──────────────►  │  FastAPI Backend    │ ───────────────►  │  Google Sheets   │
│  (Fintoc Widget) │                  │  (main.py)          │                   │                  │
│  frontend/       │                  │  backend/           │                   │                  │
└──────────────────┘                  └─────────────────────┘                   └──────────────────┘
```

## Prerequisites

| Tool | Version |
|------|---------|
| Python | 3.9+ |
| pip | latest |
| A Fintoc account | [fintoc.com](https://fintoc.com) |
| A Google Cloud project with Sheets API enabled | — |

---

## 1 · Set up the Fintoc account

1. Sign up at [fintoc.com](https://fintoc.com) and create a project.
2. Go to **Settings → API Keys** and note your:
   - **Public key** (`pk_live_…`) — used in the frontend.
   - **Secret key** (`sk_live_…`) — used in the backend.

---

## 2 · Set up Google Sheets API

1. Open [Google Cloud Console](https://console.cloud.google.com/) and create a project (or reuse one).
2. Enable the **Google Sheets API**.
3. Go to **IAM & Admin → Service Accounts** → create a service account.
4. Under the service account's **Keys** tab, click **Add Key → JSON** and download the file.
5. Rename the file to `credentials.json` and place it in the `backend/` folder.
6. Open your Google Sheet and **share it** (as Editor) with the service account's e-mail address (visible on the service account page).
7. Copy the **Spreadsheet ID** from the Sheet URL:
   ```
   https://docs.google.com/spreadsheets/d/<SPREADSHEET_ID>/edit
   ```

---

## 3 · Configure the backend

```bash
cd backend
cp .env.example .env
```

Edit `.env` and fill in your values:

```env
FINTOC_SECRET_KEY=sk_live_YOUR_REAL_SECRET_KEY
SPREADSHEET_ID=YOUR_REAL_SPREADSHEET_ID
SHEET_RANGE=Movimientos!A1        # tab name + starting cell
GOOGLE_CREDENTIALS_FILE=credentials.json
DAYS_BACK=3
```

---

## 4 · Install dependencies & run the backend

```bash
cd backend

# Create and activate a virtual environment (recommended)
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Start the server
uvicorn main:app --reload --port 8000
```

The API will be available at `http://localhost:8000`.  
Interactive docs: `http://localhost:8000/docs`.

---

## 5 · Configure & open the frontend

Edit `frontend/index.html` and replace the placeholder with your Fintoc **public** key:

```js
const FINTOC_PUBLIC_KEY = "pk_live_YOUR_REAL_PUBLIC_KEY";
```

Then simply open `frontend/index.html` in a browser (double-click or use a local server):

```bash
# Quick local server (Python built-in)
python -m http.server 5500 --directory frontend
# Then open http://localhost:5500
```

Click **Conectar con Fintoc**, complete the Bancolombia login, enter the Dynamic Token when prompted by the widget, and the movements will be appended to your sheet automatically.

---

## Project structure

```
fintocbancolombia/
├── frontend/
│   └── index.html          # Fintoc Widget page
├── backend/
│   ├── main.py             # FastAPI application
│   ├── requirements.txt    # Python dependencies
│   ├── .env.example        # Environment variable template
│   └── tests/
│       ├── test_main.py            # Pytest test suite
│       └── requirements-test.txt  # Test dependencies
├── .gitignore
└── README.md
```

---

## Running the tests

```bash
cd backend
pip install -r tests/requirements-test.txt
pytest tests/ -v
```

All tests use mocks — no real credentials are needed.

---

## Google Sheet column layout

The backend appends rows in this order:

| A | B | C | D | E |
|---|---|---|---|---|
| Transaction ID | Date (YYYY-MM-DD) | Description | Amount | Currency |

---

## Troubleshooting

| Error | Likely cause | Fix |
|-------|-------------|-----|
| `FINTOC_SECRET_KEY has not been configured` | Placeholder not replaced | Set `FINTOC_SECRET_KEY` in `.env` |
| `credentials.json not found` | File missing | Download from Google Cloud Console |
| `403 Forbidden` from Sheets API | Sheet not shared with service account | Share the sheet with the service account e-mail |
| CORS error in browser | Frontend origin not in `ALLOWED_ORIGINS` | Add your frontend URL to `ALLOWED_ORIGINS` in `.env` |
