
# PaperLens — Research Resource Explorer

A local Flask application for finding research papers and inspecting linked code,
datasets, documentation, and supplementary material. Scores describe resource
availability; they do not prove that experiments can be reproduced.

## Run on Windows

Use Python 3.11 or newer. From the project directory:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe run.py
```

If the virtual environment already exists, skip the first command.
Open http://127.0.0.1:5000. The health endpoint is http://127.0.0.1:5000/health.
Stop with Ctrl+C. Restart the server after changing Python files.

## Use the MVP

1. Search arXiv or Semantic Scholar, upload a PDF, or choose manual paper entry.
2. Open a saved paper. No resource category selection is required.
3. Start analysis. Progress updates automatically while a background job runs.
4. Review the score, link statuses, page evidence, and coverage warnings.
5. Correct inferred resource categories if needed; labels do not affect the score.
6. Filter the library, inspect analytics, export CSV/JSON, or print a report.

Search providers need an internet connection and can rate-limit requests. Manual
entry and local PDF extraction work independently of search providers. Availability
checks still need network access. Remote PDF failures fall back to abstract links
and produce a partial report.

An optional Semantic Scholar API key can be set before starting the server:

```powershell
$env:SEMANTIC_SCHOLAR_API_KEY = 'your-key'
```

Do not put API keys in source files. They are not required for local PDF uploads.

## Data and limits

- Papers, reports, and jobs are stored in `data/paperlens.db`.
- Uploaded PDFs and a persistent local session secret are stored in `instance/`.
- Existing older databases are backed up in `data/backups/` before migration.
- Do not delete these folders to restart the application. They contain saved work.
- PDFs are limited to a 20 MB request and 300 pages; OCR is not included.
- Every extracted unique URL is checked, without category priority or a 60-link cutoff.
- Private/local network destinations and nonstandard ports are blocked.
- Score = accessible unique links / extracted unique links x 100, rounded to a whole
  number. Every link has equal weight, including Other links. Absent categories
  are not penalized. Reports with no checked links show Not scored and are excluded
  from mean scores. Restricted or unresolved checks are uncertainty, not confirmed absence.
- Existing reports are rescored from saved checks at startup without changing their
  check timestamps or the database schema. Recheck older partial reports to refresh
  extraction and check any links previously omitted by the old limit.
- Run one server process. Background jobs run in that process; interrupted jobs
  are marked failed after restart and can be retried. Previous reports are kept.
- This is a local single-user MVP. Authentication and a shared durable worker queue
  are future work before exposing it as a multi-user hosted service.

## Verification

```powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m pip check
```

Tests use temporary databases and generated PDFs. External provider/check responses
are simulated so tests do not rely on third-party uptime or alter saved project data.
They cover pages, search integration, uploads, extraction, background analysis,
category corrections, scoring, exports, persistence, migration, and failure recovery.

No Git commit is required to run the application.

