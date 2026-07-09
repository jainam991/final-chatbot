"""
Generates synthetic data for the college query system and builds college.db
Run once: python3 generate_data.py
"""
import sqlite3
import random
from datetime import datetime, timedelta

random.seed(42)
DB_PATH = "college.db"


def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def create_schema(conn):
    c = conn.cursor()

    c.executescript("""
    DROP TABLE IF EXISTS courses;
    DROP TABLE IF EXISTS teachers;
    DROP TABLE IF EXISTS applications;
    DROP TABLE IF EXISTS fees;
    DROP TABLE IF EXISTS inventory;
    DROP TABLE IF EXISTS students;
    DROP TABLE IF EXISTS query_logs;
    DROP TABLE IF EXISTS users;

    CREATE TABLE users (
        user_id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        role TEXT NOT NULL,       -- Admin, Course Staff, Fees Staff, Teacher Admin, Applications Staff
        full_name TEXT
    );

    CREATE TABLE students (
        student_id INTEGER PRIMARY KEY AUTOINCREMENT,
        full_name TEXT NOT NULL,
        roll_no TEXT UNIQUE NOT NULL,
        department TEXT NOT NULL,
        year INTEGER NOT NULL,
        email TEXT
    );

    CREATE TABLE courses (
        course_id INTEGER PRIMARY KEY AUTOINCREMENT,
        course_name TEXT NOT NULL,
        department TEXT NOT NULL,
        credits INTEGER NOT NULL,
        seats_total INTEGER NOT NULL,
        seats_filled INTEGER NOT NULL,
        semester TEXT NOT NULL
    );

    CREATE TABLE teachers (
        teacher_id INTEGER PRIMARY KEY AUTOINCREMENT,
        full_name TEXT NOT NULL,
        department TEXT NOT NULL,
        designation TEXT NOT NULL,
        email TEXT,
        courses_assigned TEXT,
        years_experience INTEGER
    );

    CREATE TABLE applications (
        application_id INTEGER PRIMARY KEY AUTOINCREMENT,
        applicant_name TEXT NOT NULL,
        department_applied TEXT NOT NULL,
        application_date TEXT NOT NULL,
        status TEXT NOT NULL,     -- Pending, Approved, Rejected, Under Review
        score REAL,
        email TEXT
    );

    CREATE TABLE fees (
        fee_id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id INTEGER NOT NULL,
        semester TEXT NOT NULL,
        amount_due REAL NOT NULL,
        amount_paid REAL NOT NULL,
        paid_status TEXT NOT NULL,   -- Paid, Partial, Unpaid
        due_date TEXT NOT NULL,
        FOREIGN KEY (student_id) REFERENCES students(student_id)
    );

    CREATE TABLE inventory (
        item_id INTEGER PRIMARY KEY AUTOINCREMENT,
        item_name TEXT NOT NULL,
        category TEXT NOT NULL,
        quantity INTEGER NOT NULL,
        reorder_level INTEGER NOT NULL,
        location TEXT
    );

    CREATE TABLE query_logs (
        log_id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT NOT NULL,
        username TEXT,
        role TEXT,
        domain TEXT,
        question TEXT,
        generated_sql TEXT,
        status TEXT,          -- success, blocked, error
        error_message TEXT,
        response_time_ms INTEGER
    );
    """)
    conn.commit()


DEPARTMENTS = ["Computer Science", "Mechanical", "Electrical", "Civil", "Business Admin", "Physics", "Mathematics"]
FIRST_NAMES = ["Aarav", "Vivaan", "Aditi", "Diya", "Ishaan", "Ananya", "Kabir", "Meera", "Rohan", "Sanya",
               "Arjun", "Priya", "Karan", "Neha", "Vikram", "Pooja", "Rahul", "Sneha", "Aman", "Riya"]
LAST_NAMES = ["Sharma", "Verma", "Patel", "Gupta", "Iyer", "Nair", "Reddy", "Singh", "Mehta", "Joshi"]


def rand_name():
    return f"{random.choice(FIRST_NAMES)} {random.choice(LAST_NAMES)}"


def rand_date(days_back_max=365):
    d = datetime.now() - timedelta(days=random.randint(0, days_back_max))
    return d.strftime("%Y-%m-%d")


def seed_users(conn):
    users = [
        ("admin", "admin123", "Admin", "College Administrator"),
        ("fees_staff", "fees123", "Fees Staff", "Fee Office Clerk"),
        ("course_staff", "course123", "Course Staff", "Academic Office Staff"),
        ("teacher_admin", "teach123", "Teacher Admin", "HR - Faculty Affairs"),
        ("apps_staff", "apps123", "Applications Staff", "Admissions Officer"),
    ]
    conn.executemany(
        "INSERT INTO users (username, password, role, full_name) VALUES (?, ?, ?, ?)",
        users,
    )
    conn.commit()


def seed_students(conn, n=200):
    rows = []
    for i in range(n):
        dept = random.choice(DEPARTMENTS)
        year = random.randint(1, 4)
        roll = f"{dept[:2].upper()}{year}{1000+i}"
        name = rand_name()
        email = name.lower().replace(" ", ".") + "@college.edu"
        rows.append((name, roll, dept, year, email))
    conn.executemany(
        "INSERT INTO students (full_name, roll_no, department, year, email) VALUES (?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()


def seed_courses(conn):
    course_names = ["Data Structures", "Thermodynamics", "Circuit Theory", "Structural Analysis",
                     "Marketing Management", "Quantum Mechanics", "Linear Algebra", "Operating Systems",
                     "Fluid Mechanics", "Digital Electronics", "Financial Accounting", "Statistics",
                     "Machine Learning", "Database Systems", "Organizational Behavior"]
    rows = []
    for name in course_names:
        dept = random.choice(DEPARTMENTS)
        credits = random.choice([2, 3, 4])
        seats_total = random.choice([40, 50, 60, 80])
        seats_filled = random.randint(int(seats_total*0.5), seats_total)
        semester = random.choice(["Fall 2026", "Spring 2026"])
        rows.append((name, dept, credits, seats_total, seats_filled, semester))
    conn.executemany(
        "INSERT INTO courses (course_name, department, credits, seats_total, seats_filled, semester) VALUES (?, ?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()


def seed_teachers(conn, n=40):
    designations = ["Assistant Professor", "Associate Professor", "Professor", "Lecturer"]
    cur = conn.execute("SELECT course_name FROM courses")
    all_course_names = [r[0] for r in cur.fetchall()]
    rows = []
    for _ in range(n):
        name = rand_name()
        dept = random.choice(DEPARTMENTS)
        designation = random.choice(designations)
        email = name.lower().replace(" ", ".") + "@college.edu"
        assigned = random.sample(all_course_names, k=min(2, len(all_course_names)))
        courses = ", ".join(assigned)
        exp = random.randint(1, 25)
        rows.append((name, dept, designation, email, courses, exp))
    conn.executemany(
        "INSERT INTO teachers (full_name, department, designation, email, courses_assigned, years_experience) VALUES (?, ?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()


def seed_applications(conn, n=150):
    statuses = ["Pending", "Approved", "Rejected", "Under Review"]
    rows = []
    for _ in range(n):
        name = rand_name()
        dept = random.choice(DEPARTMENTS)
        date = rand_date(180)
        status = random.choice(statuses)
        score = round(random.uniform(50, 99), 1)
        email = name.lower().replace(" ", ".") + "@applicant.com"
        rows.append((name, dept, date, status, score, email))
    conn.executemany(
        "INSERT INTO applications (applicant_name, department_applied, application_date, status, score, email) VALUES (?, ?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()


def seed_fees(conn):
    cur = conn.execute("SELECT student_id FROM students")
    student_ids = [r[0] for r in cur.fetchall()]
    rows = []
    for sid in student_ids:
        for semester in ["Fall 2025", "Spring 2026"]:
            amount_due = random.choice([50000, 60000, 75000, 90000])
            paid_status = random.choices(["Paid", "Partial", "Unpaid"], weights=[0.6, 0.25, 0.15])[0]
            if paid_status == "Paid":
                amount_paid = amount_due
            elif paid_status == "Partial":
                amount_paid = round(amount_due * random.uniform(0.2, 0.8), 2)
            else:
                amount_paid = 0
            due_date = rand_date(120)
            rows.append((sid, semester, amount_due, amount_paid, paid_status, due_date))
    conn.executemany(
        "INSERT INTO fees (student_id, semester, amount_due, amount_paid, paid_status, due_date) VALUES (?, ?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()


def seed_inventory(conn):
    items = [
        ("Office Chair", "Furniture", "Admin Block"),
        ("Whiteboard Marker", "Stationery", "Store Room"),
        ("Projector", "Electronics", "AV Room"),
        ("Lab Beaker", "Lab Equipment", "Chemistry Lab"),
        ("Football", "Sports", "Sports Room"),
        ("Desktop Computer", "Electronics", "Computer Lab"),
        ("Cricket Bat", "Sports", "Sports Room"),
        ("Table Lamp", "Furniture", "Library"),
        ("Extension Cord", "Electronics", "Store Room"),
        ("Microscope", "Lab Equipment", "Biology Lab"),
    ]
    rows = []
    for name, cat, loc in items:
        qty = random.randint(5, 100)
        reorder = random.randint(5, 20)
        rows.append((name, cat, qty, reorder, loc))
    conn.executemany(
        "INSERT INTO inventory (item_name, category, quantity, reorder_level, location) VALUES (?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()


def main():
    conn = connect()
    create_schema(conn)
    seed_users(conn)
    seed_students(conn, n=200)
    seed_courses(conn)
    seed_teachers(conn, n=40)
    seed_applications(conn, n=150)
    seed_fees(conn)
    seed_inventory(conn)
    conn.close()
    print(f"Database created at {DB_PATH}")


if __name__ == "__main__":
    main()
