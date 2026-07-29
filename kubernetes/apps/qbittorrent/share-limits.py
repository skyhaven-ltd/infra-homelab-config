import pathlib
import sys

CONFIG_PATH = pathlib.Path("/config/qBittorrent/qBittorrent.conf")
SECTION = "[BitTorrent]"
SETTINGS = {
    "Session\\QueueingSystemEnabled": "true",
    "Session\\MaxActiveDownloads": "20",
    "Session\\MaxActiveUploads": "-1",
    "Session\\MaxActiveTorrents": "-1",
    "Session\\GlobalDLSpeedLimit": "0",
    "Session\\GlobalUPSpeedLimit": "0",
    "Session\\UseAlternativeGlobalSpeedLimit": "false",
    "Session\\BandwidthSchedulerEnabled": "false",
    "Session\\GlobalMaxRatio": "2",
    "Session\\GlobalMaxSeedingMinutes": "10080",
    "Session\\ShareLimitAction": "Stop",
}


def render_section():
    return [SECTION] + [f"{key}={value}" for key, value in SETTINGS.items()]


def patch(lines):
    changed = False
    section_start = None
    section_end = len(lines)
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped == SECTION:
            section_start = index
            continue
        if (
            section_start is not None
            and stripped.startswith("[")
            and stripped.endswith("]")
        ):
            section_end = index
            break

    if section_start is None:
        if lines and lines[-1].strip():
            lines.append("")
        return lines + render_section(), True

    body = lines[section_start + 1 : section_end]
    for key, value in SETTINGS.items():
        expected = f"{key}={value}"
        for index, line in enumerate(body):
            if line.split("=", 1)[0].strip() == key:
                if line.strip() != expected:
                    body[index] = expected
                    changed = True
                break
        else:
            body.append(expected)
            changed = True

    return lines[: section_start + 1] + body + lines[section_end:], changed


def main():
    if not CONFIG_PATH.exists():
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text("\n".join(render_section()) + "\n")
        print(f"created {CONFIG_PATH} with share limits", flush=True)
        return

    lines = CONFIG_PATH.read_text().splitlines()
    patched, changed = patch(lines)
    if not changed:
        print("share limits already applied", flush=True)
        return

    CONFIG_PATH.write_text("\n".join(patched) + "\n")
    print("share limits applied", flush=True)


if __name__ == "__main__":
    sys.exit(main())
