"""
Safety layer for LLM-generated SQL.

Rules:
- SELECT is always allowed on the tables belonging to the current domain.
- UPDATE is allowed ONLY on a small whitelist of (table, column) pairs per domain
  (e.g. fees.paid_status, fees.amount_paid, inventory.quantity).
- INSERT is allowed only on whitelisted tables for "add new record" type intents.
- DROP, DELETE, ALTER, TRUNCATE, ATTACH, PRAGMA, multiple statements, and any
  table outside the domain's allowed list are always blocked.
- Only one statement per query (no ';' chaining) is allowed.
"""
import re
import sqlparse

# Which tables each domain may touch at all
DOMAIN_TABLES = {
    "Course Inventory": ["courses"],
    "Teachers": ["teachers"],
    "Applications": ["applications"],
    "Fees": ["fees", "students"],
    "Inventory": ["inventory"],
    "Other": ["students", "courses", "teachers", "applications", "fees", "inventory"],
}

# (table, column) pairs that may be UPDATEd. Everything else is read-only.
UPDATE_WHITELIST = {
    ("fees", "paid_status"),
    ("fees", "amount_paid"),
    ("inventory", "quantity"),
    ("applications", "status"),
    ("courses", "seats_filled"),
}

# Tables that may receive INSERTs (new records) via chat
INSERT_WHITELIST = {"inventory", "applications"}

BLOCKED_KEYWORDS = [
    "drop", "delete", "alter", "truncate", "attach", "detach", "pragma",
    "vacuum", "reindex", "create", "replace into", "grant", "revoke",
]


class SQLSafetyError(Exception):
    pass


def _extract_tables(parsed_stmt):
    tables = set()
    tokens = list(parsed_stmt.flatten())
    trigger_types = (sqlparse.tokens.Keyword, sqlparse.tokens.Keyword.DML, sqlparse.tokens.Keyword.DDL)
    for i, tok in enumerate(tokens):
        if tok.ttype in trigger_types and tok.value.upper() in ("FROM", "INTO", "UPDATE", "JOIN"):
            # find next identifier token
            for j in range(i + 1, len(tokens)):
                nxt = tokens[j]
                if nxt.is_whitespace:
                    continue
                if nxt.ttype in (sqlparse.tokens.Name, None) or nxt.ttype is sqlparse.tokens.Literal.String.Symbol:
                    tables.add(nxt.value.strip('"[]`').lower())
                break
    return tables


def validate_sql(sql: str, domain: str):
    """
    Validates a single SQL statement against domain + whitelist rules.
    Returns (is_allowed: bool, reason: str, statement_type: str)
    """
    sql_clean = sql.strip().rstrip(";")

    if not sql_clean:
        return False, "Empty SQL generated.", None

    # Only one statement allowed
    statements = [s for s in sqlparse.split(sql_clean) if s.strip()]
    if len(statements) != 1:
        return False, "Multiple SQL statements are not allowed.", None

    lowered = sql_clean.lower()

    # Blocked keyword scan (word-boundary to avoid false positives like 'updated_at')
    for kw in BLOCKED_KEYWORDS:
        if re.search(rf"\b{re.escape(kw)}\b", lowered):
            return False, f"Blocked keyword detected: '{kw}'.", None

    parsed = sqlparse.parse(sql_clean)[0]
    stmt_type = parsed.get_type()  # SELECT, UPDATE, INSERT, UNKNOWN, etc.

    allowed_tables = set(DOMAIN_TABLES.get(domain, []))
    used_tables = _extract_tables(parsed)

    if not used_tables:
        return False, "Could not determine tables referenced in query.", stmt_type

    # Every table touched must be within this domain's allowed set
    disallowed = used_tables - allowed_tables
    if disallowed:
        return False, f"Query touches tables outside this domain's scope: {disallowed}.", stmt_type

    if stmt_type == "SELECT":
        return True, "OK", stmt_type

    if stmt_type == "UPDATE":
        # Extract "SET col = " column names
        set_cols = re.findall(r"set\s+(.+?)\s+where", lowered, re.DOTALL)
        if not set_cols:
            set_cols = re.findall(r"set\s+(.+)$", lowered, re.DOTALL)
        if not set_cols:
            return False, "Could not parse SET clause for UPDATE.", stmt_type
        cols = re.findall(r"([a-zA-Z_][a-zA-Z0-9_]*)\s*=", set_cols[0])
        for table in used_tables:
            for col in cols:
                if (table, col) not in UPDATE_WHITELIST:
                    return False, f"Column '{table}.{col}' is not allowed to be updated via chat.", stmt_type
        if "where" not in lowered:
            return False, "UPDATE without a WHERE clause is blocked (would affect all rows).", stmt_type
        return True, "OK", stmt_type

    if stmt_type == "INSERT":
        for table in used_tables:
            if table not in INSERT_WHITELIST:
                return False, f"INSERT into '{table}' is not permitted via chat.", stmt_type
        return True, "OK", stmt_type

    return False, f"Statement type '{stmt_type}' is not permitted.", stmt_type
