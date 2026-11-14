# 微信语音与群聊交接 · 2026-11-14

这一版支持在已绑定的微信群点名要求语音讲故事。普通群消息仍按群回复策略处理。私聊普通回复和主动问候使用小窝里设置的语音概率，显式要求语音会直接触发。

## 从源码追踪一条请求

1. `wechat-bridge/desktop_bridge.py` 读取微信会话，将消息交给 AstrBot 插件。
2. `wechat-bridge/astrbot_plugin_room_bridge/main.py` 使用 `group_reply_policy.py` 区分点名、插话和静默。「大肥鱼用语音讲一遍故事」属于点名请求。
3. `app.py` 的 `/api/wechat` 校验绑定会话、生成故事并返回 `voice`。群聊回执保存语音标志，桥接重取同一回执时仍能按语音处理。
4. 桌面桥接的 `send_voice` 使用当前音色合成；`play_voice` 核对聊天窗口，将声音送到微信录音面板。群内实际送达效果留待真实请求验证。

## 运行与验证

小窝本地启动方法见 [README.md](README.md)。微信集成需要另行配置 Linux 微信桌面、虚拟音频设备、AstrBot 和各自的绑定配置。服务端通过 `FISH_WECHAT_OWNER`、`FISH_WECHAT_GROUP` 和 `FISH_WECHAT_TOKEN` 识别调用。Fish Audio 使用 `FISH_API_KEY`，音色「自选一」「自选二」对应 `FISH_VOICE_ID_1`、`FISH_VOICE_ID_2`。配置后可在私聊发送 `/音色 自选二`。私聊概率初始值为 15%，可在小窝的模型设置中调整。

从仓库根目录运行以下命令。会话测试使用临时数据库和模拟模型响应。

```sh
python tests/test_wechat_sessions.py
node --check static/room-ui.js
```

唱歌效果优化已暂停。即兴旋律在 `wechat-bridge/singing_pitch.py` 中处理；预录清唱从部署方自己的 `floral-sea.wav` 加载。公开仓库使用内置示例角色，额外角色卡列表为空。私有会话状态、音色选择、录音和部署凭据由部署方单独维护。
