# UCanDrop 1.2.0 release validation

The release was built and checked on Ubuntu 26.04, native amd64. These results
validate the included implementation and distribution artifacts. They do not
establish physical compatibility with every Wi-Fi adapter, network, Apple
device or iOS version. Saved network profiles were not changed during
release validation; the access-point checks below changed only in-memory
NetworkManager state, which was released afterwards.

## Automated checks

| Check | Result |
| --- | --- |
| Release, installation, client portability, radio and receiver suite | 61 passed |
| Full client suite | 226 passed, 2 environment-dependent tests skipped |
| Native OWL and Debian package build | Passed |
| Source and extracted package privacy/content audit | Passed |
| Relocated clean native build | Passed |
| Original and relocated Debian package comparison | Byte-identical |

The installed-layout regression test extracts the real Debian package and
runs its public command without a backend override. It confirms that the
colocated OWL helper is probed rather than falling back to the upstream Apple
hardware check. Frequency fixtures cover both integer and zero-decimal MHz
fields from iw, including rejection of a decimal no-IR entry. These tests
failed with the original packaged implementation and pass with the fixes.

1.2.0 adds access-point steering. `client/tests/test_wifi_steer.py` drives
`wifi_steer.py` against a simulated nmcli that, like NetworkManager 1.54 on
real hardware, lets wpa_supplicant pick the strongest access point unless the
profile carries a BSSID. It covers choosing a supported access point of the
same network, never another network name, user-pinned profiles, users
without password-free permission, colon-escaped SSIDs, the in-memory pin,
activation failure, landing on the wrong access point, and releasing only the
pin UCanDrop set. Doctor and probe tests cover the new `frequency`,
`shared_frequencies` and `notices` fields, and the supervisor test covers a
session whose association leaves its frequency.

## Hardware checks

Ubuntu 26.04, mt7925e, NetworkManager 1.54.3, one network name served by
access points on channels 6, 36 and 149:

| Check | Result |
| --- | --- |
| `nmcli connection up ... ap BSSID` alone | Rejected approach: reassociated to the stronger channel-36 access point |
| From channel 36, `ucandrop on` (source client) | Moved to channel 149 in about 13 s; profile pinned in memory; radio visible |
| From channel 149, `ucandrop on` (source client) | Pinned in place with the same active connection (no reconnect); radio visible |
| `ucandrop off` after either | Pin released, runtime record removed, Wi-Fi reassociated |
| Installed 1.2.0 package: move from channel 36, hold on 149, release on `off` | Passed |
| iPhone photo transfer after an automatic move from channel 36 | Passed (2.6 MB JPEG stored) |
| iPhone photo transfer with the access point held on channel 149 | Passed (2.6 MB JPEG stored) |
| Association forced to channel 36 mid-window | Session stopped as `channel-changed`; status said so; a pin changed by the user was left in place |
| `wifi-switch off` on channel 36 | Doctor reported the channel as a blocker; `on` refused without touching Wi-Fi |
| Start cancelled after a move | Not exercised on hardware; covered by the EXIT-trap release path only |

The client skips were:

- `RadioBackendTests.test_install_with_a_probing_backend_and_nothing_missing_does_nothing`:
  the validation environment did not have all receiver dependencies required
  for that fixture. Other dependency-probe paths ran.
- `BusyPortTests.test_the_receiver_waits_for_its_port_instead_of_moving_to_another`:
  no active `awdl0` interface was available to the fixture.

The receiver tests use loopback TLS and generated archives. They cover large
and multi-member transfers, compressed archive completion without the optional
HTTP terminator, delayed end markers, truncated archives, incorrect declared
file sizes and normal keep-alive behavior. The HT tests compile harnesses
against the actual C implementation, covering spatial-stream normalization,
wire encoding and conservative fallback.

Radio tests use simulated association, regulatory and device capabilities.
They cover IPv6-only association without gateway ping, dynamic interface and
Bluetooth selection, preservation of unrelated interfaces, delayed exec,
exact process identity, inherited signal handling and status queries where
an unprivileged user cannot read a root process's executable link. Process
termination retains strict identity checks.

## Distribution checks

The exported source was extracted into a different directory containing
Unicode, spaces and a percent sign. Read-only installation preflight, a clean
native build, extracted-package audit and the packaged command's version check
passed there. Its complete `.deb` matched the original build byte for byte.

Source archive ownership is normalized to UID/GID 0 with empty account and
group names. File and gzip timestamps are fixed. Debian archive ownership and
timestamps are also normalized; a regression test checks the outer archive
headers against the declared release epoch. Compiler prefix maps remove
checkout paths from the native executable.

The release audit checks for private identities and keys, account home paths,
physical interface names, capture files, inspecting-account identifiers,
external source symlinks and prebuilt source executables. Source exports
exclude build output, caches and distribution artifacts. Required runtime
modules, public trust anchors, policy, service templates, dependencies and
license notices are checked in the package.

## Reproduce the checks

Run from the extracted source directory as an ordinary user, with the build
and test dependencies installed:

```bash
./tools/install.sh --check
./tools/build-deb.sh --jobs 2
python3 -m unittest discover -s tests -v
python3 -m unittest discover -s client/tests -v
python3 tools/verify-release.py --package dist/ucandrop_1.2.0_amd64.deb
python3 tools/export-release.py
```

Use the package filename for the native architecture actually built. Arm64
build support is included, but an arm64 package was not built or physically
validated in this release check. Real transfers still require the hardware,
regulatory and shared-radio frequency conditions documented in the README.
