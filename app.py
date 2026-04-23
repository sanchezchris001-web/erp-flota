from flask import Flask, request, jsonify, session, redirect, render_template
import sqlite3
from datetime import datetime

app = Flask(__name__)
app.secret_key = "secret123"

DB = "database.db"

# ================= CONEXIÓN =================
def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

# ================= LOGIN (ejemplo base) =================
@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

# ================= DATOS DASHBOARD =================
@app.route("/datos")
def datos():
    conn = get_db()
    cur = conn.cursor()

    conductores = cur.execute("SELECT * FROM conductores").fetchall()
    unidades = cur.execute("SELECT * FROM unidades").fetchall()

    asignaciones = cur.execute("""
        SELECT c.nombre as conductor, u.placa as unidad
        FROM asignaciones a
        JOIN conductores c ON c.id = a.conductor_id
        JOIN unidades u ON u.id = a.unidad_id
    """).fetchall()

    stats = {
        "conductores_disponibles": cur.execute("SELECT COUNT(*) FROM conductores WHERE estado='disponible'").fetchone()[0],
        "conductores_ocupados": cur.execute("SELECT COUNT(*) FROM conductores WHERE estado='en_ruta'").fetchone()[0],
        "unidades_disponibles": cur.execute("SELECT COUNT(*) FROM unidades WHERE estado='disponible'").fetchone()[0],
        "unidades_ocupadas": cur.execute("SELECT COUNT(*) FROM unidades WHERE estado='ocupada'").fetchone()[0],
        "unidades_inhabilitadas": cur.execute("SELECT COUNT(*) FROM unidades WHERE estado='inhabilitado'").fetchone()[0],
    }

    conn.close()

    return jsonify({
        "conductores": [dict(x) for x in conductores],
        "unidades": [dict(x) for x in unidades],
        "asignaciones": [dict(x) for x in asignaciones],
        "stats": stats
    })

# ================= CRUD BÁSICO =================
@app.route("/crear_conductor", methods=["POST"])
def crear_conductor():
    data = request.json
    conn = get_db()
    conn.execute("INSERT INTO conductores(nombre, estado) VALUES(?, 'disponible')",
                 (data["nombre"],))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})

@app.route("/crear_unidad", methods=["POST"])
def crear_unidad():
    data = request.json
    conn = get_db()
    conn.execute("INSERT INTO unidades(placa, estado) VALUES(?, 'disponible')",
                 (data["placa"],))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})

# ================= ASIGNAR =================
@app.route("/asignar", methods=["POST"])
def asignar():
    data = request.json
    conn = get_db()

    conn.execute("""
        INSERT INTO asignaciones(conductor_id, unidad_id)
        VALUES(?, ?)
    """, (data["conductor_id"], data["unidad_id"]))

    conn.execute("UPDATE conductores SET estado='en_ruta' WHERE id=?",
                 (data["conductor_id"],))

    conn.execute("UPDATE unidades SET estado='ocupada' WHERE id=?",
                 (data["unidad_id"],))

    conn.commit()
    conn.close()

    return jsonify({"ok": True})

# ================= FINALIZAR =================
@app.route("/finalizar", methods=["POST"])
def finalizar():
    data = request.json
    conn = get_db()

    conn.execute("DELETE FROM asignaciones WHERE conductor_id=? OR unidad_id=?",
                 (data.get("conductor_id"), data.get("unidad_id")))

    conn.execute("UPDATE conductores SET estado='disponible' WHERE id=?",
                 (data.get("conductor_id"),))

    conn.execute("UPDATE unidades SET estado='disponible' WHERE id=?",
                 (data.get("unidad_id"),))

    conn.commit()
    conn.close()

    return jsonify({"ok": True})

# ================= ⭐ NUEVO: ESTADO UNIDAD =================
@app.route("/cambiar_estado_unidad", methods=["POST"])
def cambiar_estado_unidad():
    data = request.json

    unidad_id = data.get("unidad_id")
    estado = data.get("estado")
    observacion = data.get("observacion", "")

    if not unidad_id or not estado:
        return jsonify({"error": "datos incompletos"}), 400

    conn = get_db()

    # actualizar estado
    conn.execute("""
        UPDATE unidades
        SET estado=?
        WHERE id=?
    """, (estado, unidad_id))

    # registrar movimiento
    conn.execute("""
        INSERT INTO movimientos(accion, usuario, fecha, obs)
        VALUES(?,?,?,?)
    """, (
        f"Unidad {estado}",
        session.get("user", "system"),
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        observacion
    ))

    conn.commit()
    conn.close()

    return jsonify({"ok": True})

# ================= MOVIMIENTOS =================
@app.route("/movimientos")
def movimientos():
    conn = get_db()
    data = conn.execute("SELECT * FROM movimientos ORDER BY id DESC").fetchall()
    conn.close()
    return jsonify([dict(x) for x in data])

# ================= USUARIOS (BASE SIMPLE) =================
@app.route("/usuarios")
def usuarios():
    conn = get_db()
    data = conn.execute("SELECT id, username, rol FROM usuarios").fetchall()
    conn.close()
    return jsonify([dict(x) for x in data])

@app.route("/crear_usuario", methods=["POST"])
def crear_usuario():
    data = request.json
    conn = get_db()
    conn.execute("""
        INSERT INTO usuarios(username, password, rol)
        VALUES(?,?,?)
    """, (data["username"], data["password"], data["rol"]))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})

@app.route("/editar_usuario", methods=["POST"])
def editar_usuario():
    data = request.json
    conn = get_db()
    conn.execute("""
        UPDATE usuarios
        SET username=?, password=?, rol=?
        WHERE id=?
    """, (data["username"], data["password"], data["rol"], data["id"]))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})

@app.route("/eliminar_usuario", methods=["POST"])
def eliminar_usuario():
    data = request.json
    conn = get_db()
    conn.execute("DELETE FROM usuarios WHERE id=?", (data["id"],))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})

# ================= INICIO =================
@app.route("/")
def index():
    return render_template("index.html")

# ================= RUN =================
if __name__ == "__main__":
    app.run(debug=True)