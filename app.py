import os
import json
import re
from datetime import datetime
from typing import List, Dict, Optional
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


def analyze_article_with_ai(title: str, content: str, publish_date: str) -> Dict:
    """
    Use OpenAI to analyze the article and extract:
    - Time periods discussed
    - Best pull quote
    - Topic categories
    """
    
    # Clean HTML tags from content
    clean_content = re.sub(r'<[^>]+>', '', content)
    
    # Truncate if too long (to save tokens)
    if len(clean_content) > 8000:
        clean_content = clean_content[:8000] + "..."
    
    prompt = f"""Analyze this newsletter article and extract the following information:

Title: {title}
Content: {clean_content}

Please respond with ONLY a JSON object (no markdown, no explanation) with this structure:
{{
  "periods": ["period-id", ...],
  "event_summary": "brief factual summary of the event/trend/topic",
  "topics": ["topic-id", ...]
}}

Time periods to choose from (can select multiple):
- "early-90s" (1990-1994)
- "late-90s" (1995-1999)
- "early-2000s" (2000-2004)
- "late-2000s" (2005-2009)
- "early-2010s" (2010-2014)
- "late-2010s" (2015-2019)
- "early-2020s" (2020-2029)

Topics to choose from (can select multiple):
- "tech" - anything about tech companies, platforms, apps
- "memes" - internet trends, viral content, online culture
- "politics" - political events, movements, elections
- "entertainment" - TV, movies, music, celebrities

RULES FOR EVENT SUMMARY:
1. Write a brief, factual, matter-of-fact description of the news event, trend, meme, or political development discussed
2. Keep it to 1-2 sentences maximum
3. Focus on WHAT happened, WHEN it happened, and WHO was involved
4. Be specific with names, platforms, dates, and concrete details
5. Write in past tense as if describing a historical event
6. Examples of good summaries:
   - "Vine, the six-second video platform, shut down in January 2017 despite its cultural influence on internet humor"
   - "MySpace launched in August 2003 and popularized the concept of customizable social media profiles with HTML and top 8 friends"
   - "The Tumblr adult content ban went into effect in December 2018, fundamentally changing the platform's user base"

OTHER RULES:
1. Select periods based on WHEN the event happened, not when the article was published
2. Select all relevant topics that apply
3. Can select multiple periods if the article discusses events across different eras"""

    try:
        response = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are an expert at analyzing internet culture and history content. Always respond with valid JSON only."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3,
            max_tokens=500
        )
        
        result_text = response.choices[0].message.content.strip()
        
        # Remove markdown code blocks if present
        result_text = re.sub(r'^```json\s*|\s*```$', '', result_text, flags=re.MULTILINE)
        
        result = json.loads(result_text)
        
        # Validate the response
        if not isinstance(result.get('periods'), list) or not result['periods']:
            result['periods'] = ['late-2010s']  # default
        if not isinstance(result.get('topics'), list) or not result['topics']:
            result['topics'] = ['tech']  # default
        if not result.get('event_summary'):
            # Fallback: use first 200 chars of clean content
            result['event_summary'] = clean_content[:200] + "..."
            
        return result
        
    except Exception as e:
        print(f"Error analyzing article: {e}")
        # Return safe defaults
        return {
            "periods": ["late-2010s"],
            "event_summary": clean_content[:200] + "..." if clean_content else "...",
            "topics": ["tech"]
        }


def store_article(article_data: Dict) -> bool:
    """Store analyzed article in Supabase"""
    try:
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
        
        return True
    except Exception as e:
        print(f"Error storing article: {e}")
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
        
        return article_data
        
    except Exception as e:
        print(f"Error processing article {post.get('id')}: {e}")
        return None


def import_all_posts():
    """Import and process all posts from Beehiiv"""
    print("Starting Beehiiv import...")
    print(f"Using Publication ID: {BEEHIIV_PUBLICATION_ID}")
    print(f"API Key present: {'Yes' if BEEHIIV_API_KEY else 'No'}")
    
    page = 1
    total_processed = 0
    
    while True:
        print(f"\nFetching page {page}...")
        
        try:
            response = fetch_beehiiv_posts(limit=50, page=page)
            posts = response.get('data', [])
            
            if not posts:
                print("No more posts to fetch")
                break
            
            print(f"Found {len(posts)} posts on page {page}")
            
            for post in posts:
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
