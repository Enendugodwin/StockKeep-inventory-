# Changelog

All notable changes to StockKeep are documented here.

## 1.2.0

- Added database-backed roles and an Admin-only **Roles & permissions** page.
  Admins can create custom roles and tick exactly which sections and actions each
  role can use.
- Added the `users.view`, `roles.view` and `roles.manage` permissions, plus a
  permission matrix in the role editor and a live role summary on the Users page.
  The Owner can see Users and Roles read-only; editing roles stays Admin-only.
- Updated the default Owner role: all operational sections (including sales,
  refunds, reports and read-only Users) except Settings, Audit and role
  administration.
- Updated the default Base user role: Dashboard, Record Sale, and read-only
  Transactions. Refund and reversal controls are hidden and rejected by the
  service layer.
- Permission-aware dashboard quick actions, inventory edit controls, report job
  controls and backup controls.
- Added schema versions 3 and 4 with automatic migration and seeded built-in
  roles; version 4 adds read-only Roles visibility to the default Owner.
- Added hidden-console flags for Task Scheduler helper commands, so `schtasks`
  no longer flashes a Command Prompt window.
- Added GitHub Actions CI, Dependabot, editor/git attributes and contribution
  and security notes.
- Updated README screenshots and documentation.

## 1.1.0

- Portable data storage beside the application (including the packaged build).
- Windows installer built with Inno Setup; uninstall preserves business data.
- Lazy page construction and SQLite cache/mmap tuning for faster startup.
- Added the `yard` unit.
