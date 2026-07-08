"""Scrape Senate PTRs from efdsearch.senate.gov into data/filings.json.

efdsearch.senate.gov geo-blocks non-US connections, so this script is designed
to run in GitHub Actions (US-based runners) on a daily cron — "git scraping".
The committed data/filings.json is the public mirror a Disclosure Tracker
backend ingests from anywhere.

Flow (the site is a Django app behind a DataTables endpoint):
  1. GET  /search/home/  -> csrfmiddlewaretoken
  2. POST /search/home/  with prohibition_agreement=1 -> session unlocked
  3. POST /search/report/data/ (paginated) -> PTR index rows, newest first
  4. GET  each new e-filed PTR page -> parse the transaction <table>
     Paper filings (/search/view/paper/) are scanned images: recorded with
     "paper": true and zero transactions.

Incremental: filings already in data/filings.json are skipped; pagination
stops at the first fully-known page. Run with SCRAPE_FULL=1 to re-walk the
whole window (START_DATE, default 2025-01-01).
"""

import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

BASE = "https://efdsearch.senate.gov"
HOME_URL = f"{BASE}/search/home/"
SEARCH_URL = f"{BASE}/search/"
DATA_URL = f"{BASE}/search/report/data/"
PTR_REPORT_TYPE = 11
PAGE_SIZE = 100
DELAY_SECONDS = 0.5

OUT_FILE = Path(__file__).parent / "data" / "filings.json"
START_DATE = os.environ.get("START_DATE", "01/01/2025 00:00:00")

HEADERS = {
    "User-Agent": "disclosure-tracker senate mirror (public STOCK Act data)",
    "Accept": "application/json, text/javascript, */*",
}


def make_session() -> httpx.Client:
    """Agree to the site's prohibition notice to unlock the search API."""
    client = httpx.Client(headers=HEADERS, timeout=30, follow_redirects=True)
    resp = client.get(HOME_URL)
    resp.raise_for_status()
    token = BeautifulSoup(resp.text, "html.parser").find(
        "input", {"name": "csrfmiddlewaretoken"}
    )
    if token is None:
        raise RuntimeError("No CSRF token on the Senate home page — layout changed?")
    resp = client.post(
        HOME_URL,
        data={"csrfmiddlewaretoken": token["value"], "prohibition_agreement": "1"},
        headers={"Referer": HOME_URL},
    )
    resp.raise_for_status()
    return client


def iter_filing_index(client: httpx.Client):
    """Yield PTR index entries (newest first) from the DataTables endpoint."""
    start = 0
    while True:
        resp = client.post(
            DATA_URL,
            data={
                "start": start,
                "length": PAGE_SIZE,
                "report_types": f"[{PTR_REPORT_TYPE}]",
                "filer_types": "[]",
                "submitted_start_date": START_DATE,
                "submitted_end_date": "",
                "candidate_state": "",
                "senator_state": "",
                "office_id": "",
                "first_name": "",
                "last_name": "",
                "csrfmiddlewaretoken": client.cookies.get("csrftoken", ""),
            },
            headers={"Referer": SEARCH_URL},
        )
        resp.raise_for_status()
        payload = resp.json()
        rows = payload.get("data", [])
        if not rows:
            return

        for first, last, _full, link_html, filed in rows:
            href_match = re.search(r'href="([^"]+)"', link_html)
            if not href_match:
                continue
            href = href_match.group(1)
            yield {
                "id": href.strip("/").split("/")[-1],
                "first": first.strip().title(),
                "last": last.strip().title(),
                "filed": datetime.strptime(filed, "%m/%d/%Y").date().isoformat(),
                "url": f"{BASE}{href}",
                "paper": "/view/paper/" in href,
            }

        start += PAGE_SIZE
        if start >= payload.get("recordsFiltered", 0):
            return
        time.sleep(DELAY_SECONDS)


def parse_report_html(html: str) -> list[dict]:
    """Parse an e-filed PTR page's transaction table.

    Columns: #, tx date, owner, ticker, asset name, asset type, tx type,
    amount, comment.
    """
    table = BeautifulSoup(html, "html.parser").find("table")
    if table is None:
        return []

    transactions = []
    for row in table.find_all("tr")[1:]:
        cols = [td.get_text(" ", strip=True) for td in row.find_all("td")]
        if len(cols) < 8 or not re.match(r"\d{2}/\d{2}/\d{4}", cols[1]):
            continue
        ticker = cols[3].upper()
        transactions.append(
            {
                "date": datetime.strptime(cols[1], "%m/%d/%Y").date().isoformat(),
                "owner": cols[2],
                "ticker": "" if ticker in ("--", "N/A", "") else ticker,
                "asset": cols[4],
                "asset_type": cols[5],
                "type": cols[6],
                "amount": cols[7],
                "comment": cols[8] if len(cols) > 8 else "",
            }
        )
    return transactions


def main() -> None:
    existing: dict[str, dict] = {}
    if OUT_FILE.exists():
        for filing in json.loads(OUT_FILE.read_text(encoding="utf-8"))["filings"]:
            existing[filing["id"]] = filing

    full_walk = os.environ.get("SCRAPE_FULL") == "1"
    client = make_session()
    new_count = unchanged_streak = 0

    for entry in iter_filing_index(client):
        if entry["id"] in existing:
            unchanged_streak += 1
            # Index is newest-first: a full page of known ids means we're done.
            if not full_walk and unchanged_streak >= PAGE_SIZE:
                break
            continue
        unchanged_streak = 0

        transactions = []
        if not entry["paper"]:
            resp = client.get(entry["url"])
            if resp.status_code == 200:
                transactions = parse_report_html(resp.text)
            time.sleep(DELAY_SECONDS)

        existing[entry["id"]] = {**entry, "transactions": transactions}
        new_count += 1

    filings = sorted(existing.values(), key=lambda f: (f["filed"], f["id"]), reverse=True)
    OUT_FILE.parent.mkdir(exist_ok=True)
    OUT_FILE.write_text(
        json.dumps(
            {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "source": "efdsearch.senate.gov",
                "filings": filings,
            },
            indent=1,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"{new_count} new filings, {len(filings)} total -> {OUT_FILE}")


if __name__ == "__main__":
    main()
