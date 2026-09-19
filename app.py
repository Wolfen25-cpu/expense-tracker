from flask import Flask

app = Flask(__name__)

@app.route("/")
def inicio():
    return "<h1>Rastreador de Gastos</h1><p>¡Funciona! 🎉</p>"

if __name__ == "__main__":
    app.run(debug=True)