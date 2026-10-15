# Changelog

## 1.2.1

- When `on` cannot fix an unsupported channel, `doctor` and `on` now say what
  to do: set the router to channel 44 or 149 when no access point of the
  network uses a supported channel, run `ucandrop wifi-switch on` when
  switching is off, join the netdev group when NetworkManager would ask for a
  password, or clear a BSSID lock. `on` stops before starting anything,
  including before saving a `-c`/`-e` visibility change.
- The access-point pin record moved from the runtime directory to
  `~/.local/state/ucandrop/`, so logging out without `ucandrop off` no longer
  leaves the connection pinned with no record; the next `on` or `off`
  releases it. Records left by 1.2.0 are still released.
- A 6 GHz association is named as such ("channel 37 (6 GHz)") instead of an
  empty channel.

## 1.2.0

- When Wi-Fi is associated on a channel AWDL cannot share, `ucandrop on` moves
  the same connection profile to another access point of the same network on
  channel 6, 44 or 149 when one is in range (mesh nodes, dual 5 GHz routers).
- The access point is held with an in-memory BSSID pin until `off` -- also
  when the connection was already on a supported channel -- so NetworkManager
  cannot roam it to a sibling access point mid-window. The saved profile is
  never edited, profiles the user pinned are left alone, nothing is tried
  unless NetworkManager allows the change without a password prompt (on
  Ubuntu: members of sudo or netdev), and `ucandrop wifi-switch off` turns
  switching and holding off.
- If the association still leaves the session's frequency, the radio helper
  stops the session (`channel-changed`) instead of reporting it visible.
- `doctor` reports a planned access-point move instead of a blocker
  (`notices` in `--json`); the probe adds `shared_frequencies` and the
  unsupported `frequency`.
- Unsupported-channel messages name the actual frequency and channel.

## 1.1.0

- Resolve the bundled OWL probe in the installed Debian layout and recognize
  integer or decimal MHz fields from iw without relaxing regulatory checks.
- Standalone Ubuntu distribution with a public `ucandrop` command, native
  package tooling and a self-contained OWL source build.
- Dynamic user paths, download-directory discovery and network/hardware
  preflight instead of development-machine configuration.
- Discover advertising-capable Bluetooth adapters through BlueZ and derive
  sender names from the current host or user configuration.
- Restrict radio elevation to the installed helper and track owned processes
  by executable, arguments, UID and start time during cleanup.
- Native desktop notifications open received files with their default apps.
  A photo batch produces one notification and opens its first image.
- Received web links stay in memory and open from their notification; no
  shortcut file is saved in the download directory.
- Complete CPIO/DVZip archives and declared file sizes are validated before
  accepting transfers with a missing optional HTTP terminator. The validated
  completion grace period is 0.25 seconds.
- HT RX advertisement reads the selected Wi-Fi device's capabilities, allowing
  supported additional spatial streams and using a conservative fallback.
- Previous local releases, diagnostic captures, network profiles, private
  identities and local recovery state are excluded from the distribution.
