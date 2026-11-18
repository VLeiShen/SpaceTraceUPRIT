import os
import sqlite3

import click
from flask import current_app, g


class _LibsqlRow:
    def __init__(self, column_names, values):
        self._column_names = tuple(column_names)
        self._values = tuple(values)
        self._positions = {name: index for index, name in enumerate(column_names)}

    def __getitem__(self, key):
        if isinstance(key, str):
            key = self._positions[key]
        return self._values[key]

    def __iter__(self):
        return iter(self._values)

    def __len__(self):
        return len(self._values)

    def keys(self):
        return self._column_names


class _LibsqlCursor:
    def __init__(self, cursor):
        self._cursor = cursor
        self._column_names = tuple(column[0] for column in cursor.description or ())

    def _row(self, values):
        if values is None:
            return None
        return _LibsqlRow(self._column_names, values)

    def fetchone(self):
        return self._row(self._cursor.fetchone())

    def fetchall(self):
        return [self._row(values) for values in self._cursor.fetchall()]

    def __iter__(self):
        for values in self._cursor:
            yield self._row(values)

    def __getattr__(self, name):
        return getattr(self._cursor, name)


class _LibsqlConnection:
    def __init__(self, connection):
        self._connection = connection

    def execute(self, *args, **kwargs):
        return _LibsqlCursor(self._connection.execute(*args, **kwargs))

    def commit(self):
        self._connection.commit()

    def close(self):
        self._connection.close()


def _connect_database():
    database_url = current_app.config.get("TURSO_DATABASE_URL", "").strip()
    auth_token = current_app.config.get("TURSO_AUTH_TOKEN", "").strip()
    if database_url or auth_token:
        if not database_url or not auth_token:
            raise RuntimeError(
                "TURSO_DATABASE_URL y TURSO_AUTH_TOKEN deben configurarse juntos."
            )
        if not database_url.startswith("libsql://"):
            raise RuntimeError("La URL de la base debe usar el esquema libsql://.")
        import libsql

        connection = libsql.connect(database=database_url, auth_token=auth_token)
        return _LibsqlConnection(connection)

    database_path = current_app.config["DATABASE"]
    os.makedirs(os.path.dirname(database_path), exist_ok=True)
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def get_db():
    if "db" not in g:
        g.db = _connect_database()
    return g.db


def close_db(_error=None):
    database = g.pop("db", None)
    if database is not None:
        database.close()


def _execute_schema(connection, schema):
    statement = ""
    for line in schema.splitlines():
        statement += line + "\n"
        if sqlite3.complete_statement(statement):
            if statement.strip():
                connection.execute(statement)
            statement = ""
    if statement.strip():
        raise ValueError("schema.sql contiene una instrucción SQL incompleta.")
    connection.commit()


def init_db():
    schema_path = os.path.join(current_app.root_path, "schema.sql")
    with open(schema_path, encoding="utf-8") as schema_file:
        schema = schema_file.read()
    _execute_schema(get_db(), schema)


def register_db_commands(app):
    app.teardown_appcontext(close_db)
    app.cli.add_command(init_db_command)


@click.command("init-db")
def init_db_command():
    init_db()
    click.echo("Base de datos preparada.")
