#!/usr/bin/env python3
"""
SQL 方言转换器：在 MySQL / Trino / Doris 之间转换SQL。

用法：
  python sql_converter.py "SELECT IFNULL(a, 0) FROM t LIMIT 10, 20" --from mysql --to trino
  python sql_converter.py --file query.sql --from trino --to mysql
"""

import argparse
import re
import sys

# ===== 方言映射规则 =====

DIALECT_MAP = {
    ("mysql", "trino"): {
        "IFNULL": "COALESCE",
        "SUBSTRING": "SUBSTR",
        "NOW()": "CURRENT_TIMESTAMP",
        "CURDATE()": "CURRENT_DATE",
        "CURTIME()": "CURRENT_TIME",
        "DATEDIFF": "DATE_DIFF",
        "TIMESTAMPDIFF": "TIMESTAMP_DIFF",
    },
    ("mysql", "doris"): {
        "IFNULL": "IFNULL",
        "SUBSTRING": "SUBSTR",
        "NOW()": "NOW()",
        "CURDATE()": "CURDATE()",
        "CURTIME()": "CURTIME()",
        "DATEDIFF": "DATEDIFF",
        "TIMESTAMPDIFF": "TIMESTAMPDIFF",
    },
    ("trino", "mysql"): {
        "COALESCE": "IFNULL",
        "SUBSTR": "SUBSTRING",
        "CURRENT_TIMESTAMP": "NOW()",
        "CURRENT_DATE": "CURDATE()",
        "CURRENT_TIME": "CURTIME()",
        "DATE_DIFF": "DATEDIFF",
        "TIMESTAMP_DIFF": "TIMESTAMPDIFF",
        "APPROX_DISTINCT": "APPROX_COUNT_DISTINCT",
    },
    ("trino", "doris"): {
        "COALESCE": "COALESCE",
        "SUBSTR": "SUBSTR",
        "CURRENT_TIMESTAMP": "NOW()",
        "CURRENT_DATE": "CURDATE()",
        "CURRENT_TIME": "CURTIME()",
        "DATE_DIFF": "DATEDIFF",
        "APPROX_DISTINCT": "APPROX_COUNT_DISTINCT",
    },
    ("doris", "mysql"): {
        "IFNULL": "IFNULL",
        "SUBSTR": "SUBSTRING",
        "NOW()": "NOW()",
        "CURDATE()": "CURDATE()",
        "CURTIME()": "CURTIME()",
    },
    ("doris", "trino"): {
        "IFNULL": "COALESCE",
        "SUBSTR": "SUBSTR",
        "NOW()": "CURRENT_TIMESTAMP",
        "CURDATE()": "CURRENT_DATE",
        "CURTIME()": "CURRENT_TIME",
        "DATEDIFF": "DATE_DIFF",
        "APPROX_COUNT_DISTINCT": "APPROX_DISTINCT",
    },
}

# MySQL 日期提取函数 → Trino EXTRACT 语法
# 这类函数需要把 FUNC(expr) 整体转换为 EXTRACT(PART FROM expr)
MYSQL_EXTRACT_FUNCTIONS = {
    "YEAR": "YEAR",
    "MONTH": "MONTH",
    "DAY": "DAY",
    "HOUR": "HOUR",
    "MINUTE": "MINUTE",
    "SECOND": "SECOND",
}

# Trino → MySQL：EXTRACT(YEAR FROM expr) → YEAR(expr)
TRINO_EXTRACT_PATTERN = re.compile(
    r"EXTRACT\s*\(\s*(\w+)\s+FROM\s+(.+?)\s*\)",
    re.IGNORECASE,
)

SUPPORTED_DIALECTS = ["mysql", "trino", "doris"]


class SQLConverter:
    def convert(self, sql: str, from_dialect: str, to_dialect: str) -> str:
        from_dialect = from_dialect.lower()
        to_dialect = to_dialect.lower()

        if from_dialect == to_dialect:
            return sql

        if from_dialect not in SUPPORTED_DIALECTS or to_dialect not in SUPPORTED_DIALECTS:
            raise ValueError(f"不支持的方言。支持: {SUPPORTED_DIALECTS}")

        key = (from_dialect, to_dialect)
        if key not in DIALECT_MAP:
            raise ValueError(f"暂不支持 {from_dialect} → {to_dialect} 转换")

        result = sql

        # 分页语法转换
        result = self._convert_limit(result, from_dialect, to_dialect)

        # 日期提取函数转换（MySQL ↔ Trino）
        result = self._convert_extract_functions(result, from_dialect, to_dialect)

        # 函数名转换
        rules = DIALECT_MAP[key]
        for pattern, replacement in rules.items():
            if pattern.endswith("()"):
                # 带括号的函数，精确匹配
                result = re.sub(re.escape(pattern), replacement, result, flags=re.IGNORECASE)
            else:
                result = re.sub(r"\b" + pattern + r"\b", replacement, result, flags=re.IGNORECASE)

        return result

    def _convert_extract_functions(self, sql: str, from_d: str, to_d: str) -> str:
        """转换日期提取函数：MySQL YEAR(dt) ↔ Trino EXTRACT(YEAR FROM dt)"""

        # MySQL/Doris → Trino: YEAR(expr) → EXTRACT(YEAR FROM expr)
        if to_d == "trino" and from_d in ("mysql", "doris"):
            for func_name, extract_part in MYSQL_EXTRACT_FUNCTIONS.items():
                # 匹配 FUNC_NAME(内容)，需要处理嵌套括号
                pattern = re.compile(
                    r"\b" + func_name + r"\s*\(",
                    re.IGNORECASE,
                )
                result = sql
                while True:
                    m = pattern.search(result)
                    if not m:
                        break
                    # 从括号开始位置找匹配的右括号
                    paren_start = m.end() - 1  # 指向 "("
                    depth = 0
                    paren_end = None
                    for i in range(paren_start, len(result)):
                        if result[i] == "(":
                            depth += 1
                        elif result[i] == ")":
                            depth -= 1
                            if depth == 0:
                                paren_end = i
                                break
                    if paren_end is None:
                        break
                    inner_expr = result[paren_start + 1:paren_end].strip()
                    replacement = f"EXTRACT({extract_part} FROM {inner_expr})"
                    result = result[:m.start()] + replacement + result[paren_end + 1:]
                sql = result

        # Trino → MySQL/Doris: EXTRACT(YEAR FROM expr) → YEAR(expr)
        if from_d == "trino" and to_d in ("mysql", "doris"):
            def extract_to_func(m):
                part = m.group(1).upper()
                expr = m.group(2).strip()
                if part in MYSQL_EXTRACT_FUNCTIONS:
                    return f"{part}({expr})"
                return m.group(0)  # 未知部分，保持原样
            sql = TRINO_EXTRACT_PATTERN.sub(extract_to_func, sql)

        return sql

    def _convert_limit(self, sql: str, from_d: str, to_d: str) -> str:
        # MySQL LIMIT offset,rows → Trino OFFSET rows LIMIT count
        if from_d == "mysql" and to_d == "trino":
            m = re.search(r"LIMIT\s+(\d+)\s*,\s*(\d+)", sql, re.IGNORECASE)
            if m:
                offset, rows = m.group(1), m.group(2)
                sql = re.sub(r"LIMIT\s+\d+\s*,\s*\d+", f"OFFSET {offset} LIMIT {rows}", sql, flags=re.IGNORECASE)

        # Trino OFFSET rows LIMIT count → MySQL LIMIT offset,rows
        if from_d == "trino" and to_d in ("mysql", "doris"):
            m = re.search(r"OFFSET\s+(\d+)\s+LIMIT\s+(\d+)", sql, re.IGNORECASE)
            if m:
                offset, rows = m.group(1), m.group(2)
                sql = re.sub(r"OFFSET\s+\d+\s+LIMIT\s+\d+", f"LIMIT {offset}, {rows}", sql, flags=re.IGNORECASE)

        # Doris LIMIT offset,rows (same as MySQL) → Trino
        if from_d == "doris" and to_d == "trino":
            m = re.search(r"LIMIT\s+(\d+)\s*,\s*(\d+)", sql, re.IGNORECASE)
            if m:
                offset, rows = m.group(1), m.group(2)
                sql = re.sub(r"LIMIT\s+\d+\s*,\s*\d+", f"OFFSET {offset} LIMIT {rows}", sql, flags=re.IGNORECASE)

        return sql


def main():
    parser = argparse.ArgumentParser(description="SQL 方言转换器")
    parser.add_argument("sql", nargs="?", help="SQL语句")
    parser.add_argument("--file", "-f", help="从文件读取SQL")
    parser.add_argument("--from", dest="from_dialect", required=True, choices=SUPPORTED_DIALECTS, help="源方言")
    parser.add_argument("--to", dest="to_dialect", required=True, choices=SUPPORTED_DIALECTS, help="目标方言")
    parser.add_argument("--list", action="store_true", help="列出所有支持的方言")
    args = parser.parse_args()

    if args.list:
        print(f"支持方言: {', '.join(SUPPORTED_DIALECTS)}")
        for key in DIALECT_MAP:
            print(f"  {key[0]} → {key[1]}")
        return

    sql = ""
    if args.file:
        with open(args.file, "r", encoding="utf-8") as f:
            sql = f.read()
    elif args.sql:
        sql = args.sql
    else:
        print("请提供SQL语句或使用 --file", file=sys.stderr)
        sys.exit(1)

    converter = SQLConverter()
    result = converter.convert(sql, args.from_dialect, args.to_dialect)
    print(result)


if __name__ == "__main__":
    main()
