# inventory.py
import os
import csv
import sqlite3
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "coupons.db")

DDL = """
CREATE TABLE IF NOT EXISTS inventory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    download_link TEXT NOT NULL,
    passcode TEXT,
    notes TEXT,
    assigned_to TEXT,           -- 企微 external_userid
    assigned_chat_id TEXT,      -- 群ID
    assigned_at TEXT,
    delivered INTEGER DEFAULT 0 -- 是否已成功发送给用户
);
CREATE INDEX IF NOT EXISTS idx_inventory_assigned ON inventory (assigned_to);
"""

def _conn():
    con = sqlite3.connect(DB_PATH, isolation_level=None)  # autocommit
    con.row_factory = sqlite3.Row
    return con

def init_db():
    con = _conn()
    try:
        con.executescript(DDL)
    finally:
        con.close()

def import_csv(file_path: str) -> int:
    """
    导入 CSV：必须包含 download_link 列，passcode/notes 可选
    """
    init_db()
    rows = []
    with open(file_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fields = set([c.strip() for c in (reader.fieldnames or [])])
        if "download_link" not in fields:
            raise ValueError("CSV 必须包含列: download_link")
        for r in reader:
            link = (r.get("download_link") or "").strip()
            if not link:
                continue
            passcode = (r.get("passcode") or "").strip()
            notes = (r.get("notes") or "").strip()
            rows.append((link, passcode, notes, 0))

    if not rows:
        return 0

    con = _conn()
    try:
        cur = con.cursor()
        cur.executemany(
            "INSERT INTO inventory (download_link, passcode, notes, delivered) VALUES (?, ?, ?, ?)",
            rows
        )
        return cur.rowcount or 0
    finally:
        con.close()

def assign_one(external_userid: str, chat_id: str | None):
    """
    分配一条未被占用的记录（FIFO）
    使用单条 UPDATE 竞争，避免并发重复分配
    """
    init_db()
    con = _conn()
    try:
        cur = con.cursor()
        # 选一条未分配的
        cur.execute("""
            SELECT id, download_link, passcode
            FROM inventory
            WHERE assigned_to IS NULL
            ORDER BY id ASC
            LIMIT 1
        """)
        row = cur.fetchone()
        if not row:
            return None

        now = datetime.utcnow().isoformat()
        # 仅当仍未分配时更新（避免并发抢占）
        cur.execute("""
            UPDATE inventory
            SET assigned_to = ?, assigned_chat_id = ?, assigned_at = ?
            WHERE id = ? AND assigned_to IS NULL
        """, (external_userid, chat_id, now, row["id"]))

        if cur.rowcount == 0:
            return None  # 被别的并发拿走了

        return {"id": row["id"], "download_link": row["download_link"], "passcode": row["passcode"]}
    finally:
        con.close()

def mark_delivered(inv_id: int):
    con = _conn()
    try:
        con.execute("UPDATE inventory SET delivered=1 WHERE id=?", (inv_id,))
    finally:
        con.close()

def lookup_by_id(inv_id: int):
    con = _conn()
    try:
        cur = con.cursor()
        cur.execute("SELECT * FROM inventory WHERE id=?", (inv_id,))
        return cur.fetchone()
    finally:
        con.close()

def stats():
    con = _conn()
    try:
        cur = con.cursor()
        cur.execute("SELECT COUNT(*) FROM inventory WHERE assigned_to IS NULL")
        unassigned = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM inventory WHERE assigned_to IS NOT NULL")
        assigned = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM inventory WHERE delivered=1")
        delivered = cur.fetchone()[0]
        return {"unassigned": unassigned, "assigned": assigned, "delivered": delivered}
    finally:
        con.close()
