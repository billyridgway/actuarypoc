# CRM Accounts Mock Schema

File: `src/actuarypoc/sample_data/crm_accounts.csv`

| column | type | description |
| --- | --- | --- |
| `account_id` | string | CRM account identifier |
| `advisor_id` | string | Owning advisor ID |
| `client_name` | string | Client display name |
| `client_segment` | string | Segment/bucket (MassAffluent, HNW, etc.) |
| `email` | string | Contact email |
| `last_touch_date` | date | Most recent advisor interaction |
| `preferred_product` | string | Product most associated with client |

Use this dataset to mock CRM data for connector development.
