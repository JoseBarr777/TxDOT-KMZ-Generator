"""Release tooling invoked by .github/workflows/release-staging.yml.

Each module is a standalone, standard-library-only script
(``python3 scripts/release/<name>.py``); this file exists only so the tests
can import them as ``release.gate`` / ``release.package`` / ``release.verify``.
"""
