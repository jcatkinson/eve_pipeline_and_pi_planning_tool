# Process Guide: Running the Profit Engine

## First-Time Setup

```bash
# 1. Copy and fill in credentials
cp .env.example .env

# 2. Build the PI blueprint database (once, or after a PI patch)
python -m src.databaseCreator

# 3. Authenticate and run
python -m src.main
```

## Offline Mode (no ESI credentials needed)

```bash
python -m src.main --no-auth
```

Uses built-in mock Jita prices. Useful for testing the formula logic.

## Filtering by Planet Type

```bash
# Only evaluate chains producible on barren or temperate planets
python -m src.main --no-auth --planet-type barren --planet-type temperate
```

## P4-only output

```bash
python -m src.main --no-auth --tier 4
```

## Export to JSON

```bash
python -m src.main --no-auth --json > results.json
```

## Understanding the Output

```
TIER  PRODUCT                                SELL RAW (net)         PROCESS (net)          DELTA                  RECOMMENDATION
P3    Robotics                               12.34M ISK             18.90M ISK             +6.56M ISK             ✔ PROCESS
P3    Wetware Mainframe                      14.20M ISK             11.80M ISK             -2.40M ISK               SELL RAW
```

- **SELL RAW (net)**: What you'd net selling all input P1/P2 materials individually on Jita after fees.
- **PROCESS (net)**: What you'd net selling the finished P3/P4 output after fees.
- **DELTA**: `PROCESS - SELL RAW`. Positive = manufacturing is more profitable.
- **RECOMMENDATION**: Binary decision based on the delta sign.

## Adjusting Transport Risk

Edit `TRANSPORT_RISK_FACTOR` in `.env`. Set to `0` for high-sec only logistics.
