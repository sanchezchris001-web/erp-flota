from flask import Flask, render_template, request, jsonify, session, redirect
from flask_sqlalchemy import SQLAlchemy
from flask_socketio import SocketIO
from datetime import datetime

app = Flask(__name__)
app.config["SECRET_KEY"] = "secret123"
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///db.sqlite3"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)
socketio = SocketIO(app, async_mode="threading")

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

# ================= MOVIMIENTOS =================

@app.route("/movimientos")
def movimientos():
    if not require_login() or not is_admin():
        return "", 403

    return jsonify([
        {
            "tipo":m.tipo,
            "obs":m.observacion,
            "fecha":m.fecha.strftime("%Y-%m-%d %H:%M")
        }
        for m in Movimiento.query.order_by(Movimiento.fecha.desc()).all()
    ])

# ================= USUARIOS (CRUD COMPLETO) =================

@app.route("/usuarios")
def usuarios():
    if not is_admin():
        return "", 403
    return jsonify([
        {"id":u.id,"username":u.username,"rol":u.rol}
        for u in Usuario.query.all()
    ])


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


@app.route("/editar_usuario", methods=["POST"])
def editar_usuario():
    if not is_admin():
        return "", 403

    data = request.json
    u = Usuario.query.get(data["id"])
    if not u:
        return "", 404

    u.username = data["username"]
    u.password = data["password"]
    u.rol = data["rol"]
    db.session.commit()
    return "", 200


@app.route("/eliminar_usuario", methods=["POST"])
def eliminar_usuario():
    if not is_admin():
        return "", 403

    data = request.json
    u = Usuario.query.get(data["id"])
    if not u:
        return "", 404

    db.session.delete(u)
    db.session.commit()
    return "", 200

# ================= CONDUCTORES =================

@app.route("/crear_conductor", methods=["POST"])
def crear_conductor():
    if not is_supervisor():
        return "", 403

    data = request.json
    db.session.add(Conductor(nombre=data["nombre"]))
    db.session.commit()
    socketio.emit("actualizar")
    return "", 200

# ================= UNIDADES =================

@app.route("/crear_unidad", methods=["POST"])
def crear_unidad():
    if not is_supervisor():
        return "", 403

    data = request.json
    db.session.add(Unidad(placa=data["placa"]))
    db.session.commit()
    socketio.emit("actualizar")
    return "", 200

# ================= ASIGNAR =================

@app.route("/asignar", methods=["POST"])
def asignar():
    if not is_supervisor():
        return "", 403

    data = request.json

    if not data.get("conductor_id") or not data.get("unidad_id"):
        return "", 400

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

    if conductor_id and not unidad_id:
        c = Conductor.query.get(conductor_id)
        if not c:
            return "", 404
        c.estado = "disponible"
        db.session.add(Movimiento(tipo=f"Finalizó conductor {c.nombre}"))

    elif unidad_id and not conductor_id:
        u = Unidad.query.get(unidad_id)
        if not u:
            return "", 404
        u.estado = "disponible"
        db.session.add(Movimiento(tipo=f"Finalizó unidad {u.placa}"))

    elif conductor_id and unidad_id:
        c = Conductor.query.get(conductor_id)
        u = Unidad.query.get(unidad_id)
        if not c or not u:
            return "", 404
        c.estado = "disponible"
        u.estado = "disponible"
        db.session.add(Movimiento(tipo=f"Finalizó {c.nombre} → {u.placa}"))

    else:
        return "", 400

    db.session.commit()
    socketio.emit("actualizar")
    return "", 200

# ================= INHABILITAR / HABILITAR =================

@app.route("/inhabilitar", methods=["POST"])
def inhabilitar():
    if not is_supervisor():
        return "", 403

    data = request.json
    u = Unidad.query.get(data["unidad_id"])
    u.estado = "inhabilitado"

    db.session.add(Movimiento(
        tipo=f"Inhabilitado {u.placa}",
        observacion=data.get("observacion")
    ))
    db.session.commit()
    socketio.emit("actualizar")
    return "", 200


@app.route("/habilitar", methods=["POST"])
def habilitar():
    if not is_supervisor():
        return "", 403

    data = request.json
    u = Unidad.query.get(data["unidad_id"])
    u.estado = "disponible"

    db.session.add(Movimiento(tipo=f"Habilitado {u.placa}"))
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

    socketio.run(app, debug=True)