import datetime
import json
import os
import sys
import urllib.error
import urllib.request


RADARR = "http://radarr.radarr.svc.cluster.local:7878"
SEARCH_INTERVAL = datetime.timedelta(
    hours=int(os.getenv("SEARCH_INTERVAL_HOURS", "6"))
)
MAX_MOVIES = int(os.getenv("MAX_MOVIES_PER_RUN", "20"))
NOW = datetime.datetime.now(datetime.timezone.utc)


def request(api_key, path, method="GET", payload=None):
    body = json.dumps(payload).encode() if payload is not None else None
    headers = {"X-Api-Key": api_key}
    if body is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(
        f"{RADARR}{path}", data=body, headers=headers, method=method
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        raw = response.read()
    return json.loads(raw) if raw else None


def parse_timestamp(value):
    return datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))


def eligible(movie):
    if not movie.get("monitored") or movie.get("hasFile"):
        return False
    if not movie.get("isAvailable"):
        return False
    last_search = movie.get("lastSearchTime")
    return not last_search or NOW - parse_timestamp(last_search) >= SEARCH_INTERVAL


def search_age(movie):
    last_search = movie.get("lastSearchTime")
    return parse_timestamp(last_search) if last_search else datetime.datetime.min.replace(
        tzinfo=datetime.timezone.utc
    )


def main():
    credential = os.environ["RADARR_API_KEY"]
    movies = sorted(
        (movie for movie in request(credential, "/api/v3/movie") if eligible(movie)),
        key=search_age,
    )[:MAX_MOVIES]
    if not movies:
        print("Radarr: no monitored missing movies are due for a search", flush=True)
        return

    movie_ids = [movie["id"] for movie in movies]
    command = request(
        credential,
        "/api/v3/command",
        method="POST",
        payload={"name": "MoviesSearch", "movieIds": movie_ids},
    )
    titles = ", ".join(repr(movie["title"]) for movie in movies)
    print(
        f"Radarr: queued search command {command['id']} for {len(movies)} "
        f"missing movie(s): {titles}",
        flush=True,
    )


if __name__ == "__main__":
    try:
        main()
    except (KeyError, ValueError, urllib.error.URLError) as error:
        sys.exit(f"availability search failed: {error}")
