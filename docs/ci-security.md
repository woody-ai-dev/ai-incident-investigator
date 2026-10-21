# CI security and Python coverage

These checks use GitHub Actions and local command-line tools. They require no SonarQube
account, Codecov account, OpenAI API key, or manually created access token.

## Secret scanning

The **Security scan** workflow (`.github/workflows/security-scan.yaml`) runs the
`Secret scan (Gitleaks)` job on pull requests and pushes to `main`. It checks
all fetched Git history, including secrets removed by later commits. Checkout fetches
the full history and does not persist repository credentials in the scanner job.

The workflow downloads Gitleaks CLI 8.30.1 and verifies the Linux archive against a
pinned SHA-256 before execution. It uses the free CLI directly. Findings are redacted;
the job fails when a leak or scanner error is detected. No secret-bearing report is
uploaded as an artifact. Security scanning runs independently of build and demo CI;
require both workflows before merging. The scanner job name remains unchanged.

To scan locally after installing Gitleaks:

```bash
gitleaks git --no-banner --redact --log-opts="--all" .
```

If a real credential is found, revoke or rotate it. Removing the current file alone
does not remove the credential from Git history. Only verified dummy values should
receive narrowly scoped exceptions; there is no blanket ignore list in this project.

The README Security scan badge reflects only this workflow, filtered to pushes on
`main`. It becomes available after the first run of the new workflow on `main`.
It reports secret-scan status, not dependency vulnerability coverage or a security audit.

## Python coverage

The Python job runs pytest with pytest-cov. Coverage includes the application package
`src/ai_incident_investigator`; branch coverage is recorded as well. The README badge
shows **line coverage** from the generated XML report. It does not represent Java or
frontend coverage, optional PostgreSQL-only integration coverage, or LLM evaluation
quality. No coverage percentage is hardcoded in the README.

Run the same commands locally:

```bash
uv sync --locked --dev
uv run --locked pytest --cov --cov-report=term --cov-report=xml:data/coverage.xml
uv run --locked python scripts/coverage_badge.py \
  --input data/coverage.xml \
  --output data/coverage-badge/python-coverage.svg
```

Every successful Python job uploads a `python-coverage` artifact containing the XML
report and SVG badge, retained for seven days. Generated files stay under ignored
`data/` locally.

On a successful push to `main`, the publication job copies the tested SVG to a dedicated
`coverage-badges` branch. It uses the GitHub-provided `GITHUB_TOKEN` with `contents:
write` only in that job. Pull request jobs have read-only access and never publish a
badge. Publication is serialized, skips outdated main commits, and commits only when
the SVG changes. The generated branch contains no workflow files, so updating the badge
does not start another CI run.

The badge URL becomes available after merging this configuration and completing the
first successful `main` run. GitHub may briefly cache an earlier image. The XML and SVG
artifacts remain available in PR runs before publication.

## Repository settings

1. In GitHub repository settings, open **Actions → General → Workflow permissions**.
   Ensure repository or organization policy permits the publication job's explicitly
   requested `contents: write` permission. No personal access token is needed.
2. In **Settings → Rules → Rulesets**, protect `main` and require the
   `Secret scan (Gitleaks)` and existing CI validation checks before merging. Configure
   required checks after they first appear in a workflow run. Keep the generated
   `coverage-badges` branch outside rules that require pull requests or signed commits.
3. In **Settings → Security**, check **Secret scanning / Push protection** and enable
   repository push protection where available. GitHub secret scanning is available for
   public repositories. Push protection detects supported secrets before accepting a
   push; the CI scanner runs after GitHub receives it.

SonarQube analysis and its Quality Gate are not configured in this change.
