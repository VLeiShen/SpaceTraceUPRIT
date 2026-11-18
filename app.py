import hmac
import os
import re
import secrets
import sqlite3
from functools import wraps
from urllib.parse import urlparse

import click
from flask import (
    Flask,
    abort,
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash

from database import get_db, init_db, register_db_commands


CONTENT_SECTIONS = {"missions", "timeline", "science", "media", "general"}
USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{3,32}$")
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

app = Flask(__name__, instance_relative_config=True)
app.config.update(
    SECRET_KEY=os.environ.get("SECRET_KEY") or secrets.token_hex(32),
    DATABASE=os.environ.get(
        "DATABASE_PATH",
        os.path.join(app.instance_path, "space_trace.sqlite3"),
    ),
    TURSO_DATABASE_URL=os.environ.get("TURSO_DATABASE_URL", ""),
    TURSO_AUTH_TOKEN=os.environ.get("TURSO_AUTH_TOKEN", ""),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("SESSION_COOKIE_SECURE", "").lower() == "true",
)
os.makedirs(app.instance_path, exist_ok=True)
register_db_commands(app)


@app.before_request
def load_request_user_and_csrf_token():
    g.user = None
    user_id = session.get("user_id")
    if user_id is not None:
        g.user = get_db().execute(
            "SELECT id, username, email, role, status FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
        if g.user is None or g.user["status"] != "active":
            session.clear()
            g.user = None

    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(32)
    g.csrf_token = session["csrf_token"]


@app.context_processor
def inject_template_context():
    return {"current_user": dict(g.user) if g.user else None, "csrf_token": g.csrf_token}


def require_csrf():
    submitted = request.form.get("csrf_token", "")
    expected = session.get("csrf_token", "")
    if not expected or not hmac.compare_digest(submitted, expected):
        abort(400, description="El formulario expiró o su token de seguridad no es válido.")


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            flash("Inicia sesión para continuar.", "error")
            return redirect(url_for("join", mode="login"))
        return view(*args, **kwargs)

    return wrapped


def editor_required(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if g.user["role"] not in {"admin", "collaborator"}:
            abort(403)
        return view(*args, **kwargs)

    return wrapped


def admin_required(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if g.user["role"] != "admin":
            abort(403)
        return view(*args, **kwargs)

    return wrapped


def valid_account(username, email, password):
    errors = []
    if not USERNAME_PATTERN.fullmatch(username):
        errors.append("El usuario debe tener entre 3 y 32 caracteres: letras, números, punto, guion o guion bajo.")
    if not EMAIL_PATTERN.fullmatch(email):
        errors.append("Escribe un correo electrónico válido.")
    if len(password) < 10:
        errors.append("La contraseña debe tener al menos 10 caracteres.")
    return errors


def valid_optional_url(value, label):
    if not value:
        return None
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return f"{label} debe ser una URL que comience con http:// o https://."
    return None


def validated_content(form):
    section = form.get("section", "").strip()
    title_es = form.get("title_es", "").strip()
    title_en = form.get("title_en", "").strip()
    body_es = form.get("body_es", "").strip()
    body_en = form.get("body_en", "").strip()
    image_url = form.get("image_url", "").strip()
    source_url = form.get("source_url", "").strip()
    errors = []

    if section not in CONTENT_SECTIONS:
        errors.append("Selecciona una sección válida.")
    for label, value, limit in (
        ("Título en español", title_es, 160),
        ("Título en inglés", title_en, 160),
        ("Texto en español", body_es, 5000),
        ("Texto en inglés", body_en, 5000),
    ):
        if not value:
            errors.append(f"{label} es obligatorio.")
        elif len(value) > limit:
            errors.append(f"{label} supera el máximo de {limit} caracteres.")
    for value, label in ((image_url, "La imagen"), (source_url, "La fuente")):
        error = valid_optional_url(value, label)
        if error:
            errors.append(error)
    if len(image_url) > 2048 or len(source_url) > 2048:
        errors.append("Las URL no pueden superar 2048 caracteres.")

    return {
        "section": section,
        "title_es": title_es,
        "title_en": title_en,
        "body_es": body_es,
        "body_en": body_en,
        "image_url": image_url,
        "source_url": source_url,
    }, errors


@app.get("/")
def home():
    editorial_items = get_db().execute(
        "SELECT * FROM editorial_items ORDER BY section, id DESC"
    ).fetchall()
    return render_template("index.html", editorial_items=editorial_items)


@app.get("/join")
def join():
    if g.user:
        return redirect(url_for("admin_panel"))
    mode = request.args.get("mode", "login")
    return render_template("join.html", mode=mode if mode in {"login", "register"} else "login")


@app.post("/join")
def join_submit():
    require_csrf()
    action = request.form.get("action")
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")

    if action == "login":
        user = get_db().execute(
            "SELECT * FROM users WHERE username = ? COLLATE NOCASE",
            (username,),
        ).fetchone()
        if user is None or not check_password_hash(user["password_hash"], password):
            flash("Usuario o contraseña incorrectos.", "error")
        elif user["status"] == "pending":
            flash("Tu cuenta está pendiente de aprobación por un administrador.", "error")
        elif user["status"] != "active":
            flash("Esta cuenta está desactivada. Contacta al administrador.", "error")
        else:
            session.clear()
            session["user_id"] = user["id"]
            session["csrf_token"] = secrets.token_urlsafe(32)
            flash(f"Bienvenido, {user['username']}.", "success")
            return redirect(url_for("admin_panel"))
        return redirect(url_for("join", mode="login"))

    if action == "register":
        email = request.form.get("email", "").strip().lower()
        errors = valid_account(username, email, password)
        if errors:
            for error in errors:
                flash(error, "error")
            return redirect(url_for("join", mode="register"))
        try:
            get_db().execute(
                """INSERT INTO users (username, email, password_hash, role, status)
                   VALUES (?, ?, ?, 'collaborator', 'pending')""",
                (username, email, generate_password_hash(password)),
            )
            get_db().commit()
        except sqlite3.IntegrityError:
            flash("Ese nombre de usuario o correo ya está registrado.", "error")
            return redirect(url_for("join", mode="register"))
        flash("Registro recibido. Un administrador debe aprobar la cuenta antes de iniciar sesión.", "success")
        return redirect(url_for("join", mode="login"))

    abort(400, description="Acción de autenticación desconocida.")


@app.post("/logout")
@login_required
def logout():
    require_csrf()
    session.clear()
    flash("Has cerrado sesión.", "success")
    return redirect(url_for("home"))


@app.get("/admin")
@editor_required
def admin_panel():
    database = get_db()
    editorial_items = database.execute(
        """SELECT editorial_items.*, users.username AS author
           FROM editorial_items
           JOIN users ON users.id = editorial_items.created_by
           ORDER BY editorial_items.updated_at DESC, editorial_items.id DESC"""
    ).fetchall()
    pending_users = []
    collaborators = []
    if g.user["role"] == "admin":
        pending_users = database.execute(
            "SELECT id, username, email, created_at FROM users WHERE status = 'pending' ORDER BY created_at"
        ).fetchall()
        collaborators = database.execute(
            """SELECT id, username, email, role, status, created_at
               FROM users WHERE id != ? ORDER BY role, username""",
            (g.user["id"],),
        ).fetchall()
    return render_template(
        "admin.html",
        editorial_items=editorial_items,
        pending_users=pending_users,
        collaborators=collaborators,
    )


@app.post("/admin/users/create")
@admin_required
def create_collaborator():
    require_csrf()
    username = request.form.get("username", "").strip()
    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")
    errors = valid_account(username, email, password)
    if errors:
        for error in errors:
            flash(error, "error")
        return redirect(url_for("admin_panel"))
    try:
        get_db().execute(
            """INSERT INTO users (username, email, password_hash, role, status)
               VALUES (?, ?, ?, 'collaborator', 'active')""",
            (username, email, generate_password_hash(password)),
        )
        get_db().commit()
    except sqlite3.IntegrityError:
        flash("Ese nombre de usuario o correo ya está registrado.", "error")
        return redirect(url_for("admin_panel"))
    flash(f"Colaborador «{username}» creado.", "success")
    return redirect(url_for("admin_panel"))


@app.post("/admin/users/<int:user_id>/<action>")
@admin_required
def manage_user(user_id, action):
    require_csrf()
    database = get_db()
    target = database.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if target is None:
        abort(404)
    if target["id"] == g.user["id"]:
        flash("No puedes cambiar tu propio acceso desde este panel.", "error")
        return redirect(url_for("admin_panel"))

    if action == "approve" and target["status"] == "pending":
        database.execute("UPDATE users SET status = 'active' WHERE id = ?", (user_id,))
    elif action == "enable" and target["status"] == "disabled":
        database.execute("UPDATE users SET status = 'active' WHERE id = ?", (user_id,))
    elif action == "disable" and target["status"] == "active":
        if target["role"] == "admin":
            active_admins = database.execute(
                "SELECT COUNT(*) FROM users WHERE role = 'admin' AND status = 'active'"
            ).fetchone()[0]
            if active_admins <= 1:
                flash("Debe quedar al menos un administrador activo.", "error")
                return redirect(url_for("admin_panel"))
        database.execute("UPDATE users SET status = 'disabled' WHERE id = ?", (user_id,))
    elif action == "promote" and target["role"] == "collaborator" and target["status"] == "active":
        database.execute("UPDATE users SET role = 'admin' WHERE id = ?", (user_id,))
    elif action == "demote" and target["role"] == "admin" and target["status"] == "active":
        active_admins = database.execute(
            "SELECT COUNT(*) FROM users WHERE role = 'admin' AND status = 'active'"
        ).fetchone()[0]
        if active_admins <= 1:
            flash("Debe quedar al menos un administrador activo.", "error")
            return redirect(url_for("admin_panel"))
        database.execute("UPDATE users SET role = 'collaborator' WHERE id = ?", (user_id,))
    else:
        abort(400, description="La acción no es válida para el estado actual de esta cuenta.")

    database.commit()
    flash("Permisos de la cuenta actualizados.", "success")
    return redirect(url_for("admin_panel"))


@app.route("/admin/content/new", methods=["GET", "POST"])
@editor_required
def create_content():
    if request.method == "POST":
        require_csrf()
        content, errors = validated_content(request.form)
        if errors:
            for error in errors:
                flash(error, "error")
            return render_template("content_form.html", item=request.form, editing=False), 400
        database = get_db()
        database.execute(
            """INSERT INTO editorial_items
               (section, title_es, title_en, body_es, body_en, image_url, source_url, created_by)
               VALUES (:section, :title_es, :title_en, :body_es, :body_en, :image_url, :source_url, :created_by)""",
            {**content, "created_by": g.user["id"]},
        )
        database.commit()
        flash("Contenido publicado en el archivo.", "success")
        return redirect(url_for("admin_panel"))
    return render_template("content_form.html", item={}, editing=False)


@app.route("/admin/content/<int:item_id>/edit", methods=["GET", "POST"])
@editor_required
def edit_content(item_id):
    database = get_db()
    stored_item = database.execute(
        "SELECT * FROM editorial_items WHERE id = ?",
        (item_id,),
    ).fetchone()
    if stored_item is None:
        abort(404)
    item = dict(stored_item)
    if request.method == "POST":
        require_csrf()
        content, errors = validated_content(request.form)
        if errors:
            for error in errors:
                flash(error, "error")
            return render_template("content_form.html", item=request.form, editing=True), 400
        database.execute(
            """UPDATE editorial_items
               SET section = :section, title_es = :title_es, title_en = :title_en,
                   body_es = :body_es, body_en = :body_en, image_url = :image_url,
                   source_url = :source_url, updated_at = CURRENT_TIMESTAMP
               WHERE id = :id""",
            {**content, "id": item_id},
        )
        database.commit()
        flash("Contenido actualizado.", "success")
        return redirect(url_for("admin_panel"))
    return render_template("content_form.html", item=item, editing=True)


@app.post("/admin/content/<int:item_id>/delete")
@editor_required
def delete_content(item_id):
    require_csrf()
    database = get_db()
    result = database.execute("DELETE FROM editorial_items WHERE id = ?", (item_id,))
    if result.rowcount == 0:
        abort(404)
    database.commit()
    flash("Contenido eliminado.", "success")
    return redirect(url_for("admin_panel"))


@app.get("/api/editorial")
def editorial_api():
    language = request.args.get("lang", "es")
    if language not in {"es", "en"}:
        abort(400, description="El idioma debe ser «es» o «en».")
    rows = get_db().execute(
        "SELECT id, section, title_es, title_en, body_es, body_en, image_url, source_url FROM editorial_items ORDER BY section, id DESC"
    ).fetchall()
    return jsonify([dict(row) for row in rows])


@app.get("/mision-luna")
def mision_luna():
    return send_from_directory(app.static_folder, "pages/misionluna.html")


@app.get("/cohete-luna")
def cohete_luna():
    return send_from_directory(app.static_folder, "pages/cohete-luna.html")


@app.cli.command("create-admin")
def create_admin_command():
    """Create the first administrator interactively."""
    username = click.prompt("Nombre de usuario")
    email = click.prompt("Correo electrónico")
    password = click.prompt("Contraseña (mínimo 10 caracteres)", hide_input=True, confirmation_prompt=True)
    errors = valid_account(username.strip(), email.strip().lower(), password)
    if errors:
        raise click.ClickException(" ".join(errors))
    try:
        get_db().execute(
            """INSERT INTO users (username, email, password_hash, role, status)
               VALUES (?, ?, ?, 'admin', 'active')""",
            (username.strip(), email.strip().lower(), generate_password_hash(password)),
        )
        get_db().commit()
    except sqlite3.IntegrityError as error:
        raise click.ClickException("Ese nombre de usuario o correo ya está registrado.") from error
    click.echo("Administrador creado.")


with app.app_context():
    init_db()


if __name__ == "__main__":
    app.run()
