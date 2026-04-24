from flask import Flask, request, jsonify, session, redirect, render_template
import psycopg2
import os
from datetime import datetime

app = Flask(__name__)
app.secret_key = "secret123"

# ================= DB =================
def get_db():
    return psycopg2.connect(
        os.environ.get("DATABASE_URL"),
        sslmode="require"
    )

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
    return "BD OK"

# ================= HISTORIAL =================
def registrar_movimiento(accion, obs=""):
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
    INSERT INTO movimientos(accion, usuario, fecha, obs)
    VALUES(%s,%s,%s,%s)
    """, (
        accion,
        session.get("user", {}).get("username", "system"),
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        obs
    ))

    conn.commit()
    conn.close()

# ================= LOGIN =================
@app.route("/login", methods=["GET","POST"])
def login():
    if request.method == "POST":
        u = request.form["username"]
        p = request.form["password"]

        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT * FROM usuarios WHERE username=%s AND password=%s",(u,p))
        user = cur.fetchone()
        conn.close()

        if user:
            session["user"] = {"username":user[1],"rol":user[3]}
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
    return "admin listo"

# ================= INDEX =================
@app.route("/")
def index():
    if "user" not in session:
        return redirect("/login")
    return render_template("index.html", user=session["user"])

# ================= DATOS =================
@app.route("/datos")
def datos():
    if "user" not in session:
        return jsonify({"error":"no auth"})

    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT * FROM conductores")
    conductores = cur.fetchall()

    cur.execute("SELECT * FROM unidades")
    unidades = cur.fetchall()

    cur.execute("""
    SELECT c.nombre,u.placa
    FROM asignaciones a
    JOIN conductores c ON c.id=a.conductor_id
    JOIN unidades u ON u.id=a.unidad_id
    """)
    asignaciones = cur.fetchall()

    stats = {}
    cur.execute("SELECT COUNT(*) FROM conductores WHERE estado='disponible'")
    stats["conductores_disponibles"]=cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM conductores WHERE estado='en_ruta'")
    stats["conductores_ocupados"]=cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM unidades WHERE estado='disponible'")
    stats["unidades_disponibles"]=cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM unidades WHERE estado='ocupada'")
    stats["unidades_ocupadas"]=cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM unidades WHERE estado='inhabilitado'")
    stats["unidades_inhabilitadas"]=cur.fetchone()[0]

    conn.close()

    return jsonify({
        "conductores":[{"id":x[0],"nombre":x[1],"estado":x[2]} for x in conductores],
        "unidades":[{"id":x[0],"placa":x[1],"estado":x[2]} for x in unidades],
        "asignaciones":[{"conductor":x[0],"unidad":x[1]} for x in asignaciones],
        "stats":stats
    })

# ================= CRUD =================
@app.route("/crear_conductor",methods=["POST"])
def crear_conductor():
    d=request.json
    conn=get_db();cur=conn.cursor()
    cur.execute("INSERT INTO conductores(nombre,estado) VALUES(%s,'disponible')",(d["nombre"],))
    conn.commit();conn.close()
    registrar_movimiento(f"Creó conductor: {d['nombre']}")
    return jsonify({"ok":True})

@app.route("/crear_unidad",methods=["POST"])
def crear_unidad():
    d=request.json
    conn=get_db();cur=conn.cursor()
    cur.execute("INSERT INTO unidades(placa,estado) VALUES(%s,'disponible')",(d["placa"],))
    conn.commit();conn.close()
    registrar_movimiento(f"Creó unidad: {d['placa']}")
    return jsonify({"ok":True})

@app.route("/editar_conductor",methods=["POST"])
def editar_conductor():
    d=request.json
    conn=get_db();cur=conn.cursor()
    cur.execute("UPDATE conductores SET nombre=%s WHERE id=%s",(d["nombre"],d["id"]))
    conn.commit();conn.close()
    registrar_movimiento(f"Editó conductor ID {d['id']} → {d['nombre']}")
    return jsonify({"ok":True})

@app.route("/eliminar_conductor",methods=["POST"])
def eliminar_conductor():
    d=request.json
    conn=get_db();cur=conn.cursor()
    cur.execute("DELETE FROM conductores WHERE id=%s",(d["id"],))
    conn.commit();conn.close()
    registrar_movimiento(f"Eliminó conductor ID {d['id']}")
    return jsonify({"ok":True})

@app.route("/editar_unidad",methods=["POST"])
def editar_unidad():
    d=request.json
    conn=get_db();cur=conn.cursor()
    cur.execute("UPDATE unidades SET placa=%s WHERE id=%s",(d["placa"],d["id"]))
    conn.commit();conn.close()
    registrar_movimiento(f"Editó unidad ID {d['id']} → {d['placa']}")
    return jsonify({"ok":True})

@app.route("/eliminar_unidad",methods=["POST"])
def eliminar_unidad():
    d=request.json
    conn=get_db();cur=conn.cursor()
    cur.execute("DELETE FROM unidades WHERE id=%s",(d["id"],))
    conn.commit();conn.close()
    registrar_movimiento(f"Eliminó unidad ID {d['id']}")
    return jsonify({"ok":True})

# ================= OPERACIONES =================
@app.route("/asignar",methods=["POST"])
def asignar():
    d=request.json
    conn=get_db();cur=conn.cursor()

    cur.execute("INSERT INTO asignaciones(conductor_id,unidad_id) VALUES(%s,%s)",
                (d["conductor_id"],d["unidad_id"]))

    cur.execute("UPDATE conductores SET estado='en_ruta' WHERE id=%s",(d["conductor_id"],))
    cur.execute("UPDATE unidades SET estado='ocupada' WHERE id=%s",(d["unidad_id"],))

    conn.commit();conn.close()
    registrar_movimiento(f"Asignó conductor {d['conductor_id']} a unidad {d['unidad_id']}")
    return jsonify({"ok":True})

@app.route("/finalizar",methods=["POST"])
def finalizar():
    d=request.json
    conn=get_db();cur=conn.cursor()

    cur.execute("DELETE FROM asignaciones WHERE conductor_id=%s OR unidad_id=%s",
                (d["conductor_id"],d["unidad_id"]))

    if d["conductor_id"]:
        cur.execute("UPDATE conductores SET estado='disponible' WHERE id=%s",(d["conductor_id"],))
    if d["unidad_id"]:
        cur.execute("UPDATE unidades SET estado='disponible' WHERE id=%s",(d["unidad_id"],))

    conn.commit();conn.close()
    registrar_movimiento(f"Finalizó asignación C:{d['conductor_id']} U:{d['unidad_id']}")
    return jsonify({"ok":True})

# ================= INHABILITAR =================
@app.route("/cambiar_estado_unidad", methods=["POST"])
def cambiar_estado_unidad():
    d = request.json

    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        "UPDATE unidades SET estado=%s WHERE id=%s",
        (d["estado"], d["unidad_id"])
    )

    conn.commit()
    conn.close()

    estado = "INHABILITADA" if d["estado"]=="inhabilitado" else "HABILITADA"

    registrar_movimiento(
        f"Unidad {d['unidad_id']} fue {estado}",
        d.get("observacion","")
    )

    return jsonify({"ok":True})

# ================= HISTORIAL =================
@app.route("/movimientos")
def movimientos():
    conn=get_db();cur=conn.cursor()
    cur.execute("SELECT * FROM movimientos ORDER BY id DESC")
    data=cur.fetchall()
    conn.close()

    return jsonify([
        {"accion":x[1],"usuario":x[2],"fecha":x[3],"obs":x[4]}
        for x in data
    ])

# ================= USUARIOS =================
@app.route("/usuarios")
def usuarios():
    conn=get_db();cur=conn.cursor()
    cur.execute("SELECT id,username,rol FROM usuarios")
    data=cur.fetchall()
    conn.close()

    return jsonify([{"id":x[0],"username":x[1],"rol":x[2]} for x in data])

@app.route("/crear_usuario",methods=["POST"])
def crear_usuario():
    d=request.json
    conn=get_db();cur=conn.cursor()
    cur.execute("INSERT INTO usuarios(username,password,rol) VALUES(%s,%s,%s)",
                (d["username"],d["password"],d["rol"]))
    conn.commit();conn.close()
    registrar_movimiento(f"Creó usuario: {d['username']}")
    return jsonify({"ok":True})

@app.route("/editar_usuario",methods=["POST"])
def editar_usuario():
    d=request.json
    conn=get_db();cur=conn.cursor()
    cur.execute("UPDATE usuarios SET username=%s,password=%s,rol=%s WHERE id=%s",
                (d["username"],d["password"],d["rol"],d["id"]))
    conn.commit();conn.close()
    registrar_movimiento(f"Editó usuario: {d['username']}")
    return jsonify({"ok":True})

@app.route("/eliminar_usuario",methods=["POST"])
def eliminar_usuario():
    d=request.json
    conn=get_db();cur=conn.cursor()
    cur.execute("DELETE FROM usuarios WHERE id=%s",(d["id"],))
    conn.commit();conn.close()
    registrar_movimiento(f"Eliminó usuario ID {d['id']}")
    return jsonify({"ok":True})