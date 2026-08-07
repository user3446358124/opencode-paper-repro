# Security Policy

Please do not disclose credentials, private datasets, unpublished papers, project logs, or personal paths in public issues.

For a suspected credential leak:
1. Revoke or rotate the credential immediately.
2. Do not bypass GitHub push protection.
3. Open a private security advisory or contact the repository owner through a private channel.

The public repository must contain only the sanitized paper-repro system source. Runtime workspaces, `.paper-repro/`, model/data assets, API responses, and user configuration are out of scope and must never be committed.
