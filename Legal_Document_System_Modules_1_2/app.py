import os
import sqlite3
from datetime import datetime
from functools import wraps

from flask import Flask, render_template, request, redirect, url_for, session, flash, send_from_directory
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
DB_PATH = os.path.join(BASE_DIR, "legal_documents.db")
ALLOWED_EXTENSIONS = {"pdf", "docx", "txt"}

app = Flask(__name__)
app.secret_key = "change-this-secret-key-for-production"
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            email TEXT,
            role TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS documents (
            document_id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_name TEXT NOT NULL,
            stored_name TEXT NOT NULL,
            file_path TEXT NOT NULL,
            uploaded_by INTEGER NOT NULL,
            upload_date TEXT NOT NULL,
            document_type TEXT,
            extracted_text TEXT,
            status TEXT NOT NULL,
            FOREIGN KEY(uploaded_by) REFERENCES users(user_id)
        )
    """)
    users = [
        ("admin", "admin123", "admin@example.com", "Admin"),
        ("staff", "staff123", "staff@example.com", "Legal Staff"),
        ("viewer", "viewer123", "viewer@example.com", "Viewer"),
    ]
    for username, password, email, role in users:
        exists = conn.execute("SELECT user_id FROM users WHERE username=?", (username,)).fetchone()
        if not exists:
            conn.execute(
                "INSERT INTO users(username,password,email,role,created_at) VALUES(?,?,?,?,?)",
                (username, generate_password_hash(password), email, role,
                 datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            )
    conn.commit()
    conn.close()


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def extract_text(path, extension):
    try:
        if extension == "txt":
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                return f.read()

        if extension == "pdf":
            from PyPDF2 import PdfReader
            reader = PdfReader(path)
            return "\n".join((page.extract_text() or "") for page in reader.pages)

        if extension == "docx":
            from docx import Document
            doc = Document(path)
            return "\n".join(p.text for p in doc.paragraphs)

    except Exception as e:
        raise RuntimeError(f"Parsing failed: {e}")

    return ""


def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            flash("Please login first.", "warning")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper


def roles_required(*roles):
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if "user_id" not in session:
                return redirect(url_for("login"))
            if session.get("role") not in roles:
                flash("You do not have permission for this operation.", "danger")
                return redirect(url_for("dashboard"))
            return f(*args, **kwargs)
        return wrapper
    return decorator


@app.route("/")
def index():
    return redirect(url_for("dashboard") if "user_id" in session else url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        conn = db()
        user = conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        conn.close()

        if user and check_password_hash(user["password"], password):
            session["user_id"] = user["user_id"]
            session["username"] = user["username"]
            session["role"] = user["role"]
            flash("Login successful.", "success")
            return redirect(url_for("dashboard"))

        flash("Invalid username or password.", "danger")

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("login"))


@app.route("/dashboard")
@login_required
def dashboard():
    conn = db()
    documents = conn.execute("""
        SELECT d.*, u.username
        FROM documents d
        JOIN users u ON d.uploaded_by = u.user_id
        ORDER BY d.document_id DESC
    """).fetchall()
    conn.close()
    return render_template("dashboard.html", documents=documents)


@app.route("/upload", methods=["POST"])
@roles_required("Admin", "Legal Staff")
def upload():
    if "document" not in request.files:
        flash("No document selected.", "danger")
        return redirect(url_for("dashboard"))

    file = request.files["document"]
    if file.filename == "":
        flash("Please choose a document.", "warning")
        return redirect(url_for("dashboard"))

    if not allowed_file(file.filename):
        flash("Only PDF, DOCX and TXT files are supported.", "danger")
        return redirect(url_for("dashboard"))

    original_name = secure_filename(file.filename)
    extension = original_name.rsplit(".", 1)[1].lower()
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S%f")
    stored_name = f"{timestamp}_{original_name}"
    path = os.path.join(app.config["UPLOAD_FOLDER"], stored_name)

    try:
        file.save(path)
        text = extract_text(path, extension)
        status = "Parsed"
        doc_type = extension.upper()
    except Exception as e:
        text = ""
        status = "Failed"
        doc_type = extension.upper()
        flash(str(e), "danger")

    conn = db()
    conn.execute("""
        INSERT INTO documents
        (file_name, stored_name, file_path, uploaded_by, upload_date,
         document_type, extracted_text, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        original_name, stored_name, path, session["user_id"],
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        doc_type, text, status
    ))
    conn.commit()
    conn.close()

    if status == "Parsed":
        flash("Document uploaded and parsed successfully.", "success")
    return redirect(url_for("dashboard"))


@app.route("/document/<int:document_id>")
@login_required
def document_view(document_id):
    conn = db()
    document = conn.execute("""
        SELECT d.*, u.username FROM documents d
        JOIN users u ON d.uploaded_by=u.user_id
        WHERE d.document_id=?
    """, (document_id,)).fetchone()
    conn.close()

    if not document:
        flash("Document not found.", "danger")
        return redirect(url_for("dashboard"))
    return render_template("document.html", document=document)


@app.route("/download/<int:document_id>")
@login_required
def download(document_id):
    conn = db()
    document = conn.execute("SELECT * FROM documents WHERE document_id=?", (document_id,)).fetchone()
    conn.close()
    if not document:
        flash("Document not found.", "danger")
        return redirect(url_for("dashboard"))
    return send_from_directory(app.config["UPLOAD_FOLDER"], document["stored_name"],
                               as_attachment=True, download_name=document["file_name"])


@app.route("/admin/users")
@roles_required("Admin")
def users():
    conn = db()
    users = conn.execute("SELECT user_id,username,email,role,created_at FROM users ORDER BY user_id").fetchall()
    conn.close()
    return render_template("users.html", users=users)


@app.route("/admin/users/add", methods=["POST"])
@roles_required("Admin")
def add_user():
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")
    email = request.form.get("email", "").strip()
    role = request.form.get("role", "Viewer")

    if not username or not password or role not in {"Admin", "Legal Staff", "Viewer"}:
        flash("Enter valid user details.", "danger")
        return redirect(url_for("users"))

    conn = db()
    try:
        conn.execute(
            "INSERT INTO users(username,password,email,role,created_at) VALUES(?,?,?,?,?)",
            (username, generate_password_hash(password), email, role,
             datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        )
        conn.commit()
        flash("User created successfully.", "success")
    except sqlite3.IntegrityError:
        flash("Username already exists.", "danger")
    finally:
        conn.close()
    return redirect(url_for("users"))


if __name__ == "__main__":
    init_db()
    app.run(debug=True)
