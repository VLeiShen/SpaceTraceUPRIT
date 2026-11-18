# Space Trace

Sitio informativo bilingüe de exploración espacial, servido con Flask. Incluye un archivo editorial gestionado con SQLite/libSQL, acceso de equipo y permisos de administrador y colaborador.

## Ejecutar localmente en Windows

Desde la carpeta del proyecto:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python app.py
```

Sin variables de Turso, la aplicación usa `instance/space_trace.sqlite3` para el desarrollo local. Al ejecutar `python app.py`, la base local se crea automáticamente.

## Conectar con Turso (libSQL)

La aplicación detecta `TURSO_DATABASE_URL` y `TURSO_AUTH_TOKEN` y usa el cliente Python `libsql`. Configura ambas variables en el entorno; no guardes sus valores en el repositorio. La URL debe comenzar con `libsql://`.

El esquema de [schema.sql](schema.sql) se prepara de forma idempotente con el comando `init-db`. Para inicializar la base y crear el primer administrador en Turso, ejecuta estos comandos con las variables de Turso ya configuradas:

```powershell
$env:TURSO_DATABASE_URL = "libsql://tu-base.turso.io"
$env:TURSO_AUTH_TOKEN = "tu-token-secreto"
.\.venv\Scripts\flask.exe --app app init-db
.\.venv\Scripts\flask.exe --app app create-admin
```

Usa los valores de la página **Connect** de Turso y no publiques el token ni lo compartas en chats. El comando solicita usuario, correo y contraseña de forma interactiva. No hay credenciales iniciales guardadas en el código. Los registros nuevos quedan pendientes hasta que un administrador los apruebe.

## Desplegar en Render

Conecta el repositorio GitHub como **Web Service** y configura:

- **Build Command:** `pip install -r requirements.txt`
- **Start Command:** `gunicorn app:app --bind 0.0.0.0:$PORT`
- **Variables secretas:** `SECRET_KEY`, `TURSO_DATABASE_URL`, `TURSO_AUTH_TOKEN` y `SESSION_COOKIE_SECURE=true`.

El archivo `.python-version` fija Python 3.13 para el despliegue. Genera `SECRET_KEY` con `python -c "import secrets; print(secrets.token_hex(32))"` y guárdala en Render, no en GitHub. El plan gratuito de Render puede suspender la web tras un período sin visitas; la base permanece en Turso. Su sistema de archivos local no es persistente.

## Permisos

- **Administrador:** gestiona cuentas, aprueba solicitudes, activa/desactiva usuarios, cambia roles y gestiona las entradas del archivo editorial.
- **Colaborador:** crea, edita y elimina entradas editoriales.
- **Visitante:** consulta el sitio y las entradas publicadas sin registrarse.

Las entradas editoriales pueden pertenecer a Misiones, Cronología, Ciencia, Medios o General, y admiten contenido en español e inglés, imagen y fuente.

## Pruebas

```powershell
python -m unittest -v
```
