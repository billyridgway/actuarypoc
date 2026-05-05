# Actuarial Table Mock Schema

File: `src/actuarypoc/sample_data/actuarial_tables.csv`

| column | type | description |
| --- | --- | --- |
| `table_id` | string | Identifier for the table source (e.g., VBT-2015) |
| `version` | string | Variant (Base, Preferred, Standard) |
| `gender` | string | Male/Female |
| `age` | integer | Attained age |
| `mortality_rate` | decimal | Annual q_x for the row |
| `interest_rate_basis` | decimal | Base interest rate associated with the table |
| `load_factor` | decimal | Additional expense or risk load applied by actuaries |

Use this dataset to prototype the actuarial table connector in Dagster until real tables are available.
