# n8n enrichment workflows

Exports of the n8n workflows behind the ✦ AI suggestions in the editor. Each webhook
takes a batch of variables and returns suggestions; the backend calls them from
`ddicdi/enrich.py` with the URLs configured in `ddicdi/config.py`.

| Workflow | Webhook path | Suggests |
|---|---|---|
| `metadata-unit-enrichment.json` | `metadata-enrichment` | Unit of measure (EU measurement-unit authority) |
| `metadata-role-enrichment.json` | `metadata-role-enrichment` | Variable role: measure / identifier / attribute |
| `metadata-function-enrichment.json` | `metadata-function-enrichment` | Variable function (Weight, UnitIdentifier, ...) |
| `metadata-spss-measure-enrichment.json` | `metadata-spss-measure-enrichment` | Level of measurement: nominal / ordinal / scale |
| `metadata-elsst-enrichment-rag-v2.json` | `metadata-elsst-enrichment-rag-v2` | ELSST concepts, retrieval-augmented from a Supabase vector store |
| `metadata-elsst-kb-loader.json` | (manual) | Loads the ELSST SKOS export into the vector store used above |

Import them through n8n (Workflows → Import from file). Credentials are referenced by
name only and must be created in the target instance: an Azure OpenAI chat model, an
Azure text-embedding-3 model, a Supabase account, and a header-auth credential whose
value is the `Authorization` header the backend sends as `DDI_N8N_BEARER_KEY`.
