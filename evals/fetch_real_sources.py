"""Fetch pinned public sources into a local cache; never silently update the dataset."""

import argparse
import hashlib
import json
from pathlib import Path
from urllib.parse import urlparse

import httpx

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=ROOT / "evals/real/dataset-v1.json")
    parser.add_argument("--output", type=Path, default=ROOT / ".local/real-corpus")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    dataset = json.loads(args.dataset.read_text())
    with httpx.Client(timeout=60, follow_redirects=False) as client:
        for source in dataset["sources"]:
            url = urlparse(source["url"])
            if url.scheme != "https" or url.hostname != "documents.portwest.com":
                raise ValueError("Source URL is outside the curated manufacturer allowlist")
            path = (args.output / source["filename"]).resolve()
            if not path.is_relative_to(args.output.resolve()):
                raise ValueError("Invalid source filename")
            if path.exists():
                data = path.read_bytes()
            else:
                response = client.get(source["url"])
                response.raise_for_status()
                data = response.content
            if hashlib.sha256(data).hexdigest() != source["sha256"]:
                raise ValueError(
                    f"{source['id']}: manufacturer bytes changed. Keep the pinned local copy or review and version a new dataset; no overwrite performed."
                )
            if not path.exists():
                path.write_bytes(data)
            print(source["id"] + ": verified")


if __name__ == "__main__":
    main()
