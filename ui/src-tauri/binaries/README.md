# Generated sidecar binaries

`python scripts/build_desktop.py --sidecar-only` writes the platform-specific executable here as `aws2-backend-<target-triple>[.exe]`.

Generated binaries are intentionally ignored by Git and are never used to store credentials.
