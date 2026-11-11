# Kriyānighaṇṭu Synonym Finder

Give the app a passage (typed text, a .txt file or a PDF) and a word from it. It reads the context and returns the
best-suited Sanskrit synonym from a Neo4j graph built from the Kriyānighaṇṭu dataset, or explains why there is none.

How it works, in two pages: [docs/report.pdf](docs/report.pdf).

## Quick start: Linux server with Docker (for the college network)

Needs Docker with the Compose plugin (`docker compose version`), about 2 GB of RAM and 2 GB of disk.
No Docker? Use [Linux without Docker](#linux-without-docker-also-inside-a-container) instead.

```bash
git clone <this-repo-url> kriyanighantu && cd kriyanighantu
cp .env.example .env
nano .env                        # set NEO4J_PASSWORD (8+ characters)
docker compose up -d --build     # first start: ~1 min to build, then the graph loads itself
docker compose logs -f app       # wait for "Serving on http://0.0.0.0:5000", then Ctrl+C
```

Open `http://<server-ip>:5000` from any computer on the network (`hostname -I` shows the IP).
If it does not load from other machines, open the port: `sudo ufw allow 5000/tcp`.

| Task | Command |
|---|---|
| Stop / start | `docker compose stop` / `docker compose start` |
| Update after `git pull` | `docker compose up -d --build` |
| Reload the graph after data changes | `docker compose exec app python pipeline/load_neo4j.py` |
| Run the tests | `docker compose exec app python -m pytest -q tests` |
| Remove everything, including the database | `docker compose down -v` |
| Use another port | set `APP_PORT=8080` in `.env`, then `docker compose up -d` |

Neo4j itself is not exposed to the network. From the server, its browser is at <http://localhost:7474> (user `neo4j`,
password from `.env`). Both containers restart automatically after a reboot.

## Linux without Docker (also inside a container)

Needs only Python 3.12, `curl` and about 2 GB of disk. No root, Docker or systemd is required.

```bash
git clone <this-repo-url> kriyanighantu && cd kriyanighantu
cp .env.example .env
nano .env               # set NEO4J_PASSWORD (8+ characters)
sh setup_linux.sh       # once: Python packages in .venv/, Java 21 + Neo4j in .linux/ (~400 MB, 10-15 min)
sh serve.sh             # every time: starts Neo4j, loads the graph on first run, serves on 0.0.0.0:5000
```

Do not run `pip install -r requirements.txt` on the system Python. Debian and Ubuntu block it with
`error: externally-managed-environment`, so `setup_linux.sh` installs into `.venv/` instead.

- **Keep it running after you log out:** `nohup sh serve.sh > serve.log 2>&1 &`, or run it inside `tmux`.
- **Stop it:** `Ctrl+C` stops the app. Then `JAVA_HOME=$PWD/.linux/jdk .linux/neo4j/bin/neo4j stop` stops Neo4j.
- **Inside a container:** the app listens on port 5000 of that container. To reach it from other machines, the container
  must publish that port (for example `docker run -p 5000:5000 …`); ask whoever manages the server. Open
  `http://<server-ip>:5000`.
- **Settings:** `APP_PORT` (default 5000) and `WORKERS` (default 2) are read from `.env` or the environment. If port 5000 is taken, set e.g. `APP_PORT=5007` in `.env`.
- **Change the password later:** delete `.linux/neo4j/data`, update `.env`, and run `sh setup_linux.sh` again.

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

Use `.venv/bin/python` (Linux) or `.venv\Scripts\python` (Windows). With Docker, run `docker compose up -d --build` and
then the reload command from the table above. Restart the app afterwards so it rereads the graph.

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
| `Dockerfile`, `docker-compose.yml`, `setup_linux.sh`, `serve.sh` | Linux deployment, with or without Docker |
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
| "The database is not reachable" | Neo4j is not running or the password in `.env` is wrong. Docker: `docker compose logs neo4j`. |
| `NEO4J_PASSWORD` error from Compose | Create `.env` from `.env.example`. |
| `error: externally-managed-environment` | You ran pip on the system Python. Use `sh setup_linux.sh`, or create a venv: `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`. |
| `docker: command not found` | Use [Linux without Docker](#linux-without-docker-also-inside-a-container). |
| Changed the password after the first start | Docker: `docker compose down -v` and start again. Without Docker: delete `.linux/neo4j/data` and rerun `setup_linux.sh`. Either way the database is deleted and reloads itself. |
| Page loads on the server but not from other PCs | Open the port in the firewall, and check that both are on the same network. |
| "This PDF has no extractable text" | The PDF is scanned. Run OCR on it, or paste the text. |
| A Sanskrit word from a PDF is "not in your text" | The PDF's font does not store real Unicode. Paste the text instead. |

## Known limits

- The verb list covers अ to न only, so common verbs like वदति, पठति and भवति are absent.
- Only present-tense endings are recognised (चलन्ति → चलति), not other tenses, participles or most sandhi.
- 146 verbs have no usable meaning, and 120 shades have no English gloss.
- Context matching compares words and does not parse sentences. It has not been measured on real texts, because no
  labelled Sanskrit data exists for it.
- There is no login. Host it only on a trusted network.
