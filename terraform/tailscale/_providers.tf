# Credentials come from the environment, never Git.
# Chosen path: tailnet API access token — TAILSCALE_API_KEY (full-tailnet scope, works
# on the untagged user-owned node; disabling key expiry is a run-once apply so the
# token's 90-day expiry is immaterial after first apply).
# Alt path (not used): OAuth client via TAILSCALE_OAUTH_CLIENT_ID/_SECRET — but write
# scope is tag-restricted, so it only works once the node is tag-owned.
# tailnet defaults to the credential's own tailnet ("-").
provider "tailscale" {}
