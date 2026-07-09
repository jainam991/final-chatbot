"""Shared login + logging helpers used by both the chat page and dashboard."""
import sqlite3
import streamlit as st
from datetime import datetime

DB_PATH = "college.db"

ROLE_DOMAINS = {
    "Admin": ["Course Inventory", "Teachers", "Applications", "Fees", "Inventory", "Other"],
    "Course Staff": ["Course Inventory", "Other"],
    "Fees Staff": ["Fees", "Other"],
    "Teacher Admin": ["Teachers", "Other"],
    "Applications Staff": ["Applications", "Other"],
}


def check_login(username: str, password: str):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.execute(
        "SELECT * FROM users WHERE username = ? AND password = ?", (username, password)
    )
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def login_form():
    st.subheader("🔐 Login")
    with st.form("login_form"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Log in")
        if submitted:
            user = check_login(username, password)
            if user:
                st.session_state["user"] = user
                st.rerun()
            else:
                st.error("Invalid username or password.")

    with st.expander("Demo credentials"):
        st.markdown("""
        | Username | Password | Role |
        |---|---|---|
        | admin | admin123 | Admin (sees everything) |
        | fees_staff | fees123 | Fees Staff |
        | course_staff | course123 | Course Staff |
        | teacher_admin | teach123 | Teacher Admin |
        | apps_staff | apps123 | Applications Staff |
        """)


def require_login():
    if "user" not in st.session_state:
        login_form()
        st.stop()
    return st.session_state["user"]


def logout_button():
    user = st.session_state.get("user")
    if user:
        st.sidebar.markdown(f"**{user['full_name']}**  \n_{user['role']}_")
        if st.sidebar.button("Log out"):
            del st.session_state["user"]
            st.rerun()


def log_query(username, role, domain, question, sql, status, error_message, response_time_ms):
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """INSERT INTO query_logs (timestamp, username, role, domain, question, generated_sql, status, error_message, response_time_ms)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            datetime.now().isoformat(timespec="seconds"),
            username, role, domain, question, sql, status, error_message, response_time_ms,
        ),
    )
    conn.commit()
    conn.close()
