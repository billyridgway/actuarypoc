# PAS Export Mock Schema

Synthetic file: `src/actuarypoc/sample_data/pas_export.csv`

| column         | type    | description |
|----------------|---------|-------------|
| `policy_id`    | string  | Unique policy identifier from the PAS |
| `holder_name`  | string  | Insured/owner full name (for testing only) |
| `issue_date`   | date    | Policy issue date (YYYY-MM-DD) |
| `status`       | string  | Policy status (InForce, Lapsed, Pending, etc.) |
| `premium_mode` | string  | Payment frequency (Annual, Quarterly, Monthly) |
| `premium_amount` | numeric | Modal premium amount |
| `face_amount`  | numeric | Sum assured / face amount |
| `rider_codes`  | string  | Comma-separated rider codes |
| `last_update`  | date    | Timestamp of last sync |

Use this mock to prototype the PAS connector Dagster job until real exports are available.
