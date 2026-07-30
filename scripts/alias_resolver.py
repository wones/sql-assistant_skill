#!/usr/bin/env python3
"""
别名递归还原引擎：将含别名引用的SQL展开为完整可执行SQL。
从 aliases.md 文件读取别名定义，递归替换SQL中的别名为对应子查询。

基于 sqlparse 做 token 级解析，精确识别 FROM/JOIN 后的表名，
不会把 WHERE/GROUP BY 等关键字误认为表别名。

用法：
  python alias_resolver.py --aliases references/aliases/ --sql "SELECT * FROM user_base"
  python alias_resolver.py --aliases references/aliases/ --file query.sql
  python alias_resolver.py --aliases references/aliases/ --sql "..." --format markdown
"""

import argparse
import os
import re
import sys

import sqlparse
from sqlparse.sql import Identifier, IdentifierList, Parenthesis, Where


# ============================================================
# 第一部分：别名定义加载（与旧版兼容）
# ============================================================

def parse_aliases_md(filepath: str) -> dict:
    """从单个 aliases.md 文件解析所有别名定义，返回 {alias_name: sql_content} 字典。

    文件格式：
        ## alias_name
        - 描述: ...
        ```sql
        SELECT ...
        ```
    """
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
    except FileNotFoundError:
        return {}

    aliases = {}
    # 按 ## 标题分割
    sections = re.split(r"^## ", content, flags=re.MULTILINE)

    for section in sections[1:]:  # sections[0] 是标题前内容，跳过
        lines = section.strip().split("\n")
        alias_name = lines[0].strip()
        # 提取 ```sql ... ``` 代码块
        sql_match = re.search(r"```sql\s*\n(.*?)```", section, re.DOTALL)
        if sql_match:
            aliases[alias_name] = sql_match.group(1).strip()

    return aliases


def load_all_aliases(path: str) -> dict:
    """从目录递归加载所有别名。支持分组子文件夹结构：
    aliases/
    ├── README.md
    ├── {分组}/
    │   └── aliases.md
    """
    aliases = {}
    if not os.path.isdir(path):
        return parse_aliases_md(path)

    for fname in sorted(os.listdir(path)):
        fpath = os.path.join(path, fname)
        if os.path.isdir(fpath):
            # 分组子文件夹，查找其中的 aliases.md
            for sub_fname in os.listdir(fpath):
                if sub_fname == "aliases.md":
                    file_aliases = parse_aliases_md(os.path.join(fpath, sub_fname))
                    aliases.update(file_aliases)
        elif fname.endswith(".md") and fname != "README.md":
            # 兼容旧的平铺文件结构
            file_aliases = parse_aliases_md(fpath)
            aliases.update(file_aliases)

    return aliases


# ============================================================
# 第二部分：基于 sqlparse 的别名识别与替换
# ============================================================

# FROM/JOIN 类关键字，出现在这些关键字后的 Identifier 才是表引用
FROM_JOIN_KEYWORDS = {"FROM", "JOIN", "INNER JOIN", "LEFT JOIN", "RIGHT JOIN",
                      "OUTER JOIN", "LEFT OUTER JOIN", "RIGHT OUTER JOIN",
                      "FULL JOIN", "FULL OUTER JOIN", "CROSS JOIN"}

# 大小写不敏感的别名查找：构建 lower -> original 映射
def _build_case_insensitive_map(aliases: dict) -> dict:
    """构建大小写不敏感的别名字典 {lower_name: (original_name, sql)}"""
    return {k.lower(): (k, v) for k, v in aliases.items()}


def _find_alias_ref(name: str, ci_map: dict, visited: set) -> tuple:
    """查找 name 是否匹配某个别名（大小写不敏感 + _ 后缀兼容）。

    返回 (resolved_sql, actual_name) 或 None。
    """
    key = name.lower()

    # 精确匹配（大小写不敏感）
    if key in ci_map:
        original, sql = ci_map[key]
        if original not in visited:
            return (sql, original)

    # _ 后缀兼容：user_base_ 也匹配别名 user_base
    if key.endswith("_"):
        base_key = key[:-1]
        if base_key in ci_map:
            original, sql = ci_map[base_key]
            if original not in visited:
                return (sql, original)

    return None


def _extract_table_refs(token, ci_map: dict, visited: set) -> list:
    """从 sqlparse token 中提取表引用（表名 + 表别名）。

    处理 Identifier 和 IdentifierList 两种情况。
    跳过已经是子查询的引用（Parenthesis）。

    返回 [{"token": Identifier对象, "name": 表名, "alias": 表别名或None, "ref": 别名匹配结果}]
    """
    refs = []

    if isinstance(token, IdentifierList):
        # 多表逗号分隔：FROM a, b, c
        for idt in token.get_identifiers():
            ref = _extract_single_identifier(idt, ci_map, visited)
            if ref:
                refs.append(ref)
    elif isinstance(token, Identifier):
        # 单表：FROM a 或 FROM a alias
        ref = _extract_single_identifier(token, ci_map, visited)
        if ref:
            refs.append(ref)

    return refs


def _extract_single_identifier(idt, ci_map: dict, visited: set) -> dict:
    """处理单个 Identifier，判断是否为别名引用。

    跳过子查询（Parenthesis），只处理普通表名引用。
    """
    # 如果 Identifier 内部包含 Parenthesis，说明是子查询，跳过
    for sub in idt.tokens:
        if isinstance(sub, Parenthesis):
            return None

    # get_real_name() 返回表名，get_alias() 返回表别名或 None
    name = idt.get_real_name()
    alias = idt.get_alias()

    # 跳过带 schema 前缀的真实表（如 ods.users → real_name 返回 "users"，但 token 可见完整路径）
    # 如果 real_name 包含点号，说明是 schema.table，不是别名
    # 但 sqlparse 的 get_real_name() 只返回最后一段，需要另外判断
    # 实际做法：看 token 的 Name 部分，如果前面有 schema. 则跳过
    name_part = idt.token_first(skip_ws=True, skip_cm=True)
    if name_part is not None:
        # 检查是否为 schema.table 格式（type=Token.Name 但 value 含点号的情况需要看原始token）
        # sqlparse 对 schema.table 解析时 get_real_name 返回 table，需要看完整路径
        full_name = idt.value
        # 如果包含点号且点号前部分看起来像 schema（不含空格，全小写/下划线）
        if "." in full_name:
            # 去掉别名部分，检查是否有 schema 前缀
            # 例如 "ods.users" 或 "ods.users u" 或 "ods.users AS u"
            base_part = full_name
            if alias:
                # 去掉别名部分
                base_part = re.sub(r'\s+(AS\s+)?' + re.escape(alias) + r'\s*$', '', full_name, flags=re.IGNORECASE)
            # 如果去掉别名后包含点号，认为是 schema.table 引用
            if "." in base_part.strip():
                return None

    # 查找别名
    ref = _find_alias_ref(name, ci_map, visited)
    if ref is None:
        return None

    return {
        "token": idt,
        "name": name,
        "alias": alias,
        "resolved_sql": ref[0],
        "actual_name": ref[1],
    }


def resolve_aliases(sql: str, aliases: dict, visited: set = None, depth: int = 0) -> str:
    """递归展开SQL中的别名引用为子查询。

    Args:
        sql: 待还原的SQL语句
        aliases: {alias_name: sql_content} 字典
        visited: 已展开的别名集合，防止循环依赖
        depth: 当前递归深度，超过 MAX_DEPTH 时报错

    Returns:
        展开后的完整SQL
    """
    MAX_DEPTH = 10

    if visited is None:
        visited = set()

    if depth > MAX_DEPTH:
        raise RecursionError(
            f"别名递归深度超过 {MAX_DEPTH} 层，可能存在循环依赖。"
            f"已展开链: {' -> '.join(visited)}"
        )

    sql = sql.strip().rstrip(";").strip()

    ci_map = _build_case_insensitive_map(aliases)

    # 整条SQL就是一个别名
    direct_ref = _find_alias_ref(sql, ci_map, visited)
    if direct_ref:
        resolved_sql, actual_name = direct_ref
        new_visited = visited | {actual_name}
        return resolve_aliases(resolved_sql, aliases, new_visited, depth + 1)

    # 用 sqlparse 解析
    try:
        parsed = sqlparse.parse(sql)[0]
    except Exception:
        # 解析失败则原样返回
        return sql

    # 收集所有需要替换的表引用（FROM/JOIN 后的 Identifier）
    # 使用 (old_value_str, new_subquery_str) 二元组
    replacements = []

    # 递归处理子查询（Parenthesis 内部的 SQL），返回替换后的文本
    def _process_parenthesis(paren) -> str:
        """递归处理 Parenthesis 内部的 SQL，展开其中的别名引用。"""
        inner_sql = str(paren)
        # 去掉外层括号
        inner_sql = inner_sql.strip()
        if inner_sql.startswith("(") and inner_sql.endswith(")"):
            inner_sql = inner_sql[1:-1].strip()
        try:
            inner_resolved = resolve_aliases(inner_sql, aliases, visited, depth + 1)
        except RecursionError:
            inner_resolved = inner_sql
        if inner_resolved != inner_sql:
            return f"({inner_resolved})"
        return None  # 无变化时返回 None

    prev_keyword = None
    for token in parsed.tokens:
        if token.is_keyword:
            prev_keyword = token.value.upper().strip()
        elif isinstance(token, (Identifier, IdentifierList)):
            if prev_keyword and prev_keyword in FROM_JOIN_KEYWORDS:
                refs = _extract_table_refs(token, ci_map, visited)
                for ref in refs:
                    old_value = ref["token"].value
                    resolved_sql = ref["resolved_sql"]
                    actual_name = ref["actual_name"]
                    user_alias = ref["alias"]

                    # 递归展开别名 SQL 内部的别名引用
                    new_visited = visited | {actual_name}
                    try:
                        inner_resolved = resolve_aliases(
                            resolved_sql, aliases, new_visited, depth + 1
                        )
                    except RecursionError:
                        inner_resolved = resolved_sql

                    new_alias = user_alias or actual_name
                    new_value = f"({inner_resolved}) AS {new_alias}"

                    replacements.append((old_value, new_value))
            prev_keyword = None

    # 递归处理所有 Parenthesis 内部的别名引用
    for token in parsed.tokens:
        if isinstance(token, Parenthesis):
            new_paren = _process_parenthesis(token)
            if new_paren is not None:
                replacements.append((str(token), new_paren))
        elif isinstance(token, Identifier):
            # Identifier 内部可能包含 Parenthesis（子查询）
            for sub in token.tokens:
                if isinstance(sub, Parenthesis):
                    new_paren = _process_parenthesis(sub)
                    if new_paren is not None:
                        replacements.append((str(sub), new_paren))
        elif isinstance(token, Where):
            # WHERE 子句中可能包含子查询
            for sub in token.tokens:
                if isinstance(sub, Parenthesis):
                    new_paren = _process_parenthesis(sub)
                    if new_paren is not None:
                        replacements.append((str(sub), new_paren))

    # 倒序做字符串替换，避免位置错乱
    result = str(parsed)
    for old_value, new_value in reversed(replacements):
        result = result.replace(old_value, new_value, 1)

    return result


# ============================================================
# 第三部分：命令行入口
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="别名递归还原引擎：将含别名的SQL展开为完整可执行SQL",
    )
    parser.add_argument(
        "--aliases", required=True,
        help="aliases 目录路径（如 references/aliases/）或单独的 aliases.md 文件"
    )
    parser.add_argument("--sql", help="待还原的SQL语句")
    parser.add_argument("--file", "-f", help="从文件读取SQL")
    parser.add_argument(
        "--format", choices=["sql", "markdown"], default="sql",
        help="输出格式：sql（默认）或 markdown"
    )
    args = parser.parse_args()

    # 加载别名
    aliases = load_all_aliases(args.aliases)
    if not aliases:
        print("错误：未找到别名定义，请检查路径和文件内容", file=sys.stderr)
        print(f"  查找路径: {args.aliases}", file=sys.stderr)
        sys.exit(1)

    # 获取SQL
    if args.file:
        with open(args.file, "r", encoding="utf-8") as f:
            sql = f.read()
    elif args.sql:
        sql = args.sql
    else:
        print("错误：请提供 --sql 或 --file 参数", file=sys.stderr)
        sys.exit(1)

    # 执行还原
    try:
        resolved = resolve_aliases(sql, aliases)
    except RecursionError as e:
        print(f"错误：{e}", file=sys.stderr)
        sys.exit(2)

    # 输出
    if args.format == "markdown":
        print(f"## 还原结果\n\n```sql\n{resolved}\n```")
    else:
        print(resolved)


if __name__ == "__main__":
    main()
