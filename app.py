import os
import re
from datetime import datetime
from typing import List, Dict, Optional, Any

import requests
from supabase import create_client, Client


# =========================
# CONFIG / CLIENTS
# =========================
BEEHIIV_API_KEY = os.getenv("BEEHIIV_API_KEY")
BEEHIIV_PUBLICATION_ID = os.getenv("BEEHIIV_PUBLICATION_ID")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Timeline range
YEAR_MIN = 1990
YEAR_MAX = 2025

YEAR_RE = re.compile(r"\b(19\d{2}|20\d{2})\b")


# =========================
# BEEHIIV FETCH
# =========================
def fetch_beehiiv_posts(limit: int = 50, page: int = 1) -> Dict:
    """Fetch posts from Beehiiv API."""
    if not BEEHIIV_API_KEY or not BEEHIIV_PUBLICATION_ID:
        raise Exception("Missing BEEHIIV_API_KEY or BEEHIIV_PUBLICATION_ID in env vars")

    url = f"https://api.beehiiv.com/v2/publications/{BEEHIIV_PUBLICATION_ID}/posts"
    headers = {
        "Authorization": f"Bearer {BEEHIIV_API_KEY}",
        "Content-Type": "application/json",
    }
    params = {"limit": limit, "page": page}

    resp = requests.get(url, headers=headers, params=params, timeout=30)
    if resp.status_code != 200:
        raise Exception(f"Beehiiv API error {resp.status_code}: {resp.text}")

    return resp.json()


# =========================
# TEXT CLEANUP
# =========================
def strip_html(html: str) -> str:
    if not html:
        return ""
    # Convert block-ish tags into newlines so we preserve structure
    html = re.sub(r"</(p|div|br|li|h1|h2|h3|h4|h5|blockquote)>", "\n\n", html, flags=re.IGNORECASE)
    html = re.sub(r"<br\s*/?>", "\n", html, flags=re.IGNORECASE)
    # Strip remaining tags
    text = re.sub(r"<[^>]+>", " ", html)
    # Normalize spaces but keep newlines
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def normalize_paragraphs(text: str) -> List[str]:
    """
    Turn a big block of text into paragraphs.
    We try to preserve some paragraph-ish structure by splitting on double newlines
    first; if not present, we fall back to sentence-y chunking.
    """
    if not text:
        return []

    # Try splitting on double newlines
    rough = re.split(r"\n\s*\n", text)
    paras = [p.strip() for p in rough if p and p.strip()]

    if len(paras) >= 2:
        return paras

    # If Beehiiv content has no newlines after stripping HTML,
    # create pseudo-paragraphs by splitting on ". "
    chunks = re.split(r"(?<=[.!?])\s+", text)
    # Re-join into ~2-4 sentence blocks
    blocks = []
    buf = []
    for s in chunks:
        s = s.strip()
        if not s:
            continue
        buf.append(s)
        if len(buf) >= 3:
            blocks.append(" ".join(buf))
            buf = []
    if buf:
        blocks.append(" ".join(buf))

    return [b.strip() for b in blocks if len(b.strip()) > 50]


# =========================
# CARD EXTRACTION (NO AI)
# =========================
SENT_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")

def extract_year_cards(text: str, max_cards: int = 40) -> List[Dict]:
    if not text:
        return []

    # Split into sentences (works even if the whole issue is one blob)
    sentences = [s.strip() for s in SENT_SPLIT_RE.split(text) if s and len(s.strip()) > 40]

    cards: List[Dict] = []
    for s in sentences:
        m = YEAR_RE.search(s)
        if not m:
            continue

        year = int(m.group(1))
        if year < YEAR_MIN or year > YEAR_MAX:
            continue

        excerpt = s[:260] + ("…" if len(s) > 260 else "")

        cards.append({
            "year_start": year,
            "year_end": None,
            "excerpt": excerpt,
            "context": s,
        })

        if len(cards) >= max_cards:
            break

    return cards



# =========================
# SUPABASE STORAGE
# =========================
def store_article(article_data: Dict) -> bool:
    """
    Store article in 'articles' and store its cards in 'cards'.
    Expects article_data['_cards'] to exist (list).
    """
    try:
        cards = article_data.pop("_cards", [])

        # Upsert article by beehiiv_id
        existing = supabase.table("articles").select("id").eq("beehiiv_id", article_data["beehiiv_id"]).execute()

        if existing.data:
            supabase.table("articles").update(article_data).eq("beehiiv_id", article_data["beehiiv_id"]).execute()
            print(f"Updated article: {article_data['title']}")
        else:
            supabase.table("articles").insert(article_data).execute()
            print(f"Stored new article: {article_data['title']}")

        # Replace cards for this issue
        store_cards(
            beehiiv_id=article_data["beehiiv_id"],
            publish_date=article_data.get("publish_date"),
            title=article_data.get("title"),
            url=article_data.get("url"),
            cards=cards,
        )
        return True

    except Exception as e:
        print(f"Error storing article/cards: {e}")
        return False


def store_cards(beehiiv_id: str, publish_date: Optional[str], title: str, url: str, cards: List[Dict]) -> bool:
    """
    Insert cards into 'cards' table.
    Minimal expected columns (recommended):
      beehiiv_id, card_index, publish_date, issue_title, issue_url,
      year_start, year_end, excerpt, context, created_at
    """
    try:
        # Delete old cards for this issue
        supabase.table("cards").delete().eq("beehiiv_id", beehiiv_id).execute()

        rows = []
        for idx, c in enumerate(cards):
            rows.append({
                "beehiiv_id": beehiiv_id,
                "card_index": idx,
                "publish_date": publish_date,
                "issue_title": title,
                "issue_url": url,
                "year_start": c.get("year_start"),
                "year_end": c.get("year_end"),
                "excerpt": c.get("excerpt"),
                "context": c.get("context"),
                "created_at": datetime.utcnow().isoformat(),
            })

        if rows:
            supabase.table("cards").insert(rows).execute()
            print(f"Inserted {len(rows)} cards for issue {beehiiv_id}")
        else:
            print(f"No cards found for issue {beehiiv_id}")

        return True

    except Exception as e:
        print(f"Error storing cards: {e}")
        return False


# =========================
# PROCESS ONE POST
# =========================
def process_article(post: Dict) -> Optional[Dict]:
    """Process a single Beehiiv post and generate year-cards."""
    try:
        beehiiv_id = post["id"]
        title = post.get("title", "Untitled")

        # Try multiple fields Beehiiv might use
        content = post.get("content") or post.get("content_html") or post.get("preview_text") or ""
        if isinstance(content, dict):
            content = content.get("html") or content.get("text") or ""

        # If it's HTML, strip it. If it's already plain text, strip_html is harmless.
        clean_content = strip_html(content)
        print("HAS YEAR:", bool(YEAR_RE.search(clean_content)), "CONTENT LENGTH:", len(clean_content))


        publish_date = post.get("published_at") or post.get("created_at") or post.get("updated_at")
        if not publish_date:
            publish_date = datetime.utcnow().isoformat()
            print(f"⚠️ Using current date for '{title}' - no publish date available")

        web_url = post.get("web_url", "#")

        # Extract cards
        cards = extract_year_cards(clean_content, max_cards=25)

        print(f"\nAnalyzing: {title}")
        print("CONTENT LENGTH:", len(clean_content))
        print("CARDS FOUND:", len(cards))

        article_data = {
            "beehiiv_id": beehiiv_id,
            "title": title,
            "publish_date": publish_date,
            "url": web_url,
            # simple preview: first card excerpt or first 200 chars
            "pull_quote": cards[0]["excerpt"] if cards else (clean_content[:200] + ("…" if len(clean_content) > 200 else "")),
            # placeholders so your existing schema/UI doesn't break
            "periods": ["early-2020s"],
            "topics": ["tech"],
            "processed_at": datetime.utcnow().isoformat(),
        }

        article_data["_cards"] = cards
        return article_data

    except Exception as e:
        print(f"Error processing article {post.get('id')}: {e}")
        return None


# =========================
# IMPORT LOOP
# =========================
def import_all_posts(
    max_issues: Optional[int] = None,
    max_pages: Optional[int] = None,
    limit: int = 50,
    **kwargs
) -> int:
    """
    Import Beehiiv posts and generate year-cards (no AI).
    max_issues: stop after this many posts processed (testing)
    """
    print("Starting Beehiiv import (NO AI)...")
    page = 1
    total_processed = 0

    while True:
        if max_pages is not None and page > int(max_pages):
            print(f"Reached max_pages={max_pages}; stopping.")
            break

        print(f"\nFetching page {page}...")
        resp = fetch_beehiiv_posts(limit=limit, page=page)
        posts = resp.get("data", []) or []

        if not posts:
            print("No more posts.")
            break

        for post in posts:
            article_data = process_article(post)
            if article_data:
                if store_article(article_data):
                    total_processed += 1

            if max_issues is not None and total_processed >= int(max_issues):
                print(f"Reached max_issues={max_issues}; stopping early.")
                print(f"✅ Import complete! Processed {total_processed} articles")
                return total_processed

        # Pagination (Beehiiv sometimes provides next_page)
        next_page = resp.get("pagination", {}).get("next_page")
        if not next_page:
            print("No more pages.")
            break

        page += 1

    print(f"✅ Import complete! Processed {total_processed} articles")
    return total_processed


# =========================
# FRONTEND HELPERS
# =========================
def get_articles_for_frontend():
    """Fetch all articles for the frontend."""
    try:
        result = supabase.table("articles").select("*").order("publish_date", desc=False).execute()
        return result.data
    except Exception as e:
        print(f"Error fetching articles: {e}")
        return []
