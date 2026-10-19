import sqlite3


DATABASE_FILE = "hawkeye.db"


def initialize_database():
    connection = sqlite3.connect(DATABASE_FILE)

    connection.execute("""
        CREATE TABLE IF NOT EXISTS telemetry (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            drone_id TEXT NOT NULL,
            speed REAL NOT NULL,
            battery REAL NOT NULL,
            status TEXT NOT NULL,
            mission_id TEXT NOT NULL
        )
    """)

    connection.commit()
    connection.close()

def save_telemetry(data):
    connection = sqlite3.connect(DATABASE_FILE)

    connection.execute("""
        INSERT INTO telemetry (
            drone_id,
            speed,
            battery,
            status,
            mission_id
        )
        VALUES (?, ?, ?, ?, ?)
    """, (
        data.drone_id,
        data.speed,
        data.battery,
        data.status,
        data.mission_id
    ))

    connection.commit()
    connection.close()

def get_all_telemetry():
    connection = sqlite3.connect(DATABASE_FILE)
    connection.row_factory = sqlite3.Row

    rows = connection.execute("""
        SELECT *
        FROM telemetry
        ORDER BY id DESC
    """).fetchall()

    connection.close()

    return [dict(row) for row in rows]