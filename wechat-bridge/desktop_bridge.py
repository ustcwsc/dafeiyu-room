"""Message transport through the logged-in WeChat desktop's visible UI."""
import hashlib
import io
import json
import logging
import re
import subprocess
import sys
import time
import uuid
import wave
import tempfile
from contextlib import closing
from difflib import SequenceMatcher
from pathlib import Path
from typing import NamedTuple
from urllib.request import Request, urlopen
from urllib.error import URLError
from urllib.parse import unquote, urlsplit

import cv2
import mss
import numpy as np
from PIL import Image, ImageGrab, PngImagePlugin
from rapidocr import RapidOCR
from Xlib.display import Display


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
ROOT = Path("/config/room-bridge")
SETTINGS = json.loads((ROOT / "settings.json").read_text())
STATE = ROOT / "state.json"
ocr = RapidOCR(params={
    "EngineConfig.onnxruntime.intra_op_num_threads": 1,
    "EngineConfig.onnxruntime.inter_op_num_threads": 1,
})


def key(*args):
    subprocess.run(["xdotool", *map(str, args)], check=True)


def clipboard(text):
    subprocess.run(["xclip", "-selection", "clipboard"], input=text.encode(), check=True)


def title():
    result = ocr(np.array(ImageGrab.grab().crop((305, 35, 830, 80))))
    text = " ".join(result.txts or [])
    return re.sub(r"\s*[（(]\d+[)）]\s*$", "", text).strip()


def select(name):
    # Select the existing chat from the conversation list and recheck its header.
    windows=subprocess.check_output(["wmctrl","-lG"]).decode().splitlines()
    main=next((fields for line in windows if len(fields:=line.split(None,7))==8
               and fields[7]=="微信" and int(fields[4])>=700),None)
    if not main:
        raise RuntimeError("WeChat login or main window required")
    if tuple(map(int,main[2:6]))!=(0,0,1008,840):
        subprocess.run(["wmctrl","-ir",main[0],"-e","0,0,0,1008,840"],check=True)
        time.sleep(0.4)
    key("windowactivate", main[0])
    time.sleep(0.15)
    if title() == name:
        return
    rows = ocr(np.array(ImageGrab.grab().crop((112,80,265,810))))
    for text, box in zip(rows.txts or [], rows.boxes if rows.boxes is not None else []):
        cy = int(np.mean(box[:,1]))
        if text.strip() == name and cy % 65 < 38:
            key("mousemove", 150, 80+cy, "click", 1)
            time.sleep(0.35)
            break
    else:
        raise RuntimeError("Target is not visible in the conversation list")
    if title() != name:
        raise RuntimeError("Chat header does not match the selected target")


def copy_message(px, py, media):
    clipboard("")
    key("mousemove",px,py,"click",3)
    time.sleep(0.15)
    # Inspect the actual Qt popup, which can open above or to the left of the click.
    with closing(Display()) as display:
        root=display.screen().root
        menu=root.query_pointer().child
        if not menu or "wechat" not in (menu.get_wm_class() or ()):
            key("mousemove",730,51,"click",1)
            return None
        geometry=menu.get_geometry()
        if not 80<=geometry.width<=320 or geometry.height<35:
            key("mousemove",730,51,"click",1)
            return None
        origin=root.translate_coords(menu,0,0)
    x,y=origin.x,origin.y
    if media:
        result=ocr(np.array(ImageGrab.grab().crop((x,y,x+geometry.width,y+geometry.height))))
        items=zip(result.txts or [], result.boxes if result.boxes is not None else [])
        button=next((np.mean(box,axis=0) for label,box in items if label.strip().endswith(("复制","复制图片","复制表情"))),None)
        if button is None:
            key("key","Escape")
            return None
        key("mousemove",x+int(button[0]),y+int(button[1]),"click",1)
    else:
        key("key","Down","Return")
    time.sleep(0.15)
    command=["xclip","-selection","clipboard","-o"]
    if not media:
        return subprocess.run(command,capture_output=True,timeout=5).stdout.decode(errors="replace").strip()
    targets=subprocess.run(command+["-t","TARGETS"],capture_output=True,timeout=5).stdout.splitlines()
    if b"text/uri-list" in targets:
        uris=subprocess.run(command+["-t","text/uri-list"],capture_output=True,timeout=5).stdout.decode(errors="replace")
        for uri in uris.splitlines():
            parsed=urlsplit(uri)
            if parsed.scheme!="file" or parsed.netloc not in ("","localhost"):
                continue
            path=Path(unquote(parsed.path)).resolve()
            if path.is_relative_to("/config/xwechat_files") and path.is_file() and path.stat().st_size<=20*1024*1024:
                data=path.read_bytes()
                if data[4:8]==b"ftyp" or data.startswith((b"GIF87a",b"GIF89a",b"\x89PNG\r\n\x1a\n",b"\xff\xd8\xff")) or (data[:4]==b"RIFF" and data[8:12]==b"WEBP"):
                    return data
    bitmap=None
    for mime in (b"image/gif",b"image/webp",b"image/png",b"image/jpeg"):
        if mime in targets:
            data=subprocess.run(command+["-t",mime.decode()],capture_output=True,timeout=5).stdout
            if data and len(data)<=20*1024*1024:
                with Image.open(io.BytesIO(data)) as image:
                    if getattr(image,"n_frames",1)>1:
                        return data
                # A bitmap offered by Qt may be a flattened animation.
                if bitmap is None or mime==b"image/png":
                    bitmap=data
                if mime==b"image/png":
                    break
    return ClipboardStill(bitmap) if bitmap else None


class ClipboardStill(NamedTuple):
    data: bytes


class ScreenSticker(NamedTuple):
    box: tuple
    avatar_top: int
    avatar: bytes
    still: bytes | None


class VideoBubble(NamedTuple):
    box: tuple
    cover: Image.Image


def read_video(bubble):
    left,top,right,bottom=bubble.box
    width,height=bubble.cover.size
    sample=np.asarray(bubble.cover.resize((48,48))).astype("int16")
    # Ignore the central play button, the lower duration badge and the rounded corners.
    mask=np.ones((48,48),dtype=bool)
    mask[:2]=mask[-7:]=False
    mask[:,:2]=mask[:,-2:]=False
    mask[15:33,15:33]=False
    matches=[]
    for path in Path("/config/xwechat_files").glob("*/msg/video/**/*_thumb.jpg"):
        with Image.open(path) as im:
            if abs(im.width/im.height*height/width-1)>.045:
                continue
            thumb=np.asarray(im.convert("RGB").resize((48,48)))
        error=np.abs(sample[mask]-thumb[mask]).mean()
        if error<9:
            matches.append((error,path.with_name(path.name.removesuffix("_thumb.jpg")+".mp4")))
    matches.sort()
    if not matches or (len(matches)>1 and matches[1][0]-matches[0][0]<2):
        return None,"发来一个小视频。当前无法从封面确定对应的正片。"
    path=matches[0][1]
    if not path.is_file():
        key("mousemove",(left+right)//2,(top+bottom)//2,"click",1)
    for _ in range(40):
        if path.is_file():
            if path.stat().st_size>20*1024*1024:
                return None,"发来一个小视频。正片超过当前 20 MiB 的接收上限。"
            # A file can appear before WeChat has finished writing its media data.
            probe=subprocess.run(["ffprobe","-v","error","-select_streams","v:0","-show_entries",
                                  "stream=codec_type","-of","csv=p=0",str(path)],capture_output=True,timeout=5)
            if probe.stdout.strip()==b"video":
                return path.read_bytes(),"发来一个小视频。"
        time.sleep(.5)
    return None,"发来一个小视频。微信还未提供可读取的正片。"


def observed_cycle(sequence):
    """Find two successive passes, allowing frames the desktop didn't paint."""
    # The first observed frame may already be ending when the chat is opened.
    for start in range(min(6,len(sequence))):
        marks=[i for i in range(start,len(sequence)) if sequence[i]==sequence[start]]
        for middle,end in zip(marks[1:],marks[2:]):
            first,second=sequence[start:middle],sequence[middle:end]
            if abs(len(first)-len(second))>max(1,len(first)*.08):
                continue
            cycle=first if len(first)>=len(second) else second
            if len(cycle)<2 or not set(sequence).issubset(cycle):
                continue
            if SequenceMatcher(None,first,second,autojunk=False).ratio()>=.94:
                return (start,middle) if cycle is first else (middle,end)
    return None


def capture_playback(sticker):
    left,top,right,bottom=sticker.box
    grab_top=min(top,sticker.avatar_top)
    region=(325,grab_top,right,max(bottom,sticker.avatar_top+24))
    frames={}
    sequence=[]
    times=[]
    cycle=None
    key("mousemove",730,51)
    with mss.mss() as display:
        started=time.monotonic()
        next_check=12.0
        while True:
            shot=np.asarray(display.grab(region))
            anchor=shot[sticker.avatar_top-grab_top:sticker.avatar_top-grab_top+24,:23,2::-1]
            if anchor.tobytes()!=sticker.avatar:
                raise RuntimeError("Sticker row moved during playback")
            elapsed=time.monotonic()-started
            pixels=shot[top-grab_top:bottom-grab_top,left-325:,2::-1].tobytes()
            digest=hashlib.blake2s(pixels,digest_size=16).digest()
            if not sequence or sequence[-1]!=digest:
                if digest not in frames:
                    frame=Image.frombytes("RGB",(right-left,bottom-top),pixels)
                    buf=io.BytesIO()
                    frame.save(buf,"PNG",compress_level=1)
                    frames[digest]=buf.getvalue()
                sequence.append(digest)
                times.append(elapsed)
            if elapsed>=next_check:
                cycle=observed_cycle(sequence)
                if cycle or len(sequence)==1 or elapsed>=30:
                    break
                next_check+=3
            time.sleep(.012)
    if len(sequence)==1:
        return sticker.still or frames[sequence[0]],"发来一张表情或图片。观察聊天窗口 12 秒，画面未发生变化。"
    start,end=cycle or (0,len(sequence))
    times.append(elapsed)
    count=end-start
    positions=[start+round(i*(count-1)/(min(120,count)-1)) for i in range(min(120,count))]
    images=[Image.open(io.BytesIO(frames[sequence[i]])).convert("RGB") for i in positions]
    durations=[max(1,round(1000*(times[j]-times[i]))) for i,j in zip(positions,positions[1:]+[end])]
    out=io.BytesIO()
    metadata=PngImagePlugin.PngInfo()
    metadata.add_text("room.wechat.playback","cycle" if cycle else "window")
    images[0].save(out,"PNG",save_all=True,append_images=images[1:],duration=durations,loop=0,pnginfo=metadata)
    coverage=("观察到重复播放，取其中一轮；起点可能在原动画中途。" if cycle else
              f"连续观察了 {elapsed:.1f} 秒，未确认循环，只描述这段时间看到的动作。")
    note=(f"发来一个动态表情。以下来自微信聊天窗口的连续播放画面。{coverage}"
          f"这段播放中观察到 {count} 个画面，按时间顺序保留 {len(positions)} 个；时长为屏幕观测值。")
    return out.getvalue(),note


def read_visible(group):
    screen = ImageGrab.grab()
    area = np.array(screen.crop((305,92,941,695)))
    mask = (np.max(np.abs(area.astype("int16")-250),axis=2)>7).astype("uint8")*255
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    boxes = [cv2.boundingRect(c) for c in contours]
    # Left-hand avatars anchor incoming rows, including images without a text bubble.
    avatars=sorted(y for x,y,w,h in boxes if 14<=x<=18 and 33<=w<=38 and 30<=h<=38)
    messages = []
    files={}
    previous_video_ids={}
    for avatar in avatars:
        top=avatar+(23 if group else 0)
        candidates=[b for b in boxes if 58<=b[0]<=77 and top-2<=b[1]<=top+12 and b[2]>=20 and b[3]>=22]
        if not candidates:
            continue
        x,y,width,height=max(candidates,key=lambda b:b[2]*b[3])
        px,py=x+305,y+92
        # The tail of a left text bubble starts at x=366; media is inset to x=371.
        media=x>=65
        sender = "本人"
        if group:
            result = ocr(np.array(screen.crop((px, max(82, py - 27), px + 240, py))))
            sender = " ".join(result.txts or []) or "群成员"
        value=copy_message(px+min(width//2,30),py+min(height//2,25),media)
        if not media:
            if value:messages.append({"sender":sender,"body":value})
            continue
        box=(px,py,px+width,py+height)
        avatar_rgb=screen.crop((325,avatar+97,348,avatar+121)).convert("RGB").tobytes()
        legacy_id=hashlib.sha256(avatar_rgb+bytes(str((width,height)),"ascii")).hexdigest()
        if isinstance(value,bytes) and value[4:8]!=b"ftyp":
            body="发来一张图片或表情。"
            fingerprint=hashlib.sha256(value).hexdigest()
        else:
            direct_video=isinstance(value,bytes)
            badge=screen.crop((px+width//2,py+max(0,height-34),px+width,py+height))
            if direct_video or any(re.fullmatch(r"\s*\d{1,3}[:：]\d{2}\s*",label) for label in ocr(np.asarray(badge)).txts or []):
                body="发来一个小视频。"
                cover=screen.crop(box).convert("RGB")
                fingerprint="video-"+hashlib.sha256(cover.resize((32,32)).tobytes()).hexdigest()
                previous_video_ids[len(messages)]=legacy_id
                if not direct_video:
                    value=VideoBubble(box,cover)
            else:
                body="发来一张表情或图片。"
                fingerprint=legacy_id
                value=ScreenSticker(box,avatar+97,avatar_rgb,value.data if value else None)
        item={"sender":sender,"body":body,"media":fingerprint}
        messages.append(item)
        files[len(messages)-1]=value
    return messages,files,previous_video_ids


def recording():
    panel=np.array(ImageGrab.grab().crop((950,790,987,826))).astype("int16")
    return ((panel[:,:,1]>panel[:,:,0]+70)&(panel[:,:,1]>panel[:,:,2]+28)).sum()>100


def send_voice(name,answer,voice,sing=False):
    target=SETTINGS["targets"][name]
    req=Request("http://172.17.0.1:48732/api/wechat",data=json.dumps({
        "action":"speech","body":answer,"contact":target["id"],"is_group":target["is_group"],"voice":voice}).encode(),
        headers={"Content-Type":"application/json","X-Fish-Bridge-Key":SETTINGS["token"]})
    with urlopen(req,timeout=60) as res:
        audio=res.read()
    with tempfile.TemporaryDirectory() as temp:
        source=Path(temp)/"source.wav"
        # Streaming WAV responses can declare 0xffffffff bytes. Write a sized
        # PCM file before Praat allocates space from its header.
        with wave.open(io.BytesIO(audio),"rb") as incoming, wave.open(str(source),"wb") as out:
            pcm=incoming.readframes(incoming.getnframes())
            if not pcm:
                raise ValueError("Speech service returned empty audio")
            out.setparams(incoming.getparams())
            out.setnframes(len(pcm)//(incoming.getsampwidth()*incoming.getnchannels()))
            out.writeframes(pcm)
        if sing:
            lib=str(ROOT/"voice-lib")
            if lib not in sys.path:
                sys.path.append(lib)
            from parselmouth import Sound
            from parselmouth.praat import call
            sound=Sound(str(source))
            manipulation=call(sound,"To Manipulation",.01,65,650)
            from singing_pitch import guide_pitch
            melody=(0,4,7,9,7,4,2,0,2,5,9,7,4,2,0,0)
            starts=np.arange(0,sound.duration,.48)
            guide_pitch(sound,manipulation,starts,220*2**(np.resize(melody,len(starts))/12))
            call(manipulation,"Get resynthesis (overlap-add)").save(str(source),"WAV")
        with wave.open(str(source),"rb") as wav:
            play_voice(wav,temp,name)


def play_voice(wav,temp,name):
    path=Path(temp)/"voice.wav"
    while chunk:=wav.readframes(48*wav.getframerate()):
        with wave.open(str(path),"wb") as part:
            part.setparams(wav.getparams())
            part.setnframes(len(chunk)//(wav.getsampwidth()*wav.getnchannels()))
            part.writeframes(chunk)
        if title()!=name or recording():
            raise RuntimeError("Unexpected WeChat recording panel")
        key("mousemove",915,808,"click",1)
        time.sleep(.4)
        if not recording():
            raise RuntimeError("WeChat did not open recorder")
        try:
            subprocess.run(["paplay","--device=input",str(path)],check=True,timeout=53)
            time.sleep(.2)
            if title()!=name or not recording():
                raise RuntimeError("WeChat recording interrupted")
            key("mousemove",968,805,"click",1)
            time.sleep(.5)
        finally:
            if recording():
                key("mousemove",767,805,"click",1)


def send(name, answer, sticker="", *, voice=None,sing=False):
    if title() != name:
        raise RuntimeError("Chat changed before delivery")
    if answer and voice:
        try:
            send_voice(name,answer,voice,sing)
            answer=""
        except (URLError,TimeoutError,RuntimeError,ValueError,subprocess.SubprocessError,wave.Error) as exc:
            logging.error("voice delivery failed: %s",type(exc).__name__)
            if title()!=name:
                raise RuntimeError("Chat changed before text fallback")
    if answer:
        key("mousemove", 410, 739, "click", 1)
        key("key", "ctrl+a")
        clipboard(answer)
        key("key", "ctrl+v")
        key("key", "Return")
        time.sleep(0.4)
    if sticker:
        target = SETTINGS["targets"][name]
        payload = {"action": "asset", "key": sticker, "contact": target["id"], "is_group": target["is_group"]}
        request = Request("http://172.17.0.1:48732/api/wechat", data=json.dumps(payload).encode(),
                          headers={"Content-Type":"application/json","X-Fish-Bridge-Key":SETTINGS["token"]})
        with urlopen(request, timeout=20) as response:
            path = ROOT / Path(sticker).name
            path.write_bytes(response.read())
        if title() != name:
            raise RuntimeError("Chat changed before GIF delivery")
        subprocess.run(["xclip","-selection","clipboard","-t","text/uri-list"],
                       input=(path.as_uri()+"\r\n").encode(), check=True)
        key("mousemove", 410, 739, "click", 1, "key", "ctrl+v")
        time.sleep(0.7)
        key("key", "Return")
        time.sleep(0.4)


def poll(state, name, reply_latest=False):
    select(name)
    current,files,previous_video_ids = read_visible(SETTINGS["targets"][name]["is_group"])
    baselines=state.setdefault("_media_ready",{})
    if not baselines.get(name):
        # Old snapshots contain text only. Align them before enabling media so a
        # deployment doesn't send replies to previously visible messages.
        baselines[name]=True
        if not reply_latest:
            state[name]=current
            STATE.write_text(json.dumps(state,ensure_ascii=False))
            return
    if not current:
        if name not in state:
            state[name] = []
            STATE.write_text(json.dumps(state, ensure_ascii=False))
        return
    previous = state.get(name)
    if previous is None:
        previous = current[:-1] if reply_latest else current
    # Old snapshots used a different caption for native stickers.
    old_ids=[(m["sender"],m.get("media") or m["body"]) for m in previous]
    new_ids=[(m["sender"],m.get("media") or m["body"]) for m in current]
    # Older bridges recorded video covers as generic media. Migrate only known rows.
    old_media={m.get("media") for m in previous}
    for index,legacy_id in previous_video_ids.items():
        if legacy_id in old_media and current[index]["media"] not in old_media:
            new_ids[index]=(current[index]["sender"],legacy_id)
    overlap = max((n for n in range(min(len(previous), len(current)) + 1)
                   if n == 0 or old_ids[-n:] == new_ids[:n]), default=0)
    # A reply can scroll later bubbles off screen. Capture new rows before sending.
    captions={}
    for index,source in files.items():
        if index>=overlap and isinstance(source,ScreenSticker):
            files[index],captions[index]=capture_playback(source)
        elif index>=overlap and isinstance(source,VideoBubble):
            files[index],captions[index]=read_video(source)
    state.setdefault("_instance", uuid.uuid4().hex)
    sequence = state.setdefault("_sequence", {})
    for index, item in enumerate(current[overlap:], overlap):
        number = sequence.get(name, 0) + 1
        event = {"name": name, **item, "event_id": f"{state['_instance']}-{number}"}
        if index in captions:
            event["body"]=captions[index]
        if files.get(index):
            target=SETTINGS["targets"][name]
            upload=Request("http://172.17.0.1:48732/api/wechat/media",data=files[index],headers={
                "Content-Type":"application/octet-stream","X-Fish-Bridge-Key":SETTINGS["token"],
                "X-Fish-Contact":target["id"]})
            with urlopen(upload,timeout=35) as response:
                event["attachment"]=json.load(response)["name"]
            logging.info("incoming media collected (%d bytes)",len(files[index]))
        request = Request(
            "http://172.17.0.1:6199/message", data=json.dumps(event).encode(),
            headers={"Content-Type": "application/json", "X-Fish-Bridge-Key": SETTINGS["token"]},
        )
        # Record the observed message before UI delivery to avoid re-sending after a restart.
        body=item["body"].strip()
        private=not SETTINGS["targets"][name]["is_group"]
        if private and body.startswith("/音色"):
            choice=body.removeprefix("/音色").strip().lower()
            voices={"清柔":"coral","明亮":"nova","低沉":"onyx","自选一":"自选一","自选二":"自选二"}
            selected=voices.get(choice,choice)
            if selected in voices.values():
                state["_voice"]=selected
                result={"answer":"已切换音色，"+selected+"。"}
            else:
                result={"answer":"当前音色："+state.get("_voice","coral")+"。可选清柔、明亮、低沉、自选一、自选二。"}
        else:
            with urlopen(request,timeout=100) as response:
                result=json.load(response)
        sequence[name]=number
        state[name]=current[:index+1]
        STATE.write_text(json.dumps(state, ensure_ascii=False))
        if result["answer"] or result.get("sticker"):
            if private and result.get("score")=="floral-sea":
                if (ROOT/"floral-sea.wav").is_file() and state.get("_voice","coral") in ("自选一","自选二"):
                    with wave.open(str(ROOT/"floral-sea.wav"),"rb") as wav,tempfile.TemporaryDirectory() as temp:
                        play_voice(wav,temp,name)
                else:
                    send(name,"当前无法播放这段预录清唱，请检查本地录音和所选音色。")
                continue
            voice=state.get("_voice","coral") if result.get("voice") else None
            send(name,result["answer"],result.get("sticker",""),voice=voice,sing=result.get("sing",False))
            logging.info("reply delivered to %s", name)
        else:
            logging.info("group message did not address the bot")
    state[name] = current
    STATE.write_text(json.dumps(state, ensure_ascii=False))


if __name__ == "__main__":
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    if len(sys.argv) > 1:
        name = sys.argv[2]
        select(name)
        if sys.argv[1] == "inspect":
            print(json.dumps(read_visible(SETTINGS["targets"][name]["is_group"])[0], ensure_ascii=False))
        elif sys.argv[1] == "reply-latest":
            state.pop(name, None)
            poll(state, name, reply_latest=True)
    else:
        previous_image = None
        last_scan = 0.0
        last_proactive = time.monotonic()
        while True:
            image = ImageGrab.grab().crop((62, 81, 998, 688)).tobytes()
            if image != previous_image or time.monotonic() - last_scan >= 60:
                previous_image = image
                last_scan = time.monotonic()
                check_due = last_scan - last_proactive >= 60
                if check_due:
                    last_proactive = last_scan
                for name in SETTINGS["targets"]:
                    try:
                        poll(state, name)
                        if check_due:
                            event = {"action":"proactive","name":name}
                            req = Request("http://172.17.0.1:6199/message", data=json.dumps(event).encode(),
                                          headers={"Content-Type":"application/json","X-Fish-Bridge-Key":SETTINGS["token"]})
                            with urlopen(req, timeout=100) as response:
                                result=json.load(response)
                            if result["answer"] or result.get("sticker"):
                                send(name,result["answer"],result.get("sticker",""),
                                     voice=state.get("_voice","coral") if result.get("voice") else None)
                    except (URLError, TimeoutError, RuntimeError, subprocess.SubprocessError) as exc:
                        logging.error("desktop bridge paused this poll: %s", type(exc).__name__)
            time.sleep(2)
