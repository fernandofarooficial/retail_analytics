from flask import Flask

app = Flask(__name__)

@app.route('/')
def index():
    return 'retail_analytics funcionando!'

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5003, debug=False)