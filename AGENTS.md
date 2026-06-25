# Listly Lead Engine / ListlyHomes Backend Instructions

## General
- Keep PRs small and scoped.
- Do not merge PRs automatically.
- Do not rename AWS resources unless explicitly requested.
- Visible product naming should use ListlyHomes/Listly, but internal AWS/resource names may still contain BuyersBoard until an explicit rename migration.
- Do not add unauthenticated public write routes.
- Any route that imports, lists, edits, promotes, deletes, or exposes internal candidate/lead data must require auth unless explicitly requested otherwise.
- Keep local tools local unless explicitly asked to expose them as API routes.

## Verification Required Before Finishing
Every Codex task must return a Pre-Merge Verification Report with:
- PR number and URL
- branch name
- changed files
- new files
- modified existing files
- auth/security-sensitive changes
- infrastructure/template.yaml changes
- API route changes
- whether existing endpoint behavior changed
- validation commands run
- build/test result
- known limitations
- exact PowerShell commands Cody can run locally to verify

## Backend Validation Defaults
Run when relevant:
- git diff --check
- python -m py_compile for changed Python files
- sam validate when template.yaml changes or SAM resources are touched
- focused smoke commands for any changed local tool or API behavior

## Candidate/Lead Finder Rules
- The Discovery Inbox is for reviewed candidate leads.
- Do not import junk automatically.
- Prefer dry-run first.
- Public source discovery only.
- Do not scrape private/logged-in sources.
- For candidate finder/scout work, preserve candidate_import.py compatibility.
- Do not change template.yaml unless absolutely required.
