# Changelog

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
