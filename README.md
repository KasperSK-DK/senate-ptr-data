# senate-ptr-data

Daily mirror of U.S. Senate periodic transaction reports (STOCK Act PTRs) from
[efdsearch.senate.gov](https://efdsearch.senate.gov), scraped by GitHub Actions
and committed to [`data/filings.json`](data/filings.json).

Why this exists: the Senate eFD site geo-blocks non-US connections, so tools
running outside the US can't read it directly. GitHub Actions runners are
US-based; a daily cron re-publishes the public-record data here ("git
scraping"). One JSON object per filing:

```json
{
  "id": "0a1b2c3d-…",
  "first": "Jane", "last": "Doe",
  "filed": "2026-07-01",
  "url": "https://efdsearch.senate.gov/search/view/ptr/0a1b2c3d-…/",
  "paper": false,
  "transactions": [
    {
      "date": "2026-06-15", "owner": "Spouse", "ticker": "NVDA",
      "asset": "NVIDIA Corp Common Stock", "asset_type": "Stock",
      "type": "Purchase", "amount": "$1,001 - $15,000", "comment": ""
    }
  ]
}
```

Paper filings are scanned images with no text layer: `"paper": true`, zero
transactions. The window starts 2025-01-01; runs are incremental. Trigger the
workflow manually ("Run workflow", optionally with *full* checked) for the
first backfill or to heal gaps.

All data is US-government public record. Scraper code is MIT.
