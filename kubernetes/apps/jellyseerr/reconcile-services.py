import json
import os
import pathlib
import sys
import urllib.error
import urllib.request

SETTINGS_PATH = pathlib.Path("/app/config/settings.json")
JELLYSEERR = "http://jellyseerr.jellyseerr.svc.cluster.local:5055"

SERVICES = [
    {
        "kind": "radarr",
        "name": "Radarr",
        "url": "http://radarr.radarr.svc.cluster.local:7878",
        "profile_path": "/api/v3/qualityprofile",
        "api_key_env": "RADARR_API_KEY",
        "hostname": "radarr.radarr.svc.cluster.local",
        "port": 7878,
        "quality_profile": "HD Bluray + WEB",
        "root_folder": "/data/library/movies",
    },
    {
        "kind": "sonarr",
        "name": "Sonarr",
        "url": "http://sonarr.sonarr.svc.cluster.local:8989",
        "profile_path": "/api/v3/qualityprofile",
        "api_key_env": "SONARR_API_KEY",
        "hostname": "sonarr.sonarr.svc.cluster.local",
        "port": 8989,
        "quality_profile": "WEB-1080p",
        "root_folder": "/data/library/tv",
    },
]


def request(url, api_key, method="GET", payload=None):
    body = json.dumps(payload).encode() if payload is not None else None
    headers = {"X-Api-Key": api_key}
    if body is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=30) as response:
        raw = response.read()
    return json.loads(raw) if raw else None


def jellyseerr_api_key():
    if not SETTINGS_PATH.exists():
        sys.exit(f"{SETTINGS_PATH} does not exist yet; Jellyseerr has not started")
    settings = json.loads(SETTINGS_PATH.read_text())
    api_key = settings.get("main", {}).get("apiKey")
    if not api_key:
        sys.exit("Jellyseerr has not generated an API key yet")
    return api_key


def require_initialized(api_key):
    status = request(f"{JELLYSEERR}/api/v1/settings/public", api_key)
    if not status.get("initialized"):
        sys.exit(
            "Jellyseerr has not completed its first-run setup. "
            "Sign in once at https://jellyseerr.lab.skyhaven.ltd and finish "
            "the wizard, then re-run this job."
        )


def resolve_profile_id(service, arr_key):
    profiles = request(f"{service['url']}{service['profile_path']}", arr_key)
    for profile in profiles:
        if profile["name"] == service["quality_profile"]:
            return profile["id"]
    found = ", ".join(repr(profile["name"]) for profile in profiles)
    sys.exit(
        f"{service['name']} has no quality profile named "
        f"{service['quality_profile']!r} (found: {found})"
    )


def desired_payload(service, arr_key, profile_id):
    payload = {
        "name": service["name"],
        "hostname": service["hostname"],
        "port": service["port"],
        "apiKey": arr_key,
        "useSsl": False,
        "baseUrl": "",
        "activeProfileId": profile_id,
        "activeProfileName": service["quality_profile"],
        "activeDirectory": service["root_folder"],
        "is4k": False,
        "isDefault": True,
        "externalUrl": f"https://{service['kind']}.lab.skyhaven.ltd",
        "syncEnabled": True,
        "preventSearch": False,
        "tags": [],
    }
    if service["kind"] == "radarr":
        payload["minimumAvailability"] = "released"
    else:
        payload["enableSeasonFolders"] = True
    return payload


def reconcile(service, jellyseerr_key):
    arr_key = os.environ[service["api_key_env"]]
    profile_id = resolve_profile_id(service, arr_key)
    payload = desired_payload(service, arr_key, profile_id)

    existing = (
        request(f"{JELLYSEERR}/api/v1/settings/{service['kind']}", jellyseerr_key) or []
    )
    current = next((item for item in existing if item["name"] == service["name"]), None)

    if current is None:
        request(
            f"{JELLYSEERR}/api/v1/settings/{service['kind']}",
            jellyseerr_key,
            method="POST",
            payload=payload,
        )
        print(f"created {service['name']} service in Jellyseerr", flush=True)
        return

    if all(current.get(key) == value for key, value in payload.items()):
        print(f"{service['name']} service already matches", flush=True)
        return

    request(
        f"{JELLYSEERR}/api/v1/settings/{service['kind']}/{current['id']}",
        jellyseerr_key,
        method="PUT",
        payload=payload,
    )
    print(f"updated {service['name']} service in Jellyseerr", flush=True)


def main():
    jellyseerr_key = jellyseerr_api_key()
    require_initialized(jellyseerr_key)
    for service in SERVICES:
        reconcile(service, jellyseerr_key)


if __name__ == "__main__":
    try:
        main()
    except urllib.error.HTTPError as error:
        body = error.read().decode(errors="replace")
        sys.exit(f"{error.code} {error.reason} from {error.url}: {body}")
