---
AIGC:
  ContentProducer: '001191110102MAD55U9H0F10002'
  ContentPropagator: '001191110102MAD55U9H0F10002'
  Label: '1'
  ProduceID: 'e8781a0e-30ff-4cf6-896f-2d02e39ba72c'
  PropagateID: 'e8781a0e-30ff-4cf6-896f-2d02e39ba72c'
  ReservedCode1: '029c5d9d-4867-47fd-aac0-4d33230b9414'
  ReservedCode2: '029c5d9d-4867-47fd-aac0-4d33230b9414'
---

# 别名索引

> 别名按业务分组存储在子文件夹中。AI 按需读取对应分组，避免全量加载。

---

## 目录结构

```
references/aliases/
├── README.md          ← 本索引文件
├── {分组名}/
│   └── aliases.md     ← 该分组的别名定义
└── ...
```

## 已注册分组

| 分组文件夹 | 业务域 | 别名数量 |
|-----------|--------|---------|
| `default/` | 默认分组（未指定分组时存入） | 0 |
| <!-- 在此行上方添加新分组 --> | | |

---

## 操作说明

- **新增别名**：确认所属分组 → 追加到 `{分组}/aliases.md` → 更新本索引
- **新增分组**：创建 `{分组名}/aliases.md` → 更新本索引
- **删除别名**：从对应 `aliases.md` 中移除 → 更新本索引数量
- **移动别名**：从原分组移除 → 追加到目标分组 → 更新两方索引
- **查看所有别名**：遍历各分组 `aliases.md` 的 `##` 标题

> AI生成