#!/usr/bin/env python3
"""
Species Popularity Ranker

Analyzes Wikipedia bulk dumps to rank species by:
1. Incoming wikilinks (backlinks)
2. Page views

Data sources:
- Wikidata SPARQL: Get list of species with Wikipedia articles
- Wikipedia pagelinks SQL dump: Count incoming links
- Wikimedia pageview dumps: Count page views

Usage:
    python species_popularity.py --step 1  # Fetch species list from Wikidata
    python species_popularity.py --step 2  # Download and process pagelinks dump
    python species_popularity.py --step 3  # Download and process pageview dumps
    python species_popularity.py --step 4  # Combine metrics and produce ranking
    python species_popularity.py --all     # Run all steps
"""

import argparse
import bz2
import gzip
import json
import os
import re
import sqlite3
import subprocess
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterator

import requests

# Configuration
DATA_DIR = Path("./data")
SPECIES_DB = DATA_DIR / "species.db"
SPECIES_LIST_FILE = DATA_DIR / "species_titles.json"
RESULTS_FILE = DATA_DIR / "species_rankings.csv"

# Wikipedia dump mirror (you can change to a closer mirror)
DUMP_MIRROR = "https://dumps.wikimedia.org"
WIKI_LANG = "enwiki"


def setup_dirs():
    """Create necessary directories."""
    DATA_DIR.mkdir(exist_ok=True)


def init_database():
    """Initialize SQLite database for storing results."""
    conn = sqlite3.connect(SPECIES_DB)
    c = conn.cursor()
    
    c.execute("""
        CREATE TABLE IF NOT EXISTS species (
            page_id INTEGER PRIMARY KEY,
            title TEXT UNIQUE,
            wikidata_id TEXT,
            backlink_count INTEGER DEFAULT 0,
            pageview_count INTEGER DEFAULT 0
        )
    """)
    
    c.execute("CREATE INDEX IF NOT EXISTS idx_title ON species(title)")
    
    conn.commit()
    return conn


# =============================================================================
# Step 1: Fetch species list from Wikidata
# =============================================================================

WIKIDATA_SPARQL_ENDPOINT = "https://query.wikidata.org/sparql"

def fetch_species_from_wikidata(batch_size: int = 5000, max_retries: int = 3, max_species: int | None = None) -> list[dict]:
    """
    Fetch all species with English Wikipedia articles from Wikidata.
    Uses pagination to handle the large result set.
    
    Note: Wikidata SPARQL has a default timeout of 60 seconds and limits on
    result sizes. We use smaller batches and retry logic to handle this.
    """
    species_list = []
    offset = 0
    consecutive_failures = 0
    
    while consecutive_failures < max_retries:
        print(f"Fetching species batch starting at offset {offset}...")
        
        # Query for taxons at species rank (Q7432) with English Wikipedia articles
        # Using a simpler query without SERVICE for labels (faster)
        query = f"""
        SELECT ?species ?article WHERE {{
          ?species wdt:P31 wd:Q16521 ;      # instance of taxon
                   wdt:P105 wd:Q7432 .       # taxon rank = species
          ?article schema:about ?species ;
                   schema:isPartOf <https://en.wikipedia.org/> .
        }}
        LIMIT {batch_size}
        OFFSET {offset}
        """
        
        try:
            response = requests.get(
                WIKIDATA_SPARQL_ENDPOINT,
                params={"query": query, "format": "json"},
                headers={
                    "User-Agent": "TaxonomicaBot/1.0 (https://github.com/taxonomica; educational project)",
                    "Accept": "application/sparql-results+json"
                },
                timeout=120
            )
            response.raise_for_status()
            
            # Check if response is actually JSON
            content_type = response.headers.get('content-type', '')
            if 'json' not in content_type:
                print(f"  Warning: Unexpected content-type: {content_type}")
                print(f"  Response preview: {response.text[:500]}")
                consecutive_failures += 1
                continue
            
            data = response.json()
            consecutive_failures = 0  # Reset on success
            
        except requests.exceptions.Timeout:
            print(f"  Query timed out at offset {offset}. Retrying with smaller batch...")
            consecutive_failures += 1
            # Try with smaller batch on timeout
            if batch_size > 1000:
                batch_size = batch_size // 2
                print(f"  Reduced batch size to {batch_size}")
            continue
        except json.JSONDecodeError as e:
            print(f"  JSON decode error: {e}")
            print(f"  Response preview: {response.text[:1000] if response else 'No response'}")
            consecutive_failures += 1
            # Try with smaller batch
            if batch_size > 1000:
                batch_size = batch_size // 2
                print(f"  Reduced batch size to {batch_size}")
            continue
        except requests.exceptions.RequestException as e:
            print(f"  Request error: {e}")
            consecutive_failures += 1
            time.sleep(5)  # Wait before retry
            continue
        
        results = data.get("results", {}).get("bindings", [])
        
        if not results:
            print("No more results.")
            break
        
        for item in results:
            article_url = item.get("article", {}).get("value", "")
            # Extract article title from URL
            if "/wiki/" in article_url:
                title = urllib.parse.unquote(article_url.split("/wiki/")[-1])
                species_list.append({
                    "title": title,
                    "wikidata_id": item.get("species", {}).get("value", "").split("/")[-1],
                    "label": title.replace("_", " ")  # Use title as label
                })
        
        print(f"  Fetched {len(results)} species (total: {len(species_list)})")
        
        # Check if we've reached the limit
        if max_species and len(species_list) >= max_species:
            print(f"Reached limit of {max_species} species.")
            species_list = species_list[:max_species]  # Trim to exact limit
            break
        
        if len(results) < batch_size:
            print("Received fewer results than batch size, likely at end of data.")
            break
            
        offset += batch_size
        
        # Be nice to the API
        time.sleep(1)
    
    if consecutive_failures >= max_retries:
        print(f"Failed after {max_retries} consecutive failures. Returning partial results.")
    
    return species_list


def step1_fetch_species(max_species: int | None = None):
    """Step 1: Fetch species list and store in database."""
    print("=" * 60)
    print("Step 1: Fetching species list from Wikidata")
    if max_species:
        print(f"  (Limited to {max_species} species for debugging)")
    print("=" * 60)
    
    setup_dirs()
    
    # This can take 30+ minutes due to the large number of species
    species_list = fetch_species_from_wikidata(max_species=max_species)
    
    print(f"\nTotal species fetched: {len(species_list)}")
    
    # Save to JSON as backup
    with open(SPECIES_LIST_FILE, "w") as f:
        json.dump(species_list, f)
    print(f"Saved species list to {SPECIES_LIST_FILE}")
    
    # Insert into database
    conn = init_database()
    c = conn.cursor()
    
    # Clear existing data
    c.execute("DELETE FROM species")
    
    # Insert species
    for i, species in enumerate(species_list):
        c.execute(
            "INSERT OR IGNORE INTO species (title, wikidata_id) VALUES (?, ?)",
            (species["title"], species["wikidata_id"])
        )
        if (i + 1) % 100000 == 0:
            print(f"  Inserted {i + 1} species...")
            conn.commit()
    
    conn.commit()
    conn.close()
    
    print(f"Inserted species into database at {SPECIES_DB}")


# =============================================================================
# Step 2: Process pagelinks dump for backlink counts
# =============================================================================

def get_latest_dump_date() -> str:
    """Find the most recent complete dump date."""
    url = f"{DUMP_MIRROR}/{WIKI_LANG}/"
    print(f"  Checking {url}")
    response = requests.get(url)
    
    # Find dates in format YYYYMMDD
    dates = re.findall(r"(\d{8})/", response.text)
    dates = sorted(set(dates), reverse=True)
    print(f"  Found {len(dates)} dump dates, checking latest: {dates[:5]}")
    
    # Check for complete dump (has pagelinks)
    for date in dates[:10]:  # Check last 10
        status_url = f"{DUMP_MIRROR}/{WIKI_LANG}/{date}/dumpstatus.json"
        try:
            status_resp = requests.get(status_url)
            if status_resp.status_code != 200:
                print(f"    {date}: No status file")
                continue
            status = status_resp.json()
            jobs = status.get("jobs", {})
            
            # Try different possible job names for pagelinks
            pagelinks_status = None
            for job_name in ["pagelinks", "pagelinkstable", "articlelinks"]:
                if job_name in jobs:
                    pagelinks_status = jobs[job_name].get("status")
                    if pagelinks_status == "done":
                        print(f"    {date}: Found completed {job_name}")
                        return date
                    else:
                        print(f"    {date}: {job_name} status = {pagelinks_status}")
            
            # If no pagelinks job found, check if this is a complete dump
            if not pagelinks_status:
                # Check for any completed SQL dumps we could use
                available_jobs = [k for k, v in jobs.items() if v.get("status") == "done"]
                print(f"    {date}: No pagelinks found. Available: {available_jobs[:5]}...")
                
        except Exception as e:
            print(f"    {date}: Error - {e}")
            continue
    
    raise RuntimeError("Could not find a complete dump with pagelinks. "
                       "Try using --step 3 to skip pagelinks and use pageviews only.")


def download_file(url: str, dest: Path, chunk_size: int = 8192):
    """Download a file with progress indicator."""
    if dest.exists():
        print(f"  File already exists: {dest}")
        return
    
    print(f"  Downloading {url}")
    response = requests.get(url, stream=True)
    total_size = int(response.headers.get("content-length", 0))
    
    downloaded = 0
    with open(dest, "wb") as f:
        for chunk in response.iter_content(chunk_size=chunk_size):
            f.write(chunk)
            downloaded += len(chunk)
            if total_size:
                pct = downloaded / total_size * 100
                print(f"\r  Progress: {pct:.1f}% ({downloaded // 1024 // 1024} MB)", end="")
    print()


def stream_pagelinks_dump(dump_path: Path) -> Iterator[tuple[int, str]]:
    """
    Stream pagelinks dump and yield (from_page_id, to_title) tuples.
    
    The pagelinks table format is:
    INSERT INTO `pagelinks` VALUES (from_id, from_namespace, to_title, to_namespace)
    """
    print(f"  Streaming {dump_path}...")
    
    # Pattern to match INSERT statements and extract values
    insert_pattern = re.compile(r"\((\d+),(\d+),'([^']*)',(\d+)\)")
    
    open_func = gzip.open if dump_path.suffix == ".gz" else open
    
    with open_func(dump_path, "rt", encoding="utf-8", errors="replace") as f:
        for line in f:
            if not line.startswith("INSERT INTO"):
                continue
            
            # Find all value tuples in this INSERT statement
            for match in insert_pattern.finditer(line):
                from_id = int(match.group(1))
                from_ns = int(match.group(2))
                to_title = match.group(3).replace("\\'", "'").replace("_", " ")
                to_ns = int(match.group(4))
                
                # Only count links from main namespace (0) to main namespace (0)
                if from_ns == 0 and to_ns == 0:
                    yield (from_id, to_title)


def step2_process_pagelinks():
    """Step 2: Download and process pagelinks dump."""
    print("=" * 60)
    print("Step 2: Processing pagelinks dump for backlink counts")
    print("=" * 60)
    
    setup_dirs()
    
    # Load species titles into a set for fast lookup
    conn = sqlite3.connect(SPECIES_DB)
    c = conn.cursor()
    c.execute("SELECT title FROM species")
    species_titles = {row[0].replace("_", " ") for row in c.fetchall()}
    print(f"Loaded {len(species_titles)} species titles")
    
    if not species_titles:
        print("ERROR: No species in database. Run step 1 first.")
        return
    
    # Find latest dump
    print("Finding latest dump...")
    dump_date = get_latest_dump_date()
    print(f"Using dump from {dump_date}")
    
    # Download pagelinks dump
    pagelinks_url = f"{DUMP_MIRROR}/{WIKI_LANG}/{dump_date}/{WIKI_LANG}-{dump_date}-pagelinks.sql.gz"
    pagelinks_file = DATA_DIR / f"pagelinks-{dump_date}.sql.gz"
    
    print(f"Downloading pagelinks dump (~5GB compressed)...")
    download_file(pagelinks_url, pagelinks_file)
    
    # Count backlinks to species pages
    print("Counting backlinks to species pages...")
    backlink_counts = defaultdict(int)
    processed = 0
    
    for from_id, to_title in stream_pagelinks_dump(pagelinks_file):
        # Normalize title for comparison
        normalized = to_title.replace("_", " ")
        if normalized in species_titles:
            backlink_counts[normalized] += 1
        
        processed += 1
        if processed % 10_000_000 == 0:
            print(f"  Processed {processed // 1_000_000}M links, found {len(backlink_counts)} species with backlinks")
    
    print(f"Total links processed: {processed}")
    print(f"Species with backlinks: {len(backlink_counts)}")
    
    # Update database
    print("Updating database with backlink counts...")
    for title, count in backlink_counts.items():
        c.execute(
            "UPDATE species SET backlink_count = ? WHERE title = ?",
            (count, title)
        )
    
    conn.commit()
    conn.close()
    print("Done updating backlink counts.")


# =============================================================================
# Step 3: Get pageviews via Wikimedia API (recommended)
# =============================================================================

PAGEVIEW_API_BASE = "https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article"


def get_pageviews_for_article(title: str, months: int = 12) -> int:
    """
    Get total pageviews for a Wikipedia article using the Wikimedia API.
    
    API docs: https://wikimedia.org/api/rest_v1/
    """
    # Calculate date range
    end_date = datetime.now()
    start_date = end_date - timedelta(days=30 * months)
    
    # Format dates as YYYYMMDD
    start_str = start_date.strftime("%Y%m%d")
    end_str = end_date.strftime("%Y%m%d")
    
    # URL-encode the title (spaces -> underscores, then URL encode)
    encoded_title = urllib.parse.quote(title.replace(" ", "_"), safe="")
    
    # Build API URL
    # Format: /per-article/{project}/{access}/{agent}/{article}/{granularity}/{start}/{end}
    url = f"{PAGEVIEW_API_BASE}/en.wikipedia/all-access/user/{encoded_title}/monthly/{start_str}/{end_str}"
    
    try:
        response = requests.get(
            url,
            headers={"User-Agent": "TaxonomicaBot/1.0 (educational project)"},
            timeout=10
        )
        
        if response.status_code == 404:
            # Article not found or no pageview data
            return 0
        
        response.raise_for_status()
        data = response.json()
        
        # Sum up all monthly views
        total_views = sum(item.get("views", 0) for item in data.get("items", []))
        return total_views
        
    except Exception:
        return 0


def step3_process_pageviews_api(months: int = 12, batch_size: int = 100):
    """
    Step 3: Get pageviews via Wikimedia REST API.
    
    This queries the API directly for each species, which is slower but
    more reliable than processing dump files.
    """
    print("=" * 60)
    print(f"Step 3: Fetching pageviews via Wikimedia API (last {months} months)")
    print("=" * 60)
    
    setup_dirs()
    
    # Load species titles
    conn = sqlite3.connect(SPECIES_DB)
    c = conn.cursor()
    c.execute("SELECT title FROM species WHERE pageview_count = 0 OR pageview_count IS NULL")
    species_to_process = [row[0] for row in c.fetchall()]
    
    c.execute("SELECT COUNT(*) FROM species WHERE pageview_count > 0")
    already_done = c.fetchone()[0]
    
    print(f"Species to process: {len(species_to_process):,}")
    print(f"Already have data for: {already_done:,}")
    
    if not species_to_process:
        print("All species already have pageview data!")
        return
    
    # Process in batches with progress
    total = len(species_to_process)
    processed = 0
    updated = 0
    
    print(f"\nFetching pageviews (this may take a while for large datasets)...")
    print(f"  Rate: ~{batch_size} requests, then 1 second pause")
    
    start_time = time.time()
    
    for i, title in enumerate(species_to_process):
        views = get_pageviews_for_article(title, months=months)
        
        if views > 0:
            c.execute(
                "UPDATE species SET pageview_count = ? WHERE title = ?",
                (views, title)
            )
            updated += 1
        
        processed += 1
        
        # Progress update every batch_size items
        if processed % batch_size == 0:
            elapsed = time.time() - start_time
            rate = processed / elapsed if elapsed > 0 else 0
            eta = (total - processed) / rate if rate > 0 else 0
            
            print(f"  Processed {processed:,}/{total:,} ({100*processed/total:.1f}%) - "
                  f"{updated:,} with views - "
                  f"ETA: {eta/60:.1f} min")
            
            # Commit periodically
            conn.commit()
            
            # Rate limiting - be nice to the API
            time.sleep(1)
    
    conn.commit()
    conn.close()
    
    elapsed = time.time() - start_time
    print(f"\nDone! Processed {processed:,} species in {elapsed/60:.1f} minutes")
    print(f"  Species with pageviews: {updated:,}")


# =============================================================================
# Step 3 Alternative: Process monthly dump files
# =============================================================================

def get_monthly_pageview_url(year: int, month: int) -> str | None:
    """
    Get URL for the monthly aggregated pageview dump.
    
    These are pre-aggregated files with total views per article per month.
    Much more efficient than processing hourly dumps.
    
    Location: https://dumps.wikimedia.org/other/pageview_complete/
    Format: pageviews-YYYYMM-user.bz2 (user views, excluding bots)
    """
    # Monthly aggregated dumps location
    base_url = f"{DUMP_MIRROR}/other/pageview_complete/{year}/{year}-{month:02d}/"
    
    try:
        response = requests.get(base_url)
        if response.status_code != 200:
            print(f"  Could not access {base_url}")
            return None
        
        # Look for the user pageview file (excludes bots/spiders)
        # Format: pageviews-YYYYMM-user.bz2
        pattern = rf'pageviews-{year}{month:02d}-user\.bz2'
        match = re.search(pattern, response.text)
        
        if match:
            return f"{base_url}{match.group(0)}"
        
        # Fallback: look for any monthly file
        files = re.findall(r'pageviews-\d{6}-\w+\.bz2', response.text)
        if files:
            # Prefer 'user' file, then 'all-sites'
            for f in files:
                if 'user' in f:
                    return f"{base_url}{f}"
            return f"{base_url}{files[0]}"
            
    except Exception as e:
        print(f"  Error fetching monthly dump list: {e}")
    
    return None


def process_monthly_pageview_file(filepath: Path, species_titles: set) -> dict[str, int]:
    """
    Process a monthly aggregated pageview dump file.
    
    Format (tab-separated):
    wiki_code  article_title  [device_type]  monthly_total  [daily_counts...]
    
    Example:
    en.wikipedia  Cat  desktop  1234567  ...
    """
    counts = defaultdict(int)
    processed = 0
    matched = 0
    
    print(f"  Processing {filepath.name}...")
    
    try:
        with bz2.open(filepath, "rt", encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    parts = line.strip().split(" ")
                    
                    if len(parts) < 3:
                        continue
                    
                    wiki_code = parts[0]
                    
                    # Only count English Wikipedia (main namespace)
                    # Format is like "en.wikipedia" or "en.m.wikipedia"
                    if not wiki_code.startswith("en."):
                        continue
                    if wiki_code not in ("en.wikipedia", "en.m.wikipedia"):
                        continue
                    
                    # Title is the second field
                    title = urllib.parse.unquote(parts[1]).replace("_", " ")
                    
                    # Monthly total is typically the 3rd or 4th field
                    # Try to find the numeric total
                    monthly_total = 0
                    for part in parts[2:5]:
                        try:
                            monthly_total = int(part)
                            break
                        except ValueError:
                            continue
                    
                    if title in species_titles:
                        counts[title] += monthly_total
                        matched += 1
                    
                    processed += 1
                    if processed % 5_000_000 == 0:
                        print(f"    Processed {processed // 1_000_000}M lines, matched {matched} species...")
                        
                except Exception:
                    continue
                    
    except Exception as e:
        print(f"  Error processing file: {e}")
    
    print(f"  Finished: {processed:,} lines processed, {len(counts):,} unique species matched")
    return counts


def download_monthly_dump(url: str, dest: Path) -> bool:
    """Download a monthly pageview dump with progress."""
    if dest.exists():
        print(f"  File already exists: {dest}")
        return True
    
    print(f"  Downloading {url}")
    print(f"  (This file is ~2-4 GB, may take a while...)")
    
    try:
        response = requests.get(url, stream=True, timeout=30)
        response.raise_for_status()
        total_size = int(response.headers.get("content-length", 0))
        
        downloaded = 0
        with open(dest, "wb") as f:
            for chunk in response.iter_content(chunk_size=1024 * 1024):  # 1MB chunks
                f.write(chunk)
                downloaded += len(chunk)
                if total_size:
                    pct = downloaded / total_size * 100
                    print(f"\r  Progress: {pct:.1f}% ({downloaded // 1024 // 1024} MB / {total_size // 1024 // 1024} MB)", end="", flush=True)
        print()  # Newline after progress
        return True
    except Exception as e:
        print(f"\n  Download failed: {e}")
        if dest.exists():
            dest.unlink()  # Remove partial download
        return False


def step3_process_pageviews_monthly(months: int = 3):
    """
    Step 3: Process monthly aggregated pageview dumps.
    
    Uses pre-aggregated monthly files which are much more efficient
    than processing hourly dumps.
    """
    print("=" * 60)
    print(f"Step 3: Processing monthly pageview dumps (last {months} months)")
    print("=" * 60)
    
    setup_dirs()
    
    # Load species titles
    conn = sqlite3.connect(SPECIES_DB)
    c = conn.cursor()
    c.execute("SELECT title FROM species")
    species_titles = {row[0].replace("_", " ") for row in c.fetchall()}
    print(f"Loaded {len(species_titles):,} species titles")
    
    if not species_titles:
        print("ERROR: No species in database. Run step 1 first.")
        return
    
    # Show sample titles for debugging
    sample_titles = list(species_titles)[:5]
    print(f"  Sample titles: {sample_titles}")
    
    # Aggregate pageview counts across months
    total_counts = defaultdict(int)
    months_processed = 0
    
    # Process each month (going backwards from current)
    now = datetime.now()
    for i in range(months):
        # Go back by months
        date = now - timedelta(days=30 * (i + 1))  # +1 to skip current incomplete month
        year, month = date.year, date.month
        
        print(f"\nLooking for {year}-{month:02d} dump...")
        url = get_monthly_pageview_url(year, month)
        
        if not url:
            print(f"  No monthly dump found for {year}-{month:02d}")
            continue
        
        print(f"  Found: {url.split('/')[-1]}")
        
        # Download to local file
        local_file = DATA_DIR / f"pageviews-{year}{month:02d}-user.bz2"
        
        if not download_monthly_dump(url, local_file):
            continue
        
        # Process the file
        month_counts = process_monthly_pageview_file(local_file, species_titles)
        
        for title, count in month_counts.items():
            total_counts[title] += count
        
        months_processed += 1
        print(f"  Running total: {len(total_counts):,} species with pageviews")
    
    if months_processed == 0:
        print("\nERROR: Could not process any monthly dumps.")
        print("The monthly dumps may not be available for recent months.")
        print("Try using --use-hourly to fall back to hourly dumps.")
        return
    
    # Update database
    print(f"\nUpdating database with pageview counts...")
    print(f"  Total species with pageviews: {len(total_counts):,}")
    
    for title, count in total_counts.items():
        c.execute(
            "UPDATE species SET pageview_count = ? WHERE title = ?",
            (count, title)
        )
    
    conn.commit()
    conn.close()
    print(f"Done! Updated {len(total_counts):,} species with pageview data.")


# Legacy hourly dump functions (kept for --use-hourly fallback)
def get_pageview_dump_urls(year: int, month: int) -> list[str]:
    """Get URLs for hourly pageview dumps for a given month."""
    urls = []
    
    # Pageviews are stored in hourly files
    # Format: pageviews-YYYYMMDD-HHMMSS.gz
    base_url = f"{DUMP_MIRROR}/other/pageviews/{year}/{year}-{month:02d}/"
    
    try:
        response = requests.get(base_url)
        # Find all pageview files
        files = re.findall(r'pageviews-\d{8}-\d{6}\.gz', response.text)
        urls = [f"{base_url}{f}" for f in sorted(set(files))]
    except Exception as e:
        print(f"Error fetching pageview list: {e}")
    
    return urls


def process_pageview_file(url: str, species_titles: set) -> dict[str, int]:
    """
    Process a single pageview dump file.
    
    Format: domain page_title view_count response_size
    Example: en.wikipedia Dog 12345 0
    """
    counts = defaultdict(int)
    
    try:
        response = requests.get(url, stream=True, timeout=60)
        
        with gzip.GzipFile(fileobj=response.raw) as f:
            for line in f:
                try:
                    line = line.decode("utf-8")
                    parts = line.strip().split(" ")
                    
                    if len(parts) < 3:
                        continue
                    
                    domain, title, views = parts[0], parts[1], parts[2]
                    
                    # Only count English Wikipedia main namespace
                    if domain not in ("en", "en.wikipedia", "en.m.wikipedia"):
                        continue
                    
                    # Normalize title
                    title = urllib.parse.unquote(title).replace("_", " ")
                    
                    if title in species_titles:
                        counts[title] += int(views)
                        
                except Exception:
                    continue
                    
    except Exception as e:
        print(f"  Error processing {url}: {e}")
    
    return counts


def step3_process_pageviews(months: int = 12, samples_per_day: int = 1):
    """Step 3: Download and process pageview dumps."""
    print("=" * 60)
    print(f"Step 3: Processing pageview dumps (last {months} months)")
    print(f"  Sampling {samples_per_day} file(s) per day")
    print("=" * 60)
    
    setup_dirs()
    
    # Load species titles
    conn = sqlite3.connect(SPECIES_DB)
    c = conn.cursor()
    c.execute("SELECT title FROM species")
    species_titles = {row[0].replace("_", " ") for row in c.fetchall()}
    print(f"Loaded {len(species_titles)} species titles")
    
    # Show sample titles for debugging
    sample_titles = list(species_titles)[:5]
    print(f"  Sample titles: {sample_titles}")
    
    if not species_titles:
        print("ERROR: No species in database. Run step 1 first.")
        return
    
    # Aggregate pageview counts
    total_counts = defaultdict(int)
    
    # Process each month
    now = datetime.now()
    for i in range(months):
        date = now - timedelta(days=30 * i)
        year, month = date.year, date.month
        
        print(f"\nProcessing {year}-{month:02d}...")
        urls = get_pageview_dump_urls(year, month)
        
        if not urls:
            print(f"  No pageview files found for {year}-{month:02d}")
            continue
        
        print(f"  Found {len(urls)} hourly dump files")
        
        # Process a sample based on samples_per_day
        # 24 hourly files per day, so step = 24 / samples_per_day
        step = max(1, 24 // samples_per_day)
        sample_urls = urls[::step]
        print(f"  Processing {len(sample_urls)} samples (every {step} hours)...")
        
        for j, url in enumerate(sample_urls):
            counts = process_pageview_file(url, species_titles)
            for title, count in counts.items():
                total_counts[title] += count
            
            if (j + 1) % 5 == 0:
                print(f"    Processed {j + 1}/{len(sample_urls)} files")
    
    # Scale up counts (since we sampled)
    # We took samples_per_day samples per day, so multiply to estimate full day
    scale_factor = max(1, 24 // samples_per_day)
    print(f"\nUpdating database with pageview counts (scale factor: {scale_factor}x)...")
    print(f"  Species with pageviews found: {len(total_counts)}")
    for title, count in total_counts.items():
        estimated_count = count * scale_factor
        c.execute(
            "UPDATE species SET pageview_count = ? WHERE title = ?",
            (estimated_count, title)
        )
    
    conn.commit()
    conn.close()
    print(f"Updated pageview counts for {len(total_counts)} species.")


# =============================================================================
# Step 4: Combine metrics and produce rankings
# =============================================================================

def step4_produce_rankings(top_n: int = 5000):
    """Step 4: Combine metrics and output final rankings."""
    print("=" * 60)
    print(f"Step 4: Producing top {top_n} species rankings")
    print("=" * 60)
    
    conn = sqlite3.connect(SPECIES_DB)
    c = conn.cursor()
    
    # Print diagnostic statistics
    c.execute("SELECT COUNT(*) FROM species")
    total_species = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM species WHERE pageview_count > 0")
    species_with_pageviews = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM species WHERE backlink_count > 0")
    species_with_backlinks = c.fetchone()[0]
    
    print(f"\nDatabase statistics:")
    print(f"  Total species in database: {total_species:,}")
    print(f"  Species with pageview data: {species_with_pageviews:,} ({100*species_with_pageviews/total_species:.1f}%)")
    print(f"  Species with backlink data: {species_with_backlinks:,} ({100*species_with_backlinks/total_species:.1f}%)")
    
    # Get statistics for normalization
    c.execute("SELECT MAX(backlink_count), MAX(pageview_count) FROM species")
    max_backlinks, max_pageviews = c.fetchone()
    
    # Handle case where only one metric is available
    if not max_backlinks and not max_pageviews:
        print("ERROR: No data found. Run steps 2 and/or 3 first.")
        return
    
    # Default to 1 if a metric is missing to avoid division errors
    max_backlinks = max_backlinks or 1
    max_pageviews = max_pageviews or 1
    
    has_backlinks = max_backlinks > 1
    has_pageviews = max_pageviews > 1
    
    print(f"Max backlinks: {max_backlinks}" + (" (no data)" if not has_backlinks else ""))
    print(f"Max pageviews: {max_pageviews}" + (" (no data)" if not has_pageviews else ""))
    
    # Calculate combined score based on available data
    if has_backlinks and has_pageviews:
        # Both metrics available - use 50/50 weighting
        query = """
            SELECT 
                title,
                wikidata_id,
                backlink_count,
                pageview_count,
                (CAST(backlink_count AS REAL) / ? * 0.5 + 
                 CAST(pageview_count AS REAL) / ? * 0.5) AS combined_score
            FROM species
            WHERE backlink_count > 0 OR pageview_count > 0
            ORDER BY combined_score DESC
            LIMIT ?
        """
        params = (max_backlinks, max_pageviews, top_n)
    elif has_pageviews:
        # Only pageviews available
        print("Note: Using pageviews only (no backlink data)")
        query = """
            SELECT 
                title,
                wikidata_id,
                backlink_count,
                pageview_count,
                CAST(pageview_count AS REAL) / ? AS combined_score
            FROM species
            WHERE pageview_count > 0
            ORDER BY combined_score DESC
            LIMIT ?
        """
        params = (max_pageviews, top_n)
    else:
        # Only backlinks available
        print("Note: Using backlinks only (no pageview data)")
        query = """
            SELECT 
                title,
                wikidata_id,
                backlink_count,
                pageview_count,
                CAST(backlink_count AS REAL) / ? AS combined_score
            FROM species
            WHERE backlink_count > 0
            ORDER BY combined_score DESC
            LIMIT ?
        """
        params = (max_backlinks, top_n)
    
    c.execute(query, params)
    
    results = c.fetchall()
    
    # Write to CSV
    with open(RESULTS_FILE, "w") as f:
        f.write("rank,title,wikidata_id,backlink_count,pageview_count,combined_score\n")
        for i, (title, wikidata_id, backlinks, pageviews, score) in enumerate(results, 1):
            # Escape commas in title
            safe_title = f'"{title}"' if "," in title else title
            f.write(f"{i},{safe_title},{wikidata_id},{backlinks},{pageviews},{score:.6f}\n")
    
    print(f"\nTop 20 species:")
    print("-" * 80)
    print(f"{'Rank':<6} {'Title':<40} {'Backlinks':<12} {'Pageviews':<12}")
    print("-" * 80)
    for i, (title, wikidata_id, backlinks, pageviews, score) in enumerate(results[:20], 1):
        print(f"{i:<6} {title[:38]:<40} {backlinks:<12} {pageviews:<12}")
    
    print(f"\nFull results saved to {RESULTS_FILE}")
    conn.close()


# =============================================================================
# Main
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description="Rank species by Wikipedia popularity")
    parser.add_argument("--step", type=int, choices=[1, 2, 3, 4], 
                        help="Run specific step (1-4)")
    parser.add_argument("--all", action="store_true", 
                        help="Run all steps")
    parser.add_argument("--months", type=int, default=12,
                        help="Number of months of pageview data to process (default: 12)")
    parser.add_argument("--top", type=int, default=5000,
                        help="Number of top species to output (default: 5000)")
    parser.add_argument("--limit", type=int, default=None,
                        help="Limit species to fetch in step 1 (for debugging, e.g. --limit 50000)")
    parser.add_argument("--skip-pagelinks", action="store_true",
                        help="Skip step 2 (pagelinks dump) - uses only pageviews for ranking")
    parser.add_argument("--samples-per-day", type=int, default=1,
                        help="Pageview samples per day when using --use-hourly (1-24)")
    parser.add_argument("--use-api", action="store_true", default=True,
                        help="Use Wikimedia API for pageviews (default, most reliable)")
    parser.add_argument("--use-monthly-dumps", action="store_true",
                        help="Use monthly aggregated dump files instead of API")
    parser.add_argument("--use-hourly", action="store_true",
                        help="Use hourly pageview dumps (slowest, most granular)")
    
    args = parser.parse_args()
    
    if args.all:
        step1_fetch_species(max_species=args.limit)
        if not args.skip_pagelinks:
            step2_process_pagelinks()
        else:
            print("\n" + "=" * 60)
            print("Step 2: SKIPPED (--skip-pagelinks)")
            print("=" * 60)
        if args.use_hourly:
            step3_process_pageviews(months=args.months, samples_per_day=args.samples_per_day)
        elif args.use_monthly_dumps:
            step3_process_pageviews_monthly(months=args.months)
        else:
            step3_process_pageviews_api(months=args.months)
        step4_produce_rankings(top_n=args.top)
    elif args.step == 1:
        step1_fetch_species(max_species=args.limit)
    elif args.step == 2:
        step2_process_pagelinks()
    elif args.step == 3:
        if args.use_hourly:
            step3_process_pageviews(months=args.months, samples_per_day=args.samples_per_day)
        elif args.use_monthly_dumps:
            step3_process_pageviews_monthly(months=args.months)
        else:
            step3_process_pageviews_api(months=args.months)
    elif args.step == 4:
        step4_produce_rankings(top_n=args.top)
    else:
        parser.print_help()
        print("\nExample usage:")
        print("  python wiki_query.py --step 1                    # Fetch species from Wikidata")
        print("  python wiki_query.py --step 3                    # Get pageviews via API (default)")
        print("  python wiki_query.py --step 4                    # Generate rankings")
        print("  python wiki_query.py --all --skip-pagelinks      # Recommended: API + skip pagelinks")
        print("  python wiki_query.py --all --limit 50000         # Debug: limit to 50k species")
        print("  python wiki_query.py --step 3 --use-monthly-dumps  # Use monthly dump files")
        print("  python wiki_query.py --step 3 --use-hourly       # Use hourly dumps (slowest)")


if __name__ == "__main__":
    main()