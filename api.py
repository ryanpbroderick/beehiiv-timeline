import os
from flask import Flask, jsonify
from flask_cors import CORS
from supabase import create_client, Client

app = Flask(__name__)
CORS(app)

SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

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

@app.route('/api/health')
def health():
    return jsonify({'status': 'ok'})

if __name__ == '__main__':
    port = int(os.getenv('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
