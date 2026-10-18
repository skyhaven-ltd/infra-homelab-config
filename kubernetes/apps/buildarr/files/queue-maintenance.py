import datetime
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request


MINIMUM_AGE = datetime.timedelta(hours=int(os.getenv("MINIMUM_AGE_HOURS", "8")))
NOW = datetime.datetime.now(datetime.timezone.utc)
SERVICES = [
    (
        "Sonarr",
        "http://sonarr.sonarr.svc.cluster.local:8989",
        "SONARR_API_KEY",
    ),
    (
        "Radarr",
        "http://radarr.radarr.svc.cluster.local:7878",
        "RADARR_API_KEY",
    ),
]


def request(base_url, api_key, path, method="GET"):
    req = urllib.request.Request(
        f"{base_url}{path}",
        headers={"X-Api-Key": api_key},
        method=method,
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        raw = response.read()
    return json.loads(raw) if raw else None


def parse_timestamp(value):
    return datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))


def is_old_enough(item):
    added = item.get("added")
    if not added:
        # Radarr can briefly return queue records without an added timestamp
        # while it is importing or removing a download. There is no safe way
        # to apply the age policy to those transient records, so leave them
        # for the next hourly run instead of failing maintenance for both apps.
        print(
            f"Skipping queue entry without an added timestamp: "
            f"{item.get('title', item.get('id', 'unknown'))!r}",
            flush=True,
        )
        return False
    return NOW - parse_timestamp(added) >= MINIMUM_AGE


def is_stalled(item):
    return (
        item.get("protocol") == "torrent"
        and item.get("trackedDownloadState") == "downloading"
        and "stalled with no connections" in item.get("errorMessage", "").lower()
    )


def message_details(item):
    return [
        message
        for group in item.get("statusMessages", [])
        for message in group.get("messages", [])
    ]


def is_already_imported(item):
    details = message_details(item)
    return (
        item.get("status") == "completed"
        and item.get("trackedDownloadState") == "importBlocked"
        and bool(details)
        and all("file already imported" in message.lower() for message in details)
    )


def queue(base_url, api_key):
    query = urllib.parse.urlencode(
        {
            "page": 1,
            "pageSize": 1000,
            "includeUnknownSeriesItems": "true",
        }
    )
    return request(base_url, api_key, f"/api/v3/queue?{query}")["records"]


def delete(service, base_url, api_key, item, blocklist, skip_redownload):
    query = urllib.parse.urlencode(
        {
            "removeFromClient": "true",
            "blocklist": str(blocklist).lower(),
            "skipRedownload": str(skip_redownload).lower(),
        }
    )
    request(base_url, api_key, f"/api/v3/queue/{item['id']}?{query}", "DELETE")
    action = "blocklisted stalled" if blocklist else "removed already-imported"
    print(f"{service}: {action} download {item['title']!r}", flush=True)


def maintain(service, base_url, api_key):
    # Sonarr represents a season torrent once per episode. Act once per
    # download ID so deleting one queue record cannot cause repeated requests.
    downloads = {}
    for item in queue(base_url, api_key):
        downloads.setdefault(item.get("downloadId") or str(item["id"]), item)

    changed = 0
    for item in downloads.values():
        if not is_old_enough(item):
            continue
        if is_stalled(item):
            delete(service, base_url, api_key, item, True, False)
            changed += 1
        elif is_already_imported(item):
            delete(service, base_url, api_key, item, False, True)
            changed += 1
    if not changed:
        print(f"{service}: no eligible queue entries", flush=True)


def main():
    for service, base_url, key_name in SERVICES:
        maintain(service, base_url, os.environ[key_name])


if __name__ == "__main__":
    try:
        main()
    except (KeyError, ValueError, urllib.error.URLError) as error:
        sys.exit(f"queue maintenance failed: {error}")
