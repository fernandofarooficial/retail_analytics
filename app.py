import os
from datetime import datetime
from flask import Flask
from dotenv import load_dotenv
from extensions import cache

load_dotenv()

app = Flask(__name__, static_url_path='/retail_analytics/static')
app.secret_key = os.environ['SECRET_KEY']

cache.init_app(app, config={
    'CACHE_TYPE': 'SimpleCache',
    'CACHE_DEFAULT_TIMEOUT': 900,
})


@app.context_processor
def inject_now():
    return {'now': datetime.utcnow()}


@app.template_filter('fmt_cep')
def fmt_cep_filter(cep):
    """Formata CEP para o padrão 00000-000."""
    if not cep:
        return '—'
    digits = str(cep).replace('-', '').replace('.', '').zfill(8)[:8]
    return f'{digits[:5]}-{digits[5:]}'


@app.template_filter('br_valor')
def br_valor_filter(value, symbol=''):
    """Formata número no padrão brasileiro com símbolo da unidade."""
    if value is None:
        return '—'
    try:
        v = float(value)
        fmt = f'{v:,.2f}'.replace(',', 'X').replace('.', ',').replace('X', '.')
        if symbol == 'R$':
            return f'R$ {fmt}'
        elif symbol == '%':
            return f'{fmt}%'
        elif symbol:
            return f'{fmt} {symbol}'
        return fmt
    except (ValueError, TypeError):
        return '—'


from routes.auth      import auth_bp
from routes.cadastros import cadastros_bp
from routes.conta     import conta_bp
from routes.usuarios  import usuarios_bp
from routes.mobile    import mobile_bp
from routes.metas     import metas_bp
from routes.gestao    import gestao_bp
from routes.motor     import motor_bp

app.register_blueprint(auth_bp,      url_prefix='/retail_analytics')
app.register_blueprint(cadastros_bp)
app.register_blueprint(conta_bp)
app.register_blueprint(usuarios_bp)
app.register_blueprint(mobile_bp,    url_prefix='/retail_analytics/m')
app.register_blueprint(metas_bp)
app.register_blueprint(gestao_bp)
app.register_blueprint(motor_bp)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5003, debug=False)
