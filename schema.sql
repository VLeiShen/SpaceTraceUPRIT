    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL UNIQUE COLLATE NOCASE,
        email TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'collaborator'
            CHECK (role IN ('admin', 'collaborator')),
        status TEXT NOT NULL DEFAULT 'pending'
            CHECK (status IN ('pending', 'active', 'disabled')),
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS editorial_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        section TEXT NOT NULL
            CHECK (section IN ('missions', 'timeline', 'science', 'media', 'general')),
        title_es TEXT NOT NULL,
        title_en TEXT NOT NULL,
        body_es TEXT NOT NULL,
        body_en TEXT NOT NULL,
        image_url TEXT NOT NULL DEFAULT '',
        source_url TEXT NOT NULL DEFAULT '',
        created_by INTEGER NOT NULL REFERENCES users(id),
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );

    CREATE INDEX IF NOT EXISTS idx_editorial_items_section
        ON editorial_items (section, id);

    CREATE INDEX IF NOT EXISTS idx_users_status_role
        ON users (status, role);
