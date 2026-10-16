# DDI-CDI Studio

DDI-CDI Studio turns a statistical data file into a [DDI-CDI 1.1beta](https://github.com/ddi-cdi/ddi-cdi/releases/tag/v1.1beta) description and lets you shape that description by hand before you download it.

Drop an SPSS (`.sav`, `.zsav`, `.por`), Stata (`.dta`), SAS (`.sas7bdat`, `.xpt`), CSV/TSV or Parquet file into the browser. The app reads the variables, labels, value labels, missing codes and data with [qsv](https://github.com/dathere/qsv) (readstat feature; Parquet through `qsv sqlp`, typed like a CSV) and opens everything in an editable workspace:

- **Metadata table.** Rename variables, edit labels, formats, types, measurement level, unit of measure, role, value labels, missing codes, variable functions and ELSST concepts.
- **Data table.** Page through the data, edit cells, add or delete rows, add variables.
- **Statistics.** Per-variable summary statistics and frequency tables, weighted or unweighted, which can be written into the output as a `StatisticsCollection` per variable with `Statistics` and `CategoryStatistics`.
- **✦ AI suggestions.** Optional: units, roles, variable functions, level of measurement and ELSST concepts are proposed by n8n workflows and reviewed before they are accepted.
- **Live output.** The DDI-CDI document regenerates on every change as JSON-LD, with changed objects highlighted. Download it as `<file>_DDICDI.jsonld`.

Under the hood it is a FastAPI backend (`ddicdi/`) and a React editor (`frontend/`), shipped together in one Docker image. The REST API is documented at `/docs` and can be used without the editor.

## Run locally with Docker

Requirements: Docker Desktop. The image targets `linux/amd64`, the same as the Azure deployment; on Apple Silicon it runs under emulation, which is slower but works.

Build the image from the repository root:

```bash
docker build --platform linux/amd64 -t ddicdi-studio .
```

Start it:

```bash
docker run --rm -p 8080:8000 ddicdi-studio
```

Open http://localhost:8080/app/ and drop a file. The API docs are at http://localhost:8080/docs. Stop the container with Ctrl+C.

Useful variations:

```bash
# Require an API key for uploads (the editor asks for it on the upload screen)
docker run --rm -p 8080:8000 -e DDI_API_KEY=secret ddicdi-studio

# Enable the ✦ AI suggestions (value is the full Authorization header for the n8n webhooks)
docker run --rm -p 8080:8000 -e DDI_N8N_BEARER_KEY='Bearer <token>' ddicdi-studio

# Run in the background and stop later
docker run -d --name ddicdi -p 8080:8000 ddicdi-studio
docker stop ddicdi && docker rm ddicdi
```

If `docker run` fails with `port is already allocated`, an earlier container is still running: `docker ps` shows it, `docker stop <name>` frees the port.

Uploads live inside the container and are deleted after six hours of inactivity (`DDI_UPLOAD_TTL_SECONDS`) or when the container restarts. An open editor tab then returns to the upload screen with a "session has expired" message.

All settings are environment variables prefixed `DDI_`; the full list with defaults is in `ddicdi/config.py`. Deployment notes are kept internally at Sikt.

## Run from source (development)

```bash
# qsv with the readstat feature: download the release zip for your platform from
# https://github.com/dathere/qsv/releases and put `qsv` in bin/
unzip qsv-23.0.1-aarch64-apple-darwin.zip qsv -d bin/ && xattr -d com.apple.quarantine bin/qsv
# User-missing codes (SPSS 99, SAS .R) are only kept in the data by a qsv newer than
# 23.0.1 (dathere/qsv#4667); until a release has it, build master:
#   cargo build --release --locked --bin qsv -F feature_capable,readstat,polars
# Older builds still work, but write those cells empty. Stata's are empty either way (qsv#4627).

uv sync                                              # Python 3.12 environment
cd frontend && npm install && npm run build && cd .. # editor -> frontend/dist
uv run uvicorn ddicdi.api.main:app --reload --port 8000
open http://localhost:8000/app/
```

Frontend with hot reload, API proxied to port 8000:

```bash
cd frontend && npm run dev     # http://localhost:5173/app/
```

Tests:

```bash
DDI_API_KEY= uv run pytest -q  # blank the key if your .env sets one
```

The tests read sample files from `test-files/` (ESS11-subset.sav, CRON3w5e01_1.csv and .dta). They are survey microdata and not part of the repository; ask the maintainer for them.

## Further reading

- `ddicdi/config.py`: all settings and their defaults.

## SHACL validation, example
```bash
shacl validate --shapes=validation/ddi-cdi.shacl.ttl --data=json-backup/climate-profile-1.1.jsonld
```
## License

Apache License 2.0, see [LICENSE](LICENSE) and [NOTICE](NOTICE).
