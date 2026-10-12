#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
동네가게 예약 시스템 — 데모 앱
손님용 예약 화면 + 사장님용 관리자 화면 (Flask + SQLite)
"""
import os
import re
import sqlite3
from datetime import date, datetime, timedelta

from flask import (
    Flask, g, request, redirect, url_for, render_template,
    flash, jsonify, abort, session,
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "booking.db")

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "shop-booking-demo-secret")
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024

# ----------------------------------------------------------------------------
# DB helpers
# ----------------------------------------------------------------------------

def get_db():
    if "db" not in g:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        g.db = conn
    return g.db


@app.teardown_appcontext
def close_db(exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def q(sql, args=(), one=False):
    cur = get_db().execute(sql, args)
    rows = cur.fetchall()
    cur.close()
    return (rows[0] if rows else None) if one else rows


def q1(sql, args=()):
    return q(sql, args, one=True)


def today_str():
    return date.today().isoformat()


def minutes(hhmm):
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def hhmm(total):
    return f"{total // 60:02d}:{total % 60:02d}"


PHONE_RE = re.compile(r"^01[016789]-?\d{3,4}-?\d{4}$")


def normalize_phone(raw):
    return re.sub(r"\D", "", (raw or "").strip())


def valid_phone(raw):
    return bool(PHONE_RE.match((raw or "").strip()))


# ----------------------------------------------------------------------------
# Schema + seed
# ----------------------------------------------------------------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS shops (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    phone TEXT NOT NULL DEFAULT '',
    address TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    open_time TEXT NOT NULL DEFAULT '10:00',
    close_time TEXT NOT NULL DEFAULT '20:00',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS services (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    shop_id INTEGER NOT NULL REFERENCES shops(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    duration_min INTEGER NOT NULL DEFAULT 30,
    price INTEGER NOT NULL DEFAULT 0,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS bookings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    shop_id INTEGER NOT NULL REFERENCES shops(id) ON DELETE CASCADE,
    service_id INTEGER NOT NULL REFERENCES services(id),
    book_date TEXT NOT NULL,
    start_time TEXT NOT NULL,
    end_time TEXT NOT NULL,
    customer_name TEXT NOT NULL,
    customer_phone TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    memo TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_bookings_shop_date
    ON bookings(shop_id, book_date, status);
CREATE INDEX IF NOT EXISTS idx_bookings_phone ON bookings(customer_phone);
"""

SEED_SHOPS = [
    ("단비헤어", "미용실", "02-314-7788", "서울 마포구 연남로 12, 1층",
     "동네에서 8년째 운영 중인 남성·여성 커트 전문 미용실입니다. 예약제로 운영되어 대기 없이 바로 시술받으실 수 있어요.",
     "10:00", "20:00"),
    ("네일팜", "네일샵", "02-322-9911", "서울 마포구 성미산로 45, 2층",
     "트렌디한 디자인 네일 전문샵. 1:1 예약제로 꼼꼼하게 시술해 드립니다. 첫 방문 10% 할인 중!",
     "10:00", "19:00"),
    ("든든한밥상", "맛집", "02-333-5566", "서울 마포구 동교로 88",
     "점심시간 줄 서지 마세요. 미리 예약하시면 바로 착석 가능합니다. 단체 예약(8인 이상)은 전화 문의!",
     "11:00", "21:00"),
]

SEED_SERVICES = {
    "단비헤어": [
        ("남성 커트", 40, 15000),
        ("여성 커트", 60, 25000),
        ("염색 (숏)", 120, 80000),
        ("펌 (롱)", 150, 120000),
        ("클리닉", 30, 30000),
    ],
    "네일팜": [
        ("젤네일 (한 달 유지)", 90, 55000),
        ("아트네일", 120, 75000),
        ("페디큐어", 60, 45000),
        ("네일 제거", 30, 15000),
    ],
    "든든한밥상": [
        ("점심 특선 (11:30~14:00)", 60, 12000),
        ("저녁 코스", 120, 35000),
        ("단체석 예약 (4인~)", 90, 0),
    ],
}


def seed_demo_bookings(db):
    """데모용 예약 데이터 — 오늘/이번 주/단골 고객이 보이도록 생성"""
    shops = {r["name"]: r["id"] for r in db.execute("SELECT id, name FROM shops")}
    services = {}
    for r in db.execute("SELECT id, shop_id, name, duration_min, price FROM services"):
        services.setdefault(r["shop_id"], []).append(dict(r))

    demo = [
        # (가게명, 서비스명, 날짜오프셋, 시작시각, 이름, 전화, 상태)
        ("단비헤어", "남성 커트", 0, "10:30", "김민수", "01012345678", "confirmed"),
        ("단비헤어", "여성 커트", 0, "13:00", "박지영", "01023456789", "confirmed"),
        ("단비헤어", "펌 (롱)", 0, "15:00", "이수진", "01034567890", "pending"),
        ("단비헤어", "염색 (숏)", 1, "11:00", "김민수", "01012345678", "confirmed"),  # 단골
        ("단비헤어", "클리닉", 2, "14:00", "최현우", "01045678901", "pending"),
        ("네일팜", "젤네일 (한 달 유지)", 0, "11:00", "정아름", "01056789012", "confirmed"),
        ("네일팜", "아트네일", 0, "14:00", "한소희", "01067890123", "pending"),
        ("네일팜", "페디큐어", 3, "10:30", "정아름", "01056789012", "confirmed"),  # 단골
        ("든든한밥상", "점심 특선 (11:30~14:00)", 0, "12:00", "오대식", "01078901234", "confirmed"),
        ("든든한밥상", "점심 특선 (11:30~14:00)", 0, "12:30", "강밥순", "01089012345", "pending"),
        ("든든한밥상", "저녁 코스", 1, "18:00", "송연어", "01090123456", "confirmed"),
        ("단비헤어", "남성 커트", -2, "11:00", "김민수", "01012345678", "confirmed"),  # 과거 (단골 이력)
    ]
    for shop_name, svc_name, d_off, start, name, phone, status in demo:
        sid = shops[shop_name]
        svc = next(s for s in services[sid] if s["name"] == svc_name)
        d = (date.today() + timedelta(days=d_off)).isoformat()
        end = hhmm(minutes(start) + svc["duration_min"])
        db.execute(
            """INSERT INTO bookings
               (shop_id, service_id, book_date, start_time, end_time,
                customer_name, customer_phone, status)
               VALUES (?,?,?,?,?,?,?,?)""",
            (sid, svc["id"], d, start, end, name, phone, status),
        )
    db.commit()


def init_db():
    fresh = not os.path.exists(DB_PATH)
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    db.executescript(SCHEMA)
    if fresh or db.execute("SELECT COUNT(*) FROM shops").fetchone()[0] == 0:
        for s in SEED_SHOPS:
            db.execute(
                """INSERT INTO shops
                   (name, category, phone, address, description, open_time, close_time)
                   VALUES (?,?,?,?,?,?,?)""", s,
            )
        shop_ids = {r["name"]: r["id"]
                    for r in db.execute("SELECT id, name FROM shops")}
        for shop_name, svcs in SEED_SERVICES.items():
            for name, dur, price in svcs:
                db.execute(
                    "INSERT INTO services (shop_id, name, duration_min, price) VALUES (?,?,?,?)",
                    (shop_ids[shop_name], name, dur, price),
                )
        seed_demo_bookings(db)
    db.commit()
    db.close()


init_db()

# ----------------------------------------------------------------------------
# Domain logic
# ----------------------------------------------------------------------------

STATUS_LABEL = {
    "pending": "예약대기",
    "confirmed": "확정",
    "cancelled": "취소됨",
    "noshow": "노쇼",
}


def active_bookings(shop_id, book_date):
    """해당 날짜의 유효 예약(대기/확정) 목록 — 시간순"""
    return q(
        """SELECT b.*, s.name AS service_name, s.price, s.duration_min
           FROM bookings b JOIN services s ON b.service_id = s.id
           WHERE b.shop_id = ? AND b.book_date = ?
             AND b.status IN ('pending','confirmed')
           ORDER BY b.start_time""",
        (shop_id, book_date),
    )


def overlaps(a_start, a_end, b_start, b_end):
    return a_start < b_end and b_start < a_end


def slot_available(shop_id, duration_min, book_date, start):
    """특정 시작 시각의 예약 가능 여부 (중복 방지 핵심)"""
    end = hhmm(minutes(start) + duration_min)
    for b in active_bookings(shop_id, book_date):
        if overlaps(start, end, b["start_time"], b["end_time"]):
            return False
    return True


def build_slots(shop, service, book_date):
    """예약 가능한 시간대 목록 생성 (30분 단위)"""
    open_m = minutes(shop["open_time"])
    close_m = minutes(shop["close_time"])
    dur = service["duration_min"]
    now = datetime.now()
    slots = []
    t = open_m
    while t + dur <= close_m:
        start = hhmm(t)
        end = hhmm(t + dur)
        ok = slot_available(shop["id"], dur, book_date, start)
        # 오늘 날짜는 현재 시각 +30분 이후만 노출
        if book_date == today_str():
            if t <= now.hour * 60 + now.minute + 30:
                ok = False
        slots.append({"start": start, "end": end, "available": ok})
        t += 30
    return slots


def current_shop_id():
    try:
        sid = int(request.args.get("shop_id", 1))
    except (TypeError, ValueError):
        sid = 1
    shop = q1("SELECT * FROM shops WHERE id = ?", (sid,))
    return shop["id"] if shop else q1("SELECT id FROM shops ORDER BY id LIMIT 1")["id"]


def week_range():
    d = date.today()
    mon = d - timedelta(days=d.weekday())
    return mon.isoformat(), (mon + timedelta(days=6)).isoformat()


# ----------------------------------------------------------------------------
# Error handling — traceback 절대 노출 금지
# ----------------------------------------------------------------------------

@app.errorhandler(404)
def not_found(e):
    return render_template("error.html", code=404,
                           message="요청하신 페이지를 찾을 수 없습니다."), 404


@app.errorhandler(405)
def method_not_allowed(e):
    return render_template("error.html", code=405,
                           message="잘못된 접근 방식입니다."), 405


@app.errorhandler(413)
def too_large(e):
    return render_template("error.html", code=413,
                           message="요청이 너무 큽니다."), 413


@app.errorhandler(500)
def server_error(e):
    return render_template("error.html", code=500,
                           message="일시적인 오류가 발생했습니다. 잠시 후 다시 시도해 주세요."), 500


@app.errorhandler(Exception)
def uncaught(e):
    app.logger.exception("uncaught error")
    return render_template("error.html", code=500,
                           message="일시적인 오류가 발생했습니다. 잠시 후 다시 시도해 주세요."), 500


# ============================================================================
# 손님용 화면
# ============================================================================

@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        new_industry = request.form.get("industry")
        if new_industry in INDUSTRIES:
            session["industry"] = new_industry
            session["v_price"] = INDUSTRIES[new_industry]["avg_price"]
            flash(f"{INDUSTRIES[new_industry]['icon']} "
                  f"{INDUSTRIES[new_industry]['name']} 버전으로 바뀌었어요. "
                  "메뉴와 용어가 가게에 맞게 변경됩니다.", "success")
            return redirect(url_for("index"))
    industry = current_industry()
    extra = INDUSTRIES[industry]
    shops = q("SELECT * FROM shops ORDER BY id")
    counts = {}
    for s in shops:
        counts[s["id"]] = q1(
            "SELECT COUNT(*) c FROM services WHERE shop_id=? AND is_active=1",
            (s["id"],))["c"]
    return render_template("index.html", shops=shops, counts=counts,
                           industry=extra, industries=INDUSTRIES,
                           industry_key=industry)


@app.route("/shop/<int:shop_id>")
def shop_detail(shop_id):
    shop = q1("SELECT * FROM shops WHERE id = ?", (shop_id,))
    if not shop:
        abort(404)
    services = q(
        "SELECT * FROM services WHERE shop_id=? AND is_active=1 ORDER BY price",
        (shop_id,))
    max_date = (date.today() + timedelta(days=30)).isoformat()
    return render_template("shop.html", shop=shop, services=services,
                           today=today_str(), max_date=max_date)


@app.route("/api/slots")
def api_slots():
    """예약 시간대 조회 API — 손님용 예약 폼에서 사용"""
    try:
        shop_id = int(request.args.get("shop_id", 0))
        service_id = int(request.args.get("service_id", 0))
        book_date = request.args.get("date", "")
    except (TypeError, ValueError):
        return jsonify({"ok": False, "message": "잘못된 요청입니다."}), 400

    shop = q1("SELECT * FROM shops WHERE id = ?", (shop_id,))
    svc = q1("SELECT * FROM services WHERE id = ? AND shop_id = ? AND is_active = 1",
             (service_id, shop_id))
    if not shop or not svc:
        return jsonify({"ok": False, "message": "가게 또는 서비스를 찾을 수 없습니다."}), 404
    try:
        d = datetime.strptime(book_date, "%Y-%m-%d").date()
    except ValueError:
        return jsonify({"ok": False, "message": "날짜 형식이 올바르지 않습니다."}), 400
    if book_date < today_str() or d > date.today() + timedelta(days=30):
        return jsonify({"ok": False, "message": "예약 가능한 날짜를 선택해 주세요. (오늘 ~ 30일 이내)"}), 400

    slots = build_slots(shop, svc, book_date)
    return jsonify({"ok": True, "slots": slots,
                    "open": shop["open_time"], "close": shop["close_time"]})


@app.route("/book", methods=["POST"])
def book():
    """예약 신청 — 중복/영업시간/입력 검증 후 pending 상태로 저장"""
    try:
        shop_id = int(request.form.get("shop_id", 0))
        service_id = int(request.form.get("service_id", 0))
    except (TypeError, ValueError):
        flash("잘못된 요청입니다.", "error")
        return redirect(url_for("index"))

    name = (request.form.get("name") or "").strip()
    phone_raw = (request.form.get("phone") or "").strip()
    book_date = (request.form.get("book_date") or "").strip()
    start = (request.form.get("start_time") or "").strip()
    memo = (request.form.get("memo") or "").strip()[:200]

    shop = q1("SELECT * FROM shops WHERE id = ?", (shop_id,))
    svc = q1("SELECT * FROM services WHERE id = ? AND shop_id = ? AND is_active = 1",
             (service_id, shop_id))
    back = url_for("shop_detail", shop_id=shop_id) if shop else url_for("index")

    # 입력 검증
    if not shop or not svc:
        flash("가게 또는 서비스를 찾을 수 없습니다.", "error")
        return redirect(url_for("index"))
    if not (1 <= len(name) <= 20):
        flash("이름을 1~20자로 입력해 주세요.", "error")
        return redirect(back)
    if not valid_phone(phone_raw):
        flash("연락처를 올바르게 입력해 주세요. (예: 010-1234-5678)", "error")
        return redirect(back)
    try:
        d = datetime.strptime(book_date, "%Y-%m-%d").date()
    except ValueError:
        flash("날짜를 올바르게 선택해 주세요.", "error")
        return redirect(back)
    if book_date < today_str() or d > date.today() + timedelta(days=30):
        flash("예약은 오늘부터 30일 이내 날짜만 가능합니다.", "error")
        return redirect(back)
    if not re.fullmatch(r"\d{2}:\d{2}", start):
        flash("시간을 선택해 주세요.", "error")
        return redirect(back)

    dur = svc["duration_min"]
    end = hhmm(minutes(start) + dur)
    # 영업시간 검증
    if not (shop["open_time"] <= start and end <= shop["close_time"]):
        flash(f"영업시간({shop['open_time']}~{shop['close_time']}) 내 시간을 선택해 주세요.", "error")
        return redirect(back)
    # 오늘 날짜면 지난 시간 차단
    if book_date == today_str():
        now_m = datetime.now().hour * 60 + datetime.now().minute + 30
        if minutes(start) <= now_m:
            flash("이미 지난 시간에는 예약할 수 없습니다.", "error")
            return redirect(back)

    phone = normalize_phone(phone_raw)
    db = get_db()
    try:
        # 중복 방지: 체크→저장을 하나의 트랜잭션으로 (IMMEDIATE 락)
        db.execute("BEGIN IMMEDIATE")
        clash = db.execute(
            """SELECT 1 FROM bookings
               WHERE shop_id = ? AND book_date = ?
                 AND status IN ('pending','confirmed')
                 AND start_time < ? AND ? < end_time
               LIMIT 1""",
            (shop_id, book_date, end, start)).fetchone()
        if clash:
            db.execute("ROLLBACK")
            flash("선택하신 시간대는 방금 예약이 찼습니다. 다른 시간을 선택해 주세요.", "error")
            return redirect(back)
        cur = db.execute(
            """INSERT INTO bookings
               (shop_id, service_id, book_date, start_time, end_time,
                customer_name, customer_phone, status, memo)
               VALUES (?,?,?,?,?,?,?,'pending',?)""",
            (shop_id, service_id, book_date, start, end, name, phone, memo),
        )
        booking_id = cur.lastrowid
        db.commit()
    except sqlite3.Error:
        db.execute("ROLLBACK")
        app.logger.exception("booking insert failed")
        flash("예약 처리 중 오류가 발생했습니다. 다시 시도해 주세요.", "error")
        return redirect(back)

    booking = q1(
        """SELECT b.*, s.name AS service_name, s.price
           FROM bookings b JOIN services s ON b.service_id = s.id
           WHERE b.id = ?""", (booking_id,))
    return render_template("booking_done.html", shop=shop, booking=booking)


@app.route("/my", methods=["GET", "POST"])
def my_bookings():
    """내 예약 조회 — 연락처로 조회"""
    bookings = None
    phone_input = ""
    if request.method == "POST":
        phone_input = (request.form.get("phone") or "").strip()
        if not valid_phone(phone_input):
            flash("연락처를 올바르게 입력해 주세요. (예: 010-1234-5678)", "error")
        else:
            phone = normalize_phone(phone_input)
            bookings = q(
                """SELECT b.*, s.name AS service_name, s.price, sh.name AS shop_name
                   FROM bookings b
                   JOIN services s ON b.service_id = s.id
                   JOIN shops sh ON b.shop_id = sh.id
                   WHERE b.customer_phone = ?
                   ORDER BY b.book_date DESC, b.start_time DESC""",
                (phone,))
            if not bookings:
                flash("해당 연락처로 조회된 예약이 없습니다.", "info")
    return render_template("my.html", bookings=bookings, phone_input=phone_input,
                           status_label=STATUS_LABEL)


@app.route("/my/cancel/<int:booking_id>", methods=["POST"])
def my_cancel(booking_id):
    """손님이 직접 예약 취소 — 본인 확인(연락처) 필요, 대기/확정만 가능"""
    phone = normalize_phone(request.form.get("phone", ""))
    b = q1("SELECT * FROM bookings WHERE id = ?", (booking_id,))
    if not b or b["customer_phone"] != phone:
        flash("예약 정보를 확인할 수 없습니다.", "error")
        return redirect(url_for("my_bookings"))
    if b["status"] not in ("pending", "confirmed"):
        flash("이미 처리된 예약은 취소할 수 없습니다.", "error")
        return redirect(url_for("my_bookings"))
    if b["book_date"] < today_str():
        flash("지난 예약은 취소할 수 없습니다.", "error")
        return redirect(url_for("my_bookings"))
    get_db().execute("UPDATE bookings SET status='cancelled' WHERE id = ?", (booking_id,))
    get_db().commit()
    flash(f"예약 #{booking_id}이(가) 취소되었습니다.", "success")
    return redirect(url_for("my_bookings"))


# ============================================================================
# 사장님용 관리자 화면
# ============================================================================

@app.route("/admin")
def admin_dashboard():
    sid = current_shop_id()
    shop = q1("SELECT * FROM shops WHERE id = ?", (sid,))
    shops = q("SELECT id, name FROM shops ORDER BY id")
    t = today_str()
    mon, sun = week_range()

    today_count = q1(
        "SELECT COUNT(*) c FROM bookings WHERE shop_id=? AND book_date=? "
        "AND status IN ('pending','confirmed')", (sid, t))["c"]
    week_revenue = q1(
        """SELECT COALESCE(SUM(s.price),0) total FROM bookings b
           JOIN services s ON b.service_id = s.id
           WHERE b.shop_id=? AND b.book_date BETWEEN ? AND ?
             AND b.status IN ('pending','confirmed')""",
        (sid, mon, sun))["total"]
    week_count = q1(
        "SELECT COUNT(*) c FROM bookings WHERE shop_id=? AND book_date BETWEEN ? AND ? "
        "AND status IN ('pending','confirmed')", (sid, mon, sun))["c"]
    regulars = q1(
        """SELECT COUNT(*) c FROM (
             SELECT customer_phone FROM bookings
             WHERE shop_id=? AND status != 'cancelled'
             GROUP BY customer_phone HAVING COUNT(*) >= 2)""",
        (sid,))["c"]
    pending_count = q1(
        "SELECT COUNT(*) c FROM bookings WHERE shop_id=? AND status='pending'",
        (sid,))["c"]
    noshow_count = q1(
        "SELECT COUNT(*) c FROM bookings WHERE shop_id=? AND status='noshow'",
        (sid,))["c"]

    today_list = q(
        """SELECT b.*, s.name AS service_name, s.price
           FROM bookings b JOIN services s ON b.service_id = s.id
           WHERE b.shop_id=? AND b.book_date=?
           ORDER BY b.start_time""", (sid, t))

    return render_template(
        "admin_dashboard.html", shop=shop, shops=shops, sid=sid,
        today=t, mon=mon, sun=sun,
        today_count=today_count, week_revenue=week_revenue, week_count=week_count,
        regulars=regulars, pending_count=pending_count, noshow_count=noshow_count,
        today_list=today_list, status_label=STATUS_LABEL)


@app.route("/admin/services", methods=["GET", "POST"])
def admin_services():
    sid = current_shop_id()
    shop = q1("SELECT * FROM shops WHERE id = ?", (sid,))
    shops = q("SELECT id, name FROM shops ORDER BY id")
    db = get_db()

    if request.method == "POST":
        action = request.form.get("action", "")
        if action in ("add", "edit"):
            name = (request.form.get("name") or "").strip()
            try:
                duration = int(request.form.get("duration_min", 0))
                price = int(request.form.get("price", 0))
            except (TypeError, ValueError):
                flash("소요시간과 가격은 숫자로 입력해 주세요.", "error")
                return redirect(url_for("admin_services", shop_id=sid))
            if not (1 <= len(name) <= 40):
                flash("시술명을 1~40자로 입력해 주세요.", "error")
                return redirect(url_for("admin_services", shop_id=sid))
            if not (10 <= duration <= 480) or duration % 10 != 0:
                flash("소요시간은 10~480분 사이 10분 단위로 입력해 주세요.", "error")
                return redirect(url_for("admin_services", shop_id=sid))
            if not (0 <= price <= 10000000):
                flash("가격은 0~1,000만원 사이로 입력해 주세요.", "error")
                return redirect(url_for("admin_services", shop_id=sid))
            if action == "add":
                db.execute(
                    "INSERT INTO services (shop_id, name, duration_min, price) VALUES (?,?,?,?)",
                    (sid, name, duration, price))
                flash(f"「{name}」 메뉴가 등록되었습니다.", "success")
            else:
                try:
                    svc_id = int(request.form.get("service_id", 0))
                except (TypeError, ValueError):
                    flash("잘못된 요청입니다.", "error")
                    return redirect(url_for("admin_services", shop_id=sid))
                svc = q1("SELECT * FROM services WHERE id=? AND shop_id=?", (svc_id, sid))
                if not svc:
                    flash("메뉴를 찾을 수 없습니다.", "error")
                else:
                    db.execute(
                        "UPDATE services SET name=?, duration_min=?, price=? WHERE id=?",
                        (name, duration, price, svc_id))
                    flash(f"「{name}」 메뉴가 수정되었습니다.", "success")
            db.commit()
        elif action == "toggle":
            try:
                svc_id = int(request.form.get("service_id", 0))
            except (TypeError, ValueError):
                flash("잘못된 요청입니다.", "error")
                return redirect(url_for("admin_services", shop_id=sid))
            svc = q1("SELECT * FROM services WHERE id=? AND shop_id=?", (svc_id, sid))
            if svc:
                db.execute("UPDATE services SET is_active = 1 - is_active WHERE id=?", (svc_id,))
                db.commit()
                flash(f"「{svc['name']}」 노출이 {'켜졌습니다' if not svc['is_active'] else '꺼졌습니다'}.", "success")
        elif action == "delete":
            try:
                svc_id = int(request.form.get("service_id", 0))
            except (TypeError, ValueError):
                flash("잘못된 요청입니다.", "error")
                return redirect(url_for("admin_services", shop_id=sid))
            svc = q1("SELECT * FROM services WHERE id=? AND shop_id=?", (svc_id, sid))
            if not svc:
                flash("메뉴를 찾을 수 없습니다.", "error")
            else:
                linked = q1(
                    "SELECT COUNT(*) c FROM bookings WHERE service_id=? AND status IN ('pending','confirmed')",
                    (svc_id,))["c"]
                if linked:
                    flash(f"진행 중인 예약 {linked}건이 있어 삭제할 수 없습니다. 노출 끄기를 사용해 주세요.", "error")
                else:
                    db.execute("DELETE FROM services WHERE id=?", (svc_id,))
                    db.commit()
                    flash(f"「{svc['name']}」 메뉴가 삭제되었습니다.", "success")
        return redirect(url_for("admin_services", shop_id=sid))

    services = q("SELECT * FROM services WHERE shop_id=? ORDER BY is_active DESC, price",
                 (sid,))
    edit_id = request.args.get("edit", type=int)
    edit_svc = q1("SELECT * FROM services WHERE id=? AND shop_id=?", (edit_id, sid)) if edit_id else None
    return render_template("admin_services.html", shop=shop, shops=shops, sid=sid,
                           services=services, edit_svc=edit_svc)


@app.route("/admin/bookings")
def admin_bookings():
    sid = current_shop_id()
    shop = q1("SELECT * FROM shops WHERE id = ?", (sid,))
    shops = q("SELECT id, name FROM shops ORDER BY id")
    view = request.args.get("view", today_str())
    try:
        d = datetime.strptime(view, "%Y-%m-%d").date()
    except ValueError:
        view = today_str()
        d = date.today()
    prev_day = (d - timedelta(days=1)).isoformat()
    next_day = (d + timedelta(days=1)).isoformat()

    bookings = q(
        """SELECT b.*, s.name AS service_name, s.price, s.duration_min
           FROM bookings b JOIN services s ON b.service_id = s.id
           WHERE b.shop_id=? AND b.book_date=?
           ORDER BY b.start_time""", (sid, view))

    # 시간대 그리드: 30분 단위, 해당 시간대 예약을 매핑
    open_m = minutes(shop["open_time"])
    close_m = minutes(shop["close_time"])
    grid = []
    t = open_m
    while t < close_m:
        cell_bookings = [
            b for b in bookings
            if minutes(b["start_time"]) <= t < minutes(b["end_time"])
            and b["status"] in ("pending", "confirmed")
        ]
        grid.append({"time": hhmm(t), "bookings": cell_bookings})
        t += 30

    counts = {
        st: len([b for b in bookings if b["status"] == st])
        for st in ("pending", "confirmed", "cancelled", "noshow")
    }
    return render_template(
        "admin_bookings.html", shop=shop, shops=shops, sid=sid,
        view=view, prev_day=prev_day, next_day=next_day,
        bookings=bookings, grid=grid, counts=counts,
        status_label=STATUS_LABEL, today=today_str())


@app.route("/admin/booking/<int:booking_id>/<action>", methods=["POST"])
def admin_booking_action(booking_id, action):
    """예약 상태 변경 — 확정/취소/노쇼 (사장님 전용)"""
    if action not in ("confirm", "cancel", "noshow"):
        abort(404)
    sid = int(request.form.get("shop_id", 1) or 1)
    view = request.form.get("view", today_str())
    b = q1("SELECT * FROM bookings WHERE id=?", (booking_id,))
    if not b or b["shop_id"] != sid:
        flash("예약을 찾을 수 없습니다.", "error")
        return redirect(url_for("admin_bookings", shop_id=sid, view=view))

    new_status = {"confirm": "confirmed", "cancel": "cancelled",
                  "noshow": "noshow"}[action]

    allowed = {
        "pending": ("confirmed", "cancelled"),
        "confirmed": ("cancelled", "noshow"),
        "cancelled": (),
        "noshow": (),
    }
    if new_status not in allowed.get(b["status"], ()):
        flash("이미 처리된 예약은 상태를 변경할 수 없습니다.", "error")
        return redirect(url_for("admin_bookings", shop_id=sid, view=view))

    get_db().execute("UPDATE bookings SET status=? WHERE id=?",
                     (new_status, booking_id))
    get_db().commit()
    label = {"confirmed": "확정", "cancelled": "취소", "noshow": "노쇼"}[new_status]
    flash(f"예약 #{booking_id} ({b['customer_name']}님)이 {label} 처리되었습니다.", "success")
    return redirect(url_for("admin_bookings", shop_id=sid, view=view))


# ----------------------------------------------------------------------------
# 리트로핏 — 사장님 심리/바이럴/레거시 기능 (전부 사장님 말로, 개발자 용어 금지)
# ----------------------------------------------------------------------------

INDUSTRIES = {
    "cleaning": {
        "name": "청소업체", "icon": "🧹",
        "services": [("입주청소", 180, 150000), ("정기청소", 120, 80000),
                     ("사무실청소", 150, 120000)],
        "term": "작업",
        "dignity": "오늘 {n}가정이 사장님 덕분에 깨끗해졌어요 🧹",
        "meaning": "깨끗한 집에서 시작되는 하루를 만드세요",
        "bench_text": "우리 동네 청소업체는 전화 응대로 일주일에 5시간을 씁니다",
        "fomo_count": 37, "avg_price": 120000,
    },
    "beauty": {
        "name": "미용실·네일샵", "icon": "💇",
        "services": [("커트", 40, 25000), ("펌", 120, 60000),
                     ("젤네일", 90, 55000)],
        "term": "시술",
        "dignity": "오늘 {n}분이 사장님 덕분에 예뻐지셨어요 💇",
        "meaning": "손님의 가장 빛나는 순간을 만드세요",
        "bench_text": "우리 동네 미용실은 전화 응대로 일주일에 6시간을 씁니다",
        "fomo_count": 52, "avg_price": 45000,
    },
    "moving": {
        "name": "이사·용달", "icon": "🚚",
        "services": [("포장이사", 240, 500000), ("용달이사", 120, 150000),
                     ("원룸이사", 180, 200000)],
        "term": "운송",
        "dignity": "오늘 {n}가족이 사장님 덕분에 새 출발을 했어요 🚚",
        "meaning": "새로운 시작의 첫 페이지를 함께하세요",
        "bench_text": "우리 동네 이사 업체는 전화 응대로 일주일에 7시간을 씁니다",
        "fomo_count": 21, "avg_price": 280000,
    },
}
DEFAULT_INDUSTRY = "beauty"

PRINCIPLES = [
    ("사람을 사람으로", "손님을 숫자가 아닌 사람으로 대합니다. "
     "화면에 보이는 건 예약 건수가 아니라, 사장님을 믿고 찾아온 얼굴입니다."),
    ("정직", "숫자를 부풀리지 않습니다. 잘 안 된 날은 안 됐다고, "
     "그대로 보여드립니다."),
    ("다크패턴 금지", "속이지 않고, 숨기지 않고, 몰래 켜놓지 않습니다. "
     "사장님이 모르는 사이에 돌아가는 건 없습니다."),
    ("따뜻함", "모든 문구는 사장님 말로 씁니다. 어려운 말은 쓰지 않습니다."),
    ("신뢰", "약속한 건 지킵니다. 예약 하나도 어기지 않습니다."),
    ("겸손", "잘된 건 사장님 덕분입니다. 이 화면의 좋은 숫자는 "
     "사장님이 쌓아온 신뢰의 결과입니다."),
    ("인내", "사장님의 속도에 맞춥니다. 급하게 바꾸라 하지 않고, "
     "천천히 익숙해지도록 돕습니다."),
]


def current_industry():
    key = session.get("industry", DEFAULT_INDUSTRY)
    return key if key in INDUSTRIES else DEFAULT_INDUSTRY


def daily_greeting(now=None):
    """매일 루틴 메시지 — 아침/저녁/월말"""
    now = now or datetime.now()
    if now.day >= 27:
        return "이번 달도 정말 고생 많으셨어요. 사장님 최고예요 🏆"
    if 5 <= now.hour < 12:
        return "좋은 아침이에요. 오늘도 힘내세요 😊"
    if 18 <= now.hour or now.hour < 5:
        return "오늘 하루도 수고하셨어요 🌙"
    return "바쁜 하루 보내고 계시죠? 잠깐 쉬어가세요 ☕"


def manwon(n):
    try:
        v = int(round(n))
    except (TypeError, ValueError):
        v = 0
    if v >= 100000:
        return f"{int(round(v / 10000)):,}만원"
    if v >= 10000 and v % 10000 == 0:
        return f"{v // 10000:,}만원"
    return f"{v:,}원"


def calc_value_01(calls, mins, monthly, avg_price):
    """가치 계산기 — 전화 응대 시간 절약 + 노쇼·더블부킹 방지"""
    hours_saved = calls * mins * 30 / 60
    time_money = hours_saved * 12000  # 사장님 시간 시급 환산
    saved_money = monthly * avg_price * 0.15 * 0.5  # 노쇼율 15%의 절반을 되찾는다고 가정
    return {
        "hours_saved": hours_saved,
        "time_money": time_money,
        "saved_money": saved_money,
        "total": time_money + saved_money,
    }


def shop_month_stats(sid, month):
    row = q1(
        """SELECT COUNT(*) total,
                  SUM(CASE WHEN b.status='noshow' THEN 1 ELSE 0 END) ns,
                  COALESCE(SUM(CASE WHEN b.status IN ('pending','confirmed')
                                   THEN s.price ELSE 0 END),0) revenue,
                  COUNT(DISTINCT CASE WHEN b.status IN ('pending','confirmed')
                                      THEN b.customer_phone END) people
           FROM bookings b JOIN services s ON b.service_id = s.id
           WHERE b.shop_id=? AND substr(b.book_date,1,7)=?""",
        (sid, month))
    total = row["total"] or 0
    ns = row["ns"] or 0
    return {"total": total, "noshow": ns, "revenue": row["revenue"] or 0,
            "people": row["people"] or 0,
            "rate": (ns / total * 100) if total else 0}


# ----------------------------------------------------------------------------
# 사장님 오늘 브리핑 — 도파민 대시보드
# ----------------------------------------------------------------------------
@app.route("/briefing")
def briefing():
    sid = current_shop_id()
    shop = q1("SELECT * FROM shops WHERE id = ?", (sid,))
    shops = q("SELECT id, name FROM shops ORDER BY id")
    industry = current_industry()
    extra = INDUSTRIES[industry]
    t = today_str()
    mon, sun = week_range()

    counts = {}
    for st in ("pending", "confirmed", "cancelled", "noshow"):
        counts[st] = q1(
            "SELECT COUNT(*) c FROM bookings WHERE shop_id=? AND book_date=? "
            "AND status=?", (sid, t, st))["c"]
    week_revenue = q1(
        """SELECT COALESCE(SUM(s.price),0) total FROM bookings b
           JOIN services s ON b.service_id = s.id
           WHERE b.shop_id=? AND b.book_date BETWEEN ? AND ?
             AND b.status IN ('pending','confirmed')""",
        (sid, mon, sun))["total"]
    month = t[:7]
    ms = shop_month_stats(sid, month)

    people = q1(
        "SELECT COUNT(DISTINCT customer_phone) c FROM bookings "
        "WHERE shop_id=? AND book_date=? AND status IN ('pending','confirmed')",
        (sid, t))["c"] or 0

    fresh = q1(
        "SELECT COUNT(*) c FROM bookings WHERE shop_id=? AND status='pending' "
        "AND substr(created_at,1,10)=?", (sid, t))["c"] or 0

    today_list = q(
        """SELECT b.*, s.name AS service_name, s.price
           FROM bookings b JOIN services s ON b.service_id = s.id
           WHERE b.shop_id=? AND b.book_date=?
           ORDER BY b.start_time""", (sid, t))

    return render_template(
        "briefing.html", shop=shop, shops=shops, sid=sid,
        greeting=daily_greeting(), counts=counts, today=t,
        week_revenue=week_revenue, mon=mon, sun=sun, month=month, ms=ms,
        dignity=extra["dignity"].format(n=people), people=people,
        fresh=fresh, today_list=today_list, status_label=STATUS_LABEL,
        industry=extra, bench_text=extra["bench_text"], manwon=manwon)


# ----------------------------------------------------------------------------
# 가치 계산기 + 경쟁사 비교 + ROI
# ----------------------------------------------------------------------------
@app.route("/value", methods=["GET", "POST"])
def value():
    industry = current_industry()
    extra = INDUSTRIES[industry]
    calls = int(session.get("v_calls", 20))
    mins = int(session.get("v_mins", 3))
    monthly = int(session.get("v_monthly", 200))
    avg_price = int(session.get("v_price", extra["avg_price"]))
    if request.method == "POST":
        try:
            calls = max(0, int(request.form.get("calls", calls)))
            mins = max(0, int(request.form.get("mins", mins)))
            monthly = max(0, int(request.form.get("monthly", monthly)))
            avg_price = max(0, int(request.form.get("avg_price", avg_price)))
        except (TypeError, ValueError):
            flash("숫자만 입력해 주세요.", "error")
        session["v_calls"] = calls
        session["v_mins"] = mins
        session["v_monthly"] = monthly
        session["v_price"] = avg_price
    calc = calc_value_01(calls, mins, monthly, avg_price)
    return render_template(
        "value.html", calls=calls, mins=mins, monthly=monthly,
        avg_price=avg_price, calc=calc, roi_fee=30000,
        industry=extra, manwon=manwon)


# ----------------------------------------------------------------------------
# 월간 리포트 — 단톡방 공유
# ----------------------------------------------------------------------------
@app.route("/report")
def report():
    sid = current_shop_id()
    shop = q1("SELECT * FROM shops WHERE id = ?", (sid,))
    shops = q("SELECT id, name FROM shops ORDER BY id")
    industry = current_industry()
    extra = INDUSTRIES[industry]
    t = today_str()
    month = t[:7]
    ms = shop_month_stats(sid, month)
    share_text = (
        f"[{shop['name']} {int(month[5:])}월 리포트]\n"
        f"• 예약 {ms['total']}건 중 노쇼 {ms['noshow']}건 "
        f"(노쇼율 {ms['rate']:.1f}%)\n"
        f"• 이번 달 찾아온 손님 {ms['people']}명\n"
        f"• 예약으로 들어올 돈: {manwon(ms['revenue'])}\n"
        f"— 동네가게 예약 월간 리포트"
    )
    return render_template(
        "report.html", shop=shop, shops=shops, sid=sid, month=month, ms=ms,
        share_text=share_text, industry=extra, manwon=manwon)


# ----------------------------------------------------------------------------
# 성장 — 추천 리워드 + FOMO + 성장 시뮬레이터
# ----------------------------------------------------------------------------
@app.route("/growth")
def growth():
    industry = current_industry()
    extra = INDUSTRIES[industry]
    monthly = int(session.get("v_monthly", 200))
    avg_price = int(session.get("v_price", extra["avg_price"]))
    gain_month = calc_value_01(20, 3, monthly, avg_price)["total"]
    referral_text = (
        f"옆 가게 사장님, 전화 받느라 일 끊기셨죠?\n"
        f"저는 '동네가게 예약' 쓰면서 한 달에 {manwon(gain_month)}를 아끼고 있어요.\n"
        f"제 소개로 시작하면 우리 둘 다 1개월 무료래요. 한번 써보세요 😊\n"
        f"— {get_setting_shop_name()} 사장님"
    )
    return render_template(
        "growth.html", industry=extra, gain_month=gain_month,
        referral_text=referral_text, manwon=manwon)


def get_setting_shop_name():
    return "우리 가게"


# ----------------------------------------------------------------------------
# 소개 — 레거시 철학 + 일곱 가지 약속 + 사명
# ----------------------------------------------------------------------------
@app.route("/about")
def about():
    industry = current_industry()
    extra = INDUSTRIES[industry]
    return render_template(
        "about.html", principles=PRINCIPLES, industry=extra)


# ----------------------------------------------------------------------------
# 입소문 배지
# ----------------------------------------------------------------------------
@app.route("/badge")
def badge():
    sid = current_shop_id()
    shop = q1("SELECT * FROM shops WHERE id = ?", (sid,))
    snippet = (
        '<a href="#" style="display:inline-block;background:#fff4e6;color:#d9480f;'
        'font-weight:800;padding:10px 18px;border-radius:999px;'
        'text-decoration:none;font-size:14px;">'
        f"📅 이 가게는 동네가게 예약 시스템을 사용합니다 — {shop['name']}</a>"
    )
    return render_template("badge.html", snippet=snippet, shop=shop)


# ----------------------------------------------------------------------------
if __name__ == "__main__":
    import os
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5001)), debug=False)
