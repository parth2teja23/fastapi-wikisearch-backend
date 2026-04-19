# WikiSearch — Complete Technical Documentation

> A full-stack Wikipedia search engine built on a DigitalOcean VPS, powered by FastAPI, Meilisearch, and Next.js. Live at `wikisearch.parth2teja.in`.

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Architecture Diagram](#2-architecture-diagram)
3. [The Wikipedia XML Dump](#3-the-wikipedia-xml-dump)
4. [Indexing Pipeline](#4-indexing-pipeline)
5. [Meilisearch — How It Works](#5-meilisearch--how-it-works)
6. [FastAPI Backend](#6-fastapi-backend)
7. [Next.js Frontend](#7-nextjs-frontend)
8. [Networking & VPS Setup](#8-networking--vps-setup)
9. [SSL & Domain Configuration](#9-ssl--domain-configuration)
10. [How Search Actually Works](#10-how-search-actually-works)
11. [What Can Be Added in the Future](#11-what-can-be-added-in-the-future)

---

## 1. Project Overview

WikiSearch is a production-deployed search engine that lets users search through all ~220,000+ articles of Simple English Wikipedia. The key idea is: instead of sending queries to Wikipedia's own servers, we download a copy of the entire Wikipedia database, process it ourselves, and build our own search index on top of it.

The result is a fast, self-hosted search API with sub-50ms response times, our own ranking logic, full article retrieval, and a clean Next.js frontend.

**Tech Stack:**

| Layer | Technology |
|---|---|
| Data source | Wikipedia XML Dump (Simple English) |
| Search engine | Meilisearch |
| Backend API | FastAPI (Python) |
| Frontend | Next.js (deployed on Vercel) |
| Web server | Nginx (reverse proxy) |
| VPS | DigitalOcean — 2vCPU, 2GB RAM, 60GB SSD |
| SSL | Let's Encrypt via Certbot |
| Domain | wikisearch.parth2teja.in |

---

## 2. Architecture Diagram

```
User Browser
     │
     │  HTTPS
     ▼
wikisearch.parth2teja.in  (DNS A record → 139.59.58.223)
     │
     ▼
Vercel (Next.js Frontend)
     │
     │  API calls to https://wikisearch.parth2teja.in/api/...
     ▼
DigitalOcean VPS (139.59.58.223)
     │
     ▼
Nginx (port 80/443)
  ├── /         → Next.js  (port 3000)  [if self-hosted]
  └── /api/     → FastAPI  (port 8000)
                     │
                     ▼
               Meilisearch (port 7700, internal only)
                     │
                     ▼
               meili_data/ (on disk, ~500MB for simplewiki)
```

Meilisearch is never exposed to the public internet — only FastAPI can talk to it internally via `localhost:7700`. This is a key security decision.

---

## 3. The Wikipedia XML Dump

Wikipedia is free and open. The Wikimedia Foundation publishes complete database dumps of every Wikipedia at `dumps.wikimedia.org`. These are updated regularly (roughly monthly).

### Why Simple English Wikipedia?

The full English Wikipedia has ~6.7 million articles and the compressed dump is ~22GB (~90GB uncompressed). Indexing it requires 4–8GB RAM and 40GB+ disk just for the Meilisearch index. Our VPS has 2GB RAM and 60GB disk, so we use **Simple English Wikipedia** instead — ~220,000 articles, ~250MB compressed. Same architecture, fraction of the resource requirements.

### What the dump looks like

The file is a `.bz2` compressed XML file. When decompressed, it looks like this:

```xml
<mediawiki xmlns="http://www.mediawiki.org/xml/export-0.11/">
  <page>
    <title>Artificial Intelligence</title>
    <ns>0</ns>
    <revision>
      <text>Artificial intelligence (AI) is intelligence demonstrated by machines...
      [[Category:Computer science]]
      {{reflist}}
      </text>
    </revision>
  </page>
  <page>
    <title>Talk:Artificial Intelligence</title>
    <ns>1</ns>
    ...
  </page>
</mediawiki>
```

Two important things:
- `<ns>` is the namespace. `ns=0` means it's a real article. `ns=1` is a Talk page, `ns=4` is Wikipedia meta pages, etc. We only want `ns=0`.
- The text is in **MediaWiki markup** — full of `{{templates}}`, `[[wikilinks]]`, `==headings==`, `'''bold'''`. We need to strip this to get plain text.

### The namespace gotcha

The XML namespace (`xmlns`) changes between dump versions — e.g. `export-0.10` vs `export-0.11`. If you hardcode the wrong version in your parser, `elem.tag` comparisons silently fail and you get zero articles. The fix is to auto-detect the namespace from the root tag at parse time.

---

## 4. Indexing Pipeline

The indexing pipeline has three stages: **Parse → Clean → Index**.

### Stage 1: Stream Parsing (`parse.py`)

The dump file is ~250MB compressed and expands to several GB. You cannot load it into memory — you have to **stream parse** it.

We use Python's `xml.etree.ElementTree.iterparse()` which fires events (`start`, `end`) as it reads through the file tag by tag, without loading the whole thing. When a `<page>` end event fires, we extract the title and text, yield the article, then call `elem.clear()` to free that element from memory immediately.

```python
import bz2
import xml.etree.ElementTree as ET

def stream_articles(dump_path: str):
    namespace = None

    with bz2.open(dump_path, "rb") as f:
        for event, elem in ET.iterparse(f, events=["start", "end"]):
            # auto-detect namespace from root tag
            if namespace is None and event == "start":
                if "}" in elem.tag:
                    namespace = elem.tag.split("}")[0].strip("{")
                continue

            if event == "end" and elem.tag == f"{{{namespace}}}page":
                title = elem.findtext(f"{{{namespace}}}title")
                ns    = elem.findtext(f"{{{namespace}}}ns")
                text  = elem.findtext(f".//{{{namespace}}}revision/{{{namespace}}}text")

                if ns == "0" and text:
                    yield {"title": title, "text": text}

                elem.clear()  # critical — prevents memory bloat
```

Key decisions:
- `bz2.open()` decompresses on the fly — no need to decompress the file first
- `elem.clear()` after each page keeps RAM usage flat regardless of dump size
- We filter `ns == "0"` to skip Talk pages, User pages, Wikipedia meta pages

### Stage 2: Cleaning (`clean.py`)

Raw Wikipedia text is MediaWiki markup. It's unreadable as-is:

```
'''Albert Einstein''' (14 March 1879{{spaced ndash}}18 April 1955) was a [[Germans|German]]-born
[[theoretical physics|theoretical physicist]]. {{cite web|url=...}}
== Early life ==
Einstein was born in [[Ulm]], in the [[Kingdom of Württemberg]]...
```

We use `mwparserfromhell`, a library specifically built to parse MediaWiki markup, to strip it down to plain text:

```python
import mwparserfromhell

def clean_article(raw_text: str) -> str:
    parsed = mwparserfromhell.parse(raw_text)
    clean = parsed.strip_code()   # removes templates, links, formatting
    return clean.strip()[:5000]   # cap at 5000 chars
```

We cap at 5000 characters because: (a) Meilisearch indexes the full text for search but we don't need 100k chars per article for our use case, and (b) it keeps our index size manageable on a small VPS.

### Stage 3: Indexing (`index.py`)

We batch articles in groups of 1000 and push them to Meilisearch via its Python SDK. Batching is important — sending one document at a time would be 220,000 HTTP requests.

```python
batch.append({
    "id": total,                         # unique numeric ID required by Meilisearch
    "title": article["title"],
    "excerpt": clean_text[:500],         # short preview for search results
    "text": clean_text,                  # full text for article page
    "url": f"https://simple.wikipedia.org/wiki/{title.replace(' ', '_')}"
})

if len(batch) >= 1000:
    index.add_documents(batch)
    batch = []
```

The entire indexing run for Simple English Wikipedia takes about 20–30 minutes on our VPS. We run it with `nohup` so it survives SSH disconnects:

```bash
nohup ../venv/bin/python index.py > indexing.log 2>&1 &
```

---

## 5. Meilisearch — How It Works

Meilisearch is an open-source search engine written in Rust. It's fast, easy to use, and designed to be embedded in your own applications — unlike Elasticsearch which is heavyweight and complex.

### What Meilisearch does internally

When you add documents, Meilisearch builds an **inverted index**. An inverted index maps every word to the list of documents that contain it:

```
"einstein"  → [doc_42, doc_891, doc_1203]
"physics"   → [doc_42, doc_77, doc_891, doc_4521]
"germany"   → [doc_42, doc_103, doc_788]
```

When you search for "einstein physics", Meilisearch looks up both terms, finds the intersection of document lists, and ranks by relevance.

### Ranking rules

We configured these ranking rules:

```python
"rankingRules": ["words", "typo", "proximity", "attribute", "sort", "exactness"]
```

In order:
- **words** — documents containing more of the query words rank higher
- **typo** — documents with fewer typos between query and match rank higher (Meilisearch supports fuzzy matching — "einsten" still finds Einstein)
- **proximity** — documents where query words appear close together rank higher
- **attribute** — matches in `title` rank higher than matches in `text` (because we set `title` first in `searchableAttributes`)
- **sort** — allows custom sort fields (we don't use this)
- **exactness** — exact matches rank above fuzzy matches

### Displayed vs Searchable attributes

- `searchableAttributes: ["title", "text"]` — Meilisearch only searches these fields. It builds the inverted index from them.
- `displayedAttributes: ["title", "excerpt", "text", "url"]` — fields returned in results. We don't return the full `text` in search results (only `excerpt`) to keep responses small, but we do return it on the article endpoint.
- `filterableAttributes: ["title"]` — fields you can filter on (e.g. `filter: 'title = "India"'`). Requires a separate indexing pass by Meilisearch when you enable it.

### Meilisearch on the VPS

Meilisearch runs as a systemd service on port 7700. Its data is stored in `/home/meili_data/`. The master key (`parth123`) is required for all API calls — without it you get a 401.

After indexing, the `meili_data/` directory is about 450–500MB for Simple English Wikipedia.

---

## 6. FastAPI Backend

The backend is a FastAPI application with three route groups: search, article, and history.

### Project structure

```
app/
├── main.py           # FastAPI app, middleware, router registration
├── cache.py          # Redis helpers (get/set with TTL)
├── dependency.py     # API key auth as a Depends()
├── models.py         # SQLAlchemy models (APIKey, SearchLog)
└── routes/
    ├── search.py     # GET /api/search
    ├── articles.py   # GET /api/article/{title}
    └── history.py    # GET /api/history
```

### Search endpoint (`GET /api/search`)

```
GET /api/search?q=india&limit=10
```

Flow:
1. Check Redis cache for `search:{q}:{limit}` — if hit, return immediately
2. Query Meilisearch with the search term
3. Return title, excerpt, url for each hit
4. Cache the result for 10 minutes
5. Log the search to DB as a background task (so it doesn't slow the response)

Meilisearch returns results in ~5–20ms. With Redis cache hit, it's ~1ms.

### Article endpoint (`GET /api/article/{title}`)

```
GET /api/article/Official%20names%20of%20India
```

Flow:
1. Query Meilisearch by title, retrieve `title`, `text`, `url`
2. Return the full article text

We search by title rather than by ID because the frontend only knows the title (from the search result). The title field has `filterableAttributes` enabled so Meilisearch can do exact title lookups efficiently.

### CORS

Since the frontend is on Vercel (`https://wikisearch.parth2teja.in`) and the API is on our VPS, we need CORS middleware:

```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
```

Without this, browsers block cross-origin API calls with a CORS error.

### Running as a systemd service

FastAPI runs via `uvicorn` bound to `127.0.0.1:8000` — only localhost, never directly exposed:

```ini
[Service]
ExecStart=/home/fastapi-wikisearch-backend/venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
Restart=always
```

`Restart=always` means if it crashes, systemd brings it back automatically.

---

## 7. Next.js Frontend

The frontend is a Next.js app deployed on Vercel. It has two pages:

### Search page (`/`)

- User types a query and submits
- Calls `GET {API_BASE_URL}/api/search?q={query}&limit=10`
- Renders results as clickable cards
- Each card is a `<Link href="/article/{title}">` — clicking navigates to the article page

### Article page (`/article/[title]`)

- Reads `params.title` from the URL (URL-decoded)
- Calls `GET {API_BASE_URL}/api/article/{title}` on mount
- Renders the full article text
- Shows a "View on Wikipedia →" link to the original article
- "← Back to results" button uses `router.back()`

### Environment variable

`NEXT_PUBLIC_API_BASE_URL` is set in Vercel's environment variables to `https://wikisearch.parth2teja.in`. This is the only thing that changes between local dev and production.

---

## 8. Networking & VPS Setup

### DigitalOcean Droplet

Our VPS specs: 2 vCPU, 2GB RAM, 60GB SSD NVMe, Bangalore region (blr1). It runs Ubuntu 24.04 LTS.

**Why these specs matter:**
- 2GB RAM is enough for Meilisearch at rest (~200MB) + FastAPI (~50MB) + OS overhead. It was tight during indexing (we added a 4GB swap file to handle peaks).
- 60GB SSD is plenty — OS (3GB) + meili_data (500MB) + dump file (250MB) + app code leaves ~55GB free.
- 2 vCPU helps during indexing where parsing and indexing happen in parallel.

### Swap file

During indexing, memory usage spikes. We added a 4GB swap file as a safety net:

```bash
sudo fallocate -l 4G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile swap swap defaults 0 0' | sudo tee -a /etc/fstab
```

Swap is slower than RAM (it uses disk) but prevents OOM kills during the one-time indexing job. After indexing, it's rarely used.

### Nginx as reverse proxy

Nginx sits in front of everything on port 80/443. It routes traffic based on the URL path:

```nginx
server {
    listen 80;
    server_name wikisearch.parth2teja.in;

    location / {
        proxy_pass http://127.0.0.1:3000;   # Next.js (if self-hosted)
    }

    location /api/ {
        proxy_pass http://127.0.0.1:8000;   # FastAPI
    }
}
```

Why a reverse proxy instead of exposing FastAPI directly?
- Single entry point for all traffic (one port 80/443)
- Nginx handles SSL termination — FastAPI receives plain HTTP internally
- Nginx can serve static files, handle compression, rate limiting at the network level
- Security: internal services (Meilisearch on 7700, FastAPI on 8000) are never directly reachable from the internet

### Port layout

| Port | Service | Accessible from |
|---|---|---|
| 80 | Nginx | Public internet |
| 443 | Nginx (HTTPS) | Public internet |
| 8000 | FastAPI (uvicorn) | localhost only |
| 7700 | Meilisearch | localhost only |
| 3000 | Next.js (if self-hosted) | localhost only |

### Systemd services

Three systemd services keep everything running:

```
meilisearch.service     → Meilisearch search engine
wikisearch-api.service  → FastAPI backend
wikisearch-frontend.service  → Next.js (if self-hosted)
```

`Restart=always` on each means they auto-restart on crash. `systemctl enable` makes them start on VPS reboot. This is how production servers are managed — no manual `python app.py` in a terminal.

---

## 9. SSL & Domain Configuration

### DNS Setup

`parth2teja.in` is registered on GoDaddy. We added an A record:

```
Type: A
Host: wikisearch
Value: 139.59.58.223
TTL: 1 hour
```

This tells DNS: "when anyone asks for `wikisearch.parth2teja.in`, send them to `139.59.58.223`". TTL (Time To Live) controls how long DNS resolvers cache this record — 1 hour means changes propagate within an hour.

### Let's Encrypt SSL

We use Certbot to get a free SSL certificate from Let's Encrypt:

```bash
sudo apt install certbot python3-certbot-nginx -y
sudo certbot --nginx -d wikisearch.parth2teja.in
```

Certbot:
1. Proves to Let's Encrypt that we control the domain (via HTTP challenge on port 80)
2. Downloads the certificate and private key
3. Automatically modifies the Nginx config to use HTTPS
4. Sets up a cron job to auto-renew before the 90-day expiry

After certbot runs, Nginx listens on 443 with SSL and redirects all port 80 traffic to HTTPS automatically.

### Why HTTPS matters for this project

Our frontend is on Vercel which is HTTPS. If the API were plain HTTP, browsers would block the request as "mixed content" — a page served over HTTPS cannot make requests to HTTP URLs. Without SSL on our VPS, the frontend would silently fail to call the API.

---

## 10. How Search Actually Works

When a user searches for "black hole", here's the complete journey:

1. **Browser** — user types "black hole" and hits search on `wikisearch.parth2teja.in` (Vercel)

2. **Next.js** — `fetch("https://wikisearch.parth2teja.in/api/search?q=black+hole&limit=10")`

3. **DNS** — resolves `wikisearch.parth2teja.in` to `139.59.58.223`

4. **Nginx on VPS** — receives HTTPS request on port 443, terminates SSL, sees path starts with `/api/`, proxies to `http://127.0.0.1:8000/api/search?q=black+hole&limit=10`

5. **FastAPI** — checks Redis cache for `search:black hole:10`. Cache miss → proceeds.

6. **Meilisearch** — FastAPI sends search query to `http://localhost:7700/indexes/wikipedia/search`. Meilisearch:
   - Tokenizes "black hole" into ["black", "hole"]
   - Looks up both terms in the inverted index
   - Finds all documents containing "black" and "hole"
   - Ranks by words → typo → proximity → attribute
   - Returns top 10 hits with title, excerpt, url (not full text)

7. **FastAPI** — stores result in Redis with 10-minute TTL, returns JSON response

8. **Nginx** — passes response back to Vercel

9. **Next.js** — renders 10 result cards with title and excerpt

10. **User clicks "Black hole"** — navigates to `/article/Black%20hole`

11. **Article page** — fetches `GET /api/article/Black%20hole`

12. **FastAPI** → **Meilisearch** — searches by title with filter, retrieves full `text` field

13. **User sees** — full article text + "View on Wikipedia" link

Total time from search to results: ~50–100ms on first load, ~5ms on cached queries.

---

## 11. What Can Be Added in the Future

### Short term (1–2 weeks)

**Autocomplete / suggestions**
Add a `GET /api/suggest?q=bla` endpoint that queries Meilisearch with `limit=5` and returns just titles. Wire it to a dropdown below the search input in the frontend. Meilisearch is fast enough for this to feel real-time.

**Search filters**
Let users filter by article length (stub vs full article), or add categories if you parse the `[[Category:...]]` tags during indexing and store them as a field.

**Pagination**
Currently limited to 10 results. Add `page` and `limit` params, use Meilisearch's `offset` parameter, and add next/prev buttons in the frontend.

**Better article rendering**
Right now the article text is raw plain text with `whitespace-pre-wrap`. Parse it further — detect headings (lines starting with `==`), convert them to `<h2>` tags, detect lists, etc. Makes the article page look much more like Wikipedia.

### Medium term (1–2 months)

**Full English Wikipedia**
Upgrade the VPS to 4GB+ RAM and 160GB+ disk. Re-run the same pipeline on the full English dump. The architecture doesn't change at all — just the data size.

**Semantic / vector search**
Use `sentence-transformers` to generate embeddings for each article during indexing, store them in a vector database (FAISS or Meilisearch's built-in vector search), and support "meaning-based" queries. For example, searching "heart attack" would also return articles about "cardiac arrest" even if the exact words don't match.

**API key system**
Add proper API key issuance (`POST /api/keys/generate`), per-key rate limiting via `slowapi`, and usage dashboards. Turn this into a public API others can use.

**Redis caching for articles**
Currently only search results are cached. Cache full article fetches too — popular articles like "India", "Albert Einstein" get hit constantly.

**Full-text search highlighting**
Meilisearch supports `attributesToHighlight` which wraps matched terms in `<em>` tags. Use this to bold the matching words in the excerpt, just like Google does.

### Long term (serious projects)

**Incremental index updates**
Wikipedia dumps are released monthly. Instead of re-indexing everything, parse the incremental diff dumps (`*-pages-articles-multistream.xml.bz2`) and only update changed articles. This keeps your index fresh without a 30-minute full re-index.

**Multi-language support**
Wikimedia publishes dumps for every language Wikipedia. The same pipeline works for Hindi Wikipedia (`hiwiki`), French, Spanish, etc. Add a `lang` query param and maintain separate Meilisearch indexes per language.

**Analytics dashboard**
Log every search query to a database with timestamps. Build an admin page showing: top 100 queries today, search volume over time, zero-result queries (tells you what's missing from your index), average response time. This is genuinely useful and impressive to show.

**Wikipedia link graph**
During indexing, parse `[[Article Name]]` wikilinks and store the link graph in a graph database (Neo4j) or even just a Postgres table. Enable "related articles" suggestions based on how many articles link to each other. This is how Wikipedia's "See also" section works conceptually.

---

## Appendix: Key Commands Reference

```bash
# Check all services
sudo systemctl status meilisearch wikisearch-api nginx

# View FastAPI logs
journalctl -u wikisearch-api -f

# Check index stats
curl -s http://localhost:7700/indexes/wikipedia/stats \
  -H "Authorization: Bearer parth123" | python3 -m json.tool

# Re-index (run in background, survives disconnect)
cd /home/fastapi-wikisearch-backend
nohup venv/bin/python indexer/index.py > indexer/indexing.log 2>&1 &

# Watch indexing progress
tail -f /home/fastapi-wikisearch-backend/indexer/indexing.log

# Test search API directly
curl "http://localhost:8000/api/search?q=india"

# Restart everything after a code change
git pull
sudo systemctl restart wikisearch-api
```