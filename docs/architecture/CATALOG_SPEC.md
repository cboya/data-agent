# Semantic Catalog & Retrieval Specification

**Version:** v0.1.0
**Status:** Binding MVP design

## 1. Objective

The catalog gives the Data Agent a searchable semantic view of MySQL without placing the entire database schema into every model context.

It answers two questions:

1. Which tables are relevant to this requirement?
2. How can those tables be connected correctly?

## 2. Two-source catalog model

```text
MySQL information_schema         Repository-curated semantics
           │                               │
           ▼                               ▼
 catalog/generated/                 catalog/semantic/
           │                               │
           └──────────────┬────────────────┘
                          ▼
                   CatalogDocument
```

### Generated metadata

Generated from MySQL and never manually maintained:

- table name;
- column names;
- data types;
- nullability;
- PK/FK metadata where available;
- database comments.

M5 writes `catalog/generated/schema.json` as a versioned, deterministic artifact with this
provider-neutral shape:

```text
version
schema
tables[]
  name
  comment
  columns[]
    ordinal_position
    name
    data_type
    nullable
    primary_key
    comment
  foreign_keys[]
    constraint_name
    columns[]
    referenced_table
    referenced_columns[]
fingerprint
```

Tables, columns, and foreign keys use stable database-defined ordering with deterministic
tie-breakers. The SHA-256 fingerprint covers the canonical artifact payload excluding the
`fingerprint` field itself. It contains no generation timestamp or curated semantics.

Introspection uses the analytics read-only principal and explicitly scopes every
`information_schema` query to the configured analytics schema. Under M17 it additionally scopes
all table, column, and FK reads to the active profile's explicit allowed tables. Foreign keys with
an endpoint outside that surface are not admitted to the normalized selected-source catalog.
Cross-schema foreign keys fail closed rather than introducing another schema into the business
catalog.

### Curated semantics

Version-controlled:

- aliases;
- human descriptions;
- business rules;
- semantic column descriptions;
- typical use cases;
- known relationships/cardinality;
- known analytical traps.

Conversation content cannot automatically modify curated semantics.

Generated foreign keys establish join connectivity evidence only. They do not establish
`Relationship.cardinality`: an FK column may also be unique, and M5 does not preserve enough
uniqueness metadata to distinguish one-to-one from many-to-one. M6 therefore takes cardinality
only from validated curated relationship semantics. Neither an LLM nor merge code may infer it
from an FK alone.

`Relationship v0.1` represents only single-column connectivity. Composite foreign keys remain
generated metadata and must not be decomposed into independently valid relationship edges.

## 3. Suggested paths

```text
catalog/
├── generated/
│   ├── schema.json
│   ├── catalog.json
│   └── index/
└── semantic/
    ├── tables.yaml
    └── relationships.yaml
```

`catalog/generated/` is rebuildable.

`catalog/semantic/` is source-controlled domain knowledge.

M17 preserves these exact paths for the synthetic reference workspace. One explicitly selected
external source uses an isolated workspace instead:

```text
catalog/workspaces/<workspace-id>/
├── generated/
│   ├── schema.json
│   ├── catalog.json
│   └── index/
└── semantic/
    ├── tables.yaml
    └── relationships.yaml
```

The active `AnalyticsSourceProfile` deterministically selects one workspace. External generated
state cannot overwrite the synthetic reference artifacts, and external curated semantics are
required only for the profile's allowed-table surface. Credentials and network endpoints do not
enter either workspace identity or generated artifacts.

M6 requires curated table semantics for every generated analytics table and rejects curated
references to tables or columns absent from the generated snapshot. The assembled
`catalog/generated/catalog.json` contains sorted `CatalogDocument` and curated `Relationship`
values plus the generated schema fingerprint, canonical semantic revision, and a revalidated
fingerprint over the complete assembled payload. It is rebuildable output, not a second source of
curated truth.

Column semantics merge field by field. A curated non-null column `description` overrides the
generated database comment; an omitted curated description inherits the generated comment.
Curated aliases are independent enrichment and never clear that comment merely because a column
overlay exists. M6 has no explicit operation for clearing a generated column description.

The MVP introspection boundary currently supports `BASE TABLE` objects. View support remains a
compatibility decision for a future real-schema boundary; encountering unsupported visible
column metadata continues to fail closed rather than broadening M5 implicitly.

## 4. Catalog document text for retrieval

Embedding/BM25 text should be constructed deterministically from meaningful semantics, for example:

```text
Table: fact_order
Aliases: 订单, 交易订单, 支付订单
Description: 订单事实表，一条记录代表一个业务订单
Business rules:
- status=PAID indicates paid order
- paid_amount is actual paid amount
Columns:
- user_id: 下单用户
- paid_amount: 实际支付金额
- paid_at: 支付成功时间
Typical use cases:
- 订单数量
- GMV
- 支付金额
- 用户购买分析
```

Do not blindly embed raw full DDL if it reduces signal quality.

M7 projection version `retrieval-document-v0.1` renders table name/aliases/description, business
rules, sorted column names/types/aliases/descriptions, and typical use cases into one deterministic
text value. Retrieval documents are derived values and never mutate their `CatalogDocument` source.

## 5. Index fingerprint

Every generated retrieval index must have a fingerprint containing at least:

- assembled catalog fingerprint;
- catalog semantic revision/hash;
- generated schema fingerprint;
- complete embedding `ModelFingerprint`;
- model runtime version;
- index format/version;
- retrieval-document builder version.

If the embedding model changes, rebuild embeddings before serving semantic queries.
The artifact fingerprint also covers projected documents and vectors. Loading compares its complete
identity to the current generated schema, curated semantics, assembled catalog, and runtime model
identity; an internally valid but stale artifact fails closed.

## 6. Retrieval pipeline

```text
RequirementState
   ↓
Retrieval Query
   ├───────────────┐
   ▼               ▼
Lexical          Embed
   │               │
   ▼               ▼
Top-K lexical   Top-K semantic
   └───────┬───────┘
           ▼
       Rank fusion
           ▼
        Top-N
           ▼
 optional reranker
           ▼
      seed tables
           ▼
 relationship graph expansion
           ▼
   final schema slice
```

## 7. Lexical retrieval

Lexical retrieval handles:

- exact table names;
- exact column names;
- acronyms;
- aliases;
- highly specific business terms.

The implementation should be deterministic.

M7 uses repository-local BM25 (`k1=1.2`, `b=0.75`) over NFKC/casefold-normalized ASCII
identifier/word terms plus CJK character/bigram terms. This keeps the ten-document controlled-world
corpus dependency-free and makes Chinese/English behavior mechanically reproducible.

## 8. Embedding retrieval

Use the configured provider-neutral `EmbeddingModel`. Ollama remains the Phase-1/default local
reference; M16 permits the same bounded in-process retrieval path to use the selected
OpenAI-compatible embedding adapter.

MVP constraints:

- index and query use the same configured model;
- batch embedding is preferred when rebuilding;
- result vectors are searched in-process;
- no external vector database.

M16 advances the internal generated index format to `retrieval-index-v0.2` only to persist the
complete portable embedding identity: optional digest, endpoint identity, optional provider
revision, and identity assurance. Ranking, document projection, vector search, fusion, and graph
expansion semantics remain unchanged. Loading a v0.1 artifact under the v0.2 identity fails closed
and requires a deterministic rebuild.

Similarity metric should match the chosen embedding behavior and be documented in implementation.
M7 uses cosine similarity and revalidates query/index dimensions and finite numeric values before
ranking.

## 9. Rank fusion

Default recommendation: Reciprocal Rank Fusion.

Example conceptual formula:

```text
RRF(d) = Σ 1 / (k + rank_i(d))
```

Exact `k` and top-K values are implementation parameters calibrated by eval.

M7 uses RRF `k=60`. Lexical and semantic rank provenance is retained on seed hits; score-scale
normalization or hidden weighted blending is not used.

Do not overfit score weights to a tiny sample without recording evidence.

## 10. Reranking

Reranking is optional.

If LLM reranking is used:

- it receives only candidates found by retrieval;
- it may reorder/drop candidates;
- it cannot invent new tables;
- it returns structured output.

The simplest mechanism meeting eval targets wins.

## 11. Relationship graph

Relationship records include:

- source table/column;
- target table/column;
- cardinality;
- description;
- curated/generated provenance.

Graph expansion solves cases where a semantically central fact table requires dimension/intermediate tables that did not rank highly by text similarity.

## 12. Expansion rules

MVP defaults:

- seed from top-ranked tables;
- 1-hop expansion first;
- allow 2-hop only when necessary;
- impose a hard max hop count;
- impose a hard max candidate-table count.

Do not expand the entire database graph.

M7 takes the top four fused candidates as seed tables and performs deterministic multi-source
breadth-first expansion, ordered by seed rank and canonical relationship endpoint. It traverses
only validated M6 `Relationship` values, never raw M5 foreign keys. Hop count and total returned
tables are hard-bounded by application settings. Graph-added hits carry `GRAPH_EXPANSION`, no
lexical/semantic rank, and an explicit path reason.

Controlled-world calibration freezes the default expansion bound at one hop and eight total tables.
The 24-case standalone eval recovered every required path under that tighter boundary, so two-hop
expansion is available only by explicit configuration rather than enabled by default.

## 13. Synthetic test-world semantics

The test schema should exercise:

### Amount ambiguity

```text
fact_order.total_amount
fact_order.paid_amount
fact_refund.refund_amount
```

### Time ambiguity

```text
created_at
paid_at
completed_at
refunded_at
```

### Payment attempt multiplicity

One order may have several `fact_payment_transaction` rows but only one successful payment.

### Fan-out risk

Joining order-items and payment-transactions at detail grain can multiply rows.

### Dimensional lookup

Region/channel/category analyses require relationship expansion.

## 14. Retrieval evaluation

Primary retrieval metric:

```text
Required Table Recall@K
```

Why: a planner cannot recover a table that retrieval never exposes.

Track at minimum:

- seed Recall@5 and Recall@10 before graph expansion;
- final Recall@5 and Recall@10 after graph expansion;
- Precision@5;
- mean candidate count;
- relationship-path recovery rate.

Targets are defined in `EVAL_SPEC.md`.

## 15. Failure behavior

If no sufficiently relevant schema is found:

- do not fabricate a table;
- do not query `information_schema` through model-generated arbitrary SQL;
- return a typed retrieval failure or request clarification if the business term itself is ambiguous.
