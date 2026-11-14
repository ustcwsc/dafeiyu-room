import json
import secrets
import asyncio
import base64
import tempfile
from pathlib import Path

from aiohttp import web, ClientSession, ClientTimeout
from astrbot.api.star import Star

from .group_reply_policy import GroupReplyPolicy


class RoomBridge(Star):
    async def initialize(self):
        self.settings = json.loads(Path("data/room-bridge.json").read_text())
        self.policy = GroupReplyPolicy({
            "group_reply_mode": "adaptive",
            "group_bot_aliases": ["大肥鱼"],
            "group_interject_probability": 0,
            "group_interject_min_interval_seconds": 10,
        }, self.settings["self_id"])
        server = web.Application(client_max_size=16 * 1024)
        server.router.add_post("/message", self.message)
        server.router.add_post("/preview", self.preview)
        self.runner = web.AppRunner(server, access_log=None)
        await self.runner.setup()
        await web.TCPSite(self.runner, "0.0.0.0", 6199).start()

    async def preview(self, request):
        if not secrets.compare_digest(request.headers.get("X-Fish-Bridge-Key",""),self.settings["token"]):
            raise web.HTTPForbidden()
        from .media_preview import render_media
        owner=next(t for t in self.settings["targets"].values() if not t["is_group"])
        data=await request.json()
        name=data.get("name","")
        async with ClientSession(timeout=ClientTimeout(total=30)) as client:
            async with client.post("http://172.17.0.1:48732/api/wechat",
                                   json={"action":"asset","key":"collection/"+name,"contact":owner["id"],"is_group":False},
                                   headers={"X-Fish-Bridge-Key":self.settings["token"]}) as response:
                if response.status!=200:raise web.HTTPNotFound()
                raw=await response.read()
        with tempfile.TemporaryDirectory() as folder:
            paths,note,_=await asyncio.to_thread(render_media,raw,name.endswith(".mp4"),Path(folder))
            return web.json_response({"note":note,"images":[base64.b64encode(Path(p).read_bytes()).decode() for p in paths]})

    async def message(self, request):
        if not secrets.compare_digest(request.headers.get("X-Fish-Bridge-Key", ""), self.settings["token"]):
            raise web.HTTPForbidden()
        data = await request.json()
        target = self.settings["targets"].get(data.get("name"))
        if target is None:
            raise web.HTTPForbidden()
        action = data.get("action", "reply")
        payload = {
            "action": action,
            "contact": target["id"],
            "is_group": target["is_group"],
            "sender": data.get("sender", "群成员"),
            "body": data.get("body"),
            "event_id": data.get("event_id"),
        }
        async with ClientSession(timeout=ClientTimeout(total=95)) as client:
            url = "http://172.17.0.1:48732/api/wechat"
            headers = {"X-Fish-Bridge-Key": self.settings["token"]}
            if data.get("attachment"):
                payload["attachment"]=data["attachment"]
            if action == "reply" and target["is_group"]:
                async with client.post(url,json={**payload,"action":"group-config"},headers=headers) as response:
                    config = await response.json()
                    if response.status != 200:
                        return web.json_response(config,status=response.status)
                if "receipt" in config:
                    return web.json_response(config["receipt"])
                self.policy.probability = config["probability"]/100 if config["enabled"] else 0
                self.policy.max_per_minute = config["per_minute"]
                decision = self.policy.decide(target["id"], payload["body"], {})
                if decision.kind == "spontaneous":
                    payload["action"] = "interject"
                    payload["single_part"] = self.policy.remaining_count(target["id"]) == 1
                elif decision.kind == "silent" or decision.reason == "explicit_command":
                    payload["action"] = "observe"
            async with client.post(url,json=payload,headers=headers) as response:
                result = await response.json()
                if payload["action"] == "interject" and response.status == 200:
                    # Each nonempty component becomes a separate native WeChat send.
                    for part in ("answer","sticker"):
                        if result.get(part):
                            async with self.policy.send_slot(target["id"]) as allowed:
                                if not allowed:
                                    result[part] = ""
                return web.json_response(result, status=response.status)

    async def terminate(self):
        await self.runner.cleanup()
