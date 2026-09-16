import time

import httpx

deadline = time.monotonic() + 90
with httpx.Client(base_url="http://127.0.0.1:8188/api", timeout=5) as client:
    while time.monotonic() < deadline:
        try:
            response = client.post(
                "/auth/login",
                json={
                    "email": "reviewer@catalogforge.local",
                    "password": "CatalogForge-demo-2026!",
                },
            )
            response.raise_for_status()
            session = response.json()
            client.headers["x-workspace-id"] = "00000000-0000-0000-0000-000000000001"
            sources = client.get("/sources").json()
            if len(sources) == 5 and all(s["status"] == "ready" for s in sources):
                print("API and five synthetic sources are ready")
                break
        except (httpx.HTTPError, KeyError, TypeError):
            pass
        time.sleep(0.5)
    else:
        raise SystemExit("API or document ingestion did not become ready within 90 seconds")
