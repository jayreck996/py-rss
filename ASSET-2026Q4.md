ASSET LOG
INSTRUCTION FOR AI MODEL:

ALWAYS ADD NEW ASSET ENTRIES AT THE TOP, DIRECTLY BELOW THIS HEADER.

NEVER DELETE OR EDIT PREVIOUS ASSET ENTRIES.

REQUIRED FORMAT FOR EACH ASSET ENTRY:

## ASSET:{NAME OF ENVIRONMENT} {YYYY-MM-DD HH:MM} → {CONTENT}

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
