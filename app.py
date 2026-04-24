from flask import Flask, request, jsonify, session, redirect, render_template
import psycopg2
import os
from datetime import datetime

app = Flask(__name__)
app.secret_key = "secret123"

# ================= CONEXIÓN =================
def get_db():
    return psycopg2.connect(
        os.environ.get("DATABASE_URL"),
        sslmode="require"
    )

# ================= INIT DB =================
def init_db():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS conductores(
        id SERIAL PRIMARY KEY,
        nombre TEXT,
        estado TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS unidades(
        id SERIAL PRIMARY KEY,
        placa TEXT,
        estado TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS asignaciones(
        id SERIAL PRIMARY KEY,
        conductor_id INTEGER,
        unidad_id INTEGER
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS movimientos(
        id SERIAL PRIMARY KEY,
        accion TEXT,
        usuario TEXT,
        fecha TEXT,
        obs TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS usuarios(
        id SERIAL PRIMARY KEY,
        username TEXT,
        password TEXT,
        rol TEXT
    )
    """)

    conn.commit()
    conn.close()

# ================= INIT ENDPOINT =================
@app.route("/init")
def init():
    try:
        init_db()
        return "Base de datos creada correctamente"
    except Exception as e:
        return str(e)

# ================= LOGIN =================
@app.route("/login", methods=["POST"])
def login():
    data = request.json
    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        "SELECT * FROM usuarios WHERE username=%s AND password=%s",
        (data["username"], data["password"])
    )

    user = cur.fetchone()
    conn.close()

    if user:
        session["user"] = user[1]
        session["rol"] = user[3]
        return jsonify({"ok": True})
    return jsonify({"ok": False})

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

# ================= DATOS =================
@app.route("/datos")
def datos():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT * FROM conductores")
    conductores = cur.fetchall()

    cur.execute("SELECT * FROM unidades")
    unidades = cur.fetchall()

    cur.execute("""
        SELECT c.nombre, u.placa
        FROM asignaciones a
        JOIN conductores c ON c.id = a.conductor_id
        JOIN unidades u ON u.id = a.unidad_id
    """)
    asignaciones = cur.fetchall()

    stats = {}

    cur.execute("SELECT COUNT(*) FROM conductores WHERE estado='disponible'")
    stats["conductores_disponibles"] = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM conductores WHERE estado='en_ruta'")
    stats["conductores_ocupados"] = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM unidades WHERE estado='disponible'")
    stats["unidades_disponibles"] = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM unidades WHERE estado='ocupada'")
    stats["unidades_ocupadas"] = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM unidades WHERE estado='inhabilitado'")
    stats["unidades_inhabilitadas"] = cur.fetchone()[0]

    conn.close()

    return jsonify({
        "conductores": [{"id": x[0], "nombre": x[1], "estado": x[2]} for x in conductores],
        "unidades": [{"id": x[0], "placa": x[1], "estado": x[2]} for x in unidades],
        "asignaciones": [{"conductor": x[0], "unidad": x[1]} for x in asignaciones],
        "stats": stats
    })

# ================= CREAR =================
@app.route("/crear_conductor", methods=["POST"])
def crear_conductor():
    data = request.json
    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        "INSERT INTO conductores(nombre, estado) VALUES(%s,'disponible')",
        (data["nombre"],)
    )

    conn.commit()
    conn.close()
    return jsonify({"ok": True})

@app.route("/crear_unidad", methods=["POST"])
def crear_unidad():
    data = request.json
    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        "INSERT INTO unidades(placa, estado) VALUES(%s,'disponible')",
        (data["placa"],)
    )

    conn.commit()
    conn.close()
    return jsonify({"ok": True})

# ================= ASIGNAR =================
@app.route("/asignar", methods=["POST"])
def asignar():
    data = request.json
    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        "INSERT INTO asignaciones(conductor_id, unidad_id) VALUES(%s,%s)",
        (data["conductor_id"], data["unidad_id"])
    )

    cur.execute(
        "UPDATE conductores SET estado='en_ruta' WHERE id=%s",
        (data["conductor_id"],)
    )

    cur.execute(
        "UPDATE unidades SET estado='ocupada' WHERE id=%s",
        (data["unidad_id"],)
    )

    conn.commit()
    conn.close()
    return jsonify({"ok": True})

# ================= FINALIZAR =================
@app.route("/finalizar", methods=["POST"])
def finalizar():
    data = request.json
    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        "DELETE FROM asignaciones WHERE conductor_id=%s OR unidad_id=%s",
        (data.get("conductor_id"), data.get("unidad_id"))
    )

    cur.execute(
        "UPDATE conductores SET estado='disponible' WHERE id=%s",
        (data.get("conductor_id"),)
    )

    cur.execute(
        "UPDATE unidades SET estado='disponible' WHERE id=%s",
        (data.get("unidad_id"),)
    )

    conn.commit()
    conn.close()
    return jsonify({"ok": True})

# ================= ESTADO UNIDAD =================
@app.route("/cambiar_estado_unidad", methods=["POST"])
def cambiar_estado_unidad():
    data = request.json
    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        "UPDATE unidades SET estado=%s WHERE id=%s",
        (data["estado"], data["unidad_id"])
    )

    cur.execute(
        "INSERT INTO movimientos(accion, usuario, fecha, obs) VALUES(%s,%s,%s,%s)",
        (
            f"Unidad {data['estado']}",
            session.get("user", "system"),
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            data.get("observacion", "")
        )
    )

    conn.commit()
    conn.close()
    return jsonify({"ok": True})

# ================= MOVIMIENTOS =================
@app.route("/movimientos")
def movimientos():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT * FROM movimientos ORDER BY id DESC")
    data = cur.fetchall()

    conn.close()

    return jsonify([
        {"id": x[0], "accion": x[1], "usuario": x[2], "fecha": x[3], "obs": x[4]}
        for x in data
    ])

# ================= USUARIOS =================
@app.route("/usuarios")
def usuarios():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT id, username, rol FROM usuarios")
    data = cur.fetchall()

    conn.close()

    return jsonify([
        {"id": x[0], "username": x[1], "rol": x[2]}
        for x in data
    ])

@app.route("/crear_usuario", methods=["POST"])
def crear_usuario():
    data = request.json
    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        "INSERT INTO usuarios(username, password, rol) VALUES(%s,%s,%s)",
        (data["username"], data["password"], data["rol"])
    )

    conn.commit()
    conn.close()
    return jsonify({"ok": True})

@app.route("/editar_usuario", methods=["POST"])
def editar_usuario():
    data = request.json
    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        "UPDATE usuarios SET username=%s, password=%s, rol=%s WHERE id=%s",
        (data["username"], data["password"], data["rol"], data["id"])
    )

    conn.commit()
    conn.close()
    return jsonify({"ok": True})

@app.route("/eliminar_usuario", methods=["POST"])
def eliminar_usuario():
    data = request.json
    conn = get_db()
    cur = conn.cursor()

    cur.execute("DELETE FROM usuarios WHERE id=%s", (data["id"],))

    conn.commit()
    conn.close()
    return jsonify({"ok": True})

# ================= INDEX =================
@app.route("/")
def index():
    return render_template("index.html", user={
        "username": session.get("user", "Invitado"),
        "rol": session.get("rol", "user")
    })