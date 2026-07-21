# ESI API Reference

Documentation for the EVE Swagger Interface (ESI) endpoints used by this project.

## Endpoints in Use

| Endpoint | Scope | Purpose |
|---|---|---|
| `GET /characters/{character_id}/skills/` | `esi-skills.read_skills.v1` | Fetch Accounting & Broker Relations skill levels |
| `GET /markets/{region_id}/orders/` | Public | Fetch regional market orders by type ID |

## Rate Limits

ESI enforces per-route error limits. This client respects `X-Pages` pagination headers and does not batch-parallel-request market data to avoid triggering rate limits.

## Authentication

OAuth2 Authorization Code flow. See [EVE Developers Portal](https://developers.eveonline.com/) and `.env.example` for setup.
