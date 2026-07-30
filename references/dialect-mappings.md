---
AIGC:
  ContentProducer: '001191110102MAD55U9H0F10002'
  ContentPropagator: '001191110102MAD55U9H0F10002'
  Label: '1'
  ProduceID: 'feba9f1f-f2a9-44d3-b139-243be4ece7cc'
  PropagateID: 'feba9f1f-f2a9-44d3-b139-243be4ece7cc'
  ReservedCode1: 'ae6c95a6-90c7-4821-af7a-abb494cd6862'
  ReservedCode2: 'ae6c95a6-90c7-4821-af7a-abb494cd6862'
---

# 方言转换映射表

## 支持的转换方向

| 源方言 | 目标方言 | 支持状态 |
|--------|---------|---------|
| MySQL → Trino | 支持 |
| MySQL → Doris | 支持 |
| Trino → MySQL | 支持 |
| Trino → Doris | 支持 |
| Doris → MySQL | 支持 |
| Doris → Trino | 支持 |

## 函数映射

### 通用函数差异

| MySQL | Trino | Doris | 说明 |
|-------|-------|-------|------|
| `IFNULL(a, b)` | `COALESCE(a, b)` | `IFNULL(a, b)` | 空值处理 |
| `SUBSTRING(s, n, len)` | `SUBSTR(s, n, len)` | `SUBSTR(s, n, len)` | 子串截取 |
| `NOW()` | `CURRENT_TIMESTAMP` | `NOW()` | 当前时间戳 |
| `CURDATE()` | `CURRENT_DATE` | `CURDATE()` | 当前日期 |
| `CURTIME()` | `CURRENT_TIME` | `CURTIME()` | 当前时间 |
| `DATEDIFF(d1, d2)` | `DATE_DIFF('day', d2, d1)` | `DATEDIFF(d1, d2)` | 日期差 |
| `TIMESTAMPDIFF(unit, d1, d2)` | `TIMESTAMP_DIFF(unit, d1, d2)` | `TIMESTAMPDIFF(unit, d1, d2)` | 时间戳差 |
| `APPROX_COUNT_DISTINCT(col)` | `APPROX_DISTINCT(col)` | `APPROX_COUNT_DISTINCT(col)` | 近似去重 |

### 日期提取函数差异

| MySQL | Trino | Doris |
|-------|-------|-------|
| `YEAR(date)` | `EXTRACT(YEAR FROM date)` | `YEAR(date)` |
| `MONTH(date)` | `EXTRACT(MONTH FROM date)` | `MONTH(date)` |
| `DAY(date)` | `EXTRACT(DAY FROM date)` | `DAY(date)` |
| `HOUR(time)` | `EXTRACT(HOUR FROM time)` | `HOUR(time)` |
| `MINUTE(time)` | `EXTRACT(MINUTE FROM time)` | `MINUTE(time)` |
| `SECOND(time)` | `EXTRACT(SECOND FROM time)` | `SECOND(time)` |

## 分页语法差异

### MySQL / Doris

```sql
-- LIMIT offset, row_count
SELECT * FROM users LIMIT 10, 20   -- 跳过10行，取20行
```

### Trino

```sql
-- OFFSET offset LIMIT row_count
SELECT * FROM users OFFSET 10 LIMIT 20   -- 跳过10行，取20行
```

## 转换注意事项

1. **数据类型差异**未自动转换：MySQL的`DATETIME`对应Trino的`TIMESTAMP`，需手动调整
2. **字符串引号**未自动转换：MySQL支持双引号字符串，Trino严格要求单引号
3. **DDL语法差异**未覆盖：CREATE TABLE语法各方言差异较大
4. **日期格式化函数**差异：`DATE_FORMAT()`在MySQL和Trino中参数格式不同
5. **隐式类型转换**：Trino更严格，可能需要显式CAST

> AI生成