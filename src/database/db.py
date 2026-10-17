import sqlite3
from pathlib import Path


# Project root directory
PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Database file location
DATABASE_PATH = PROJECT_ROOT / "instance" / "reproducibility_explorer.db"

# SQL schema file
SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"


# Create and return connection to database
def get_connection(db_path=None):


    if db_path is None:
        db_path = DATABASE_PATH

    db_path = Path(db_path) # path object for the path.... for using function

    # Ensure the parent directory exists
    db_path.parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(db_path)

    # Return query results as dictionary-like rows
    # access row['title']
    connection.row_factory = sqlite3.Row

    #foreign-key enforcement
    connection.execute("PRAGMA foreign_keys = ON")

    return connection


# create database tables if not exists already
def init_db(db_path=None):

    connection = get_connection(db_path)

    try:
        schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")
        connection.executescript(schema_sql)
        connection.commit()

    finally:
        connection.close()