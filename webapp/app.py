"""Web app for the Kriyanighantu synonym finder.

Development: python webapp/app.py [--open]          (APP_HOST / APP_PORT, default 127.0.0.1:5000)
Production:  gunicorn --chdir webapp app:app         (see serve.sh)
"""
import os
import sys
import tempfile
import threading
import unicodedata
import webbrowser
from pathlib import Path

from flask import Flask, jsonify, render_template, request
from neo4j import GraphDatabase
from neo4j.exceptions import DriverError, Neo4jError

PROJECT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(PROJECT), str(PROJECT / "pipeline")]

from settings import connection  # noqa: E402
from text_synonyms import Lexicon, read_file  # noqa: E402
import finder  # noqa: E402

HOST = os.environ.get("APP_HOST", "127.0.0.1")
PORT = int(os.environ.get("APP_PORT", "5000"))
EXTENSIONS = {"text": ".txt", "pdf": ".pdf"}

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024

uri, auth, database = connection()
driver = GraphDatabase.driver(uri, auth=auth)
_lexicon, _lexicon_lock = None, threading.Lock()


def lexicon(session):
    global _lexicon
    with _lexicon_lock:
        if _lexicon is None:
            _lexicon = Lexicon(session)
        return _lexicon


def text_from_request():
    """Return (text, None) or (None, explanation) for the selected input type."""
    mode = request.form.get("mode", "statement")
    if mode == "statement":
        text = request.form.get("text", "").strip()
        if not text:
            return None, finder.explained("Nothing to read", "Type or paste a statement that contains the word.")
        return unicodedata.normalize("NFC", text), None
    if mode not in EXTENSIONS:
        return None, finder.explained("Unknown input type", "Choose Statement, Text file or PDF.")
    upload = request.files.get("file")
    if upload is None or not upload.filename:
        return None, finder.explained("No file chosen", f"Choose a {EXTENSIONS[mode]} file to read.")
    if Path(upload.filename).suffix.lower() != EXTENSIONS[mode]:
        return None, finder.explained("Wrong file type", f"This input type needs a {EXTENSIONS[mode]} file.")
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / f"input{EXTENSIONS[mode]}"
        upload.save(path)
        try:
            return read_file(path), None
        except ValueError as error:
            return None, finder.explained("The file could not be read", str(error))
        except RuntimeError:
            return None, finder.explained("The file could not be read", "It appears to be damaged or is not a real PDF.")


@app.get("/")
def index():
    return render_template("index.html")


@app.post("/api/find")
def find():
    word = unicodedata.normalize("NFC", request.form.get("word", "").strip())
    if not word:
        return jsonify(finder.explained("No word given", "Enter the word you want a synonym for."))
    text, problem = text_from_request()
    if problem:
        return jsonify(problem)
    try:
        with driver.session(database=database) as session:
            return jsonify(finder.find(session, lexicon(session), text, word))
    except (DriverError, Neo4jError):
        return jsonify(finder.explained("The database is not reachable",
                                        "Neo4j does not seem to be running. Close this app and start it with start.bat."))


@app.errorhandler(413)
def too_large(_):
    return jsonify(finder.explained("File too large", "Files can be up to 16 MB.")), 413


if __name__ == "__main__":
    print(f"Open http://{HOST}:{PORT}  (Ctrl+C to stop)", flush=True)
    if "--open" in sys.argv:
        threading.Timer(1.5, webbrowser.open, [f"http://{HOST}:{PORT}"]).start()
    app.run(host=HOST, port=PORT, debug=False)
