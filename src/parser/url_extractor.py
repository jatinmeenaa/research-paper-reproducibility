import re 
from urllib.parse import urlsplit,urlunsplit
URL_PATTERN = re.compile(r"https?://[^\s<>\"'`]+", re.IGNORECASE)

def extract_urls(text:str) -> list[str]:
    found = set()
    for match in URL_PATTERN.findall(text or ""):
         url = match.rstrip(".,;:!?)]}")
         parts = urlunsplit(url)
         if parts.scheme.lower() not in {"http", "https"} or not parts.netloc:
            continue
         normalized = urlunsplit((parts.scheme.lower(), parts.netloc.lower(),
                                 parts.path, parts.query, ""))
         found.add(normalized)

    return sorted(found)