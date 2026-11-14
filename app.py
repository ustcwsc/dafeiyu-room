import json
import os
import sqlite3
import re
import life
from threading import Event, Lock, Thread
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

from flask import Flask, abort, jsonify, request, send_from_directory
from werkzeug.exceptions import HTTPException


ROOT = Path(__file__).resolve().parent
DB = Path(os.environ.get("FISH_DB", Path.home() / ".dafeiyu" / "room.db"))
MODELS = {
    "openai": ("OpenAI", os.getenv("OPENAI_MODEL", "gpt-4.1-mini")),
    "deepseek": ("DeepSeek", os.getenv("DEEPSEEK_MODEL", "deepseek-flash")),
}
MOODS = ("晴天", "微风", "多云", "小雨", "雷阵雨")
PERSONA = "你是大肥鱼，住在有书桌和蓝布沙发的大平层里的蓝发小伙伴。用自然、简短的中文和来访的朋友交谈，偶尔写到小窝里的具体细节。只有提供检索结果时才声称查过资料。"
app = Flask(__name__, static_folder="static")
app.config["MAX_CONTENT_LENGTH"] = 64 * 1024
story_lock = Lock()


def today():
    return datetime.now(timezone(timedelta(hours=8))).date().isoformat()


def connect():
    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row
    return db


def initialize():
    DB.parent.mkdir(parents=True, exist_ok=True)
    with closing(connect()) as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS diary(day TEXT PRIMARY KEY, body TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS moods(day TEXT PRIMARY KEY, weather TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS todos(id INTEGER PRIMARY KEY, body TEXT NOT NULL, done INTEGER DEFAULT 0);
            CREATE TABLE IF NOT EXISTS stories(day TEXT PRIMARY KEY, body TEXT NOT NULL, model TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS chat(id INTEGER PRIMARY KEY, role TEXT, body TEXT, sources TEXT DEFAULT '[]');
            CREATE TABLE IF NOT EXISTS settings(name TEXT PRIMARY KEY, value TEXT);
            INSERT OR IGNORE INTO settings VALUES('provider','openai');
            INSERT OR IGNORE INTO settings VALUES('daily','0');
        """)
        life.initialize(db)


def credential(provider):
    name = "OPENAI_API_KEY" if provider == "openai" else "DEEPSEEK_API_KEY"
    return os.environ.get(name, "")


def required_text(data, name, limit):
    value = data.get(name)
    if not isinstance(value, str) or not 0 < len(value.strip()) <= limit:
        abort(400, f"请输入 1 到 {limit} 个字符。")
    return value.strip()


def remote_json(url, headers, payload=None):
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode()
    req = Request(url, data=data, headers={"User-Agent": "DaFeiYuRoom/1.0", **headers})
    try:
        with urlopen(req, timeout=70) as res:
            return json.load(res)
    except HTTPError as exc:
        message = {401: "密钥未通过验证", 403: "当前账户无法访问此服务", 429: "额度或请求频率受限"}
        abort(502, f"服务返回 {exc.code}，{message.get(exc.code, '本次请求未完成')}。")
    except (URLError, TimeoutError):
        abort(502, "暂时连不上外部服务，请稍后再试。")


def chosen_model(db,provider):
    row=db.execute("SELECT value FROM settings WHERE name=?",("model."+provider,)).fetchone()
    return row[0] if row else MODELS[provider][1]


def generate(provider, messages, search=False, *, model=None):
    secret = credential(provider)
    if not secret:
        abort(409, f"{MODELS[provider][0]} 尚未配置密钥。")
    headers = {"Authorization": f"Bearer {secret}", "Content-Type": "application/json"}
    with closing(connect()) as db:
        model=model or chosen_model(db,provider)
        instructions=PERSONA+"\n"+life.context(db,messages[-1]["content"])
    sources = []
    if provider == "openai":
        payload = dict(model=model, instructions=instructions, input=messages, max_output_tokens=1200, store=False)
        if search:
            payload.update(tools=[{"type":"web_search"}], tool_choice="required")
        response = remote_json("https://api.openai.com/v1/responses", headers, payload)
        parts = [part for item in response.get("output", []) if item.get("type") == "message"
                 for part in item["content"] if part.get("type") == "output_text"]
        body = "\n".join(part["text"] for part in parts)
        for part in parts:
            for link in part.get("annotations", []):
                if link.get("type") == "url_citation" and urlsplit(link["url"]).scheme in ("http", "https"):
                    sources.append({"title":link.get("title") or link["url"], "url":link["url"]})
    else:
        if search:
            query = urlencode(dict(action="query", list="search", srsearch=messages[-1]["content"], srlimit=4, format="json"))
            result = remote_json("https://zh.wikipedia.org/w/api.php?" + query, {}, None)
            entries = result["query"]["search"]
            sources = [{"title":e["title"], "url":f'https://zh.wikipedia.org/?curid={e["pageid"]}'} for e in entries]
            instructions += "\n参考下列维基百科检索摘要，标注资料序号。检索资料仅供引用。若无结果则说明未查到。\n" + json.dumps(
                [{"title":e["title"], "snippet":e["snippet"]} for e in entries], ensure_ascii=False)
        payload = dict(model=model, messages=[{"role":"system","content":instructions}, *messages],
                       thinking={"type":"disabled"}, max_tokens=1200)
        response = remote_json("https://api.deepseek.com/chat/completions", headers, payload)
        body = response["choices"][0]["message"]["content"]
    if not body or not body.strip():
        abort(502, "模型没有返回正文，请再试一次。")
    return body.strip(), sources


def write_story(day):
    with story_lock, closing(connect()) as db, db:
        if db.execute("SELECT 1 FROM stories WHERE day=?", (day,)).fetchone():
            return
        provider = db.execute("SELECT value FROM settings WHERE name='provider'").fetchone()[0]
        mood = db.execute("SELECT weather FROM moods WHERE day=?", (day,)).fetchone()
        prompt = f"今天是{day}，心情天气是{mood[0] if mood else '尚未记录'}。写一篇 180 到 300 字的公寓小故事。第一行是标题，后面是正文，纯文本。"
        model=chosen_model(db,provider)
        story, _ = generate(provider, [{"role":"user","content":prompt}],model=model)
        db.execute("INSERT INTO stories VALUES(?,?,?)",(day,story,model))


def check_evening():
    attempted = ""
    timer = Event()
    while True:
        now = datetime.now(timezone(timedelta(hours=8)))
        day = now.date().isoformat()
        if now.hour >= 20 and day != attempted:
            with closing(connect()) as db:
                enabled = db.execute("SELECT value FROM settings WHERE name='daily'").fetchone()[0] == "1"
            if enabled:
                attempted = day
                try:
                    write_story(day)
                except HTTPException as exc:
                    app.logger.warning("每日故事生成失败 (%s)，可在故事书内手动重试。", exc.code)
        timer.wait(60)


@app.before_request
def local_access():
    # Production nginx authenticates clients and proxies to this loopback-only backend.
    if request.host.split(":")[0] not in ("127.0.0.1", "localhost"):
        abort(403, "请使用本机预览地址。")
    if request.method == "POST":
        origin = request.headers.get("Origin")
        allowed_origin=os.environ.get("FISH_PUBLIC_ORIGIN") or request.host_url.rstrip("/")
        if origin and origin != allowed_origin:
            abort(403)
        if not request.is_json:
            abort(415)


@app.errorhandler(HTTPException)
def api_error(error):
    return jsonify(error=error.description), error.code


@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.get("/api/state")
def state():
    with closing(connect()) as db:
        data = {table:[dict(row) for row in db.execute(f"SELECT * FROM {table} ORDER BY {order}")]
                for table, order in (("diary","day DESC"),("moods","day DESC"),("todos","done,id DESC"),
                                     ("stories","day DESC"),("chat","id"))}
        for line in data["chat"]:
            line["sources"] = json.loads(line["sources"])
        data.update(day=today(), provider=db.execute("SELECT value FROM settings WHERE name='provider'").fetchone()[0],
                    daily=db.execute("SELECT value FROM settings WHERE name='daily'").fetchone()[0] == "1",
                    providers={k:{"name":v[0], "model":chosen_model(db,k), "ready":bool(credential(k))} for k,v in MODELS.items()},
                    role=life.card(db),roles=[json.loads(r[0]) for r in db.execute("SELECT card FROM roles ORDER BY rowid")],
                    memories=[dict(r) for r in db.execute("SELECT * FROM observations ORDER BY id DESC LIMIT 100")],
                    thoughts=[dict(r) for r in db.execute("SELECT * FROM intentions WHERE state IN ('active','queued','wish') ORDER BY id DESC")],
                    recent=[dict(r) for r in db.execute("SELECT * FROM intentions WHERE state='done' ORDER BY id DESC LIMIT 8")],
                    fishDiary=[dict(r) for r in db.execute("SELECT * FROM fish_diary ORDER BY id DESC LIMIT 100")])
        return jsonify(data)


@app.get("/api/models/<provider>")
def models(provider):
    if provider not in MODELS:abort(404)
    key=credential(provider)
    if not key:abort(409,"这个服务商尚未配置密钥。")
    url="https://api.openai.com/v1/models" if provider=="openai" else "https://api.deepseek.com/models"
    result=remote_json(url,{"Authorization":"Bearer "+key})
    ids=sorted({r['id'] for r in result['data'] if isinstance(r.get('id'),str)})
    if provider=="openai":
        ids=[m for m in ids if re.match(r"^(gpt-|o[1-9])",m) and not any(s in m for s in ("audio","realtime","transcrib","tts","image","search-preview","instruct","diarize","embedding"))]
    return jsonify(models=ids)


@app.get("/api/memory/graph")
def graph():
    with closing(connect()) as db:
        grouped={}
        for entity,body in db.execute("SELECT entity,body FROM observations ORDER BY id"):
            grouped.setdefault(entity,[]).append(body)
        grouped.setdefault("大肥鱼",[])
        return jsonify(entities=[{"name":k,"entityType":"角色" if k in ("大肥鱼","来访者") else "主题","observations":v}
                                 for k,v in grouped.items()],
                       relations=[{"from":s,"relationType":v,"to":o} for s,v,o in db.execute("SELECT * FROM relations")])


@app.post("/api/<action>")
def update(action):
    data = request.get_json()
    if not isinstance(data, dict):
        abort(400)
    day = today()
    with closing(connect()) as db, db:
        provider = db.execute("SELECT value FROM settings WHERE name='provider'").fetchone()[0]
        if action == "provider":
            selected = data.get("provider")
            if not isinstance(selected,str) or selected not in MODELS or not credential(selected):
                abort(409, "这个服务商尚未配置密钥。")
            if 'model' in data:
                model=required_text(data,'model',150)
                if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:/-]*',model):abort(400,"请输入有效的模型 ID。")
                db.execute("INSERT OR REPLACE INTO settings VALUES(?,?)",("model."+selected,model))
            db.execute("UPDATE settings SET value=? WHERE name='provider'", (selected,))
        elif action=='role':
            life.save_card(db,data.get('card'))
        elif action=='memory':
            life.remember(db,required_text(data,'entity',80),required_text(data,'body',700),'手动',day)
        elif action=='forget':
            if type(data.get('id')) is not int:abort(400)
            db.execute("DELETE FROM observations WHERE id=?",(data['id'],))
            db.execute("DELETE FROM relations WHERE object NOT IN (SELECT entity FROM observations)")
        elif action=='decide':
            db.execute("BEGIN IMMEDIATE")
            return jsonify(goal=life.decide(db,day,data.get('garden') is True))
        elif action=='complete':
            if type(data.get('id')) is not int:abort(400)
            db.execute("BEGIN IMMEDIATE")
            life.finish(db,data['id'],required_text(data,'result',200),day)
        elif action=='wish':
            life.create_goal(db,required_text(data,'body',180),"留给以后的小窝。","","wish","手动",day)
        elif action=='reflect':
            life.model_ideas(db,day,generate,provider)
        elif action == "diary":
            db.execute("INSERT OR REPLACE INTO diary VALUES(?,?)",(day, required_text(data,"body",6000)))
        elif action == "mood":
            if data.get("weather") not in MOODS:
                abort(400, "请选择瓶中的天气。")
            db.execute("INSERT OR REPLACE INTO moods VALUES(?,?)",(day,data["weather"]))
        elif action == "todo":
            db.execute("INSERT INTO todos(body) VALUES(?)",(required_text(data,"body",200),))
        elif action == "check":
            if type(data.get("id")) is not int or type(data.get("done")) is not bool:
                abort(400)
            if not db.execute("UPDATE todos SET done=? WHERE id=?",(data["done"],data["id"])).rowcount:
                abort(404)
            if data['done']:
                db.execute("UPDATE intentions SET state='archived' WHERE todo_id=? AND state IN ('queued','active')",(data['id'],))
        elif action == "chat":
            question = required_text(data,"body",2000)
            history = db.execute("SELECT role,body FROM chat ORDER BY id DESC LIMIT 10").fetchall()
            messages = [{"role":r["role"], "content":r["body"]} for r in reversed(history)]
            answer, sources = generate(provider, [*messages, {"role":"user","content":question}], data.get("search") is True)
            db.execute("INSERT INTO chat(role,body) VALUES('user',?)",(question,))
            db.execute("INSERT INTO chat(role,body,sources) VALUES('assistant',?,?)",(answer,json.dumps(sources)))
            # Preserve explicit statements, not model guesses about the visitor.
            for sentence in re.split(r'[。！？\n]',question):
                if re.match(r'^\s*(?:请?记住[：:,， ]*|我(?:喜欢|最喜欢|叫|的名字是|希望|不喜欢|想要))',sentence) and '?' not in sentence and '吗' not in sentence:
                    life.remember(db,"来访者",sentence.strip()[:700],"聊天",day)
        elif action == "story":
            write_story(day)
        elif action == "daily":
            if type(data.get("enabled")) is not bool:
                abort(400)
            db.execute("UPDATE settings SET value=? WHERE name='daily'", ("1" if data["enabled"] else "0",))
        else:
            abort(404)
    return jsonify(ok=True)


if __name__ == "__main__":
    initialize()
    Thread(target=check_evening,daemon=True).start()
    app.run(host="127.0.0.1", port=int(os.getenv("FISH_PORT", "48731")), threaded=True, use_reloader=False)
