# Kriyānighaṇṭu Synonym Finder

Give the app a passage (typed text, a .txt file or a PDF) and a word from it. It reads the context and returns the
best-suited Sanskrit synonym from a Neo4j graph built from the Kriyānighaṇṭu dataset, or explains why there is none.

How it works, in two pages: [docs/report.pdf](docs/report.pdf).

## Host it on a Linux server (college network)

Needs Python 3.12, `curl`, about 2 GB of disk and 2 GB of RAM. No root, Docker or systemd is required, so it also
works inside a container or a shared account.

```bash
git clone <this-repo-url> kriyanighantu && cd kriyanighantu
cp .env.example .env
nano .env                               # set NEO4J_PASSWORD (8+ characters); change ports if needed
sh setup_linux.sh                       # once: Python packages, Java 21 and Neo4j (~400 MB, 10-15 min)
nohup sh serve.sh > serve.log 2>&1 &    # start; keeps running after you log out
tail -f serve.log                       # wait for "Listening at: http://0.0.0.0:5006", then Ctrl+C
```

Open `http://<server-ip>:5006` from any computer on the network. `hostname -I` shows the server's IP.

| Task | Command |
|---|---|
| Stop | `sh stop.sh` (stops this app and its Neo4j only) |
| Start again, e.g. after a reboot | `nohup sh serve.sh > serve.log 2>&1 &` |
| Update after `git pull` | `sh stop.sh`, `sh setup_linux.sh`, then start again |
| See requests and errors | `tail -f serve.log` |
| Run the tests | `.venv/bin/python -m pytest -q tests` |

**Ports.** The defaults are the usual ones + 6, to avoid clashes on shared servers:

| Setting in `.env` | Default | Used for |
|---|---|---|
| `APP_PORT` | 5006 | The website, open to the network |
| `NEO4J_BOLT_PORT` | 7693 | Database connection, this machine only |
| `NEO4J_HTTP_PORT` | 7480 | Neo4j Browser at `http://localhost:7480`, this machine only |

If a port is taken, `serve.sh` says which one. Change it in `.env`, run `sh setup_linux.sh` again (it skips the
downloads), then start again. `WORKERS` (default 2) sets the number of app processes.

**Notes**

- Do not run `pip install -r requirements.txt` on the system Python. Debian and Ubuntu block it with
  `error: externally-managed-environment`, so `setup_linux.sh` installs into `.venv/` instead.
- Inside a container, `hostname -I` must show a college-network address. If it shows only `172.17.x.x`, the
  container's port must be published to the host by whoever manages it.
- Everything is installed inside the project folder (`.venv/`, `.linux/`). Deleting the folder removes it all.

## Windows (this computer)

Double-click **`start.bat`**. It starts the private Neo4j in `.neo4j\` if needed and opens <http://127.0.0.1:5000>.
To stop, press `Ctrl+C` in the app window and close the Neo4j window. This mode is reachable only from this computer.

To set it up on another Windows computer you need Python 3.12 and Java 21:

1. `python -m venv .venv` and `.venv\Scripts\python -m pip install -r requirements.txt`.
2. Extract `neo4j-community-2025.12.1-windows.zip` (from <https://dist.neo4j.org/>) to `.neo4j\dist\`. Copy its
   `conf\server-logs.xml` and `conf\user-logs.xml` to `.neo4j\conf\` along with a `neo4j.conf` that sets the data, logs
   and run folders inside `.neo4j\`, Bolt on `127.0.0.1:7688` and HTTP on `127.0.0.1:7475`.
3. Copy `.env.example` to `.env` and set the password. Then set it in Neo4j, with `NEO4J_HOME` and `NEO4J_CONF` set as
   in `start_neo4j.ps1`: `& "$env:NEO4J_HOME\bin\neo4j-admin.bat" dbms set-initial-password <password>`.
4. Run `.\start_neo4j.ps1`. In a second window run `.venv\Scripts\python pipeline\build_graph.py` and then
   `.venv\Scripts\python pipeline\load_neo4j.py`. From then on use `start.bat`.

## Using the app

1. Choose **Statement**, **Text file** (.txt, UTF-8) or **PDF** (with a text layer, not scanned).
2. Paste the text or choose the file, and type a word that appears in it.
3. Click **Find synonym**. You get the meaning chosen from the context, the best synonym and alternatives. If no
   synonym can be given, the app says why (word not in the text, verb not in the dataset, a noun, no meaning recorded,
   or no other verb with that meaning) and suggests close spellings.

Ready-made inputs are in `test_data/`: 20 paragraphs (`cases/T01.txt`…, five as `pdf/`), listed with the expected
meaning in `cases.json`. `python test_data/run_cases.py` scores them all and writes `test_data/results.md`.

## After changing the data or `pipeline/lexicon.py`

```bash
python pipeline/build_graph.py      # dataset/data/*.xlsx -> output/graph.json and output/report.json
python -m pytest -q tests
python pipeline/load_neo4j.py       # replaces everything in the database
```

Use `.venv/bin/python` (Linux, with Neo4j running) or `.venv\Scripts\python` (Windows). Restart the app afterwards
so it rereads the graph.

## Project layout

| Path | Contents |
|---|---|
| `dataset/data/` | The three source spreadsheets |
| `misc/` | The proposed schema (PDF) |
| `pipeline/` | `build_graph.py` (relations), `lexicon.py` (curated Sanskrit rules), `load_neo4j.py`, `settings.py` |
| `text_synonyms.py`, `synonyms.py` | Context reading and synonym ranking; both also work from the command line (`--help`) |
| `webapp/` | Flask app (`app.py`, `finder.py`) and its page |
| `tests/`, `test_data/` | Unit tests; generated test paragraphs |
| `docs/` | The report (`report.html` → `report.pdf` via `make_report.py`) |
| `setup_linux.sh`, `serve.sh`, `stop.sh` | Linux server: install, start, stop |
| `start.bat`, `start.ps1`, `start_neo4j.ps1` | Windows start |

## Graph model

```
(:Verb)-[:HAS_SHADE {id, confidence, sources}]->(:Shade)<-[:HAS_SHADE]-(:Sense)
(:Verb)-[:LISTED_UNDER]->(:LookUp)-[:DENOTES]->(:Shade)
(:Verb)-[:FROM_ROOT]->(:Root)      (:Verb)-[:SEE_ALSO]->(:Verb)
```

A **Sense** is one meaning (गति), a **Shade** one English gloss block under it, and a **LookUp** the original dataset
label. Two verbs are synonyms in a context when they share a Shade. Details are in the report.

## Troubleshooting

| What you see | What to do |
|---|---|
| "The database is not reachable" | Neo4j is not running or the password in `.env` is wrong. Restart with `sh stop.sh`, then `serve.sh`. Neo4j's own log is `.linux/neo4j/logs/neo4j.log`. |
| "Port … is already in use" | Another program has it. Pick a free port in `.env` and run `sh setup_linux.sh` again. |
| "Failed to start Neo4j" / `PortBindException` | Same as above, for `NEO4J_BOLT_PORT` or `NEO4J_HTTP_PORT`. |
| `error: externally-managed-environment` | You ran pip on the system Python. Use `sh setup_linux.sh` instead. |
| Changed the password after the first start | `sh stop.sh`, delete `.linux/neo4j/data`, run `sh setup_linux.sh`, start again. The graph reloads itself. |
| Page loads on the server but not from other PCs | The server's firewall blocks the port (admin: `sudo ufw allow 5006/tcp`), or the PC is on another network. |
| "This PDF has no extractable text" | The PDF is scanned. Run OCR on it, or paste the text. |
| A Sanskrit word from a PDF is "not in your text" | The PDF's font does not store real Unicode. Paste the text instead. |

## Known limits

- The verb list covers अ to न only, so common verbs like वदति, पठति and भवति are absent.
- Only present-tense endings are recognised (चलन्ति → चलति), not other tenses, participles or most sandhi.
- 146 verbs have no usable meaning, and 120 shades have no English gloss.
- Context matching compares words and does not parse sentences. It has not been measured on real texts, because no
  labelled Sanskrit data exists for it.
- There is no login. Host it only on a trusted network.
