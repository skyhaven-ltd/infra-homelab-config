import json
import os
import pathlib
import sys
import urllib.error
import urllib.parse
import urllib.request

import yaml

BAZARR = "http://bazarr.bazarr.svc.cluster.local:6767/api"
CONFIG = pathlib.Path("/config/config/config.yaml")


def request(path, api_key, payload=None):
    body = urllib.parse.urlencode(payload, doseq=True).encode() if payload else None
    req = urllib.request.Request(
        f"{BAZARR}/{path}", data=body, headers={"X-API-KEY": api_key}
    )
    with urllib.request.urlopen(req, timeout=120) as response:
        raw = response.read()
    return json.loads(raw) if raw else None


def reconcile(api_key):
    profiles = request("system/languages/profiles", api_key)
    english = next((p for p in profiles if p["name"] == "English"), None)
    if english is None:
        english = {"profileId": max((p["profileId"] for p in profiles), default=0) + 1}
        profiles.append(english)
    english.update(
        name="English",
        cutoff=1,
        items=[
            {
                "id": 1,
                "language": "en",
                "hi": "False",
                "forced": "False",
                "audio_exclude": "False",
            }
        ],
        mustContain=[],
        mustNotContain=[],
        originalFormat=False,
    )
    languages = request("system/languages", api_key)
    enabled = sorted({"en"} | {x["code2"] for x in languages if x["enabled"]})
    settings = request("system/settings", api_key)
    payload = {
        "languages-enabled": enabled,
        "languages-profiles": json.dumps(profiles),
        "settings-general-serie_default_enabled": "true",
        "settings-general-serie_default_profile": english["profileId"],
        "settings-general-movie_default_enabled": "true",
        "settings-general-movie_default_profile": english["profileId"],
        "settings-general-single_language": "false",
        "settings-general-subfolder": "current",
    }
    if not settings["general"]["enabled_providers"]:
        payload["settings-general-enabled_providers"] = ["tvsubtitles", "yifysubtitles"]
    request("system/settings", api_key, payload)
    for kind, port in (("sonarr", 8989), ("radarr", 7878)):
        request(
            "system/settings",
            api_key,
            {
                f"settings-general-use_{kind}": "true",
                f"settings-{kind}-ip": f"{kind}.{kind}.svc.cluster.local",
                f"settings-{kind}-port": port,
                f"settings-{kind}-base_url": "/",
                f"settings-{kind}-ssl": "false",
                f"settings-{kind}-only_monitored": "false",
                f"settings-{kind}-apikey": os.environ[f"{kind.upper()}_API_KEY"],
            },
        )
    for path, field, parameter in (
        ("series", "sonarrSeriesId", "seriesid"),
        ("movies", "radarrId", "radarrid"),
    ):
        items = request(f"{path}?length=-1", api_key)["data"]
        for item in items:
            if item["profileId"] is None:
                request(
                    path,
                    api_key,
                    {
                        parameter: item[field],
                        "profileid": english["profileId"],
                    },
                )
    print("English subtitles configured for new media and unassigned existing media.")


if __name__ == "__main__":
    try:
        reconcile(yaml.safe_load(CONFIG.read_text())["auth"]["apikey"])
    except urllib.error.HTTPError as error:
        sys.exit(f"Bazarr settings request failed: HTTP {error.code}")
