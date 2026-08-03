# Backlog Portal

Backlog Portal is a mobile-first, authenticated intake application for GitHub
issues and Azure DevOps work items. A user captures a rough idea, a host-side
Codex worker refines it through the same queue pattern used by BookBuddy, and
the application presents an editable review before server-side submission.

## Configuration

Copy `.env.example` to `.env` for local development. `PORTAL_TARGETS` is an
explicit JSON allow-list; browser input cannot select an organisation,
repository, or project that is not configured there. Provider and worker
tokens remain server-side.

The application requires `PORTAL_USERNAME`, `PORTAL_PASSWORD`, and
`WORKER_TOKEN`. Set `GITHUB_TOKEN` and/or `AZURE_DEVOPS_TOKEN` for the enabled
destinations. GitHub credentials need issue write access only. Azure DevOps
credentials need work-item read/write access only.

## Development

```bash
python -m pip install -r requirements-dev.txt
uvicorn app.main:app --reload
```

Run the host-side worker from a machine with an authenticated Codex CLI:

```bash
WORKER_TOKEN=... python scripts/process_jobs.py \
  --base-url http://127.0.0.1:8080
```

## Validation

```bash
python -m ruff check app tests scripts
python -m ruff format --check app tests scripts
python -m pytest
docker build -t backlog-portal:local .
```
