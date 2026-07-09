"""
Rule-based (NO API KEY, NO LLM) natural-language to SQL engine.

Instead of calling Claude, this uses:
- keyword/regex intent matching within each domain
- fuzzy entity extraction against real values already in the database
  (course names, teacher names, departments, item names, statuses, roll numbers)
- pre-written safe SQL templates per intent

100% free to run, works offline, no external API calls at all.
"""
import sqlite3
import re
import difflib

DB_PATH = "college.db"


# ---------------------------------------------------------------- helpers --

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def fetch_distinct(table, column):
    conn = get_conn()
    try:
        cur = conn.execute(f"SELECT DISTINCT {column} FROM {table}")
        return [r[0] for r in cur.fetchall() if r[0]]
    finally:
        conn.close()


def run_select(sql, params=()):
    conn = get_conn()
    try:
        cur = conn.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def run_write(sql, params=()):
    conn = get_conn()
    try:
        cur = conn.execute(sql, params)
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


def fuzzy_find(text, choices, cutoff=0.55):
    """Find the best-matching known value that appears (or nearly appears) in the text."""
    if not choices:
        return None
    text_lower = text.lower()

    # 1. direct substring match -> prefer the longest/most specific hit
    substr_matches = [c for c in choices if c.lower() in text_lower]
    if substr_matches:
        return max(substr_matches, key=len)

    # 2. fuzzy match against each word-window of the text
    best, best_score = None, 0.0
    words = text_lower.split()
    for c in choices:
        c_lower = c.lower()
        window = max(1, len(c_lower.split()))
        for i in range(len(words) - window + 1):
            chunk = " ".join(words[i:i + window])
            score = difflib.SequenceMatcher(None, c_lower, chunk).ratio()
            if score > best_score:
                best_score, best = score, c
    return best if best_score >= cutoff else None


def extract_number(text):
    m = re.search(r"\b(\d+)\b", text)
    return int(m.group(1)) if m else None


def extract_roll_no(text):
    m = re.search(r"\b([A-Za-z]{2}\d{5,6})\b", text)
    return m.group(1).upper() if m else None


ITEM_SYNONYMS = {
    "chairs": "Office Chair", "chair": "Office Chair",
    "markers": "Whiteboard Marker", "marker": "Whiteboard Marker",
    "projectors": "Projector", "projector": "Projector",
    "beakers": "Lab Beaker", "beaker": "Lab Beaker",
    "footballs": "Football", "football": "Football",
    "computers": "Desktop Computer", "computer": "Desktop Computer", "pcs": "Desktop Computer",
    "bats": "Cricket Bat", "bat": "Cricket Bat",
    "lamps": "Table Lamp", "lamp": "Table Lamp",
    "cords": "Extension Cord", "cord": "Extension Cord",
    "microscopes": "Microscope", "microscope": "Microscope",
}


def resolve_item_name(text, choices):
    text_lower = text.lower()
    for syn, real in ITEM_SYNONYMS.items():
        if syn in text_lower:
            return real
    return fuzzy_find(text, choices)


# ------------------------------------------------------------- intent map --
# Each entry: (regex pattern, intent_name). First match wins, checked in order.

INTENT_PATTERNS = {
    "Course Inventory": [
        (r"\b(full|available seats|seats left|how many seats)\b", "check_seats"),
        (r"\b(credit)", "course_credits"),
        (r"\b(list|show|all courses|catalog)\b", "list_courses"),
        (r"\b(department|which dept)\b", "course_department"),
        (r"\b(update|enroll|add student)\b", "update_seats"),
    ],
    "Teachers": [
        (r"\b(who teach|teaches|teaching)\b", "who_teaches"),
        (r"\b(email)\b", "teacher_email"),
        (r"\b(how many|count)\b", "count_teachers"),
        (r"\b(list|show|all)\b", "list_teachers"),
        (r"\b(experience|years)\b", "experience_filter"),
    ],
    "Applications": [
        (r"\b(pending)\b", "list_pending"),
        (r"\b(approved)\b", "list_approved"),
        (r"\b(rejected)\b", "list_rejected"),
        (r"\b(under review)\b", "list_under_review"),
        (r"\b(average|avg)\b", "avg_score"),
        (r"\b(how many|count|total applications)\b", "count_applications"),
        (r"\b(update|approve|reject|mark)\b", "update_status"),
        (r"\b(list|show)\b", "list_all_applications"),
    ],
    "Fees": [
        (r"\b(unpaid|not paid|pending dues|outstanding)\b", "list_unpaid"),
        (r"\b(partial)\b", "list_partial"),
        (r"\b(mark|update).*paid\b", "mark_paid"),
        (r"\b(total collected|total fee|collected)\b", "total_collected"),
        (r"\b(how much|owe|due)\b", "fee_owed"),
        (r"\b(list|show)\b", "list_all_fees"),
    ],
    "Inventory": [
        (r"\b(low stock|reorder|need)\b", "low_stock"),
        (r"\b(received|got|restocked)\b", "update_quantity_add"),
        (r"\b(used|removed|consumed|took)\b", "update_quantity_subtract"),
        (r"\b(add a new item|add new|new item)\b", "add_item"),
        (r"\b(how many|quantity|left|stock)\b", "check_quantity"),
        (r"\b(list|show|all)\b", "list_inventory"),
    ],
}


def detect_intent(domain, question):
    q = question.lower()
    for pattern, intent in INTENT_PATTERNS.get(domain, []):
        if re.search(pattern, q):
            return intent
    return "unknown"


# ------------------------------------------------------------ domain logic --

def handle_course_inventory(question, intent):
    courses = fetch_distinct("courses", "course_name")
    departments = fetch_distinct("courses", "department")

    if intent == "check_seats":
        course = fuzzy_find(question, courses)
        if not course:
            return None, "I couldn't tell which course you meant. Try naming it more specifically."
        rows = run_select(
            "SELECT course_name, seats_total, seats_filled, semester FROM courses WHERE course_name = ?",
            (course,),
        )
        if not rows:
            return None, f"No data found for '{course}'."
        r = rows[0]
        remaining = r["seats_total"] - r["seats_filled"]
        status = "full" if remaining <= 0 else f"{remaining} seat(s) available"
        return rows, f"**{r['course_name']}** ({r['semester']}): {r['seats_filled']}/{r['seats_total']} seats filled — {status}."

    if intent == "course_credits":
        course = fuzzy_find(question, courses)
        if not course:
            return None, "I couldn't tell which course you meant."
        rows = run_select("SELECT course_name, credits FROM courses WHERE course_name = ?", (course,))
        if not rows:
            return None, f"No data found for '{course}'."
        return rows, f"**{rows[0]['course_name']}** is worth {rows[0]['credits']} credits."

    if intent == "course_department":
        course = fuzzy_find(question, courses)
        if not course:
            return None, "I couldn't tell which course you meant."
        rows = run_select("SELECT course_name, department FROM courses WHERE course_name = ?", (course,))
        if not rows:
            return None, f"No data found for '{course}'."
        return rows, f"**{rows[0]['course_name']}** is offered by the {rows[0]['department']} department."

    if intent == "list_courses":
        dept = fuzzy_find(question, departments)
        if dept:
            rows = run_select("SELECT course_name, department, semester FROM courses WHERE department = ?", (dept,))
            label = f" in {dept}"
        else:
            rows = run_select("SELECT course_name, department, semester FROM courses")
            label = ""
        if not rows:
            return rows, f"No courses found{label}."
        names = ", ".join(r["course_name"] for r in rows)
        return rows, f"Courses{label} ({len(rows)}): {names}."

    return None, "I understood you're asking about courses, but couldn't map it to a specific lookup. Try: 'how many seats left in X', 'what department offers X', or 'list courses in X'."


def handle_teachers(question, intent):
    teachers = fetch_distinct("teachers", "full_name")
    departments = fetch_distinct("teachers", "department")
    courses = fetch_distinct("courses", "course_name")
    designations = fetch_distinct("teachers", "designation")

    if intent == "who_teaches":
        course = fuzzy_find(question, courses)
        if not course:
            return None, "I couldn't tell which course you meant."
        rows = run_select(
            "SELECT full_name, department, email FROM teachers WHERE courses_assigned LIKE ?",
            (f"%{course}%",),
        )
        if not rows:
            return rows, f"No teacher found assigned to '{course}' in our records."
        names = ", ".join(r["full_name"] for r in rows)
        return rows, f"**{course}** is taught by: {names}."

    if intent == "teacher_email":
        teacher = fuzzy_find(question, teachers)
        if not teacher:
            return None, "I couldn't tell which teacher you meant."
        rows = run_select("SELECT full_name, email FROM teachers WHERE full_name = ?", (teacher,))
        if not rows:
            return None, f"No record found for '{teacher}'."
        return rows, f"{rows[0]['full_name']}'s email is {rows[0]['email']}."

    if intent == "count_teachers":
        dept = fuzzy_find(question, departments)
        if dept:
            rows = run_select("SELECT COUNT(*) as cnt FROM teachers WHERE department = ?", (dept,))
            return rows, f"There are {rows[0]['cnt']} teachers in {dept}."
        rows = run_select("SELECT COUNT(*) as cnt FROM teachers")
        return rows, f"There are {rows[0]['cnt']} teachers total."

    if intent == "list_teachers":
        dept = fuzzy_find(question, departments)
        desig = fuzzy_find(question, designations)
        if dept:
            rows = run_select("SELECT full_name, designation FROM teachers WHERE department = ?", (dept,))
            label = f" in {dept}"
        elif desig:
            rows = run_select("SELECT full_name, department FROM teachers WHERE designation = ?", (desig,))
            label = f" who are {desig}s"
        else:
            rows = run_select("SELECT full_name, department, designation FROM teachers")
            label = ""
        if not rows:
            return rows, f"No teachers found{label}."
        names = ", ".join(r["full_name"] for r in rows[:20])
        more = f" (+{len(rows)-20} more)" if len(rows) > 20 else ""
        return rows, f"Teachers{label} ({len(rows)}): {names}{more}."

    if intent == "experience_filter":
        num = extract_number(question) or 10
        rows = run_select(
            "SELECT full_name, department, years_experience FROM teachers WHERE years_experience > ?", (num,)
        )
        if not rows:
            return rows, f"No teachers found with more than {num} years of experience."
        names = ", ".join(f"{r['full_name']} ({r['years_experience']}y)" for r in rows[:20])
        return rows, f"Teachers with more than {num} years experience ({len(rows)}): {names}."

    return None, "I understood you're asking about teachers, but couldn't map it to a specific lookup. Try: 'who teaches X', 'how many teachers in X department', or 'teachers with more than N years experience'."


def handle_applications(question, intent):
    departments = fetch_distinct("applications", "department_applied")
    status_map = {
        "list_pending": "Pending", "list_approved": "Approved",
        "list_rejected": "Rejected", "list_under_review": "Under Review",
    }

    if intent in status_map:
        status = status_map[intent]
        dept = fuzzy_find(question, departments)
        if dept:
            rows = run_select(
                "SELECT applicant_name, department_applied, score FROM applications WHERE status = ? AND department_applied = ?",
                (status, dept),
            )
            label = f" for {dept}"
        else:
            rows = run_select(
                "SELECT applicant_name, department_applied, score FROM applications WHERE status = ?", (status,)
            )
            label = ""
        return rows, f"{len(rows)} application(s) are {status}{label}."

    if intent == "avg_score":
        dept = fuzzy_find(question, departments)
        if dept:
            rows = run_select(
                "SELECT AVG(score) as avg_score FROM applications WHERE department_applied = ?", (dept,)
            )
            label = f" for {dept}"
        else:
            rows = run_select("SELECT AVG(score) as avg_score FROM applications")
            label = ""
        avg = rows[0]["avg_score"]
        return rows, f"The average application score{label} is {avg:.1f}." if avg else f"No score data available{label}."

    if intent == "count_applications":
        dept = fuzzy_find(question, departments)
        if dept:
            rows = run_select(
                "SELECT COUNT(*) as cnt FROM applications WHERE department_applied = ?", (dept,)
            )
            label = f" for {dept}"
        else:
            rows = run_select("SELECT COUNT(*) as cnt FROM applications")
            label = ""
        return rows, f"There are {rows[0]['cnt']} total applications{label}."

    if intent == "list_all_applications":
        rows = run_select("SELECT applicant_name, department_applied, status FROM applications LIMIT 30")
        return rows, f"Showing {len(rows)} applications (capped at 30). Ask about a specific status (pending/approved/rejected) to narrow it down."

    if intent == "update_status":
        return None, "Updating application status requires a specific applicant name/ID — this action isn't wired into the free rule-based mode yet. Please update it directly if needed."

    return None, "I understood you're asking about applications, but couldn't map it to a specific lookup. Try: 'how many pending applications', 'show approved applications for X', or 'average score'."


def handle_fees(question, intent):
    if intent == "list_unpaid":
        rows = run_select(
            """SELECT s.full_name, s.roll_no, f.semester, f.amount_due
               FROM fees f JOIN students s ON f.student_id = s.student_id
               WHERE f.paid_status = 'Unpaid'"""
        )
        return rows, f"{len(rows)} student(s) have unpaid fees."

    if intent == "list_partial":
        rows = run_select(
            """SELECT s.full_name, s.roll_no, f.semester, f.amount_due, f.amount_paid
               FROM fees f JOIN students s ON f.student_id = s.student_id
               WHERE f.paid_status = 'Partial'"""
        )
        return rows, f"{len(rows)} student(s) have made partial fee payments."

    if intent == "total_collected":
        rows = run_select("SELECT SUM(amount_paid) as total FROM fees")
        total = rows[0]["total"] or 0
        return rows, f"Total fees collected so far: ₹{total:,.2f}."

    if intent == "fee_owed":
        roll = extract_roll_no(question)
        if roll:
            rows = run_select(
                """SELECT s.full_name, f.semester, f.amount_due, f.amount_paid, f.paid_status
                   FROM fees f JOIN students s ON f.student_id = s.student_id
                   WHERE s.roll_no = ?""",
                (roll,),
            )
            if not rows:
                return None, f"No fee record found for roll number {roll}."
            lines = [f"{r['semester']}: ₹{r['amount_due']-r['amount_paid']:,.2f} due ({r['paid_status']})" for r in rows]
            return rows, f"{rows[0]['full_name']}'s dues — " + "; ".join(lines)
        names = fetch_distinct("students", "full_name")
        student = fuzzy_find(question, names)
        if student:
            rows = run_select(
                """SELECT f.semester, f.amount_due, f.amount_paid, f.paid_status
                   FROM fees f JOIN students s ON f.student_id = s.student_id
                   WHERE s.full_name = ?""",
                (student,),
            )
            if not rows:
                return None, f"No fee record found for {student}."
            lines = [f"{r['semester']}: ₹{r['amount_due']-r['amount_paid']:,.2f} due ({r['paid_status']})" for r in rows]
            return rows, f"{student}'s dues — " + "; ".join(lines)
        return None, "I couldn't tell which student you meant. Try including their roll number (e.g. CS1001) or full name."

    if intent == "mark_paid":
        return None, "Marking fees as paid requires a specific student roll number and semester — this write action isn't wired into the free rule-based mode yet."

    if intent == "list_all_fees":
        rows = run_select(
            """SELECT s.full_name, s.roll_no, f.semester, f.paid_status
               FROM fees f JOIN students s ON f.student_id = s.student_id LIMIT 30"""
        )
        return rows, f"Showing {len(rows)} fee records (capped at 30). Ask about unpaid/partial fees to narrow it down."

    return None, "I understood you're asking about fees, but couldn't map it to a specific lookup. Try: 'show unpaid fees', 'total fees collected', or 'how much does <roll number> owe'."


def handle_inventory(question, intent):
    items = fetch_distinct("inventory", "item_name")
    categories = fetch_distinct("inventory", "category")

    if intent == "check_quantity":
        item = resolve_item_name(question, items)
        if not item:
            return None, "I couldn't tell which item you meant."
        rows = run_select("SELECT item_name, quantity, location FROM inventory WHERE item_name = ?", (item,))
        if not rows:
            return None, f"No record found for '{item}'."
        return rows, f"We have {rows[0]['quantity']} {rows[0]['item_name']}(s) in {rows[0]['location']}."

    if intent == "low_stock":
        rows = run_select("SELECT item_name, quantity, reorder_level FROM inventory WHERE quantity <= reorder_level")
        if not rows:
            return rows, "No items are currently below their reorder level."
        names = ", ".join(f"{r['item_name']} ({r['quantity']} left)" for r in rows)
        return rows, f"{len(rows)} item(s) need reordering: {names}."

    if intent == "list_inventory":
        cat = fuzzy_find(question, categories)
        if cat:
            rows = run_select("SELECT item_name, quantity, location FROM inventory WHERE category = ?", (cat,))
            label = f" in {cat}"
        else:
            rows = run_select("SELECT item_name, quantity, location FROM inventory")
            label = ""
        names = ", ".join(f"{r['item_name']} ({r['quantity']})" for r in rows)
        return rows, f"Inventory{label} ({len(rows)} items): {names}."

    if intent == "update_quantity_add":
        item = resolve_item_name(question, items)
        num = extract_number(question)
        if not item or not num:
            return None, "I couldn't tell which item and quantity you meant. Try: 'we received 20 more markers'."
        affected = run_write("UPDATE inventory SET quantity = quantity + ? WHERE item_name = ?", (num, item))
        rows = run_select("SELECT item_name, quantity FROM inventory WHERE item_name = ?", (item,))
        return rows, f"Added {num} to {item}. New quantity: {rows[0]['quantity']}."

    if intent == "update_quantity_subtract":
        item = resolve_item_name(question, items)
        num = extract_number(question)
        if not item or not num:
            return None, "I couldn't tell which item and quantity you meant. Try: 'we used 5 footballs'."
        affected = run_write(
            "UPDATE inventory SET quantity = MAX(quantity - ?, 0) WHERE item_name = ?", (num, item)
        )
        rows = run_select("SELECT item_name, quantity FROM inventory WHERE item_name = ?", (item,))
        return rows, f"Removed {num} from {item}. New quantity: {rows[0]['quantity']}."

    if intent == "add_item":
        return None, "Adding a brand-new inventory item needs category/quantity/location details — this isn't wired into the free rule-based mode yet. Try phrasing it as an update to an existing item instead."

    return None, "I understood you're asking about inventory, but couldn't map it to a specific lookup. Try: 'how many chairs left', 'show low stock items', or 'we received 20 more markers'."


DOMAIN_HANDLERS = {
    "Course Inventory": handle_course_inventory,
    "Teachers": handle_teachers,
    "Applications": handle_applications,
    "Fees": handle_fees,
    "Inventory": handle_inventory,
}


def answer_question(question: str, domain: str):
    """
    Same return contract as the old llm_sql.answer_question, so app.py
    barely needs to change: {question, domain, sql, status, error, answer, rows}
    """
    result = {
        "question": question, "domain": domain, "sql": None,
        "status": None, "error": None, "answer": None, "rows": None,
    }

    if domain == "Other" or domain not in DOMAIN_HANDLERS:
        result["status"] = "no_query_needed"
        return result

    intent = detect_intent(domain, question)
    result["sql"] = f"[rule-based] domain={domain} intent={intent}"

    try:
        rows, answer = DOMAIN_HANDLERS[domain](question, intent)
        if rows is None and answer:
            result["status"] = "no_query_needed"
            result["answer"] = answer
        else:
            result["status"] = "success"
            result["rows"] = rows
            result["answer"] = answer
        return result
    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)
        return result
