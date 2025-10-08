# Minimal fallback for Python 3.13 where stdlib imghdr was removed
# Only detects the common types our bot may touch; safe to extend later.

def what(filename, h=None):
    if h is None:
        try:
            with open(filename, "rb") as f:
                h = f.read(32)
        except Exception:
            return None

    if not h:
        return None

    # JPEG
    if h[:3] == b"\xff\xd8\xff":
        return "jpeg"
    # PNG
    if h[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    # GIF
    if h[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"

    # Unknown / not supported
    return None