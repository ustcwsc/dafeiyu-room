"""Room-local adapters for character cards, graph memory and goal arbitration."""
import json
import re
from uuid import uuid4

from werkzeug.exceptions import BadRequest

DEFAULT_CARD = {
    "id":"home-fish", "name":"大肥鱼", "description":"住在海风街公寓里的蓝发少女，喜欢收集海边的小事。",
    "personality":"好奇、慢热，有一点贪玩。", "style":"用自然简短的中文，偶尔自称本鱼。",
    "behavior":"喜欢读书、观察花苗，把亲眼见到的小事写进日记。", "scenario":"海风街、菜园和自己的书桌。"
}
CARD_FIELDS = ("id","name","emoji","description","personality","scenario","first_mes","mes_example",
               "system_prompt","post_history_instructions","creator_notes","character_version","creator","style","rules","behavior")
ACTIVITIES = {
    "garden":("菜园","照料菜苗","想看看菜苗还缺什么。","花园 种植 菜园 种菜 浇水 植物"),
    "bookshop":("海风书屋","翻一本书","想带一段新故事回家。","读书 阅读 书屋 看书 小说 故事"),
    "street":("花舍","看看花店","想去看看花舍今天的颜色。","花店 看花 鲜花 散步 逛街"),
    "living":("客厅","练习接球","想活动一下，把球接稳。","玩耍 接球 游戏 运动 活泼"),
    "desk":("书桌","整理手记","想把刚经历的事记清楚。","日记 写字 写作 手记 记录"),
    "home":("卧室","歇一会儿","想回卧室安静一会儿。","休息 安静 睡觉 疲倦 慵懒")
}


def initialize(db):
    db.executescript("""
        CREATE TABLE IF NOT EXISTS roles(id TEXT PRIMARY KEY, card TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS observations(id INTEGER PRIMARY KEY, entity TEXT NOT NULL, body TEXT NOT NULL,
            source TEXT NOT NULL, day TEXT NOT NULL, UNIQUE(entity,body));
        CREATE TABLE IF NOT EXISTS relations(subject TEXT, verb TEXT, object TEXT, PRIMARY KEY(subject,verb,object));
        CREATE TABLE IF NOT EXISTS intentions(id INTEGER PRIMARY KEY, title TEXT NOT NULL, reason TEXT NOT NULL,
            place TEXT NOT NULL, state TEXT NOT NULL, source TEXT NOT NULL, day TEXT NOT NULL, todo_id INTEGER, result TEXT DEFAULT '');
        CREATE TABLE IF NOT EXISTS fish_diary(id INTEGER PRIMARY KEY,day TEXT NOT NULL,body TEXT NOT NULL,source TEXT NOT NULL, event INTEGER UNIQUE);
        CREATE UNIQUE INDEX IF NOT EXISTS one_current_intention ON intentions(state) WHERE state='active';
    """)
    if "author" not in {r[1] for r in db.execute("PRAGMA table_info(todos)")}:
        db.execute("ALTER TABLE todos ADD COLUMN author TEXT NOT NULL DEFAULT '我'")
    db.execute("INSERT OR IGNORE INTO roles VALUES(?,?)",(DEFAULT_CARD["id"],json.dumps(DEFAULT_CARD,ensure_ascii=False)))
    db.execute("INSERT OR IGNORE INTO settings VALUES('role',?)",(DEFAULT_CARD["id"],))
    db.commit()


def card(db):
    return json.loads(db.execute("SELECT card FROM roles JOIN settings ON roles.id=settings.value WHERE settings.name='role'").fetchone()[0])


def save_card(db, raw):
    if not isinstance(raw,dict) or not isinstance(raw.get("name"),str) or not raw["name"].strip():
        raise BadRequest("角色卡需要一个名字。")
    result={}
    for key in CARD_FIELDS:
        val=raw.get(key,"")
        if not isinstance(val,str) or len(val)>(100 if key in ("id","name") else 4000):
            raise BadRequest("角色卡字段长度或格式不正确。")
        if val.strip(): result[key]=val.strip()
    tags=raw.get("tags",[])
    if not isinstance(tags,list) or len(tags)>24 or any(not isinstance(t,str) or len(t)>64 for t in tags):
        raise BadRequest("角色卡标签格式不正确。")
    result["tags"]=tags
    key=result.setdefault("id",uuid4().hex)
    db.execute("INSERT OR REPLACE INTO roles VALUES(?,?)",(key,json.dumps(result,ensure_ascii=False)))
    db.execute("UPDATE settings SET value=? WHERE name='role'",(key,))


def remember(db,entity,body,source,day):
    db.execute("INSERT OR IGNORE INTO observations(entity,body,source,day) VALUES(?,?,?,?)",(entity,body,source,day))
    db.execute("INSERT OR IGNORE INTO relations VALUES('大肥鱼','记得',?)",(entity,))


def recall(db,query,limit=6):
    # Character bigrams also work on Chinese text without spaces.
    def terms(text):
        return {w.lower() for w in re.findall(r'[a-zA-Z0-9]+',text)} | {
            part[i:i+2] for part in re.findall(r'[\u3400-\u9fff]+',text) for i in range(max(1,len(part)-1))}
    keys=terms(query)
    rows=[dict(r) for r in db.execute("SELECT * FROM observations ORDER BY id DESC")]
    return sorted(rows,key=lambda r:(len(keys & terms(r["entity"]+r["body"])), r["source"]!="经历",r["id"]),reverse=True)[:limit]


def context(db,query):
    role=card(db)
    fields=[role.get(k,"") for k in ("system_prompt","name","description","personality","style","rules","behavior","scenario","mes_example","post_history_instructions")]
    current=db.execute("SELECT title,reason FROM intentions WHERE state='active'").fetchone()
    memory=[r["entity"]+" · "+r["body"] for r in recall(db,query)]
    return "\n".join(filter(None,fields))+ "\n以下是小窝的观察记录，作为背景资料：\n"+"\n".join(memory)+(
        "\n当下的心愿："+current["title"]+"，"+current["reason"] if current else "")


def create_goal(db,title,reason,place,state,source,day):
    todo=None
    if state in ("active","queued"):
        todo=db.execute("INSERT INTO todos(body,author) VALUES(?,'大肥鱼')",(title,)).lastrowid
    return db.execute("INSERT INTO intentions(title,reason,place,state,source,day,todo_id) VALUES(?,?,?,?,?,?,?)",
                      (title,reason,place,state,source,day,todo)).lastrowid


def decide(db,day,garden):
    active=db.execute("SELECT * FROM intentions WHERE state='active'").fetchone()
    if active:return dict(active)
    queued=db.execute("SELECT id FROM intentions WHERE state='queued' ORDER BY id LIMIT 1").fetchone()
    if queued:
        ident=queued[0]
        db.execute("UPDATE intentions SET state='active' WHERE id=?",(ident,))
    else:
        role=card(db)
        traits=" ".join(role.get(k,"") for k in ("personality","behavior","description"))+" "+" ".join(role.get("tags",[]))
        recent=[r[0] for r in db.execute("SELECT place FROM intentions WHERE state='done' ORDER BY id DESC LIMIT 8")]
        weather=db.execute("SELECT weather FROM moods WHERE day=?",(day,)).fetchone()
        user_todos=" ".join(r[0] for r in db.execute("SELECT body FROM todos WHERE done=0 AND author='我'"))
        memories="。".join(r[0] for r in db.execute("SELECT body FROM observations WHERE source!='经历' ORDER BY id DESC LIMIT 12"))
        aversions=re.findall(r'(?:不喜欢|不想|讨厌|避免)[^，。！？\n]{1,14}',traits+"。"+memories)
        scores={}
        for place,(_,title,reason,terms) in ACTIVITIES.items():
            keywords=terms.split()
            # Yuka's goal arbitration: per-goal desirability times the personality bias.
            bias=1+.48*sum(w in traits for w in keywords)
            score=1.1+.08*((sum(map(ord,day+place))%7))
            if any(w in memories for w in keywords): score+=1.25;reason="最近记下了相关的事，"+reason
            if any(w in user_todos for w in keywords): score+=1.55;reason="看见便签上提到了这件事，"+reason
            if place=="garden" and garden: score+=3.2;reason="菜畦里有需要照料的作物，想先去看一眼。"
            if place=="home" and weather and weather[0] in ("小雨","雷阵雨"): score+=2.0;reason="今天心情像雨天，想留点时间歇歇。"
            if place=="desk" and recent and 'desk' not in recent[:4]:score+=2
            penalty=sum(3.4/(1+i*.45) for i,p in enumerate(recent) if p==place)
            if any(w in clause for w in keywords for clause in aversions):penalty+=9
            scores[place]=(score*bias-penalty-(5 if recent[:1]==[place] else 0),title,reason)
        place=max(scores,key=lambda p:scores[p][0])
        _,title,reason=scores[place]
        ident=create_goal(db,title,reason,place,"active","本地",day)
    return dict(db.execute("SELECT * FROM intentions WHERE id=?",(ident,)).fetchone())


def finish(db,goal_id,result,day):
    item=db.execute("SELECT * FROM intentions WHERE id=? AND state='active'",(goal_id,)).fetchone()
    if not item:return
    db.execute("UPDATE intentions SET state='done',result=? WHERE id=?",(result,item["id"]))
    db.execute("UPDATE todos SET done=1 WHERE id=?",(item["todo_id"],))
    place=ACTIVITIES[item["place"]][0]
    body=f"{item['reason']} {result}" if item["place"]=="garden" else {
        "desk":"坐到书桌前，又添了几行手记。","bookshop":"我在海风书屋停了一会儿，翻了翻书。",
        "living":"今天在客厅玩了会儿抛接球。","street":"去花舍看了花，回来时还惦记着窗台。",
        "home":"回到卧室，给自己留了一会儿安静的时间。"}[item["place"]]
    if not db.execute("SELECT 1 FROM fish_diary WHERE day=? AND body=?",(day,body)).fetchone():
        db.execute("INSERT INTO fish_diary(day,body,source,event) VALUES(?,?,?,?)",(day,body,"生活记录",item["id"]))
    remember(db,place,result,"经历",day)
    # A recurring interest can yield an unrealised wish without spending tokens.
    ideas={"garden":("想给菜苗搭一座小温室","几次照料菜畦后，想让小苗也有避雨的地方。"),
           "bookshop":("想在家里办一次读书会","几次去书屋，总想和人一起读一段。"),
           "street":("想在窗台上开一个花角","看过几次花舍，想把花香带回家。"),
           "living":("想画出一片可以打球的小场地","客厅里能接球，也想试试更远的抛接。")}
    idea=ideas.get(item["place"])
    if idea:
        visits=db.execute("SELECT count(*) FROM intentions WHERE place=? AND state='done'",(item["place"],)).fetchone()[0]
        if visits>=2 and not db.execute("SELECT 1 FROM intentions WHERE state='wish' AND title=?",(idea[0],)).fetchone():
            create_goal(db,*idea,"","wish","经历",day)


def model_ideas(db,day,generate,provider):
    events=[r["body"] for r in db.execute("SELECT body FROM fish_diary WHERE day=? ORDER BY id DESC LIMIT 8",(day,))]
    prompt=("读自己的角色卡、记忆及今天实际发生的事，为自己写日记和一条可做的待办，再提出一个当前房间还做不了的愿望。"
            "无经历时写当下的期待，别编造已完成的事。只输出 JSON 对象，键为 diary,title,reason,place,wish。"
            "place 只能是 "+", ".join(ACTIVITIES)+"。每项用简短中文。\n已记录经历："+json.dumps(events,ensure_ascii=False))
    body,_=generate(provider,[{"role":"user","content":prompt}])
    try:
        item=json.loads(re.sub(r'^\x60{3}(?:json)?\s*|\s*\x60{3}$','',body.strip(),flags=re.I))
    except ValueError as exc:
        raise BadRequest("模型未返回完整的构思，没有写入记录。") from exc
    if not isinstance(item,dict) or not all(isinstance(item.get(k),str) and 0<len(item[k].strip())<=2000 for k in ("diary","title","reason","place","wish")) or item["place"] not in ACTIVITIES:
        raise BadRequest("模型返回的心愿格式不完整，没有写入记录。")
    db.execute("INSERT INTO fish_diary(day,body,source) VALUES(?,?,?)",(day,item["diary"].strip(),"模型手记"))
    create_goal(db,item["title"],item["reason"],item["place"],"queued","模型",day)
    create_goal(db,item["wish"],item["reason"],"","wish","模型",day)
