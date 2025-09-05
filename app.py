# app.py
# -*- coding: utf-8 -*-
"""
模式：KF 私聊为主 + 欢迎语兜底（欢迎语只发一次）
- 新人入群 → 创建 Pass2U → 先KF私聊发专属链接
- KF失败 → 仅在该用户该场景未发过欢迎语时，用欢迎语模板发一次固定文案
- 记录所有结果到 SQLite（bot.db）
"""

import os, json, sqlite3
from datetime import datetime
from xml.etree import ElementTree as ET
from flask import Flask, request, abort, jsonify, send_from_directory
from dotenv import load_dotenv
from wechatpy.enterprise.crypto import WeChatCrypto
from wechatpy.exceptions import InvalidSignatureException

from wecom_api import WeComAPI
from pass2u_api import create_pass2u_link, Pass2UError
try:
    from pass2u_api import create_pass2u_raw   # 若你实现了原始返回
except Exception:
    create_pass2u_raw = None  # type: ignore

# -------------------- 配置 --------------------
load_dotenv()
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__)

TOKEN = os.getenv("WECHAT_TOKEN", "")
ENCODING_AES_KEY = os.getenv("WECHAT_ENCODING_AES_KEY", "")
CORP_ID = os.getenv("WECHAT_CORP_ID", "")

PORT = int(os.getenv("PORT", "8000"))
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "http://localhost:8000")
VERIFY_FILENAME = os.getenv("WECOM_VERIFY_FILENAME", "WW_verify_example.txt")
WELCOME_TPL_ID = os.getenv("WECOM_GROUP_WELCOME_TEMPLATE_ID", "")  # 有值才会启用兜底欢迎语

crypto = WeChatCrypto(TOKEN, ENCODING_AES_KEY, CORP_ID)
api = WeComAPI()

# -------------------- DB --------------------
DB_PATH = os.path.join(BASE_DIR, "bot.db")

def db_conn():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con

def init_db():
    with db_conn() as con:
        con.execute("""
        CREATE TABLE IF NOT EXISTS assignments(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          external_userid TEXT NOT NULL,
          chat_id TEXT,
          link TEXT NOT NULL,
          notes TEXT,
          delivered INTEGER DEFAULT 0,
          created_at TEXT NOT NULL
        );
        """)
    ensure_schema()

def ensure_schema():
    """补充列 & 建幂等索引（external_userid+scene）"""
    with db_conn() as con:
        cols = {r[1] for r in con.execute("PRAGMA table_info(assignments)")}
        def add(col, typ="TEXT", default_sql=None):
            if col not in cols:
                sql = f"ALTER TABLE assignments ADD COLUMN {col} {typ}"
                if default_sql is not None:
                    sql += f" DEFAULT {default_sql}"
                con.execute(sql)

        # pass 结果
        add("scene")
        add("pass_id")
        add("model_id")
        add("barcode_message")
        add("download_url")
        add("expiration_date")
        add("created_time")
        add("raw_resp")

        # 欢迎语只发一次
        add("gw_sent", "INTEGER", 0)
        add("gw_sent_at")

        con.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS
            idx_assignments_user_scene
            ON assignments (external_userid, COALESCE(scene,''))
        """)

def log_pass_creation(external_userid: str, chat_id: str | None, scene: str,
                      download_url: str | None, resp: dict | None):
    """创建/更新一条（幂等：相同 external_userid+scene）"""
    pass_id = (resp or {}).get("passId")
    model_id = (resp or {}).get("modelId")
    barcode_message = (resp or {}).get("barcodeMessage")
    expiration_date = (resp or {}).get("expirationDate")
    created_time = (resp or {}).get("createdTime")
    raw_json = json.dumps(resp or {}, ensure_ascii=False)

    with db_conn() as con:
        con.execute("""
          INSERT INTO assignments (
            external_userid, chat_id, link, notes, delivered, created_at,
            scene, pass_id, model_id, barcode_message, download_url,
            expiration_date, created_time, raw_resp
          )
          VALUES (?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?, ?, ?, ?)
          ON CONFLICT(external_userid, scene) DO UPDATE SET
            link=excluded.link,
            pass_id=excluded.pass_id,
            model_id=excluded.model_id,
            barcode_message=excluded.barcode_message,
            download_url=excluded.download_url,
            expiration_date=excluded.expiration_date,
            created_time=excluded.created_time,
            raw_resp=excluded.raw_resp
        """, (
            external_userid, chat_id, download_url or "", "pass2u_api",
            datetime.utcnow().isoformat(),
            scene, pass_id, str(model_id or ""), barcode_message, download_url or "",
            expiration_date, created_time, raw_json
        ))

def mark_delivered_by_user_scene(external_userid: str, scene: str):
    with db_conn() as con:
        con.execute("UPDATE assignments SET delivered=1 WHERE external_userid=? AND COALESCE(scene,'')=?",
                    (external_userid, scene))

def is_welcome_sent(external_userid: str, scene: str) -> bool:
    with db_conn() as con:
        cur = con.cursor()
        cur.execute("SELECT gw_sent FROM assignments WHERE external_userid=? AND COALESCE(scene,'')=?",
                    (external_userid, scene))
        row = cur.fetchone()
        return bool(row and row[0] == 1)

def mark_welcome_sent(external_userid: str, scene: str):
    with db_conn() as con:
        con.execute("UPDATE assignments SET gw_sent=1, gw_sent_at=? WHERE external_userid=? AND COALESCE(scene,'')=?",
                    (datetime.utcnow().isoformat(), external_userid, scene))

# -------------------- 业务 --------------------
def create_pass_and_log(external_userid: str, chat_id: str, scene: str) -> str | None:
    """创建Pass；写库；返回直链（可能为None）"""
    extras = {"scene": scene, "chat_id": chat_id}

    # 若你实现了 create_pass2u_raw，优先用它拿完整返回
    if callable(create_pass2u_raw):
        try:
            resp = create_pass2u_raw(external_userid, extras)  # type: ignore
            link = resp.get("downloadUrl") or resp.get("url") or resp.get("link")
            log_pass_creation(external_userid, chat_id, scene, link, resp)
            return link
        except Exception as e:
            print("[Pass2U RAW 失败]", e)

    # 否则使用 link 版本
    try:
        link = create_pass2u_link(external_userid, extras)
        log_pass_creation(external_userid, chat_id, scene, link, None)
        return link
    except Pass2UError as e:
        print("[Pass2U API 失败]", e)
    except Exception as e:
        print("[Pass2U 未知异常]", e)

    # 即便没拿到link，也要先写一条占位记录，避免后续欢迎语重复
    log_pass_creation(external_userid, chat_id, scene, None, None)
    return None

# -------------------- 路由 --------------------
@app.get("/")
def health():
    return "OK"

# 域名校验文件（可信域名用）
@app.get(f"/{VERIFY_FILENAME}")
def wecom_domain_verify_file():
    path = os.path.join(BASE_DIR, VERIFY_FILENAME)
    if not os.path.isfile(path):
        return f"verify file not found: {path}", 404
    return send_from_directory(BASE_DIR, VERIFY_FILENAME, mimetype="text/plain")

# 管理接口（可选）
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "")
@app.get("/admin/stats")
def admin_stats():
    if ADMIN_TOKEN and request.headers.get("X-Admin-Token") != ADMIN_TOKEN:
        abort(401)
    with db_conn() as con:
        cur = con.cursor()
        cur.execute("SELECT COUNT(*) FROM assignments")
        total = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM assignments WHERE delivered=1")
        delivered = cur.fetchone()[0]
        cur.execute("""SELECT id, external_userid, scene, link, pass_id, delivered, created_at
                       FROM assignments ORDER BY id DESC LIMIT 20""")
        last20 = [dict(r) for r in cur.fetchall()]
    return jsonify({"total": total, "delivered": delivered, "undelivered": total - delivered, "last20": last20})

# --- 企业微信：GET 验证 ---
@app.get("/wecom/callback")
def wecom_verify():
    try:
        echo = crypto.check_signature(
            request.args.get("msg_signature"),
            request.args.get("timestamp"),
            request.args.get("nonce"),
            request.args.get("echostr"),
        )
        return echo
    except InvalidSignatureException:
        abort(403)

# --- 企业微信：事件回调（POST） ---
@app.post("/wecom/callback")
def wecom_events():
    try:
        msg = crypto.decrypt_message(
            request.data,
            request.args.get("msg_signature"),
            request.args.get("timestamp"),
            request.args.get("nonce"),
        )
    except InvalidSignatureException:
        abort(403)

    root = ET.fromstring(msg)
    event = root.findtext("Event")
    change_type = root.findtext("ChangeType")

    if event == "change_external_chat" and change_type == "add_member":
        chat_id = root.findtext("ChatId")
        scene = "wecom_group_join"
        eus = [n.text for n in root.findall(".//ExternalUserID") if n is not None]

        for eu in eus:
            # 1) 创建专属券 & 落库
            link = create_pass_and_log(eu, chat_id, scene)

            # 2) KF 私聊发专属链接（有无链接都可发：没有就简短文案引导）
            if link:
                text = f"欢迎加入 Cityheroes Billiards！这是你的专属卡券：\n{link}\n打开即可添加到 Wallet。"
            else:
                text = "欢迎加入 Cityheroes Billiards！请私聊我领取专属新人礼～"

            kf = api.kf_send_text(eu, text)

            if isinstance(kf, dict) and kf.get("errcode") in (0, None):
                mark_delivered_by_user_scene(eu, scene)
            else:
                # 3) KF失败 → 兜底：仅在未发过欢迎语且配置了模板ID时，发一次群欢迎语
                if WELCOME_TPL_ID and not is_welcome_sent(eu, scene):
                    gw = api.send_group_welcome(chat_id, eu)
                    if isinstance(gw, dict) and gw.get("errcode") == 0:
                        mark_welcome_sent(eu, scene)
                    else:
                        # 选填：打印“开启会话链接”，方便人工引导
                        start_url = api.kf_add_contact_url(eu, scene="pass2u")
                        print(f"[欢迎语失败] eu={eu} gw={gw} start_url={start_url}")

    return "success"

# ---- 启动 ----
if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=PORT)

