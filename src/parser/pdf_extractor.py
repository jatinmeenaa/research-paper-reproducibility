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
        if "pdf" not in content_type and not url.lower().split("?")[0].endswith(".pdf"):
            pass
        with path.open("wb") as out:
            for chunk in response.iter_content(chunk_size=64*1024):
                if not chunk:
                    continue
                total += len(chunk)
                if total > max_bytes:
                    out.close()
                    path.unlink(missing_ok=True)
                    raise ValueError(f"PDF exceeds size limit ({max_bytes}bytes)")
                out.write(chunk)

        with path.open("rb") as inp:
            signature = inp.read(5)

        if signature != b"%PDF-":
            path.unlink(missing_ok=True)
            raise ValueError("Downloaded content is not a valid PDF file")
        return str(path)

def extract_pdf_text(pdf_path: str) -> str:
        parts = []
        with fitz.open(pdf_path) as document:
            for page in document:
                parts.append(page.get_text("text"))
        return "\n".join(parts).strip()            
