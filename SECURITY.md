# Security policy

StockKeep is a local, single-machine desktop application.  It stores business
data in a SQLite database beside the executable and does not run a network
service.

## Reporting a vulnerability

Please do **not** open a public issue for a security problem.  Contact the
maintainer privately with:

- the affected version and Windows version,
- steps to reproduce,
- the impact you believe it has, and
- any suggested fix.

Allow reasonable time for a fix before public disclosure.

## Handling data

- Passwords are salted PBKDF2 hashes; passwords are never written to the audit
  log.
- The audit log records account and role changes, including before/after
  permission sets.
- Backups contain the full database.  Store them somewhere appropriately
  protected.
- Do not attach a real `database/stockkeep.db`, backup, report or log to an
  issue.  Use a seeded throwaway database if you need to demonstrate a bug.
- The app has no telemetry and makes no outbound network calls.
