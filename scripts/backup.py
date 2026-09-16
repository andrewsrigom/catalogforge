"""Consistent Compose backups and non-destructive, isolated restore rehearsals."""

import argparse
import hashlib
import json
import os
import re
import subprocess
import tarfile
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ["docker", "compose", "-f", str(ROOT / "compose.yaml")]

# Executed in a one-off application container while API and worker are stopped.
INVENTORY = """
import hashlib,json
from sqlalchemy import create_engine,text
from catalogforge.config import settings
from catalogforge.storage import storage
with create_engine(settings().database_url).connect() as db:
    tables=db.execute(text("SELECT schemaname,tablename FROM pg_tables WHERE schemaname IN ('public','checkpoints') ORDER BY 1,2")).all()
    counts={s+'.'+t:db.execute(text('SELECT count(*) FROM "'+s+'"."'+t+'"')).scalar() for s,t in tables}
    sources=[]
    for key,digest in db.execute(text('SELECT storage_key,content_hash FROM source_documents ORDER BY storage_key')):
        actual=hashlib.sha256(storage().read(key)).hexdigest()
        if actual != digest: raise ValueError('Source content hash mismatch: '+key)
        sources.append({'key':key,'sha256':digest})
    print(json.dumps({'tables':counts,'sources':sources},sort_keys=True))
"""
ARCHIVE = """
import sys,tarfile
from catalogforge.config import settings
root=settings().storage_root
with tarfile.open(fileobj=sys.stdout.buffer,mode='w|') as archive:
    for p in sorted(root.rglob('*')):
        if p.is_symlink(): raise ValueError('Upload symlinks cannot be backed up')
        if p.is_file(): archive.add(p,arcname=p.relative_to(root).as_posix(),recursive=False)
"""


def run(args, **kwargs):
    return subprocess.run(args, cwd=ROOT, check=True, **kwargs)


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def services(compose=COMPOSE):
    result = run([*compose, "ps", "--format", "json"], capture_output=True, text=True)
    return [json.loads(line) for line in result.stdout.splitlines() if line.strip()]


def inventory(compose):
    result = run(
        [
            *compose,
            "run",
            "--rm",
            "--no-deps",
            "-T",
            "--entrypoint",
            "/app/.venv/bin/python",
            "api",
            "-c",
            INVENTORY,
        ],
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def create(destination):
    destination = destination.resolve()
    destination.mkdir(parents=True, exist_ok=False)
    destination.chmod(0o700)
    active = services()
    if any(row["Service"] == "init" and row["State"] == "running" for row in active):
        raise ValueError("Wait for initialization to finish before backup")
    restart = [
        row["Service"]
        for row in active
        if row["Service"] in {"api", "worker", "web"} and row["State"] == "running"
    ]
    try:
        # Stop ingress before the worker; SIGTERM is given a bounded grace period.
        run([*COMPOSE, "stop", "-t", "45", "web", "api", "worker"])
        state = inventory(COMPOSE)
        with (destination / "database.dump").open("wb") as stream:
            run(
                [
                    *COMPOSE,
                    "exec",
                    "-T",
                    "db",
                    "pg_dump",
                    "-U",
                    "catalogforge",
                    "-d",
                    "catalogforge",
                    "-Fc",
                    "--no-owner",
                    "--no-acl",
                ],
                stdout=stream,
            )
        with (destination / "uploads.tar").open("wb") as stream:
            run(
                [
                    *COMPOSE,
                    "run",
                    "--rm",
                    "--no-deps",
                    "-T",
                    "--entrypoint",
                    "/app/.venv/bin/python",
                    "api",
                    "-c",
                    ARCHIVE,
                ],
                stdout=stream,
            )
        commit = run(["git", "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
        runtime_images = {}
        for service in ["api", "worker"]:
            image_id = run(
                [*COMPOSE, "images", "-q", service], capture_output=True, text=True
            ).stdout.strip()
            if not image_id:
                raise ValueError("Cannot identify the running application image")
            runtime_images[service] = run(
                ["docker", "image", "inspect", image_id, "--format", "{{.Id}}"],
                capture_output=True,
                text=True,
            ).stdout.strip()
        manifest = {
            "format": 1,
            "runtime_images": runtime_images,
            "created_at": datetime.now(UTC).isoformat(),
            "commit": commit,
            "working_tree_dirty": bool(
                run(["git", "status", "--porcelain"], capture_output=True, text=True).stdout
            ),
            "consistent_window": "Compose API, worker and web stopped; no external writers permitted",
            "files": {
                name: digest(destination / name) for name in ["database.dump", "uploads.tar"]
            },
            "inventory": state,
        }
        (destination / "manifest.json").write_text(json.dumps(manifest, indent=2))
        for path in destination.iterdir():
            path.chmod(0o600)
        print(
            json.dumps(
                {"backup": str(destination), "sources": len(state["sources"]), "complete": True}
            )
        )
    finally:
        if restart:
            run([*COMPOSE, "up", "-d", "--no-deps", "--wait", "--wait-timeout", "90", *restart])


def validate_backup(source):
    manifest = json.loads((source / "manifest.json").read_text())
    if manifest.get("format") != 1 or set(manifest["files"]) != {"database.dump", "uploads.tar"}:
        raise ValueError("Unsupported backup manifest")
    for name, expected in manifest["files"].items():
        if digest(source / name) != expected:
            raise ValueError("Backup checksum mismatch: " + name)
    return manifest


def extract_uploads(archive_path, target):
    with tarfile.open(archive_path) as archive:
        members = archive.getmembers()
        seen = set()
        for member in members:
            resolved = (target / member.name).resolve()
            if (
                not resolved.is_relative_to(target.resolve())
                or not member.isfile()
                or member.name in seen
            ):
                raise ValueError("Unsafe or duplicate upload archive member")
            seen.add(member.name)
        archive.extractall(target, members=members, filter="data")


def restore(source, name, port):
    if not re.fullmatch(r"catalogforge-restore-[a-z0-9-]{1,40}", name):
        raise ValueError("Use a new project name beginning catalogforge-restore-")
    manifest = validate_backup(source)
    images = manifest.get("runtime_images")
    if not images or not all(
        re.fullmatch(r"sha256:[a-f0-9]{64}", images.get(service, ""))
        for service in ["api", "worker"]
    ):
        raise ValueError(
            "Backup lacks pinned runtime images; use the matching historical version or create a new backup"
        )
    for image in images.values():
        run(["docker", "image", "inspect", image], stdout=subprocess.DEVNULL)
    target = ROOT / ".local" / "restores" / name
    if target.exists():
        raise ValueError("Restore target already exists; choose a new name")
    # Prevent attaching to any existing Compose project/volume, even if stopped.
    for kind in ["container", "volume"]:
        result = run(
            ["docker", kind, "ls", "-q", "--filter", f"label=com.docker.compose.project={name}"],
            capture_output=True,
            text=True,
        )
        if result.stdout.strip():
            raise ValueError("Restore project already has Docker resources")
    target.mkdir(parents=True)
    target.chmod(0o700)
    uploads = target / "uploads"
    uploads.mkdir()
    extract_uploads(source / "uploads.tar", uploads)
    env = {
        "DATABASE_URL": "postgresql+psycopg://catalogforge:catalogforge-local@db:5432/catalogforge",
        "STORAGE_ROOT": "/data/uploads",
        "AI_MODE": "fixture",
        "OPENAI_API_KEY": "",
    }
    app = {
        "image": images["api"],
        "environment": env,
        "volumes": ["uploads:/data/uploads"],
        "depends_on": {"db": {"condition": "service_healthy"}},
    }
    config = {
        "name": name,
        "services": {
            "db": {
                "image": "pgvector/pgvector:pg16",
                "environment": {
                    "POSTGRES_USER": "catalogforge",
                    "POSTGRES_DB": "catalogforge",
                    "POSTGRES_PASSWORD": "catalogforge-local",
                },
                "volumes": ["postgres:/var/lib/postgresql/data"],
                "healthcheck": {
                    "test": ["CMD-SHELL", "pg_isready -U catalogforge"],
                    "interval": "2s",
                    "timeout": "2s",
                    "retries": 30,
                },
            },
            "api": {
                **app,
                "command": [
                    "uv",
                    "run",
                    "--no-sync",
                    "uvicorn",
                    "catalogforge.main:app",
                    "--host",
                    "0.0.0.0",
                    "--port",
                    "8000",
                ],
                "ports": [f"127.0.0.1:{port}:8000"],
            },
            "worker": {
                **app,
                "image": images["worker"],
                "command": ["uv", "run", "--no-sync", "python", "-m", "catalogforge.worker"],
            },
        },
        "volumes": {"postgres": {}, "uploads": {}},
    }
    file = target / "compose.json"
    file.write_text(json.dumps(config, indent=2))
    compose = ["docker", "compose", "-f", str(file)]
    run([*compose, "up", "-d", "--wait", "db"])
    with (source / "database.dump").open("rb") as stream:
        run(
            [
                *compose,
                "exec",
                "-T",
                "db",
                "pg_restore",
                "-U",
                "catalogforge",
                "-d",
                "catalogforge",
                "--no-owner",
                "--no-acl",
                "--exit-on-error",
            ],
            stdin=stream,
        )
    restore_files = """
import sys,tarfile,os
from pathlib import Path
root=Path('/data/uploads')
with tarfile.open(fileobj=sys.stdin.buffer,mode='r|') as archive:
    for member in archive:
        if not member.isfile() or not (root/member.name).resolve().is_relative_to(root):
            raise ValueError('Unsafe archive member')
        archive.extract(member,root,filter='data')
for path in [root,*root.rglob('*')]:
    os.chown(path,1000,1000)
    path.chmod(0o755 if path.is_dir() else 0o644)
"""
    with (source / "uploads.tar").open("rb") as stream:
        run(
            [
                *compose,
                "run",
                "--rm",
                "--no-deps",
                "-T",
                "--user",
                "0:0",
                "--entrypoint",
                "/app/.venv/bin/python",
                "api",
                "-c",
                restore_files,
            ],
            stdin=stream,
        )
    restored = inventory(compose)
    if restored != manifest["inventory"]:
        raise ValueError("Restored inventory differs; worker remains stopped for inspection")
    result = {
        "backup": str(source),
        "project": name,
        "inventory_matches": True,
        "source_hashes_verified": len(restored["sources"]),
        "api_port": port,
        "worker_started": False,
    }
    (target / "verification.json").write_text(json.dumps(result, indent=2))
    run([*compose, "up", "-d", "api"])
    print(json.dumps(result))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    backup = sub.add_parser("create")
    backup.add_argument("--output", type=Path, required=True)
    recover = sub.add_parser("restore")
    recover.add_argument("--source", type=Path, required=True)
    recover.add_argument("--project", required=True)
    recover.add_argument("--port", type=int, default=8288)
    args = parser.parse_args()
    if args.command == "create":
        create(args.output)
    else:
        if not 1024 <= args.port <= 65535 or args.port in {5288, 5488, 8188}:
            parser.error("Choose a distinct unprivileged restore port")
        restore(args.source.resolve(), args.project, args.port)


if __name__ == "__main__":
    os.umask(0o077)
    main()
