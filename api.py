import os
import sys
from flask import Flask, jsonify
from flask_cors import CORS
from supabase import create_client, Client

# Import the import function from app.py
sys.path.insert(0, os.path.dirname(__file__))
from app import import_all_posts

app = Flask(__name__)
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

@app.route('/api/run-import')
def run_import():
    """Trigger the Beehiiv import process"""
    global import_status
    
    if import_status['running']:
        return jsonify({
            'success': False,
            'error': 'Import already running',
            'status': import_status
        }), 400
    
    try:
        import_status['running'] = True
        
        # Run the import in a separate thread so it doesn't block
        import threading
        from datetime import datetime
        
        def run_import_thread():
            global import_status
            try:
                count = import_all_posts()
                import_status['last_count'] = count
                import_status['last_run'] = datetime.utcnow().isoformat()
            except Exception as e:
                print(f"Import error: {e}")
            finally:
                import_status['running'] = False
        
        thread = threading.Thread(target=run_import_thread)
        thread.start()
        
        return jsonify({
            'success': True,
            'message': 'Import started in background',
            'note': 'This will take 10-15 minutes. Check /api/import-status for progress'
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
