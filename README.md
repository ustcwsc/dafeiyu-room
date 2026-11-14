# 大肥鱼的小窝

可以走动的三维房间，里面住着大肥鱼。打开书桌写日记，把今天的心情放进天气瓶，或者坐下来和它聊几句。

## 本地运行

使用 Python 3.10 或更新版本，在项目目录运行以下命令。

```sh
python -m pip install -r requirements.txt
python app.py
```

浏览器打开 `http://127.0.0.1:48731/`。要启用模型功能，在启动前设置 `OPENAI_API_KEY` 或 `DEEPSEEK_API_KEY`，并在界面中选择对应的提供方。日记、对话等数据默认写入用户目录下的 `.dafeiyu/room.db`，也可用 `FISH_DB` 指定位置。

## 版本与素材

本仓库保存 2026-11-14 VPS 发布的应用代码和静态资源。角色变体说明见 [VARIANTS.txt](static/pet/VARIANTS.txt)，形象和动画署名见 [CREDITS.md](static/pet/CREDITS.md)。上游模板及依赖的授权说明保存在 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
