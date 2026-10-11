# UCanDrop

Transfer content via AirDrop on Ubuntu, including images, videos, documents
and web links. Based on Omdrop and OWL, this project adds file integrity
validation and wireless transfer optimizations.

English | [简体中文](README.zh-CN.md)

## Quick install (recommended)

The target system is **Ubuntu 26.04 Desktop**, with GNOME as the reference
desktop. Bluetooth and a compatible Wi-Fi adapter are required; see
“Compatibility” below for wireless requirements.

Download **`ucandrop_1.1.0_amd64.deb`** from the
[release assets](https://github.com/lazitech/ucandrop/releases/tag/v1.1.0),
open a terminal in the directory containing the file, and run:

```bash
sudo apt install ./ucandrop_1.1.0_amd64.deb
ucandrop setup
```

The current prebuilt package is for amd64 (x86_64). Check your system
architecture with `dpkg --print-architecture`. For arm64, use the source
installation instructions below.

## Receive your first file

Check the environment, then open a one-hour receive window:

```bash
ucandrop doctor --json
ucandrop on 1h
```

If the check or activation reports that wireless requirements are not met,
review your connection and adapter under “Compatibility”. Close other
AirDrop receivers before activation to avoid competing for the wireless
interface and receiving port.

1. Enable Wi-Fi and Bluetooth on the iPhone and keep it near the computer.
2. Open a photo or file and choose **Share → AirDrop**.
3. Select the computer's name to send. The name comes from the local hostname
   or your settings.
4. After the transfer completes, click the **AirDrop** desktop notification
   to open the file.

Files are saved to your system download directory by default. The receive
window closes automatically when it expires. To close it early:

```bash
ucandrop off
```

## Send from your computer to iPhone

On the iPhone, set AirDrop to **Everyone for 10 Minutes** and keep the screen
on, then run:

```bash
ucandrop send /path/to/file --pick
```

Replace `/path/to/file` with the file you want to send and select the phone
from the list.

## Common commands

| Action | Command |
| --- | --- |
| Check the environment | `ucandrop doctor --json` |
| Receive for one hour | `ucandrop on 1h` |
| Check receiving status | `ucandrop status --json` |
| List nearby devices | `ucandrop peers` |
| Send a file and choose a device | `ucandrop send /path/to/file --pick` |
| Change the download directory | `ucandrop dir /path/to/folder` |
| Stop receiving | `ucandrop off` |

If your firewall blocks receiving, run `ucandrop firewall install` to add
the scoped AWDL receiving rule. If clicking a file does not open it, make
sure a suitable default viewer is installed.

## Compatibility

NetworkManager, systemd user services and a desktop notification service
supporting click actions are required. The Wi-Fi adapter and driver must
support the necessary monitor mode, frame injection and acknowledgments.

This version uses shared-radio mode: the computer stays connected to its
existing Wi-Fi network. The connection's access-point frequency must match
the table below and be permitted by the local regulatory domain:

| Band | Channel | Actual frequency |
| --- | --- | --- |
| 2.4 GHz | 6 | 2437 MHz |
| 5 GHz | 44 | 5220 MHz |
| 5 GHz | 149 | 5745 MHz |

A 6 GHz channel with the same number cannot substitute for these frequencies.
The program reads the actual connection and regulatory restrictions. It
does not depend on internet access or gateway ping responses, and it does
not change the router or automatically disconnect Wi-Fi.

Unknown drivers are marked as untested. After reviewing the check results,
if you decide to try one, run:

```bash
sudo install -d -m 0755 /etc/ucandrop
printf '1\n' | sudo tee /etc/ucandrop/allow-untested >/dev/null
ucandrop doctor --json
```

Remove `/etc/ucandrop/allow-untested` to restore the default policy.

## Install from source (optional)

To build the project yourself, modify the code or use arm64, download and
extract the [source archive](https://github.com/lazitech/ucandrop/releases/download/v1.1.0/ucandrop-1.1.0-source.tar.gz).
From the project directory, run as your ordinary desktop user:

```bash
./tools/install.sh --install --install-build-deps
ucandrop setup
```

To check only the source-build environment, run `./tools/install.sh --check`.
This command does not install anything. It lists missing build tools or
runtime dependencies and returns a nonzero status if any are missing.

Run setup and transfer commands from the logged-in desktop session. XDG
configuration directories must match that session's systemd user manager;
changing variables only in a terminal does not change its service search
directories. Transfers use the standard `/run/user/<uid>` runtime directory.
Temporary overrides of `XDG_RUNTIME_DIR` are rejected.

## Uninstall

Close receiving, then remove the application through apt:

```bash
ucandrop off
sudo apt remove ucandrop
```

## Build and verify without installing

Build dependencies are listed in `tools/install.sh`. With build and test
dependencies installed, run:

```bash
./tools/build-deb.sh
python3 -m unittest discover -s tests
python3 -m unittest discover -s client/tests
python3 tools/verify-release.py --package dist/ucandrop_1.1.0_amd64.deb
```

Use the package filename for the architecture actually built. Builds are
native, unprivileged and offline: OWL and its required source dependencies
are vendored. `UCANDROP_BUILD_DIR` and `UCANDROP_OUTPUT_DIR` select writable
output directories. The package includes license notices and source provenance.

See the [release validation record](docs/validation.md) for validation details,
the [third-party notices](THIRD_PARTY_NOTICES.md) for upstream sources and
licenses, and the [changelog](CHANGELOG.md) for version changes.
