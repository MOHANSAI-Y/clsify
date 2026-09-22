# Legal Document Classification System — Modules 1 & 2

This package implements the first two modules from the supplied project:
1. Authentication & Role Management
2. Document Upload & Parsing

## Technology
- Python 3.10+
- Flask
- SQLite
- Werkzeug password hashing
- PyPDF2 for PDF text extraction
- python-docx for DOCX text extraction

## Run
1. Open a terminal in this folder.
2. Run: `pip install -r requirements.txt`
3. Run: `python app.py`
4. Open: http://127.0.0.1:5000

Demo accounts:
- Admin: admin / admin123
- Legal Staff: staff / staff123
- Viewer: viewer / viewer123

Uploaded files are stored in `uploads/` and document records are stored in `legal_documents.db`.

Supported upload formats: PDF, DOCX, TXT.
