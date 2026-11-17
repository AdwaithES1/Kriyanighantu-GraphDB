# Kriyanighantu

A thesaurus of synonymous Sanskrit verbs, in one web app on one port, backed by one Neo4j graph database.

| Part | Address | Login | What it does |
|---|---|---|---|
| Home | `/` | no | The three options below |
| Synonym Finder | `/synonyms` | no | Search by root, verb or English meaning; shows every synonym of a verb, grouped by meaning |
| Context-Aware Synonym Finder | `/context` | no | Reads a passage (typed, .txt or PDF) and picks the synonym that fits the context, or finds a word's synonyms inside the passage |
| Data Entry Portal | `/data-entry` | yes | Add, edit and delete verbs, roots and meanings |

This replaces the two earlier apps (the MongoDB data-entry portal and the MongoDB viewer). MongoDB is no longer used.
How the context finder works, in two pages: [docs/report.pdf](docs/report.pdf).

## Host it on a Linux server

Needs Python 3.12, `curl`, about 2 GB of disk and 2 GB of RAM. No root access or systemd is required, so it also
works inside a container or a shared account.

```bash
git clone <this-repo-url> kriyanighantu && cd kriyanighantu
cp .env.example .env
nano .env                               # set NEO4J_PASSWORD (8+ characters) and the portal login
sh setup_linux.sh                       # once: Python packages, Java 21 and Neo4j (~400 MB, 10-15 min)
nohup sh serve.sh > serve.log 2>&1 &    # start; keeps running after you log out
tail -f serve.log                       # wait for "Listening at: http://0.0.0.0:5010", then Ctrl+C
```

Open `http://<server-ip>:5010` from any computer on the network. `hostname -I` shows the server's IP.
On the first start the dataset is imported from the Excel files in `dataset/data/` and the graph is built.

| Task | Command |
|---|---|
| Stop | `sh stop.sh` (stops this app and its Neo4j only) |
| Start again, e.g. after a reboot | `nohup sh serve.sh > serve.log 2>&1 &` |
| Update after `git pull` | `sh stop.sh`, `sh setup_linux.sh`, then start again |
| See requests and errors | `tail -f serve.log` |
| Run the tests | `.venv/bin/python -m pytest -q tests` |

**Settings in `.env`**

| Setting | Default | Used for |
|---|---|---|
| `APP_PORT` | 5010 | The whole website, open to the network |
| `ADMIN_USERNAME`, `ADMIN_PASSWORD` | `admin`, `admin` | Login for the data-entry portal. Change them before real use. |
| `NEO4J_PASSWORD` | none | Database password, 8+ characters |
| `NEO4J_BOLT_PORT` | 7693 | Database connection, this machine only |
| `NEO4J_HTTP_PORT` | 7480 | Neo4j Browser at `http://localhost:7480`, this machine only |
| `SECRET_KEY` | random at each start | Set a long random text to keep portal logins valid across restarts |

The website and Neo4j cannot share one port number: two programs cannot listen on the same port. So only port 5010
is open to the network, and Neo4j listens on its own ports on the server itself. If a port is taken, `serve.sh` says
which one. Change it in `.env`, run `sh setup_linux.sh` again (it skips the downloads), then start again.

**Notes**

- Do not run `pip install -r requirements.txt` on the system Python. Debian and Ubuntu block it with
  `error: externally-managed-environment`, so `setup_linux.sh` installs into `.venv/` instead.
- Inside a container, `hostname -I` must show a network address. If it shows only `172.17.x.x`, the container's port
  must be published to the host by whoever manages it.
- Everything is installed inside the project folder (`.venv/`, `.linux/`). Deleting the folder removes it all,
  including the database.
- The portal login is sent in plain text over `http`. For a public address, put the app behind an `https` proxy.

## Windows

Double-click **`start.bat`**. It starts the private Neo4j in `.neo4j\` if needed, imports the dataset if the database
is empty, and opens <http://127.0.0.1:5010>. To stop, press `Ctrl+C` in the app window and close the Neo4j window.
This mode is reachable only from this computer.

To set it up on another Windows computer you need Python 3.12 and Java 21:

1. `python -m venv .venv` and `.venv\Scripts\python -m pip install -r requirements.txt`.
2. Extract `neo4j-community-2025.12.1-windows.zip` (from <https://dist.neo4j.org/>) to `.neo4j\dist\`. Copy its
   `conf\server-logs.xml` and `conf\user-logs.xml` to `.neo4j\conf\` along with a `neo4j.conf` that sets the data, logs
   and run folders inside `.neo4j\`, Bolt on `127.0.0.1:7688` and HTTP on `127.0.0.1:7475`.
3. Copy `.env.example` to `.env`, set the password and `NEO4J_URI=bolt://localhost:7688`. Then set the password in
   Neo4j, with `NEO4J_HOME` and `NEO4J_CONF` set as in `start_neo4j.ps1`:
   `& "$env:NEO4J_HOME\bin\neo4j-admin.bat" dbms set-initial-password <password>`.
4. Run `start.bat`.

## Where the data lives

Everything is in Neo4j, in two layers:

```
Entries (the dataset itself; what the portal edits and the Excel import replaces)
  (:VerbEntry   {verb, lookup, root, ganam, rootIndex, transVerb, ItAgma, derivation, example, reverseWord, seeAlso})
  (:LookupEntry {lookup, englishMeaning, reference})
  (:RootEntry   {root, ganam, rootIndex})

Synonym graph (rebuilt from the entries; what the two finders read)
  (:Verb)-[:HAS_SHADE {id, confidence, sources}]->(:Shade)<-[:HAS_SHADE]-(:Sense)
  (:Verb)-[:LISTED_UNDER]->(:LookUp)-[:DENOTES]->(:Shade)
  (:Verb)-[:FROM_ROOT]->(:Root)      (:Verb)-[:SEE_ALSO]->(:Verb)
```

The entries keep the field names of the old MongoDB collections (`verb_entries`, `look_up`, `root_entries`).
A **Sense** is one meaning (गति), a **Shade** one English gloss block under it, and a **LookUp** the dataset's label.
Two verbs are synonyms when they share a Shade.

There are two ways to change the data. Both end with the synonym graph being rebuilt, which takes a few seconds and
swaps in atomically, so the finders never see a half-built graph.

**1. The Data Entry Portal** (`/data-entry`). Each save changes the entries at once. The graph is rebuilt in the
background about two seconds after the last edit, and the portal shows "Updating the synonym graph…" until it is done.

**2. The Excel files.** This is the replacement for the old Excel → MongoDB script. Put the three files in
`dataset/data/` (or pass `--dir`) and run, with the app's Neo4j running:

```bash
.venv/bin/python pipeline/import_excel.py              # Windows: .venv\Scripts\python pipeline\import_excel.py
.venv/bin/python pipeline/import_excel.py --dir excel  # from another folder
```

It deletes all existing entries, inserts the spreadsheet rows and rebuilds the graph. Edits made in the portal since
the spreadsheets were last exported are lost, exactly as with the old script. The running app picks up the new
graph by itself. The files must be named `Look-up entry.xlsx`, `Root-Entry.xlsx` and `Verb-Entries.xlsx`.

After changing the hand-made Sanskrit rules in `pipeline/lexicon.py`, rebuild the graph from the stored entries with
`python pipeline/load_neo4j.py`.

## Using the finders

**Synonym Finder.** Choose Root, Verb or Meaning, type a word (an on-screen Devanagari keyboard is available) and open
a result. A verb shows its synonyms for each of its meanings, then its dataset details. A root shows its verbs.
A meaning shows the verbs listed under it, other verbs that share it, and related meanings.

**Context-Aware Synonym Finder.** Choose one of its two modes, then Statement, Text file (.txt, UTF-8) or PDF (with a
text layer, not scanned):

| Mode | You give | You get |
|---|---|---|
| Synonym for a word in the text | A passage and a word that appears in it | The meaning the context selects, the best synonym, and alternatives |
| Synonyms of a word, in the text | A passage and any word (a Sanskrit verb, or an English meaning such as *tremble*) | The words in the passage that are its synonyms, best first, with the shared meaning |

If no answer can be given, it says why. Example: text `मुनिः नगरे क्ष्मायते । नरः कम्पे केपते । राजा अपि एजति ।`, word `गेपते`
(not in the text). It finds केपते, क्ष्मायते and एजति, which share गेपते's meaning कम्प (trembling).

Ready-made inputs are in `test_data/`: 20 paragraphs (`cases/T01.txt`…, five as `pdf/`), listed with the expected
meaning in `cases.json`. `python test_data/run_cases.py` scores them all and writes `test_data/results.md`.

## Project layout

| Path | Contents |
|---|---|
| `dataset/data/` | The three source spreadsheets |
| `pipeline/entries.py` | The entry store in Neo4j (replaces the MongoDB collections) |
| `pipeline/import_excel.py` | Excel → Neo4j refresh (replaces the Excel → MongoDB script) |
| `pipeline/build_graph.py`, `lexicon.py` | Builds the synonym graph from entries; curated Sanskrit rules |
| `pipeline/load_neo4j.py`, `settings.py` | Writes the graph into Neo4j; reads `.env` |
| `text_synonyms.py`, `synonyms.py` | Context reading and synonym ranking; both also work from the command line (`--help`) |
| `webapp/app.py` | All pages and APIs, login, background graph rebuild |
| `webapp/thesaurus.py`, `finder.py` | Synonym Finder queries; Context Finder answers |
| `webapp/templates/`, `static/` | Pages (shared layout in `base.html`), styles, Devanagari keyboard |
| `tests/`, `test_data/` | Unit tests; generated test paragraphs |
| `docs/`, `misc/` | The report; the proposed schema |
| `setup_linux.sh`, `serve.sh`, `stop.sh` | Linux server: install, start, stop |
| `start.bat`, `start.ps1`, `start_neo4j.ps1` | Windows start |

## Troubleshooting

| What you see | What to do |
|---|---|
| "The database is not reachable" | Neo4j is not running or the password in `.env` is wrong. Restart with `sh stop.sh`, then `serve.sh`. Neo4j's own log is `.linux/neo4j/logs/neo4j.log`. |
| "Port … is already in use" | Another program has it. Pick a free port in `.env` and run `sh setup_linux.sh` again. |
| "Failed to start Neo4j" / `PortBindException` | Same as above, for `NEO4J_BOLT_PORT` or `NEO4J_HTTP_PORT`. |
| The site still opens on the old port | `.env` still has an old `APP_PORT` line. Set `APP_PORT=5010`. |
| Portal shows "Graph update failed" | The entries were saved, but the graph could not be built from them; the finders keep the previous graph. The message names the cause, usually one malformed entry. Fix it in the portal and the rebuild runs again. |
| Logged out after a restart | Expected unless `SECRET_KEY` is set in `.env`. |
| `error: externally-managed-environment` | You ran pip on the system Python. Use `sh setup_linux.sh` instead. |
| Changed the Neo4j password after the first start | `sh stop.sh`, delete `.linux/neo4j/data`, run `sh setup_linux.sh`, start again. This deletes portal edits; the dataset is re-imported from Excel. |
| Page loads on the server but not from other PCs | The server's firewall blocks the port (admin: `sudo ufw allow 5010/tcp`), or the PC is on another network. |
| "This PDF has no extractable text" | The PDF is scanned. Run OCR on it, or paste the text. |

## Known limits

- The verb list covers अ to न only, so common verbs like वदति, पठति and भवति are absent.
- The context finder recognises only present-tense endings (चलन्ति → चलति), not other tenses, participles or most sandhi.
- 146 verbs have no usable meaning, and 120 shades have no English gloss.
- Context matching compares words and does not parse sentences. It has not been measured on real texts.
- The portal has one shared admin account and keeps no history of edits. Export or back up before bulk changes.
