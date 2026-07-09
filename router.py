"""
Lightweight domain router. Classifies an incoming question into one of:
Course Inventory, Teachers, Applications, Fees, Inventory, Other

Uses TF-IDF + Logistic Regression (fast, no LLM call needed) so we don't
spend an API call just to figure out where to route the question.
"""
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
import pickle
import os

MODEL_PATH = "router_model.pkl"

TRAINING_DATA = [
    # Course Inventory
    ("how many seats are left in data structures", "Course Inventory"),
    ("what courses are offered this semester", "Course Inventory"),
    ("show me all courses in computer science", "Course Inventory"),
    ("how many credits is machine learning", "Course Inventory"),
    ("is thermodynamics full", "Course Inventory"),
    ("list courses for spring 2026", "Course Inventory"),
    ("which department offers linear algebra", "Course Inventory"),
    ("update seats filled for database systems", "Course Inventory"),
    ("how many students enrolled in operating systems", "Course Inventory"),
    ("show course catalog", "Course Inventory"),

    # Teachers
    ("who teaches machine learning", "Teachers"),
    ("how many teachers in computer science department", "Teachers"),
    ("show me professor details", "Teachers"),
    ("which teachers have more than 10 years experience", "Teachers"),
    ("list all associate professors", "Teachers"),
    ("what is the email of professor sharma", "Teachers"),
    ("how many faculty members do we have", "Teachers"),
    ("show teachers in mechanical department", "Teachers"),
    ("who is teaching database systems", "Teachers"),
    ("list faculty by designation", "Teachers"),

    # Applications
    ("how many applications are pending", "Applications"),
    ("show me approved applications", "Applications"),
    ("what is the status of my application", "Applications"),
    ("list rejected applicants", "Applications"),
    ("how many students applied to computer science", "Applications"),
    ("update application status to approved", "Applications"),
    ("show applications under review", "Applications"),
    ("what is the average application score", "Applications"),
    ("list applicants with score above 90", "Applications"),
    ("how many total applications this year", "Applications"),

    # Fees
    ("how much fee do i owe", "Fees"),
    ("show unpaid fees for student roll number cs1001", "Fees"),
    ("mark fee as paid for student 5", "Fees"),
    ("how many students have not paid fees", "Fees"),
    ("what is the total fee collected this semester", "Fees"),
    ("show partial payments", "Fees"),
    ("list students with pending dues", "Fees"),
    ("update payment status to paid", "Fees"),
    ("how much did student pay last semester", "Fees"),
    ("total outstanding fees amount", "Fees"),

    # Inventory
    ("how many chairs are left", "Inventory"),
    ("show low stock items", "Inventory"),
    ("we received 20 more markers", "Inventory"),
    ("how many projectors do we have", "Inventory"),
    ("update quantity of footballs", "Inventory"),
    ("add a new item table lamp", "Inventory"),
    ("what items need reordering", "Inventory"),
    ("show inventory in sports room", "Inventory"),
    ("how many microscopes in biology lab", "Inventory"),
    ("list all lab equipment", "Inventory"),

    # Other / general
    ("hello", "Other"),
    ("hi there", "Other"),
    ("what can you help me with", "Other"),
    ("thank you", "Other"),
    ("help", "Other"),
    ("what is this system", "Other"),
    ("who are you", "Other"),
    ("good morning", "Other"),
]


def train_router():
    texts = [t for t, _ in TRAINING_DATA]
    labels = [l for _, l in TRAINING_DATA]

    vectorizer = TfidfVectorizer(ngram_range=(1, 2), min_df=1, sublinear_tf=True)
    X = vectorizer.fit_transform(texts)

    clf = LogisticRegression(max_iter=2000, C=8.0)
    clf.fit(X, labels)

    with open(MODEL_PATH, "wb") as f:
        pickle.dump((vectorizer, clf), f)

    return vectorizer, clf


def load_router():
    if not os.path.exists(MODEL_PATH):
        return train_router()
    with open(MODEL_PATH, "rb") as f:
        return pickle.load(f)


def classify_domain(question: str, vectorizer=None, clf=None):
    """Returns (domain, confidence)"""
    if vectorizer is None or clf is None:
        vectorizer, clf = load_router()
    X = vectorizer.transform([question])
    probs = clf.predict_proba(X)[0]
    classes = clf.classes_
    best_idx = probs.argmax()
    return classes[best_idx], float(probs[best_idx])


if __name__ == "__main__":
    vectorizer, clf = train_router()
    test_qs = [
        "how many chairs are left in inventory",
        "who teaches thermodynamics",
        "mark fee id 3 as paid",
        "how many pending applications",
        "is data structures full",
        "hello how are you",
    ]
    for q in test_qs:
        domain, conf = classify_domain(q, vectorizer, clf)
        print(f"{domain:20s} ({conf:.2f})  <- {q}")
