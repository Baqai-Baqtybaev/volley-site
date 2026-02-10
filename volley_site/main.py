from flask import Flask, render_template, request, redirect, url_for, session, flash
import sqlite3
from pathlib import Path

APP_DIR = Path(__file__).parent
DB_PATH = APP_DIR / "volleyball.db"

app = Flask(__name__)
app.secret_key = "change_this_secret_key"


# ---------- DB helpers ----------
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS teams (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE,
        points INTEGER NOT NULL DEFAULT 0
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS players (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        team_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        number INTEGER NOT NULL,
        is_active INTEGER NOT NULL DEFAULT 0,
        FOREIGN KEY(team_id) REFERENCES teams(id) ON DELETE CASCADE
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS matches (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        round TEXT NOT NULL,       -- R16, QF, SF, F
        slot INTEGER NOT NULL,     -- 1..N (позиция в раунде)
        team_a_id INTEGER,
        team_b_id INTEGER,
        score_a INTEGER NOT NULL DEFAULT 0,
        score_b INTEGER NOT NULL DEFAULT 0,
        winner_id INTEGER,
        FOREIGN KEY(team_a_id) REFERENCES teams(id),
        FOREIGN KEY(team_b_id) REFERENCES teams(id),
        FOREIGN KEY(winner_id) REFERENCES teams(id),
        UNIQUE(round, slot)
    )
    """)

    conn.commit()
    conn.close()


def compute_winner(score_a, score_b, team_a_id, team_b_id):
    if team_a_id is None or team_b_id is None:
        return None
    if score_a == score_b:
        return None
    return team_a_id if score_a > score_b else team_b_id


def get_losers_map():
    """
    Возвращает dict {team_id: True} для команд, которые проиграли хотя бы один матч.
    Для показа 'Ұтылды' в дереве.
    """
    conn = get_db()
    cur = conn.cursor()
    rows = cur.execute("""
        SELECT team_a_id, team_b_id, winner_id
        FROM matches
        WHERE team_a_id IS NOT NULL AND team_b_id IS NOT NULL AND winner_id IS NOT NULL
    """).fetchall()
    conn.close()

    losers = {}
    for r in rows:
        a, b, w = r["team_a_id"], r["team_b_id"], r["winner_id"]
        if w == a:
            losers[b] = True
        elif w == b:
            losers[a] = True
    return losers


def get_round_title(round_code: str) -> str:
    return {
        "R16": "1/8 финал",
        "QF": "1/4 финал",
        "SF": "1/2 жартылай финал",
        "F": "Финал",
    }.get(round_code, round_code)


# ---------- Routes ----------
@app.before_request
def _ensure_db():
    if not DB_PATH.exists():
        init_db()


@app.get("/")
def index():
    return redirect(url_for("show"))


@app.get("/show")
def show():
    conn = get_db()
    teams = conn.execute("SELECT * FROM teams ORDER BY id ASC").fetchall()

    players_by_team = {}
    for t in teams:
        players_by_team[t["id"]] = conn.execute(
            "SELECT * FROM players WHERE team_id=? ORDER BY is_active DESC, number ASC, name ASC",
            (t["id"],)
        ).fetchall()

    # matches grouped
    rounds = ["R16", "QF", "SF", "F"]
    matches_by_round = {}
    for rc in rounds:
        matches_by_round[rc] = conn.execute("""
            SELECT m.*,
                   ta.name AS team_a_name,
                   tb.name AS team_b_name
            FROM matches m
            LEFT JOIN teams ta ON ta.id = m.team_a_id
            LEFT JOIN teams tb ON tb.id = m.team_b_id
            WHERE m.round = ?
            ORDER BY m.slot ASC
        """, (rc,)).fetchall()

    # rating table: wins*3 + points
    wins = {t["id"]: 0 for t in teams}
    match_rows = conn.execute("SELECT winner_id FROM matches WHERE winner_id IS NOT NULL").fetchall()
    for r in match_rows:
        wins[r["winner_id"]] = wins.get(r["winner_id"], 0) + 1

    standings = []
    for t in teams:
        rating = wins.get(t["id"], 0) * 3 + int(t["points"])
        standings.append({
            "id": t["id"],
            "name": t["name"],
            "points": int(t["points"]),
            "wins": wins.get(t["id"], 0),
            "rating": rating
        })
    standings.sort(key=lambda x: (x["rating"], x["wins"], x["points"]), reverse=True)

    conn.close()

    losers_map = get_losers_map()

    return render_template(
        "show.html",
        standings=standings,
        teams=teams,
        players_by_team=players_by_team,
        matches_by_round=matches_by_round,
        get_round_title=get_round_title,
        losers_map=losers_map
    )


@app.post("/login")
def login():
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "").strip()

    if username == "admin" and password == "admin1234":
        session["is_admin"] = True
        session["from_show"] = True
        return redirect(url_for("admin"))
    flash("Қате логин немесе құпиясөз!", "error")
    return redirect(url_for("show") + "#admin-login")


@app.get("/logout")
def logout():
    session.clear()
    return redirect(url_for("show"))


@app.get("/admin")
def admin():
    # только если залогинен и пришёл через show
    if not session.get("is_admin") or not session.get("from_show"):
        flash("Админ панельге кіру тек Show беті арқылы!", "error")
        return redirect(url_for("show") + "#admin-login")

    conn = get_db()
    teams = conn.execute("SELECT * FROM teams ORDER BY id ASC").fetchall()

    players_by_team = {}
    for t in teams:
        players_by_team[t["id"]] = conn.execute(
            "SELECT * FROM players WHERE team_id=? ORDER BY is_active DESC, number ASC, name ASC",
            (t["id"],)
        ).fetchall()

    rounds = ["R16", "QF", "SF", "F"]
    matches_by_round = {}
    for rc in rounds:
        matches_by_round[rc] = conn.execute("""
            SELECT m.*,
                   ta.name AS team_a_name,
                   tb.name AS team_b_name
            FROM matches m
            LEFT JOIN teams ta ON ta.id = m.team_a_id
            LEFT JOIN teams tb ON tb.id = m.team_b_id
            WHERE m.round = ?
            ORDER BY m.slot ASC
        """, (rc,)).fetchall()

    conn.close()

    return render_template(
        "admin.html",
        teams=teams,
        players_by_team=players_by_team,
        matches_by_round=matches_by_round,
        get_round_title=get_round_title
    )


# ---------- Admin actions ----------
@app.post("/admin/team/add")
def admin_team_add():
    if not session.get("is_admin"):
        return redirect(url_for("show"))
    name = request.form.get("team_name", "").strip()
    if not name:
        flash("Команда атауын енгіз!", "error")
        return redirect(url_for("admin"))
    conn = get_db()
    try:
        conn.execute("INSERT INTO teams(name, points) VALUES(?, 0)", (name,))
        conn.commit()
        flash("Команда қосылды.", "ok")
    except sqlite3.IntegrityError:
        flash("Бұл атауда команда бар.", "error")
    finally:
        conn.close()
    return redirect(url_for("admin"))


@app.post("/admin/team/points")
def admin_team_points():
    if not session.get("is_admin"):
        return redirect(url_for("show"))
    team_id = request.form.get("team_id")
    points = request.form.get("points", "0")
    try:
        p = int(points)
    except ValueError:
        p = 0

    conn = get_db()
    conn.execute("UPDATE teams SET points=? WHERE id=?", (p, team_id))
    conn.commit()
    conn.close()
    flash("Ұпай жаңартылды.", "ok")
    return redirect(url_for("admin"))


@app.post("/admin/player/add")
def admin_player_add():
    if not session.get("is_admin"):
        return redirect(url_for("show"))

    team_id = request.form.get("team_id")
    name = request.form.get("player_name", "").strip()
    number = request.form.get("player_number", "0").strip()

    if not name:
        flash("Ойыншы аты керек.", "error")
        return redirect(url_for("admin"))

    try:
        num = int(number)
    except ValueError:
        num = 0

    conn = get_db()
    count = conn.execute("SELECT COUNT(*) AS c FROM players WHERE team_id=?", (team_id,)).fetchone()["c"]
    if count >= 8:
        conn.close()
        flash("Бұл командада 8 ойыншы бар (максимум).", "error")
        return redirect(url_for("admin"))

    # авто: пока нет 6 активных — делаем активным
    active_count = conn.execute(
        "SELECT COUNT(*) AS c FROM players WHERE team_id=? AND is_active=1",
        (team_id,)
    ).fetchone()["c"]
    is_active = 1 if active_count < 6 else 0

    conn.execute(
        "INSERT INTO players(team_id, name, number, is_active) VALUES(?,?,?,?)",
        (team_id, name, num, is_active)
    )
    conn.commit()
    conn.close()
    flash("Ойыншы қосылды.", "ok")
    return redirect(url_for("admin"))


@app.post("/admin/player/toggle")
def admin_player_toggle():
    if not session.get("is_admin"):
        return redirect(url_for("show"))

    player_id = request.form.get("player_id")
    team_id = request.form.get("team_id")

    conn = get_db()
    player = conn.execute("SELECT * FROM players WHERE id=?", (player_id,)).fetchone()
    if not player:
        conn.close()
        flash("Ойыншы табылмады.", "error")
        return redirect(url_for("admin"))

    # constraints: максимум 6 active, минимум 0, при полном ростере желательно 6/2
    active_count = conn.execute(
        "SELECT COUNT(*) AS c FROM players WHERE team_id=? AND is_active=1",
        (team_id,)
    ).fetchone()["c"]

    new_state = 0 if player["is_active"] == 1 else 1
    if new_state == 1 and active_count >= 6:
        conn.close()
        flash("Алаңда максимум 6 ойыншы!", "error")
        return redirect(url_for("admin"))

    conn.execute("UPDATE players SET is_active=? WHERE id=?", (new_state, player_id))
    conn.commit()
    conn.close()
    flash("Құрам ауыстырылды.", "ok")
    return redirect(url_for("admin"))


@app.post("/admin/match/upsert")
def admin_match_upsert():
    if not session.get("is_admin"):
        return redirect(url_for("show"))

    round_code = request.form.get("round")
    slot = request.form.get("slot", "1")
    team_a_id = request.form.get("team_a_id") or None
    team_b_id = request.form.get("team_b_id") or None
    score_a = request.form.get("score_a", "0")
    score_b = request.form.get("score_b", "0")

    try:
        slot_i = int(slot)
    except ValueError:
        slot_i = 1
    try:
        sa = int(score_a)
    except ValueError:
        sa = 0
    try:
        sb = int(score_b)
    except ValueError:
        sb = 0

    # convert empty strings to None
    def to_int_or_none(x):
        if x is None:
            return None
        x = str(x).strip()
        if not x:
            return None
        try:
            return int(x)
        except ValueError:
            return None

    a_id = to_int_or_none(team_a_id)
    b_id = to_int_or_none(team_b_id)

    winner_id = compute_winner(sa, sb, a_id, b_id)

    conn = get_db()
    # upsert by (round, slot)
    existing = conn.execute("SELECT id FROM matches WHERE round=? AND slot=?", (round_code, slot_i)).fetchone()
    if existing:
        conn.execute("""
            UPDATE matches
            SET team_a_id=?, team_b_id=?, score_a=?, score_b=?, winner_id=?
            WHERE round=? AND slot=?
        """, (a_id, b_id, sa, sb, winner_id, round_code, slot_i))
    else:
        conn.execute("""
            INSERT INTO matches(round, slot, team_a_id, team_b_id, score_a, score_b, winner_id)
            VALUES(?,?,?,?,?,?,?)
        """, (round_code, slot_i, a_id, b_id, sa, sb, winner_id))

    conn.commit()
    conn.close()
    flash("Матч жаңартылды.", "ok")
    return redirect(url_for("admin"))


if __name__ == "__main__":
    # первый запуск создаст БД
    init_db()
    app.run(debug=True)
