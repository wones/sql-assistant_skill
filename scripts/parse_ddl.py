#!/usr/bin/env python3
"""
DDL 解析工具：从 CREATE TABLE 语句中提取表名、字段、类型、注释等信息。
支持 Trino/Presto/Hive 风格的 DDL。

用法：
  # 从命令行参数读取 DDL，输出 JSON
  python parse_ddl.py "CREATE TABLE schema.table (id bigint, name varchar, ...) COMMENT '表注释'"

  # 从文件读取 DDL
  python parse_ddl.py --file path/to/ddl.sql

  # 输出 markdown 格式
  python parse_ddl.py --file ddl.sql --format markdown

  # 直接落盘：追加到指定分组的 tables.md 并更新索引
  python parse_ddl.py --file ddl.sql --group user_domain --append

  # 覆盖已存在的同名表（默认拒绝重名）
  python parse_ddl.py --file ddl.sql --group user_domain --append --force

输出：JSON 格式的解析结果（默认）或 Markdown
"""

import argparse
import json
import os
import re
import sys

# 脚本所在目录的上一级即 skill 根目录
_SKILL_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TABLES_DIR = os.path.join(_SKILL_ROOT, "references", "tables")
_TABLES_INDEX = os.path.join(_TABLES_DIR, "README.md")


def _mark_partition(fields, target_name):
    """将指定名称的字段标记为分区字段（在注释追加【分区字段】）。"""
    for f in fields:
        if f["name"] == target_name:
            if "【分区字段】" not in f["comment"]:
                f["comment"] = (f["comment"] + " 【分区字段】") if f["comment"] else "【分区字段】"
            return


def _extract_partition_name(raw):
    """从 PARTITIONED BY 的原始字段定义中提取字段名。

    例如: 'region string' → 'region', 'stat_date string' → 'stat_date'
    """
    parts = raw.strip().split()
    return parts[0] if parts else raw.strip()


def parse_ddl(ddl_text: str) -> dict:
    """解析单条 CREATE TABLE DDL 语句，返回结构化信息。"""

    # 标准化空白
    ddl = ddl_text.strip()
    # 移除尾部分号
    ddl = ddl.rstrip(";").strip()

    # 提取表名
    table_match = re.search(
        r"CREATE\s+(?:EXTERNAL\s+)?TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([^\s(]+)",
        ddl,
        re.IGNORECASE,
    )
    if not table_match:
        return {"error": "无法识别 CREATE TABLE 语句"}

    full_table_name = table_match.group(1)

    # 拆分 schema 和 table
    parts = full_table_name.replace("`", "").replace('"', "").split(".")
    if len(parts) == 2:
        schema_name, table_name = parts
    else:
        schema_name = "default"
        table_name = parts[0]

    # 提取表注释（取最后一个 COMMENT，通常在括号外）
    table_comment = ""
    comment_matches = re.findall(r"COMMENT\s+'([^']*)'", ddl, re.IGNORECASE)
    if comment_matches:
        table_comment = comment_matches[-1]

    # 提取字段定义区域（第一个括号对）
    # 用深度计数精确匹配括号，避免贪婪匹配吞掉后续字段或分区定义
    paren_start = None
    paren_end = None
    depth = 0
    for i, char in enumerate(ddl):
        if char == "(":
            if depth == 0:
                paren_start = i
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                paren_end = i
                break

    if paren_start is None or paren_end is None:
        return {"error": "无法提取字段定义"}

    fields_str = ddl[paren_start + 1:paren_end]

    # 分割字段（处理嵌套括号 () 和尖括号 <> 内的逗号）
    columns = []
    depth = 0
    current = ""
    for char in fields_str:
        if char in "(<":
            depth += 1
            current += char
        elif char in ")>":
            depth -= 1
            current += char
        elif char == "," and depth == 0:
            columns.append(current.strip())
            current = ""
        else:
            current += char
    if current.strip():
        columns.append(current.strip())

    # 解析每个字段
    fields = []
    partition_fields = []
    seen_names = set()
    duplicate_names = []

    for col in columns:
        col_upper = col.upper().strip()

        # 跳过分区定义
        if col_upper.startswith("PARTITIONED BY"):
            # 提取分区字段
            part_match = re.search(r"PARTITIONED\s+BY\s+\((.+)\)", col, re.IGNORECASE)
            if part_match:
                for pf in part_match.group(1).split(","):
                    pf_name = _extract_partition_name(pf)
                    if pf_name:
                        partition_fields.append(pf_name)
                        _mark_partition(fields, pf_name)
            continue

        # 跳过表属性
        if any(
            col_upper.startswith(kw)
            for kw in ["PRIMARY KEY", "UNIQUE", "INDEX", "KEY", "CONSTRAINT"]
        ):
            continue

        # 解析字段：name type [COMMENT 'xxx']
        # 支持 Trino/Hive 类型：varchar, decimal(18,2), array<string>, map<string,string>, row(a int, b varchar)
        # 策略：先提取字段名（第一个标识符），剩余部分按 COMMENT 分割
        col_match = re.match(
            r'[\s"`]*([\w]+)[\s"`]*\s+(.+)',
            col,
            re.IGNORECASE | re.DOTALL,
        )
        if col_match:
            col_name = col_match.group(1)

            # 字段重名检测
            if col_name in seen_names:
                duplicate_names.append(col_name)
                continue
            seen_names.add(col_name)

            remainder = col_match.group(2).strip()

            # 从 remainder 中提取 COMMENT（如果存在）
            comment_match = re.search(
                r"\s+COMMENT\s+'([^']*)'\s*$",
                remainder,
                re.IGNORECASE,
            )
            if comment_match:
                col_type = remainder[:comment_match.start()].strip()
                col_comment = comment_match.group(1)
            else:
                col_type = remainder.strip()
                col_comment = ""

            # 清理类型中的多余空白
            col_type = re.sub(r"\s+", " ", col_type)

            fields.append(
                {"name": col_name, "type": col_type, "comment": col_comment}
            )

    # 检查 DDL 中的 PARTITIONED BY（表级别）
    part_clause = re.search(
        r"PARTITIONED\s+BY\s+\(([^)]+)\)", ddl, re.IGNORECASE
    )
    if part_clause and not partition_fields:
        for pf in part_clause.group(1).split(","):
            pf_name = _extract_partition_name(pf)
            if pf_name:
                partition_fields.append(pf_name)
                _mark_partition(fields, pf_name)

    # 分区字段兜底：表名后缀推断 (_D -> stat_date, _M -> stat_month)
    table_lower = table_name.lower()
    if not partition_fields:
        names_lower = {f["name"].lower(): f["name"] for f in fields}
        if table_lower.endswith("_d") and "stat_date" in names_lower:
            partition_fields.append(names_lower["stat_date"])
            _mark_partition(fields, names_lower["stat_date"])
        elif table_lower.endswith("_m") and "stat_month" in names_lower:
            partition_fields.append(names_lower["stat_month"])
            _mark_partition(fields, names_lower["stat_month"])

    # 账期字段与格式 — 优先取 stat_date/stat_month 字段，而非 partition_fields[0]
    # 因为 PARTITIONED BY 可能指定非日期分区（如 region），但账期仍应为 stat_date
    field_names_lower = {f["name"].lower(): f["name"] for f in fields}
    if table_lower.endswith("_d"):
        period_field = field_names_lower.get("stat_date", partition_fields[0] if partition_fields else "stat_date")
        period_format = "yyyyMMdd"
        period_label = "日账期"
    elif table_lower.endswith("_m"):
        period_field = field_names_lower.get("stat_month", partition_fields[0] if partition_fields else "stat_month")
        period_format = "yyyyMM"
        period_label = "月账期"
    else:
        period_field = partition_fields[0] if partition_fields else ""
        period_format = ""
        period_label = ""

    result = {
        "schema": schema_name,
        "table": table_name,
        "full_name": f"{schema_name}.{table_name}",
        "table_comment": table_comment,
        "fields": fields,
        "partition_fields": partition_fields,
        "period_field": period_field,
        "period_format": period_format,
        "period_label": period_label,
        "field_count": len(fields),
    }
    if duplicate_names:
        result["warnings"] = ["字段重名（已自动去重，仅保留首次出现）: %s" % ", ".join(duplicate_names)]
    return result


def format_as_markdown(parsed: dict) -> str:
    """将解析结果格式化为符合技能规范的 Markdown 片段，可直接追加到 tables.md。"""

    lines = []
    lines.append("## %s" % parsed["full_name"])
    lines.append("")

    if parsed.get("table_comment"):
        lines.append("> 表注释: %s" % parsed["table_comment"])
        lines.append("")

    lines.append("| 字段名 | 类型 | 注释 |")
    lines.append("|--------|------|------|")

    for f in parsed["fields"]:
        lines.append("| %s | %s | %s |" % (f["name"], f["type"], f["comment"]))

    lines.append("")

    # 分区字段（支持多分区，列出全部）
    # 格式统一：字段名 (type)，格式 xxx  — 中文逗号在括号外
    if parsed["partition_fields"]:
        pf_types = []
        for pf_name in parsed["partition_fields"]:
            pf_type = "string"
            for f in parsed["fields"]:
                if f["name"] == pf_name:
                    pf_type = f["type"]
                    break
            pf_types.append("%s (%s)" % (pf_name, pf_type))
        fmt_str = "，格式 %s" % parsed["period_format"] if parsed["period_format"] else ""
        lines.append("- 分区字段: %s%s" % (", ".join(pf_types), fmt_str))
    elif parsed["period_field"]:
        lines.append("- 分区字段: %s (string)，格式 %s" % (parsed["period_field"], parsed["period_format"]))
    else:
        lines.append("- 分区字段: 未识别（如该表有账期字段，请手动补充）")

    # 备注
    note = "共 %d 个字段" % parsed["field_count"]
    if parsed["period_field"] and parsed["period_label"]:
        note += "；%s %s 为分区账期，查询必须用分区字段过滤，禁止全表扫描" % (
            parsed["period_label"], parsed["period_field"])
    lines.append("- 备注: %s" % note)
    lines.append("")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 落盘相关（与 parse_json.py 对齐的能力）
# ---------------------------------------------------------------------------

def _check_table_exists(group_dir, full_name):
    """检查指定分组的 tables.md 中是否已存在同名表。"""
    tables_file = os.path.join(group_dir, "tables.md")
    if not os.path.exists(tables_file):
        return False
    with open(tables_file, "r", encoding="utf-8") as fh:
        content = fh.read()
    pattern = re.compile(r"^##\s+%s\s*$" % re.escape(full_name), re.MULTILINE)
    return bool(pattern.search(content))


def _remove_table_section(group_dir, full_name):
    """从分组 tables.md 中移除指定表的整个章节。"""
    tables_file = os.path.join(group_dir, "tables.md")
    if not os.path.exists(tables_file):
        return
    with open(tables_file, "r", encoding="utf-8") as fh:
        content = fh.read()
    pattern = re.compile(
        r"(## %s\b.*?)(?=\n## |\Z)" % re.escape(full_name),
        re.DOTALL,
    )
    content = pattern.sub("", content).rstrip("\n") + "\n"
    with open(tables_file, "w", encoding="utf-8") as fh:
        fh.write(content)


def _append_to_group(group, markdown, full_name, index_delta=1):
    """将 markdown 追加到指定分组的 tables.md，并更新 README.md 索引。

    返回: (tables_file_path, action) 其中 action 为 "created" 或 "appended"。
    index_delta: 表数量净增量。新增表为 1；--force 覆盖已存在表时为 0（先移除再追加，净不变）。
    """
    group_dir = os.path.join(_TABLES_DIR, group)
    tables_file = os.path.join(group_dir, "tables.md")

    if not os.path.exists(group_dir):
        os.makedirs(group_dir)
        header = "# %s基础表\n\n> %s业务域基础表结构定义。\n\n---\n\n" % (group, group)
        with open(tables_file, "w", encoding="utf-8") as fh:
            fh.write(header)
        action = "created"
    else:
        action = "appended"

    with open(tables_file, "r", encoding="utf-8") as fh:
        existing = fh.read()
    if not existing.endswith("\n"):
        existing += "\n"
    existing = re.sub(r"\n*> AI生成\s*\n*$", "\n", existing)
    with open(tables_file, "w", encoding="utf-8") as fh:
        fh.write(existing + markdown)

    # 更新索引：新建分组插入新行（数量恒为 1，首张表）；已有分组按净增量更新
    if action == "created":
        _update_index(group, 1, "created")
    else:
        _update_index(group, index_delta, "appended")
    return tables_file, action


def _collect_files(path):
    """如果 path 是目录，收集其下所有 .sql/.ddl/.txt 文件；否则返回 [path]。"""
    if os.path.isdir(path):
        files = []
        for name in sorted(os.listdir(path)):
            if name.lower().endswith((".sql", ".ddl", ".txt")):
                files.append(os.path.join(path, name))
        return files
    return [path]


def _update_index(group, delta, action):
    """更新 references/tables/README.md 的分组表数量。"""
    with open(_TABLES_INDEX, "r", encoding="utf-8") as fh:
        content = fh.read()

    group_row_pattern = re.compile(
        r"(\|\s*`%s/`\s*\|\s*[^\|]*\|\s*)(\d+)(\s*\|)" % re.escape(group)
    )

    if action == "created":
        new_row = "| `%s/` | %s业务域 | 1 |\n" % (group, group)
        content = content.replace(
            "| <!-- 在此行上方添加新分组 --> | | |",
            new_row + "| <!-- 在此行上方添加新分组 --> | | |",
        )
    else:
        def _bump(m):
            new_count = int(m.group(2)) + delta
            return "%s%d%s" % (m.group(1), new_count, m.group(3))
        content = group_row_pattern.sub(_bump, content)

    with open(_TABLES_INDEX, "w", encoding="utf-8") as fh:
        fh.write(content)


def main():
    parser = argparse.ArgumentParser(
        description="解析 DDL 语句",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("ddl", nargs="?", help="DDL 语句")
    parser.add_argument("--file", "-f", help="从文件读取 DDL，或指定目录批量导入")
    parser.add_argument("--format", choices=["json", "markdown"], default="json", help="输出格式")
    parser.add_argument("--group", help="指定分组名，配合 --append 直接落盘")
    parser.add_argument("--append", action="store_true",
                        help="直接追加到 --group 指定分组的 tables.md 并更新索引")
    parser.add_argument("--force", action="store_true",
                        help="当分组下已存在同名表时，覆盖旧内容（默认拒绝重名）")
    args = parser.parse_args()

    if args.append and not args.group:
        print("错误：--append 需要配合 --group 使用", file=sys.stderr)
        sys.exit(1)

    # 确定输入来源
    if args.file:
        files = _collect_files(args.file)
        if not files:
            print("错误：未找到任何 .sql/.ddl/.txt 文件: %s" % args.file, file=sys.stderr)
            sys.exit(1)
    elif args.ddl:
        files = None  # 命令行直接传入 DDL
    else:
        print("错误：请提供 DDL 语句或使用 --file 指定文件", file=sys.stderr)
        sys.exit(1)

    # 落盘模式
    if args.append:
        errors = []
        success = 0
        all_results = []

        if files:
            # 文件/目录模式
            for fpath in files:
                with open(fpath, "r", encoding="utf-8") as f:
                    ddl_text = f.read()
                ddl_statements = [s.strip() for s in ddl_text.split(";") if s.strip().upper().startswith("CREATE")]
                for stmt in ddl_statements:
                    parsed = parse_ddl(stmt)
                    all_results.append(parsed)
        else:
            # 命令行 DDL 模式
            ddl_statements = [s.strip() for s in args.ddl.split(";") if s.strip().upper().startswith("CREATE")]
            for stmt in ddl_statements:
                parsed = parse_ddl(stmt)
                all_results.append(parsed)

        for r in all_results:
            if "error" in r:
                errors.append(r["error"])
                continue
            full_name = r["full_name"]
            group_dir = os.path.join(_TABLES_DIR, args.group)
            is_overwrite = False
            if _check_table_exists(group_dir, full_name):
                if not args.force:
                    errors.append("表 %s 已存在于分组 %s，使用 --force 覆盖" % (full_name, args.group))
                    continue
                _remove_table_section(group_dir, full_name)
                is_overwrite = True
            markdown = format_as_markdown(r)
            _append_to_group(args.group, markdown, full_name, index_delta=0 if is_overwrite else 1)
            print("%s → 已追加到 %s/tables.md" % (full_name, args.group))
            if r.get("warnings"):
                print("  [警告: %s]" % "; ".join(r["warnings"]))
            success += 1

        if files and len(files) > 1:
            print("\n批量导入完成: 成功 %d 个，失败 %d 个" % (success, len(errors)))
        if errors:
            for e in errors:
                print("[失败] %s" % e, file=sys.stderr)
        sys.exit(0 if not errors else 1)

    # stdout 模式
    all_results = []
    if files:
        for fpath in files:
            with open(fpath, "r", encoding="utf-8") as f:
                ddl_text = f.read()
            ddl_statements = [s.strip() for s in ddl_text.split(";") if s.strip().upper().startswith("CREATE")]
            for stmt in ddl_statements:
                parsed = parse_ddl(stmt)
                all_results.append(parsed)
    else:
        ddl_statements = [s.strip() for s in args.ddl.split(";") if s.strip().upper().startswith("CREATE")]
        for stmt in ddl_statements:
            parsed = parse_ddl(stmt)
            all_results.append(parsed)

    if args.format == "markdown":
        for r in all_results:
            if "error" not in r:
                print(format_as_markdown(r))
    else:
        print(json.dumps(all_results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
