---
description: Permanent rule prohibiting the creation of GitHub Actions workflows in this repository
globs: ["**/*"]
alwaysApply: true
---

# Operational Rule: No GitHub Actions Workflows

1. **NEVER** create files under `.github/workflows/` or add any GitHub Actions configuration.
2. The user's GitHub account has unresolved billing/payment restrictions for cloud runner minutes; triggering Actions causes account payment error banners and halts CI.
3. Keep all testing, validation, and quality gates **strictly local** (via `scripts\run_tests.bat` or `python -m pytest`).
4. Never install blocking pre-push hooks directly into `.git/hooks/` as it breaks the user's non-interactive VS Code GUI push button.
