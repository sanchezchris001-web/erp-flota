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

socketio = SocketIO(app, async_mode="eventlet", cors_allowed_origins="*")

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
    tipo = db.Column(db.String(150))
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

    asignaciones = [
        {"conductor": c.nombre, "unidad": u.placa, "estado": "En ruta"}
        for c in conductores if c.estado == "en_ruta"
        for u in unidades if u.estado == "ocupada"
    ]

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

# ================= MOVIMIENTOS (HISTORIAL ARREGLADO) =================

@app.route("/movimientos")
def movimientos():
    if not require_login():
        return "", 403

    return jsonify([
        {
            "tipo": m.tipo,
            "obs": m.observacion or "",
            "fecha": m.fecha.strftime("%Y-%m-%d %H:%M")
        }
        for m in Movimiento.query.order_by(Movimiento.fecha.desc()).all()
    ])

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

    d = request.json
    db.session.add(Usuario(username=d["username"], password=d["password"], rol=d["rol"]))
    db.session.commit()
    return "", 200


@app.route("/editar_usuario", methods=["POST"])
def editar_usuario():
    if not is_admin():
        return "", 403

    d = request.json
    u = Usuario.query.get(d["id"])
    u.username = d["username"]
    u.rol = d["rol"]
    if d.get("password"):
        u.password = d["password"]
    db.session.commit()
    return "", 200


@app.route("/eliminar_usuario", methods=["POST"])
def eliminar_usuario():
    if not is_admin():
        return "", 403

    u = Usuario.query.get(request.json["id"])
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


@app.route("/editar_conductor", methods=["POST"])
def editar_conductor():
    if not is_supervisor():
        return "", 403

    c = Conductor.query.get(request.json["id"])
    c.nombre = request.json["nombre"]
    db.session.commit()
    return "", 200


@app.route("/eliminar_conductor", methods=["POST"])
def eliminar_conductor():
    if not is_supervisor():
        return "", 403

    c = Conductor.query.get(request.json["id"])
    db.session.delete(c)
    db.session.commit()
    return "", 200

# ================= UNIDADES =================

@app.route("/crear_unidad", methods=["POST"])
def crear_unidad():
    if not is_supervisor():
        return "", 403

    db.session.add(Unidad(placa=request.json["placa"]))
    db.session.commit()
    return "", 200


@app.route("/editar_unidad", methods=["POST"])
def editar_unidad():
    if not is_supervisor():
        return "", 403

    u = Unidad.query.get(request.json["id"])
    u.placa = request.json["placa"]
    db.session.commit()
    return "", 200


@app.route("/eliminar_unidad", methods=["POST"])
def eliminar_unidad():
    if not is_supervisor():
        return "", 403

    u = Unidad.query.get(request.json["id"])
    db.session.delete(u)
    db.session.commit()
    return "", 200

# ================= OPERACIONES =================

@app.route("/asignar", methods=["POST"])
def asignar():
    if not is_supervisor():
        return "", 403

    d = request.json

    c = Conductor.query.get(d["conductor_id"])
    u = Unidad.query.get(d["unidad_id"])

    if c: c.estado = "en_ruta"
    if u: u.estado = "ocupada"

    db.session.add(Movimiento(tipo=f"Asignación {c.nombre} → {u.placa}"))
    db.session.commit()
    return "", 200


@app.route("/finalizar", methods=["POST"])
def finalizar():
    if not is_supervisor():
        return "", 403

    d = request.json

    if d.get("conductor_id"):
        c = Conductor.query.get(d["conductor_id"])
        if c: c.estado = "disponible"

    if d.get("unidad_id"):
        u = Unidad.query.get(d["unidad_id"])
        if u: u.estado = "disponible"

    db.session.add(Movimiento(tipo="Finalización de operación"))
    db.session.commit()
    return "", 200


@app.route("/inhabilitar", methods=["POST"])
def inhabilitar():
    if not is_supervisor():
        return "", 403

    u = Unidad.query.get(request.json["unidad_id"])
    if u: u.estado = "inhabilitado"

    db.session.commit()
    return "", 200


@app.route("/habilitar", methods=["POST"])
def habilitar():
    if not is_supervisor():
        return "", 403

    u = Unidad.query.get(request.json["unidad_id"])
    if u: u.estado = "disponible"

    db.session.commit()
    return "", 200

# ================= INIT =================

if __name__ == "__main__":
    with app.app_context():
        db.create_all()

        if not Usuario.query.filter_by(username="admin").first():
            db.session.add(Usuario(username="admin", password="admin", rol="admin"))
            db.session.commit()

    port = int(os.environ.get("PORT", 5000))
    socketio.run(app, host="0.0.0.0", port=port, debug=False)