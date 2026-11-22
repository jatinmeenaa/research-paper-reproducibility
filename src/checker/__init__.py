import http.client
import socket
import ssl

from src.checker.network import UnsafeURL, fetch
from src.database.db import now


def check_resource(resource):
    result = dict(resource)
    result.update(status="unresolved", http_status=None, final_url=None, checked_at=now(), note="")
    try:
        response = fetch(resource["url"], method="HEAD", timeout=10)
        if response["status"] in (405, 501):
            try:
                response = fetch(
                    resource["url"], max_bytes=65536, timeout=10, headers={"Range": "bytes=0-1023"}
                )
            except ValueError:
                result["note"] = "HEAD is unsupported; the GET response exceeded the check limit."
                return result
        code = response["status"]
        result.update(http_status=code, final_url=response["url"])
        if 200 <= code < 300:
            result.update(
                status="accessible",
                note="Public HTTP response; content was not reproduced or audited.",
            )
        elif code in (404, 410):
            result.update(status="missing", note="The server reports this resource is missing.")
        elif code in (401, 403, 429):
            result.update(
                status="restricted",
                note="Authentication, bot protection, or rate limiting may apply.",
            )
        else:
            result.update(
                status="unresolved", note="The server returned an unexpected HTTP response."
            )
    except UnsafeURL as exc:
        result.update(status="blocked", note=str(exc))
    except ssl.SSLCertVerificationError:
        result["note"] = (
            "Certificate verification failed. Check the trusted CA bundle; "
            "resource availability could not be determined."
        )
    except (OSError, ssl.SSLError, socket.timeout, http.client.HTTPException, ValueError):
        result["note"] = "Could not establish availability (DNS, TLS, timeout, or redirect error)."
    return result
