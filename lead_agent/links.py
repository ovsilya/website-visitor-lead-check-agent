"""Page links shown in the chat and sent to the model."""
from urllib.parse import urlsplit


def page_link(url: str) -> str:
    """Scheme, host and path only: query strings and fragments can carry tracking ids or emails.

    Anything that isn't an http(s) link becomes "".
    """
    p = urlsplit(str(url).strip())
    return f"{p.scheme}://{p.hostname}{p.path}" if p.scheme in ("http", "https") and p.hostname else ""
