
import os
import requests

API_URL = "https://api.semanticscholar.org/graph/v1/paper/search"
FIELDS = "title,authors,abstract,year,url,openAccessPdf,externalIds,fieldsOfStudy"


def search_semantic_scholar(query, limit=10, api_key=None):
   
    if not isinstance(query, str) or not query.strip():
        return []
    count = max(1, min(int(limit), 20))
    key = api_key if api_key is not None else os.environ.get("SEMANTIC_SCHOLAR_API_KEY", "")
    headers = {"User-Agent": "PaperLens/1.0 (academic resource explorer)"}
    if key:
        headers["x-api-key"] = key
    response = requests.get(
        API_URL,
        params={"query": query.strip(), "limit": count, "fields": FIELDS},
        headers=headers, timeout=(8, 25),
    )
    response.raise_for_status() 
    payload = response.json()
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise ValueError("Unexpected Semantic Scholar response")
    papers = []
    for entry in payload["data"]:
        if not isinstance(entry, dict):
            continue
        title, paper_id = entry.get("title"), entry.get("paperId")
        if not title or not paper_id:
            continue
        pdf = (entry.get("openAccessPdf") or {}).get("url")
       
        if not public_url(pdf):
            continue
        external_ids = entry.get("externalIds") or {}
        paper_url = public_url(entry.get("url"))
        papers.append({
            "paper_id": paper_id,
            "title": " ".join(str(title).split()),
            "authors": [a.get("name", "") for a in (entry.get("authors") or []) if isinstance(a, dict)],
            "abstract": entry.get("abstract") or "",
            "year": entry.get("year"),
            "area": next(iter(entry.get("fieldsOfStudy") or []), "Uncategorized"),
            "paper_url": paper_url,
            "pdf_url": public_url(pdf),
            "arxiv_id": external_ids.get("ArXiv"),
            "source": "Semantic Scholar",
        })
    return papers


def public_url(value):
    """Reject non-http(s) and malformed metadata URLs."""
    from urllib.parse import urlsplit
    if not isinstance(value, str):
        return None
    try:
        p = urlsplit(value)
        if p.scheme.lower() not in ("https", "http") or not p.hostname or p.username is not None or p.password is not None:
            return None
        return value
    except ValueError:
        return None
