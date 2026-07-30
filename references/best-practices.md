---
AIGC:
  ContentProducer: '001191110102MAD55U9H0F10002'
  ContentPropagator: '001191110102MAD55U9H0F10002'
  Label: '1'
  ProduceID: '280de985-c0a6-4a08-a9ec-6aed09cf5091'
  PropagateID: '280de985-c0a6-4a08-a9ec-6aed09cf5091'
  ReservedCode1: '54e7a464-3843-406d-9c36-c42be9f4c367'
  ReservedCode2: '54e7a464-3843-406d-9c36-c42be9f4c367'
---

# SQL 使用规范与最佳实践

## 一、别名命名规范

### 格式

```
{业务模块}_{查询类型}[_{修饰符}]
```

### 示例

| 用途 | 命名 | 说明 |
|------|------|------|
| 用户基础表 | `user_base` | 业务_类型 |
| 用户订单查询 | `user_order_list` | 业务_类型_列表 |
| 活跃用户查询 | `user_active_daily` | 用户_活跃_日 |
| 用户订单月统计 | `user_order_count_monthly` | 用户_订单_统计_月 |

### 规则

- 分隔符用下划线 `_`
- 推荐小写
- 长度建议 3-30 字符
- 语义化命名，避免 `q1`、`tmp` 等

## 二、分组策略

### 按业务域

```
crm_customers/     → 用户基础、用户画像、联系方式
crm_orders/        → 订单基础、订单明细、退款
bi_analytics/      → 用户统计、趋势分析、留存
```

### 按使用频率

```
frequently_used/   → 高频查询
occasional/        → 低频查询
```

## 三、SQL 编写规范

### 必须遵守

- 禁止 `SELECT *`（明确列出需要的列）
- 必须有 `WHERE` 条件（防全表扫描）
- 大表查询必须加 `LIMIT` 或分区过滤
- 中文别名用双引号：`AS "用户数"`

### 推荐做法

- CTE 组织复杂逻辑
- 表名带 schema 前缀
- 关键字大写
- 逗号前置写法

```sql
WITH
  cte1 AS (
    SELECT
      user_id
      , user_name
      , status
    FROM default.users
    WHERE dt = CURRENT_DATE - INTERVAL '1' DAY
  )
SELECT
  user_id AS "用户ID"
  , user_name AS "用户名"
FROM cte1
LIMIT 1000;
```

## 四、分层架构实践

```
L3 报表层  → user_monthly_report, order_daily_report
    ↓
L2 聚合层  → user_active_stats, order_status_summary
    ↓
L1 基础层  → user_base, order_base
    ↓
原始表    → sys_user, ord_order
```

| 层级 | 职责 | 特点 |
|------|------|------|
| L1 基础层 | 单表查询、过滤、基础字段 | 原子化、高复用 |
| L2 聚合层 | 多表JOIN、分组统计 | 引用L1别名 |
| L3 报表层 | 业务计算、格式化输出 | 引用L2别名 |

## 五、依赖管理

### 原则

- 依赖必须单向，禁止循环
- 基础层不依赖聚合层
- 修改前检查依赖影响

```
✅ 正确: user_base → user_order → user_order_summary
❌ 循环: user_order → user_base → order_detail → user_order
```

### 声明格式

每个别名必须声明依赖：

```
- 依赖表: sys_user, ord_order
- 依赖别名: user_base
```

## 六、字段语义映射

> 跨表同语义不同字段名对照。SQL 生成时须先查此表确定字段名，避免 JOIN 时字段名不匹配。
>
> 此表为用户自定义内容，技能预置为空。当用户录入表结构时，若发现跨表同义不同名的字段，应主动引导用户在此登记。

### 6.1 使用规则

- SQL 生成涉及多表 JOIN 时，**必须**先查此映射表确认字段名，不可假设同名
- 大小写差异（如 `user_id` vs `USER_ID`）无需映射，Hive/Trino 忽略大小写
- 新增表时，若发现字段名与映射表已有语义冲突，须同步更新此表

### 6.2 登记格式示例

用户可按以下格式在此表追加映射行：

| 语义名 | 标准字段名 | 映射表及字段 |
|--------|-----------|-------------|
| 用户ID | user_id | ods.user_info_d.user_id; dwd.user_detail_d.uid（同义不同名） |
| 创建时间 | create_time | ods.user_info_d.create_time; ods.order_info_d.created_at（同义不同名） |
| 金额 | amount | dwd.fee_d.amount; dwd.payment_d.total_fee（同义不同名） |

## 七、维护建议

| 周期 | 任务 |
|------|------|
| 每天 | 检查新增别名是否正常 |
| 每周 | 检查过期/废弃别名 |
| 每月 | 优化慢查询、更新文档 |
| 每季度 | 全面审查分组结构 |

> AI生成