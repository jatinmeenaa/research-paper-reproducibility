import ipaddress
import socket
import time
from urllib.parse import urlparse
import requests
def _is_public_http_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in {"http","https"} or not parsed.hostname:
        return False
    host = parsed.hostname.lower()
    if host in {"localhost"} or host.endswith(".local"):
        return False

    try:
        addresses = socket.getaddrinfo(host,None)
        for item in addresses:
            ip = ipaddress.ip_address(item[4][0])
            if not ip.is_global:
                return False
    except(socket.gaierror,ValueError):
        return True
    return True


def check_url(url:str,timeout: int = 10) -> dict:
    result = {
        "url":url,"final_url":None,"status_code":None,
        "accessible":None,"response_time_ms":None,"error":None,
    }
    if not _is_public_http_url(url):
        result["error"] = "URL rejected:only public HTTP(S) URLS are allowed"
        return result
    start = time.monotonic()
    try: 
        response = requests.get(
            url,timeout=timeout,allow_redirects=True,stream=True,
            headers={"User-Agent":"ResearchPaperReproducibility/1.0"},
        )
        result["status_code"] = response.status_code
        result["final_url"] = response.status_code
        result["accessible"] = 200 <=response.status_code < 300
        response.close()

    except requests.RequestException as exc:
        result["error"] = f"{type(exc).__name__}:{exc}"

    finally:
        result["response_time_ms"] = round((time.monotonic() - start)*1000,2)
    return result
