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
`information_schema` query to the configured analytics schema. Cross-schema foreign keys fail
closed rather than introducing another schema into the business catalog.

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

## 3. Suggested paths

```text
catalog/
├── generated/
│   ├── schema.json
│   └── index/
└── semantic/
    ├── tables.yaml
    └── relationships.yaml
```

`catalog/generated/` is rebuildable.

`catalog/semantic/` is source-controlled domain knowledge.

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

## 5. Index fingerprint

Every generated retrieval index must have a fingerprint containing at least:

- catalog semantic revision/hash;
- generated schema fingerprint;
- complete embedding `ModelFingerprint`;
- model runtime version;
- index format/version.

If the embedding model changes, rebuild embeddings before serving semantic queries.

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

## 8. Embedding retrieval

Use local Ollama embeddings.

MVP constraints:

- index and query use the same configured model;
- batch embedding is preferred when rebuilding;
- result vectors are searched in-process;
- no external vector database.

Similarity metric should match the chosen embedding behavior and be documented in implementation.

## 9. Rank fusion

Default recommendation: Reciprocal Rank Fusion.

Example conceptual formula:

```text
RRF(d) = Σ 1 / (k + rank_i(d))
```

Exact `k` and top-K values are implementation parameters calibrated by eval.

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

- Recall@5;
- Recall@10;
- Precision@5;
- mean candidate count;
- relationship-path recovery rate.

Targets are defined in `EVAL_SPEC.md`.

## 15. Failure behavior

If no sufficiently relevant schema is found:

- do not fabricate a table;
- do not query `information_schema` through model-generated arbitrary SQL;
- return a typed retrieval failure or request clarification if the business term itself is ambiguous.
