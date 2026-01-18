from flask import Flask, jsonify
from flask_cors import CORS
from app import get_articles_for_frontend

app = Flask(__name__)
CORS(app)

@app.route('/api/articles')
def articles():
    return jsonify(get_articles_for_frontend())

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', 8080)))
