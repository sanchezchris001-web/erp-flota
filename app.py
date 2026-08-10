```python
from flask import (
    Flask,
    request,
    jsonify,
    session,
    redirect,
    render_template,
    send_file
)

import psycopg2
import os
import io

from datetime import datetime
from functools import wraps

from openpyxl import Workbook
from werkzeug.security import generate_password_hash, check_password_hash


# ============================================================
# CONFIGURACIÓN FLASK
# ============================================================

app = Flask(__name__)

app.secret_key = os.environ.get(
    "SECRET_KEY",
    "CAMBIA_ESTA_CLAVE_EN_RENDER"
)


# ============================================================
# BASE DE DATOS
# ============================================================

def get_db():
    """
    Conecta con PostgreSQL utilizando DATABASE_URL.
    Render debe tener configurada esta variable.
    """

    url = os.environ.get("DATABASE_URL")

    if not url:
        raise Exception(
            "DATABASE_URL no configurada en las variables de entorno."
        )

    return psycopg2.connect(
        url,
        sslmode="require"
    )


def init_db():
    """
    Crea las tablas si no existen.
    """

    conn = get_db()
    cur = conn.cursor()

    try:

        # ----------------------------------------------------
        # CONDUCTORES
        # ----------------------------------------------------

        cur.execute("""
            CREATE TABLE IF NOT EXISTS conductores(
                id SERIAL PRIMARY KEY,
                nombre TEXT NOT NULL,
                estado TEXT NOT NULL DEFAULT 'disponible'
            )
        """)

        # ----------------------------------------------------
        # UNIDADES
        # ----------------------------------------------------

        cur.execute("""
            CREATE TABLE IF NOT EXISTS unidades(
                id SERIAL PRIMARY KEY,
                placa TEXT NOT NULL,
                estado TEXT NOT NULL DEFAULT 'disponible'
            )
        """)

        # ----------------------------------------------------
        # ASIGNACIONES
        # ----------------------------------------------------

        cur.execute("""
            CREATE TABLE IF NOT EXISTS asignaciones(
                id SERIAL PRIMARY KEY,
                conductor_id INT NOT NULL,
                unidad_id INT NOT NULL,
                fecha_asignacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # ----------------------------------------------------
        # MOVIMIENTOS
        # ----------------------------------------------------

        cur.execute("""
            CREATE TABLE IF NOT EXISTS movimientos(
                id SERIAL PRIMARY KEY,
                accion TEXT,
                usuario TEXT,
                fecha TEXT,
                obs TEXT
            )
        """)

        # ----------------------------------------------------
        # USUARIOS
        # ----------------------------------------------------

        cur.execute("""
            CREATE TABLE IF NOT EXISTS usuarios(
                id SERIAL PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                rol TEXT NOT NULL
            )
        """)

        # ----------------------------------------------------
        # SOLICITUDES DE ASIGNACIÓN
        # ----------------------------------------------------

        cur.execute("""
            CREATE TABLE IF NOT EXISTS solicitudes_asignacion(
                id SERIAL PRIMARY KEY,
                conductor_id INT NOT NULL,
                unidad_id INT NOT NULL,
                usuario_id INT,
                estado TEXT NOT NULL DEFAULT 'pendiente',
                observacion TEXT,
                fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                atendido_por TEXT,
                fecha_atencion TIMESTAMP
            )
        """)

        # ----------------------------------------------------
        # COMPATIBILIDAD CON BASES ANTIGUAS
        # ----------------------------------------------------

        cur.execute("""
            ALTER TABLE solicitudes_asignacion
            ADD COLUMN IF NOT EXISTS usuario_id INT
        """)

        cur.execute("""
            ALTER TABLE solicitudes_asignacion
            ADD COLUMN IF NOT EXISTS estado TEXT DEFAULT 'pendiente'
        """)

        cur.execute("""
            ALTER TABLE solicitudes_asignacion
            ADD COLUMN IF NOT EXISTS observacion TEXT
        """)

        cur.execute("""
            ALTER TABLE solicitudes_asignacion
            ADD COLUMN IF NOT EXISTS fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        """)

        cur.execute("""
            ALTER TABLE solicitudes_asignacion
            ADD COLUMN IF NOT EXISTS atendido_por TEXT
        """)

        cur.execute("""
            ALTER TABLE solicitudes_asignacion
            ADD COLUMN IF NOT EXISTS fecha_atencion TIMESTAMP
        """)

        # ----------------------------------------------------
        # ASEGURAR VALORES DE ROL VÁLIDOS
        # ----------------------------------------------------

        cur.execute("""
            UPDATE usuarios
            SET rol='operador'
            WHERE rol='user'
        """)

        conn.commit()

    except Exception:
        conn.rollback()
        raise

    finally:
        cur.close()
        conn.close()


# ============================================================
# AUTENTICACIÓN
# ============================================================

def usuario_actual():
    return session.get("user")


def esta_logueado():
    return "user" in session


def tiene_rol(*roles):
    user = usuario_actual()

    if not user:
        return False

    return user.get("rol") in roles


def requiere_rol(*roles):

    def decorator(func):

        @wraps(func)
        def wrapper(*args, **kwargs):

            if not esta_logueado():

                return jsonify({
                    "error": "No autenticado"
                }), 401

            if not tiene_rol(*roles):

                return jsonify({
                    "error": "No autorizado"
                }), 403

            return func(*args, **kwargs)

        return wrapper

    return decorator


# ============================================================
# HISTORIAL
# ============================================================

def registrar_movimiento(accion, obs=""):

    conn = None
    cur = None

    try:

        conn = get_db()
        cur = conn.cursor()

        usuario = session.get(
            "user",
            {}
        ).get(
            "username",
            "system"
        )

        cur.execute("""
            INSERT INTO movimientos(
                accion,
                usuario,
                fecha,
                obs
            )
            VALUES(%s,%s,%s,%s)
        """, (
            accion,
            usuario,
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            obs
        ))

        conn.commit()

    except Exception:
        # El historial nunca debe romper
        # una operación principal.
        pass

    finally:

        if cur:
            cur.close()

        if conn:
            conn.close()


# ============================================================
# INICIALIZAR BASE DE DATOS
# ============================================================

@app.route("/init")
def init():

    try:

        init_db()

        return "Base de datos lista."

    except Exception as e:

        return f"Error inicializando BD: {e}", 500


# ============================================================
# LOGIN
# ============================================================

@app.route("/login", methods=["GET", "POST"])
def login():

    if request.method == "POST":

        username = request.form.get(
            "username",
            ""
        ).strip()

        password = request.form.get(
            "password",
            ""
        )

        if not username or not password:

            return render_template(
                "login.html",
                error="Complete usuario y contraseña."
            )

        conn = None
        cur = None

        try:

            conn = get_db()
            cur = conn.cursor()

            cur.execute("""
                SELECT
                    id,
                    username,
                    password,
                    rol
                FROM usuarios
                WHERE username=%s
            """, (username,))

            user = cur.fetchone()

        except Exception as e:

            return render_template(
                "login.html",
                error=f"Error de conexión con la base de datos: {e}"
            )

        finally:

            if cur:
                cur.close()

            if conn:
                conn.close()

        if user:

            password_correcta = False

            try:

                password_correcta = check_password_hash(
                    user[2],
                    password
                )

            except Exception:

                password_correcta = False

            if password_correcta:

                if user[3] not in [
                    "admin",
                    "supervisor",
                    "operador"
                ]:

                    return render_template(
                        "login.html",
                        error="El usuario tiene un rol inválido."
                    )

                session.clear()

                session["user"] = {
                    "id": user[0],
                    "username": user[1],
                    "rol": user[3]
                }

                return redirect("/")

        return render_template(
            "login.html",
            error="Usuario o contraseña incorrectos."
        )

    return render_template("login.html")


# ============================================================
# LOGOUT
# ============================================================

@app.route("/logout")
def logout():

    session.clear()

    return redirect("/login")


# ============================================================
# CREAR ADMINISTRADOR INICIAL
# ============================================================

@app.route("/crear_admin", methods=["GET"])
def crear_admin():

    conn = None
    cur = None

    try:

        conn = get_db()
        cur = conn.cursor()

        # Verificar si ya existe algún usuario
        cur.execute("""
            SELECT COUNT(*)
            FROM usuarios
        """)

        cantidad = cur.fetchone()[0]

        if cantidad > 0:

            return (
                "Ya existen usuarios en la base de datos. "
                "No se puede crear el administrador inicial "
                "desde esta ruta."
            ), 400

        username = os.environ.get(
            "ADMIN_USERNAME",
            "admin"
        ).strip()

        password = os.environ.get(
            "ADMIN_PASSWORD"
        )

        if not username:

            return (
                "ADMIN_USERNAME no está configurado correctamente."
            ), 500

        if not password:

            return (
                "ADMIN_PASSWORD no está configurada en Render."
            ), 500

        password_hash = generate_password_hash(
            password
        )

        cur.execute("""
            INSERT INTO usuarios(
                username,
                password,
                rol
            )
            VALUES(%s,%s,'admin')
        """, (
            username,
            password_hash
        ))

        conn.commit()

        return (
            "Administrador creado correctamente. "
            "Ya puedes iniciar sesión."
        )

    except Exception as e:

        if conn:
            conn.rollback()

        return f"Error creando administrador: {e}", 500

    finally:

        if cur:
            cur.close()

        if conn:
            conn.close()


# ============================================================
# INDEX
# ============================================================

@app.route("/")
def index():

    if not esta_logueado():

        return redirect("/login")

    return render_template(
        "index.html",
        user=session["user"]
    )


# ============================================================
# DATOS DEL DASHBOARD
#
# ADMIN / SUPERVISOR / OPERADOR
# ============================================================

@app.route("/datos")
@requiere_rol(
    "admin",
    "supervisor",
    "operador"
)
def datos():

    conn = None
    cur = None

    try:

        conn = get_db()
        cur = conn.cursor()

        # ----------------------------------------------------
        # CONDUCTORES
        # ----------------------------------------------------

        cur.execute("""
            SELECT
                id,
                nombre,
                estado
            FROM conductores
            ORDER BY nombre
        """)

        conductores = cur.fetchall()

        # ----------------------------------------------------
        # UNIDADES
        # ----------------------------------------------------

        cur.execute("""
            SELECT
                id,
                placa,
                estado
            FROM unidades
            ORDER BY placa
        """)

        unidades = cur.fetchall()

        # ----------------------------------------------------
        # ASIGNACIONES
        #
        # Solo se entregan a admin/supervisor.
        # El operador no necesita esta información.
        # ----------------------------------------------------

        asignaciones = []

        if tiene_rol("admin", "supervisor"):

            cur.execute("""
                SELECT
                    a.id,
                    c.id,
                    c.nombre,
                    u.id,
                    u.placa
                FROM asignaciones a
                JOIN conductores c
                    ON c.id=a.conductor_id
                JOIN unidades u
                    ON u.id=a.unidad_id
                ORDER BY a.id DESC
            """)

            asignaciones = cur.fetchall()

        # ----------------------------------------------------
        # ESTADÍSTICAS
        # ----------------------------------------------------

        cur.execute("""
            SELECT COUNT(*)
            FROM conductores
            WHERE estado='disponible'
        """)

        conductores_disponibles = cur.fetchone()[0]

        cur.execute("""
            SELECT COUNT(*)
            FROM conductores
            WHERE estado='en_ruta'
        """)

        conductores_ocupados = cur.fetchone()[0]

        cur.execute("""
            SELECT COUNT(*)
            FROM unidades
            WHERE estado='disponible'
        """)

        unidades_disponibles = cur.fetchone()[0]

        cur.execute("""
            SELECT COUNT(*)
            FROM unidades
            WHERE estado='ocupada'
        """)

        unidades_ocupadas = cur.fetchone()[0]

        cur.execute("""
            SELECT COUNT(*)
            FROM unidades
            WHERE estado='inhabilitado'
        """)

        unidades_inhabilitadas = cur.fetchone()[0]

        return jsonify({

            "conductores": [
                {
                    "id": x[0],
                    "nombre": x[1],
                    "estado": x[2]
                }
                for x in conductores
            ],

            "unidades": [
                {
                    "id": x[0],
                    "placa": x[1],
                    "estado": x[2]
                }
                for x in unidades
            ],

            "asignaciones": [
                {
                    "id": x[0],
                    "conductor_id": x[1],
                    "conductor": x[2],
                    "unidad_id": x[3],
                    "unidad": x[4]
                }
                for x in asignaciones
            ],

            "stats": {
                "conductores_disponibles":
                    conductores_disponibles,

                "conductores_ocupados":
                    conductores_ocupados,

                "unidades_disponibles":
                    unidades_disponibles,

                "unidades_ocupadas":
                    unidades_ocupadas,

                "unidades_inhabilitadas":
                    unidades_inhabilitadas
            }

        })

    except Exception as e:

        return jsonify({
            "error": str(e)
        }), 500

    finally:

        if cur:
            cur.close()

        if conn:
            conn.close()


# ============================================================
# CREAR CONDUCTOR
#
# ADMIN / SUPERVISOR
# ============================================================

@app.route("/crear_conductor", methods=["POST"])
@requiere_rol("admin", "supervisor")
def crear_conductor():

    conn = None
    cur = None

    try:

        data = request.get_json(silent=True) or {}

        nombre = data.get(
            "nombre",
            ""
        ).strip()

        if not nombre:

            return jsonify({
                "error": "Debe ingresar el nombre."
            }), 400

        conn = get_db()
        cur = conn.cursor()

        cur.execute("""
            INSERT INTO conductores(
                nombre,
                estado
            )
            VALUES(%s,'disponible')
        """, (nombre,))

        conn.commit()

        registrar_movimiento(
            f"Creó conductor {nombre}"
        )

        return jsonify({
            "ok": True
        })

    except Exception as e:

        if conn:
            conn.rollback()

        return jsonify({
            "error": str(e)
        }), 500

    finally:

        if cur:
            cur.close()

        if conn:
            conn.close()


# ============================================================
# EDITAR CONDUCTOR
#
# ADMIN / SUPERVISOR
# ============================================================

@app.route("/editar_conductor", methods=["POST"])
@requiere_rol("admin", "supervisor")
def editar_conductor():

    conn = None
    cur = None

    try:

        data = request.get_json(silent=True) or {}

        conductor_id = data.get("id")
        nombre = data.get(
            "nombre",
            ""
        ).strip()

        if not conductor_id or not nombre:

            return jsonify({
                "error": "Datos incompletos."
            }), 400

        conn = get_db()
        cur = conn.cursor()

        cur.execute("""
            SELECT nombre
            FROM conductores
            WHERE id=%s
        """, (conductor_id,))

        anterior = cur.fetchone()

        if not anterior:

            return jsonify({
                "error": "Conductor no existe."
            }), 404

        cur.execute("""
            UPDATE conductores
            SET nombre=%s
            WHERE id=%s
        """, (
            nombre,
            conductor_id
        ))

        conn.commit()

        registrar_movimiento(
            f"Editó conductor {anterior[0]} → {nombre}"
        )

        return jsonify({
            "ok": True
        })

    except Exception as e:

        if conn:
            conn.rollback()

        return jsonify({
            "error": str(e)
        }), 500

    finally:

        if cur:
            cur.close()

        if conn:
            conn.close()


# ============================================================
# ELIMINAR CONDUCTOR
#
# ADMIN / SUPERVISOR
# ============================================================

@app.route("/eliminar_conductor", methods=["POST"])
@requiere_rol("admin", "supervisor")
def eliminar_conductor():

    conn = None
    cur = None

    try:

        data = request.get_json(silent=True) or {}

        conductor_id = data.get("id")

        if not conductor_id:

            return jsonify({
                "error": "Conductor no especificado."
            }), 400

        conn = get_db()
        cur = conn.cursor()

        cur.execute("""
            SELECT
                nombre,
                estado
            FROM conductores
            WHERE id=%s
        """, (conductor_id,))

        conductor = cur.fetchone()

        if not conductor:

            return jsonify({
                "error": "Conductor no existe."
            }), 404

        if conductor[1] == "en_ruta":

            return jsonify({
                "error": "No se puede eliminar un conductor en ruta."
            }), 400

        cur.execute("""
            SELECT COUNT(*)
            FROM asignaciones
            WHERE conductor_id=%s
        """, (conductor_id,))

        tiene_asignaciones = cur.fetchone()[0]

        if tiene_asignaciones > 0:

            return jsonify({
                "error":
                    "El conductor tiene registros de asignación. "
                    "No se puede eliminar."
            }), 400

        cur.execute("""
            DELETE FROM conductores
            WHERE id=%s
        """, (conductor_id,))

        conn.commit()

        registrar_movimiento(
            f"Eliminó conductor {conductor[0]}"
        )

        return jsonify({
            "ok": True
        })

    except Exception as e:

        if conn:
            conn.rollback()

        return jsonify({
            "error": str(e)
        }), 500

    finally:

        if cur:
            cur.close()

        if conn:
            conn.close()


# ============================================================
# CREAR UNIDAD
#
# ADMIN / SUPERVISOR
# ============================================================

@app.route("/crear_unidad", methods=["POST"])
@requiere_rol("admin", "supervisor")
def crear_unidad():

    conn = None
    cur = None

    try:

        data = request.get_json(silent=True) or {}

        placa = data.get(
            "placa",
            ""
        ).strip().upper()

        if not placa:

            return jsonify({
                "error": "Debe ingresar la placa."
            }), 400

        conn = get_db()
        cur = conn.cursor()

        cur.execute("""
            SELECT id
            FROM unidades
            WHERE UPPER(placa)=UPPER(%s)
        """, (placa,))

        if cur.fetchone():

            return jsonify({
                "error": "La unidad ya existe."
            }), 400

        cur.execute("""
            INSERT INTO unidades(
                placa,
                estado
            )
            VALUES(%s,'disponible')
        """, (placa,))

        conn.commit()

        registrar_movimiento(
            f"Creó unidad {placa}"
        )

        return jsonify({
            "ok": True
        })

    except Exception as e:

        if conn:
            conn.rollback()

        return jsonify({
            "error": str(e)
        }), 500

    finally:

        if cur:
            cur.close()

        if conn:
            conn.close()


# ============================================================
# EDITAR UNIDAD
#
# ADMIN / SUPERVISOR
# ============================================================

@app.route("/editar_unidad", methods=["POST"])
@requiere_rol("admin", "supervisor")
def editar_unidad():

    conn = None
    cur = None

    try:

        data = request.get_json(silent=True) or {}

        unidad_id = data.get("id")

        placa = data.get(
            "placa",
            ""
        ).strip().upper()

        if not unidad_id or not placa:

            return jsonify({
                "error": "Datos incompletos."
            }), 400

        conn = get_db()
        cur = conn.cursor()

        cur.execute("""
            SELECT
                placa,
                estado
            FROM unidades
            WHERE id=%s
        """, (unidad_id,))

        unidad = cur.fetchone()

        if not unidad:

            return jsonify({
                "error": "Unidad no existe."
            }), 404

        cur.execute("""
            SELECT id
            FROM unidades
            WHERE UPPER(placa)=UPPER(%s)
            AND id<>%s
        """, (
            placa,
            unidad_id
        ))

        if cur.fetchone():

            return jsonify({
                "error": "La placa ya está registrada."
            }), 400

        cur.execute("""
            UPDATE unidades
            SET placa=%s
            WHERE id=%s
        """, (
            placa,
            unidad_id
        ))

        conn.commit()

        registrar_movimiento(
            f"Editó unidad {unidad[0]} → {placa}"
        )

        return jsonify({
            "ok": True
        })

    except Exception as e:

        if conn:
            conn.rollback()

        return jsonify({
            "error": str(e)
        }), 500

    finally:

        if cur:
            cur.close()

        if conn:
            conn.close()


# ============================================================
# ELIMINAR UNIDAD
#
# ADMIN / SUPERVISOR
# ============================================================

@app.route("/eliminar_unidad", methods=["POST"])
@requiere_rol("admin", "supervisor")
def eliminar_unidad():

    conn = None
    cur = None

    try:

        data = request.get_json(silent=True) or {}

        unidad_id = data.get("id")

        if not unidad_id:

            return jsonify({
                "error": "Unidad no especificada."
            }), 400

        conn = get_db()
        cur = conn.cursor()

        cur.execute("""
            SELECT
                placa,
                estado
            FROM unidades
            WHERE id=%s
        """, (unidad_id,))

        unidad = cur.fetchone()

        if not unidad:

            return jsonify({
                "error": "Unidad no existe."
            }), 404

        if unidad[1] == "ocupada":

            return jsonify({
                "error": "No se puede eliminar una unidad ocupada."
            }), 400

        cur.execute("""
            SELECT COUNT(*)
            FROM asignaciones
            WHERE unidad_id=%s
        """, (unidad_id,))

        tiene_asignaciones = cur.fetchone()[0]

        if tiene_asignaciones > 0:

            return jsonify({
                "error":
                    "La unidad tiene registros de asignación. "
                    "No se puede eliminar."
            }), 400

        cur.execute("""
            DELETE FROM unidades
            WHERE id=%s
        """, (unidad_id,))

        conn.commit()

        registrar_movimiento(
            f"Eliminó unidad {unidad[0]}"
        )

        return jsonify({
            "ok": True
        })

    except Exception as e:

        if conn:
            conn.rollback()

        return jsonify({
            "error": str(e)
        }), 500

    finally:

        if cur:
            cur.close()

        if conn:
            conn.close()


# ============================================================
# ASIGNAR DIRECTAMENTE
#
# ADMIN / SUPERVISOR
# ============================================================

@app.route("/asignar", methods=["POST"])
@requiere_rol("admin", "supervisor")
def asignar():

    conn = None
    cur = None

    try:

        data = request.get_json(silent=True) or {}

        conductor_id = data.get("conductor_id")
        unidad_id = data.get("unidad_id")

        if not conductor_id or not unidad_id:

            return jsonify({
                "error":
                    "Debe seleccionar conductor y unidad."
            }), 400

        conn = get_db()
        cur = conn.cursor()

        # ----------------------------------------------------
        # BLOQUEAR CONDUCTOR
        # ----------------------------------------------------

        cur.execute("""
            SELECT
                id,
                nombre,
                estado
            FROM conductores
            WHERE id=%s
            FOR UPDATE
        """, (conductor_id,))

        conductor = cur.fetchone()

        if not conductor:

            return jsonify({
                "error": "Conductor no existe."
            }), 404

        # ----------------------------------------------------
        # BLOQUEAR UNIDAD
        # ----------------------------------------------------

        cur.execute("""
            SELECT
                id,
                placa,
                estado
            FROM unidades
            WHERE id=%s
            FOR UPDATE
        """, (unidad_id,))

        unidad = cur.fetchone()

        if not unidad:

            return jsonify({
                "error": "Unidad no existe."
            }), 404

        if conductor[2] != "disponible":

            return jsonify({
                "error":
                    "El conductor no está disponible."
            }), 400

        if unidad[2] != "disponible":

            return jsonify({
                "error":
                    "La unidad no está disponible."
            }), 400

        # ----------------------------------------------------
        # CREAR ASIGNACIÓN
        # ----------------------------------------------------

        cur.execute("""
            INSERT INTO asignaciones(
                conductor_id,
                unidad_id
            )
            VALUES(%s,%s)
        """, (
            conductor_id,
            unidad_id
        ))

        # ----------------------------------------------------
        # CAMBIAR ESTADOS
        # ----------------------------------------------------

        cur.execute("""
            UPDATE conductores
            SET estado='en_ruta'
            WHERE id=%s
        """, (conductor_id,))

        cur.execute("""
            UPDATE unidades
            SET estado='ocupada'
            WHERE id=%s
        """, (unidad_id,))

        conn.commit()

        registrar_movimiento(
            f"Asignó {conductor[1]} → {unidad[1]}"
        )

        return jsonify({
            "ok": True,
            "mensaje": "Asignación creada correctamente."
        })

    except Exception as e:

        if conn:
            conn.rollback()

        return jsonify({
            "error": str(e)
        }), 500

    finally:

        if cur:
            cur.close()

        if conn:
            conn.close()


# ============================================================
# FINALIZAR ASIGNACIÓN
#
# ADMIN / SUPERVISOR
# ============================================================

@app.route("/finalizar", methods=["POST"])
@requiere_rol("admin", "supervisor")
def finalizar():

    conn = None
    cur = None

    try:

        data = request.get_json(silent=True) or {}

        conductor_id = data.get("conductor_id")
        unidad_id = data.get("unidad_id")

        if not conductor_id and not unidad_id:

            return jsonify({
                "error":
                    "Debe seleccionar conductor o unidad."
            }), 400

        conn = get_db()
        cur = conn.cursor()

        # ----------------------------------------------------
        # BUSCAR ASIGNACIÓN
        # ----------------------------------------------------

        if conductor_id and unidad_id:

            cur.execute("""
                SELECT id
                FROM asignaciones
                WHERE conductor_id=%s
                AND unidad_id=%s
            """, (
                conductor_id,
                unidad_id
            ))

        elif conductor_id:

            cur.execute("""
                SELECT id
                FROM asignaciones
                WHERE conductor_id=%s
            """, (conductor_id,))

        else:

            cur.execute("""
                SELECT id
                FROM asignaciones
                WHERE unidad_id=%s
            """, (unidad_id,))

        asignacion = cur.fetchone()

        if not asignacion:

            return jsonify({
                "error":
                    "No existe una asignación activa."
            }), 404

        # ----------------------------------------------------
        # LIBERAR CONDUCTOR
        # ----------------------------------------------------

        if conductor_id:

            cur.execute("""
                UPDATE conductores
                SET estado='disponible'
                WHERE id=%s
            """, (conductor_id,))

        # ----------------------------------------------------
        # LIBERAR UNIDAD
        # ----------------------------------------------------

        if unidad_id:

            cur.execute("""
                UPDATE unidades
                SET estado='disponible'
                WHERE id=%s
            """, (unidad_id,))

        # ----------------------------------------------------
        # ELIMINAR ASIGNACIÓN
        # ----------------------------------------------------

        if conductor_id and unidad_id:

            cur.execute("""
                DELETE FROM asignaciones
                WHERE conductor_id=%s
                AND unidad_id=%s
            """, (
                conductor_id,
                unidad_id
            ))

        elif conductor_id:

            cur.execute("""
                DELETE FROM asignaciones
                WHERE conductor_id=%s
            """, (conductor_id,))

        else:

            cur.execute("""
                DELETE FROM asignaciones
                WHERE unidad_id=%s
            """, (unidad_id,))

        conn.commit()

        registrar_movimiento(
            "Finalizó asignación"
        )

        return jsonify({
            "ok": True,
            "mensaje": "Asignación finalizada."
        })

    except Exception as e:

        if conn:
            conn.rollback()

        return jsonify({
            "error": str(e)
        }), 500

    finally:

        if cur:
            cur.close()

        if conn:
            conn.close()


# ============================================================
# CAMBIAR ESTADO DE UNIDAD
#
# ADMIN / SUPERVISOR
# ============================================================

@app.route("/cambiar_estado_unidad", methods=["POST"])
@requiere_rol("admin", "supervisor")
def cambiar_estado_unidad():

    conn = None
    cur = None

    try:

        data = request.get_json(silent=True) or {}

        unidad_id = data.get("unidad_id")

        nuevo_estado = data.get("estado")

        observacion = data.get(
            "observacion",
            ""
        ).strip()

        estados_validos = [
            "disponible",
            "inhabilitado"
        ]

        if nuevo_estado not in estados_validos:

            return jsonify({
                "error": "Estado inválido."
            }), 400

        conn = get_db()
        cur = conn.cursor()

        cur.execute("""
            SELECT
                placa,
                estado
            FROM unidades
            WHERE id=%s
            FOR UPDATE
        """, (unidad_id,))

        unidad = cur.fetchone()

        if not unidad:

            return jsonify({
                "error": "Unidad no existe."
            }), 404

        if unidad[1] == "ocupada":

            return jsonify({
                "error":
                    "No se puede cambiar el estado "
                    "de una unidad ocupada."
            }), 400

        cur.execute("""
            UPDATE unidades
            SET estado=%s
            WHERE id=%s
        """, (
            nuevo_estado,
            unidad_id
        ))

        conn.commit()

        if nuevo_estado == "inhabilitado":

            texto = "INHABILITADA"

        else:

            texto = "HABILITADA"

        registrar_movimiento(
            f"Unidad {unidad[0]} fue {texto}",
            observacion
        )

        return jsonify({
            "ok": True
        })

    except Exception as e:

        if conn:
            conn.rollback()

        return jsonify({
            "error": str(e)
        }), 500

    finally:

        if cur:
            cur.close()

        if conn:
            conn.close()


# ============================================================
# SOLICITAR ASIGNACIÓN
#
# SOLO OPERADOR
# ============================================================

@app.route("/solicitar_asignacion", methods=["POST"])
@requiere_rol("operador")
def solicitar_asignacion():

    conn = None
    cur = None

    try:

        data = request.get_json(silent=True) or {}

        conductor_id = data.get("conductor_id")
        unidad_id = data.get("unidad_id")

        observacion = data.get(
            "observacion",
            ""
        ).strip()

        if not conductor_id or not unidad_id:

            return jsonify({
                "error":
                    "Debe seleccionar conductor y unidad."
            }), 400

        conn = get_db()
        cur = conn.cursor()

        # ----------------------------------------------------
        # VERIFICAR CONDUCTOR
        # ----------------------------------------------------

        cur.execute("""
            SELECT
                id,
                nombre,
                estado
            FROM conductores
            WHERE id=%s
        """, (conductor_id,))

        conductor = cur.fetchone()

        if not conductor:

            return jsonify({
                "error": "Conductor no existe."
            }), 404

        # ----------------------------------------------------
        # VERIFICAR UNIDAD
        # ----------------------------------------------------

        cur.execute("""
            SELECT
                id,
                placa,
                estado
            FROM unidades
            WHERE id=%s
        """, (unidad_id,))

        unidad = cur.fetchone()

        if not unidad:

            return jsonify({
                "error": "Unidad no existe."
            }), 404

        # ----------------------------------------------------
        # VALIDAR DISPONIBILIDAD
        # ----------------------------------------------------

        if conductor[2] != "disponible":

            return jsonify({
                "error":
                    "El conductor no está disponible."
            }), 400

        if unidad[2] != "disponible":

            return jsonify({
                "error":
                    "La unidad no está disponible."
            }), 400

        # ----------------------------------------------------
        # USUARIO ACTUAL
        # ----------------------------------------------------

        usuario_id = session["user"]["id"]

        # ----------------------------------------------------
        # EVITAR SOLICITUDES DUPLICADAS
        # ----------------------------------------------------

        cur.execute("""
            SELECT id
            FROM solicitudes_asignacion
            WHERE conductor_id=%s
            AND unidad_id=%s
            AND estado='pendiente'
        """, (
            conductor_id,
            unidad_id
        ))

        if cur.fetchone():

            return jsonify({
                "error":
                    "Ya existe una solicitud pendiente "
                    "para esta asignación."
            }), 400

        # ----------------------------------------------------
        # CREAR SOLICITUD
        # ----------------------------------------------------

        cur.execute("""
            INSERT INTO solicitudes_asignacion(
                conductor_id,
                unidad_id,
                usuario_id,
                estado,
                observacion
            )
            VALUES(
                %s,
                %s,
                %s,
                'pendiente',
                %s
            )
        """, (
            conductor_id,
            unidad_id,
            usuario_id,
            observacion
        ))

        conn.commit()

        registrar_movimiento(
            f"Solicitó asignación "
            f"{conductor[1]} → {unidad[1]}",
            observacion
        )

        return jsonify({
            "ok": True,
            "mensaje":
                "Solicitud enviada correctamente."
        })

    except Exception as e:

        if conn:
            conn.rollback()

        return jsonify({
            "error": str(e)
        }), 500

    finally:

        if cur:
            cur.close()

        if conn:
            conn.close()


# ============================================================
# VER SOLICITUDES
#
# ADMIN / SUPERVISOR / OPERADOR
# ============================================================

@app.route("/solicitudes")
@requiere_rol(
    "admin",
    "supervisor",
    "operador"
)
def solicitudes():

    conn = None
    cur = None

    try:

        conn = get_db()
        cur = conn.cursor()

        # ----------------------------------------------------
        # OPERADOR:
        # SOLO SUS SOLICITUDES
        # ----------------------------------------------------

        if tiene_rol("operador"):

            cur.execute("""
                SELECT
                    s.id,
                    s.conductor_id,
                    s.unidad_id,
                    c.nombre,
                    u.placa,
                    s.estado,
                    s.observacion,
                    s.fecha,
                    COALESCE(us.username,''),
                    COALESCE(s.atendido_por,'')
                FROM solicitudes_asignacion s
                JOIN conductores c
                    ON c.id=s.conductor_id
                JOIN unidades u
                    ON u.id=s.unidad_id
                LEFT JOIN usuarios us
                    ON us.id=s.usuario_id
                WHERE s.usuario_id=%s
                ORDER BY s.id DESC
            """, (
                session["user"]["id"],
            ))

        # ----------------------------------------------------
        # ADMIN / SUPERVISOR:
        # TODAS
        # ----------------------------------------------------

        else:

            cur.execute("""
                SELECT
                    s.id,
                    s.conductor_id,
                    s.unidad_id,
                    c.nombre,
                    u.placa,
                    s.estado,
                    s.observacion,
                    s.fecha,
                    COALESCE(us.username,''),
                    COALESCE(s.atendido_por,'')
                FROM solicitudes_asignacion s
                JOIN conductores c
                    ON c.id=s.conductor_id
                JOIN unidades u
                    ON u.id=s.unidad_id
                LEFT JOIN usuarios us
                    ON us.id=s.usuario_id
                ORDER BY s.id DESC
            """)

        data = cur.fetchall()

        return jsonify([

            {
                "id": x[0],
                "conductor_id": x[1],
                "unidad_id": x[2],
                "conductor": x[3],
                "unidad": x[4],
                "estado": x[5],
                "observacion": x[6] or "",
                "fecha": str(x[7]) if x[7] else "",
                "usuario": x[8],
                "atendido_por": x[9]
            }

            for x in data

        ])

    except Exception as e:

        return jsonify({
            "error": str(e)
        }), 500

    finally:

        if cur:
            cur.close()

        if conn:
            conn.close()


# ============================================================
# APROBAR SOLICITUD
#
# ADMIN / SUPERVISOR
# ============================================================

@app.route("/aprobar_solicitud", methods=["POST"])
@requiere_rol("admin", "supervisor")
def aprobar_solicitud():

    conn = None
    cur = None

    try:

        data = request.get_json(silent=True) or {}

        solicitud_id = data.get(
            "solicitud_id"
        )

        if not solicitud_id:

            return jsonify({
                "error": "Solicitud no especificada."
            }), 400

        conn = get_db()
        cur = conn.cursor()

        # ----------------------------------------------------
        # BLOQUEAR SOLICITUD
        # ----------------------------------------------------

        cur.execute("""
            SELECT
                s.id,
                s.conductor_id,
                s.unidad_id,
                s.estado,
                c.nombre,
                c.estado,
                u.placa,
                u.estado
            FROM solicitudes_asignacion s
            JOIN conductores c
                ON c.id=s.conductor_id
            JOIN unidades u
                ON u.id=s.unidad_id
            WHERE s.id=%s
            FOR UPDATE
        """, (solicitud_id,))

        solicitud = cur.fetchone()

        if not solicitud:

            return jsonify({
                "error": "Solicitud no existe."
            }), 404

        (
            sid,
            conductor_id,
            unidad_id,
            estado_solicitud,
            conductor_nombre,
            conductor_estado,
            placa,
            unidad_estado
        ) = solicitud

        if estado_solicitud != "pendiente":

            return jsonify({
                "error":
                    "La solicitud ya fue procesada."
            }), 400

        if conductor_estado != "disponible":

            return jsonify({
                "error":
                    "El conductor ya no está disponible."
            }), 400

        if unidad_estado != "disponible":

            return jsonify({
                "error":
                    "La unidad ya no está disponible."
            }), 400

        # ----------------------------------------------------
        # CREAR ASIGNACIÓN
        # ----------------------------------------------------

        cur.execute("""
            INSERT INTO asignaciones(
                conductor_id,
                unidad_id
            )
            VALUES(%s,%s)
        """, (
            conductor_id,
            unidad_id
        ))

        # ----------------------------------------------------
        # ACTUALIZAR CONDUCTOR
        # ----------------------------------------------------

        cur.execute("""
            UPDATE conductores
            SET estado='en_ruta'
            WHERE id=%s
        """, (conductor_id,))

        # ----------------------------------------------------
        # ACTUALIZAR UNIDAD
        # ----------------------------------------------------

        cur.execute("""
            UPDATE unidades
            SET estado='ocupada'
            WHERE id=%s
        """, (unidad_id,))

        # ----------------------------------------------------
        # ACTUALIZAR SOLICITUD
        # ----------------------------------------------------

        usuario = session["user"]["username"]

        cur.execute("""
            UPDATE solicitudes_asignacion
            SET
                estado='aprobada',
                atendido_por=%s,
                fecha_atencion=CURRENT_TIMESTAMP
            WHERE id=%s
        """, (
            usuario,
            solicitud_id
        ))

        conn.commit()

        registrar_movimiento(
            f"Aprobó solicitud "
            f"{conductor_nombre} → {placa}"
        )

        return jsonify({
            "ok": True,
            "mensaje":
                "Asignación aprobada correctamente."
        })

    except Exception as e:

        if conn:
            conn.rollback()

        return jsonify({
            "error": str(e)
        }), 500

    finally:

        if cur:
            cur.close()

        if conn:
            conn.close()


# ============================================================
# RECHAZAR SOLICITUD
#
# ADMIN / SUPERVISOR
# ============================================================

@app.route("/rechazar_solicitud", methods=["POST"])
@requiere_rol("admin", "supervisor")
def rechazar_solicitud():

    conn = None
    cur = None

    try:

        data = request.get_json(silent=True) or {}

        solicitud_id = data.get(
            "solicitud_id"
        )

        observacion = data.get(
            "observacion",
            ""
        ).strip()

        if not solicitud_id:

            return jsonify({
                "error":
                    "Solicitud no especificada."
            }), 400

        conn = get_db()
        cur = conn.cursor()

        cur.execute("""
            SELECT
                c.nombre,
                u.placa
            FROM solicitudes_asignacion s
            JOIN conductores c
                ON c.id=s.conductor_id
            JOIN unidades u
                ON u.id=s.unidad_id
            WHERE s.id=%s
            AND s.estado='pendiente'
        """, (solicitud_id,))

        solicitud = cur.fetchone()

        if not solicitud:

            return jsonify({
                "error":
                    "Solicitud no encontrada "
                    "o ya procesada."
            }), 404

        conductor = solicitud[0]
        placa = solicitud[1]

        usuario = session["user"]["username"]

        cur.execute("""
            UPDATE solicitudes_asignacion
            SET
                estado='rechazada',
                observacion=%s,
                atendido_por=%s,
                fecha_atencion=CURRENT_TIMESTAMP
            WHERE id=%s
        """, (
            observacion,
            usuario,
            solicitud_id
        ))

        conn.commit()

        registrar_movimiento(
            f"Rechazó solicitud "
            f"{conductor} → {placa}",
            observacion
        )

        return jsonify({
            "ok": True,
            "mensaje":
                "Solicitud rechazada."
        })

    except Exception as e:

        if conn:
            conn.rollback()

        return jsonify({
            "error": str(e)
        }), 500

    finally:

        if cur:
            cur.close()

        if conn:
            conn.close()


# ============================================================
# HISTORIAL
#
# SOLO ADMIN
# ============================================================

@app.route("/movimientos")
@requiere_rol("admin")
def movimientos():

    conn = None
    cur = None

    try:

        conn = get_db()
        cur = conn.cursor()

        cur.execute("""
            SELECT
                id,
                accion,
                usuario,
                fecha,
                obs
            FROM movimientos
            ORDER BY id DESC
        """)

        data = cur.fetchall()

        return jsonify([

            {
                "id": x[0],
                "accion": x[1],
                "usuario": x[2],
                "fecha": x[3],
                "obs": x[4] or ""
            }

            for x in data

        ])

    except Exception as e:

        return jsonify({
            "error": str(e)
        }), 500

    finally:

        if cur:
            cur.close()

        if conn:
            conn.close()


# ============================================================
# USUARIOS
#
# SOLO ADMIN
# ============================================================

@app.route("/usuarios")
@requiere_rol("admin")
def usuarios():

    conn = None
    cur = None

    try:

        conn = get_db()
        cur = conn.cursor()

        cur.execute("""
            SELECT
                id,
                username,
                rol
            FROM usuarios
            ORDER BY username
        """)

        data = cur.fetchall()

        return jsonify([

            {
                "id": x[0],
                "username": x[1],
                "rol": x[2]
            }

            for x in data

        ])

    except Exception as e:

        return jsonify({
            "error": str(e)
        }), 500

    finally:

        if cur:
            cur.close()

        if conn:
            conn.close()


# ============================================================
# CREAR USUARIO
#
# SOLO ADMIN
# ============================================================

@app.route("/crear_usuario", methods=["POST"])
@requiere_rol("admin")
def crear_usuario():

    conn = None
    cur = None

    try:

        data = request.get_json(silent=True) or {}

        username = data.get(
            "username",
            ""
        ).strip()

        password = data.get(
            "password",
            ""
        )

        rol = data.get("rol")

        roles_validos = [
            "admin",
            "supervisor",
            "operador"
        ]

        if not username or not password:

            return jsonify({
                "error":
                    "Usuario y contraseña son obligatorios."
            }), 400

        if rol not in roles_validos:

            return jsonify({
                "error": "Rol inválido."
            }), 400

        conn = get_db()
        cur = conn.cursor()

        cur.execute("""
            SELECT id
            FROM usuarios
            WHERE username=%s
        """, (username,))

        if cur.fetchone():

            return jsonify({
                "error": "El usuario ya existe."
            }), 400

        password_hash = generate_password_hash(
            password
        )

        cur.execute("""
            INSERT INTO usuarios(
                username,
                password,
                rol
            )
            VALUES(%s,%s,%s)
        """, (
            username,
            password_hash,
            rol
        ))

        conn.commit()

        registrar_movimiento(
            f"Creó usuario {username} ({rol})"
        )

        return jsonify({
            "ok": True
        })

    except Exception as e:

        if conn:
            conn.rollback()

        return jsonify({
            "error": str(e)
        }), 500

    finally:

        if cur:
            cur.close()

        if conn:
            conn.close()


# ============================================================
# EDITAR USUARIO
#
# SOLO ADMIN
# ============================================================

@app.route("/editar_usuario", methods=["POST"])
@requiere_rol("admin")
def editar_usuario():

    conn = None
    cur = None

    try:

        data = request.get_json(silent=True) or {}

        user_id = data.get("id")

        username = data.get(
            "username",
            ""
        ).strip()

        password = data.get(
            "password",
            ""
        )

        rol = data.get("rol")

        roles_validos = [
            "admin",
            "supervisor",
            "operador"
        ]

        if not user_id or not username:

            return jsonify({
                "error": "Datos incompletos."
            }), 400

        if rol not in roles_validos:

            return jsonify({
                "error": "Rol inválido."
            }), 400

        conn = get_db()
        cur = conn.cursor()

        cur.execute("""
            SELECT
                username,
                rol
            FROM usuarios
            WHERE id=%s
        """, (user_id,))

        usuario = cur.fetchone()

        if not usuario:

            return jsonify({
                "error": "Usuario no existe."
            }), 404

        # ----------------------------------------------------
        # EVITAR CAMBIOS QUE DEJEN AL SISTEMA SIN ADMIN
        # ----------------------------------------------------

        if usuario[1] == "admin" and rol != "admin":

            cur.execute("""
                SELECT COUNT(*)
                FROM usuarios
                WHERE rol='admin'
            """)

            cantidad_admin = cur.fetchone()[0]

            if cantidad_admin <= 1:

                return jsonify({
                    "error":
                        "Debe existir al menos un administrador."
                }), 400

        # ----------------------------------------------------
        # ACTUALIZAR CON PASSWORD
        # ----------------------------------------------------

        if password:

            password_hash = generate_password_hash(
                password
            )

            cur.execute("""
                UPDATE usuarios
                SET
                    username=%s,
                    password=%s,
                    rol=%s
                WHERE id=%s
            """, (
                username,
                password_hash,
                rol,
                user_id
            ))

        # ----------------------------------------------------
        # ACTUALIZAR SIN PASSWORD
        # ----------------------------------------------------

        else:

            cur.execute("""
                UPDATE usuarios
                SET
                    username=%s,
                    rol=%s
                WHERE id=%s
            """, (
                username,
                rol,
                user_id
            ))

        conn.commit()

        registrar_movimiento(
            f"Editó usuario "
            f"{usuario[0]} → {username}"
        )

        return jsonify({
            "ok": True
        })

    except Exception as e:

        if conn:
            conn.rollback()

        return jsonify({
            "error": str(e)
        }), 500

    finally:

        if cur:
            cur.close()

        if conn:
            conn.close()


# ============================================================
# ELIMINAR USUARIO
#
# SOLO ADMIN
# ============================================================

@app.route("/eliminar_usuario", methods=["POST"])
@requiere_rol("admin")
def eliminar_usuario():

    conn = None
    cur = None

    try:

        data = request.get_json(silent=True) or {}

        user_id = data.get("id")

        if not user_id:

            return jsonify({
                "error":
                    "Usuario no especificado."
            }), 400

        # No permitir eliminarse a sí mismo
        if int(user_id) == int(
            session["user"]["id"]
        ):

            return jsonify({
                "error":
                    "No puede eliminar su propio usuario."
            }), 400

        conn = get_db()
        cur = conn.cursor()

        cur.execute("""
            SELECT
                username,
                rol
            FROM usuarios
            WHERE id=%s
        """, (user_id,))

        usuario = cur.fetchone()

        if not usuario:

            return jsonify({
                "error":
                    "Usuario no existe."
            }), 404

        # ----------------------------------------------------
        # NO DEJAR EL SISTEMA SIN ADMIN
        # ----------------------------------------------------

        if usuario[1] == "admin":

            cur.execute("""
                SELECT COUNT(*)
                FROM usuarios
                WHERE rol='admin'
            """)

            cantidad_admin = cur.fetchone()[0]

            if cantidad_admin <= 1:

                return jsonify({
                    "error":
                        "No puede eliminar el último administrador."
                }), 400

        cur.execute("""
            DELETE FROM usuarios
            WHERE id=%s
        """, (user_id,))

        conn.commit()

        registrar_movimiento(
            f"Eliminó usuario {usuario[0]}"
        )

        return jsonify({
            "ok": True
        })

    except Exception as e:

        if conn:
            conn.rollback()

        return jsonify({
            "error": str(e)
        }), 500

    finally:

        if cur:
            cur.close()

        if conn:
            conn.close()


# ============================================================
# EXPORTAR EXCEL
#
# SOLO ADMIN
# ============================================================

@app.route("/exportar_excel")
@requiere_rol("admin")
def exportar_excel():

    conn = None
    cur = None

    try:

        conn = get_db()
        cur = conn.cursor()

        cur.execute("""
            SELECT
                accion,
                usuario,
                fecha,
                obs
            FROM movimientos
            ORDER BY id DESC
        """)

        data = cur.fetchall()

        workbook = Workbook()

        sheet = workbook.active
        sheet.title = "Historial"

        sheet.append([
            "Acción",
            "Usuario",
            "Fecha",
            "Observación"
        ])

        for row in data:

            sheet.append(row)

        sheet.column_dimensions["A"].width = 45
        sheet.column_dimensions["B"].width = 20
        sheet.column_dimensions["C"].width = 22
        sheet.column_dimensions["D"].width = 60

        file = io.BytesIO()

        workbook.save(file)

        file.seek(0)

        return send_file(
            file,
            as_attachment=True,
            download_name="historial.xlsx",
            mimetype=(
                "application/vnd.openxmlformats-officedocument."
                "spreadsheetml.sheet"
            )
        )

    except Exception as e:

        return jsonify({
            "error": str(e)
        }), 500

    finally:

        if cur:
            cur.close()

        if conn:
            conn.close()


# ============================================================
# HEALTH CHECK
# ============================================================

@app.route("/health")
def health():

    try:

        conn = get_db()
        cur = conn.cursor()

        cur.execute("SELECT 1")

        cur.fetchone()

        cur.close()
        conn.close()

        return jsonify({
            "status": "ok",
            "database": "connected"
        })

    except Exception as e:

        return jsonify({
            "status": "error",
            "database": str(e)
        }), 500


# ============================================================
# EJECUCIÓN
# ============================================================

if __name__ == "__main__":

    # Crear tablas al iniciar.
    init_db()

    port = int(
        os.environ.get(
            "PORT",
            5000
        )
    )

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False
    )
```
