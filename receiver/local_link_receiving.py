"""Deliver received web links to the local notification listener in memory."""
from urllib.parse import urlsplit

from web_links import publish_links, valid_web_url


def link_labels(items):
    return [urlsplit(item).hostname for item in items if valid_web_url(item)]


def receive_links(handler, items):
    if not isinstance(items, list) or not items or not all(
            valid_web_url(item) for item in items):
        handler._event_failed("invalid web link transfer")
        handler.reject(400, "invalid web link transfer")
        return False
    try:
        publish_links(handler._event_id, items)
    except ValueError:
        handler._event_failed("link transfer exceeds notification size limit")
        handler.reject(413, "link transfer exceeds notification size limit")
        return False
    except OSError:
        handler._event_failed("link notification is not ready")
        handler.reject(503, "link notification is not ready")
        return False
    # Only the labels and lifecycle id reach the journal. The full addresses
    # are held by the notification listener until clicked or dismissed.
    handler._event_complete([], names=link_labels(items))
    return True
