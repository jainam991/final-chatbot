"""
Uses Claude to translate a natural-language question into SQL for the
relevant domain, validates it with sql_safety, executes it against
college.db, and returns a natural-language answer.
"""
import sqlite3
import os
import anthropic
from sql_safety import validate_sql, DOMAIN_TABLES

DB_PATH = "college.db"

SCHEMAS = {
    "students": """students(student_id INTEGER PK, full_name TEXT, roll_no TEXT, department TEXT, year INTEGER, email TEXT)""",
    "courses": """courses(course_id INTEGER PK, course_name TEXT, department TEXT, credits INTEGER, seats_total INTEGER, seats_filled INTEGER, semester TEXT)""",
    "teachers": """teachers(teacher_id INTEGER PK, full_name TEXT, department TEXT, designation TEXT, email TEXT, courses_assigned TEXT, years_experience INTEGER)""",
    "applications": """applications(application_id INTEGER PK, applicant_name TEXT, department_applied TEXT, application_date TEXT, status TEXT CHECK(Pending/Approved/Rejected/Under Review), score REAL, email TEXT)""",
    "fees": """fees(fee_id INTEGER PK, student_id INTEGER FK->students, semester TEXT, amount_due REAL, amount_paid REAL, paid_status TEXT CHECK(Paid/Partial/Unpaid), due_date TEXT)""",
    "inventory": """inventory(item_id INTEGER PK, item_name TEXT, category TEXT, quantity INTEGER, reorder_level INTEGER, location TEXT)""",
}

UPDATABLE_COLS = {
    "fees": ["paid_status", "amount_paid"],
    "inventory": ["quantity"],
    "applications": ["status"],
    "courses": ["seats_filled"],
}


def get_client():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set")
    return anthropic.Anthropic(api_key=api_key)


def build_schema_prompt(domain: str) -> str:
    tables = DOMAIN_TABLES.get(domain, [])
    lines = []
    for t in tables:
        lines.append(SCHEMAS[t])
        if t in UPDATABLE_COLS:
            lines.append(f"  -> writable columns for UPDATE: {UPDATABLE_COLS[t]}")
    return "\n".join(lines)


SYSTEM_PROMPT_TEMPLATE = """You are a SQL generator for a college management system, restricted to the "{domain}" domain.

You may ONLY reference these tables:
{schema}

Rules:
- Output ONLY the raw SQL statement. No markdown, no explanation, no backticks.
- Only ONE statement, no semicolon-chained statements.
- Prefer SELECT. Only use UPDATE on the writable columns listed above, and UPDATE must always include a WHERE clause.
- Only use INSERT for adding new inventory items or new applications, matching the full column list.
- Never use DROP, DELETE, ALTER, TRUNCATE, PRAGMA, or any schema-modifying statement.
- Use SQLite syntax.
- If the question cannot be answered with these tables, output exactly: NO_QUERY
"""


def generate_sql(question: str, domain: str) -> str:
    client = get_client()
    schema = build_schema_prompt(domain)
    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(domain=domain, schema=schema)

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=300,
        system=system_prompt,
        messages=[{"role": "user", "content": question}],
    )
    sql = response.content[0].text.strip()
    # strip accidental markdown fences
    sql = sql.replace("```sql", "").replace("```", "").strip()
    return sql


def execute_sql(sql: str):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        cur.execute(sql)
        if sql.strip().upper().startswith("SELECT"):
            rows = [dict(r) for r in cur.fetchall()]
            conn.close()
            return rows, cur.rowcount
        else:
            conn.commit()
            affected = cur.rowcount
            conn.close()
            return None, affected
    except Exception as e:
        conn.close()
        raise e


def summarize_result(question: str, sql: str, rows, affected: int) -> str:
    """Turn raw SQL results into a natural language answer using Claude."""
    client = get_client()
    if rows is not None:
        data_repr = str(rows[:30])  # cap to avoid huge payloads
        content = f"Question: {question}\nSQL used: {sql}\nResult rows ({len(rows)} total, showing up to 30): {data_repr}\n\nGive a short, clear, natural-language answer to the question based on this data. If it's a list, format it readably. Do not mention SQL."
    else:
        content = f"Question: {question}\nSQL used: {sql}\nRows affected: {affected}\n\nConfirm briefly and naturally what change was made."

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=400,
        messages=[{"role": "user", "content": content}],
    )
    return response.content[0].text.strip()


def answer_question(question: str, domain: str):
    """
    Full pipeline: generate SQL -> validate -> execute -> summarize.
    Returns a dict with all details needed for logging + display.
    """
    result = {
        "question": question,
        "domain": domain,
        "sql": None,
        "status": None,
        "error": None,
        "answer": None,
        "rows": None,
    }

    if domain == "Other":
        result["status"] = "no_query_needed"
        result["answer"] = None
        return result

    try:
        sql = generate_sql(question, domain)
        result["sql"] = sql

        if sql.strip() == "NO_QUERY":
            result["status"] = "no_query_needed"
            return result

        is_allowed, reason, stype = validate_sql(sql, domain)
        if not is_allowed:
            result["status"] = "blocked"
            result["error"] = reason
            return result

        rows, affected = execute_sql(sql)
        result["rows"] = rows
        result["status"] = "success"
        result["answer"] = summarize_result(question, sql, rows, affected)
        return result

    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)
        return result
