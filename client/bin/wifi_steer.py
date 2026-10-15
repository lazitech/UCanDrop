"""Move Wi-Fi to an access point of the same network that AWDL can share.

Shared-radio AWDL only works when the managed connection sits on one of the
backend's shared frequencies (6, 44 or 149). A home network with several
access points under one name -- a mesh, or a router with two 5 GHz radios --
often has one on a supported channel even when NetworkManager happened to
pick another. This finds that access point and asks NetworkManager to
activate the SAME connection profile on it.

Deliberately narrow:
  - same profile, so same credentials; never a different network name;
  - the access point is held by pinning the profile's BSSID IN MEMORY
    (`nmcli connection modify --temporary`): the file on disk is never
    written, a NetworkManager restart or reboot drops the pin, and `release`
    drops it when the window closes;
  - a profile the user pinned to a BSSID is their choice and is left alone;
  - nothing is attempted unless NetworkManager already grants this user the
    change without asking (Ubuntu: the sudo or netdev group), so `on` never
    raises a password dialog the user did not expect.

Why a pin and not `nmcli connection up ... ap BSSID`: NetworkManager 1.54
passes only the SSID to wpa_supplicant for that, which picked the stronger
channel-36 access point again (observed 2026-10-14). The pin is also what
keeps bgscan from roaming back off the shared channel mid-window.

    wifi_steer.py plan    --from MHZ --supported MHZ,MHZ,...
    wifi_steer.py switch  --from MHZ --supported MHZ,MHZ,...
    wifi_steer.py hold    --supported MHZ,MHZ,...
    wifi_steer.py release --uuid UUID --bssid BSSID

All print one JSON object. `plan` exits 0 with a plan, 1 with only a
"reason". `switch` exits 0 once the device is associated on the chosen
frequency (the pin stays), 1 when there is nothing to switch to, 2 when the
switch failed (the pin is dropped again). `hold` pins the access point the
device is already on when that is a supported frequency -- no reconnect, the
same protection against roaming -- and exits 0 with what it pinned, 1 with a
"reason". `release` drops the pin only while it is still the one `switch` or
`hold` set, so a later change by the user stands.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time

# Weaker than this and the new access point is likely to drop the internet
# connection the user already had; staying put with a clear reason is better.
MIN_SIGNAL = 30
# 5 GHz keeps the internet connection fast; 2.4 GHz channel 6 only wins
# when it is clearly stronger.
FIVE_GHZ_BONUS = 15
NMCLI_TIMEOUT = 20
SWITCH_WAIT = 30
VERIFY_SECONDS = 10


def nmcli(*args, timeout=NMCLI_TIMEOUT):
    env = dict(os.environ, LC_ALL="C")
    return subprocess.run(["nmcli", *args], env=env, capture_output=True,
                          text=True, timeout=timeout)


def fields(line):
    """Split one `nmcli -t -e yes` line on unescaped colons."""
    out, cur, i = [], [], 0
    while i < len(line):
        ch = line[i]
        if ch == "\\" and i + 1 < len(line):
            cur.append(line[i + 1])
            i += 2
            continue
        if ch == ":":
            out.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
        i += 1
    out.append("".join(cur))
    return out


def mhz(value):
    m = re.match(r"\s*(\d+)", value or "")
    return int(m.group(1)) if m else None


def channel(freq):
    if 2412 <= freq <= 2472:
        return (freq - 2407) // 5
    if freq == 2484:
        return 14
    if 5000 <= freq < 5925:
        return (freq - 5000) // 5
    return None


def wifi_devices():
    res = nmcli("-t", "-e", "yes", "-f", "DEVICE,TYPE,STATE", "device")
    if res.returncode:
        return []
    devs = []
    for line in res.stdout.splitlines():
        f = fields(line)
        if len(f) >= 3 and f[1] == "wifi" and f[2] == "connected":
            devs.append(f[0])
    return devs


def scan(device):
    res = nmcli("-t", "-e", "yes", "-f", "IN-USE,BSSID,SSID,FREQ,SIGNAL",
                "device", "wifi", "list", "ifname", device, "--rescan", "auto")
    if res.returncode:
        return []
    rows = []
    for line in res.stdout.splitlines():
        f = fields(line)
        if len(f) < 5:
            continue
        freq = mhz(f[3])
        try:
            signal = int(f[4])
        except ValueError:
            continue
        if freq is None:
            continue
        rows.append({"in_use": f[0].strip() == "*", "bssid": f[1].lower(),
                     "ssid": f[2], "freq": freq, "signal": signal})
    return rows


def first_line(res):
    return res.stdout.splitlines()[0].strip() if res.returncode == 0 and res.stdout.strip() else ""


def may_pin(uuid):
    """Whether this user may edit the profile with no authentication prompt:
    a system profile needs settings.modify.system, a user-owned one
    (connection.permissions set) settings.modify.own."""
    owned = first_line(nmcli("-g", "connection.permissions", "connection", "show", "uuid", uuid))
    want = "org.freedesktop.NetworkManager.settings.modify." + ("own" if owned else "system")
    res = nmcli("-t", "-f", "PERMISSION,VALUE", "general", "permissions")
    if res.returncode:
        return False
    return any(fields(line) == [want, "yes"] for line in res.stdout.splitlines())


def plan(current_freq, supported):
    """The access point to move to, or {"reason": ...} explaining why not."""
    for device in wifi_devices():
        rows = scan(device)
        here = next((r for r in rows if r["in_use"]), None)
        if not here or here["freq"] != current_freq:
            continue
        if not here["ssid"]:
            return {"reason": "hidden"}
        uuid = first_line(nmcli("-g", "GENERAL.CON-UUID", "device", "show", device))
        if not uuid:
            return {"reason": "no-profile"}
        pinned = first_line(nmcli("-g", "802-11-wireless.bssid", "connection", "show", "uuid", uuid))
        if pinned:
            return {"reason": "pinned"}
        if not may_pin(uuid):
            return {"reason": "no-permission"}
        best, best_score = None, None
        for r in rows:
            if r["in_use"] or r["ssid"] != here["ssid"] or r["freq"] not in supported:
                continue
            if r["signal"] < MIN_SIGNAL:
                continue
            score = r["signal"] + (FIVE_GHZ_BONUS if r["freq"] >= 5000 else 0)
            if best_score is None or score > best_score:
                best, best_score = r, score
        if not best:
            return {"reason": "no-access-point"}
        return {"device": device, "uuid": uuid, "ssid": here["ssid"],
                "from": {"bssid": here["bssid"], "freq": here["freq"],
                         "channel": channel(here["freq"])},
                "to": {"bssid": best["bssid"], "freq": best["freq"],
                       "channel": channel(best["freq"]), "signal": best["signal"]}}
    return {"reason": "no-device"}


def associated_freq(device):
    """The current association's frequency, without triggering a scan."""
    res = nmcli("-t", "-e", "yes", "-f", "IN-USE,BSSID,FREQ",
                "device", "wifi", "list", "ifname", device, "--rescan", "no")
    if res.returncode:
        return None, None
    for line in res.stdout.splitlines():
        f = fields(line)
        if len(f) >= 3 and f[0].strip() == "*":
            return f[1].lower(), mhz(f[2])
    return None, None


def said(res):
    return " ".join((res.stderr or res.stdout).split()) or "nmcli exited %d" % res.returncode


def pinned_bssid(uuid):
    return first_line(nmcli("-g", "802-11-wireless.bssid", "connection", "show",
                            "uuid", uuid)).replace("\\", "").lower()


def set_pin(uuid, bssid):
    return nmcli("connection", "modify", "--temporary", "uuid", uuid,
                 "802-11-wireless.bssid", bssid)


def release(uuid, bssid):
    if pinned_bssid(uuid) != bssid.lower():
        return {"released": False}
    res = set_pin(uuid, "")
    if res.returncode:
        return {"released": False, "error": said(res)}
    return {"released": True}


def switch(p, sleep=time.sleep):
    target = p["to"]["bssid"].upper()
    res = set_pin(p["uuid"], target)
    if res.returncode:
        return dict(p, ok=False, error=said(res))
    res = nmcli("-w", str(SWITCH_WAIT), "connection", "up", "uuid", p["uuid"],
                "ifname", p["device"], timeout=SWITCH_WAIT + 10)
    if res.returncode == 0:
        for _ in range(VERIFY_SECONDS * 2):
            bssid, freq = associated_freq(p["device"])
            if bssid == p["to"]["bssid"] and freq == p["to"]["freq"]:
                return dict(p, ok=True)
            sleep(0.5)
        error = "NetworkManager reconnected, but not to the chosen access point"
    else:
        error = said(res)
    release(p["uuid"], target)
    return dict(p, ok=False, error=error)


def hold(supported):
    for device in wifi_devices():
        bssid, freq = associated_freq(device)
        if not bssid or freq not in supported:
            continue
        uuid = first_line(nmcli("-g", "GENERAL.CON-UUID", "device", "show", device))
        if not uuid:
            return {"reason": "no-profile"}
        if pinned_bssid(uuid):
            return {"reason": "pinned"}
        if not may_pin(uuid):
            return {"reason": "no-permission"}
        res = set_pin(uuid, bssid.upper())
        if res.returncode:
            return {"reason": "nmcli", "error": said(res)}
        return {"device": device, "uuid": uuid,
                "to": {"bssid": bssid, "freq": freq, "channel": channel(freq)}}
    return {"reason": "no-device"}


def main(argv):
    ap = argparse.ArgumentParser(prog="wifi_steer.py")
    ap.add_argument("action", choices=("plan", "switch", "hold", "release"))
    ap.add_argument("--from", dest="current", type=int)
    ap.add_argument("--supported")
    ap.add_argument("--uuid")
    ap.add_argument("--bssid")
    args = ap.parse_args(argv)
    if args.action == "release":
        if not (args.uuid and args.bssid):
            ap.error("release needs --uuid and --bssid")
        try:
            out = release(args.uuid, args.bssid)
        except (OSError, subprocess.TimeoutExpired) as exc:
            out = {"released": False, "error": str(exc)}
        print(json.dumps(out))
        return 0
    if not args.supported or (args.action != "hold" and args.current is None):
        ap.error("plan and switch need --from and --supported; hold needs --supported")
    supported = {int(x) for x in args.supported.split(",") if x.strip().isdigit()}
    if args.action == "hold":
        try:
            out = hold(supported)
        except (OSError, subprocess.TimeoutExpired) as exc:
            out = {"reason": "nmcli", "error": str(exc)}
        print(json.dumps(out))
        return 1 if "reason" in out else 0
    try:
        p = plan(args.current, supported)
    except (OSError, subprocess.TimeoutExpired) as exc:
        p = {"reason": "nmcli", "error": str(exc)}
    if "reason" in p:
        print(json.dumps(p))
        return 1
    if args.action == "plan":
        print(json.dumps(p))
        return 0
    try:
        result = switch(p)
    except (OSError, subprocess.TimeoutExpired) as exc:
        result = dict(p, ok=False, error=str(exc))
    print(json.dumps(result))
    return 0 if result["ok"] else 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
