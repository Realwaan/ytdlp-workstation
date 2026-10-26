# Repository Guidelines & Operational Rules

## 🚫 CRITICAL RULE: DO NOT ADD GITHUB ACTIONS WORKFLOWS
- **Strictly Prohibited**: Never create `.github/workflows/` or add any GitHub Actions YAML files.
- **Reason**: The repository owner's GitHub account has a payment/billing block on GitHub cloud compute minutes. Any GitHub Actions workflow causes GitHub to halt and throw billing/payment restriction errors on the account.
- **Testing Standard**: 
  - All CI/CD and testing must remain **100% local**.
  - Run tests locally using `python -m pytest` or `scripts\run_tests.bat`.
  - Do not install blocking pre-push git hooks into `.git/hooks/` that interfere with VS Code's GUI Git integration.
