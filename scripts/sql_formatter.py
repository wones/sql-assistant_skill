#!/usr/bin/env python3
"""
SQL 格式化器：将SQL格式化为不同风格。

基于 sqlparse 实现，保证关键字不会被错误拆分。

用法：
  python sql_formatter.py "SELECT id,name FROM users WHERE id>10"
  python sql_formatter.py "SELECT id FROM users" --style compact
  python sql_formatter.py --file query.sql --style expanded

风格：
  standard  — 标准缩进，关键字大写（默认）
  compact   — 单行紧凑
  expanded  — 每个关键字独占一行，SELECT 列逗号前置
"""

import argparse
import re
import sys

import sqlparse


def format_standard(sql: str) -> str:
    """标准格式化：关键字大写 + 合理缩进。"""
    formatted = sqlparse.format(
        sql,
        reindent=True,          # 智能缩进
        keyword_case="upper",   # 关键字大写
        identifier_case="lower", # 标识符小写（不强制，sqlparse 保留原样）
        strip_comments=False,    # 保留注释
        comma_first=True,       # 逗号前置（符合 Trino 规范）
    )
    return formatted.strip()


def format_compact(sql: str) -> str:
    """紧凑格式化：单行，关键字大写。"""
    formatted = sqlparse.format(
        sql,
        strip_whitespace=True,  # 移除多余空白
        keyword_case="upper",   # 关键字大写
        strip_comments=True,    # 移除注释
    )
    return formatted.strip()


def format_expanded(sql: str) -> str:
    """展开格式化：每个关键字独占一行，SELECT 列逗号前置。"""
    # 先用 sqlparse 做基础格式化
    formatted = sqlparse.format(
        sql,
        reindent=True,
        keyword_case="upper",
        comma_first=True,
        strip_comments=False,
    )

    # 进一步展开：确保每个主要关键字独占一行
    lines = formatted.split("\n")
    result_lines = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        # 检查是否多个关键字挤在同一行（非首行）
        # 例如 "FROM users WHERE" 拆成 "FROM users" 和 "WHERE"
        keywords = ["WHERE", "GROUP BY", "HAVING", "ORDER BY", "LIMIT", "OFFSET",
                     "LEFT JOIN", "RIGHT JOIN", "INNER JOIN", "CROSS JOIN", "JOIN",
                     "UNION", "UNION ALL", "ON"]

        # 确定当前行的缩进
        indent = len(line) - len(line.lstrip())

        parts = [stripped]
        changed = True
        while changed:
            changed = False
            new_parts = []
            for part in parts:
                # 检查这个部分是否需要进一步拆分
                # 只在行首不是关键字的情况下，查找行中的关键字
                first_word = part.split()[0].upper() if part.split() else ""
                if first_word in keywords or first_word in ("SELECT", "FROM", "WITH"):
                    # 这个部分已经以关键字开头，不再拆分
                    new_parts.append(part)
                else:
                    # 查找行中的关键字位置
                    split_pos = None
                    for kw in sorted(keywords, key=len, reverse=True):
                        # 查找关键字（前面有空格）
                        kw_pattern = r"\s+" + kw + r"\b"
                        m = re.search(kw_pattern, part, re.IGNORECASE)
                        if m:
                            split_pos = m.start()
                            split_kw = kw
                            break
                    if split_pos is not None:
                        before = part[:split_pos].strip()
                        after = part[split_pos:].strip()
                        if before:
                            new_parts.append(before)
                        new_parts.append(after)
                        changed = True
                    else:
                        new_parts.append(part)
            parts = new_parts

        for part in parts:
            result_lines.append(" " * indent + part)

    return "\n".join(result_lines)


def main():
    parser = argparse.ArgumentParser(description="SQL 格式化器")
    parser.add_argument("sql", nargs="?", help="SQL语句")
    parser.add_argument("--file", "-f", help="从文件读取SQL")
    parser.add_argument(
        "--style", choices=["standard", "compact", "expanded"],
        default="standard", help="格式化风格"
    )
    args = parser.parse_args()

    sql = ""
    if args.file:
        with open(args.file, "r", encoding="utf-8") as f:
            sql = f.read()
    elif args.sql:
        sql = args.sql
    else:
        print("请提供SQL语句或使用 --file", file=sys.stderr)
        sys.exit(1)

    formatters = {
        "standard": format_standard,
        "compact": format_compact,
        "expanded": format_expanded,
    }

    print(formatters[args.style](sql))


if __name__ == "__main__":
    main()
