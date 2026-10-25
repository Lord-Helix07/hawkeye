import sqlite3 #loads sqlite database 


DATABASE_FILE = "hawkeye.db"


def initialize_database(): #prepares the database for use by creating a table if it doesn't exist
    connection = sqlite3.connect(DATABASE_FILE)  #connects to the database file
#defines the structure of the telemetry table in the database
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

    connection.commit() #commits the changes to the database
    connection.close() #closes the connection to the database after

def save_telemetry(data): # adds a new telemetry record to the database once Post request is received
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

def get_all_telemetry(): # returns all telemetry records from the database in revers eorder of their IDs
    connection = sqlite3.connect(DATABASE_FILE)
    connection.row_factory = sqlite3.Row

    rows = connection.execute("""
        SELECT *
        FROM telemetry
        ORDER BY id DESC
    """).fetchall()

    connection.close()

    return [dict(row) for row in rows]