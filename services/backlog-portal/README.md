# Backlog Portal

Backlog Portal is a mobile-first, authenticated intake application for GitHub
issues and Azure DevOps work items. A user captures a rough idea, a host-side
Codex worker refines it through the same queue pattern used by BookBuddy, and
the application presents an editable review before server-side submission.

When no item type is supplied, the portal applies deterministic keyword scoring
against the destination's supported types. A unique match is inferred; ambiguous
ideas fall back to `Task` when supported (otherwise the first configured type).
Explicit supported types always take precedence. The audit log records the
classification result and whether it was explicit, inferred, or a fallback.

## Configuration

Copy `.env.example` to `.env` for local development. `PORTAL_TARGETS` is an
explicit JSON allow-list; browser input cannot select an organisation,
repository, or project that is not configured there. Provider and worker
tokens remain server-side.

The application requires `PORTAL_USERNAME`, `PORTAL_PASSWORD`, and
`WORKER_TOKEN`. Set `GITHUB_TOKEN` and/or `AZURE_DEVOPS_TOKEN` for the enabled
destinations. GitHub credentials need issue and Projects write access. Azure
DevOps credentials need work-item read/write access only.

GitHub Project V2 targets set `project_id` to the board's GraphQL node ID. Each
target can set a `template` instruction and its own `item_types`; the worker
includes both in the refinement prompt. Azure DevOps targets use `organisation`
for the organisation name and `container` for the project name.

## Deployment

Kubernetes manifests live in `kubernetes/apps/backlog-portal`. Before Argo CD
syncs the application, create its server-side secret in the target namespace:

```bash
kubectl create namespace backlog-portal --dry-run=client -o yaml | kubectl apply -f -
kubectl create secret generic backlog-portal-env \
  --namespace backlog-portal \
  --from-literal=PORTAL_USERNAME='<username>' \
  --from-literal=PORTAL_PASSWORD='<password>' \
  --from-literal=WORKER_TOKEN='<random-worker-token>' \
  --from-literal=GITHUB_TOKEN='<fine-grained-token>' \
  --from-literal=AZURE_DEVOPS_TOKEN='<optional-pat>' \
  --dry-run=client -o yaml | kubectl apply -f -
```

Install the subscription-backed worker on the k3s host with the same worker
token and the existing Codex authentication file:

```bash
BACKLOG_PORTAL_WORKER_TOKEN='<random-worker-token>' \
CODEX_AUTH_FILE="$HOME/.codex/auth.json" \
ansible-playbook -i ansible/inventory/hosts.yml ansible/site.yml \
  --tags backlog_portal_worker
```

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
