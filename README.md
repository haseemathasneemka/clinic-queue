# CareQueue – Live Clinic Queue & Token Management System

A full stack web app that replaces manual token calling in clinics. Patients book a token online and watch their queue position and estimated wait update live on their phone. Reception and doctors run the queue from a dashboard, and a TV screen in the waiting room shows who is being served.

## Features

- **Online booking** with a personal live-tracking page (no login needed for patients)
- **Real-time updates** with WebSockets (Flask-SocketIO): patient phones, staff dashboards and the TV display all update instantly without refreshing
- **Smart wait estimate** based on the doctor's actual average consultation time today (falls back to the last 7 days)
- **Safe token numbering**: a row-level lock (`SELECT ... FOR UPDATE`) on a daily counter guarantees two receptionists can never issue the same token number at the same moment
- **Role-based access**: admin, receptionist and doctor (doctors only control their own queue)
- **Walk-in tokens**, mark absent, recall absent patients, doctor leave handling
- **TV display mode** with a chime when the token changes
- **Analytics**: peak booking hours, daily average wait, consultation time and no-show rate per doctor (Chart.js)

## Tech stack

Python · Flask · Flask-SocketIO · MySQL (PyMySQL) · HTML/CSS · JavaScript · Chart.js

## Setup

1. Install **Python 3.10+** and **MySQL 8** (remember your MySQL root password).
2. Open this folder in VS Code and open a terminal (`Ctrl + ``).
3. Create and activate a virtual environment:
   ```bash
   python -m venv venv
   venv\Scripts\activate          # Windows
   # source venv/bin/activate     # Mac / Linux
   ```
4. Install packages:
   ```bash
   pip install -r requirements.txt
   ```
5. Copy `.env.example` to a new file named `.env` and put your MySQL password in `DB_PASSWORD`.
6. Create the database and demo logins, then add 30 days of sample history for the charts:
   ```bash
   python init_db.py
   python seed.py
   ```
7. Run the app:
   ```bash
   python app.py
   ```
8. Open http://localhost:5000

### Demo logins

| Role | Username | Password |
|---|---|---|
| Admin | admin | admin123 |
| Receptionist | reception | reception123 |
| Doctor | dr_anjali | doctor123 |

### Try the live demo

1. Open the TV display (`/display`) in one browser tab.
2. Book a token on the home page; you land on your tracking page.
3. Log in as `reception` in another window and press **Call next**.
4. Watch the tracking page and TV display update instantly.

To test on your phone, connect it to the same Wi-Fi and open `http://<your-laptop-IP>:5000` (find the IP with `ipconfig` on Windows).

## Project structure

```
app.py            Flask routes, REST APIs, WebSocket events, queue logic
config.py         Reads settings from .env
schema.sql        Database tables
init_db.py        Creates database, tables, sample doctors and logins
seed.py           Fills 30 days of fake history for analytics
templates/        HTML pages (Jinja2)
static/style.css  Styling
```

## Database design

- `doctors` – name, specialization, room, availability
- `users` – staff logins with hashed passwords and roles
- `tokens` – each token with status (`waiting → serving → done / absent`) and timestamps used for wait and consultation analytics
- `daily_counters` – one locked row per doctor per day for race-free token numbering
