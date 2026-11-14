"""The room's private image, sticker and short-video collection."""
import hashlib
import re

NAME = re.compile(r"collected_[a-f0-9]{24}\.(?:gif|png|jpe?g|webp|mp4)")
MARK = re.compile(r"\[media:([^\]\n]{1,100})\]")


def collect(db, folder, content, label):
    if content.startswith((b"GIF87a",b"GIF89a")):
        ext = ".gif"
    elif content.startswith(b"\x89PNG\r\n\x1a\n"):
        ext = ".png"
    elif content.startswith(b"\xff\xd8\xff"):
        ext = ".jpg"
    elif content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        ext = ".webp"
    elif content[4:8] == b"ftyp":
        ext = ".mp4"
    else:
        from werkzeug.exceptions import BadRequest
        raise BadRequest("收藏支持 PNG、JPEG、WebP、GIF 和 MP4。")
    name = "collected_" + hashlib.sha256(content).hexdigest()[:24] + ext
    folder.mkdir(parents=True,exist_ok=True)
    (folder/name).write_bytes(content)
    db.execute("INSERT OR IGNORE INTO collection(name,description,kind,created) VALUES(?,?,?,CURRENT_TIMESTAMP)",
               (name,label,"video" if ext==".mp4" else "sticker" if ext==".gif" else "image"))
    return name
