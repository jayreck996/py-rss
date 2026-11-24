ASSET LOG
INSTRUCTION FOR AI MODEL:

ALWAYS ADD NEW ASSET ENTRIES AT THE TOP, DIRECTLY BELOW THIS HEADER.

NEVER DELETE OR EDIT PREVIOUS ASSET ENTRIES.

REQUIRED FORMAT FOR EACH ASSET ENTRY:

## ASSET:{NAME OF ENVIRONMENT} {YYYY-MM-DD HH:MM} → {CONTENT}

## ASSET:py-rss 2026-11-24 → Coinbase date extraction fix and landing page exclusion

**Bug fixes in COINBASE/extractor.py and run_daily.py.**
`discover_listing()` was matching `/blog/landing` as an article URL (regex `^/blog/[^/]+$`). Added `_NON_ARTICLE_SLUGS` exclusion set (`landing`, `index`, etc.) to filter it out.

Added two new date extraction helpers: `_time_element_date()` checks `<time datetime="...">` elements in the JS-rendered DOM; `_rsc_date()` searches the RSC payload for `publishedAt`/`publishDate`/`datePublished` fields. These run after `article:published_time` and JSON-LD checks.

Removed the "default to today" fallback in `run_daily.py` for Coinbase — previously all articles defaulted to today's date, bypassing the 7-day window filter and causing months-old articles (Q1/Q2 earnings, etc.) to appear in the feed. Now only articles with an extractable `published_at` are date-filtered; articles with no date are still saved but without a `pubDate` in the feed.

## ASSET:py-rss 2026-11-24 → stealth patches applied to COINBASE and NINTENDO extractors

**Cloudflare/bot-detection hardening across all four sources.**
Applied full inline stealth JS to `COINBASE/extractor.py` and `NINTENDO/extractor.py` (both `extract()` and `discover_listing()` contexts in each). Patches cover: `navigator.webdriver`, Chrome runtime mock, permissions, plugins, languages, vendor, platform, hardwareConcurrency. Chrome UA updated 125 → 131. Added `--no-sandbox`, `--disable-dev-shm-usage` to Playwright launch args.

COINBASE was already patched from a prior session. NINTENDO was the remaining unpatched source — now updated with `locale="en-AU"` and `timezone_id="Pacific/Auckland"` to match the Nintendo AU site.

All four extractors (ANTHROPIC, OPENAI, COINBASE, NINTENDO) are now on identical stealth configuration.

## ASSET:py-rss 2026-11-24 → schedule consolidation + Cloudflare stealth fix

**Schedule consolidation from py-openai / py-anthropic.**
Added `fetch-openai.yml` and `fetch-anthropic.yml` as standalone scheduled workflows (`0 17 * * *`, 6:00 AM NZDT). Each runs and commits only its own XML subfolder. `daily.yml` remains at `30 17 * * *` as full aggregator + Pages deployer. Schedules in `py-openai` and `py-anthropic` disabled (`workflow_dispatch` only) — both repos marked for retirement.

**NINTENDO added.** `run_daily.py` now covers four sources: ANTHROPIC, OPENAI, COINBASE, NINTENDO.

**Cloudflare bypass (OPENAI extractor).**
Articles from Nov 19–23 were blocked by Cloudflare during Playwright extraction. Fixed by inlining stealth JS patches in `OPENAI/extractor.py`: removes `navigator.webdriver`, mocks Chrome runtime, patches permissions/plugins/languages/vendor/hardwareConcurrency, adds `sec-ch-ua` headers. Chrome UA updated 125 → 131. Same patches applied to `ANTHROPIC/extractor.py` proactively.

**Pages feeds:** `openai.xml` · `anthropic.xml` · `coinbase.xml` · `nintendo.xml` → `https://jayreck996.github.io/py-rss/`

**Secrets required:** `XML_PAT`.

## ASSET:py-rss 2026-11-22 → initial setup; monorepo consolidating py-anthropic, py-openai, py-coinbase

**Repo consolidates all three scrapers into one workflow with per-source failure isolation.**

**Structure:** `ANTHROPIC/`, `OPENAI/`, `COINBASE/` each contain their own extractor, models, and supporting modules. `run_daily.py` orchestrates all three; a failure in one source does not stop the others.

**Discovery:**
- ANTHROPIC: HTTP API (`claude.com/resources/articles` + pagination)
- OPENAI: RSS (`openai.com/news/rss.xml`)
- COINBASE: Playwright listing scrape (`coinbase.com/blog`, `domcontentloaded`)

**Feeds written to `jayreck996/XML` submodule:**
- `XML/ANTHROPIC/XML-2026Q4.xml`
- `XML/OPENAI/XML-2026Q4.xml`
- `XML/COINBASE/XML-2026Q4.xml`
- `XML/COMBINED/XML-2026Q4.xml` (all sources merged, sorted by pubDate)

**Pages serves:** `feed.xml` (combined), `anthropic.xml`, `openai.xml`, `coinbase.xml`

**Secrets required:** `XML_PAT` (global `jayreck996` read-write PAT).

**Individual repos (py-anthropic, py-openai, py-coinbase) remain intact but are superseded by this repo.**
