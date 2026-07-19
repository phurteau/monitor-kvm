"""App version + update source configuration.

The updater checks the GitHub Releases of the repo below. Until the repo is
published, update checks simply return "no update" and the app is unaffected.
Bump VERSION on each release; the release tag should be like `v1.1.0`.
"""

VERSION = "1.3.0"

# GitHub repo that hosts releases (change if you fork/rename).
GITHUB_OWNER = "phurteau"
GITHUB_REPO = "monitor-kvm"
