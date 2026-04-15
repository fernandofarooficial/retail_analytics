import os
from datetime import datetime
from flask import Flask
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__, static_url_path='/retail_analytics/static')
app.secret_key = os.environ['SECRET_KEY']


@app.context_processor
def inject_now():
    return {'now': datetime.utcnow()}


from routes.auth      import auth_bp
from routes.cadastros import cadastros_bp
from routes.conta     import conta_bp
from routes.usuarios  import usuarios_bp
from routes.mobile    import mobile_bp

app.register_blueprint(auth_bp,      url_prefix='/retail_analytics')
app.register_blueprint(cadastros_bp)
app.register_blueprint(conta_bp)
app.register_blueprint(usuarios_bp)
app.register_blueprint(mobile_bp,    url_prefix='/retail_analytics/m')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5003, debug=False)
