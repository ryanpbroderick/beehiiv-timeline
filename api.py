import os
import sys
from flask import Flask, jsonify, render_template
from flask_cors import CORS
from supabase import create_client, Client

# Import the import function from app.py
sys.path.insert(0, os.path.dirname(__file__))
from app import import_all_posts

app = Flask(__name__, template_folder='templates', static_folder='static')
CORS(app)

SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# Track import status
import_status = {
    'running': False,
    'last_run': None,
    'last_count': 0
}

@app.route('/api/articles')
def get_articles():
    try:
        result = supabase.table('articles').select('*').order('publish_date', desc=False).execute()
        
        articles = []
        for article in result.data:
            articles.append({
                'id': article['beehiiv_id'],
                'title': article['title'],
                'url': article['url'],
                'pullQuote': article['pull_quote'],
                'periods': article['periods'],
                'topics': article['topics'],
                'publishDate': article['publish_date']
            })
        
        return jsonify({
            'success': True,
            'articles': articles,
            'total': len(articles)
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/cards')
def get_cards():
    """Return generated cards (one row per card) for the UI."""
    try:
        # Order by then_start primarily (nulls last), then publish_date.
        # Supabase python client doesn't support NULLS LAST syntax directly; simple ordering is fine for MVP.
        result = supabase.table('cards').select('*').order('then_start', desc=False).order('publish_date', desc=False).execute()

        cards = []
        for row in result.data:
            cards.append({
                'id': row.get('id') or f"{row.get('beehiiv_id')}:{row.get('card_index')}",
                'beehiiv_id': row.get('beehiiv_id'),
                'cardIndex': row.get('card_index'),
                'claim': row.get('claim'),
                'thenStart': row.get('then_start'),
                'thenEnd': row.get('then_end'),
                'nowLabel': row.get('now_label'),
                'linkType': row.get('link_type'),
                'tags': row.get('tags') or [],
                'evidence': row.get('evidence') or [],
                'confidence': row.get('confidence'),
                'publishDate': row.get('publish_date'),
                'issueTitle': row.get('issue_title'),
                'issueUrl': row.get('issue_url'),
            })

        return jsonify({
            'success': True,
            'cards': cards,
            'total': len(cards)
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/')
def index():
    """Mobile-friendly card browser."""
    return render_template('index.html')

@app.route('/api/run-import')
def run_import():
    """Trigger the Beehiiv import process
    
    Query params:
        test=1 - Process only 50 issues for testing
    """
    global import_status
    
    if import_status['running']:
        return jsonify({
            'success': False,
            'error': 'Import already running',
            'status': import_status
        }), 400
    
    try:
        import_status['running'] = True
        
        # Check for test mode
        from flask import request
        test_mode = request.args.get('test') == '1'
        max_issues = 50 if test_mode else None
        
        # Run the import in a separate thread so it doesn't block
        import threading
        from datetime import datetime
        
        def run_import_thread():
            global import_status
            try:
                count = import_all_posts(max_issues=max_issues)
                import_status['last_count'] = count
                import_status['last_run'] = datetime.utcnow().isoformat()
            except Exception as e:
                print(f"Import error: {e}")
            finally:
                import_status['running'] = False
        
        thread = threading.Thread(target=run_import_thread)
        thread.start()
        
        mode_msg = "test mode (50 issues max)" if test_mode else "full import (all issues)"
        
        return jsonify({
            'success': True,
            'message': f'Import started in background ({mode_msg})',
            'note': 'This will take 10-15 minutes for 50 issues. Check /api/import-status for progress',
            'test_mode': test_mode
        })
    except Exception as e:
        import_status['running'] = False
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/import-status')
def import_status_endpoint():
    """Check the status of the import"""
    return jsonify({
        'success': True,
        'status': import_status
    })

@app.route('/api/health')
def health():
    return jsonify({'status': 'ok'})

if __name__ == '__main__':
    port = int(os.getenv('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
