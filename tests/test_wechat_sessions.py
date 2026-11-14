import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch
from contextlib import closing

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as room


class WechatSessions(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.previous = room.DB
        room.DB = Path(self.temp.name) / "room.db"
        with closing(sqlite3.connect(room.DB)) as db, db:
            db.execute("CREATE TABLE chat(id INTEGER PRIMARY KEY, role TEXT, body TEXT, sources TEXT DEFAULT '[]')")
            db.execute("INSERT INTO chat(role,body) VALUES('user','原网页私密历史')")
        room.initialize()
        room.initialize()
        with closing(room.connect()) as db, db:
            room.life.remember(db, "来访者", "私聊记忆暗号松子", "聊天", room.today())
            room.life.create_goal(db, room.today(), "desk", "完成私人的报告", "私密原因", "active", "手动")
            db.commit()
        self.env = patch.dict(os.environ, {
            "FISH_WECHAT_TOKEN": "test-token",
            "FISH_WECHAT_OWNER": "owner-wechat",
            "FISH_WECHAT_GROUP": "group-wechat",
            "OPENAI_API_KEY": "test-only",
        })
        self.env.start()
        self.calls = []
        def model(url, headers, payload=None):
            self.calls.append(payload)
            return {"output": [{"type": "message", "content": [{"type": "output_text", "text": "已收到。"}]}]}
        self.gateway = patch.object(room, "remote_json", side_effect=model)
        self.gateway.start()
        self.client = room.app.test_client()

    def tearDown(self):
        self.gateway.stop()
        self.env.stop()
        room.DB = self.previous
        self.temp.cleanup()

    def incoming(self, event_id, body, group=False, contact=None, token="test-token"):
        return self.client.post("/api/wechat", headers={"X-Fish-Bridge-Key": token}, json={
            "contact": contact or ("group-wechat" if group else "owner-wechat"),
            "is_group": group, "sender": "群成员" if group else "本人",
            "body": body, "event_id": event_id,
        })

    def test_owner_continues_web_history(self):
        self.assertEqual(self.incoming("1", "请记住我喜欢小熊").status_code, 200)
        prompt = str(self.calls[-1])
        self.assertIn("原网页私密历史", prompt)
        self.assertIn("私聊记忆暗号松子", prompt)
        self.assertEqual(self.client.post("/api/chat", json={"body": "接着聊"}).status_code, 200)
        self.assertIn("请记住我喜欢小熊", str(self.calls[-1]))

    def test_group_context_excludes_private_data(self):
        self.assertEqual(self.incoming("2", "大肥鱼，你在做什么？", True).status_code, 200)
        prompt = str(self.calls[-1])
        for secret in ("原网页私密历史", "私聊记忆暗号松子", "完成私人的报告", "私密原因"):
            self.assertNotIn(secret, prompt)
        self.assertIn("书桌", prompt)
        self.assertEqual(self.incoming("3", "继续", True).status_code, 200)
        self.assertIn("大肥鱼，你在做什么", str(self.calls[-1]))
        state = self.client.get("/api/state").get_json()
        self.assertNotIn("大肥鱼，你在做什么", str(state["chat"]))
        self.assertEqual(self.client.post("/api/chat", json={"body": "私聊继续"}).status_code, 200)
        self.assertNotIn("大肥鱼，你在做什么", str(self.calls[-1]))

    def test_receipt_prevents_model_repeat(self):
        self.assertEqual(self.incoming("4", "你好").get_json()["answer"], "已收到。")
        self.assertEqual(self.incoming("4", "你好").get_json()["answer"], "已收到。")
        self.assertEqual(len(self.calls), 1)

    def test_binding_and_auth(self):
        self.assertEqual(self.incoming("5", "你好", token="bad").status_code, 403)
        self.assertEqual(self.incoming("5", "你好", contact="stranger").status_code, 403)
        self.assertEqual(self.incoming("5", "你好", True, contact="other-group").status_code, 403)
        self.assertEqual(self.calls, [])

    def test_private_voice_probability(self):
        for p in (-1,101,True,0.5):
            self.assertEqual(self.client.post("/api/private-voice",json={"probability":p}).status_code,400)
        for p in (0,100):
            self.assertEqual(self.client.post("/api/private-voice",json={"probability":p}).status_code,200)
            self.assertEqual(self.client.get("/api/state").json["privateVoiceProbability"],p)
            self.assertEqual(self.incoming(str(p),"你好").json["voice"],bool(p))
            with patch.object(room,"proactive",return_value=("你好","")):
                for group,contact in [(False,"owner-wechat"),(True,"group-wechat")]:
                    res=self.client.post("/api/wechat",json={"action":"proactive","contact":contact,"is_group":group},
                                         headers={"X-Fish-Bridge-Key":"test-token"})
                    self.assertEqual(res.json.get("voice"),None if group else bool(p))
            self.assertNotIn("voice",self.incoming(str(p),"你好",group=True).json)

    def test_group_voice_request_and_retry(self):
        question="大肥鱼用语音讲一遍故事"
        self.assertTrue(self.incoming("story",question,True).json["voice"])
        self.assertIn("微信群聊",self.calls[-1]["instructions"])
        data={"action":"group-config","contact":"group-wechat","is_group":True,"event_id":"story"}
        config=self.client.post("/api/wechat",json=data,headers={"X-Fish-Bridge-Key":"test-token"}).json
        self.assertTrue(config["receipt"]["voice"])
        self.assertNotIn("voice",self.incoming("text","大肥鱼，不用语音讲",True).json)
        data.update(action="interject",body=question,sender="群成员",event_id="interject")
        self.assertNotIn("voice",self.client.post("/api/wechat",json=data,headers={"X-Fish-Bridge-Key":"test-token"}).json)

    def test_incoming_media_in_private_and_group(self):
        headers={"X-Fish-Bridge-Key":"test-token","X-Fish-Contact":"owner-wechat"}
        upload=self.client.post("/api/wechat/media",headers=headers,data=b"GIF89a-demo")
        self.assertEqual(upload.status_code,200)
        key=upload.json["name"]
        with patch.object(room,"preview_collection",return_value={"images":["demo"],"note":"测试画面"}):
            for group in (False,True):
                contact="group-wechat" if group else "owner-wechat"
                event={"action":"interject" if group else "reply","is_group":group,"contact":contact,"event_id":"m1",
                       "sender":"群友" if group else "本人","body":"图片","attachment":key}
                result=self.client.post("/api/wechat",json=event,headers=headers)
                self.assertEqual(result.status_code,200)
                self.assertEqual(self.calls[-1]["input"][-1]["content"][-1]["type"],"input_image")
        self.assertEqual(self.client.post("/api/wechat/media",data=b"GIF89a-demo").status_code,403)


if __name__ == "__main__":
    unittest.main()
