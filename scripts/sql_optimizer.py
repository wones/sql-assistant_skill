#!/usr/bin/env python3
"""
SQL 优化引擎：基于规则对SQL进行自动优化和分析。

基于 sqlparse 做 token 级解析，精确识别 SELECT 列表、子查询结构。

优化能力：
  - 移除注释、冗余条件（WHERE 1=1）
  - 去重列、大写关键字
  - 内联简单子查询
  - 子查询转 JOIN（4种模式）
  - IN 子查询→EXISTS
  - 移除冗余派生表
  - 输出优化分析报告（涉及的表/列/JOIN/子查询/警告/建议）

用法：
  python sql_optimizer.py "SELECT * FROM (SELECT id FROM users) AS t"
  python sql_optimizer.py --file query.sql --analyze
"""

import argparse
import re
import sys

import sqlparse
from sqlparse.sql import Identifier, IdentifierList, Parenthesis, Where


class SQLOptimizer:
    def optimize(self, sql: str) -> str:
        optimized = sql.strip().rstrip(";").strip()

        # 正则规则（移除注释、WHERE 1=1 等）
        regex_rules = [
            ("remove_comments", r"--.*$|/\*.*?\*/", ""),
            ("simplify_where_true", r"WHERE\s+1\s*=\s*1\s*(AND\s+)?", "WHERE "),
            ("simplify_where_false", r"WHERE\s+1\s*=\s*0", "WHERE 1=0"),
        ]
        for name, pattern, repl in regex_rules:
            optimized = re.sub(pattern, repl, optimized, flags=re.IGNORECASE | re.MULTILINE | re.DOTALL)

        # 结构化优化（基于 sqlparse）
        optimized = self._remove_duplicate_columns(optimized)
        optimized = self._inline_simple_subqueries(optimized)
        optimized = self._remove_redundant_subqueries(optimized)
        optimized = self._convert_subquery_to_join(optimized)
        optimized = self._simplify_subqueries(optimized)
        optimized = self._remove_redundant_derived_tables(optimized)

        # 清理空白
        optimized = re.sub(r"\s+", " ", optimized).strip()
        optimized = re.sub(r"\s*,\s*", ", ", optimized)
        optimized = re.sub(r"\s*=\s*", " = ", optimized)
        optimized = self._uppercase_keywords(optimized)

        return optimized

    def _uppercase_keywords(self, sql: str) -> str:
        """大写 SQL 关键字。"""
        keywords = [
            "SELECT", "FROM", "WHERE", "AND", "OR", "JOIN", "ON",
            "ORDER BY", "GROUP BY", "HAVING", "LIMIT", "OFFSET",
            "LEFT JOIN", "RIGHT JOIN", "INNER JOIN", "CROSS JOIN",
            "FULL JOIN", "FULL OUTER JOIN", "LEFT OUTER JOIN", "RIGHT OUTER JOIN",
            "UNION", "UNION ALL", "AS", "IN", "EXISTS", "NOT",
            "IS", "NULL", "BETWEEN", "LIKE", "CASE", "WHEN", "THEN", "ELSE", "END",
            "DISTINCT", "BY", "ASC", "DESC",
        ]
        for kw in sorted(keywords, key=len, reverse=True):
            sql = re.sub(r"\b" + kw + r"\b", kw, sql, flags=re.IGNORECASE)
        return sql

    # ===== 基于 sqlparse 的结构化优化 =====

    def _get_select_columns(self, sql: str) -> tuple:
        """用 sqlparse 提取 SELECT 列列表，返回 (columns_str, start, end) 或 None。"""
        parsed = sqlparse.parse(sql)[0]
        # 找 SELECT 和 FROM 的位置
        select_idx = None
        from_idx = None
        for i, token in enumerate(parsed.tokens):
            if token.is_keyword and token.value.upper() == "SELECT":
                select_idx = i
            elif token.is_keyword and token.value.upper() == "FROM" and select_idx is not None:
                from_idx = i
                break
        if select_idx is None or from_idx is None:
            return None

        # 提取 SELECT 和 FROM 之间的 token
        cols_tokens = parsed.tokens[select_idx + 1:from_idx]
        cols_str = "".join(str(t) for t in cols_tokens).strip()
        # 计算在原始 SQL 中的位置
        full_str = str(parsed)
        # 找 SELECT 后面到 FROM 前面的文本
        sel_match = re.search(r"\bSELECT\b", full_str, re.IGNORECASE)
        from_match = re.search(r"\bFROM\b", full_str, re.IGNORECASE)
        if sel_match and from_match and from_match.start() > sel_match.end():
            return (full_str[sel_match.end():from_match.start()].strip(),
                    sel_match.end(), from_match.start())
        return None

    def _remove_duplicate_columns(self, sql: str) -> str:
        """去重 SELECT 列。"""
        info = self._get_select_columns(sql)
        if not info:
            return sql
        cols_str, start, end = info
        columns = [c.strip() for c in cols_str.split(",")]
        seen = set()
        unique = []
        for c in columns:
            if c and c.lower() not in seen:
                seen.add(c.lower())
                unique.append(c)
        if len(unique) < len(columns):
            new_sql = sql[:start] + " " + ", ".join(unique) + " " + sql[end:]
            return new_sql
        return sql

    def _inline_simple_subqueries(self, sql: str) -> str:
        """内联简单子查询：SELECT ... FROM (SELECT cols FROM table) AS alias → SELECT alias.cols FROM table alias"""
        # 用 sqlparse 检测 FROM 后是否为简单子查询
        for _ in range(5):
            parsed = sqlparse.parse(sql)[0]
            changed = False
            for i, token in enumerate(parsed.tokens):
                if isinstance(token, Identifier) and i > 0:
                    # 检查前一个非空白 token 是否为 FROM
                    prev_kw = None
                    for j in range(i - 1, -1, -1):
                        t = parsed.tokens[j]
                        if t.is_whitespace:
                            continue
                        prev_kw = t
                        break
                    if prev_kw and prev_kw.is_keyword and prev_kw.value.upper() == "FROM":
                        # 检查 Identifier 是否为子查询
                        paren = None
                        for sub in token.tokens:
                            if isinstance(sub, Parenthesis):
                                paren = sub
                                break
                        if paren is None:
                            continue
                        # 解析子查询内容
                        inner_sql = str(paren).strip()
                        if inner_sql.startswith("(") and inner_sql.endswith(")"):
                            inner_sql = inner_sql[1:-1].strip()
                        inner_parsed = sqlparse.parse(inner_sql)[0]
                        # 检查内层是否为简单 SELECT ... FROM table（无 WHERE/JOIN/GROUP BY）
                        inner_has_where = any(t.is_keyword and t.value.upper() == "WHERE" for t in inner_parsed.tokens)
                        inner_has_join = any(t.is_keyword and "JOIN" in t.value.upper() for t in inner_parsed.tokens)
                        inner_has_group = any(t.is_keyword and "GROUP" in t.value.upper() for t in inner_parsed.tokens)
                        if inner_has_where or inner_has_join or inner_has_group:
                            continue
                        # 提取内层列和表
                        inner_cols = None
                        inner_table = None
                        for j, t in enumerate(inner_parsed.tokens):
                            if t.is_keyword and t.value.upper() == "SELECT":
                                # 找下一个 FROM
                                for k in range(j + 1, len(inner_parsed.tokens)):
                                    tk = inner_parsed.tokens[k]
                                    if tk.is_keyword and tk.value.upper() == "FROM":
                                        inner_cols = str(inner_parsed.tokens[j+1]).strip()
                                        # 列可能在 j+1 到 k 之间
                                        inner_cols = "".join(str(inner_parsed.tokens[x]) for x in range(j+1, k)).strip()
                                        # 表名在 k+1
                                        for m in range(k + 1, len(inner_parsed.tokens)):
                                            tm = inner_parsed.tokens[m]
                                            if not tm.is_whitespace:
                                                inner_table = str(tm).strip()
                                                break
                                        break
                                break
                        if inner_cols is None or inner_table is None:
                            continue
                        # 外层别名
                        outer_alias = token.get_alias() or token.get_real_name()
                        # 构造新 SQL
                        old_value = str(token)
                        if inner_cols.strip() == "*":
                            new_value = f"{inner_table} {outer_alias}"
                        else:
                            # 检查外层 SELECT 是否为 *
                            result = self._get_select_columns(sql)
                            if result and result[0].strip() == "*":
                                # 将内层列加前缀
                                cols = [c.strip() for c in inner_cols.split(",")]
                                qualified = [f"{outer_alias}.{c}" if "." not in c else c for c in cols]
                                new_value = f"{inner_table} {outer_alias}"
                                # 同时替换外层 SELECT *
                                sql = sql.replace("SELECT *", f"SELECT {', '.join(qualified)}", 1)
                            else:
                                new_value = f"{inner_table} {outer_alias}"
                        sql = sql.replace(old_value, new_value, 1)
                        changed = True
                        break
            if not changed:
                break
        return sql

    def _remove_redundant_subqueries(self, sql: str) -> str:
        """移除冗余子查询：SELECT * FROM (SELECT * FROM table) AS alias → SELECT * FROM table alias"""
        for _ in range(5):
            pattern = r"FROM\s*\(\s*SELECT\s+\*\s+FROM\s+(\w+(?:\.\w+)?)\s*(?:AS\s+)?(\w+)?\s*\)\s*(?:AS\s+)?(\w+)"
            m = re.search(pattern, sql, re.IGNORECASE | re.DOTALL)
            if not m:
                break
            table = m.group(1)
            inner_alias = m.group(2)
            outer_alias = m.group(3)
            final_alias = outer_alias or inner_alias or table.split(".")[-1]
            replacement = f"FROM {table} {final_alias}"
            sql = sql[:m.start()] + replacement + sql[m.end():]
        return sql

    def _convert_subquery_to_join(self, sql: str) -> str:
        """子查询转 JOIN：
        模式1: WHERE col IN (SELECT col FROM table) → INNER JOIN
        模式2: WHERE col NOT IN (...) → LEFT JOIN + WHERE IS NULL
        """
        # 模式1: WHERE col IN (SELECT col FROM table)
        pattern1 = (
            r"WHERE\s+(\w+)\.(\w+)\s+IN\s*\(\s*SELECT\s+(\w+)\s+FROM\s+(\w+(?:\.\w+)?)\s*\)"
        )
        m1 = re.search(pattern1, sql, re.IGNORECASE)
        if m1:
            table_alias = m1.group(1)
            col = m1.group(2)
            sub_col = m1.group(3)
            sub_table = m1.group(4)
            # 构造 JOIN
            old = m1.group(0)
            new = f"INNER JOIN {sub_table} ON {table_alias}.{col} = {sub_table}.{sub_col}"
            sql = sql.replace(old, new, 1)

        # 模式2: WHERE col NOT IN (SELECT col FROM table)
        pattern2 = (
            r"WHERE\s+(\w+)\.(\w+)\s+NOT\s+IN\s*\(\s*SELECT\s+(\w+)\s+FROM\s+(\w+(?:\.\w+)?)\s*\)"
        )
        m2 = re.search(pattern2, sql, re.IGNORECASE)
        if m2:
            table_alias = m2.group(1)
            col = m2.group(2)
            sub_col = m2.group(3)
            sub_table = m2.group(4)
            old = m2.group(0)
            new = (
                f"LEFT JOIN {sub_table} ON {table_alias}.{col} = {sub_table}.{sub_col} "
                f"WHERE {sub_table}.{sub_col} IS NULL"
            )
            sql = sql.replace(old, new, 1)

        return sql

    def _simplify_subqueries(self, sql: str) -> str:
        """IN → EXISTS 转换 + DISTINCT 简化。"""
        # DISTINCT in IN → 简化
        sql = re.sub(
            r"IN\s*\(\s*SELECT\s+DISTINCT\s+(\w+)\s+FROM\s+(\w+)\s*\)",
            r"IN (SELECT \1 FROM \2)",
            sql, flags=re.IGNORECASE,
        )
        # IN → EXISTS: WHERE col IN (SELECT col2 FROM table [alias] WHERE condition)
        sql = re.sub(
            r"(\w+)\.(\w+)\s+IN\s*\(\s*SELECT\s+(\w+)\s+FROM\s+(\w+(?:\.\w+)?)(?:\s+(?:AS\s+)?(\w+))?\s+WHERE\s+(.+?)\s*\)",
            lambda m: (
                f"EXISTS (SELECT 1 FROM {m.group(4)} "
                f"{m.group(5) + ' ' if m.group(5) else ''}"
                f"WHERE {m.group(6)} AND {m.group(1)}.{m.group(2)} = {m.group(3)})"
            ),
            sql, flags=re.IGNORECASE | re.DOTALL,
        )
        return sql

    def _remove_redundant_derived_tables(self, sql: str) -> str:
        """移除冗余派生表：SELECT a.* FROM (SELECT * FROM table) AS a → SELECT a.* FROM table a"""
        for _ in range(5):
            pattern = r"FROM\s*\(\s*SELECT\s+\*\s+FROM\s+(\w+(?:\.\w+)?)\s*\)\s*(?:AS\s+)?(\w+)"
            m = re.search(pattern, sql, re.IGNORECASE | re.DOTALL)
            if not m:
                break
            table = m.group(1)
            alias = m.group(2)
            replacement = f"FROM {table} {alias}"
            sql = sql[:m.start()] + replacement + sql[m.end():]
        return sql

    # ===== 分析报告 =====

    def analyze(self, sql: str) -> dict:
        """分析SQL结构，返回分析报告。"""
        analysis = {
            "tables": [],
            "columns": [],
            "joins": [],
            "subqueries": [],
            "warnings": [],
            "suggestions": [],
        }

        # 用 sqlparse 提取表名
        parsed = sqlparse.parse(sql)[0]
        prev_kw = None
        for token in parsed.tokens:
            if token.is_keyword and token.value.upper() in (
                "FROM", "JOIN", "INNER JOIN", "LEFT JOIN", "RIGHT JOIN",
                "OUTER JOIN", "CROSS JOIN", "FULL JOIN", "FULL OUTER JOIN",
                "LEFT OUTER JOIN", "RIGHT OUTER JOIN"
            ):
                prev_kw = token.value.upper()
            elif isinstance(token, Identifier) and prev_kw:
                name = token.get_real_name()
                # 获取完整的 schema.table
                first = token.token_first(skip_ws=True, skip_cm=True)
                if first and str(first).endswith(f".{name}"):
                    name = str(first)
                if name and name.upper() not in ("SELECT", "WHERE", "GROUP", "ORDER", "HAVING"):
                    if name not in analysis["tables"]:
                        analysis["tables"].append(name)
                prev_kw = None
            elif isinstance(token, IdentifierList) and prev_kw and prev_kw == "FROM":
                for idt in token.get_identifiers():
                    if isinstance(idt, Identifier):
                        name = idt.get_real_name()
                        if name and name.upper() not in ("SELECT", "WHERE", "GROUP", "ORDER", "HAVING"):
                            if name not in analysis["tables"]:
                                analysis["tables"].append(name)
                prev_kw = None

        # 提取 JOIN 类型
        for token in parsed.tokens:
            if token.is_keyword:
                val = token.value.upper()
                if "JOIN" in val and val not in analysis["joins"]:
                    analysis["joins"].append(val)

        # 检测子查询
        sub_count = len(re.findall(r"\(\s*SELECT\b", sql, re.IGNORECASE))
        if sub_count > 0:
            analysis["subqueries"].append(f"检测到 {sub_count} 个子查询")

        # 检测 SELECT *
        if re.search(r"SELECT\s+\*\s+FROM", sql, re.IGNORECASE):
            analysis["columns"].append("*")
            analysis["suggestions"].append("避免使用 SELECT *，明确指定需要的列")

        # 建议
        if sub_count > 3:
            analysis["warnings"].append("子查询过多，可能影响性能")
            analysis["suggestions"].append("考虑将子查询转换为 JOIN 或 CTE")

        if len(analysis["joins"]) > 5:
            analysis["warnings"].append("JOIN 数量较多，建议检查索引")

        if not analysis["tables"]:
            analysis["warnings"].append("未识别到表名，SQL结构可能较复杂")

        return analysis


def main():
    parser = argparse.ArgumentParser(description="SQL 优化引擎")
    parser.add_argument("sql", nargs="?", help="待优化的SQL语句")
    parser.add_argument("--file", "-f", help="从文件读取SQL")
    parser.add_argument("--analyze", action="store_true", help="输出分析报告而非优化")
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

    optimizer = SQLOptimizer()

    if args.analyze:
        report = optimizer.analyze(sql)
        print("=== SQL 分析报告 ===")
        print(f"表: {', '.join(report['tables']) or '未检测到'}")
        print(f"JOIN: {', '.join(report['joins']) or '无'}")
        print(f"子查询: {', '.join(report['subqueries']) or '无'}")
        if report["warnings"]:
            print(f"警告: {'; '.join(report['warnings'])}")
        if report["suggestions"]:
            print(f"建议: {'; '.join(report['suggestions'])}")
    else:
        optimized = optimizer.optimize(sql)
        print(optimized)


if __name__ == "__main__":
    main()
