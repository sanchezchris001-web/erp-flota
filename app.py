from flask import Flask, request, jsonify, session, redirect, render_template, send_file
import psycopg2, os, io
from datetime import datetime
from openpyxl import Workbook

app = Flask(__name__)
app.secret_key = "secret123"

# ================= DB =================
def get_db():
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise Exception("DATABASE_URL no configurada")
    return psycopg2.connect(url, sslmode="require")

# ================= INIT =================
def init_db():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("CREATE TABLE IF NOT EXISTS conductores(id SERIAL PRIMARY KEY,nombre TEXT,estado TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS unidades(id SERIAL PRIMARY KEY,placa TEXT,estado TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS asignaciones(id SERIAL PRIMARY KEY,conductor_id INT,unidad_id INT)")
    cur.execute("CREATE TABLE IF NOT EXISTS movimientos(id SERIAL PRIMARY KEY,accion TEXT,usuario TEXT,fecha TEXT,obs TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS usuarios(id SERIAL PRIMARY KEY,username TEXT UNIQUE,password TEXT,rol TEXT)")

    conn.commit()
    conn.close()

@app.route("/init")
def init():
    init_db()
    return "BD lista"

# ================= HISTORIAL =================
def registrar_movimiento(accion, obs=""):
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO movimientos(accion,usuario,fecha,obs) VALUES(%s,%s,%s,%s)",
            (
                accion,
                session.get("user", {}).get("username", "system"),
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                obs,
            ),
        )
        conn.commit()
        conn.close()
    except:
        pass

# ================= LOGIN =================
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        u = request.form["username"]
        p = request.form["password"]

        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT * FROM usuarios WHERE username=%s AND password=%s", (u, p))
        user = cur.fetchone()
        conn.close()

        if user:
            session["user"] = {"username": user[1], "rol": user[3]}
            return redirect("/")
        return render_template("login.html", error="Credenciales incorrectas")

    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")

@app.route("/crear_admin")
def crear_admin():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("INSERT INTO usuarios(username,password,rol) VALUES('admin','123','admin') ON CONFLICT DO NOTHING")
    conn.commit()
    conn.close()
    return "admin creado"

# ================= INDEX =================
@app.route("/")
def index():
    if "user" not in session:
        return redirect("/login")
    return render_template("index.html", user=session["user"])

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
    SELECT c.nombre,u.placa FROM asignaciones a
    JOIN conductores c ON c.id=a.conductor_id
    JOIN unidades u ON u.id=a.unidad_id
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

# ================= CRUD =================
@app.route("/crear_conductor", methods=["POST"])
def crear_conductor():
    try:
        d = request.json
        conn = get_db()
        cur = conn.cursor()
        cur.execute("INSERT INTO conductores(nombre,estado) VALUES(%s,'disponible')", (d["nombre"],))
        conn.commit()
        conn.close()
        registrar_movimiento(f"Creó conductor {d['nombre']}")
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/crear_unidad", methods=["POST"])
def crear_unidad():
    try:
        d = request.json
        conn = get_db()
        cur = conn.cursor()
        cur.execute("INSERT INTO unidades(placa,estado) VALUES(%s,'disponible')", (d["placa"],))
        conn.commit()
        conn.close()
        registrar_movimiento(f"Creó unidad {d['placa']}")
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ================= ASIGNAR =================
@app.route("/asignar", methods=["POST"])
def asignar():
    try:
        d = request.json
        conn = get_db()
        cur = conn.cursor()

        cur.execute("SELECT estado,placa FROM unidades WHERE id=%s",(d["unidad_id"],))
        unidad = cur.fetchone()

        if not unidad:
            return jsonify({"error":"Unidad no existe"}),400

        estado,placa = unidad

        if estado == "inhabilitado":
            return jsonify({"error":f"Unidad {placa} inhabilitada"}),400

        cur.execute("SELECT nombre FROM conductores WHERE id=%s",(d["conductor_id"],))
        c = cur.fetchone()
        if not c:
            return jsonify({"error":"Conductor no existe"}),400

        conductor = c[0]

        cur.execute("INSERT INTO asignaciones(conductor_id,unidad_id) VALUES(%s,%s)",
                    (d["conductor_id"],d["unidad_id"]))

        cur.execute("UPDATE conductores SET estado='en_ruta' WHERE id=%s",(d["conductor_id"],))
        cur.execute("UPDATE unidades SET estado='ocupada' WHERE id=%s",(d["unidad_id"],))

        conn.commit()
        conn.close()

        registrar_movimiento(f"Asignó {conductor} → {placa}")

        return jsonify({"ok":True})

    except Exception as e:
        return jsonify({"error":str(e)}),500

# ================= FINALIZAR =================
@app.route("/finalizar", methods=["POST"])
def finalizar():
    try:
        d = request.json
        conn = get_db()
        cur = conn.cursor()

        cur.execute("DELETE FROM asignaciones WHERE conductor_id=%s OR unidad_id=%s",
                    (d["conductor_id"], d["unidad_id"]))

        if d["conductor_id"]:
            cur.execute("UPDATE conductores SET estado='disponible' WHERE id=%s",(d["conductor_id"],))
        if d["unidad_id"]:
            cur.execute("UPDATE unidades SET estado='disponible' WHERE id=%s",(d["unidad_id"],))

        conn.commit()
        conn.close()

        registrar_movimiento("Finalizó asignación")

        return jsonify({"ok":True})

    except Exception as e:
        return jsonify({"error":str(e)}),500

# ================= INHABILITAR =================
@app.route("/cambiar_estado_unidad", methods=["POST"])
def cambiar_estado_unidad():
    try:
        if session.get("user", {}).get("rol") not in ["admin","supervisor"]:
            return jsonify({"error":"No autorizado"}),403

        d = request.json
        conn = get_db()
        cur = conn.cursor()

        cur.execute("SELECT placa FROM unidades WHERE id=%s",(d["unidad_id"],))
        u = cur.fetchone()
        if not u:
            return jsonify({"error":"Unidad no existe"}),400

        placa = u[0]

        cur.execute("UPDATE unidades SET estado=%s WHERE id=%s",
                    (d["estado"], d["unidad_id"]))

        conn.commit()
        conn.close()

        estado = "INHABILITADA" if d["estado"]=="inhabilitado" else "HABILITADA"

        registrar_movimiento(f"Unidad {placa} fue {estado}", d.get("observacion",""))

        return jsonify({"ok":True})

    except Exception as e:
        return jsonify({"error":str(e)}),500

# ================= HISTORIAL =================
@app.route("/movimientos")
def movimientos():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM movimientos ORDER BY id DESC")
    data = cur.fetchall()
    conn.close()

    return jsonify([{
        "accion": x[1],
        "usuario": x[2],
        "fecha": x[3],
        "obs": x[4]
    } for x in data])

# ================= USUARIOS =================
@app.route("/usuarios")
def usuarios():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id,username,rol FROM usuarios")
    data = cur.fetchall()
    conn.close()

    return jsonify([{"id":x[0],"username":x[1],"rol":x[2]} for x in data])

@app.route("/crear_usuario", methods=["POST"])
def crear_usuario():
    try:
        d = request.json
        conn = get_db()
        cur = conn.cursor()

        cur.execute("SELECT id FROM usuarios WHERE username=%s",(d["username"],))
        if cur.fetchone():
            return jsonify({"error":"Usuario ya existe"}),400

        cur.execute("INSERT INTO usuarios(username,password,rol) VALUES(%s,%s,%s)",
                    (d["username"],d["password"],d["rol"]))

        conn.commit()
        conn.close()

        return jsonify({"ok":True})

    except Exception as e:
        return jsonify({"error":str(e)}),500

@app.route("/editar_usuario", methods=["POST"])
def editar_usuario():
    try:
        d = request.json
        conn = get_db()
        cur = conn.cursor()

        cur.execute("UPDATE usuarios SET username=%s,password=%s,rol=%s WHERE id=%s",
                    (d["username"],d["password"],d["rol"],d["id"]))

        conn.commit()
        conn.close()

        return jsonify({"ok":True})

    except Exception as e:
        return jsonify({"error":str(e)}),500

@app.route("/eliminar_usuario", methods=["POST"])
def eliminar_usuario():
    try:
        d = request.json
        conn = get_db()
        cur = conn.cursor()

        cur.execute("DELETE FROM usuarios WHERE id=%s",(d["id"],))

        conn.commit()
        conn.close()

        return jsonify({"ok":True})

    except Exception as e:
        return jsonify({"error":str(e)}),500

# ================= EXPORTAR =================
@app.route("/exportar_excel")
def exportar_excel():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT accion,usuario,fecha,obs FROM movimientos")
    data = cur.fetchall()
    conn.close()

    wb = Workbook()
    ws = wb.active
    ws.append(["Acción","Usuario","Fecha","Observación"])

    for row in data:
        ws.append(row)

    file = io.BytesIO()
    wb.save(file)
    file.seek(0)

    return send_file(file, as_attachment=True, download_name="historial.xlsx")