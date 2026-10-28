from pathlib import Path
import requests
import fitz

def download_pdf(url:str,destination: str,timeout:int = 30,max_bytes:int = 40 * 1024 * 1024) -> str:
    if not url:
        raise ValueError("No PDF URL supplied")
    path = Path(destination)

    path.parent.mkdir(parents=True,exit_ok=True)
    total = 0

    with requests.get(url, timeout=timeout,stream =True,headers={"User-Agent": "ResearchPaperReproducibilityExplorer/1.0"}) as response:
        response.raise_for_status()
        content_type = response.headers.get("content-type", "").lower()
