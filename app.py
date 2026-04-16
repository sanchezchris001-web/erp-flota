import os
from flask import Flask, render_template, request, jsonify, session, redirect
from flask_sqlalchemy import SQLAlchemy
from flask_socketio import SocketIO
from datetime import datetime

import eventlet
eventlet.monkey_patch()

app = Flask(__name__)
app.config["SECRET_KEY"] = "secret123"
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///db.sqlite3"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)

socketio = SocketIO(
    app,
    async_mode="eventlet",
    cors_allowed_origins="*"
)

# ================= MODELOS =================

class Usuario(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True)
    password = db.Column(db.String(50))
    rol = db.Column(db.String(20))


class Conductor(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100))
    estado = db.Column(db.String(20), default="disponible")


class Unidad(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    placa = db.Column(db.String(50))
    estado = db.Column(db.String(20), default="disponible")


class Movimiento(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    tipo = db.Column(db.String(100))
    observacion = db.Column(db.String(200))
    fecha = db.Column(db.DateTime, default=datetime.utcnow)

# ================= HELPERS =================

def require_login():
    return "user_id" in session

def current_user():
    return Usuario.query.get(session["user_id"]) if require_login() else None

def is_admin():
    u = current_user()
    return u and u.rol == "admin"

def is_supervisor():
    u = current_user()
    return u and u.rol in ["admin", "supervisor"]

# ================= LOGIN =================

@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        u = Usuario.query.filter_by(
            username=request.form["username"],
            password=request.form["password"]
        ).first()

        if u:
            session["user_id"] = u.id
            return redirect("/home")

    return render_template("login.html")


@app.route("/home")
def home():
    if not require_login():
        return redirect("/")
    return render_template("index.html", user=current_user())


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

# ================= DATOS =================

@app.route("/datos")
def datos():
    if not require_login():
        return "", 403

    conductores = Conductor.query.all()
    unidades = Unidad.query.all()

    asignaciones = []
    for c in conductores:
        if c.estado == "en_ruta":
            unidad = next((u for u in unidades if u.estado == "ocupada"), None)
            if unidad:
                asignaciones.append({
                    "conductor": c.nombre,
                    "unidad": unidad.placa,
                    "estado": "En ruta"
                })

    return jsonify({
        "conductores":[{"id":c.id,"nombre":c.nombre,"estado":c.estado} for c in conductores],
        "unidades":[{"id":u.id,"placa":u.placa,"estado":u.estado} for u in unidades],
        "asignaciones": asignaciones,
        "stats":{
            "conductores_disponibles": len([c for c in conductores if c.estado=="disponible"]),
            "conductores_ocupados": len([c for c in conductores if c.estado=="en_ruta"]),
            "unidades_disponibles": len([u for u in unidades if u.estado=="disponible"]),
            "unidades_ocupadas": len([u for u in unidades if u.estado=="ocupada"]),
            "unidades_inhabilitadas": len([u for u in unidades if u.estado=="inhabilitado"])
        }
    })

# ================= USUARIOS =================

@app.route("/usuarios")
def usuarios():
    if not is_admin():
        return "", 403
    return jsonify([{"id":u.id,"username":u.username,"rol":u.rol} for u in Usuario.query.all()])


@app.route("/crear_usuario", methods=["POST"])
def crear_usuario():
    if not is_admin():
        return "", 403

    data = request.json
    db.session.add(Usuario(
        username=data["username"],
        password=data["password"],
        rol=data["rol"]
    ))
    db.session.commit()
    return "", 200


@app.route("/eliminar_usuario", methods=["POST"])
def eliminar_usuario():
    if not is_admin():
        return "", 403

    data = request.json
    u = Usuario.query.get(data["id"])
    if u:
        db.session.delete(u)
        db.session.commit()
    return "", 200

# ================= CONDUCTORES =================

@app.route("/crear_conductor", methods=["POST"])
def crear_conductor():
    if not is_supervisor():
        return "", 403

    db.session.add(Conductor(nombre=request.json["nombre"]))
    db.session.commit()
    socketio.emit("actualizar")
    return "", 200

# ================= UNIDADES =================

@app.route("/crear_unidad", methods=["POST"])
def crear_unidad():
    if not is_supervisor():
        return "", 403

    db.session.add(Unidad(placa=request.json["placa"]))
    db.session.commit()
    socketio.emit("actualizar")
    return "", 200

# ================= ASIGNAR =================

@app.route("/asignar", methods=["POST"])
def asignar():
    if not is_supervisor():
        return "", 403

    data = request.json

    c = Conductor.query.get(data["conductor_id"])
    u = Unidad.query.get(data["unidad_id"])

    if not c or not u:
        return "", 404

    c.estado = "en_ruta"
    u.estado = "ocupada"

    db.session.add(Movimiento(tipo=f"Asignación {c.nombre} → {u.placa}"))
    db.session.commit()
    socketio.emit("actualizar")
    return "", 200

# ================= FINALIZAR =================

@app.route("/finalizar", methods=["POST"])
def finalizar():
    if not is_supervisor():
        return "", 403

    data = request.json

    conductor_id = data.get("conductor_id")
    unidad_id = data.get("unidad_id")

    if conductor_id:
        c = Conductor.query.get(conductor_id)
        if c:
            c.estado = "disponible"

    if unidad_id:
        u = Unidad.query.get(unidad_id)
        if u:
            u.estado = "disponible"

    db.session.add(Movimiento(tipo="Finalización de operación"))
    db.session.commit()
    socketio.emit("actualizar")
    return "", 200

# ================= INHABILITAR =================

@app.route("/inhabilitar", methods=["POST"])
def inhabilitar():
    if not is_supervisor():
        return "", 403

    u = Unidad.query.get(request.json["unidad_id"])
    if u:
        u.estado = "inhabilitado"

    db.session.commit()
    socketio.emit("actualizar")
    return "", 200

# ================= HABILITAR =================

@app.route("/habilitar", methods=["POST"])
def habilitar():
    if not is_supervisor():
        return "", 403

    u = Unidad.query.get(request.json["unidad_id"])
    if u:
        u.estado = "disponible"

    db.session.commit()
    socketio.emit("actualizar")
    return "", 200

# ================= INIT =================

if __name__ == "__main__":
    with app.app_context():
        db.create_all()

        if not Usuario.query.filter_by(username="admin").first():
            db.session.add(Usuario(username="admin", password="admin", rol="admin"))
            db.session.commit()

    port = int(os.environ.get("PORT", 5000))

    socketio.run(
        app,
        host="0.0.0.0",
        port=port,
        debug=False
    )