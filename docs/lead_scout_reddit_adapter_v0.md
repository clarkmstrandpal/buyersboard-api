# Lead Scout Reddit Adapter v0

`tools/lead_scout_reddit.py` is a local-only Lead Scout source adapter for public Reddit posts. It uses Reddit OAuth/API access and does not scrape Reddit HTML, use browser automation, or read private/logged-in pages.

The adapter searches public subreddit posts, converts recent matches into Discovery Inbox-compatible candidate objects, then runs the existing Lead Scout prefiltering and scoring path. It imports nothing unless both `--import-url` and `--token` are passed.

## Setup

Set Reddit API credentials in the local shell environment. Do not commit credentials to the repo.

```powershell
$env:REDDIT_CLIENT_ID = "YOUR_CLIENT_ID"
$env:REDDIT_CLIENT_SECRET = "YOUR_CLIENT_SECRET"
$env:REDDIT_USER_AGENT = "ListlyLeadScout/0.1 by YOUR_REDDIT_USERNAME"
```

The adapter uses app-only/client-credentials style read-only access where Reddit allows it.

If credentials are missing, the tool exits cleanly with setup instructions instead of raising a traceback.

## Dry Run Examples

Use the default subreddit/query suggestions for Broward:

```powershell
python tools/lead_scout_reddit.py --market broward-fl --debug --show-rejected
```

Use the default subreddit/query suggestions for Northwest Arkansas:

```powershell
python tools/lead_scout_reddit.py --market northwest-ar --debug --show-rejected
```

Run a smaller test:

```powershell
python tools/lead_scout_reddit.py --market northwest-ar --subreddit FayettevilleAr --query rental --limit 10 --max-age-days 14 --debug --show-rejected
```

Defaults:

- Broward subreddits: `fortlauderdale`, `SouthFlorida`.
- Northwest Arkansas subreddits: `FayettevilleAr`, `Arkansas`.
- Queries: `moving`, `rent`, `rental`, `apartment`, `landlord`, `where should I live`, `looking for a place`.
- `--limit`: `25`.
- `--max-age-days`: `14`.
- `--min-score`: `0`.

## Candidate Fields

The adapter extracts:

- `title`
- `selftext` as snippet/message
- `permalink` as `source_url`
- `created_utc` as `source_post_date`
- `subreddit`
- `score`
- `num_comments`

Candidates include:

- `source = reddit`
- `source_adapter = reddit`
- `source_category = discussion`
- `market_slug`
- market city/county/state from `tools/market_packs.json`

## Import Warning

Dry-run first. Review kept candidates before importing.

Import is explicit only:

```powershell
python tools/lead_scout_reddit.py --market northwest-ar --subreddit FayettevilleAr --query rental --import-url https://2v0q4zm2v6.execute-api.us-east-1.amazonaws.com/dev/v1/candidates/import --token YOUR_AGENT_TOKEN
```

## Limitations

- This is public subreddit post search only.
- It does not read private communities, logged-in-only content, chats, or direct messages.
- It does not scrape Reddit HTML; direct Reddit HTML may return verification pages and should remain out of this adapter.
- Reddit ranking/search behavior can miss posts or return weak matches.
- Comment-level discovery is not included in v0.
- Marketplace/Craigslist adapters are not included in this PR.
