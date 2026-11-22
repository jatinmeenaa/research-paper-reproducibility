import sqlite3
from pathlib import Path

from datetime import datetime, timezone


PROJECT_ROOT = Path(__file__).resolve().parents[2]

DATABASE_PATH = PROJECT_ROOT / "instance" / "reproducibility_explorer.db"
SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"


def get_connection(db_path=None):


    if db_path is None:
        db_path = DATABASE_PATH

    db_path = Path(db_path) # path object for the path.... for using function

    db_path.parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row

    #foreign-key enforcement
    connection.execute("PRAGMA foreign_keys = ON")

    return connection


def init_db(db_path=None):

    connection = get_connection(db_path)

    try:
        schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")
        connection.executescript(schema_sql)
        connection.commit()

    finally:
        connection.close()

def save_paper(paper):


    connection = get_connection()

    try:
        cursor = connection.cursor()

        cursor.execute("""
            insert into papers (source, external_id, title, authors, year, abstract, paper_url, pdf_url)
            values (?, ?, ?, ?, ?, ?, ?, ?)
            on conflict(source, external_id) DO NOTHING """,
            (paper["source"], paper["external_id"], paper["title"], paper.get("authors"),paper.get("year"),
            paper.get("abstract"),paper.get("paper_url"),paper.get("pdf_url")))
        
        cursor.execute("""
            select id from papers
            where source = ? AND external_id = ? """, ( paper["source"], paper["external_id"]))

        paper_id = cursor.fetchone()["id"]
        connection.commit()
        return paper_id

    finally:
        connection.close()

def get_paper_by_id(paper_id):
    connection = get_connection()

    try:
        cursor = connection.execute("select * from papers where id = ?",(paper_id,))
        return cursor.fetchone()

    finally:
        connection.close()

def get_paper_by_external_id(source, external_id):

    connection = get_connection()
    try:
        cursor = connection.execute("""select * from papers where source = ? and external_id = ? """,(source, external_id))
        return cursor.fetchone()

    finally:
        connection.close()

def update_analysis_status(paper_id, status):

    valid_statuses = ["pending", "completed", "partial", "failed"]
    if status not in valid_statuses:
        raise ValueError("Invalid analysis status")

    connection = get_connection()

    try:
        if status == "pending":
            analyzed_at = None
        else:
            analyzed_at = datetime.now(timezone.utc).isoformat()

        cursor = connection.execute("""update papers set analysis_status = ?, last_analyzed_at = ? where id = ? """,(status, analyzed_at, paper_id))

        connection.commit()

        return cursor.rowcount > 0

    finally:
        connection.close()

def save_resources(paper_id, resources):
    connection = get_connection()

    try:
        current_time = datetime.now(timezone.utc).isoformat()

        resource_data = [
            (paper_id,resource["url"],
            resource["resource_type"],
            resource["accessibility_status"],
            resource.get("http_status"),
            resource.get("error_message"),
            resource.get("checked_at") or current_time
            )
            for resource in resources
        ]

        connection.executemany(
            """ insert into resources (
                paper_id,
                url,
                resource_type,
                accessibility_status,
                http_status,
                error_message,
                checked_at
            )
            values (?, ?, ?, ?, ?, ?, ?)

            on conflict(paper_id, url)
            do update set
                resource_type = excluded.resource_type,
                accessibility_status = excluded.accessibility_status,
                http_status = excluded.http_status,
                error_message = excluded.error_message,
                checked_at = excluded.checked_at
            """,
            resource_data)

        connection.commit()

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()

def get_resources_by_paper_id(paper_id):
    connection = get_connection()

    try:
        cursor = connection.execute(
            """select * from resources where paper_id = ? order by id
            """,(paper_id,))

        return cursor.fetchall()

    finally:
        connection.close()

def update_resources(paper_id, resources):

    connection = get_connection()
    try:
        current_time = datetime.now(timezone.utc).isoformat()
        resource_data = [
            (
                paper_id,
                resource["url"],
                resource["resource_type"],
                resource["accessibility_status"],
                resource.get("http_status"),
                resource.get("error_message"),
                resource.get("checked_at") or current_time
            )
            for resource in resources
        ]

        current_urls = [resource[1] for resource in resource_data]
        if current_urls:
            placeholders = ",".join("?" for _ in current_urls)

            connection.execute(
                f"""delete from resources where paper_id = ? and url not in ({placeholders})
                """,
                [paper_id] + current_urls
            )

        else:
            connection.execute(
                "delete from resources where paper_id = ?",
                (paper_id,))

        connection.executemany(
            """
            insert into resources (
                paper_id,url,resource_type,accessibility_status,
                http_status, error_message, checked_at )
            values (?, ?, ?, ?, ?, ?, ?)

            on conflict(paper_id, url)
            do update set
                resource_type = excluded.resource_type,
                accessibility_status = excluded.accessibility_status,
                http_status = excluded.http_status,
                error_message = excluded.error_message,
                checked_at = excluded.checked_at
            """,
            resource_data)

        connection.commit()

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()