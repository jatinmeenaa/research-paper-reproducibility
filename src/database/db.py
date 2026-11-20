import sqlite3
from pathlib import Path

from datetime import datetime, timezone


# Project root directory
PROJECT_ROOT = Path(__file__).resolve().parents[2]

DATABASE_PATH = PROJECT_ROOT / "instance" / "reproducibility_explorer.db"
SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"


# Create and return connection to database
def get_connection(db_path=None):


    if db_path is None:
        db_path = DATABASE_PATH

    db_path = Path(db_path) # path object for the path.... for using function

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

# save a research paper
# if already exists tthen id returned
def save_paper(paper):


    connection = get_connection()

    try:
        cursor = connection.cursor()

        cursor.execute("""
            INSERT INTO papers (source, external_id, title, authors, year, abstract, paper_url, pdf_url)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source, external_id) DO NOTHING """,
            (paper["source"],
            paper["external_id"],
            paper["title"],
            paper.get("authors"),
            paper.get("year"),
            paper.get("abstract"),
            paper.get("paper_url"),
            paper.get("pdf_url")))
        
        # retrieve id 
        cursor.execute("""
            SELECT id FROM papers
            WHERE source = ? AND external_id = ? """, ( paper["source"], paper["external_id"]))

        paper_id = cursor.fetchone()["id"]
        connection.commit()
        return paper_id

    finally:
        connection.close()

# retrieve a research paper by its id
def get_paper_by_id(paper_id):
    connection = get_connection()

    try:
        cursor = connection.execute("SELECT * FROM papers WHERE id = ?",(paper_id,))
        return cursor.fetchone()

    finally:
        connection.close()

# retrieve a research paper by its source and external id
def get_paper_by_external_id(source, external_id):

    connection = get_connection()
    try:
        cursor = connection.execute("""SELECT * FROM papers WHERE source = ? AND external_id = ? """,(source, external_id))
        return cursor.fetchone()

    finally:
        connection.close()