# EVE Online PI Profit Engine

A market-aware Python CLI tool that interfaces with the EVE Swagger Interface (ESI) and the Static Data Export (SDE) to calculate real-time net profitability for Planetary Industry (PI) chains.

## What It Does

For every P1/P2 → P3/P4 production chain available on your factory planets, the engine fetches live Jita market prices, factors in your character's Accounting and Broker Relations skills, subtracts transaction taxes, broker fees, and a configurable low-sec transport risk factor, then outputs a binary recommendation per product line:

> **SELL RAW** | **PROCESS & MANUFACTURE**

## Quick Start

```bash
# 1. Clone & enter the project
cd eve_optimizer

# 2. Set up a virtual environment
python -m venv .venv
source .venv/bin/activate       # Linux/WSL
# .venv\Scripts\activate        # Windows

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure credentials
cp .env.example .env
# Edit .env with your ESI client ID, secret, and character ID

# 5. Build the local SDE database (first run only)
python -m src.databaseCreator

# 6. Run the profit engine
python -m src.main
```

## Configuration

| Variable | Description | Default |
|---|---|---|
| `ESI_CLIENT_ID` | EVE developer app client ID | — |
| `ESI_CLIENT_SECRET` | EVE developer app client secret | — |
| `CHARACTER_ID` | Your EVE character ID | — |
| `MARKET_REGION_ID` | ESI region for market data | `10000002` (The Forge) |
| `TRANSPORT_RISK_FACTOR` | Low-sec haul risk as decimal fraction | `0.05` |

## CLI Options

```
python -m src.main [OPTIONS]

Options:
  --planet-type TEXT   Filter chains by factory planet type
                       (barren, temperate, lava, oceanic, gas, storm, plasma, ice)
  --tier INT           Minimum output tier to evaluate (3 or 4)
  --top INT            Show only top N results by net profit delta
  --json               Output results as JSON instead of table
```

## Architecture

```
src/
├── config.py          # Environment config & constants
├── eve_server.py      # ESI client (OAuth2, market & skill endpoints)
├── databaseCreator.py # SDE → SQLite pipeline (PI blueprints P0–P4)
├── profit_engine.py   # Core decision formula
├── main.py            # CLI entrypoint
└── utils/
    └── helpers.py     # ISK formatting, fee math, volume helpers
```

## Tech Stack

- **Python >= 3.10**
- `preston` — ESI API wrapper with OAuth2
- `pandas` — Data manipulation & matrix output
- `fastapi` + `uvicorn` — Stubbed for future API expansion
- `pydantic` — Data validation & schema models
- `pytest` — Unit & integration tests
- `python-dotenv` — Credential management

## License

This project is released under the [MIT License](LICENSE).

---

## Legal & Licensing Notice

### EVE Online Developer License Agreement

This tool uses the **EVE Swagger Interface (ESI)** and data derived from the
**EVE Online Static Data Export (SDE)**. Both are provided under the
[EVE Online Developer License Agreement (DLA)](https://developers.eveonline.com/resource/license-agreement).

> EVE Online, the EVE logo, EVE and all associated logos and designs are the
> intellectual property of **CCP hf**. All artwork, screenshots, characters,
> vehicles, storylines, world facts or other recognizable features of the
> intellectual property relating to these trademarks are likewise the
> intellectual property of CCP hf.
>
> This project is not endorsed by, directly affiliated with, maintained,
> authorised, or sponsored by CCP hf. Use of EVE Online data is strictly
> non-commercial and in accordance with the EVE Online DLA.

### Open-Source Dependency Attributions

The following third-party Python packages are used by this project and are
each governed by their own open-source licences:

| Package | Version (minimum) | Licence |
|---|---|---|
| [`preston`](https://github.com/Celeo/preston) | ≥ 3.0.0 | MIT |
| [`pandas`](https://pandas.pydata.org/) | ≥ 2.0.0 | BSD 3-Clause |
| [`numpy`](https://numpy.org/) | (transitive) | BSD 3-Clause |
| [`fastapi`](https://fastapi.tiangolo.com/) | ≥ 0.110.0 | MIT |
| [`uvicorn`](https://www.uvicorn.org/) | ≥ 0.29.0 | BSD 3-Clause |
| [`pydantic`](https://docs.pydantic.dev/) | ≥ 2.0.0 | MIT |
| [`pytest`](https://pytest.org/) | ≥ 8.0.0 | MIT |
| [`python-dotenv`](https://github.com/theskumar/python-dotenv) | ≥ 1.0.0 | BSD 3-Clause |
| [`requests`](https://requests.readthedocs.io/) | ≥ 2.31.0 | Apache 2.0 |
| [`PyYAML`](https://pyyaml.org/) | ≥ 6.0.1 | MIT |
| [`cryptography`](https://cryptography.io/) | (transitive) | Apache 2.0 / BSD |
| [`PyJWT`](https://pyjwt.readthedocs.io/) | (transitive) | MIT |

Full licence texts for all installed packages are available under
`.venv/Lib/site-packages/<package>.dist-info/licenses/`.

### IBM Bob Development Framework

This project was developed with the assistance of **IBM Bob**, an AI-powered
software engineering assistant. Bob's use is subject to IBM's applicable
terms of service. No IBM intellectual property is distributed as part of
this repository.
