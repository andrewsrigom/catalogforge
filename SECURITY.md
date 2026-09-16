# Security

CatalogForge defaults to local use. Compose and the development launcher bind published ports to loopback; the API accepts `localhost` and `127.0.0.1` hosts by default. Demo credentials are public and intended only for local examples.

Keep API keys in ignored environment files. Uploaded documents, database volumes, backups and `.local/` reports can contain private data and must stay outside the repository. Real AI mode sends retrieved source passages to the configured model provider.

Hosting for other users requires HTTPS, secure cookies, private accounts and explicit host and origin configuration. See [deployment limits](docs/LIMITATIONS.md).

## Reporting a vulnerability

Use [GitHub private vulnerability reporting](https://github.com/andrewsrigom/catalogforge/security/advisories/new). Include the affected version, reproduction steps and expected impact. Do not put credentials or private documents in public issues.
