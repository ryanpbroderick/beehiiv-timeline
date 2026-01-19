import os
import re
from datetime import datetime
from typing import List, Dict, Optional, Tuple
import requests
from supabase import create_client, Client

# Configuration
BEEHIIV_API_KEY = os.getenv('BEEHIIV_API_KEY')
BEEHIIV_PUBLICATION_ID = os.getenv('BEEHIIV_PUBLICATION_ID')
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')

# Initialize clients
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Temporal patterns
YEAR_PATTERN = re.compile(r'\b(19\d{2}|20[0-2]\d)\b')
TEMPORAL_PHRASES = [
    r'in (\d{4})',
    r'during the (\w+) administration',
    r'(\d+) years? ago',
    r'a decade ago',
    r'back in (\d{4})',
    r'since (\d{4})',
    r'(\d{4})[-–](\d{4})',
]

CONNECTION_PHRASES = [
    'this reminds me of',
    'similar to',
    'echoes',
    'again',
    'happened before',
    'déjà vu',
    'like when',
    'just like',
    'repeat',
    'recurring',
    'cyclical',
]

# Common entities to extract
PLATFORMS = [
    'Facebook', 'Twitter', 'Instagram', 'TikTok', 'YouTube', 'Snapchat',
    'Reddit', 'Tumblr', 'MySpace', 'Vine', 'Discord', 'Telegram',
    'WhatsApp', 'LinkedIn', 'Pinterest', 'Twitch', 'BeReal',
    'Substack', 'Medium', 'WordPress', 'Patreon'
]

COMPANIES = [
    'Google', 'Meta', 'Microsoft', 'Apple', 'Amazon', 'Netflix',
    'Tesla', 'OpenAI', 'Anthropic', 'Adobe', 'Oracle', 'Salesforce'
]


def fetch_beehiiv_posts(limit: int = 50, page: int = 1) -> Dict:
    """Fetch posts from Beehiiv API"""
    url = f"https://api.beehiiv.com/v2/publications/{BEEHIIV_PUBLICATION_ID}/posts"
    headers = {
        "Authorization": f"Bearer {BEEHIIV_API_KEY}",
        "Content-Type": "application/json"
    }
    
    params = {"limit": limit, "page": page}
    
    try:
        response = requests.get(url, headers=headers, params=params)
        if response.status_code == 200:
            return response.json()
        else:
            raise Exception(f"API Error: {response.status_code}")
    except Exception as e:
        print(f"Error fetching posts: {e}")
        raise


def strip_html(html: str) -> str:
    """Remove HTML tags"""
    return re.sub(r'<[^>]+>', '', html or '')


def extract_sentences(text: str) -> List[str]:
    """Split text into sentences"""
    # Simple sentence splitting
    sentences = re.split(r'[.!?]+\s+', text)
    return [s.strip() for s in sentences if len(s.strip()) > 20]


def extract_paragraphs(text: str) -> List[str]:
    """Split text into paragraphs"""
    paragraphs = re.split(r'\n\s*\n', text)
    return [p.strip() for p in paragraphs if len(p.strip()) > 50]


def extract_years(text: str) -> List[int]:
    """Extract all years from text"""
    years = YEAR_PATTERN.findall(text)
    return sorted(set(int(y) for y in years if 1990 <= int(y) <= 2025))


def has_temporal_reference(text: str) -> bool:
    """Check if text contains temporal references"""
    text_lower = text.lower()
    
    # Check for year patterns
    if YEAR_PATTERN.search(text):
        return True
    
    # Check for temporal phrases
    for pattern in TEMPORAL_PHRASES:
        if re.search(pattern, text, re.IGNORECASE):
            return True
    
    return False


def has_connection_phrase(text: str) -> bool:
    """Check if text contains connection/comparison phrases"""
    text_lower = text.lower()
    return any(phrase in text_lower for phrase in CONNECTION_PHRASES)


def extract_entities(text: str) -> List[str]:
    """Extract platform names, companies, and capitalized entities"""
    entities = set()
    
    # Add known platforms and companies
    for platform in PLATFORMS:
        if platform in text:
            entities.add(platform)
    
    for company in COMPANIES:
        if company in text:
            entities.add(company)
    
    # Extract capitalized words (potential entities)
    # Match words that start with capital and have 3+ chars
    caps = re.findall(r'\b[A-Z][a-z]{2,}(?:\s+[A-Z][a-z]+)*\b', text)
    for cap in caps:
        # Filter out common words
        if cap.lower() not in ['the', 'this', 'that', 'these', 'those', 'when', 'where']:
            if len(cap) > 3:  # Skip very short words
                entities.add(cap)
    
    return sorted(list(entities))[:10]  # Limit to 10 tags


def get_context_paragraph(text: str, sentence: str) -> str:
    """Get the paragraph containing the sentence"""
    paragraphs = extract_paragraphs(text)
    
    for para in paragraphs:
        if sentence in para:
            return para
    
    return sentence


def extract_cards_from_article(title: str, content: str, publish_date: str, url: str, beehiiv_id: str) -> List[Dict]:
    """Extract cards deterministically from article"""
    
    clean_text = strip_html(content)
    sentences = extract_sentences(clean_text)
    
    cards = []
    card_index = 0
    
    for sentence in sentences:
        # Skip if sentence is too short or too long
        if len(sentence) < 30 or len(sentence) > 500:
            continue
        
        # Check if sentence has temporal reference or connection phrase
        has_temporal = has_temporal_reference(sentence)
        has_connection = has_connection_phrase(sentence)
        
        if not (has_temporal or has_connection):
            continue
        
        # Extract years from sentence
        years = extract_years(sentence)
        
        # Get surrounding context
        context = get_context_paragraph(clean_text, sentence)
        
        # Extract entities for tags
        tags = extract_entities(context)
        
        # Determine timeline year (use earliest mentioned year, or None)
        timeline_year = min(years) if years else None
        
        # Create card
        card = {
            'beehiiv_id': beehiiv_id,
            'card_index': card_index,
            'title': sentence[:200],  # Truncate if too long
            'body': context[:1000],  # Limit body size
            'timeline_year': timeline_year,
            'tags': tags,
            'issue_title': title,
            'issue_url': url,
            'publish_date': publish_date,
        }
        
        cards.append(card)
        card_index += 1
        
        # Limit to 10 cards per article
        if card_index >= 10:
            break
    
    return cards


def store_cards(cards: List[Dict]) -> bool:
    """Store cards in Supabase"""
    try:
        if not cards:
            return True
        
        # Delete existing cards for this issue
        beehiiv_id = cards[0]['beehiiv_id']
        supabase.table('cards').delete().eq('beehiiv_id', beehiiv_id).execute()
        
        # Insert new cards
        supabase.table('cards').insert(cards).execute()
        print(f"✅ Stored {len(cards)} cards")
        return True
    except Exception as e:
        print(f"❌ Error storing cards: {e}")
        return False


def process_article(post: Dict) -> int:
    """Process a single article and return number of cards created"""
    try:
        beehiiv_id = post['id']
        title = post.get('title', 'Untitled')
        content = post.get('content_html', '') or post.get('content', '')
        publish_date = post.get('published_at') or post.get('created_at') or datetime.utcnow().isoformat()
        url = post.get('web_url', '#')
        
        print(f"\n📄 Processing: {title}")
        
        # Extract cards
        cards = extract_cards_from_article(title, content, publish_date, url, beehiiv_id)
        
        print(f"   Found {len(cards)} cards")
        
        # Store cards
        if cards:
            store_cards(cards)
        
        return len(cards)
        
    except Exception as e:
        print(f"❌ Error processing article: {e}")
        return 0


def import_posts(max_issues: int = 50):
    """Import posts and extract cards"""
    print(f"🚀 Starting import (max {max_issues} issues)...")
    print(f"   Publication ID: {BEEHIIV_PUBLICATION_ID}")
    
    page = 1
    total_issues = 0
    total_cards = 0
    
    while total_issues < max_issues:
        print(f"\n📥 Fetching page {page}...")
        
        try:
            response = fetch_beehiiv_posts(limit=50, page=page)
            posts = response.get('data', [])
            
            if not posts:
                print("No more posts")
                break
            
            for post in posts:
                if total_issues >= max_issues:
                    break
                
                cards_created = process_article(post)
                total_cards += cards_created
                total_issues += 1
            
            page += 1
            
        except Exception as e:
            print(f"❌ Error fetching page: {e}")
            break
    
    print(f"\n✅ Import complete!")
    print(f"   Processed {total_issues} issues")
    print(f"   Created {total_cards} cards")
    
    return total_cards


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        max_issues = int(sys.argv[1])
    else:
        max_issues = 50
    
    import_posts(max_issues)
