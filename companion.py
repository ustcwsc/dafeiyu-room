import os
import json
import random
import re
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

SHANGHAI = timezone(timedelta(hours=8))
MARKER = re.compile(r'\[(sticker|meme):([^\]\n]{1,120})\]')
MEDIA_ID = re.compile(r'(?:byhash/[0-9a-f]{12}|renders/[0-9a-f]{16})\.gif')
STICKER_PROMPT = ("聊天时可自行配一张大肥鱼 GIF。需要时写 [sticker:表情名或情绪]，如 [sticker:开心]。"
                  "对方指定文字做表情时可写 [meme:举牌|要写的字]，文字模板有举牌、想、葱卷、上联、下联。"
                  "每条最多一张，标记以外只写给朋友看的话。")


def decorate(answer):
    marker = MARKER.search(answer)
    if not marker:
        return answer, ""
    body = MARKER.sub("", answer).strip()
    action, ref = marker.groups()
    args = [action, *ref.split("|", 1)] if action == "meme" else [action, ref.strip()]
    if os.getenv("FISH_STICKER_KIT"):
        try:
            result = subprocess.run(
                [os.getenv("FISH_NODE", "node"), str(Path(__file__).with_name("sticker.mjs")), *args],
                capture_output=True, timeout=35, text=True, encoding="utf-8", check=True,
            )
            key = result.stdout.strip()
            if MEDIA_ID.fullmatch(key) and (Path(os.environ["FISH_STICKER_DATA"]) / key).is_file():
                return body, key
        except (OSError, subprocess.SubprocessError) as exc:
            import logging
            logging.getLogger(__name__).warning("表情未取得 (%s)", type(exc).__name__)
    return (body + "\n这张表情暂时没取到。").strip(), ""


def next_due(now):
    due = now + timedelta(minutes=random.randint(120, 360))
    if due.hour >= 23:
        due += timedelta(days=1)
    if due.hour < 9 or due.hour >= 23:
        due = due.replace(hour=9, minute=random.randrange(60), second=0, microsecond=0)
    return int(due.timestamp())


def group_interjection(db):
    return json.loads(db.execute("SELECT value FROM settings WHERE name='group_interjection'").fetchone()[0])


def initialize(db):
    db.execute("""INSERT OR IGNORE INTO settings VALUES('group_interjection', ?)""",
               (json.dumps({"enabled":True,"probability":50,"per_minute":3}),))
    db.execute("""CREATE TABLE IF NOT EXISTS companion_schedule (
        session TEXT PRIMARY KEY, mode TEXT NOT NULL, due INTEGER NOT NULL, unanswered INTEGER DEFAULT 0)""")
    now = datetime.now(SHANGHAI)
    db.execute("INSERT OR IGNORE INTO companion_schedule VALUES('owner','room',?,0)", (next_due(now),))
    group = os.getenv("FISH_WECHAT_GROUP")
    if group:
        db.execute("INSERT OR IGNORE INTO companion_schedule VALUES(?,'off',?,0)", ("wechat:"+group, next_due(now)))
    for table in ("chat", "wechat_receipts"):
        if "sticker" not in {r[1] for r in db.execute(f"PRAGMA table_info({table})")}:
            db.execute(f"ALTER TABLE {table} ADD COLUMN sticker TEXT NOT NULL DEFAULT ''")
