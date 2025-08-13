
# Agent Trader

A multi-agent, research-driven trading simulation with a live **Gradio** dashboard. Each trader agent alternates between **research** and **trade/rebalance** cycles, uses tool-calling (MCP) to interact with an account server, and logs activity for the UI. The app now includes **Start/Stop trading controls** so you can manage sessions without running a separate scheduler process.

---

## Table of Contents
- [Features](#features)
- [Architecture](#architecture)
- [Quick Start](#quick-start)
- [Configuration](#configuration)
- [Running the App](#running-the-app)
- [Usage Guide](#usage-guide)
- [Project Structure](#project-structure)
- [Developer Notes](#developer-notes)
- [Troubleshooting](#troubleshooting)
- [Security Notes](#security-notes)
- [License](#license)

---

## Features

- **Interactive dashboard** (Gradio) showing:
  - Portfolio value history (Plotly)
  - Holdings and recent transactions
  - Live logs (color-coded by type)
- **Start/Stop trading** directly from the UI (no manual `trading_floor.py` run needed).
- **Multi-agent trading loop**: agents alternate between research and trading/rebalancing.
- **MCP (Model Context Protocol)** tool layer:
  - `accounts_server.py` exposes account operations as tools (balance, holdings, buy/sell, etc.).
  - `accounts_client.py` launches the MCP server and provides client access to tools.
- **Pluggable LLM providers** via `traders.py`:
  - OpenAI (default), plus DeepSeek, Grok (xAI), Gemini, OpenRouter (via compatible OpenAI client).
- **Market-hours aware** loop with `market.is_market_open()`.
- **Structured tracing and logging** through `tracers.py` and `database.py`.

---

## Architecture

**Key modules**

- `app.py`: Gradio web UI. Renders trader cards (title, P&L, charts, holdings, transactions, logs) and provides **Start/Stop** controls. Creates a background `asyncio` task to run the trading loop at a configurable interval.
- `trading_floor.py`: Standalone scheduler/runner (kept for reference/CLI usage). Defines the interval, market-open checks, and creates multiple trader agents.
- `traders.py`: Defines the **agent Trader** (not the UI card). Handles model selection, creates a **researcher tool** (via MCP), executes trade/rebalance cycles, and wraps runs with tracing.
- `accounts.py`: In-memory account model (cash balance, holdings, transactions, portfolio valuation / P&L tracking).
- `accounts_server.py`: MCP tool server exposing account operations (balance, holdings, buy/sell, etc.).
- `accounts_client.py`: Launches `accounts_server.py` via MCP (`uv run`) and wraps MCP tool access.
- `market.py`: Market utilities (e.g., `is_market_open()` and price lookups).
- `database.py`: Simple logging and log retrieval (used by UI and tracers).
- `tracers.py`: Implements a `TracingProcessor` that writes span/trace events into the log store, tagged by trader name.
- `templates.py`: Agent prompts/instructions and tool descriptions for trader & researcher roles.
- `util.py`: UI helpers (CSS/JS palette, color mapping).

**Data flow**

1. **UI** (`app.py`) renders read-only account state and logs, refreshing periodically.
2. **Start Trading** creates a background task that, on each tick:
   - Checks **market hours** (unless overridden by setting).
   - **Runs all trader agents concurrently** (`traders.Trader.run()`), which:
     - Spin up MCP servers/clients for account access.
     - Perform **research** via web tools / knowledge graph where available.
     - Decide to **trade or rebalance** (alternating per run).
     - Use account tools to **buy/sell** and log actions.
3. **Logs & traces** are recorded via `tracers.py` → `database.py` and surfaced in the UI.

---

## Quick Start

> **Prereqs**
> - Python 3.10+
> - `uv` (optional but recommended for fast installs): https://docs.astral.sh/uv/
> - Node/Browser not required (Gradio serves the UI).
> - If you plan to enable code-exec tools that require Docker, install Docker Desktop. (Not required for standard runs.)

**Clone & install**

```bash
# from project root (folder that contains this README)
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# EITHER with uv (fast)
uv pip install -r requirements.txt

# OR with pip
pip install -r requirements.txt
```

---

## Configuration

Create a `.env` in the project root (one is included in the zip; **do not commit real keys**). The following variables are recognized by the codebase:

### Core LLM/API keys
- `OPENAI_API_KEY` — for OpenAI models (also used by some OpenRouter routes).
- `DEEPSEEK_API_KEY` — for DeepSeek models.
- `GROK_API_KEY` — for xAI Grok models.
- `GOOGLE_API_KEY` — for Gemini (OpenAI-compatible endpoint used).
- `OPENROUTER_API_KEY` — for OpenRouter.

### Market data
- `POLYGON_API_KEY` — required if `market.py` fetches live prices from Polygon.

### Trading loop behavior
- `RUN_EVERY_N_MINUTES` — interval between trading cycles (default: `60`).
- `RUN_EVEN_WHEN_MARKET_IS_CLOSED` — set to `"true"` to run cycles outside market hours (default: `"false"`).
- `USE_MANY_MODELS` — set to `"true"` to use four different models for the four demo traders (default: `"false"`).

> **Tip:** The Gradio UI includes controls for **interval** and **run when market is closed**. These override the environment defaults at runtime.

**Example `.env` (do not use real keys in source control):**
```dotenv
OPENAI_API_KEY=sk-...your_key...
DEEPSEEK_API_KEY=...
GROK_API_KEY=...
GOOGLE_API_KEY=...
OPENROUTER_API_KEY=...
POLYGON_API_KEY=...

RUN_EVERY_N_MINUTES=60
RUN_EVEN_WHEN_MARKET_IS_CLOSED=false
USE_MANY_MODELS=false
```

---

## Running the App

```bash
# ensure venv is active
source .venv/bin/activate

# launch the Gradio UI
python app.py
```

This starts a local server and opens the **Traders** dashboard in your browser. Four trader cards (e.g., Warren/George/Ray/Cathie) are displayed with model names (`short_model_names`).

---

## Usage Guide

### Start/Stop trading
In the **Trading Session Controls** card:
1. Choose an **Interval (minutes)**.
2. Toggle **Run when market is closed** if you want cycles outside normal hours.
3. Click **Start Trading** to launch the background loop.
4. Click **Stop Trading** to end the session gracefully.

### What you’ll see
- **Portfolio Value**: A mini time-series chart (Plotly) of each account.
- **Holdings**: Current symbol → quantity table.
- **Recent Transactions**: Timestamped buys/sells with price & rationale.
- **Logs**: Live color-coded activity feed (trace, agent, function, generation, response, account).

### How trading works (high-level)
- Each run toggles between **trade** and **rebalance**.
- The agent composes or updates a research summary, then decides on actions.
- Actions are executed via **MCP tools** exposed by `accounts_server.py`.
- Logs & traces are stored and rendered by the UI.

---

## Project Structure

```
Agent Trader/
├─ app.py                # Gradio UI + Start/Stop controller
├─ trading_floor.py      # Standalone scheduler (kept for CLI use)
├─ traders.py            # Agent Trader (LLM + tools/MCP + research/trade loop)
├─ accounts.py           # In-memory portfolio/balance/transactions logic
├─ accounts_server.py    # MCP server exposing tools backed by accounts.py
├─ accounts_client.py    # Launches server and calls MCP tools
├─ market.py             # Market/price utilities (incl. is_market_open)
├─ database.py           # Logging utilities (write_log/read_log, etc.)
├─ tracers.py            # Trace processor → logs
├─ templates.py          # Agent instructions & tool descriptions
├─ util.py               # UI CSS/JS helpers, Color map
├─ requirements.txt
├─ pyproject.toml
├─ .env                  # Local configuration (do NOT commit real keys)
└─ README.md             # You are here
```

---

## Developer Notes

- **Models & providers** are selected in `traders.py` (`get_model`). The project uses OpenAI-compatible clients to talk to multiple backends:
  - OpenAI, DeepSeek, Grok, Gemini, OpenRouter.
- **Accounts** are kept in-memory by default. Extend `accounts.py` and/or `database.py` to persist to a real DB.
- **UI refresh**:
  - Portfolio & tables refresh every 120s.
  - Logs refresh at ~0.5s intervals.
- **Tracing**: `tracers.LogTracer` implements callbacks that write structured events to the app log.
- **MCP**: `accounts_client.py` runs the server with `uv run accounts_server.py`. Ensure `uv` is installed or refactor to use `python -m` if you prefer.

---

## Troubleshooting

- **Package not found: `libgl1-mesa-glx` during Docker build**  
  On Debian *trixie*, use `libgl1` instead (and add `libglib2.0-0`). Alternatively, base on `python:3.10-bookworm` and keep `libgl1-mesa-glx`.

- **Docker required for certain code-exec tools**  
  If you enable tools that require sandboxing, install Docker. Otherwise ensure `allow_code_execution=False` for agents/tools that don’t need it.

- **CrewAI / venv mismatch warnings**  
  Use `uv run --active ...` to target the currently active venv, or `source .venv/bin/activate` in the project directory before running commands.

- **No trades occurring**  
  Confirm:
  - `RUN_EVEN_WHEN_MARKET_IS_CLOSED=true` if testing off-hours.
  - API keys (e.g., `POLYGON_API_KEY`) are set if live prices are needed.
  - Models selected in `traders.py` are accessible with your keys.

- **Sensitive keys accidentally committed**  
  Rotate keys immediately and purge history. See Security Notes below.

---

## Security Notes

- **Never commit `.env` with real API keys.** Add it to `.gitignore`.
- Rotate keys if they were shared or uploaded inadvertently.
- Consider using **secrets managers** (e.g., 1Password, Doppler, AWS Secrets Manager) for production.

---
