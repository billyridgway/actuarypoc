# Rate Curves Mock Schema

File: `src/actuarypoc/sample_data/rate_curves.csv`

| column | type | description |
| --- | --- | --- |
| `curve_id` | string | Identifier for the rate curve (UST, SWAP, etc.) |
| `as_of_date` | date | Date the curve snapshot applies to |
| `tenor_years` | integer | Tenor in years |
| `yield` | decimal | Yield/rate for that tenor |
| `source` | string | Data provider reference |

Use this dataset to mock external rate feeds.
