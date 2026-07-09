import streamlit as st
import sqlite3
import pandas as pd
import plotly.express as px
from auth import require_login, logout_button, ROLE_DOMAINS

st.set_page_config(page_title="Dashboard", page_icon="📊", layout="wide")

user = require_login()
logout_button()

st.title("📊 Query Activity Dashboard")

DB_PATH = "college.db"


@st.cache_data(ttl=10)
def load_logs():
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query("SELECT * FROM query_logs ORDER BY timestamp DESC", conn)
    conn.close()
    if not df.empty:
        df["timestamp"] = pd.to_datetime(df["timestamp"])
    return df


df = load_logs()

# Role-based filtering: non-admins only see logs for domains their role covers
if user["role"] != "Admin":
    allowed = ROLE_DOMAINS.get(user["role"], [])
    df = df[df["domain"].isin(allowed)]
    st.caption(f"Showing activity for domains visible to **{user['role']}**: {', '.join(d for d in allowed if d != 'Other')}")
else:
    st.caption("Showing activity across **all domains** (Admin view)")

if df.empty:
    st.info("No queries logged yet. Go ask something in the chat!")
    st.stop()

# --- Top metrics ---
col1, col2, col3, col4 = st.columns(4)
col1.metric("Total Queries", len(df))
success_rate = (df["status"] == "success").mean() * 100
col2.metric("Success Rate", f"{success_rate:.0f}%")
blocked = (df["status"] == "blocked").sum()
col3.metric("Blocked (safety)", int(blocked))
avg_time = df.loc[df["response_time_ms"] > 0, "response_time_ms"].mean()
col4.metric("Avg Response Time", f"{avg_time:.0f} ms" if pd.notna(avg_time) else "—")

st.markdown("---")

# --- Charts row ---
c1, c2 = st.columns(2)

with c1:
    st.subheader("Queries by Domain")
    domain_counts = df["domain"].value_counts().reset_index()
    domain_counts.columns = ["domain", "count"]
    fig = px.bar(domain_counts, x="domain", y="count", color="domain")
    fig.update_layout(showlegend=False, xaxis_title=None, yaxis_title="Queries")
    st.plotly_chart(fig, use_container_width=True)

with c2:
    st.subheader("Query Status Breakdown")
    status_counts = df["status"].value_counts().reset_index()
    status_counts.columns = ["status", "count"]
    fig2 = px.pie(status_counts, names="status", values="count", hole=0.4)
    st.plotly_chart(fig2, use_container_width=True)

st.subheader("Query Volume Over Time")
df["date"] = df["timestamp"].dt.date
daily = df.groupby("date").size().reset_index(name="count")
fig3 = px.line(daily, x="date", y="count", markers=True)
fig3.update_layout(yaxis_title="Queries", xaxis_title=None)
st.plotly_chart(fig3, use_container_width=True)

if user["role"] == "Admin":
    st.subheader("Most Active Users")
    user_counts = df["username"].value_counts().reset_index()
    user_counts.columns = ["username", "count"]
    fig4 = px.bar(user_counts, x="username", y="count")
    fig4.update_layout(yaxis_title="Queries", xaxis_title=None)
    st.plotly_chart(fig4, use_container_width=True)

st.markdown("---")

# --- Failed / blocked queries table (important for safety monitoring) ---
st.subheader("⚠️ Blocked or Failed Queries")
problem_df = df[df["status"].isin(["blocked", "error"])][
    ["timestamp", "username", "domain", "question", "generated_sql", "status", "error_message"]
]
if problem_df.empty:
    st.success("No blocked or failed queries in the log.")
else:
    st.dataframe(problem_df, use_container_width=True, hide_index=True)

st.markdown("---")
st.subheader("Recent Query Log")
recent_cols = ["timestamp", "username", "role", "domain", "question", "status", "response_time_ms"]
st.dataframe(df[recent_cols].head(50), use_container_width=True, hide_index=True)
