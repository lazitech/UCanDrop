"""Web URL validation and volatile delivery to the desktop notification watcher."""
import hashlib
import ipaddress
import json
import os
import socket
from urllib.parse import urlsplit


MAX_URL_BYTES = 8192
MAX_LINK_MESSAGE_BYTES = 32768


def valid_hostname(hostname):
    if not hostname:
        return False
    try:
        ipaddress.ip_address(hostname)
        return True
    except ValueError:
        pass
    try:
        name = hostname.encode("idna").decode("ascii")
    except UnicodeError:
        return False
    labels = name.rstrip(".").split(".")
    return len(name) <= 253 and all(
        1 <= len(label) <= 63 and label[0].isalnum() and label[-1].isalnum()
        and all(char.isalnum() or char == "-" for char in label)
        for label in labels)


def valid_web_url(value):
    if not isinstance(value, str) or not value:
        return False
    try:
        if len(value.encode("utf-8")) > MAX_URL_BYTES:
            return False
        if any(char.isspace() or ord(char) < 32 or 127 <= ord(char) <= 159
               for char in value):
            return False
        parts = urlsplit(value)
        return (parts.scheme.lower() in ("http", "https")
                and valid_hostname(parts.hostname) and parts.port != 0)
    except (ValueError, UnicodeError):
        return False


def link_socket_address(runtime_dir=None):
    runtime = runtime_dir or os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    token = hashlib.sha256(os.fsencode(runtime)).hexdigest()[:16]
    # Linux abstract AF_UNIX sockets live in the kernel, without a socket file.
    return f"\0ucandrop.links.{os.getuid()}.{token}"


def link_message(transfer_id, urls):
    if not isinstance(transfer_id, str) or not 1 <= len(transfer_id) <= 128:
        raise ValueError("invalid transfer id")
    if not isinstance(urls, list) or not 1 <= len(urls) <= 512:
        raise ValueError("invalid link count")
    if not all(valid_web_url(url) for url in urls):
        raise ValueError("invalid web link")
    data = json.dumps({"id": transfer_id, "urls": urls},
                      ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(data) > MAX_LINK_MESSAGE_BYTES:
        raise ValueError("link transfer exceeds notification size limit")
    return data


def publish_links(transfer_id, urls):
    data = link_message(transfer_id, urls)
    with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as connection:
        connection.settimeout(1)
        connection.sendto(data, link_socket_address())
