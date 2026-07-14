# Knowledge MCP Kubernetes handoff

Date: 2026-07-14

Repository: `C:\Local Files\Repositories\Sky Haven\infra-homelab-config`

## Objective

Finish the GitOps deployment of the repository's `services/knowledge-mcp` service from a
machine with working SSH/Kubernetes access. Generate and seal its bearer token, validate the
complete manifests, and - only if the user explicitly asks - commit, push, deploy, and run live
connection tests.

## Work completed

The working tree contains a new Argo CD Application at
`kubernetes/argocd-apps/app-knowledge-mcp.yaml` and a new
`kubernetes/apps/knowledge-mcp/` directory containing the Kustomization, PVC, Deployment,
Service, and TLS Ingress. Review the actual files/diff instead of relying on duplicated YAML in
this handoff.

The Deployment:

- Uses the anonymously pullable image pinned to
  `ghcr.io/skyhaven-ltd/infra-homelab-config/knowledge-mcp@sha256:7aeea5d898c646bdd1b6c8ceada586826d936d2c5f412fa6357dc6ce9e7a6621`.
- Persists `/data/knowledge.db` on a 1 GiB RWO PVC.
- Requires Secret `knowledge-mcp-env` containing `KNOWLEDGE_MCP_BEARER_TOKEN`.
- Uses non-root UID/GID 10001, a read-only root filesystem, dropped capabilities, no service
  account token, and explicit resource/probe settings.
- Exposes `https://knowledge.lab.skyhaven.ltd/mcp`; the existing Pi-hole wildcard for
  `lab.skyhaven.ltd` should route this name to ingress-nginx.

`services/knowledge-mcp/README.md` was updated for the Kubernetes deployment. The user asked
whether `latest` could replace the pin; the decision/recommendation was to keep the digest.
The current workflow publishes only a commit-SHA tag, and a mutable `latest` tag would neither
be deterministic nor cause Argo CD to roll the Deployment when its bytes changed.

The published GitHub Actions run was successful, including its image-publish job. Anonymous
GHCR manifest retrieval returned HTTP 200 and the digest above.

Local validation completed before the Kubernetes edits: Ruff passed, all 28 service tests
passed, and coverage was 97.03%.

## Blocking item

`kubernetes/apps/knowledge-mcp/kustomization.yaml` references `sealedsecret.yaml`, but that file
does not exist yet. Do not commit or deploy this incomplete state.

The previous machine had no kubeconfig, `kubectl`, `kubeseal`, SSH private key, or SSH agent.
The node at `192.168.1.3` also presented a changed SSH host key relative to that machine's stale
entry. Do not disable host-key checking. Use the SSH-enabled machine's trusted configuration or
verify the node identity through the Proxmox/node console.

The cluster's Sealed Secrets Helm values set `fullnameOverride: sealed-secrets-controller` in
`kubernetes/infrastructure/sealed-secrets/values.yaml`. Confirm the live controller Service name
before sealing.

## Important dirty-worktree warning

During handoff preparation, unrelated concurrent deletions appeared in the shared working tree:

- Several files under `docs/`, including `docs/versions.md`.
- The audiobookshelf, learning-review, and syncthing Kubernetes app directories.
- Their Argo CD Application manifests.

These deletions were not made as part of the Knowledge MCP task. Preserve them and ask the user
about their intent before restoring, staging, or committing them. A Knowledge MCP image row had
previously been added to `docs/versions.md`, but that file is now deleted by the concurrent
change. Start with `git status --short` and `git diff --stat`; do not assume the status captured
here remains current.

## Recommended continuation

1. Read the supplied global `AGENTS.md` instructions and inspect `git status`, the Knowledge MCP
   diff, and the unrelated deletions.
2. Establish trusted cluster access. The repository documentation expects the kubeconfig at the
   gitignored `ansible/lnsvrk8s01-kubeconfig`; the documented node is
   `ops@192.168.1.3` using the Proxmox SSH key.
3. Confirm the live Sealed Secrets controller and obtain its public certificate with the trusted
   kubeconfig. Use `kubeseal` 0.38.4, matching `docs/versions.md` if that file still exists in the
   resolved tree.
4. Generate a cryptographically random bearer token without writing it to Git, shell history,
   logs, or this handoff. Create a client-side Kubernetes Secret named `knowledge-mcp-env` in
   namespace `knowledge-mcp`, with key `KNOWLEDGE_MCP_BEARER_TOKEN`, and pipe it directly into
   `kubeseal`. Write only the resulting SealedSecret ciphertext to
   `kubernetes/apps/knowledge-mcp/sealedsecret.yaml`. Ensure the sealed scope matches the exact
   name and namespace. Specify `--controller-name sealed-secrets-controller` if that is the live
   Service name.
5. Give the user a secure way to set the same plaintext as `KNOWLEDGE_MCP_TOKEN` on client
   machines. Never print or commit the token.
6. Render the app with `kubectl kustomize kubernetes/apps/knowledge-mcp`, run schema validation if
   available, run `git diff --check`, and rerun the service Ruff/tests. Review security contexts,
   image pin, probe Host headers, namespace/name consistency, and the required Secret reference.
7. Resolve the unrelated dirty-tree changes with the user before any Git mutation. If asked to
   commit and push, invoke the `git-commit-push` skill; if asked to create a PR, invoke
   `create-pr`. Branch names must begin with `patch/`, `minor/`, or `major/`, and remote messages
   must not mention AI generation.
8. After an authorized merge/deployment, verify Argo sync/health, Pod/PVC/Service/Ingress status,
   `https://knowledge.lab.skyhaven.ltd/health`, an authenticated MCP `initialize`, and
   `tools/list`. Expected tools are `memory_recall`, `memory_get`, `memory_upsert`, and
   `memory_mark`.

## Suggested skills

- `git-commit-push`: only if the user asks to stage, commit, and push the completed changes.
- `create-pr`: only if the user asks to open the pull request.
- No installed skill is required for Kubernetes inspection or SealedSecret generation; follow
  the repository conventions and use the cluster tooling directly.
