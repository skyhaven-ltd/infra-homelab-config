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


def fetch(url, api_key):
    request = urllib.request.Request(url, headers={"X-Api-Key": api_key})
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.load(response)


def has_quality_profile(url, api_key, name):
    return any(profile["name"] == name for profile in fetch(url, api_key))


def has_authentication(url, api_key):
    return fetch(url, api_key).get("authenticationMethod") not in (None, "none")


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


if __name__ == "__main__":
    main()
