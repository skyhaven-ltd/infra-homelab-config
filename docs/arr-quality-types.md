# ARR quality types

Sonarr and Radarr use **quality** to describe a combination of video resolution
and source. A release name contains other properties, such as codec, colour
depth, audio format, release group, and language, but those are separate from
the ARR quality.

For example, in `1080p WEB-DL x265 10-bit Atmos`:

- `1080p` is the resolution;
- `WEB-DL` is the source;
- `x265` is the video codec;
- `10-bit` is the colour depth; and
- `Atmos` is the audio format.

Recyclarr manages which combinations are accepted and how releases are scored.
Buildarr manages the minimum, preferred, and maximum size allowed for each
quality. Jellyseerr assigns the resulting profiles to new requests.

## Resolutions

| Resolution | Common dimensions | Use |
| --- | --- | --- |
| 720p | 1280 x 720 | Smaller fallback when a suitable 1080p release is unavailable. |
| 1080p | 1920 x 1080 | Default target for this stack and the best balance for the current 1 TB disk. |
| 2160p / 4K | 3840 x 2160 | Higher detail, but substantially larger and sometimes harder to direct-play. |

Resolution alone does not determine visual quality. A well-encoded 1080p
WEB-DL can look better than a heavily compressed 2160p release.

## Sources

| ARR quality | Meaning | Practical trade-off |
| --- | --- | --- |
| HDTV | Captured from a television broadcast. | Usually relatively small, but may contain channel logos, edits, or broadcast artefacts. |
| WEBRip | Re-encoded from video captured from a streaming service. | Generally good quality, but the extra encode can lose detail compared with WEB-DL. |
| WEB-DL | Video obtained directly from a streaming service without an additional lossy capture encode. | Usually the best balance of quality, compatibility, and size for Plex. |
| Bluray | An encoded release sourced from a Blu-ray disc. | Can exceed WEB quality, particularly at higher bitrates, but normally uses more space. |
| Remux | Original video and audio streams copied from a disc into another container without re-encoding. | Near-source quality, but often tens of gigabytes per film or season. |
| BR-DISK | A complete or near-complete Blu-ray disc structure. | Very large and less convenient for normal Plex playback than a single media file. |
| Raw-HD | Uncompressed or unusually high-bitrate HD material. | Rare, inefficient for this stack, and potentially extremely large. |

`WEB-DL` and `WEBRip` are not streaming protocols. They describe how the release
was produced before it was published by an indexer.

## Codecs and other release properties

Codecs are evaluated separately using custom formats and release scoring:

| Property | Meaning |
| --- | --- |
| x264 / AVC | Older, broadly compatible codec. It normally needs more space than x265 for similar visual quality. |
| x265 / HEVC | More space-efficient codec, especially for 4K, but older clients may require Plex to transcode it. |
| AV1 | Newer, efficient codec with more limited hardware playback support. |
| 8-bit / 10-bit | Colour precision. Ten-bit encoding can reduce banding but requires compatible playback hardware. |
| AAC, AC-3, E-AC-3, DTS, TrueHD | Audio codecs with different compatibility, channel, and bitrate characteristics. |
| HDR, HDR10+, Dolby Vision | High-dynamic-range formats. They require compatible displays and clients to provide their intended benefit. |

A codec does not imply a particular resolution or source. For example, both a
720p WEBRip and a 2160p Blu-ray encode can use x265.

## Current profiles

The live profiles target 1080p and currently accept:

| Application | Profile | Accepted qualities |
| --- | --- | --- |
| Sonarr | `WEB-1080p` | `WEBRip-1080p`, `WEBDL-1080p` |
| Radarr | `HD Bluray + WEB` | `Bluray-720p`, `WEBRip-1080p`, `WEBDL-1080p`, `Bluray-1080p` |

The profile **cutoff** is the quality at which Sonarr or Radarr considers an item
good enough and stops seeking quality upgrades. Accepted qualities determine
what may be downloaded before that cutoff is reached. Custom-format scores then
rank multiple releases of an accepted quality.

The present profiles inherently reject 2160p, Remux, BR-DISK, and Raw-HD. This
comes from the selected Recyclarr profiles; there is no separate exclusion rule.

## Storage planning

File size varies with duration, bitrate, codec, audio tracks, and release group,
so resolution is not a reliable size limit. The configured MB-per-minute quality
definitions are the actual guardrails used by Sonarr and Radarr.

For the current 1 TB disk, 1080p WEB releases are the sensible default. When a
future NAS provides approximately 10 TB, retain 1080p as the general-purpose
profile and add a separate 4K profile only if selected requests justify the
additional storage and client requirements. Keeping the profiles separate lets
Jellyseerr route ordinary and 4K requests deliberately instead of silently
upgrading the entire library.

Hardlinks allow qBittorrent and the media library to reference the same imported
file without storing two copies. Disk-usage tools may count the file beneath
both directory paths even though the filesystem allocates its data blocks only
once.
