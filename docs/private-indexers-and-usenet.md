# Private indexers and Usenet

This guide describes legitimate ways to improve Sonarr and Radarr search
coverage. Only download material that you are legally entitled to access, and
follow each service's terms and local law.

## The practical choices

| Approach | Cost | Reliability | Ongoing responsibility |
| --- | --- | --- | --- |
| Public torrent indexers | Usually free | Variable; domains and anti-bot protection change frequently | Seed responsibly and maintain unreliable scrapers |
| Private torrent trackers | Usually account- or community-based | Generally better curation and retention | Maintain the required upload ratio and seed time |
| Usenet | Normally paid | Usually the most predictable automated option | Maintain provider and indexer subscriptions |

For the easiest dependable setup, Usenet is normally simpler than acquiring and
maintaining access to good private trackers. Private trackers can be excellent,
but joining is community-driven and their ratio rules require more care.

## Joining a private tracker

Private trackers are torrent communities whose indexes require an account. The
safe route is to join through the tracker's own published process:

1. Choose a tracker that covers the media and languages you actually need.
2. Read its official rules, privacy policy, ratio requirements, and prohibited
   client list before joining.
3. Watch its official site or community channels for an open-registration or
   application period.
4. Alternatively, accept an invitation from someone you genuinely know who is
   already a member and is permitted to invite you.
5. Never buy accounts or invitations. Account trading commonly violates tracker
   rules and exposes both the buyer and inviter to scams or bans.
6. Start slowly, seed continuously, and confirm qBittorrent's category-specific
   limits satisfy the tracker before allowing automation to grab releases.

Some communities recruit from other established trackers after a member builds
a good history. There is no legitimate universal shortcut: reputation, patience,
and compliance with each community's rules are the normal route.

The stack currently stops torrents at ratio 2 or seven days. A private tracker
may demand a longer seed time or a different ratio. Configure its Prowlarr seed
requirements and a dedicated qBittorrent category before adding it to Sonarr or
Radarr; tracker rules take precedence over the global defaults.

Once an account is available:

1. In Prowlarr, select the tracker from **Indexers**, or use **Generic Torznab**
   when the tracker supplies a compatible endpoint.
2. Enter only the credentials the tracker requires, such as an API key, passkey,
   or session cookie.
3. Test the indexer in Prowlarr.
4. Assign an appropriate sync profile and categories.
5. Confirm Prowlarr syncs it to Radarr and/or Sonarr and that their tests pass.

Store credentials in the existing secret-management path rather than committing
them to this repository.

## How Usenet differs

Usenet is not BitTorrent. Downloads come from paid news servers rather than from
other peers, so there is no seeding ratio. A working automated setup normally
needs three components:

- a **Usenet provider**, which stores article data and supplies server access;
- a **Usenet indexer**, which publishes searchable NZB metadata; and
- an **NZB download client**, commonly SABnzbd or NZBGet, which fetches and
  assembles the articles described by an NZB.

Prowlarr connects to the indexer using Newznab and synchronises it into Sonarr
and Radarr. Sonarr and Radarr send accepted NZBs to the download client, then
import the completed files in the same way they import completed torrents.

Provider retention describes how far back its stored articles extend. Completion
describes whether all parts of an upload remain available. Two providers on the
same underlying network usually add less resilience than providers on different
backbones, so do not buy several subscriptions before understanding their
coverage. A common starting point is one unlimited provider; add a small block
account on a different backbone only if real completion failures justify it.

## Easiest Usenet path for this stack

1. Select one reputable provider with TLS, suitable retention, and a nearby
   server region.
2. Select one reputable Newznab-compatible indexer that supports API access.
3. Deploy SABnzbd alongside qBittorrent with `/data/downloads` mounted using the
   same paths visible to Radarr and Sonarr.
4. Store the provider and indexer credentials in Azure Key Vault and project
   them into Kubernetes Secrets through the existing platform workflow.
5. Add the indexer to Prowlarr and allow its application sync to configure
   Radarr and Sonarr.
6. Add SABnzbd as a download client in both ARR applications, using separate
   `movies` and `tv` categories.
7. Test a permitted download end to end before enabling automatic searches.
8. Keep torrents enabled as a fallback until Usenet coverage has been observed
   long enough to make an informed decision.

## Using TorBox instead

TorBox is a hosted download service rather than an indexer. Prowlarr still finds
releases; TorBox replaces or supplements the machine that downloads and seeds
them. Its cache may make an already-known torrent immediately available, while
uncached torrents are downloaded by TorBox rather than by the homelab's public
IP and upload connection.

For Sonarr and Radarr, the supported pattern is:

1. Create a TorBox account and API key.
2. Deploy RDTClient in Kubernetes with `/data/downloads` mounted at the same path
   used by the ARR applications.
3. Configure RDTClient's TorBox provider and mapped download path.
4. Add RDTClient to Sonarr and Radarr using their qBittorrent-compatible download
   client option.
5. Keep Prowlarr as the search and indexer layer.
6. Test cached and uncached releases, imports, cleanup, and hardlinks before
   replacing the existing qBittorrent client.

TorBox's official
[RDTClient guide](https://support.torbox.app/en/articles/10167535-how-to-setup-rdtclient-with-torbox-docker)
documents this ARR integration. TorBox can also consume a publicly reachable
Prowlarr instance for its own search, but exposing this homelab's Prowlarr and API
key to the internet would add unnecessary risk and is not required for the
RDTClient design.

TorBox does not eliminate local library storage in this design. RDTClient still
downloads the selected file into `/data/downloads` so Radarr or Sonarr can import
it into Plex. Its main advantages are cache hits, remote torrent transfer, and
remote seeding. Plan-specific concurrent-download, maximum-size, storage, and
seeding limits apply; check the current
[TorBox pricing and limits](https://torbox.app/pricing) before relying on it.

Do not assume a private tracker permits a cloud downloader. Obtain explicit
permission from that tracker before using TorBox or any seedbox. TorBox states
that private trackers may technically work, but also acknowledges that no
private tracker officially supports its service and that bans remain possible.
See TorBox's
[private-tracker notice](https://support.torbox.app/en/articles/10031226-what-private-trackers-are-allowed).

### TorBox and Usenet together

TorBox Pro currently includes an NNTP news server that can be used directly by
SABnzbd or NZBGet. In that arrangement, TorBox acts as the Usenet **provider**;
Prowlarr still needs a separate Usenet **indexer**, and SABnzbd remains the local
download client. TorBox documents ten connections and more than 3,900 days of
retention for this service, but those are vendor claims and should be validated
with a small trial before the stack depends on them. See the official
[TorBox News Server guide](https://support.torbox.app/en/articles/15531672-torbox-news-server).

The alternative is to send NZBs through TorBox/RDTClient. Direct NNTP through
SABnzbd is the more conventional ARR design and is easier to troubleshoot because
Radarr and Sonarr see an ordinary local download client.

## Which option helps most?

| Need | Best first trial |
| --- | --- |
| Public torrents frequently stall despite good search results | TorBox through RDTClient |
| Releases are absent from torrent indexers entirely | Usenet provider plus a good Usenet indexer |
| Local upload bandwidth makes ratio or seeding inconvenient | TorBox, where tracker rules permit it |
| Predictable ARR integration and conventional troubleshooting | SABnzbd with direct NNTP |
| Lowest cost and fewest new components | Keep local qBittorrent and the expanded public indexer set |

For this homelab, first let the expanded indexer set and automated retry/search
jobs run. If stalled public torrents remain common, a one-month TorBox trial via
RDTClient is the smallest targeted experiment. If searches frequently find no
acceptable release at all, trial Usenet instead. TorBox Pro can supply the NNTP
provider side, but it does not replace the Usenet indexer.

Prowlarr supports **Generic Newznab** for Usenet and **Generic Torznab** for
torrent services that are not represented by a built-in definition. See the
[Prowlarr quick-start guide](https://wiki.servarr.com/en/prowlarr/quick-start-guide)
for the application-sync model and the
[Radarr settings guide](https://wiki.servarr.com/radarr/settings) for download
client, RSS, retention, and failed-download behaviour.

## Recommendation for this homelab

Keep the current public torrent indexers as the no-cost baseline. If reliability
remains frustrating, add Usenet before investing significant effort in private
tracker recruitment: one provider, one indexer, and SABnzbd is the smallest
useful trial. Pursue a private tracker only when its catalogue or community is
specifically valuable and its seeding rules fit the available storage and
upstream bandwidth.

The future 10 TB NAS makes long seed times easier, but capacity does not remove
the need for tracker-specific limits. Separate download and library paths should
remain on one filesystem so hardlinks continue to prevent duplicate allocation.
