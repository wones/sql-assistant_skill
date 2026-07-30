---
name: sql-assistant
description: "Trino/Hive SQL assistant that generates SQL from natural language, maintains a local knowledge base of table schemas, business metrics, SQL aliases, and data processing flows. Supports natural language→SQL, alias resolution/management, SQL optimization, formatting, dialect conversion (MySQL/Trino/Doris/Hive), DDL/JSON import, business metric management, processing flow management, and data issue troubleshooting. Trigger when user asks SQL-related questions, wants to write/query/optimize/convert SQL, mentions Trino/Presto/Hive, needs to register/view table schemas or aliases, manage business metrics or data flows, or troubleshoot data quality/billing balance issues."
name_cn: SQL智能助手
description_cn: 基于知识库的 Trino/Hive SQL 生成与管理。支持自然语言→SQL、别名管理、SQL优化/格式化/方言转换、表结构导入、业务口径管理、加工流程管理、数据问题定位排查
create_source: super-agent-skill-creator
---

# SQL 智能助手

基于知识库的 Trino/Hive SQL 生成与管理工具。支持自然语言→SQL、别名系统、SQL优化、格式化、方言转换、表结构导入、业务口径管理、加工流程管理、数据问题定位排查。

## 全局注意事项

以下注意事项适用于所有流程，执行任何操作前都应遵守：

**知识库完备性**：
- SQL 生成前必须确认已录入相关表结构，知识库为空时应提醒用户先录入
- 用户问题中提到的表/字段在知识库中找不到时，不得编造，应主动告知并建议录入

**大小写与命名**：
- Trino 对标识符大小写不敏感（除非用双引号包裹），但建议表名、列名统一小写
- **Hive 表名不区分大小写**：流程定义中的 `int_mkt_channel_m` 与知识库中的 `INT_MKT_CHANNEL_M` 是同一张表，匹配时忽略大小写差异
- 分组名不可重复，建议用英文小写 + 下划线（如 `user_domain`、`finance`）
- 别名命名遵循 `{业务模块}_{查询类型}` 规范（详见 `references/best-practices.md`）

**字段语义映射**：
- 多表 JOIN 时同一语义可能对应不同字段名（如源A表 `user_id` vs 源B表 `uid`），**必须**先查 `references/best-practices.md` 第六节「字段语义映射」确认字段名，不可假设同名
- 新增表时若发现字段名与映射表已有语义冲突，须同步更新映射表

**文件操作安全**：
- 知识库文件可能被多个会话同时编辑，保存前应先读取最新内容再追加，避免覆盖
- 所有删除操作必须经用户确认后执行，不可恢复
- 修改操作建议在对话中说明改了什么，方便用户追溯

**分组一致性**：
- tables 和 aliases 的分组是独立管理的，分组名可以不同
- 同一业务域建议 tables 和 aliases 使用相同分组名，便于关联查找

**账期字段约定（全局通用）**：
- 日账期字段：`stat_date`，类型 string，格式 `YYYYMMDD`（如 `20240115`）
- 月账期字段：`stat_month`，类型 string，格式 `YYYYMM`（如 `202401`）
- **表名后缀自动判断**：表名以 `_D` 结尾 → 日表，账期用 `stat_date`；表名以 `_M` 结尾 → 月表，账期用 `stat_month`
- 生成SQL时，涉及时间条件**必须**填充对应账期字段，避免全表扫描
- 表名后缀既非 `_D` 也非 `_M` 时，查看表结构中的分区字段声明，若无则提醒用户补充账期信息

**基础表数据特性（全局通用）**：
- 基础表若无特殊说明，存储的是**全量快照数据**（每分区包含该业务线所有在网用户），非增量数据
- 日表默认更新时间为 **T-1 天**：即当天可查的最新分区为昨天（`CURRENT_DATE - INTERVAL '1' DAY`）
- 月表默认更新时间为 **T-1 月**：即当月可查的最新分区为上月（`date_trunc('month', CURRENT_DATE) - INTERVAL '1' MONTH`）
- 生成 SQL 时，取"最新数据"应使用 T-1 账期，而非 `CURRENT_DATE`；除非用户明确指定具体日期

**脚本依赖**：
- `alias_resolver.py`、`sql_optimizer.py`、`sql_formatter.py` 依赖 `sqlparse` 库，首次使用需 `pip install sqlparse`
- `sql_converter.py`、`parse_ddl.py`、`parse_json.py` 仅依赖标准库，无需额外安装

## 意图识别

| 用户意图 | 走流程 | 参考资源 |
|---------|--------|---------|
| 录入/查看/管理表结构 | A: 表结构管理 | `references/tables/`（按分组存储） |
| 录入/查看/管理别名 | B: 别名管理 | `references/aliases/`（按分组存储） |
| 录入/查看/管理业务口径 | I: 业务口径管理 | `references/metrics/`（按分组存储） |
| 录入/查看/管理加工流程 | J: 加工流程管理 | `references/flows/`（按分组存储） |
| 数据问题定位/排查 | K: 问题定位 | `references/flows/` + `references/tables/` + `references/metrics/` |
| 自然语言→生成SQL | C: SQL生成 | `references/tables/` + `references/aliases/` + `references/metrics/` |
| 还原别名SQL | D: 别名还原 | `scripts/alias_resolver.py` |
| 优化SQL | E: SQL优化 | `scripts/sql_optimizer.py` |
| 格式化SQL | F: SQL格式化 | `scripts/sql_formatter.py` |
| 方言转换 | G: 方言转换 | `scripts/sql_converter.py` + `references/dialect-mappings.md` |
| 使用规范/最佳实践 | H: 查看规范 | `references/best-practices.md` |

## 流程 A：表结构管理

**录入表结构**

三种方式：
1. **粘贴DDL** → 运行 `scripts/parse_ddl.py` 解析（支持 `--group --append` 直接落盘，见下方用法）→ 或 AI 直接解析后追加
2. **导入JSON**（数据平台导出的表元数据）→ 运行 `scripts/parse_json.py` 解析，自动提取表名、schema、字段、分区字段、维度关联、枚举值；支持 `--group --append` 直接落盘到分组 `tables.md` 并自动更新索引，免去 AI 手动编辑
3. **手动描述** → 询问表名、schema、字段列表、账期信息（日表stat_date/月表stat_month） → 整理追加到对应分组文件 → 更新索引

**parse_json.py 用法**（仅依赖标准库）：
```bash
# 仅解析输出到 stdout（查看结果，不落盘）
python scripts/parse_json.py --file path/to/table.json
python scripts/parse_json.py --file table.json --format json        # 结构化 JSON，便于 AI 检查
python scripts/parse_json.py --file table.json --schema db_tp       # 覆盖自动推断的 schema

# 直接落盘：追加到指定分组 tables.md 并自动更新 README.md 索引（推荐，免去 AI 手动编辑）
python scripts/parse_json.py --file table.json --group user_domain --append

# 分组下已存在同名表时默认拒绝，加 --force 覆盖旧内容（索引数量保持不变）
python scripts/parse_json.py --file table.json --group user_domain --append --force

# 批量导入：--file 指向目录，自动处理其下所有 .json/.txt 文件
python scripts/parse_json.py --file metadata/ --group user_domain --append
```

**parse_ddl.py 用法**（仅依赖标准库，参数与 parse_json.py 对齐）：
```bash
python scripts/parse_ddl.py --file path/to/ddl.sql                          # 解析输出 JSON
python scripts/parse_ddl.py --file ddl.sql --format markdown                # 输出 markdown
python scripts/parse_ddl.py --file ddl.sql --group user_domain --append   # 直接落盘 + 更新索引
python scripts/parse_ddl.py --file ddl.sql --group user_domain --append --force  # 覆盖同名表
```

落盘模式（`--group {分组} --append`）下脚本自动完成：解析 → 重名检测（拒绝/覆盖）→ 追加到 `{分组}/tables.md` 末尾 → 更新 `README.md` 索引数量。新分组会自动创建文件夹与文件头。AI 仅需在落盘后向用户报告结果（含成功/失败、字段重名等警告）。仅需查看解析结果而不落盘时，用 stdout 模式（不加 `--append`）。

**存储方式**：按业务分组存储在 `references/tables/` 目录下的子文件夹中，每个分组一个文件夹。

```
references/tables/
├── README.md          ← 索引文件
├── users/             ← 用户域分组
│   └── tables.md
├── finance/           ← 财务域分组
│   └── tables.md
└── ...
```

**分组规则**：
- 新增表时，若已有对应分组则追加到 `{分组}/tables.md`
- **用户未指定分组时，默认存入 `default/tables.md`，AI 不得自行创建新分组**
- 只有用户明确指定新分组名时，才创建新分组文件夹
- 索引文件 `references/tables/README.md` 记录所有分组列表

**分组管理操作**：
- **查看所有分组**：读取 `references/tables/README.md` 索引
- **新增分组**：创建 `{分组名}/tables.md` + 更新索引
- **查看某分组下的表**：读取 `{分组}/tables.md`
- **修改分组名**：重命名文件夹 + 更新索引
- **移动表到其他分组**：从原 `tables.md` 移除 → 追加到目标 `tables.md` → 更新索引
- **删除分组**（需确认）：
  1. 列出该分组下包含的所有表，提醒用户数据将永久丢失
  2. 必须等用户明确确认后才执行删除
  3. 确认后：删除整个 `{分组名}/` 文件夹及其下所有文件 + 更新索引
  4. 用户未确认则取消操作，不做任何删除

表结构格式（parse_json.py / parse_ddl.py 落盘时自动生成此格式）：
```markdown
## db.table_name_D

> 表注释: 表的中文名称

> 数据源: hive_db_xxx | 数据层级: DWM | 主题域: PROD

| 字段名 | 类型 | 注释 |
|--------|------|------|
| id | bigint | 主键ID |
| status | integer | 状态 | 枚举: 0:禁用, 1:启用 |
| order_date | date | 下单日期 |
| stat_date | string | 日账期 【分区字段】 |

- 分区字段: stat_date (string)，格式 yyyyMMdd
- 备注: 共 4 个字段（含 1 个枚举字段）；日账期 stat_date 为分区账期，查询必须用分区字段过滤，禁止全表扫描
```
> 注释列会自动拼接枚举值（`枚举: ...`）、维度关联（`关联维度: 表.字段->中文名`）、主键/分区标记（`【主键】`/`【分区字段】`）。`- 值域:` 列表为可选手动补充项（见下方"字段值域说明"）。

**账期字段说明**：
- 表名以 `_D` 结尾（日表）：自动使用 `stat_date`（string，YYYYMMDD），无需单独声明分区字段
- 表名以 `_M` 结尾（月表）：自动使用 `stat_month`（string，YYYYMM），无需单独声明分区字段
- 其他表名：若有分区字段需在 `分区字段:` 行声明，否则视为无分区表

**字段值域说明**（可选但推荐）：
- 枚举型字段（如 status、type）必须在注释中标注取值含义
- 值域信息可在 `- 值域:` 列表中结构化记录，便于SQL生成时正确引用
- 日期型字段标注有效范围，帮助判断查询条件是否合理

**基础表项管理**：
- **增**：解析 DDL 或手动描述 → 追加到 `{分组}/tables.md` 末尾 → 更新索引数量
- **查**：
  - 查看所有表：遍历各分组 `tables.md` 的 `##` 标题
  - 查看某张表详情：在对应 `tables.md` 中找到 `## schema.table` 章节
- **改**：直接编辑 `{分组}/tables.md` 中对应表的字段行（增删字段、改类型/注释）
- **删**（需确认）：
  1. 告知用户即将删除的表名及字段信息，提醒数据将永久丢失
  2. 用户确认后，从 `{分组}/tables.md` 中移除该 `## schema.table` 整个章节，并删除该文件
  3. 若删除后该分组文件夹为空，则一并删除分组文件夹 + 更新索引
  4. 若文件中仍有其他表，仅移除该章节 + 更新索引数量（文件保留）
  5. 用户未确认则取消，不做任何修改

### 流程 A 注意事项

- **DDL 解析能力**：`parse_ddl.py` 支持 Trino/Presto/Hive 风格 DDL，含 COMMENT、PARTITIONED BY、嵌套类型（`array<string>`、`map<string,string>`、`decimal(18,2)`）
- **DDL 解析局限**：依赖 DDL 中的 `COMMENT` 提取列注释，若 DDL 无注释则注释列为空，需手动补充
- **JSON 导入解析**：数据平台导出的表元数据 JSON 用 `parse_json.py` 解析，自动提取表名、schema、字段、类型、注释、分区字段、维度关联、枚举值、主键；schema 优先取 `metaDataSource.physicalDbName`，其次数据源去 `hive_` 前缀，再次 `default`；分区字段优先用 JSON 中 `partitionKey` 标记，无标记时按表名后缀兜底（`_D`→`stat_date`，`_M`→`stat_month`）；注释列会自动拼接枚举值（`枚举: ...`）与维度关联（`关联维度: 表.字段->中文名`）；表名后缀 `_D`/`_M` 决定账期字段与格式（`yyyyMMdd`/`yyyyMM`）
- **JSON 容错**：脚本剥离文件开头的 BOM/零宽空格等不可见字符，并用 `raw_decode` 只取第一个完整 JSON 对象，忽略末尾水印或附加文本（如 "AI生成"），避免解析失败；字段缺失 `label`/`dataType` 等属性时安全降级
- **账期字段识别**：表名以 `_D` 结尾自动识别为日表（用 `stat_date`），以 `_M` 结尾识别为月表（用 `stat_month`）；DDL 含 `PARTITIONED BY` 时按解析结果填充分区字段；两者都没有时需询问用户确认账期信息
- **直接落盘模式**：`parse_json.py` / `parse_ddl.py` 加 `--group {分组} --append` 可直接追加到分组 `tables.md` 并自动更新 `README.md` 索引，免去 AI 手动 Edit；新分组会自动创建文件夹与文件头（`# {分组}基础表`）
- **批量导入**：`--file` 指向目录时，JSON 解析器自动处理其下所有 `.json`/`.txt` 文件，逐个解析落盘，末尾汇总成功/失败数量；DDL 解析器按 `;` 拆分多条 `CREATE TABLE` 语句依次处理
- **字段重名去重**：解析时检测字段重名，自动仅保留首次出现，并在输出/落盘消息中标注警告（`字段重名（已自动去重，仅保留首次出现）: <字段名>`），AI 应将警告转达用户并建议核实源数据
- **追加位置约定**：新表统一追加到 `tables.md` 末尾；脚本会先剥离文件尾部残留的 `> AI生成` 水印行再追加，保持水印统一在文件最末尾
- **变更影响**：表结构变更（加列、删列、改类型）后，引用该表的别名可能需要同步更新列定义，应提醒用户检查
- **重名检查**：`--append` 落盘时脚本自动检测同分组下是否已存在同名表（`## schema.table`），存在则报错拒绝，需加 `--force` 才覆盖（覆盖时先移除旧章节再追加新内容，索引数量保持不变）；手动录入时 AI 同样需先检查重名并询问是覆盖还是取消
- **schema 前缀**：表名必须带 schema 前缀（如 `ods.user_info`），无 schema 时默认用 `default`

### 文件格式规范（确定性规则）

所有知识库文件的写入必须遵循以下规范，AI 不得自行决定格式，所有格式决策均由脚本或以下规则确定：

**tables.md 文件结构**（脚本自动维护，AI 不可手动改写文件头）：
```
# {分组名}基础表

> {分组名}业务域基础表结构定义。

---

## schema.table_name

> 表注释: ...
> 数据源: ... | 数据层级: ... | 主题域: ... | 表密度层级: ...

| 字段名 | 类型 | 注释 |
|--------|------|------|
| ... | ... | ... |

- 分区字段: field_name (type)，格式 xxx
- 备注: 共 N 个字段（含 X 个枚举字段、含 Y 个维度关联字段）；{日/月}账期 {field} 为分区账期，查询必须用分区字段过滤，禁止全表扫描

## schema.next_table
...
```

**格式要素规范**：

| 要素 | 确定性规则 | 禁止行为 |
|------|-----------|---------|
| meta 行 `>` 符号 | 表注释独立一行 `>`；数据源/层级/主题域/密度合并为同一行 `>`，用 ` | ` 分隔 | 不可拆成多个 `>` 引用行 |
| 分区字段行 | `字段名 (type)，格式 xxx` — 中文逗号在括号外 | 不可用英文逗号、不可把格式放括号内 |
| 备注行 | 固定模板：`共 N 个字段（含 X 个枚举字段、含 Y 个维度关联字段）；{日/月}账期 {field} 为分区账期，查询必须用分区字段过滤，禁止全表扫描`；无枚举/维度时对应子句省略 | 不可手写业务描述替换标准模板 |
| 章节间距 | `##` 标题前空一行，备注后空两行 | 不可增删空行 |
| 枚举标注 | `枚举: k1:v1, k2:v2` 拼在注释列末尾 | 不可单独成列 |
| 维度关联 | `关联维度: 表.字段->中文名` 拼在注释列末尾 | 不可单独成列 |
| 标记 | `【主键】`/`【分区字段】` 拼在注释列末尾 | 不可省略 |
| 表注释行 | 有注释必输出；无注释则跳过该 `>` 行 | 不可输出空注释 |
| 数据源等 meta | 有值必输出；缺省的字段跳过（不输出空项） | 不可输出 `数据源: ` |
| 水印 | AI 文件工具写入后会自动注入 `> AI生成` 尾标和 frontmatter；脚本写入不会；AI 不可手动添加或删除水印 | 不可编辑/移动/删除 AIGC frontmatter 或 `> AI生成` 行 |

**录入操作优先级**（AI 遇到选择时按此顺序决定，不可跳级）：

1. **有源文件时**：优先用脚本 `--group --append` 落盘（格式由脚本保证，AI 不做格式决策）
2. **需覆盖时**：加 `--force`（脚本先删旧章节再追加，索引数量不变）
3. **需查看解析结果时**：先 stdout 模式确认，再 `--append` 落盘
4. **手动录入时**：严格按上述格式规范手写，不得自创格式

## 流程 B：别名管理

别名 = SQL片段的命名引用，支持分层复用（L1基础层→L2聚合层→L3报表层）。

**存储方式**：按业务分组存储在 `references/aliases/` 目录下的子文件夹中，每个分组一个文件夹。

```
references/aliases/
├── README.md          ← 索引文件
├── users/             ← 用户域分组
│   └── aliases.md
├── orders/            ← 订单域分组
│   └── aliases.md
└── ...
```

**录入别名**：用户给出别名名+SQL内容 → 提取列名和依赖表 → 追加到对应分组 `aliases.md` → 更新索引

**分组规则**：
- 新增别名时，若已有对应分组则追加到 `{分组}/aliases.md`
- **用户未指定分组时，默认存入 `default/aliases.md`，AI 不得自行创建新分组**
- 只有用户明确指定新分组名时，才创建新分组文件夹
- 索引文件 `references/aliases/README.md` 记录所有分组列表

**分组管理操作**：
- **查看所有分组**：读取 `references/aliases/README.md` 索引
- **新增分组**：创建 `{分组名}/aliases.md` + 更新索引
- **查看某分组下的别名**：读取 `{分组}/aliases.md`
- **修改分组名**：重命名文件夹 + 更新索引
- **移动别名到其他分组**：从原 `aliases.md` 移除 → 追加到目标 `aliases.md` → 更新索引
- **删除分组**（需确认）：
  1. 列出该分组下包含的所有别名，提醒用户数据将永久丢失
  2. 必须等用户明确确认后才执行删除
  3. 确认后：删除整个 `{分组名}/` 文件夹及其下所有文件 + 更新索引
  4. 用户未确认则取消操作，不做任何删除

别名格式（写在对应分组文件中）：
```markdown
## alias_name
- 描述: 一句话说明
- 方言: trino
- 依赖表: table_a, table_b
- 依赖别名: base_alias
- 列定义:
  | 列名 | 类型 | 注释 |
  |------|------|------|
  | col1 | bigint | 说明 |
```sql
SELECT col1, col2 FROM table_a WHERE status = 1
```


**别名项管理**：
- **增**：用户提供别名名+SQL → 自动提取列名和依赖表 → 追加到 `{分组}/aliases.md` 末尾 → 更新索引数量
- **查**：
  - 查看所有别名：遍历各分组 `aliases.md` 的 `##` 标题
  - 查看某个别名详情：在对应 `aliases.md` 中找到 `## alias_name` 章节
- **改**：直接编辑 `{分组}/aliases.md` 中对应别名的字段行、SQL内容、描述等
- **删**（需确认）：
  1. 告知用户即将删除的别名名及依赖信息，提醒数据将永久丢失
  2. 用户确认后，从 `{分组}/aliases.md` 中移除该 `## alias_name` 整个章节（含 SQL 代码块），并删除该文件
  3. 若删除后该分组文件夹为空，则一并删除分组文件夹 + 更新索引
  4. 若文件中仍有其他别名，仅移除该章节 + 更新索引数量（文件保留）
  5. 用户未确认则取消，不做任何修改

**别名还原**：见流程 D

命名规范见 `references/best-practices.md`

### 流程 B 注意事项

- **循环依赖检测**：别名 A 依赖 B，B 又依赖 A 时会无限递归。录入或修改别名后应检查依赖链，发现循环立即告知用户
- **列定义一致性**：别名的列定义必须与 SQL 实际输出列一一对应，否则 SQL 生成时引用该别名的列会报错
- **修改同步**：修改别名 SQL 后，如果输出列发生变化（增删列、改列名），必须同步更新列定义
- **重名检查**：录入前检查同分组下是否已存在同名别名，存在则询问是覆盖还是取消
- **跨分组引用**：别名可以引用其他分组的别名（通过名称），但不建议跨太多分组，降低维护复杂度

## 流程 C：SQL 生成

1. 读取 `references/tables/`（按需读取相关分组文件）、`references/aliases/`（按需读取相关分组文件）和 `references/metrics/`（按需读取相关分组文件）
2. 分析用户问题，识别涉及的表/别名、字段、筛选条件、聚合需求；**若用户问题涉及已知业务口径（如"宽带新增用户数"），优先从 `references/metrics/` 获取口径定义**，按口径中的计算公式和过滤条件生成 SQL，不可自行编造 WHERE 条件
3. 生成 Trino SQL，遵循规范：
   - **中文别名用双引号**：`SELECT col1 AS "用户数"`
   - **优先使用 CTE** 组织复杂查询
   - 表名带 schema 前缀
   - 账期字段优先用于过滤（日表用 `stat_date`，月表用 `stat_month`）
   - 大表查询必须加 LIMIT 或账期过滤
4. **列名验证**：检查 SQL 中引用的列名是否在表结构或别名定义中存在，发现编造列名则修正
5. 输出 SQL + 逻辑说明

### SQL 生成注意事项与保障

**列名准确性**：
- 所有列名必须来源于已注册的表结构或别名定义，禁止编造
- 若用户问题中提到的字段在知识库中找不到，主动告知并建议录入表结构
- 聚合结果列（如 `COUNT(*) AS "订单数"`）视为合法，但基础列必须可追溯
- 引用别名时，从别名定义的列定义中取列名，不从 SQL 代码块中猜测

**语法正确性**：
- 严格遵循 Trino 语法，不确定时查阅 `references/trino-reference.md`
- 字符串用单引号 `'value'`，标识符/中文别名用双引号 `"别名"`
- 分页用 `OFFSET ... LIMIT ...`，不用 MySQL 的 `LIMIT offset, rows`
- 日期提取用 `EXTRACT(YEAR FROM col)`，不用 MySQL 的 `YEAR(col)`
- 空值处理用 `COALESCE()`，不用 MySQL 的 `IFNULL()`

**安全约束**：
- 默认加 `LIMIT`，防止返回海量结果
- 禁止生成 `DROP`、`TRUNCATE`、`DELETE`、`UPDATE`、`INSERT` 等写操作语句
- 涉及大表时必须提醒加账期过滤
- 不生成 DDL 语句（CREATE/ALTER/DROP TABLE）

**性能意识**：
- 账期字段必须优先用于 WHERE 过滤（日表 `stat_date`，月表 `stat_month`）
- 避免 `SELECT *`，只查询需要的列
- 子查询优先转为 JOIN 或 CTE
- 多表 JOIN 时注意驱动表选择（小表在前）

**可读性**：
- 复杂查询用 CTE 拆分，每个 CTE 单一职责
- 逗号前置写法：`, col2`
- 关键字大写
- 输出附带注释说明用途和涉及的表

## 流程 D：别名还原

将含别名的SQL展开为完整可执行SQL。

运行 `scripts/alias_resolver.py`（依赖 `sqlparse` 库，需 `pip install sqlparse`）：
```bash
python scripts/alias_resolver.py --aliases references/aliases/ --sql "SELECT * FROM user_base WHERE age > 18"
```

脚本基于 sqlparse 做 token 级解析，精确识别 FROM/JOIN 后的表名，递归展开 SQL 中的别名引用为子查询。支持：
- FROM/JOIN 后带表别名（`user_base ub`、`user_base AS ub`）
- WHERE/GROUP BY/ORDER BY 等关键字不会被误认为表名
- 嵌套别名递归展开（L1→L2→L3）
- 子查询（Parenthesis）内部的别名也会展开
- 大小写不敏感匹配
- `_` 后缀兼容（`user_base_` 匹配别名 `user_base`）
- 循环依赖检测（visited 集合防环，最大深度 10 层）

AI也可自行根据 aliases.md 手动展开，脚本用于验证复杂场景。

### 流程 D 注意事项

- **依赖安装**：脚本依赖 `sqlparse` 库，首次使用需执行 `pip install sqlparse`
- **递归深度**：别名引用别名时递归展开，最大深度 10 层，超出时报错并提示可能存在循环依赖
- **循环依赖**：脚本通过 visited 集合检测循环引用，遇到循环时跳过而非崩溃，输出中可能残留未展开的别名名
- **展开后格式化**：展开后的 SQL 可能很长且缩进混乱，建议展开后再跑一次流程 F（格式化）
- **列名冲突**：多个别名展开后可能出现同名列，需检查并加表别名前缀消歧
- **大小写不敏感**：别名匹配大小写不敏感，`USER_BASE` 可匹配别名 `user_base`
- **schema 前缀跳过**：带 schema 前缀的表引用（如 `ods.users`）不会被误认为别名

## 流程 E：SQL 优化

运行 `scripts/sql_optimizer.py`（依赖 `sqlparse` 库）：
```bash
python scripts/sql_optimizer.py "SELECT * FROM (SELECT id, name FROM users) AS t WHERE id > 10"
```

优化能力（详见 `references/optimization-rules.md`）：
- 移除注释、冗余条件（WHERE 1=1）
- 去重列、大写关键字
- 内联简单子查询（`SELECT * FROM (SELECT cols FROM table) AS t` → `SELECT t.cols FROM table t`）
- 子查询转 JOIN（`WHERE col IN (SELECT ...)` → `INNER JOIN`，`NOT IN` → `LEFT JOIN ... IS NULL`）
- IN 子查询→EXISTS（带 WHERE 条件的子查询）
- 移除冗余派生表（`SELECT * FROM (SELECT * FROM table) AS t` → `SELECT * FROM table t`）
- 输出优化分析报告（`--analyze` 参数，输出涉及的表/JOIN/子查询/警告/建议）

### 流程 E 注意事项

- **语义等价**：优化器基于规则匹配，复杂场景可能误判，优化后必须人工确认语义是否等价
- **子查询转 JOIN 风险**：子查询含 `LIMIT`、`DISTINCT` 时转 JOIN 可能改变结果集，脚本会跳过，AI 手动优化时也需警惕
- **IN → EXISTS 的 NULL 语义**：子查询列含 NULL 值时，`IN` 和 `EXISTS` 行为可能不同，转换后需提醒用户验证
- **不可逆操作**：优化会移除注释和多余空格，原始 SQL 建议保留备份
- **优化建议**：分析报告中的"建议"项不一定都适用，需要结合实际数据量和表结构判断

## 流程 F：SQL 格式化

运行 `scripts/sql_formatter.py`（依赖 `sqlparse` 库）：
```bash
python scripts/sql_formatter.py "SELECT id,name FROM users WHERE id>10" --style standard
```

三种风格：
- `standard` — 标准缩进，关键字大写，逗号前置（默认）
- `compact` — 单行紧凑，移除注释
- `expanded` — 每个关键字独占一行，逗号前置

### 流程 F 注意事项

- **纯文本处理**：格式化不改变 SQL 语义，仅调整缩进和换行
- **字符串字面值**：含特殊字符（如换行符、引号）的字符串可能被误处理，格式化后建议检查字符串完整性
- **超长 SQL**：单行超 200 字符的 SQL 格式化后可能仍有可读性问题，建议用 `expanded` 风格
- **不可逆**：`compact` 风格会移除所有换行和缩进，原始格式无法恢复

## 流程 G：方言转换

运行 `scripts/sql_converter.py`：
```bash
python scripts/sql_converter.py "SELECT IFNULL(a, 0), YEAR(dt) FROM t LIMIT 10, 20" --from mysql --to trino
```

支持：MySQL ↔ Trino ↔ Doris（6个方向）

映射规则见 `references/dialect-mappings.md`，覆盖：
- 函数名差异（IFNULL/COALESCE、SUBSTRING/SUBSTR、APPROX_DISTINCT/APPROX_COUNT_DISTINCT 等）
- 分页语法（LIMIT offset,rows ↔ OFFSET rows LIMIT count）
- 日期提取函数（YEAR(dt)/MONTH(dt) ↔ EXTRACT(YEAR FROM dt)/EXTRACT(MONTH FROM dt)），支持嵌套函数

### 流程 G 注意事项

- **不完全等价**：转换基于函数映射表，复杂嵌套函数可能无法完全转换，脚本对未覆盖的函数原样保留不做处理，AI 应识别未转换的函数并提示用户手动确认
- **NULL 语义差异**：MySQL 的 `IFNULL` 与 Trino 的 `COALESCE` 在多参数场景行为不同（`IFNULL` 只接受两参数），转换时需注意
- **分页语法**：MySQL 的 `LIMIT offset, rows` 与 Trino 的 `OFFSET rows LIMIT count` 语义等价但参数顺序不同，转换后需验证
- **方言特有函数**：某些函数只存在于特定方言（如 MySQL 的 `GROUP_CONCAT`），无等价映射时需手动改写
- **转换后验证**：建议转换后跑一次流程 F（格式化）使输出更易读，并人工确认语义

## 流程 H：使用规范

读取 `references/best-practices.md` 向用户展示：
- 别名命名规范（`{业务模块}_{查询类型}`）
- 分组策略（按业务域 / 按使用频率）
- SQL编写规范（禁止 SELECT *、必须注释等）
- 分层架构实践（L1→L2→L3）
- 依赖管理和循环依赖避免

## 流程 I：业务口径管理

业务口径 = 业务指标的标准定义，包含计算公式、过滤条件、依赖表等。SQL 生成时涉及已知口径必须引用，禁止 AI 自行推断 WHERE 条件。

**存储方式**：按业务分组存储在 `references/metrics/` 目录下的子文件夹中，每个分组一个文件夹。

```
references/metrics/
├── README.md          ← 索引文件
├── sales/             ← 业务域分组
│   └── metrics.md
└── ...
```

**口径格式**（写在对应分组文件中）：
```markdown
## 日新增用户数

- 定义: 当日新注册的用户数
- 计算公式: COUNT(*)
- 依赖表: ods.user_info_d
- 过滤条件: is_new = 1 AND status = 'active'
- 账期: stat_date（日账期）
- 排除条件: is_test = 0（不含测试用户）
- 备注: 新用户标识通过 is_new 字段判定；测试用户单独统计
```

**格式要素规范**（确定性规则，AI 不可自创格式）：

| 要素 | 规则 | 必选 |
|------|------|------|
| `## 指标名` | 中文，简洁明确，不可含歧义 | 是 |
| `- 定义:` | 一句话说明该指标的业务含义 | 是 |
| `- 计算公式:` | SQL 聚合表达式（如 `COUNT(*)`、`SUM(amount)`） | 是 |
| `- 依赖表:` | `schema.table` 格式，多个用逗号分隔 | 是 |
| `- 过滤条件:` | WHERE 子句的核心条件，用 SQL 语法写 | 是 |
| `- 账期:` | 依赖的账期字段及类型（日/月） | 是 |
| `- 排除条件:` | 需排除的特殊情况（如携入用户），无则省略 | 否 |
| `- 备注:` | 补充说明（口径变更历史、特殊边界等），无则省略 | 否 |

**录入口径**：

1. **用户提供口径定义** → 按格式规范整理 → 追加到对应分组 `metrics.md` → 更新索引
2. **AI 从字段注释/枚举推断** → 仅当用户明确要求"根据表结构补充常见口径"时执行，推断的口径必须标注 `[推断]` 前缀提醒用户确认
3. **从需求中提取** → 用户问"XXX怎么算" → AI 根据已知口径回答；若无口径则告知用户并建议录入

**分组规则**：
- 与 tables/aliases 分组独立管理，但建议同一业务域使用相同分组名
- **用户未指定分组时，默认存入 `default/metrics.md`，AI 不得自行创建新分组**
- 只有用户明确指定新分组名时，才创建新分组文件夹
- 索引文件 `references/metrics/README.md` 记录所有分组列表

**分组管理操作**：
- **查看所有分组**：读取 `references/metrics/README.md` 索引
- **新增分组**：创建 `{分组名}/metrics.md` + 更新索引
- **查看某分组下的口径**：读取 `{分组}/metrics.md`
- **删除分组**（需确认）：与流程 A/B 规则一致

**口径项管理**：
- **增**：按格式规范整理 → 追加到 `{分组}/metrics.md` 末尾 → 更新索引数量
- **查**：
  - 查看所有口径：遍历各分组 `metrics.md` 的 `##` 标题
  - 查看某个口径详情：在对应 `metrics.md` 中找到 `## 指标名` 章节
- **改**：直接编辑 `{分组}/metrics.md` 中对应口径的字段
- **删**（需确认）：与流程 A/B 规则一致

### 流程 I 注意事项

- **口径优先于推断**：SQL 生成时，若 `references/metrics/` 中存在匹配的口径定义，必须按口径的过滤条件和计算公式生成，不可自行推断 WHERE 条件
- **口径缺失时的处理**：无对应口径时，AI 根据表结构的字段注释、枚举值生成 SQL，但在输出注意事项中标注"该指标无口径定义，WHERE 条件基于字段注释推断，建议录入口径"
- **口径与表结构一致**：口径引用的依赖表和字段必须存在于 `references/tables/` 中，录入时需校验；表结构变更后需同步检查相关口径
- **重名检查**：录入前检查同分组下是否已存在同名口径，存在则询问是覆盖还是取消
- **推断口径需确认**：AI 推断的口径定义必须在定义行标注 `[推断]`，如 `- 定义: [推断] 当日新入网的固网宽带用户数`，用户确认后去除标记

## SQL 生成规范

### Trino 语法要点

详见 `references/trino-reference.md`。核心：
- 字符串单引号 `'value'`，标识符双引号 `"alias"`
- 日期：`date_parse()`, `format_datetime()`, `CURRENT_DATE`
- 聚合：`COUNT()`, `SUM()`, `APPROX_DISTINCT()`
- 窗口：`ROW_NUMBER() OVER(...)`, `RANK() OVER(...)`
- 条件：`CASE WHEN ... END`, `IF(expr, v1, v2)`
- 数组：`ARRAY[]`, `ARRAY_AGG()`, `UNNEST()`
- JSON：`json_extract_scalar()`, `json_parse()`

### 输出格式

每次生成 SQL 后，输出**两部分**：SQL 代码 + 注意事项提醒。

**第一部分：SQL 代码**

```sql
-- 用途：[一句话描述]
-- 涉及表：[表名列表]
WITH
  cte1 AS (...),
  cte2 AS (...)
SELECT
  col1 AS "中文别名"
  , col2 AS "中文别名2"
FROM cte2
WHERE ...
GROUP BY ...
ORDER BY ...
LIMIT 1000;
```

**第二部分：注意事项**

根据本次 SQL 的实际情况，从以下维度选择相关项输出（无则省略，不要输出无意义的套话）：

- **账期过滤**：涉及日表（`_D`）或月表（`_M`）时，提醒用户确认账期条件是否充分（如 `stat_date = '20260727'`），避免全表扫描
- **数据量提醒**：预估结果集大小，超过 10 万行时提醒加 LIMIT 或缩小范围
- **未找到的列/表**：用户提到了知识库中不存在的字段或表，告知用户并建议录入
- **性能风险**：存在笛卡尔积、多层嵌套子查询、无账期过滤的大表 JOIN 等，给出优化建议
- **语义确认**：当用户问题有歧义时（如"活跃用户"的定义不明确），列出你的理解并请用户确认
- **近似函数**：使用了 `APPROX_DISTINCT()` 等近似函数时，提醒结果有微小误差
- **空值风险**：涉及可能为 NULL 的字段做聚合或 JOIN 时，提醒空值对结果的影响

示例输出：

```
**注意事项**：
1. 涉及日表 ods.user_log_D，当前 SQL 未加 stat_date 过滤，建议加上账期范围避免全表扫描
2. "活跃用户"理解为近 7 天有登录记录的用户，如定义不同请告知
3. COUNT(DISTINCT user_id) 建议替换为 APPROX_DISTINCT(user_id) 提升性能（结果有 <2% 误差）
```

### 流程 C 额外注意事项

- **列名来源**：所有列名必须来自知识库中已注册的表结构或别名定义，禁止凭空编造
- **口径优先**：涉及业务指标时，先检索 `references/metrics/`，有口径定义则严格按口径生成 WHERE 条件和计算公式，不可自行推断；无口径时基于字段注释推断，但必须输出注意事项提醒用户确认
- **方言锁定**：SQL 始终生成 Trino 语法，如需其他方言走流程 G 转换
- **别名展开策略**：
  - 简单查询（仅引用1个别名，无额外JOIN）：直接用别名名引用（`FROM user_base`），后续按需走流程D还原
  - 复杂查询（多表JOIN、CTE嵌套）：将别名展开为子查询内联到SQL中，避免用户还需额外执行还原步骤
  - 生成的SQL需直接可执行时：展开别名
- **LIMIT 默认值**：未指定行数时默认 `LIMIT 1000`，用户可要求调整

### 时间条件处理

用户提到时间条件时，AI 需根据表名后缀自动选择正确的账期字段进行过滤：

**判断规则**（详见全局注意事项-账期字段约定）：
- 表名以 `_D` 结尾（日表）→ 用 `stat_date`（string，格式 `YYYYMMDD`）
- 表名以 `_M` 结尾（月表）→ 用 `stat_month`（string，格式 `YYYYMM`）

**绝对时间表达**：
- "2024年1月的订单" → 日表：`WHERE stat_date BETWEEN '20240101' AND '20240131'`
- "2024年1月的订单" → 月表：`WHERE stat_month = '202401'`
- "2024年全年" → 日表：`WHERE stat_date BETWEEN '20240101' AND '20241231'`
- "2024年全年" → 月表：`WHERE stat_month BETWEEN '202401' AND '202412'`

**相对时间表达**（基于 `format_datetime` 生成对应格式）：
- 日表"最近7天" → `WHERE stat_date >= format_datetime(CURRENT_DATE - INTERVAL '7' DAY, 'yyyyMMdd')`
- 日表"本月" → `WHERE stat_date >= format_datetime(date_trunc('month', CURRENT_DATE), 'yyyyMMdd')`
- 日表"上月" → `WHERE stat_date BETWEEN format_datetime(date_trunc('month', CURRENT_DATE) - INTERVAL '1' MONTH, 'yyyyMMdd') AND format_datetime(date_trunc('month', CURRENT_DATE) - INTERVAL '1' DAY, 'yyyyMMdd')`
- 月表"最近3个月" → `WHERE stat_month >= format_datetime(date_trunc('month', CURRENT_DATE) - INTERVAL '2' MONTH, 'yyyyMM')`
- 月表"上月" → `WHERE stat_month = format_datetime(date_trunc('month', CURRENT_DATE) - INTERVAL '1' MONTH, 'yyyyMM')`

**注意**：`format_datetime` 的格式串大小写敏感，`yyyyMMdd` 生成 `20240115`，`yyyyMM` 生成 `202401`

### 无账期表处理策略

- 表名后缀为 `_D` 或 `_M` 的表，自动使用 `stat_date` / `stat_month` 过滤，不存在无账期问题
- 表名后缀既非 `_D` 也非 `_M`，且表结构中未声明分区字段时，视为无账期表：
  - 生成SQL时**必须加 LIMIT**，并在注意事项中提醒全表扫描风险
  - 若用户未指定行数，建议 `LIMIT 10000` 并说明原因
  - 提醒用户确认该表是否有账期字段（`stat_date` / `stat_month`），如有建议补充到表结构中

### 自然语言意图模式映射

从自然语言到SQL模式的常见映射，AI 应主动识别：

| 自然语言模式 | SQL 模式 | 示例 |
|-------------|---------|------|
| "TOP N / 前N名" | `ORDER BY ... DESC/ASC` + `LIMIT N` | "销售额前10的用户" → ORDER BY + LIMIT 10 |
| "最近N天/月" | `WHERE stat_date/stat_month >= ...` | "最近30天订单" → stat_date >= format_datetime(CURRENT_DATE - INTERVAL '30' DAY, 'yyyyMMdd') |
| "环比/同比" | CTE + LEFT JOIN + 计算变化率 | "本月比上月增长多少" → 两个CTE对比 |
| "占比/百分比" | `SUM(CASE WHEN ... THEN 1 ELSE 0 END) / COUNT(*)` | "付费用户占比" → 条件计数/总数 |
| "去重统计" | `COUNT(DISTINCT col)` 或 `APPROX_DISTINCT(col)` | "有多少不同用户下单" → COUNT(DISTINCT user_id) |
| "分组排名" | `ROW_NUMBER() OVER (PARTITION BY ... ORDER BY ...)` | "每个部门薪资最高的3人" → 窗口函数 |
| "是否存在/有无" | `EXISTS` 或 `LEFT JOIN ... IS NULL` | "有哪些用户没下过单" → LEFT JOIN + IS NULL |
| "趋势/按天统计" | `GROUP BY stat_date ORDER BY stat_date` | "每天的订单量趋势" → GROUP BY stat_date |
| "累计/Running total" | `SUM() OVER (ORDER BY ... ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)` | "累计销售额" → 窗口聚合 |
| "同行/同类对比" | 自连接或 LAG/LEAD | "比同部门平均薪资高的人" → 子查询对比 |

### NULL 值处理

生成SQL时关注可能产生NULL的场景：
- **LEFT JOIN 产生NULL**：右表无匹配行时字段为NULL，做聚合时需 `COALESCE(col, 0)` 处理
- **COUNT 的 NULL 语义**：`COUNT(col)` 不计NULL行，`COUNT(*)` 计所有行，按用户语义选择
- **NULL 参与 WHERE**：`WHERE col != 'x'` 不包含 col 为 NULL 的行，需明确写 `WHERE col != 'x' OR col IS NULL`
- **聚合函数与NULL**：`SUM(col)` 忽略NULL，若全为NULL则结果为NULL而非0

### 安全约束

- 默认加 LIMIT，防海量结果
- 禁止生成 DROP/TRUNCATE/DELETE/UPDATE/INSERT
- 涉及大表时提醒加账期过滤

## 流程 J：加工流程管理

加工流程记录表到表的转换链路，是问题定位（流程 K）的基础。每个加工流程描述一条从上游表到下游表的多步骤转换逻辑。

**存储方式**：按业务分组存储在 `references/flows/` 目录下，与 tables/aliases/metrics 平行。

```
references/flows/
├── README.md          ← 索引文件
├── sales/
│   └── flows.md
└── ...
```

**录入加工流程**：用户描述加工链路 → AI 整理为标准格式 → 追加到对应分组 `flows.md` → 更新索引

**分组规则**：
- **用户未指定分组时，默认存入 `default/flows.md`，AI 不得自行创建新分组**
- 只有用户明确指定新分组名时，才创建新分组文件夹

**加工流程格式**（严格遵循，AI 不得自行增减字段）：

```markdown
## 流程名: user_daily_new

- 描述: 日新增用户汇总
- 上游表: ods.user_info_d
- 下游表: rpt.user_daily_new_d
- 账期对齐: stat_date (yyyyMMdd) → stat_date (yyyyMMdd)
- 加工步骤:
  | 步骤 | 类型 | 输入表 | 输出表 | 说明 | 关键逻辑 |
  |------|------|--------|--------|------|---------|
  | 1 | 过滤 | ods.user_info_d | (中间结果) | 新用户+有效状态 | WHERE is_new = 1 AND status = 'active' |
  | 2 | 排除 | (中间结果) | (中间结果) | 排除测试用户 | WHERE is_test = 0 |
  | 3 | 聚合 | (中间结果) | rpt.user_daily_new_d | 按地市汇总 | GROUP BY city_id, stat_date |
  | 4 | 映射 | rpt.user_daily_new_d | rpt.user_daily_new_d | 地市名称关联 | JOIN dim.dim_city ON city_id |
- 数据量级: 上游 ~500万/分区 → 下游 ~200行/分区
- 质量校验: 下游 SUM(新增数) = 上游过滤后 COUNT(DISTINCT user_id)
- 完整SQL: 无（纯查询，步骤表格已覆盖全部逻辑）
- 备注: 无
```

**加工步骤表格列说明**：

| 列 | 必填 | 说明 |
|----|------|------|
| 步骤 | 是 | 序号（1, 2, 3...），按执行顺序排列 |
| 类型 | 是 | 操作类型，见下方类型说明 |
| 输入表 | 是 | 本步骤读取的表名（或 `(中间结果)` 表示上一步的输出） |
| 输出表 | 是 | 本步骤产出的表名（或 `(中间结果)` 表示传递给下一步） |
| 说明 | 是 | 一句话描述本步骤做了什么 |
| 关键逻辑 | 是 | WHERE条件/JOIN条件/聚合公式等核心逻辑摘要（非完整SQL） |

**字段说明**：

| 字段 | 必填 | 说明 |
|------|------|------|
| 描述 | 是 | 一句话说明加工目的 |
| 上游表 | 是 | 最初的输入表（可多个，逗号分隔），优先填已注册的表 |
| 下游表 | 是 | 最终的输出表（可多个），优先填已注册的表 |
| 账期对齐 | 是 | 上游→下游的账期字段映射，如 `stat_date → stat_month` 需注明转换关系 |
| 加工步骤 | 是 | 有序步骤表格，含输入表/输出表，支持中间临时表和多段串行 |
| 数据量级 | 否 | 上下游行量估算，帮助判断性能 |
| 质量校验 | 否 | 上下游数据一致性校验公式，问题定位时自动使用 |
| 完整SQL | 否 | 每个步骤对应的完整SQL文件路径列表（见下方"完整SQL文件存放"） |
| 备注 | 否 | 补充说明 |

**完整SQL文件存放**：

当加工流程有完整 SQL 语句时，将 SQL 存为独立文件，在流程的"完整SQL"字段中引用路径：

```
references/flows/
├── {分组}/
│   ├── flows.md          ← 流程定义
│   └── sql/              ← 完整SQL文件目录
│       ├── {流程名}_1.sql
│       ├── {流程名}_2.sql
│       └── {流程名}_3.sql
```

- 文件命名规则：`{流程名}_{步骤号}.sql`
- 每个文件开头用注释标注：流程名、步骤号、说明、数据源、账期变量
- 流程定义中的"完整SQL"字段列出每个步骤的路径，格式：`步骤N: flows/{分组}/sql/{流程名}_{步骤号}.sql`
- 无完整 SQL 的简单流程（如纯查询）可不填此字段

**加工步骤类型说明**：

| 类型 | 含义 | 典型逻辑 |
|------|------|---------|
| 过滤 | 保留满足条件的行 | WHERE 条件 |
| 排除 | 去除不满足条件的行 | WHERE 条件 != 值 |
| 聚合 | 按维度分组计算 | GROUP BY + SUM/COUNT |
| 映射 | 字段名/值转换 | CASE WHEN / JOIN 维表 |
| 去重 | 去除重复行 | DISTINCT / ROW_NUMBER |
| 窗口 | 排名/累计/偏移 | ROW_NUMBER / SUM OVER |
| 关联 | 多表 JOIN | JOIN 条件 |
| union | 合并多个数据集 | UNION ALL |
| 其他 | 不属于以上类型 | 自由描述 |

**分组管理与增删查改**：与 tables/aliases/metrics 完全一致（创建分组文件夹、更新索引、删除需确认等），不再重复。

### 流程 J 注意事项

- **上游表/下游表**：填最初输入和最终输出的表，优先填知识库中已注册的表；未注册的表（如临时表）在步骤表格的输入表/输出表列中体现
- **中间临时表**：多段串行场景中，步骤 N 的输出表即步骤 N+1 的输入表（如 `db_temp.xxx_01`），在步骤表格中体现，无需在"上游表/下游表"字段中重复
- **步骤粒度**：每个步骤应是单一操作，避免"过滤+聚合"合并为一步；粒度过粗会降低问题定位精度。多段 SQL 串行时，每段 SQL 对应一个或多个步骤
- **关键逻辑**：步骤表格的"关键逻辑"列填核心条件摘要（WHERE/JOIN/聚合公式），非完整 SQL；如需存放完整 SQL，在备注中引用别名名或单独说明
- **质量校验公式**：是问题定位的关键，AI 应主动引导用户提供校验逻辑（如"上下游行数差"、"金额汇总相等"）
- **链路拼接**：下游表 A 的输出又是下游表 B 的输入时，形成链路；问题定位时自动拼接多段流程
- **与业务口径的区别**：业务口径（Flow I）定义"指标怎么算"，加工流程定义"表怎么产出"；口径关注业务语义，流程关注数据工程

## 流程 K：问题定位

当用户报告数据问题（如"下游表数据不对"、"汇总数少了"），基于加工流程逐步排查，生成诊断 SQL。

**触发场景**：
- "XX表数据有问题"
- "汇总数不对/少了/多了"
- "上下游对不上"
- "XX指标异常"

**定位流程**：

1. **确认问题表和现象**：明确哪张表、哪个字段、什么异常（偏多/偏少/缺失/重复）
2. **查找加工流程**：在 `references/flows/` 中搜索涉及该下游表的加工流程
3. **逐层生成诊断 SQL**：从下游→上游逐步回溯，每个步骤生成一段比对 SQL
4. **输出诊断脚本**：所有诊断 SQL 按"从上游到下游"顺序排列，用户逐步执行定位

**诊断 SQL 模板**（每个加工步骤自动生成）：

```sql
-- 【诊断】步骤 N: {步骤说明}
-- 预期: {质量校验公式}
SELECT
  COUNT(*) AS "当前步骤行数"
  , {关键聚合字段} AS "关键指标"
FROM {上游表}
WHERE {步骤过滤条件}
  AND stat_date = '{指定账期}'
;
```

**输出格式**：

```
=== 问题定位报告 ===
问题表: rpt.user_daily_new_d
问题现象: 日新增数比预期少 500
涉及流程: user_daily_new（4个步骤）

--- 步骤 1: 过滤新用户 ---
SQL: [诊断SQL]
预期行数: ~200万（全量500万中新用户占40%）
定位逻辑: 如果此步骤行数正常，排除上游数据问题

--- 步骤 2: 过滤有效状态 ---
SQL: [诊断SQL]
预期行数: ~1万
定位逻辑: 如果此步骤行数偏少，说明is_new标记有误

...（逐步骤展开）

--- 诊断建议 ---
1. 先执行步骤1的SQL，确认上游全量数据是否正常
2. 逐步向下执行，观察哪一步出现数量跳变
3. 在跳变步骤定位具体原因（过滤条件变化/字段值异常/上游延迟）
```

### 流程 K 注意事项

- **流程缺失处理**：若问题表没有对应的加工流程记录，AI 应告知用户并建议先录入（流程 J），同时可基于表结构和业务口径手动推断生成临时诊断 SQL
- **账期一致性**：诊断 SQL 中上下游必须使用相同业务日期，避免因账期不对齐导致误判
- **全量快照注意**：基础表存储全量数据，诊断时注意 `COUNT(*)` 是全量行数而非增量，需加过滤条件才能比对
- **逐步执行**：建议用户按顺序逐步执行诊断 SQL，而非一次性全部执行，每步结果反馈后再决定下一步
- **无加工流程时的降级**：当知识库中无对应加工流程时，AI 基于 tables + metrics 推断生成粗粒度诊断 SQL，并在输出中标注 `[推断]`，提示用户确认后可录入为正式加工流程
- **性能提示**：诊断 SQL 涉及大表时同样需加分区过滤和 LIMIT，避免全表扫描

## 资源说明

| 路径 | 用途 |
|------|------|
| `references/tables/` | 表结构知识库（按分组存储） |
| `references/aliases/` | 别名知识库（按分组存储） |
| `references/metrics/` | 业务口径知识库（按分组存储） |
| `references/flows/` | 加工流程知识库（按分组存储） |
| `references/trino-reference.md` | Trino SQL 语法速查 |
| `references/optimization-rules.md` | SQL优化规则详解 |
| `references/dialect-mappings.md` | 方言转换映射表 |
| `references/best-practices.md` | 使用规范与最佳实践 |
| `scripts/parse_ddl.py` | DDL 解析工具 |
| `scripts/parse_json.py` | 数据平台 JSON 解析工具 |
| `scripts/alias_resolver.py` | 别名递归还原引擎 |
| `scripts/sql_optimizer.py` | SQL 优化引擎 |
| `scripts/sql_formatter.py` | SQL 格式化器 |
| `scripts/sql_converter.py` | 方言转换器 |
