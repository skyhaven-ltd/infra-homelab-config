import json
import os
import sys
import time
import urllib.error
import urllib.request

TIMEOUT_SECONDS = 900
POLL_SECONDS = 10

RADARR = "http://radarr.radarr.svc.cluster.local:7878"
SONARR = "http://sonarr.sonarr.svc.cluster.local:8989"
PROWLARR = "http://prowlarr.prowlarr.svc.cluster.local:9696"

READABLE_COLON_REPLACEMENTS = ("delete", "dash", "spaceDash", "spaceDashSpace")
FALLBACK_COLON_REPLACEMENT = "spaceDash"
MAX_PREFERRED_SIZE = 399
MAX_MAX_SIZE = 400


def call(url, api_key, method="GET", payload=None):
    body = json.dumps(payload).encode() if payload is not None else None
    headers = {"X-Api-Key": api_key}
    if body is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=30) as response:
        raw = response.read()
    return json.loads(raw) if raw else None


def has_quality_profile(url, api_key, name):
    return any(profile["name"] == name for profile in call(url, api_key))


def has_authentication(url, api_key):
    return call(url, api_key).get("authenticationMethod") not in (None, "none")


def wait_for(description, check):
    deadline = time.time() + TIMEOUT_SECONDS
    while True:
        try:
            if check():
                print(f"ready: {description}", flush=True)
                return
            reason = "condition not met yet"
        except (urllib.error.URLError, OSError, ValueError, KeyError) as error:
            reason = repr(error)
        if time.time() >= deadline:
            sys.exit(
                f"timed out after {TIMEOUT_SECONDS}s "
                f"waiting for {description}: {reason}"
            )
        print(f"waiting for {description}: {reason}", flush=True)
        time.sleep(POLL_SECONDS)


def normalise_colon_replacement(api_key):
    naming = call(f"{RADARR}/api/v3/config/naming", api_key)
    current = naming.get("colonReplacementFormat")
    if current in READABLE_COLON_REPLACEMENTS:
        return
    naming["colonReplacementFormat"] = FALLBACK_COLON_REPLACEMENT
    call(
        f"{RADARR}/api/v3/config/naming/{naming['id']}",
        api_key,
        method="PUT",
        payload=naming,
    )
    print(
        f"normalised Radarr colonReplacementFormat {current!r} -> "
        f"{FALLBACK_COLON_REPLACEMENT!r}",
        flush=True,
    )


def normalise_quality_definitions(api_key):
    for definition in call(f"{RADARR}/api/v3/qualitydefinition", api_key):
        preferred = definition.get("preferredSize") or 0
        maximum = definition.get("maxSize") or 0
        if preferred <= MAX_PREFERRED_SIZE and maximum <= MAX_MAX_SIZE:
            continue
        if preferred > MAX_PREFERRED_SIZE:
            definition["preferredSize"] = MAX_PREFERRED_SIZE
        if maximum > MAX_MAX_SIZE:
            definition["maxSize"] = MAX_MAX_SIZE
        call(
            f"{RADARR}/api/v3/qualitydefinition/{definition['id']}",
            api_key,
            method="PUT",
            payload=definition,
        )
        print(
            f"clamped Radarr quality definition {definition['quality']['name']!r} "
            f"into buildarr's readable range",
            flush=True,
        )


def main():
    radarr_key = os.environ["RADARR_API_KEY"]
    sonarr_key = os.environ["SONARR_API_KEY"]
    prowlarr_key = os.environ["PROWLARR_API_KEY"]

    wait_for(
        "Radarr quality profile 'HD Bluray + WEB'",
        lambda: has_quality_profile(
            f"{RADARR}/api/v3/qualityprofile", radarr_key, "HD Bluray + WEB"
        ),
    )
    wait_for(
        "Sonarr quality profile 'WEB-1080p'",
        lambda: has_quality_profile(
            f"{SONARR}/api/v3/qualityprofile", sonarr_key, "WEB-1080p"
        ),
    )
    wait_for(
        "Prowlarr authentication to be enabled",
        lambda: has_authentication(f"{PROWLARR}/api/v1/config/host", prowlarr_key),
    )

    normalise_colon_replacement(radarr_key)
    normalise_quality_definitions(radarr_key)


if __name__ == "__main__":
    main()
