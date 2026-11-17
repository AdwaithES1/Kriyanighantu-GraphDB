"""Kriyanighantu: one web app for the data-entry portal, the synonym finder and the context-aware finder.

Development: python webapp/app.py [--open]          (APP_HOST / APP_PORT, default 127.0.0.1:5010)
Production:  gunicorn --chdir webapp app:app         (see serve.sh; one worker, several threads)

Everything is stored in Neo4j. Portal edits change the entry nodes, and the synonym graph is
rebuilt from them in the background a moment later.
"""
import functools
import hmac
import secrets
import sys
import tempfile
import threading
import time
import unicodedata
import webbrowser
from pathlib import Path

from flask import Flask, jsonify, redirect, render_template, request, session as login, url_for
from neo4j import GraphDatabase
from neo4j.exceptions import DriverError, Neo4jError

PROJECT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(PROJECT), str(PROJECT / "pipeline")]

import entries  # noqa: E402
import load_neo4j  # noqa: E402
import settings  # noqa: E402
from text_synonyms import Lexicon, read_file  # noqa: E402
import finder  # noqa: E402
import thesaurus  # noqa: E402

HOST = settings.value("APP_HOST", "127.0.0.1")
PORT = int(settings.value("APP_PORT", "5010"))
ADMIN_USERNAME = settings.value("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = settings.value("ADMIN_PASSWORD", "admin")
EXTENSIONS = {"text": ".txt", "pdf": ".pdf"}
REBUILD_DELAY = 2  # seconds of quiet after the last portal edit before the graph is rebuilt

app = Flask(__name__)
app.config.update(MAX_CONTENT_LENGTH=16 * 1024 * 1024, SESSION_COOKIE_SAMESITE="Lax", SESSION_COOKIE_HTTPONLY=True,
                  SECRET_KEY=settings.value("SECRET_KEY") or secrets.token_hex(32))

uri, auth, database = settings.connection()
driver = GraphDatabase.driver(uri, auth=auth, notifications_min_severity="OFF")


def db():
    return driver.session(database=database)


def unreachable():
    return finder.explained("The database is not reachable",
                            "Neo4j does not seem to be running. Start the app again with serve.sh or start.bat.")


# ---------------------------------------------------------------- lexicon cache, tied to the graph version
_lexicon, _lexicon_version, _lexicon_lock = None, None, threading.Lock()


def lexicon(session):
    """The in-memory graph for the context finder, reloaded whenever the graph has been rebuilt."""
    global _lexicon, _lexicon_version
    version = load_neo4j.graph_version(session)
    with _lexicon_lock:
        if _lexicon is None or version != _lexicon_version:
            _lexicon, _lexicon_version = Lexicon(session), version
        return _lexicon


# ---------------------------------------------------------------- background graph rebuild after portal edits
_rebuild = {"pending": threading.Event(), "running": False, "error": None, "thread": None, "lock": threading.Lock()}


def _rebuild_loop():
    while True:
        _rebuild["pending"].wait()
        time.sleep(REBUILD_DELAY)  # let a burst of edits finish
        _rebuild["pending"].clear()
        _rebuild["running"] = True
        try:
            with db() as session:
                entries.rebuild_graph(session)
            _rebuild["error"] = None
        except Exception as error:  # keep serving the previous graph; the portal shows the reason
            _rebuild["error"] = f"{type(error).__name__}: {error}"[:300]
        finally:
            _rebuild["running"] = False


def request_rebuild():
    with _rebuild["lock"]:
        if _rebuild["thread"] is None:
            _rebuild["thread"] = threading.Thread(target=_rebuild_loop, daemon=True)
            _rebuild["thread"].start()
    _rebuild["pending"].set()


def rebuild_status():
    busy = _rebuild["pending"].is_set() or _rebuild["running"]
    return {"state": "updating" if busy else "error" if _rebuild["error"] else "ready", "error": _rebuild["error"]}


# ---------------------------------------------------------------- pages
@app.get("/")
def home():
    return render_template("home.html", page="home")


@app.get("/synonyms")
def synonyms_page():
    return render_template("synonyms.html", page="synonyms")


@app.get("/context")
def context_page():
    return render_template("context.html", page="context")


def safe_next(target):
    return target if target and target.startswith("/") and not target.startswith("//") else url_for("portal_page")


@app.route("/login", methods=["GET", "POST"])
def login_page():
    target = safe_next(request.values.get("next"))
    if login.get("admin"):
        return redirect(target)
    error = None
    if request.method == "POST":
        user_ok = hmac.compare_digest(request.form.get("username", "").encode(), ADMIN_USERNAME.encode())
        pass_ok = hmac.compare_digest(request.form.get("password", "").encode(), ADMIN_PASSWORD.encode())
        if user_ok and pass_ok:
            login.clear()
            login["admin"] = True
            return redirect(target)
        error = "Invalid username or password."
    return render_template("login.html", page="portal", error=error, next=target)


@app.post("/logout")
def logout():
    login.clear()
    return redirect(url_for("home"))


def admin_only(view):
    @functools.wraps(view)
    def guarded(*args, **kwargs):
        if not login.get("admin"):
            if request.path.startswith("/api/"):
                return jsonify(error="Please log in again."), 401
            return redirect(url_for("login_page", next=request.path))
        return view(*args, **kwargs)
    return guarded


@app.get("/data-entry")
@admin_only
def portal_page():
    return render_template("portal.html", page="portal", kinds=entries.KINDS)


# ---------------------------------------------------------------- data-entry API (admin only)
def json_body():
    """The JSON object sent by the portal. Requiring JSON also blocks cross-site form posts."""
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else None


@app.get("/api/entries/<kind>")
@admin_only
def list_entries(kind):
    if kind not in entries.KINDS:
        return jsonify(error="Unknown entry type."), 404
    with db() as session:
        return jsonify(entries.search(session, kind, request.args.get("q", "")))


@app.post("/api/entries/<kind>")
@admin_only
def add_entry(kind):
    data = json_body()
    if kind not in entries.KINDS or data is None:
        return jsonify(error="Bad request."), 400
    try:
        with db() as session:
            saved = entries.add(session, kind, data)
    except entries.Invalid as problem:
        return jsonify(error=str(problem)), 400
    request_rebuild()
    return jsonify(saved), 201


@app.route("/api/entries/<kind>/<entry_id>", methods=["PUT", "DELETE"])
@admin_only
def change_entry(kind, entry_id):
    if kind not in entries.KINDS:
        return jsonify(error="Unknown entry type."), 404
    try:
        with db() as session:
            if request.method == "DELETE":
                done = entries.delete(session, kind, entry_id)
            else:
                data = json_body()
                if data is None:
                    return jsonify(error="Bad request."), 400
                done = entries.update(session, kind, entry_id, data)
    except entries.Invalid as problem:
        return jsonify(error=str(problem)), 400
    if not done:
        return jsonify(error="Entry not found. It may have been deleted."), 404
    request_rebuild()
    return jsonify(done if isinstance(done, dict) else {"deleted": True})


@app.get("/api/graph-status")
@admin_only
def graph_status():
    return jsonify(rebuild_status())


# ---------------------------------------------------------------- synonym finder API (public, read-only)
@app.get("/api/thesaurus/search")
def thesaurus_search():
    by = request.args.get("by", "verb")
    if by not in thesaurus.SEARCH:
        return jsonify(error="Unknown search type."), 400
    query = unicodedata.normalize("NFC", request.args.get("query", ""))[:200]
    with db() as session:
        return jsonify(results=thesaurus.search(session, by, query))


@app.get("/api/thesaurus/detail")
def thesaurus_detail():
    by = request.args.get("by", "verb")
    if by not in thesaurus.DETAIL:
        return jsonify(error="Unknown detail type."), 400
    key = unicodedata.normalize("NFC", request.args.get("key", "").strip())[:500]
    with db() as session:
        detail = thesaurus.DETAIL[by](session, key) if key else None
    return (jsonify(detail), 200) if detail else (jsonify(error="Not found in the dataset."), 404)


# ---------------------------------------------------------------- context-aware finder API (public)
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


TASKS = {"in_context": finder.find, "in_text": finder.find_in_text}


@app.post("/api/find")
def find():
    task = TASKS.get(request.form.get("task", "in_context"))
    if task is None:
        return jsonify(finder.explained("Unknown finder", "Choose one of the two finders at the top of the page."))
    word = unicodedata.normalize("NFC", request.form.get("word", "").strip())
    if not word:
        return jsonify(finder.explained("No word given", "Enter the word you want a synonym for."))
    text, problem = text_from_request()
    if problem:
        return jsonify(problem)
    with db() as session:
        return jsonify(task(session, lexicon(session), text, word))


# ---------------------------------------------------------------- errors
@app.errorhandler(DriverError)
@app.errorhandler(Neo4jError)
def database_down(_):
    if request.path == "/api/find":
        return jsonify(unreachable())
    if request.path.startswith("/api/"):
        return jsonify(error="The database is not reachable. Check that Neo4j is running."), 503
    return render_template("message.html", page="", title="The database is not reachable",
                           message="Neo4j does not seem to be running. Start the app again with serve.sh or start.bat."), 503


@app.errorhandler(413)
def too_large(_):
    return jsonify(finder.explained("File too large", "Files can be up to 16 MB.")), 413


@app.errorhandler(404)
def not_found(_):
    if request.path.startswith("/api/"):
        return jsonify(error="Not found."), 404
    return render_template("message.html", page="", title="Page not found",
                           message="That page does not exist. Use the links at the top to continue."), 404


if __name__ == "__main__":
    print(f"Open http://{HOST}:{PORT}  (Ctrl+C to stop)", flush=True)
    if "--open" in sys.argv:
        threading.Timer(1.5, webbrowser.open, [f"http://{HOST}:{PORT}"]).start()
    app.run(host=HOST, port=PORT, debug=False, threaded=True)
