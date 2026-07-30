---
AIGC:
  ContentProducer: '001191110102MAD55U9H0F10002'
  ContentPropagator: '001191110102MAD55U9H0F10002'
  Label: '1'
  ProduceID: '04c8edfb-bede-4f7d-b84a-192127551716'
  PropagateID: '04c8edfb-bede-4f7d-b84a-192127551716'
  ReservedCode1: 'c92db543-2efc-4002-ae91-e7e20181a55a'
  ReservedCode2: 'c92db543-2efc-4002-ae91-e7e20181a55a'
---

# SQL 优化规则详解

## 一、正则优化规则（按优先级执行）

| 优先级 | 规则名 | 说明 | 示例 |
|--------|--------|------|------|
| 1 | remove_comments | 移除 `--` 和 `/* */` 注释 | `SELECT id -- comment` → `SELECT id` |
| 3 | simplify_where_true | 移除 `WHERE 1=1` | `WHERE 1=1 AND id > 10` → `WHERE id > 10` |
| 3 | simplify_where_false | 简化 `WHERE 1=0` | 保留为 `WHERE 1=0`（语义：空结果） |
| 4 | remove_duplicate_columns | 去重SELECT列 | `SELECT id, name, id` → `SELECT id, name` |
| 6 | uppercase_keywords | 关键字大写 | `select id from t` → `SELECT id FROM t` |
| 7 | remove_extra_spaces | 合并多余空格 | 标准化空白 |

## 二、结构化优化规则

### 2.1 内联简单子查询

将仅包装一层SELECT *的子查询内联：

```sql
-- 优化前
SELECT * FROM (SELECT id, name FROM users) AS t

-- 优化后
SELECT t.id, t.name FROM users t
```

### 2.2 移除冗余子查询

去掉不必要的外层SELECT *：

```sql
-- 优化前
SELECT * FROM (SELECT id, name FROM users u) AS t

-- 优化后
SELECT u.id, u.name FROM users u
```

### 2.3 子查询转 JOIN

IN 子查询转换为 INNER JOIN（4种模式）：

```sql
-- 模式1: 简单IN
-- 优化前
SELECT * FROM orders o WHERE o.user_id IN (SELECT id FROM vip_users)
-- 优化后
SELECT o.* FROM orders o INNER JOIN vip_users ON o.user_id = vip_users.id

-- 模式2: 带WHERE条件
-- 优化前
SELECT * FROM orders o WHERE o.status = 1 AND o.user_id IN (SELECT id FROM vip_users)
-- 优化后
SELECT o.* FROM orders o INNER JOIN vip_users ON o.user_id = vip_users.id WHERE o.status = 1
```

### 2.4 简化子查询

IN → EXISTS 转换：

```sql
-- 优化前
WHERE user_id IN (SELECT DISTINCT user_id FROM active_users)
-- 优化后
WHERE user_id IN (SELECT user_id FROM active_users)

-- 复杂场景（左侧列需带表别名前缀）
WHERE u.user_id IN (SELECT user_id FROM active_users WHERE is_active = 1)
-- 优化后
WHERE EXISTS (SELECT 1 FROM active_users WHERE is_active = 1 AND u.user_id = user_id)
```

### 2.5 移除冗余派生表

去掉仅做 SELECT * 透传的派生表：

```sql
-- 优化前
SELECT t.* FROM (SELECT * FROM users) AS t
-- 优化后
SELECT t.* FROM users t
```

## 三、分析报告

优化时可输出 `--analyze` 报告，包含：

- **涉及的表** — FROM/JOIN 后的表名列表
- **JOIN类型** — INNER/LEFT/RIGHT/CROSS
- **子查询数量** — 嵌套SELECT计数
- **警告** — 子查询过多、JOIN过多等
- **建议** — 避免 SELECT *、子查询转JOIN等

> AI生成