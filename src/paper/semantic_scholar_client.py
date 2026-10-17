
import requests

SEARCH_URL = (
    "https://api.semanticscholar.org/graph/v1/paper/search"
)


def search_semantic_scholar(query, limit=10, api_key=None):
    params = {
        "query": query,
        "limit": limit,
        "fields": (
            "title,authors,abstract,year,"
            "paperId,openAccessPdf,url"
        ),
    }

    headers = {}
    if api_key:
        headers["x-api-key"] = api_key

    response = requests.get(
        SEARCH_URL,
        params=params,
        headers=headers,
        timeout=30,
    )
    response.raise_for_status()

    papers = []

    for item in response.json().get("data", []):
        pdf_info = item.get("openAccessPdf") or {}

        papers.append({
            "paper_id": item.get("paperId"),
            "title": item.get("title"),
            "authors": [
                author["name"]
                for author in item.get("authors", [])
            ],
            "abstract": item.get("abstract"),
            "year": item.get("year"),
            "published": None,
            "paper_url": item.get("url"),
            "pdf_url": pdf_info.get("url"),
            "source": "Semantic Scholar",
        })

    return papers
papers = search_semantic_scholar(
    query="machine learning",
    limit=5
)
for paper in papers:
    print("Paper ID:", paper["paper_id"])
    print("Title:", paper["title"])
    print("Authors:", paper["authors"])
    print("Year:", paper["year"])
    print("Abstract:", paper["abstract"])
    print("Paper URL:", paper["paper_url"])
    print("PDF URL:", paper["pdf_url"])