
import hashlib
import re
import threading
import time
from urllib.parse import urlsplit

import requests
from flask import current_app
from src.paper.arxiv_client import search_arxiv
from src.paper.semantic_scholar_client import search_semantic_scholar

_cache = {}
_cache_lock = threading.Lock()


def identity(paper):
    if paper.get("upload_hash"):
        return "upload:" + paper["upload_hash"]
    if paper.get("arxiv_id"):
        return "arxiv:" + re.sub(r"v\d+$", "", paper["arxiv_id"])
    url = paper.get("paper_url") or ""
    if "arxiv.org/abs/" in url:
        return "arxiv:" + re.sub(r"v\d+$", "", url.split("/abs/")[-1])
    # Cross-provider deduplication fallback when identifiers are absent.
    title = re.sub(r"[^\w]", "", paper["title"].casefold())
    return "title:" + hashlib.sha256(title.encode()).hexdigest()


def public_url(value):
    if not value:
        return None
    try:
        parsed = urlsplit(value)
        return value if parsed.scheme in ("http", "https") and parsed.hostname else None
    except ValueError:
        return None


def search_semantic(query, limit=10):
    return search_semantic_scholar(
        query, limit, api_key=current_app.config.get("SEMANTIC_SCHOLAR_API_KEY")
    )


def discover(query, source="arXiv"):
    providers = {"arXiv": search_arxiv, "Semantic Scholar": search_semantic}
    selected = list(providers) if source == "both" else [source]
    papers, errors, seen, titles = [], [], set(), set()
    for name in selected:
        cache_key = (name, query.casefold())
        with _cache_lock:
            cached = _cache.get(cache_key)
        try:
            if cached and time.monotonic() - cached[0] < 600:
                results = cached[1]
            else:
                results = providers[name](query, 10)
                with _cache_lock:
                    if len(_cache) >= 100:
                        _cache.pop(next(iter(_cache)))
                    _cache[cache_key] = (time.monotonic(), results)
            for paper in results:
                key = identity(paper)
                title = re.sub(r"\W", "", paper["title"].casefold())
                if key not in seen and title not in titles:
                    seen.add(key)
                    titles.add(title)
                    papers.append(paper)
        except (requests.RequestException, ValueError, KeyError, TypeError):
            current_app.logger.exception("Discovery failed for %s", name)
            errors.append(
                name + " is unavailable or rate-limited. Try again later or use another source."
            )
    return papers, errors
