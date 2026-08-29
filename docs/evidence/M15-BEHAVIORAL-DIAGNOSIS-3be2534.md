# M15 Targeted Behavioral Diagnosis

- Report fingerprint: `1070e9346cdb441eb083299363d818e39cdde598815906e38437d1300b4ebc78`
- Source effect environment: `f2fb51fb05df516c59489fffaccb0d3a3adf0daeb528ecfb568481f6e665b933`
- Chat model fingerprint: `be7d8c949d1d85dc17e248c17db10be4634effd614fd20860d749082fbe7fe3e`
- Ollama: `0.32.15`
- Dialogue prompt: `dialogue-understanding-v0.20`
- Bounds: timeout `60.0s`, num_predict `2048`
- PR #15 disposition: **Draft; not ready for substantive review**

## Targeted M8 replay (exactly 35 cases)

- `STANDALONE_M8_ALSO_CLARIFIES`: 35

Blocking ambiguity occurrences: 37 across 36 replayed turns. Counts are ambiguity occurrences, so they need not sum to the 35-case partition.

Blocker fields:
- `dimension`: 1
- `grain`: 8
- `metric`: 6
- `time_range`: 22

| Case | Expected | Original E2E | Standalone M8 | Call outcome | Blocking subjects | Classification |
|---|---|---|---|---|---|---|
| `simple-paid-order-count` | READY | ASK_CLARIFICATION | ASK_CLARIFICATION | SUCCEEDED | time_range:整个数据集 | `STANDALONE_M8_ALSO_CLARIFIES` |
| `simple-pending-order-count` | READY | ASK_CLARIFICATION | ASK_CLARIFICATION | SUCCEEDED | time_range:整个数据集中 | `STANDALONE_M8_ALSO_CLARIFIES` |
| `simple-failed-attempts` | READY | ASK_CLARIFICATION | ASK_CLARIFICATION | SUCCEEDED | time_range:整个数据集 | `STANDALONE_M8_ALSO_CLARIFIES` |
| `simple-unit-sales` | READY | ASK_CLARIFICATION | ASK_CLARIFICATION | SUCCEEDED | time_range:整个数据集 | `STANDALONE_M8_ALSO_CLARIFIES` |
| `simple-completed-orders` | READY | ASK_CLARIFICATION | ASK_CLARIFICATION | SUCCEEDED | time_range:整个数据集中 | `STANDALONE_M8_ALSO_CLARIFIES` |
| `simple-paid-users` | READY | ASK_CLARIFICATION | ASK_CLARIFICATION | SUCCEEDED | metric:有成功支付订单的去重用户数 | `STANDALONE_M8_ALSO_CLARIFIES` |
| `agg-paid-order-channel` | READY | ASK_CLARIFICATION | ASK_CLARIFICATION | SUCCEEDED | time_range:按订单归属渠道统计成功订单的实际支付金额 | `STANDALONE_M8_ALSO_CLARIFIES` |
| `agg-paid-acquisition-channel` | READY | ASK_CLARIFICATION | ASK_CLARIFICATION | SUCCEEDED | time_range:按用户获客渠道统计成功订单的实际支付金额 | `STANDALONE_M8_ALSO_CLARIFIES` |
| `agg-paid-province` | READY | ASK_CLARIFICATION | ASK_CLARIFICATION | SUCCEEDED | time_range:按客户省份统计成功订单的实际支付金额 | `STANDALONE_M8_ALSO_CLARIFIES` |
| `agg-orders-status` | READY | ASK_CLARIFICATION | ASK_CLARIFICATION | SUCCEEDED | time_range:按订单状态统计业务订单数 | `STANDALONE_M8_ALSO_CLARIFIES` |
| `agg-gmv-status` | READY | ASK_CLARIFICATION | ASK_CLARIFICATION | SUCCEEDED | time_range:按订单状态统计 GMV | `STANDALONE_M8_ALSO_CLARIFIES` |
| `agg-attempts-status` | READY | ASK_CLARIFICATION | ASK_CLARIFICATION | SUCCEEDED | time_range:按支付尝试状态统计支付尝试次数 | `STANDALONE_M8_ALSO_CLARIFIES` |
| `agg-refund-status` | READY | ASK_CLARIFICATION | ASK_CLARIFICATION | SUCCEEDED | time_range:按退款状态统计退款金额 | `STANDALONE_M8_ALSO_CLARIFIES` |
| `agg-units-product` | READY | ASK_CLARIFICATION | ASK_CLARIFICATION | SUCCEEDED | time_range:按商品统计销售件数 | `STANDALONE_M8_ALSO_CLARIFIES` |
| `agg-units-category` | READY | ASK_CLARIFICATION | ASK_CLARIFICATION | SUCCEEDED | metric:销售件数 | `STANDALONE_M8_ALSO_CLARIFIES` |
| `agg-events-name` | READY | ASK_CLARIFICATION | ASK_CLARIFICATION | SUCCEEDED | time_range:按事件名称统计用户事件次数 | `STANDALONE_M8_ALSO_CLARIFIES` |
| `agg-events-channel` | READY | ASK_CLARIFICATION | ASK_CLARIFICATION | SUCCEEDED | time_range:按用户获客渠道统计用户事件次数 | `STANDALONE_M8_ALSO_CLARIFIES` |
| `agg-paid-date` | READY | ASK_CLARIFICATION | ASK_CLARIFICATION | SUCCEEDED | grain:按支付日期统计 | `STANDALONE_M8_ALSO_CLARIFIES` |
| `agg-orders-date` | READY | ASK_CLARIFICATION | ASK_CLARIFICATION | SUCCEEDED | grain:按下单日期 | `STANDALONE_M8_ALSO_CLARIFIES` |
| `agg-refunds-date` | READY | ASK_CLARIFICATION | ASK_CLARIFICATION | SUCCEEDED | grain:按退款日期 | `STANDALONE_M8_ALSO_CLARIFIES` |
| `agg-failed-attempts-date` | READY | ASK_CLARIFICATION | ASK_CLARIFICATION | SUCCEEDED | grain:按支付尝试日期 | `STANDALONE_M8_ALSO_CLARIFIES` |
| `agg-active-users-province` | READY | ASK_CLARIFICATION | ASK_CLARIFICATION | SUCCEEDED | time_range:按省份统计有用户事件的去重活跃用户数 | `STANDALONE_M8_ALSO_CLARIFIES` |
| `agg-users-register-date` | READY | ASK_CLARIFICATION | ASK_CLARIFICATION | SUCCEEDED | grain:按注册日期 | `STANDALONE_M8_ALSO_CLARIFIES` |
| `join-attempts-order` | READY | ASK_CLARIFICATION | ASK_CLARIFICATION | SUCCEEDED | time_range:按订单状态统计支付尝试次数 | `STANDALONE_M8_ALSO_CLARIFIES` |
| `join-units-order` | READY | ASK_CLARIFICATION | ASK_CLARIFICATION | SUCCEEDED | dimension:订单状态 | `STANDALONE_M8_ALSO_CLARIFIES` |
| `join-units-attempts-order` | READY | ASK_CLARIFICATION | ASK_CLARIFICATION | SUCCEEDED | metric:销售件数; metric:支付尝试次数 | `STANDALONE_M8_ALSO_CLARIFIES` |
| `join-paid-orders-category` | READY | ASK_CLARIFICATION | ASK_CLARIFICATION | SUCCEEDED | time_range:按商品品类统计包含该品类商品的成功订单实际支付金额 | `STANDALONE_M8_ALSO_CLARIFIES` |
| `join-paid-city` | READY | ASK_CLARIFICATION | ASK_CLARIFICATION | SUCCEEDED | time_range:按客户城市统计成功订单的实际支付金额 | `STANDALONE_M8_ALSO_CLARIFIES` |
| `join-events-city` | READY | ASK_CLARIFICATION | ASK_CLARIFICATION | SUCCEEDED | time_range:按用户所在城市统计用户事件次数 | `STANDALONE_M8_ALSO_CLARIFIES` |
| `join-units-price-product` | READY | ASK_CLARIFICATION | ASK_CLARIFICATION | SUCCEEDED | metric:item_sales_amount | `STANDALONE_M8_ALSO_CLARIFIES` |
| `join-refunds-order` | READY | ASK_CLARIFICATION | ASK_CLARIFICATION | SUCCEEDED | time_range:按原订单状态统计退款金额 | `STANDALONE_M8_ALSO_CLARIFIES` |
| `join-paid-users-channel` | READY | ASK_CLARIFICATION | ASK_CLARIFICATION | SUCCEEDED | time_range:按用户获客渠道统计有成功支付订单的去重用户数 | `STANDALONE_M8_ALSO_CLARIFIES` |
| `empty-future-paid` | READY | ASK_CLARIFICATION | ASK_CLARIFICATION | SUCCEEDED | grain:按支付日期统计 | `STANDALONE_M8_ALSO_CLARIFIES` |
| `correction-paid-month` | READY, READY | ASK_CLARIFICATION, ASK_CLARIFICATION | ASK_CLARIFICATION, ASK_CLARIFICATION | SUCCEEDED, SUCCEEDED | grain:不分组; grain:未指定统计粒度 | `STANDALONE_M8_ALSO_CLARIFIES` |
| `repair-users-province` | READY | ASK_CLARIFICATION | ASK_CLARIFICATION | SUCCEEDED | metric:user_count | `STANDALONE_M8_ALSO_CLARIFIES` |

## M12 PASSED + Oracle FAILED forensics (exactly 6 cases)

| Case | Scenario | Earliest divergence | Owner | Reproduced |
|---|---|---|---|---|
| `simple-gmv` | `EXTRA_GRAIN` | QueryPlan | `BOTH_M9_AND_M12` | yes |
| `simple-paid-amount` | `EXTRA_GRAIN` | QueryPlan | `BOTH_M9_AND_M12` | yes |
| `simple-payment-attempts` | `EXTRA_GRAIN` | QueryPlan | `BOTH_M9_AND_M12` | yes |
| `join-net-revenue` | `EXTRA_GRAIN` | QueryPlan | `BOTH_M9_AND_M12` | yes |
| `agg-gmv-channel` | `OUTPUT_SHAPE` | RequirementState | `ORACLE_SPEC_DEFECT_REQUIRING_HUMAN_REVIEW` | yes |
| `agg-orders-channel` | `OUTPUT_SHAPE` | RequirementState | `ORACLE_SPEC_DEFECT_REQUIRING_HUMAN_REVIEW` | yes |

### `simple-gmv`

- RequirementState: grain=`None`; metrics=['下单总金额 GMV→gmv']; dimensions=['—']
- PlannerContext allowed tables: `['fact_order', 'fact_order_item', 'fact_refund', 'dim_channel', 'dim_user', 'fact_payment_transaction', 'dim_product']`
- QueryPlan tables/columns: `['fact_order', 'dim_channel']` / `['channel_code', 'channel_name', 'gmv']`
- Execution columns/rows: `['channel_code', 'channel_name', 'gmv']` / `3`
- Verification: `PASSED`; unsupported coverage=['metric_source:0:gmv', 'time_range_semantics', 'metric_formula_semantics']
- Oracle columns/rows/match: `['gmv']` / `1` / `False`
- Earliest divergence / owner: `QueryPlan` / `BOTH_M9_AND_M12`
- Assessment: Query planning introduced a result shape outside the explicit requested output, and M12 still returned PASSED because that negative shape invariant is not encoded.
- SQL:

```sql
SELECT d.code AS channel_code, d.name AS channel_name, SUM(o.total_amount) AS gmv FROM fact_order o JOIN dim_channel d ON o.channel_id = d.id GROUP BY d.code, d.name ORDER BY gmv DESC;
```

### `simple-paid-amount`

- RequirementState: grain=`None`; metrics=['实际支付金额→paid_amount']; dimensions=['—']
- PlannerContext allowed tables: `['fact_payment_transaction', 'fact_order', 'fact_refund', 'fact_order_item', 'dim_channel', 'dim_user', 'dim_product']`
- QueryPlan tables/columns: `['fact_order']` / `['period', 'paid_amount']`
- Execution columns/rows: `['period', 'paid_amount']` / `8`
- Verification: `PASSED`; unsupported coverage=['time_range_semantics', 'metric_formula_semantics']
- Oracle columns/rows/match: `['paid_amount']` / `1` / `False`
- Earliest divergence / owner: `QueryPlan` / `BOTH_M9_AND_M12`
- Assessment: Query planning introduced a result shape outside the explicit requested output, and M12 still returned PASSED because that negative shape invariant is not encoded.
- SQL:

```sql
SELECT DATE(fact_order.paid_at) AS period, SUM(fact_order.paid_amount) AS paid_amount FROM fact_order WHERE fact_order.status IN ('PAID', 'COMPLETED') AND fact_order.paid_at IS NOT NULL GROUP BY DATE(fact_order.paid_at) ORDER BY period ASC;
```

### `simple-payment-attempts`

- RequirementState: grain=`None`; metrics=['支付尝试次数→payment_attempt_count']; dimensions=['—']
- PlannerContext allowed tables: `['fact_payment_transaction', 'fact_order', 'fact_user_event', 'fact_refund', 'dim_channel', 'dim_user', 'fact_order_item']`
- QueryPlan tables/columns: `['fact_payment_transaction']` / `['period', 'payment_attempt_count']`
- Execution columns/rows: `['period', 'payment_attempt_count']` / `8`
- Verification: `PASSED`; unsupported coverage=['metric_source:0:payment_attempt_count', 'time_range_semantics', 'metric_formula_semantics']
- Oracle columns/rows/match: `['payment_attempt_count']` / `1` / `False`
- Earliest divergence / owner: `QueryPlan` / `BOTH_M9_AND_M12`
- Assessment: Query planning introduced a result shape outside the explicit requested output, and M12 still returned PASSED because that negative shape invariant is not encoded.
- SQL:

```sql
SELECT DATE(fpt.attempted_at) AS period, COUNT(*) AS payment_attempt_count FROM fact_payment_transaction fpt WHERE fpt.status = 'SUCCESS' GROUP BY DATE(fpt.attempted_at) ORDER BY period ASC;
```

### `join-net-revenue`

- RequirementState: grain=`None`; metrics=['净收入→net_revenue']; dimensions=['—']
- PlannerContext allowed tables: `['fact_refund', 'fact_order', 'dim_channel', 'fact_order_item', 'dim_user', 'fact_payment_transaction', 'dim_product']`
- QueryPlan tables/columns: `['fact_order', 'dim_channel', 'fact_refund']` / `['channel_code', 'channel_name', 'net_revenue']`
- Execution columns/rows: `['channel_code', 'channel_name', 'net_revenue']` / `3`
- Verification: `PASSED`; unsupported coverage=['metric_source:0:net_revenue', 'metric_formula_semantics']
- Oracle columns/rows/match: `['net_revenue']` / `1` / `False`
- Earliest divergence / owner: `QueryPlan` / `BOTH_M9_AND_M12`
- Assessment: Query planning introduced a result shape outside the explicit requested output, and M12 still returned PASSED because that negative shape invariant is not encoded.
- SQL:

```sql
SELECT 
  dc.code AS channel_code,
  dc.name AS channel_name,
  SUM(COALESCE(fo.paid_amount, 0)) - COALESCE(SUM(fr.refund_amount), 0) AS net_revenue
FROM 
  fact_order fo
  INNER JOIN dim_channel dc ON fo.channel_id = dc.id
  LEFT JOIN fact_refund fr ON fo.id = fr.order_id AND fr.status = 'SUCCESS'
WHERE 
  fo.status IN ('PAID', 'COMPLETED')
GROUP BY 
  dc.code, dc.name
ORDER BY 
  net_revenue DESC;
```

### `agg-gmv-channel`

- RequirementState: grain=`None`; metrics=['gmv→gmv']; dimensions=['order_channel→channel']
- PlannerContext allowed tables: `['dim_channel', 'fact_order', 'fact_order_item', 'dim_user', 'fact_payment_transaction', 'fact_refund', 'dim_product', 'dim_region']`
- QueryPlan tables/columns: `['fact_order', 'dim_channel']` / `['channel', 'gmv']`
- Execution columns/rows: `['channel', 'gmv']` / `3`
- Verification: `PASSED`; unsupported coverage=['metric_source:0:gmv', 'dimension_source:0:channel', 'metric_formula_semantics']
- Oracle columns/rows/match: `['order_channel', 'gmv']` / `3` / `False`
- Earliest divergence / owner: `RequirementState` / `ORACLE_SPEC_DEFECT_REQUIRING_HUMAN_REVIEW`
- Assessment: The explicit output alias is absent from canonical RequirementState, so M9 and M12 cannot be assigned without reviewing the M8/output-shape contract.
- SQL:

```sql
SELECT dc.name AS channel, SUM(fo.total_amount) AS gmv FROM fact_order fo JOIN dim_channel dc ON fo.channel_id = dc.id WHERE fo.status IN ('PAID', 'COMPLETED') GROUP BY dc.id, dc.name ORDER BY gmv DESC;
```

### `agg-orders-channel`

- RequirementState: grain=`None`; metrics=['订单数→order_count']; dimensions=['订单归属渠道→channel']
- PlannerContext allowed tables: `['dim_channel', 'fact_order', 'fact_order_item', 'fact_payment_transaction', 'dim_user', 'fact_refund', 'dim_product']`
- QueryPlan tables/columns: `['fact_order', 'dim_channel']` / `['channel', 'order_count']`
- Execution columns/rows: `['channel', 'order_count']` / `3`
- Verification: `PASSED`; unsupported coverage=['metric_source:0:order_count', 'dimension_source:0:channel', 'metric_formula_semantics']
- Oracle columns/rows/match: `['order_channel', 'order_count']` / `3` / `False`
- Earliest divergence / owner: `RequirementState` / `ORACLE_SPEC_DEFECT_REQUIRING_HUMAN_REVIEW`
- Assessment: The explicit output alias is absent from canonical RequirementState, so M9 and M12 cannot be assigned without reviewing the M8/output-shape contract.
- SQL:

```sql
SELECT dc.name AS channel, COUNT(fo.id) AS order_count FROM fact_order fo JOIN dim_channel dc ON fo.channel_id = dc.id GROUP BY dc.id, dc.name ORDER BY order_count DESC;
```


## Recommended frozen milestones to reopen

- `M12`: `join-net-revenue`, `simple-gmv`, `simple-paid-amount`, `simple-payment-attempts`
- `M8`: `agg-active-users-province`, `agg-attempts-status`, `agg-events-channel`, `agg-events-name`, `agg-failed-attempts-date`, `agg-gmv-channel`, `agg-gmv-status`, `agg-orders-channel`, `agg-orders-date`, `agg-orders-status`, `agg-paid-acquisition-channel`, `agg-paid-date`, `agg-paid-order-channel`, `agg-paid-province`, `agg-refund-status`, `agg-refunds-date`, `agg-units-category`, `agg-units-product`, `agg-users-register-date`, `correction-paid-month`, `empty-future-paid`, `join-attempts-order`, `join-events-city`, `join-paid-city`, `join-paid-orders-category`, `join-paid-users-channel`, `join-refunds-order`, `join-units-attempts-order`, `join-units-order`, `join-units-price-product`, `repair-users-province`, `simple-completed-orders`, `simple-failed-attempts`, `simple-paid-order-count`, `simple-paid-users`, `simple-pending-order-count`, `simple-unit-sales`
- `M9`: `join-net-revenue`, `simple-gmv`, `simple-paid-amount`, `simple-payment-attempts`

## Exact remediation regression IDs

- `M12_FALSE_ACCEPT`: `join-net-revenue`, `simple-gmv`, `simple-paid-amount`, `simple-payment-attempts`
- `M8_DIALOGUE`: `agg-active-users-province`, `agg-attempts-status`, `agg-events-channel`, `agg-events-name`, `agg-failed-attempts-date`, `agg-gmv-status`, `agg-orders-date`, `agg-orders-status`, `agg-paid-acquisition-channel`, `agg-paid-date`, `agg-paid-order-channel`, `agg-paid-province`, `agg-refund-status`, `agg-refunds-date`, `agg-units-category`, `agg-units-product`, `agg-users-register-date`, `correction-paid-month`, `empty-future-paid`, `join-attempts-order`, `join-events-city`, `join-paid-city`, `join-paid-orders-category`, `join-paid-users-channel`, `join-refunds-order`, `join-units-attempts-order`, `join-units-order`, `join-units-price-product`, `repair-users-province`, `simple-completed-orders`, `simple-failed-attempts`, `simple-paid-order-count`, `simple-paid-users`, `simple-pending-order-count`, `simple-unit-sales`
- `M8_FALSE_ACCEPT`: `agg-gmv-channel`, `agg-orders-channel`
- `M9_FALSE_ACCEPT`: `join-net-revenue`, `simple-gmv`, `simple-paid-amount`, `simple-payment-attempts`

## Evidence limits

- The original six successful pipeline objects were not retained by latest.json and the clean reset removed their database rows; Task B therefore uses exact-identity targeted replays and preserves whether each source shape was reproduced.
- No hidden reasoning or free-form chain-of-thought is captured; only typed structured outputs and deterministic pipeline evidence are reported.
- The forensic composition replaces M14 synthesis only after M12 evidence is captured, so the six-case diagnostic makes no M14 model calls or M14 behavior claim.
