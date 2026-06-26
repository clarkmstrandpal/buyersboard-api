# Lead Scout Core v1

`tools/candidate_finder.py` is a local, public-source discovery tool for the ListlyHomes Discovery Inbox. PR #8 keeps the original file name, but the behavior is Lead Scout Core v1: a reusable scout that supports vertical-specific query templates and scoring rules, starting with `real_estate`.

The tool does not add an API route, does not change AWS/SAM resources, and does not scrape private or logged-in sites. It only imports when an import URL and Bearer token are explicitly passed.

Source acquisition uses public search result pages and records provider errors when a provider blocks or challenges a query. The current provider order is Mojeek, SearchMySite, then DuckDuckGo Lite fallback.

## Supported Vertical

`real_estate` is the first vertical and the default:

```powershell
python tools/candidate_finder.py --vertical real_estate --market broward-fl --dry-run
```

The vertical structure keeps query templates and scoring terms separate so future verticals such as `mold_remediation`, `public_adjuster`, and `auto_total_loss` can be added without rewriting the search and import pipeline.

## Markets

Supported market slugs come from `tools/market_packs.json`:

- `broward-fl`
- `northwest-ar`

## Real Estate Source Strategies

The `real_estate` vertical supports source-quality strategies through `--source-strategy`:

- `discussion`: prioritizes public human questions and intent posts.
- `marketplace`: targets public marketplace/wanted-post sources such as Craigslist.
- `broad`: broader demand-oriented queries without leaning into listing supply pages.
- `mixed`: default mode combining discussion and marketplace intent searches.

Examples in `discussion` mode include:

- `"{city}" "does anyone know" "rental"`
- `"{city}" "looking for a place"`
- `"{city}" "looking for a house"`
- `"{city}" "need a place"`
- `"{city}" "moving to" "where should I live"`
- `"{city}" "private landlord"`
- `"{city}" "room for rent" "looking"`
- `"{city}" "ISO" "rental"`
- `"{city}" "in search of" "rental"`
- `"{city}" "wanted" "house"`

`--city-limit` controls how many cities are used per market before query generation. `--queries-per-market` applies after all selected-city queries are generated, so it caps the executed query list per market.

## Filtering And Scoring

Lead Scout pre-filters obvious junk before scoring:

- agent directories and profile pages
- Zillow, Realtor, Redfin, Homes, Yelp, YellowPages, and similar directory/listing pages
- SEO guides
- homebuyer programs, grants, mortgage pages, and down-payment-assistance pages
- generic listing pages
- wrong-geography pages
- private or logged-in social sites

Supply/listing domains are denied before candidate creation, including Apartments.com, Zumper, Realtor, Zillow, Redfin, Homes, Compass, ForRent, Rent.com, Apartment Guide, Trulia, Movoto, PropertyShark, Point2Homes, Affordable Housing, Florida Rentals, and Vacation Key.

Use `--ai-score` to score candidates with OpenAI when `OPENAI_API_KEY` is available. If `--ai-score` is not passed, or if the key is missing, the tool uses rule-based scoring.

The scorer keeps only candidates where:

- `is_lead` is `true`
- `confidence` is at least `--min-confidence`
- `location_match` is `true`
- `is_directory_or_ad` is `false`

## Dry Runs

Dry-run output includes raw result count, candidate count after URL dedupe, domain denied count, prefilter rejection count, discussion candidate count, marketplace candidate count, AI skipped prefilter count, AI scored count, kept count, rejected count, provider error count, provider errors, rejection reasons, kept candidates, and rejected examples when requested.

```powershell
python tools/candidate_finder.py --vertical real_estate --market broward-fl --source-strategy discussion --city-limit 3 --queries-per-market 12 --results-per-query 5 --dry-run --show-rejected --debug
python tools/candidate_finder.py --vertical real_estate --market northwest-ar --source-strategy discussion --city-limit 3 --queries-per-market 12 --results-per-query 5 --dry-run --show-rejected --debug
```

Cheap AI-assisted dry run:

```powershell
$env:OPENAI_API_KEY = "YOUR_OPENAI_API_KEY"
python tools/candidate_finder.py --vertical real_estate --market broward-fl --source-strategy discussion --city-limit 3 --queries-per-market 12 --results-per-query 5 --dry-run --ai-score --ai-max-candidates 5 --show-rejected --debug
```

`--debug` adds the cities used, generated query count, executed query count, search queries executed, raw result count per query, first raw titles and URLs before filtering, whether AI scoring was requested/enabled, and whether an OpenAI API key was detected. It does not print the API key.

## Import

Import is never automatic. To POST kept candidates to the existing authenticated Discovery Inbox endpoint, pass both `--import-url` and `--token`:

```powershell
python tools/candidate_finder.py --vertical real_estate --market broward-fl --import-url https://2v0q4zm2v6.execute-api.us-east-1.amazonaws.com/dev/v1/candidates/import --token YOUR_AGENT_TOKEN
```

You can also set the token once:

```powershell
$env:CANDIDATE_IMPORT_TOKEN = "YOUR_AGENT_TOKEN"
python tools/candidate_finder.py --vertical real_estate --market northwest-ar --import-url https://2v0q4zm2v6.execute-api.us-east-1.amazonaws.com/dev/v1/candidates/import
```

## Candidate Shape

Kept candidates remain compatible with `tools/candidate_import.py` and `/v1/candidates/import`. Output includes:

- `title`
- `snippet`
- `message`
- `source`
- `source_url`
- `market`
- `market_slug`
- `county`
- `city`
- `state`
- `vertical`
- `role_guess`
- `intent_guess`
- `intent_score`
- `search_query`
- `contact_method`
- `lead_scout_score`

`source_url` is used for local dedupe before import. The backend import route also dedupes by `source_url`.
