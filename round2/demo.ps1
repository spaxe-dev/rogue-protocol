# ROGUE PROTOCOL Round 2 — Demo Flow (~3 min, offline-safe)
# Usage: from round2/ run:  powershell -ExecutionPolicy Bypass -File demo.ps1
# Dry-run pinned: JIRA live is NEVER touched by this demo.

$env:JIRA_ENABLED = "0"
Write-Host "=== 1. Crew roster ==="
python -m src.main --roster
Write-Host "=== 2. Pipeline: 5 logs in ==="
python -m src.main --input demo_logs.csv --state demo_run --memory faiss
Write-Host "=== 3. Schedule (exact schema) ==="
Get-Content demo_run/schedule.csv
Write-Host "=== 4. Notifications sent ==="
Get-ChildItem demo_run/outbox
Write-Host "=== 5. Run report ==="
Get-Content demo_run/reports/run_report.md
Write-Host "=== 6. Recurrence radar ==="
Get-Content demo_run/reports/recurrence.md
Write-Host "=== 7. Status board ==="
python -m src.main --status demo_run
Write-Host "=== 8. Dossier ==="
python -m src.tools.crew_dossier
Write-Host "DONE. Live Jira path (needs creds): python exp_jira_smoke.py"
