import os
import re
import tempfile
import unittest

import libsql
from werkzeug.security import generate_password_hash

from app import app
from database import _LibsqlConnection, _execute_schema, get_db, init_db


class FlaskRoutesTestCase(unittest.TestCase):
    def setUp(self):
        app.config.update(
            TESTING=True,
            TURSO_DATABASE_URL="",
            TURSO_AUTH_TOKEN="",
        )
        self.temp_dir = tempfile.TemporaryDirectory()
        app.config["DATABASE"] = os.path.join(self.temp_dir.name, "test.sqlite3")
        self.addCleanup(self.temp_dir.cleanup)
        with app.app_context():
            init_db()
        self.client = app.test_client()

    def csrf_token(self, response):
        match = re.search(rb'name="csrf_token" value="([^"]+)"', response.data)
        self.assertIsNotNone(match)
        return match.group(1).decode()

    def get_response(self, path, method="GET"):
        response = self.client.open(path, method=method)
        self.addCleanup(response.close)
        return response

    def test_main_page_and_static_stylesheet(self):
        response = self.get_response("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Space Trace", response.data)

        stylesheet = self.get_response("/static/css/estilos.css")
        self.assertEqual(stylesheet.status_code, 200)

        for path in (
            "/static/img/Logo/Logo.png",
            "/static/Fondo/EspacioExterior.jpg",
            "/static/Fondo/SonidoEspacial.mp3",
        ):
            with self.subTest(asset=path):
                asset = self.get_response(path, method="HEAD")
                self.assertEqual(asset.status_code, 200)

    def test_embedded_game_pages(self):
        game_pages = (
            ("/mision-luna", "Misión Luna 3D: ¡Mide antes del queso!"),
            ("/cohete-luna", "Misión Tierra → Luna"),
        )
        for path, title in game_pages:
            with self.subTest(path=path):
                response = self.get_response(path)
                self.assertEqual(response.status_code, 200)
                self.assertIn(f"<title>{title}</title>".encode(), response.data)
                self.assertIn(b'id="go"', response.data)

    def test_game_scripts_point_to_flask_routes(self):
        response = self.get_response("/static/js/juego-main.js")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'mountEmbed("/mision-luna")', response.data)
        self.assertIn(b'mountEmbed("/cohete-luna")', response.data)

    def test_libsql_adapter_returns_named_and_positional_rows(self):
        connection = _LibsqlConnection(libsql.connect(":memory:"))
        self.addCleanup(connection.close)
        row = connection.execute(
            "SELECT 7 AS id, 'Voyager' AS name"
        ).fetchone()
        self.assertEqual(row["name"], "Voyager")
        self.assertEqual(row[0], 7)
        self.assertEqual(dict(row), {"id": 7, "name": "Voyager"})

    def test_schema_initializes_through_libsql_connection(self):
        connection = _LibsqlConnection(libsql.connect(":memory:"))
        self.addCleanup(connection.close)
        with open("schema.sql", encoding="utf-8") as schema_file:
            _execute_schema(connection, schema_file.read())
        tables = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
        ).fetchall()
        self.assertEqual([row["name"] for row in tables], ["editorial_items", "sqlite_sequence", "users"])

    def test_registration_is_pending_until_admin_approves(self):
        response = self.get_response("/join?mode=register")
        token = self.csrf_token(response)
        response = self.get_response(
            "/join",
            method="POST",
        )
        self.assertEqual(response.status_code, 400)

        response = self.client.post(
            "/join",
            data={
                "csrf_token": token,
                "action": "register",
                "username": "new.collab",
                "email": "collab@example.com",
                "password": "space-trace-password",
            },
        )
        self.assertEqual(response.status_code, 302)
        with app.app_context():
            user = get_db().execute(
                "SELECT role, status FROM users WHERE username = ?",
                ("new.collab",),
            ).fetchone()
        self.assertEqual(tuple(user), ("collaborator", "pending"))

        login_page = self.get_response("/join?mode=login")
        response = self.client.post(
            "/join",
            data={
                "csrf_token": self.csrf_token(login_page),
                "action": "login",
                "username": "new.collab",
                "password": "space-trace-password",
            },
        )
        self.assertEqual(response.status_code, 302)
        with self.client.session_transaction() as browser_session:
            self.assertNotIn("user_id", browser_session)
        pending_message = self.get_response("/join?mode=login")
        self.assertIn(b"pendiente de aprobaci", pending_message.data)

    def test_admin_can_create_content_and_collaborators_cannot_manage_users(self):
        with app.app_context():
            database = get_db()
            database.execute(
                """INSERT INTO users (username, email, password_hash, role, status)
                   VALUES (?, ?, ?, 'admin', 'active')""",
                ("chief", "chief@example.com", generate_password_hash("admin-password-long")),
            )
            database.commit()

        response = self.get_response("/join?mode=login")
        response = self.client.post(
            "/join",
            data={
                "csrf_token": self.csrf_token(response),
                "action": "login",
                "username": "chief",
                "password": "admin-password-long",
            },
        )
        self.assertEqual(response.status_code, 302)
        panel = self.get_response("/admin")
        self.assertIn(b"Equipo y permisos", panel.data)

        response = self.client.post(
            "/admin/users/create",
            data={
                "csrf_token": self.csrf_token(panel),
                "username": "editor",
                "email": "editor@example.com",
                "password": "editor-password-long",
            },
        )
        self.assertEqual(response.status_code, 302)

        response = self.client.post(
            "/admin/content/new",
            data={
                "csrf_token": self.csrf_token(self.get_response("/admin")),
                "section": "science",
                "title_es": "Hallazgo editorial",
                "title_en": "Editorial finding",
                "body_es": "Texto en español.",
                "body_en": "English text.",
                "image_url": "",
                "source_url": "https://example.com/source",
            },
        )
        self.assertEqual(response.status_code, 302)
        public_page = self.get_response("/")
        self.assertIn(b"Hallazgo editorial", public_page.data)
        self.assertIn(b"Editorial finding", public_page.data)

        with app.app_context():
            editor_id = get_db().execute(
                "SELECT id FROM users WHERE username = 'editor'"
            ).fetchone()["id"]
            content_id = get_db().execute(
                "SELECT id FROM editorial_items WHERE title_es = 'Hallazgo editorial'"
            ).fetchone()["id"]
        edit_page = self.get_response(f"/admin/content/{content_id}/edit")
        self.assertIn(b"Hallazgo editorial", edit_page.data)
        response = self.client.post(
            f"/admin/content/{content_id}/edit",
            data={
                "csrf_token": self.csrf_token(edit_page),
                "section": "science",
                "title_es": "Hallazgo actualizado",
                "title_en": "Updated finding",
                "body_es": "Texto actualizado.",
                "body_en": "Updated text.",
                "image_url": "",
                "source_url": "",
            },
        )
        self.assertEqual(response.status_code, 302)
        public_page = self.get_response("/")
        self.assertIn(b"Hallazgo actualizado", public_page.data)
        self.assertNotIn(b"Hallazgo editorial", public_page.data)
        panel = self.get_response("/admin")
        response = self.client.post(
            f"/admin/content/{content_id}/delete",
            data={"csrf_token": self.csrf_token(panel)},
        )
        self.assertEqual(response.status_code, 302)
        self.assertNotIn(b"Hallazgo actualizado", self.get_response("/").data)

        editor_client = app.test_client()
        login_page = editor_client.get("/join?mode=login")
        response = editor_client.post(
            "/join",
            data={
                "csrf_token": self.csrf_token(login_page),
                "action": "login",
                "username": "editor",
                "password": "editor-password-long",
            },
        )
        self.assertEqual(response.status_code, 302)
        blocked = editor_client.post(
            f"/admin/users/{editor_id}/disable",
            data={"csrf_token": "not-used-before-authorization"},
        )
        self.assertEqual(blocked.status_code, 403)


if __name__ == "__main__":
    unittest.main()
