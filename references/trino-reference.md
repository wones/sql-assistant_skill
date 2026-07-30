---
AIGC:
  ContentProducer: '001191110102MAD55U9H0F10002'
  ContentPropagator: '001191110102MAD55U9H0F10002'
  Label: '1'
  ProduceID: 'e56becc7-7836-47ac-a1c1-980cc4e330df'
  PropagateID: 'e56becc7-7836-47ac-a1c1-980cc4e330df'
  ReservedCode1: '545f55e4-c01f-4939-acd3-3adb91bee847'
  ReservedCode2: '545f55e4-c01f-4939-acd3-3adb91bee847'
---

# Trino SQL 语法速查

## 目录

- [数据类型](#数据类型)
- [常用函数](#常用函数)
- [条件与逻辑](#条件与逻辑)
- [日期时间](#日期时间)
- [字符串](#字符串)
- [聚合与窗口](#聚合与窗口)
- [数组与MAP](#数组与map)
- [JSON处理](#json处理)
- [CTE与子查询](#cte与子查询)
- [JOIN](#join)
- [常用模式](#常用模式)

---

## 数据类型

| 类型 | 说明 |
|------|------|
| `boolean` | 布尔 |
| `tinyint/smallint/integer/bigint` | 整数 |
| `real/double` | 浮点 |
| `decimal(p,s)` | 定点数 |
| `varchar(n)/varchar` | 变长字符串 |
| `char(n)` | 定长字符串 |
| `varbinary` | 二进制 |
| `date` | 日期 |
| `time` | 时间 |
| `timestamp` | 时间戳 |
| `timestamp with time zone` | 带时区时间戳 |
| `array<T>` | 数组 |
| `map<K,V>` | 映射 |
| `row(...)` | 结构体 |

## 常用函数

```sql
-- 类型转换
CAST(expr AS type)
TRY_CAST(expr AS type)  -- 转换失败返回NULL

-- COALESCE
COALESCE(val1, val2, val3)

-- NULL处理
IF(expr, val1, val2)           -- 等价 CASE WHEN expr THEN val1 ELSE val2 END
NULLIF(val1, val2)             -- 相等返回NULL
```

## 条件与逻辑

```sql
-- CASE WHEN
CASE
  WHEN condition1 THEN result1
  WHEN condition2 THEN result2
  ELSE default
END

-- IF函数
IF(condition, true_value, false_value)

-- 逻辑
AND, OR, NOT, IS NULL, IS NOT NULL
```

## 日期时间

```sql
CURRENT_DATE                       -- 当前日期
CURRENT_TIMESTAMP                  -- 当前时间戳
CURRENT_TIME                       -- 当前时间

-- 日期解析
date_parse('2024-01-15', '%Y-%m-%d')
date_parse('20240115', '%Y%m%d')

-- 格式化
format_datetime(CURRENT_TIMESTAMP, 'yyyy-MM-dd')
format_datetime(CURRENT_TIMESTAMP, 'yyyyMMdd')

-- 日期运算
date_add('day', 7, CURRENT_DATE)          -- 加7天
date_add('month', -1, CURRENT_DATE)       -- 减1个月
date_diff('day', start_date, end_date)    -- 日期差

-- 提取
EXTRACT(YEAR FROM date_col)
EXTRACT(MONTH FROM date_col)
EXTRACT(DOW FROM date_col)                -- 星期几(0=周日)

-- 截断
date_trunc('month', CURRENT_DATE)         -- 月初
date_trunc('week', CURRENT_DATE)           -- 周一
date_trunc('day', timestamp_col)           -- 当天零点
```

## 字符串

```sql
CONCAT(str1, str2, ...)           -- 拼接
str1 || str2                       -- 拼接(另一种写法)
UPPER(str) / LOWER(str)           -- 大小写
TRIM(str) / LTRIM(str) / RTRIM(str)
SUBSTR(str, start, length)
LENGTH(str)
REPLACE(str, old, new)
SPLIT(str, delimiter)             -- 返回array
REGEXP_REPLACE(str, pattern, replacement)
LIKE 'pattern%'                   -- 模糊匹配
```

## 聚合与窗口

```sql
-- 基本聚合
COUNT(*), COUNT(col), COUNT(DISTINCT col)
SUM(col), AVG(col), MAX(col), MIN(col)
APPROX_DISTINCT(col)               -- 近似去重计数（大数据量推荐）

-- 窗口函数
ROW_NUMBER() OVER (PARTITION BY col ORDER BY col)
RANK() OVER (...)
DENSE_RANK() OVER (...)
LEAD(col, offset) OVER (...)
LAG(col, offset) OVER (...)
FIRST_VALUE(col) OVER (...)
LAST_VALUE(col) OVER (...)

-- 聚合窗口
SUM(col) OVER (PARTITION BY ... ORDER BY ... ROWS BETWEEN ...)
```

## 数组与MAP

```sql
-- 数组
ARRAY[1, 2, 3]
ARRAY_AGG(col)                     -- 聚合为数组
ARRAY_JOIN(arr, ',')               -- 数组转字符串
CARDINALITY(arr)                   -- 数组长度
CONTAINS(arr, element)             -- 是否包含
UNNEST(arr)                        -- 展开数组为行
FILTER(arr, x -> x > 0)           -- 过滤
REDUCE(arr, 0, (s, x) -> s + x)   -- 归约

-- MAP
MAP(ARRAY['k1','k2'], ARRAY['v1','v2'])
map_col['key']
ELEMENT_AT(map_col, 'key')
```

## JSON处理

```sql
-- 解析JSON
json_parse('{"a":1}')              -- 字符串转JSON

-- 提取值（返回varchar）
json_extract_scalar(json_col, '$.key')
json_extract_scalar(json_col, '$.array[0].name')

-- 提取JSON对象（返回JSON类型）
json_extract(json_col, '$.key')
json_extract(json_col, '$.array[0]')

-- 格式化
json_format(json_col)               -- JSON转字符串
```

## CTE与子查询

```sql
-- CTE（推荐）
WITH
  cte1 AS (
    SELECT ...
    FROM ...
  ),
  cte2 AS (
    SELECT ...
    FROM cte1
    WHERE ...
  )
SELECT ...
FROM cte2;

-- 递归CTE
WITH RECURSIVE cte AS (
  SELECT ...           -- 锚点查询
  UNION ALL
  SELECT ...           -- 递归查询
  FROM cte
  WHERE ...
)
SELECT * FROM cte;

-- LATERAL JOIN（配合UNNEST）
SELECT t.id, arr_val
FROM table1 t,
     UNNEST(t.array_col) AS t2(arr_val);
```

## JOIN

```sql
-- 内连接
SELECT a.*, b.*
FROM table_a a
JOIN table_b b ON a.id = b.a_id;

-- 左连接
SELECT a.*, b.*
FROM table_a a
LEFT JOIN table_b b ON a.id = b.a_id;

-- 交叉连接+UNNEST
SELECT t.id, arr.item
FROM table1 t
CROSS JOIN UNNEST(t.array_col) AS arr(item);
```

## 常用模式

### 去重取最新

```sql
WITH ranked AS (
  SELECT *
    , ROW_NUMBER() OVER (PARTITION BY user_id ORDER BY updated_at DESC) AS rn
  FROM user_table
)
SELECT * FROM ranked WHERE rn = 1;
```

### 按天统计趋势

```sql
WITH date_range AS (
  SELECT date_add('day', n, CURRENT_DATE - INTERVAL '30' DAY) AS dt
  FROM UNNEST(SEQUENCE(0, 29)) AS t(n)
)
SELECT
  d.dt AS "日期"
  , COALESCE(COUNT(t.id), 0) AS "数量"
FROM date_range d
LEFT JOIN target_table t ON DATE(t.created_at) = d.dt
GROUP BY d.dt
ORDER BY d.dt;
```

### 环比/同比

```sql
WITH
  current_period AS (
    SELECT metric, SUM(amount) AS total
    FROM fact_table
    WHERE dt BETWEEN '2024-01-01' AND '2024-01-31'
    GROUP BY metric
  ),
  prev_period AS (
    SELECT metric, SUM(amount) AS total
    FROM fact_table
    WHERE dt BETWEEN '2023-12-01' AND '2023-12-31'
    GROUP BY metric
  )
SELECT
  c.metric
  , c.total AS "本期"
  , p.total AS "上期"
  , ROUND((c.total - p.total) * 100.0 / NULLIF(p.total, 0), 2) AS "环比变化%"
FROM current_period c
LEFT JOIN prev_period p ON c.metric = p.metric;
```

> AI生成