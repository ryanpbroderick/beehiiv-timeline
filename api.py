import os
import sys
import threading
from datetime import datetime
from flask import Flask, jsonify, send_from_directory
from flask_cors import CORS
from supabase import create_client, Client

sys.path.insert(0, os.path.dirname(__file__))
from app import import_posts

app = Flask(__name__, static_folder='static')
CORS(app)

SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

import_status = {
    'running': False,
    'last_run': None,
    'last_count': 0
}

@app.route('/')
def index():
    return send_from_directory('static', 'index.html')

@app.route('/api/cards')
def get_cards():
    """Get all cards sorted by timeline year"""
    try:
        # Order by timeline_year (nulls last), then publish_date
        result = supabase.table('cards') \
            .select('*') \
            .order('timeline_year', desc=False) \
            .order('publish_date', desc=False) \
            .execute()
        
        return jsonify({
            'success': True,
            'cards': result.data,
            'total': len(result.data)
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/run-import')
def run_import():
    """Trigger import (defaults to 50 issues)"""
    global import_status
    
    if import_status['running']:
        return jsonify({
            'success': False,
            'error': 'Import already running'
        }), 400
    
    try:
        import_status['running'] = True
        
        def import_thread():
            global import_status
            try:
                count = import_posts(max_issues=50)
                import_status['last_count'] = count
                import_status['last_run'] = datetime.utcnow().isoformat()
            except Exception as e:
                print(f"Import error: {e}")
            finally:
                import_status['running'] = False
        
        thread = threading.Thread(target=import_thread)
        thread.start()
        
        return jsonify({
            'success': True,
            'message': 'Import started (50 issues)',
            'note': 'Check /api/import-status for progress'
        })
    except Exception as e:
        import_status['running'] = False
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/import-status')
def import_status_route():
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
