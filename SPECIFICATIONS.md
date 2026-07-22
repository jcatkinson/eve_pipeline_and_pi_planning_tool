# 📋 Project Specifications: EVE Online Data Engineering & PI Optimizer

> **Version:** 1.0.0 **Status:** Draft / Paused (Active Blueprint) **Target Execution Environment:** Local WSL/Ubuntu Terminal / Orchestrated via IBM Bob-Shell

## 🎯 1. High-Level Summary & Objectives

A custom, market-aware Python application that interfaces with the EVE Swagger Interface (ESI) and Static Data Export (SDE) to calculate real-time net profitability for Planetary Industry (PI) setups, enabling data-driven logistics and production decisions.

- **Primary Goal:** Build an automated data pipeline and optimization engine to evaluate manufacturing thresholds and logistics efficiency.
- **Key Use Case:** Correlating live regional market data against blueprint recipes to decide whether to sell raw intermediate materials (P1/P2) or manufacture and sell high-tier goods (P3/P4).
- **Core Output:** A dynamic Net Profit Decision Matrix factoring in character skills, actual transaction costs (market taxes and broker fees), and transportation risk/time.

## 🏗️ 2. Architectural & Technical Stack

Specify the underlying technologies and constraints for Bob to build within.

|Component|Technology / Library|Version / Constraint|
|---|---|---|
|**Language**|Python|`>= 3.10`|
|**Core Libraries**|`preston`, `pandas`, `fastapi`, `pydantic`|ESI wrapper & data manipulation|
|**Database / Storage**|SQLite / Local File Storage|Local queryable database for SDE blueprints|
|**Testing**|`pytest`|Unit & Integration testing framework|
|**Environment**|`python-dotenv`|Load `.env` for OAuth2 keys and credentials|

## 📂 3. Repository File Structure Blueprint

Bob must generate and strictly adhere to the following file layout:

eve_optimizer/
├── docs/
│   ├── SPECIFICATIONS.md
│   ├── api_reference/
│   ├── data_schemas/
│   └── process_guides/
├── src/
│   ├── __init__.py
│   ├── main.py
│   ├── config.py
│   ├── eve_server.py
│   ├── databaseCreator.py
│   └── utils/
│       ├── __init__.py
│       └── helpers.py
├── tests/
│   ├── __init__.py
│   └── test_main.py
├── .bob/
│   └── mcp.json
├── .gitignore
├── .env.example
├── LICENSE
├── README.md
└── requirements.txt