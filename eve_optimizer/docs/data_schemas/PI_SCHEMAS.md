# PI Data Schemas

## SQLite Tables

### `pi_items`
| Column | Type | Description |
|---|---|---|
| `type_id` | INTEGER PK | EVE type ID |
| `name` | TEXT | Item name |
| `tier` | INTEGER | PI tier: 0=raw, 1=P1, 2=P2, 3=P3, 4=P4 |
| `volume_m3` | REAL | Per-unit cargo volume |

### `pi_blueprints`
| Column | Type | Description |
|---|---|---|
| `blueprint_id` | INTEGER PK | Auto-increment |
| `output_type_id` | INTEGER FK | References `pi_items.type_id` |
| `output_qty` | INTEGER | Units produced per cycle |
| `planet_types` | TEXT | JSON array of compatible planet types |

### `pi_materials`
| Column | Type | Description |
|---|---|---|
| `material_id` | INTEGER PK | Auto-increment |
| `blueprint_id` | INTEGER FK | References `pi_blueprints.blueprint_id` |
| `input_type_id` | INTEGER FK | References `pi_items.type_id` |
| `input_qty` | INTEGER | Required units per cycle |

## DecisionResult Fields

| Field | Type | Description |
|---|---|---|
| `output_type_id` | int | EVE type ID of finished product |
| `output_name` | str | Product name |
| `output_tier` | int | 3 or 4 |
| `sell_raw_net_isk` | float | Net ISK from selling inputs directly |
| `process_net_isk` | float | Net ISK from selling finished output |
| `delta_isk` | float | `process_net_isk - sell_raw_net_isk` |
| `recommendation` | str | `"SELL RAW"` or `"PROCESS & MANUFACTURE"` |
| `applied_sales_tax` | float | Effective tax rate used |
| `applied_broker_fee` | float | Effective broker fee used |
| `transport_risk_factor` | float | Hauling risk fraction applied |
