"""Fills the last 30 days with realistic fake history so the analytics charts have data.
Today's queue is left empty so you can demo it live."""
import random
import secrets
from datetime import date, datetime, timedelta
import pymysql
from config import DB_CONFIG

FIRST = ["Arjun", "Meera", "Aisha", "Vishnu", "Nandana", "Rahul", "Sneha", "Fathima", "Akhil",
         "Gopika", "Ameen", "Anu", "Kiran", "Lakshmi", "Nihal", "Divya", "Hari", "Shabna", "Jithin", "Riya"]
LAST = ["Nair", "Menon", "K", "Thomas", "Pillai", "Varghese", "Rahman", "Krishnan", "Joseph", "Das"]

# Busy mornings and evenings, quiet afternoons
HOUR_WEIGHTS = {9: 10, 10: 14, 11: 12, 12: 6, 13: 3, 14: 4, 15: 5, 16: 7, 17: 11, 18: 9}

conn = pymysql.connect(**DB_CONFIG)
with conn.cursor() as cur:
    cur.execute("SELECT id FROM doctors")
    doctor_ids = [r[0] for r in cur.fetchall()]
    cur.execute("DELETE FROM tokens WHERE token_date < %s", (date.today(),))

    rows = []
    for days_ago in range(30, 0, -1):
        day = date.today() - timedelta(days=days_ago)
        if day.weekday() == 6:  # closed on Sundays
            continue
        for doc in doctor_ids:
            count = random.randint(15, 35)
            hours = random.choices(list(HOUR_WEIGHTS), weights=HOUR_WEIGHTS.values(), k=count)
            created = sorted(
                datetime(day.year, day.month, day.day, h, random.randint(0, 59)) for h in hours
            )
            doctor_free_at = created[0]
            for no, created_at in enumerate(created, start=1):
                name = f"{random.choice(FIRST)} {random.choice(LAST)}"
                phone = "9" + "".join(random.choices("0123456789", k=9))
                source = random.choice(["online", "walkin"])
                if random.random() < 0.08:
                    rows.append((secrets.token_hex(4), doc, day, no, name, phone, source,
                                 "absent", created_at, None, None))
                    continue
                called = max(created_at, doctor_free_at) + timedelta(minutes=random.randint(0, 3))
                completed = called + timedelta(minutes=random.randint(4, 14))
                doctor_free_at = completed
                rows.append((secrets.token_hex(4), doc, day, no, name, phone, source,
                             "done", created_at, called, completed))

    cur.executemany(
        """INSERT INTO tokens (public_code, doctor_id, token_date, token_no, patient_name, phone,
           source, status, created_at, called_at, completed_at)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        rows,
    )
conn.commit()
conn.close()
print(f"Inserted {len(rows)} past tokens.")
