\# Project: BuyersBoard / Listly Homes



\## What to optimize for

\- Ship small, safe patches fast. Keep existing design; no framework swaps.

\- Windows + PowerShell workflow.

\- Frontend path: C:\\buyerboard-api\\buyerboard-landing (S3 website bucket buyerboard-public-457532147)

\- Backend path: C:\\buyerboard-api\\app (API base https://2v0q4zm2v6.execute-api.us-east-1.amazonaws.com/dev)

\- HashRouter only (no SSR). Keep assets immutable cache; index.html no-cache.

\- Keep Header links working; “Log in” styled comparable to “Get Started”.

\- Logo file: public/img/horzontal\_logo.png (yes, spelled that way).

\- Don’t wipe pages; change only what’s needed. Provide full files when editing, not diffs.



\## Coding style

\- Plain CSS (no new libs). Clean, minimal patches.

\- For React: keep current file structure. Avoid global breaking changes.



\## PR requirements

\- Branch from `main`. Name like `fix/header-logo-links`.

\- PR must explain \*what changed\* + screenshots (or describe).

\- Include a step list to build and deploy (npm run build → S3 sync).



\## Test/build

\- `npm run build` in C:\\buyerboard-api\\buyerboard-landing



