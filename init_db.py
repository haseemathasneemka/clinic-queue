"""Run once: creates the database, tables, sample doctors and logins."""
import pymysql
from werkzeug.security import generate_password_hash
from config import DB_CONFIG

server_cfg = {k: v for k, v in DB_CONFIG.items() if k != "database"}
conn = pymysql.connect(**server_cfg)
with conn.cursor() as cur:
    cur.execute(f"CREATE DATABASE IF NOT EXISTS {DB_CONFIG['database']}")
conn.close()

conn = pymysql.connect(**DB_CONFIG)
with conn.cursor() as cur:
    with open("schema.sql", encoding="utf-8") as f:
        for stmt in f.read().split(";"):
            # drop comment lines, run the remaining SQL
            sql = "\n".join(l for l in stmt.splitlines() if not l.strip().startswith("--")).strip()
            if sql:
                cur.execute(sql)

    cur.execute("SELECT COUNT(*) FROM doctors")
    if cur.fetchone()[0] == 0:
        doctors = [
            ("Dr. Anjali Menon", "General Medicine", "101", "dr_anjali"),
            ("Dr. Rahul Nair", "Pediatrics", "102", "dr_rahul"),
            ("Dr. Fathima Rasheed", "Dermatology", "103", "dr_fathima"),
        ]
        for name, spec, room, username in doctors:
            cur.execute(
                "INSERT INTO doctors (name, specialization, room) VALUES (%s, %s, %s)",
                (name, spec, room),
            )
            doctor_id = cur.lastrowid
            cur.execute(
                "INSERT INTO users (username, password_hash, role, doctor_id) VALUES (%s, %s, 'doctor', %s)",
                (username, generate_password_hash("doctor123"), doctor_id),
            )
        cur.execute(
            "INSERT INTO users (username, password_hash, role) VALUES (%s, %s, 'admin')",
            ("admin", generate_password_hash("admin123")),
        )
        cur.execute(
            "INSERT INTO users (username, password_hash, role) VALUES (%s, %s, 'receptionist')",
            ("reception", generate_password_hash("reception123")),
        )
conn.commit()
conn.close()

print("Database ready.")
print("Logins -> admin/admin123, reception/reception123, dr_anjali/doctor123")
