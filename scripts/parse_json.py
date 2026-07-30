#!/usr/bin/env python3
"""
数据平台 JSON 解析工具：解析数据平台导出的表元数据 JSON，
自动提取表名、schema、字段列表、分区字段、维度关联、枚举值，
生成符合技能规范的 Markdown。

仅依赖 Python 标准库。

用法：
  # 仅输出 markdown 到 stdout（查看解析结果）
  python parse_json.py --file path/to/table.json

  # 输出结构化 JSON 到 stdout
  python parse_json.py --file table.json --format json

  # 直接落盘：追加到指定分组 tables.md 并更新索引
  python parse_json.py --file table.json --group user_domain --append

  # 覆盖已存在的同名表（默认拒绝重名）
  python parse_json.py --file table.json --group user_domain --append --force

  # 批量导入目录下所有 .json/.txt 文件
  python parse_json.py --file metadata/ --group user_domain --append

  # 覆盖自动推断的 schema
  python parse_json.py --file table.json --schema ods
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

# BOM 及零宽空格等不可见字符，数据平台导出文件开头可能含有
_INVISIBLE_CHARS = "\ufeff\u200b\u200c\u200d"


def _clean(s):
    """清洗字符串：转 None 为空，替换会破坏 markdown 表格的字符。"""
    if s is None:
        return ""
    return str(s).replace("|", "/").replace("\n", " ").strip()


def _truthy_partition(field):
    """判断字段是否为分区字段。partitionKey 可能为 "1"/True，空串/0/False 视为非分区。"""
    pk = field.get("partitionKey")
    if pk is None:
        return False
    s = str(pk).strip().lower()
    return s not in ("", "0", "false", "null", "none")


def _infer_schema(data, override=None):
    """推断 schema：优先物理库名，其次数据源去 hive_ 前缀，最后 default。"""
    if override:
        return override
    mds = data.get("metaDataSource") or {}
    phys = (mds.get("physicalDbName") or mds.get("devPhysicalDbName") or "").strip()
    if phys:
        return phys
    ds = (data.get("dsName") or "").strip()
    if ds.lower().startswith("hive_"):
        return ds[5:]
    if ds:
        return ds
    return "default"


def _mark_partition(fields, target_name):
    """将指定名称的字段标记为分区字段（在注释追加【分区字段】）。"""
    for f in fields:
        if f["name"] == target_name:
            f["is_partition"] = True
            if "【分区字段】" not in f["comment"]:
                f["comment"] = (f["comment"] + " 【分区字段】") if f["comment"] else "【分区字段】"
            return


def parse_table(data, schema_override=None):
    """解析数据平台 JSON，返回结构化信息。"""

    table_name = (data.get("name") or "").strip()
    if not table_name:
        return {"error": "JSON 中未找到表名(name 字段)"}

    schema = _infer_schema(data, schema_override)
    table_comment = data.get("label") or data.get("descr") or ""
    fields = data.get("fields") or []

    parsed_fields = []
    partition_names = []
    seen_names = set()
    duplicate_names = []

    for f in fields:
        name = (f.get("name") or "").strip()
        if not name:
            continue
        # 字段重名检测
        if name in seen_names:
            duplicate_names.append(name)
            continue
        seen_names.add(name)

        typ = (f.get("dataType") or "string").lower()
        base = f.get("label") or f.get("descr") or f.get("busiCaliber") or name

        parts = [_clean(base)]

        # 枚举值
        enum = (f.get("stdExtCode") or "").strip()
        if enum and enum.lower() not in ("none", "null"):
            parts.append("枚举: " + _clean(enum))

        # 维度关联
        dim_table = (f.get("dimTable") or "").strip()
        dim_field = (f.get("dimField") or "").strip()
        dim_field_name = (f.get("dimFieldName") or "").strip()
        dim_desc = (f.get("dimDesc") or "").strip()
        if dim_table:
            dim_str = "关联维度: %s.%s->%s" % (dim_table, dim_field, dim_field_name)
            if dim_desc:
                dim_str += "(" + _clean(dim_desc) + ")"
            parts.append(_clean(dim_str))

        comment = " | ".join(p for p in parts if p)

        is_primary = str(f.get("primaryKey") or "").strip() == "1"
        if is_primary:
            comment = (comment + " 【主键】") if comment else "【主键】"

        is_part = _truthy_partition(f)
        if is_part:
            comment = (comment + " 【分区字段】") if comment else "【分区字段】"
            partition_names.append(name)

        parsed_fields.append({
            "name": name,
            "type": typ,
            "comment": comment,
            "enum": enum,
            "is_partition": is_part,
            "is_primary": is_primary,
            "dim_table": dim_table,
        })

    # 分区字段兜底：表名后缀推断 (_D -> stat_date, _M -> stat_month)
    table_lower = table_name.lower()
    if not partition_names:
        names_lower = {pf["name"].lower(): pf["name"] for pf in parsed_fields}
        if table_lower.endswith("_d") and "stat_date" in names_lower:
            partition_names.append(names_lower["stat_date"])
            _mark_partition(parsed_fields, names_lower["stat_date"])
        elif table_lower.endswith("_m") and "stat_month" in names_lower:
            partition_names.append(names_lower["stat_month"])
            _mark_partition(parsed_fields, names_lower["stat_month"])

    # 账期字段与格式 — 优先取 stat_date/stat_month 字段，而非 partition_names[0]
    # 因为 PARTITIONED BY 可能指定非日期分区（如 region），但账期仍应为 stat_date
    field_names_lower = {pf["name"].lower(): pf["name"] for pf in parsed_fields}
    if table_lower.endswith("_d"):
        period_field = field_names_lower.get("stat_date", partition_names[0] if partition_names else "stat_date")
        period_format = "yyyyMMdd"
        period_label = "日账期"
    elif table_lower.endswith("_m"):
        period_field = field_names_lower.get("stat_month", partition_names[0] if partition_names else "stat_month")
        period_format = "yyyyMM"
        period_label = "月账期"
    else:
        period_field = partition_names[0] if partition_names else ""
        period_format = ""
        period_label = ""

    # 表元信息
    info = {
        "ds": data.get("dsName") or "",
        "lvl": data.get("lvl") or "",
        "topic": data.get("topicLabel") or data.get("topic") or "",
        "dens": data.get("tabDensLvl") or "",
    }

    enum_count = sum(1 for pf in parsed_fields if pf["enum"])
    dim_count = sum(1 for pf in parsed_fields if pf["dim_table"])

    result = {
        "schema": schema,
        "table": table_name,
        "full_name": "%s.%s" % (schema, table_name),
        "table_comment": table_comment,
        "fields": parsed_fields,
        "partition_fields": partition_names,
        "period_field": period_field,
        "period_format": period_format,
        "period_label": period_label,
        "info": info,
        "field_count": len(parsed_fields),
        "enum_count": enum_count,
        "dim_count": dim_count,
    }
    if duplicate_names:
        result["warnings"] = ["字段重名（已自动去重，仅保留首次出现）: %s" % ", ".join(duplicate_names)]
    return result


def format_as_markdown(parsed):
    """将解析结果格式化为符合技能规范的 Markdown 片段，可直接追加到 tables.md。"""

    lines = []
    lines.append("## %s" % parsed["full_name"])
    lines.append("")

    if parsed["table_comment"]:
        lines.append("> 表注释: %s" % _clean(parsed["table_comment"]))

    info = parsed["info"]
    meta_parts = []
    if info["ds"]:
        meta_parts.append("数据源: " + info["ds"])
    if info["lvl"]:
        meta_parts.append("数据层级: " + info["lvl"])
    if info["topic"]:
        meta_parts.append("主题域: " + info["topic"])
    if info["dens"]:
        meta_parts.append("表密度层级: " + info["dens"])
    if meta_parts:
        lines.append("> " + " | ".join(meta_parts))
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
    extras = []
    if parsed["enum_count"]:
        extras.append("含 %d 个枚举字段" % parsed["enum_count"])
    if parsed["dim_count"]:
        extras.append("含 %d 个维度关联字段" % parsed["dim_count"])
    if extras:
        note += "（" + "、".join(extras) + "）"
    if parsed["period_field"] and parsed["period_label"]:
        note += "；%s %s 为分区账期，查询必须用分区字段过滤，禁止全表扫描" % (
            parsed["period_label"], parsed["period_field"])
    lines.append("- 备注: %s" % note)
    lines.append("")
    lines.append("")

    return "\n".join(lines)


def _load_json_file(path):
    """读取并解析 JSON 文件，自动剥离 BOM/零宽字符，忽略尾随水印。"""
    with open(path, "r", encoding="utf-8") as fh:
        raw = fh.read()
    raw = raw.lstrip(_INVISIBLE_CHARS)
    try:
        data, _ = json.JSONDecoder().raw_decode(raw)
    except json.JSONDecodeError as e:
        return None, "JSON 解析失败: %s" % e
    return data, None


def _check_table_exists(group_dir, full_name):
    """检查指定分组的 tables.md 中是否已存在同名表。"""
    tables_file = os.path.join(group_dir, "tables.md")
    if not os.path.exists(tables_file):
        return False
    with open(tables_file, "r", encoding="utf-8") as fh:
        content = fh.read()
    header = "## %s" % full_name
    # 精确匹配行首 ## 后跟完整表名
    pattern = re.compile(r"^##\s+%s\s*$" % re.escape(full_name), re.MULTILINE)
    return bool(pattern.search(content))


def _append_to_group(group, markdown, full_name, index_delta=1):
    """将 markdown 追加到指定分组的 tables.md，并更新 README.md 索引。

    返回: (tables_file_path, action) 其中 action 为 "created" 或 "appended"。
    index_delta: 表数量净增量。新增表为 1；--force 覆盖已存在表时为 0（先移除再追加，净不变）。
    """
    group_dir = os.path.join(_TABLES_DIR, group)
    tables_file = os.path.join(group_dir, "tables.md")

    if not os.path.exists(group_dir):
        os.makedirs(group_dir)
        # 新建分组文件，写入标题头
        header = "# %s基础表\n\n> %s业务域基础表结构定义。\n\n---\n\n" % (group, group)
        with open(tables_file, "w", encoding="utf-8") as fh:
            fh.write(header)
        action = "created"
    else:
        action = "appended"

    # 通用：读取现有内容 → 去尾部水印 → 追加 markdown
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


def _update_index(group, delta, action):
    """更新 references/tables/README.md 的分组表数量。

    delta: +1 新增表 / -1 删除表
    action: "created"（新分组）/ "appended"（已有分组追加表）
    """
    with open(_TABLES_INDEX, "r", encoding="utf-8") as fh:
        content = fh.read()

    group_row_pattern = re.compile(
        r"(\|\s*`%s/`\s*\|\s*[^\|]*\|\s*)(\d+)(\s*\|)" % re.escape(group)
    )

    if action == "created":
        # 新分组：在注释行 <!-- 在此行上方添加新分组 --> 上方插入一行
        new_row = "| `%s/` | %s业务域 | 1 |\n" % (group, group)
        content = content.replace(
            "| <!-- 在此行上方添加新分组 --> | | |",
            new_row + "| <!-- 在此行上方添加新分组 --> | | |",
        )
    else:
        # 已有分组：表数量加 delta
        def _bump(m):
            new_count = int(m.group(2)) + delta
            return "%s%d%s" % (m.group(1), new_count, m.group(3))
        content = group_row_pattern.sub(_bump, content)

    with open(_TABLES_INDEX, "w", encoding="utf-8") as fh:
        fh.write(content)


# ---------------------------------------------------------------------------
# 批量导入
# ---------------------------------------------------------------------------

def _collect_files(path):
    """如果 path 是目录，收集其下所有 .json/.txt 文件；否则返回 [path]。"""
    if os.path.isdir(path):
        files = []
        for name in sorted(os.listdir(path)):
            if name.lower().endswith((".json", ".txt")):
                files.append(os.path.join(path, name))
        return files
    return [path]


def _process_one(path, schema_override, group, force, stdout_format):
    """处理单个文件：解析 → 输出到 stdout 或落盘。返回 (parsed, error_or_none)。"""
    data, err = _load_json_file(path)
    if err:
        return None, "%s: %s" % (os.path.basename(path), err)

    parsed = parse_table(data, schema_override=schema_override)
    if "error" in parsed:
        return None, "%s: %s" % (os.path.basename(path), parsed["error"])

    if group and group != "--":  # 落盘模式
        full_name = parsed["full_name"]
        group_dir = os.path.join(_TABLES_DIR, group)

        # 重名检测
        is_overwrite = False
        if _check_table_exists(group_dir, full_name):
            if not force:
                return None, "%s: 表 %s 已存在于分组 %s，使用 --force 覆盖" % (
                    os.path.basename(path), full_name, group)
            # force 模式：先移除旧章节再追加（净增量 0，索引数量不变）
            _remove_table_section(group_dir, full_name)
            is_overwrite = True

        markdown = format_as_markdown(parsed)
        _append_to_group(group, markdown, full_name, index_delta=0 if is_overwrite else 1)

        msg = "%s → 已追加到 %s/tables.md" % (full_name, group)
        if parsed.get("warnings"):
            msg += " [警告: %s]" % "; ".join(parsed["warnings"])
        print(msg)
        return parsed, None
    else:
        # 仅输出到 stdout
        if stdout_format == "json":
            print(json.dumps(parsed, ensure_ascii=False, indent=2))
        else:
            print(format_as_markdown(parsed))
        return parsed, None


def _remove_table_section(group_dir, full_name):
    """从分组 tables.md 中移除指定表的整个章节（## 标题到下一个 ## 或文件末尾）。"""
    tables_file = os.path.join(group_dir, "tables.md")
    if not os.path.exists(tables_file):
        return
    with open(tables_file, "r", encoding="utf-8") as fh:
        content = fh.read()
    # 匹配从 ## schema.table 到下一个 ## 或文件末尾
    pattern = re.compile(
        r"(## %s\b.*?)(?=\n## |\Z)" % re.escape(full_name),
        re.DOTALL,
    )
    content = pattern.sub("", content).rstrip("\n") + "\n"
    with open(tables_file, "w", encoding="utf-8") as fh:
        fh.write(content)


def main():
    ap = argparse.ArgumentParser(
        description="解析数据平台导出的表元数据 JSON",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--file", "-f", required=True,
                    help="数据平台导出的 JSON 文件路径，或含多个文件的目录（批量导入）")
    ap.add_argument("--format", choices=["json", "markdown"], default="markdown",
                    help="输出格式（仅 stdout 模式生效），默认 markdown")
    ap.add_argument("--schema", help="覆盖自动推断的 schema 名")
    ap.add_argument("--group", help="指定分组名，配合 --append 直接落盘到对应 tables.md")
    ap.add_argument("--append", action="store_true",
                    help="直接追加到 --group 指定分组的 tables.md 并更新索引")
    ap.add_argument("--force", action="store_true",
                    help="当分组下已存在同名表时，覆盖旧内容（默认拒绝重名）")
    args = ap.parse_args()

    # 落盘模式要求 --group
    if args.append and not args.group:
        print("错误：--append 需要配合 --group 使用", file=sys.stderr)
        sys.exit(1)

    files = _collect_files(args.file)
    if not files:
        print("错误：未找到任何 .json/.txt 文件: %s" % args.file, file=sys.stderr)
        sys.exit(1)

    success = 0
    errors = []
    for path in files:
        group = args.group if args.append else None
        _, err = _process_one(path, args.schema, group, args.force, args.format)
        if err:
            errors.append(err)
            print("[失败] %s" % err, file=sys.stderr)
        else:
            success += 1

    if len(files) > 1:
        print("\n批量导入完成: 成功 %d 个，失败 %d 个" % (success, len(errors)))

    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
