# Publication Privacy Boundary

This repository is generated from a clean system-source snapshot, not from any paper reproduction workspace.

The publication pipeline excludes and scans for:
- API keys, tokens, passwords, private keys and authentication files;
- project repositories, PDF papers, datasets, checkpoints, predictions and logs;
- `.paper-repro/`, Conda environment metadata and user configuration;
- absolute home/workspace paths, hostnames and known project identifiers.

A public push is blocked unless the snapshot passes the local privacy scan and the user explicitly approves the exact repository and visibility.
