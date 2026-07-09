import streamlit as st
import time
import os
from router import classify_domain, load_router
import rule_sql
from auth import require_login, logout_button, log_query, ROLE_DOMAINS

st.set_page_config(page_title="College Query Assistant", page_icon="🎓", layout="centered")

user = require_login()
logout_button()

st.title("🎓 College Query Assistant")
st.caption(f"Signed in as **{user['full_name']}** ({user['role']}) — ask about courses, teachers, applications, fees, or inventory.")

has_api_key = bool(os.environ.get("ANTHROPIC_API_KEY"))
engine = "rule"
if has_api_key:
    engine_choice = st.sidebar.radio(
        "Answer engine",
        ["Free (rule-based, no API cost)", "Claude (flexible, uses API credits)"],
        index=0,
    )
    engine = "rule" if engine_choice.startswith("Free") else "llm"
else:
    st.sidebar.caption("Running in **free rule-based mode** (no API key detected). Add `ANTHROPIC_API_KEY` in Secrets to unlock the flexible Claude-powered engine.")

allowed_domains = ROLE_DOMAINS.get(user["role"], ["Other"])

vectorizer, clf = load_router()

if "messages" not in st.session_state:
    st.session_state.messages = [
        {"role": "assistant", "content": "Hi! Ask me about courses, teachers, applications, fees, or inventory."}
    ]

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        if msg.get("meta"):
            st.caption(msg["meta"])

question = st.chat_input("Ask a question...")

if question:
    st.session_state.messages.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)

    domain, confidence = classify_domain(question, vectorizer, clf)

    with st.chat_message("assistant"):
        if domain not in allowed_domains:
            answer = (
                f"That question looks like it belongs to **{domain}**, which your role "
                f"(**{user['role']}**) doesn't have access to. You can ask about: "
                f"{', '.join(d for d in allowed_domains if d != 'Other')}."
            )
            st.markdown(answer)
            meta = f"Routed to: {domain} ({confidence:.0%} confidence) — access denied"
            st.caption(meta)
            st.session_state.messages.append({"role": "assistant", "content": answer, "meta": meta})
            log_query(user["username"], user["role"], domain, question, None, "blocked", "role not permitted for domain", 0)

        elif domain == "Other":
            answer = "I can help with questions about courses, teachers, applications, fees, or inventory. Try asking something like 'how many students applied to computer science' or 'show unpaid fees'."
            st.markdown(answer)
            meta = f"Routed to: {domain} ({confidence:.0%} confidence)"
            st.caption(meta)
            st.session_state.messages.append({"role": "assistant", "content": answer, "meta": meta})
            log_query(user["username"], user["role"], domain, question, None, "no_query_needed", None, 0)

        else:
            with st.spinner(f"Looking into {domain}..."):
                start = time.time()
                try:
                    if engine == "llm":
                        import llm_sql
                        result = llm_sql.answer_question(question, domain)
                    else:
                        result = rule_sql.answer_question(question, domain)
                    elapsed_ms = int((time.time() - start) * 1000)

                    if result["status"] == "success":
                        answer = result["answer"]
                        st.markdown(answer)
                        meta = f"Routed to: {domain} ({confidence:.0%} confidence) · {engine} engine · {elapsed_ms}ms"
                        with st.expander("Show query details"):
                            st.code(result["sql"] or "", language="sql")
                        st.caption(meta)
                        log_query(user["username"], user["role"], domain, question, result["sql"], "success", None, elapsed_ms)

                    elif result["status"] == "blocked":
                        answer = f"⚠️ I generated a query but it was blocked by the safety layer: *{result['error']}*"
                        st.markdown(answer)
                        with st.expander("Show blocked SQL"):
                            st.code(result["sql"] or "", language="sql")
                        log_query(user["username"], user["role"], domain, question, result["sql"], "blocked", result["error"], elapsed_ms)

                    elif result["status"] == "no_query_needed":
                        answer = result.get("answer") or "I couldn't map that question to a database query in this domain. Could you rephrase it?"
                        st.markdown(answer)
                        log_query(user["username"], user["role"], domain, question, None, "no_query_needed", None, elapsed_ms)

                    else:
                        answer = f"⚠️ Something went wrong: {result['error']}"
                        st.markdown(answer)
                        log_query(user["username"], user["role"], domain, question, result.get("sql"), "error", result["error"], elapsed_ms)

                    st.session_state.messages.append({"role": "assistant", "content": answer})

                except Exception as e:
                    elapsed_ms = int((time.time() - start) * 1000)
                    err_msg = f"⚠️ Error: {e}"
                    st.markdown(err_msg)
                    st.session_state.messages.append({"role": "assistant", "content": err_msg})
                    log_query(user["username"], user["role"], domain, question, None, "error", str(e), elapsed_ms)

st.sidebar.markdown("---")
st.sidebar.markdown("**Available domains for your role:**")
for d in allowed_domains:
    if d != "Other":
        st.sidebar.markdown(f"- {d}")
