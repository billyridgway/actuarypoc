# Term23 Actuarial Table Schema (Prototype)

This file defines a Term23-specific actuarial table layout aligned with the ICC23 SN 174 N Term23v3 memo:
- 2017 CSO, Age Nearest Birthday
- Gender-distinct, smoker-distinct
- Multiple risk classes and face-amount bands
- Initial level premium periods of 10/15/20/30 years

## File

Suggested file for the POC:

- `src/actuarypoc/sample_data/actuarial_tables_term23.csv`

## Columns

| column                   | type    | description |
|--------------------------|---------|-------------|
| `table_id`               | string  | Table identifier, e.g. `2017-CSO` |
| `product_code`           | string  | Product family code, e.g. `TERM23` |
| `gender`                 | string  | `Male` / `Female` |
| `smoker_class`           | string  | `Nontobacco` / `Tobacco` |
| `risk_class`             | string  | One of: `Super Preferred`, `Preferred`, `Super Standard`, `Standard` (or carrier-specific labels) |
| `face_band`              | integer | Face amount band, as defined in the memo (1,2,3) |
| `issue_age`              | integer | Age at issue (nearest birthday) |
| `duration`               | integer | Policy year (1 = first policy year) |
| `qx`                     | decimal | Annual mortality rate for this cell (q_x) |
| `nonforfeiture_int_rate` | decimal | Interest rate used for nonforfeiture testing (e.g. 0.045) |
| `load_factor`            | decimal | Aggregate load (expense/risk) applied to this cell |

### Notes

- `table_id` + `product_code` + `gender` + `smoker_class` + `risk_class` + `face_band` + `issue_age` + `duration` should uniquely identify a row.
- For early POC work you can populate a **thin slice** of ages/durations (e.g. ages 35/45/55 and first 10–20 durations) with placeholder `qx` values.
- `nonforfeiture_int_rate` is included to align with the 4.50% rate used in the memo; the projection engine can either:
  - use this directly for discounting, or
  - treat it as metadata and instead read illustration rates from the `rate_curves` connector.
- `load_factor` lets you keep some of the memo’s expense/risk loading logic attached to the mortality surface, even before we have a full expense model.

## Example Rows (Illustrative Only)

```csv
table_id,product_code,gender,smoker_class,risk_class,face_band,issue_age,duration,qx,nonforfeiture_int_rate,load_factor
2017-CSO,TERM23,Male,Nontobacco,Standard,1,35,1,0.00080,0.045,0.0020
2017-CSO,TERM23,Male,Nontobacco,Standard,1,35,2,0.00082,0.045,0.0020
2017-CSO,TERM23,Female,Nontobacco,Standard,1,35,1,0.00065,0.045,0.0020
2017-CSO,TERM23,Female,Nontobacco,Standard,1,35,2,0.00067,0.045,0.0020
```

These values are **placeholders for the POC** and are not production-credible. In a real deployment, this file would be generated from the carrier’s 2017 CSO–based tables and internal assumption sets used for Term23.
