# UCanDrop 1.1 release design

## Scope

Create an independent Ubuntu distribution of the accepted receive, notification
and transfer-performance implementation. Package only the optimized version.
Do not include previous local releases, account identities, network profiles,
capture data, machine-specific manifests or recovery backups.

## Runtime

- The client loads its own bundled receiver and completion/link modules.
- The public command is `ucandrop`; services and timers have a UCanDrop namespace.
- User paths come from the account and XDG settings. The download folder is
  discovered with `xdg-user-dir`, with a safe default when unavailable.
- File transfers create one native notification per completed batch. Clicking
  opens the first file with its default application. Received URLs remain in
  memory and open only when the notification is clicked.
- Complete-archive validation remains mandatory. The optional HTTP terminator
  grace period is 0.25 seconds only after the archive and byte count validate.
- Existing internal Omdrop identity formats may remain for interoperability;
  no identity or credentials are distributed.

## Radio

- Build the optimized OWL source on the target architecture; do not distribute
  a development-machine executable as the source of truth.
- Select a connected managed Wi-Fi interface, or validate an explicit selection.
- Determine association from the wireless link, without an IPv4 route or ICMP
  prerequisite. Check hardware and regulatory constraints before mutation.
- Keep conservative driver profiles. Shared mode uses supported AWDL frequencies
  and reports incompatible networks rather than changing the router or silently
  disconnecting the user's network.
- Read HT receive capabilities from the selected PHY and band. Invalid or missing
  capability data uses the validated legacy one-stream advertisement.
- Root execution is restricted to the installed named radio helper. Preserve
  unrelated interfaces and terminate only owned processes during teardown.

## Distribution

The source tree contains `client/`, `receiver/`, `radio/`, `vendor/owl/`, build
and installation tools, tests, license notices and user documentation. Native
Debian packages install under `/usr/lib/ucandrop` with `/usr/bin/ucandrop` as the
entrypoint. Installation leaves receiving off. Runtime setup is performed by
the ordinary desktop user. Build dependencies and runtime dependencies are
declared separately.

## Validation and support

Validate receiver integrity, notification actions and batches, HT capability
fallbacks, association/regulatory checks, native package contents and ownership,
relocated source paths and simulated clean homes. Scan the release for private
identifiers and generated build/capture artifacts.

Target Ubuntu 26.04 with NetworkManager, a systemd desktop session, Bluetooth
and a compatible Wi-Fi device. Synthetic and isolated tests cannot establish
support for every physical card or iOS revision. Publish these constraints
instead of an unconditional compatibility guarantee.

## Implementation sequence

1. Export the accepted client, strict receiver improvements and optimized OWL
   into the independent source tree.
2. Adapt the client, radio helper and packaging in separate owned areas.
3. Integrate interfaces and dependency declarations; preserve upstream licenses.
4. Run focused tests, build the native package, audit release contents, then
   create versioned source and package artifacts with SHA-256 checksums.
