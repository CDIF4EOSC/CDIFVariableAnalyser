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

### Secrets from 1Password

Instead of typing the bearer token or API key on the command line, keep them in a [1Password Environment](https://www.1password.dev/environments/) and let the 1Password CLI hand them to Docker:

```bash
op run --environment=<environment-id> -- \
  docker run --rm -p 8080:8000 -e DDI_N8N_BEARER_KEY -e DDI_API_KEY ddicdi-studio
```

How it works:

- `op run` reads the Environment's secrets (approved with Touch ID or your 1Password password) and sets them as environment variables for the one command after `--`. They never appear in the command, your shell history or a file on disk.
- `-e DDI_N8N_BEARER_KEY` without `=value` tells Docker to copy the variable of that name from the calling environment into the container. Leave out `-e DDI_API_KEY` to run without upload authentication.
- The Environment holds `DDI_N8N_BEARER_KEY` (the full `Bearer …` header value) and optionally `DDI_API_KEY`. Its ID is shown in the 1Password app under Developer → Environments.

One-time setup: `brew install 1password-cli` (a recent version; older ones lack `--environment`), then turn on **Settings → Developer → Integrate with 1Password CLI** in the 1Password app.

Check that the secrets arrived: http://localhost:8080/api/info shows `"ai_enrichment": true` and `"authentication": "X-API-Key header"`.

The same works when running from source: `op run --environment=<environment-id> -- uv run uvicorn ddicdi.api.main:app --port 8000`. Prefer this over a 1Password-mounted `.env` file; the backend reads that file once at startup, and the mount occasionally delivers it empty, which silently turns AI suggestions and authentication off.

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

## Identifiers

Every element of a generated document, DDI-CDI or CDIF, is named `urn:uuid:<uuid>`, nested ones (names, labels, statistic values, creators) included. Two UUIDs are stored in the workspace: the document's, minted at import (the default record IRI is `urn:uuid:<it>`), and each variable's, kept when the variable is renamed. Every other UUID is derived from them (UUID v5), so the same element has the same IRI on every save and in both formats, and two uploads of one file never share one. The readable ids (`#instanceVariable-age`) are still what the generator works with; set `DDI_READABLE_IDS=true` to get them in the output instead, for teaching examples or debugging (a save to QLever always uses UUIDs). `ddicdi/cdi/ids.py` has the details.

CSV headers that are not valid variable names (`my var`, `Høyde (cm)`, `2020`) become clean ones at import (`my_var`, `Hoyde_cm`, `v2020`); the header is kept as the label.

## QLever store (Save to / Import from QLever)

With `DDI_QLEVER_URL` and `DDI_QLEVER_ACCESS_TOKEN` set, the header gets a **QLever: Check | Save | Import** group. Save writes the document's CDIF to its own named graph `urn:uuid:<uuid>` (replaced on every re-save) and an entry in the catalog graph `urn:cdi-studio:catalog`; Import lists the saved documents; **Open** brings one back into the editor as a metadata-only session (no data rows; the output keeps the source's record count, and the statistics the document was saved with stand in for computed ones until the session has rows, in the output and on the Statistics tab, see `ddicdi/saved_statistics.py`), and View / download read it back as JSON-LD or Turtle. The session keeps the document's UUID, so its next save replaces the same graph. CDIF is a lossy projection of DDI-CDI: missing-value ranges come back as single labelled codes, concept labels do not come back, statistics come back rounded at about the 12th significant digit, and keywords, places and contributors come back sorted; `ddicdi/cdif/reverse.py` lists it all and `tests/test_open_from_qlever.py` pins it down. The graph is the document's UUID; a workspace from before UUIDs gets its old `urn:ddi-cdi:<file>` record IRI replaced on the first save, and a record IRI you typed yourself is kept. **Check** validates the CDIF against the CDIF SHACL shapes without saving (`POST /api/files/{id}/cdif/check`, no QLever needed), and every save runs the same check. It also lists the required fields of the Dataset tab that are empty (title, licence, date modified): the converter writes a stand-in for them, which SHACL accepts. Problems are shown but do not stop a save. The shapes (`CDIF-Complete-Shapes.ttl`, Apache-2.0) are vendored in `ddicdi/cdif/shapes/`, so the Docker image has them; `DDI_CDIF_SHACL_SHAPES` points at another file. The deployment and the design are in the QLever-deployment repository.

For development, run QLever locally with the deployment's Qleverfile (needs the `qlever` CLI ≥ 0.6, `pipx install qlever`):

```bash
mkdir ~/dev/qlever-cdif-local && cd ~/dev/qlever-cdif-local
cp ../QLever-deployment/vm/seed.nq .
sed -e 's|__ACCESS_TOKEN__|local-dev-token|' -e 's|__PORT__|7011|' \
    -e "s|__IMAGE__|$(sed -n 's/.*QLEVER_IMAGE:=\([^}]*\)}.*/\1/p' ../QLever-deployment/config.env)|" \
    ../QLever-deployment/vm/Qleverfile.template > Qleverfile
qlever index && qlever start

# in this repo
DDI_QLEVER_URL=http://localhost:7011 DDI_QLEVER_ACCESS_TOKEN=local-dev-token uv run uvicorn ddicdi.api.main:app --port 8011
# round-trip tests against it (they skip without these variables)
DDI_TEST_QLEVER_URL=http://localhost:7011 DDI_TEST_QLEVER_ACCESS_TOKEN=local-dev-token uv run pytest tests/test_qlever.py
```

The Docker image reaches it as `DDI_QLEVER_URL=http://host.docker.internal:7011`; inside a container, `localhost` is the container itself.

To empty the local store again: the index holds only the catalog seed, and every save is an update kept in `cdif.update-triples` and replayed at start, so delete that file while QLever is stopped:

```bash
cd ~/dev/qlever-cdif-local
qlever stop
rm cdif.update-triples
qlever start
```

This does not work once `qlever rebuild-index` has folded the saves into the index; then rebuild from the seed with `qlever index`. On the shared Azure instance, "Reset Updates" in the QLever UI has the same effect for everyone: it removes every saved document.

## Further reading

- `ddicdi/config.py`: all settings and their defaults.

## SHACL validation, example
```bash
shacl validate --shapes=validation/ddi-cdi.shacl.ttl --data=json-backup/climate-profile-1.1.jsonld
```
## License

Apache License 2.0, see [LICENSE](LICENSE) and [NOTICE](NOTICE).
