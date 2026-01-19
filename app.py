import os
import json
import re
from datetime import datetime
from typing import List, Dict, Optional, Any
import requests
from supabase import create_client, Client
from openai import OpenAI

# Configuration
BEEHIIV_API_KEY = os.getenv('BEEHIIV_API_KEY')
BEEHIIV_PUBLICATION_ID = os.getenv('BEEHIIV_PUBLICATION_ID')
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')

# Initialize clients
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
openai_client = OpenAI(api_key=OPENAI_API_KEY)

# Timeline periods mapping
PERIOD_MAP = {
    'early-90s': {'start': 1990, 'end': 1994, 'label': 'Early 90s'},
    'late-90s': {'start': 1995, 'end': 1999, 'label': 'Late 90s'},
    'early-2000s': {'start': 2000, 'end': 2004, 'label': 'Early 2000s'},
    'late-2000s': {'start': 2005, 'end': 2009, 'label': 'Late 2000s'},
    'early-2010s': {'start': 2010, 'end': 2014, 'label': 'Early 2010s'},
    'late-2010s': {'start': 2015, 'end': 2019, 'label': 'Late 2010s'},
    'early-2020s': {'start': 2020, 'end': 2029, 'label': 'Early 2020s'}
}

TOPICS = ['tech', 'memes', 'politics', 'entertainment']

# "Connection card" link types. Keep this short + stable.
LINK_TYPES = [
    "recurrence",
    "inversion",
    "tactic-transfer",
    "regulatory-echo",
    "platform-lifecycle",
    "narrative-laundering",
    "rebranding",
    "capability-jump",
]


def fetch_beehiiv_posts(limit: int = 100, page: int = 1) -> Dict:
    """Fetch posts from Beehiiv API with improved error handling"""
    url = f"https://api.beehiiv.com/v2/publications/{BEEHIIV_PUBLICATION_ID}/posts"
    headers = {
        "Authorization": f"Bearer {BEEHIIV_API_KEY}",
        "Content-Type": "application/json"
    }
    
    # Try different parameter combinations
    param_sets = [
        # Try without status filter first
        {
            "limit": limit,
            "page": page
        },
        # Try with published status
        {
            "status": "published",
            "limit": limit,
            "page": page
        },
        # Try with confirmed status
        {
            "status": "confirmed",
            "limit": limit,
            "page": page
        }
    ]
    
    last_error = None
    
    for params in param_sets:
        try:
            print(f"Trying API call with params: {params}")
            response = requests.get(url, headers=headers, params=params)
            
            if response.status_code == 200:
                print(f"✓ Success with params: {params}")
                return response.json()
            else:
                last_error = f"{response.status_code}: {response.text}"
                print(f"✗ Failed with params {params}: {last_error}")
                
        except Exception as e:
            last_error = str(e)
            print(f"✗ Exception with params {params}: {last_error}")
            continue
    
    # If all attempts failed, raise the last error
    raise Exception(f"All API attempts failed. Last error: {last_error}")


def _strip_html(content: str) -> str:
    return re.sub(r'<[^>]+>', '', content or '')


def _normalize_whitespace(text: str) -> str:
    return re.sub(r'\s+', ' ', (text or '')).strip()


def _parse_year(value: Any) -> Optional[int]:
    try:
        if value is None:
            return None
        s = str(value)
        m = re.search(r'(19\d{2}|20\d{2})', s)
        return int(m.group(1)) if m else None
    except Exception:
        return None


def _year_to_period_id(year: int) -> Optional[str]:
    for pid, meta in PERIOD_MAP.items():
        if meta['start'] <= year <= meta['end']:
            return pid
    return None


def _safe_list(xs: Any) -> List[Any]:
    return xs if isinstance(xs, list) else []


def validate_cards(cards: List[Dict], clean_content: str) -> List[Dict]:
    """Hard guardrails so we don't store hallucinated cards.

    Rules:
    - claim must exist and be short
    - evidence must contain at least 1 verbatim quote present in clean_content
    - then_range years must be sane if present
    - link_type must be one of LINK_TYPES if present
    """

    ok: List[Dict] = []
    haystack = clean_content

    for c in _safe_list(cards):
        if not isinstance(c, dict):
            continue

        claim = _normalize_whitespace(c.get('claim'))
        if not claim or len(claim) < 12 or len(claim) > 220:
            continue

        evidence = _safe_list(c.get('evidence'))
        evidence_quotes: List[str] = []
        for e in evidence:
            if isinstance(e, dict):
                q = _normalize_whitespace(e.get('quote'))
            else:
                q = _normalize_whitespace(e)
            if q and q in haystack:
                evidence_quotes.append(q)

        if len(evidence_quotes) == 0:
            continue

        # link type
        link_type = c.get('link_type')
        if link_type and link_type not in LINK_TYPES:
            link_type = None

        then_range = c.get('then_range')
        then_start = None
        then_end = None
        if isinstance(then_range, dict):
            then_start = _parse_year(then_range.get('start'))
            then_end = _parse_year(then_range.get('end'))
            if then_start and then_end and then_start > then_end:
                then_start, then_end = then_end, then_start
            # sanity: keep within 1990..2035
            if then_start and not (1990 <= then_start <= 2035):
                then_start = None
            if then_end and not (1990 <= then_end <= 2035):
                then_end = None

        tags = [t for t in _safe_list(c.get('tags')) if isinstance(t, str) and 1 <= len(t) <= 40]
        tags = tags[:10]

        ok.append({
            'claim': claim,
            'then_start': then_start,
            'then_end': then_end,
            'now_label': _normalize_whitespace(c.get('now_label')) or None,
            'link_type': link_type,
            'tags': tags,
            'evidence': [{'quote': q} for q in evidence_quotes[:4]],
            'confidence': float(c.get('confidence', 0.75)) if str(c.get('confidence', '')).replace('.', '', 1).isdigit() else 0.75
        })

    # cap per issue
    return ok[:6]


def analyze_article_with_ai(title: str, content: str, publish_date: str) -> Dict:
    """Generate a small set of evidence-locked cards + light metadata.

    This replaces the old "event_summary" approach with connection cards.
    """

    clean_content = _strip_html(content)
    clean_content = _normalize_whitespace(clean_content)

    # Keep enough context for evidence quotes while avoiding huge token bills.
    # If you later add chunking, you can remove this truncation.
    if len(clean_content) > 14000:
        clean_content = clean_content[:14000]

    system_msg = (
        "You extract structured notes from journalism. "
        "You MUST follow instructions and output VALID JSON only. "
        "Do not invent facts. Do not paraphrase evidence: evidence quotes must be verbatim substrings of the provided text."
    )

    user_msg = f"""Create 2 to 6 'connection cards' from this newsletter issue.

Each card captures a concrete, newsroom-useful insight (a claim) and includes evidence pulled verbatim from the article.

ISSUE TITLE: {title}
PUBLISHED_AT (may be missing/approx): {publish_date}

ARTICLE TEXT (verbatim):
{clean_content}

Output ONLY JSON with this exact shape:
{{
  "cards": [
    {{
      "claim": "One sentence, declarative. No hedging.",
      "then_range": {{"start": 2010, "end": 2012, "label": "optional"}} | null,
      "now_label": "Short label for the current trigger/event (optional)",
      "link_type": "one of: {', '.join(LINK_TYPES)}" | null,
      "tags": ["short tag", ...],
      "evidence": [{{"quote": "VERBATIM QUOTE FROM ARTICLE"}}, ...],
      "confidence": 0.0
    }}, ...
  ],
  "topics": ["tech"|"memes"|"politics"|"entertainment", ...]
}}

HARD RULES:
1) Evidence quotes MUST be exact substrings of ARTICLE TEXT. If you can't find a quote, do not create the card.
2) If the article does not explicitly reference a past time/event, set then_range = null.
3) Prefer then_range as a YEAR or YEAR RANGE (1990-2035). If unsure, use null.
4) Keep tags short. Prefer people, orgs, platforms, countries, and recurring concepts.
5) Don't repeat near-duplicate cards.
"""

    try:
        response = openai_client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg}
            ],
            temperature=0.2,
            max_tokens=900
        )

        result_text = response.choices[0].message.content.strip()
        result_text = re.sub(r'^```json\s*|\s*```$', '', result_text, flags=re.MULTILINE)
        raw = json.loads(result_text)

        raw_cards = _safe_list(raw.get('cards'))
        cards = validate_cards(raw_cards, clean_content)

        # Topics: keep within your existing controlled list.
        topics = [t for t in _safe_list(raw.get('topics')) if t in TOPICS]
        if not topics:
            topics = ['tech']

        # Derive periods from then_start/then_end across cards (for backwards compatibility with your frontend).
        period_ids: List[str] = []
        for c in cards:
            ys = [y for y in [c.get('then_start'), c.get('then_end')] if isinstance(y, int)]
            for y in ys:
                pid = _year_to_period_id(y)
                if pid and pid not in period_ids:
                    period_ids.append(pid)

        if not period_ids:
            # fallback: assume recent era when no explicit then
            period_ids = ['early-2020s']

        # A tiny "pull quote" for legacy UI: prefer the first claim.
        pull_quote = cards[0]['claim'] if cards else (clean_content[:200] + "...")

        return {
            'cards': cards,
            'periods': period_ids,
            'topics': topics,
            'event_summary': pull_quote,
        }

    except Exception as e:
        print(f"Error analyzing article: {e}")
        return {
            'cards': [],
            'periods': ['early-2020s'],
            'topics': ['tech'],
            'event_summary': clean_content[:200] + "..." if clean_content else "...",
        }


def store_article(article_data: Dict) -> bool:
    """Store analyzed article in Supabase"""
    try:
        # Cards are stored in a separate table; don't send unknown columns to the articles table.
        cards = article_data.pop('_cards', None)

        # Check if article already exists
        existing = supabase.table('articles').select('id').eq('beehiiv_id', article_data['beehiiv_id']).execute()
        
        if existing.data:
            # Update existing
            supabase.table('articles').update(article_data).eq('beehiiv_id', article_data['beehiiv_id']).execute()
            print(f"Updated article: {article_data['title']}")
        else:
            # Insert new
            supabase.table('articles').insert(article_data).execute()
            print(f"Stored new article: {article_data['title']}")
        
        # Upsert cards after the article is stored.
        if cards is not None:
            store_cards(
                beehiiv_id=article_data['beehiiv_id'],
                publish_date=article_data.get('publish_date'),
                title=article_data.get('title'),
                url=article_data.get('url'),
                cards=cards,
            )

        return True
    except Exception as e:
        print(f"Error storing article: {e}")
        return False


def store_cards(beehiiv_id: str, publish_date: str, title: str, url: str, cards: List[Dict]) -> bool:
    """Upsert cards for an issue into a `cards` table.

    Expected schema is provided in the README snippet below (see assistant message).
    """
    try:
        # If the table doesn't exist yet, this will throw and you'll see it in logs.
        # We keep it simple: delete existing cards for this issue then insert.
        supabase.table('cards').delete().eq('beehiiv_id', beehiiv_id).execute()

        rows = []
        for idx, c in enumerate(cards or []):
            rows.append({
                'beehiiv_id': beehiiv_id,
                'card_index': idx,
                'publish_date': publish_date,
                'issue_title': title,
                'issue_url': url,
                'claim': c.get('claim'),
                'then_start': c.get('then_start'),
                'then_end': c.get('then_end'),
                'now_label': c.get('now_label'),
                'link_type': c.get('link_type'),
                'tags': c.get('tags') or [],
                'evidence': c.get('evidence') or [],
                'confidence': c.get('confidence', 0.75),
                'created_at': datetime.utcnow().isoformat(),
            })

        if rows:
            supabase.table('cards').insert(rows).execute()
        return True
    except Exception as e:
        print(f"Error storing cards: {e}")
        return False


def process_article(post: Dict) -> Optional[Dict]:
    """Process a single Beehiiv post"""
    try:
        beehiiv_id = post['id']
        title = post.get('title', 'Untitled')
        content = post.get('content_html', '') or post.get('content', '')
        
        # Handle missing publish_date with fallback to current date
        publish_date = post.get('published_at') or post.get('created_at') or post.get('updated_at')
        
        # If still no date, use current date as fallback
        if not publish_date:
            publish_date = datetime.utcnow().isoformat()
            print(f"⚠️  Using current date for '{title}' - no publish date available")
        
        web_url = post.get('web_url', '#')
        
        print(f"\nAnalyzing: {title}")
        
        # Analyze with AI
        analysis = analyze_article_with_ai(title, content, publish_date)
        
        # Prepare data for storage
        article_data = {
            'beehiiv_id': beehiiv_id,
            'title': title,
            'publish_date': publish_date,
            'url': web_url,
            'pull_quote': analysis['event_summary'],  # Store as pull_quote in DB for compatibility
            'periods': analysis['periods'],
            'topics': analysis['topics'],
            'processed_at': datetime.utcnow().isoformat()
        }

        # Cards are written to a separate table by store_article().
        article_data['_cards'] = analysis.get('cards', [])
        
        return article_data
        
    except Exception as e:
        print(f"Error processing article {post.get('id')}: {e}")
        return None


def import_all_posts(max_issues=None):
    """Import and process posts from Beehiiv
    
    Args:
        max_issues: Maximum number of issues to process (None = all)
    """
    print("Starting Beehiiv import...")
    print(f"Using Publication ID: {BEEHIIV_PUBLICATION_ID}")
    print(f"API Key present: {'Yes' if BEEHIIV_API_KEY else 'No'}")
    if max_issues:
        print(f"⚠️  Test mode: Processing max {max_issues} issues")
    
    page = 1
    total_processed = 0
    
    while True:
        # Stop if we've hit the max
        if max_issues and total_processed >= max_issues:
            print(f"\n⚠️  Reached test limit of {max_issues} issues")
            break
            
        print(f"\nFetching page {page}...")
        
        try:
            response = fetch_beehiiv_posts(limit=50, page=page)
            posts = response.get('data', [])
            
            if not posts:
                print("No more posts to fetch")
                break
            
            print(f"Found {len(posts)} posts on page {page}")
            
            for post in posts:
                # Stop if we've hit the max
                if max_issues and total_processed >= max_issues:
                    break
                    
                article_data = process_article(post)
                if article_data:
                    if store_article(article_data):
                        total_processed += 1
            
            # Check if there are more pages
            if not response.get('pagination', {}).get('next_page'):
                print("No more pages available")
                break
                
            page += 1
            
        except Exception as e:
            print(f"Error fetching posts: {e}")
            break
    
    print(f"\n✅ Import complete! Processed {total_processed} articles")
    return total_processed


def get_articles_for_frontend():
    """Fetch all articles formatted for the frontend"""
    try:
        result = supabase.table('articles').select('*').order('publish_date', desc=False).execute()
        return result.data
    except Exception as e:
        print(f"Error fetching articles: {e}")
        return []


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "import":
        # Run full import
        import_all_posts()
    elif len(sys.argv) > 1 and sys.argv[1] == "test":
        # Test with one article
        print("Fetching one article for testing...")
        response = fetch_beehiiv_posts(limit=1, page=1)
        if response.get('data'):
            article_data = process_article(response['data'][0])
            if article_data:
                print("\nAnalysis result:")
                print(json.dumps(article_data, indent=2))
    else:
        print("Usage:")
        print("  python app.py import  - Import all articles from Beehiiv")
        print("  python app.py test    - Test with one article")
