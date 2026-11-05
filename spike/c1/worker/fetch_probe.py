"""Spike C1: what the isolated fetch worker can and cannot reach. Prints one JSON line per check."""

import json
import os
import socket
import urllib.error
import urllib.request
from pathlib import Path

PROXY = os.environ["EGRESS_PROXY"]
results = []


def check(req: str, name: str, passed: bool, detail: str = "") -> None:
    results.append({"role": "fetch", "req": req, "check": name, "pass": passed, "detail": detail[:160]})


def via_proxy(url: str) -> tuple[int | None, str]:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({"http": PROXY, "https": PROXY}))
    try:
        with opener.open(url, timeout=15) as response:
            return response.status, "ok"
    except urllib.error.HTTPError as error:
        return error.code, f"HTTP {error.code}"
    except (urllib.error.URLError, OSError) as error:
        # An HTTPS tunnel the proxy refuses surfaces as a URLError carrying its 403.
        if "Tunnel connection failed: 403" in str(error):
            return 403, f"tunnel refused: {error}"
        return None, f"{type(error).__name__}: {error}"


def direct(host: str, port: int) -> tuple[bool, str]:
    try:
        with socket.create_connection((host, port), timeout=4):
            return True, "connected"
    except OSError as error:
        return False, f"{type(error).__name__}: {error}"


check("1", "no database credentials in the environment", not any(k.startswith(("POSTGRES", "DATABASE", "PG")) for k in os.environ), " ".join(sorted(os.environ)))
check("2", "no AI provider credentials in the environment", not any("API_KEY" in k or k.startswith(("OPENAI", "ANTHROPIC")) for k in os.environ))
ok, detail = direct("postgres", 5432)
check("1", "PostgreSQL is not reachable", not ok, detail)
ok, detail = direct("93.184.215.14", 80)
check("10", "no direct connection to the internet, around the proxy", not ok, detail)
status, detail = via_proxy("https://example.com/")
check("10", "a public site is reached through the egress proxy", status == 200, detail)
for url, label in (
    ("http://169.254.169.254/latest/meta-data/", "the cloud metadata address"),
    ("http://127.0.0.1:8000/", "loopback"),
    ("http://10.0.0.1/", "a private address (10/8)"),
    ("http://192.168.1.1/", "a private address (192.168/16)"),
    ("http://redis:6379/", "an internal service by name"),
    ("http://localtest.me/", "a public name that resolves to loopback (rebinding-style)"),
    ("https://example.com:8443/", "a port other than 80 and 443"),
):
    status, detail = via_proxy(url)
    check("10", f"refused at network level: {label}", status == 403, detail)
check("11", "the artifact store is not mounted", not Path("/artifacts").exists())
try:
    Path("/landing/fetched.bin").write_bytes(b"TEST")
    check("11", "writes to the landing area", True)
except OSError as error:
    check("11", "writes to the landing area", False, str(error))
try:
    Path("/app/forged.py").write_text("TEST")
    check("11", "cannot write to its own filesystem", False, "written")
except OSError as error:
    check("11", "cannot write to its own filesystem", True, str(error))
for line in results:
    print(json.dumps(line))
