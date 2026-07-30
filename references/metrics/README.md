---
AIGC:
  ContentProducer: '001191110102MAD55U9H0F10002'
  ContentPropagator: '001191110102MAD55U9H0F10002'
  Label: '1'
  ProduceID: '7a79e056-efaa-4f3d-b826-e2b7fee66164'
  PropagateID: '7a79e056-efaa-4f3d-b826-e2b7fee66164'
  ReservedCode1: '8f34d90f-1f25-4afd-84a5-61c8ad32a8c0'
  ReservedCode2: '8f34d90f-1f25-4afd-84a5-61c8ad32a8c0'
---

# 业务口径索引

> 业务口径按业务分组存储在子文件夹中。AI 生成 SQL 时按需读取，确保指标计算逻辑与业务定义一致。

---

## 目录结构

```
references/metrics/
├── README.md          ← 本索引文件
├── {分组名}/
│   └── metrics.md     ← 该分组的口径定义
└── ...
```

## 已注册分组

| 分组文件夹 | 业务域 | 口径数量 |
|-----------|--------|---------|
| `default/` | 默认分组（未指定分组时存入） | 0 |
| <!-- 在此行上方添加新分组 --> | | |

---

## 操作说明

- **新增口径**：确认所属分组 → 追加到 `{分组}/metrics.md` → 更新本索引
- **新增分组**：创建 `{分组名}/metrics.md` → 更新本索引
- **删除口径**：从对应 `metrics.md` 中移除 → 更新本索引数量
- **移动口径**：从原分组移除 → 追加到目标分组 → 更新两方索引
- **查看所有口径**：遍历各分组 `metrics.md` 的 `##` 标题

> AI生成