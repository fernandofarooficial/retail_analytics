import os
from datetime import datetime
from flask import Flask
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__, static_url_path='/retail_analytics/static')
app.secret_key = os.environ['SECRET_KEY']

# Disponibiliza `now` globalmente nos templates
@app.context_processor
def inject_now():
    return {'now': datetime.utcnow()}

from routes.auth import auth_bp
app.register_blueprint(auth_bp, url_prefix='/retail_analytics')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5003, debug=False)
