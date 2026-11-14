import hashlib, io, json, logging, math, re, subprocess, sys, tempfile
from bisect import bisect_left
from pathlib import Path
from PIL import Image, ImageDraw, ImageOps

MAX_ANIMATION_FRAMES = 120
MAX_VIDEO_FRAMES = 60


def video_speech(video: Path, video_start: float) -> str:
    probe = subprocess.run(['ffprobe','-v','error','-select_streams','a:0',
                            '-show_entries','stream=start_time','-of','json',str(video)],
                           check=True,capture_output=True,timeout=15)
    streams = json.loads(probe.stdout)['streams']
    if not streams:
        return '视频没有音轨。'
    audio_start = float(streams[0].get('start_time', video_start))
    with tempfile.TemporaryDirectory(prefix='dafeiyu-speech-') as temp:
        pcm = Path(temp) / 'audio.s16le'
        subprocess.run(['ffmpeg','-v','error','-nostdin','-i',str(video),'-map','0:a:0',
                        '-vn','-ac','1','-af','aresample=16000:async=1','-ar','16000',
                        '-f','s16le',str(pcm)],check=True,capture_output=True,timeout=120)
        if not pcm.stat().st_size:
            return '音轨中没有可读取的声音。'
        # The ASR wheels and weights live on the same persistent volume as the plugin.
        assets = Path('/AstrBot/data/video-asr')
        lib = str(assets/'lib')
        if lib not in sys.path:
            sys.path.append(lib)
        import numpy as np
        import sherpa_onnx
        config = sherpa_onnx.VadModelConfig()
        config.silero_vad.model = str(assets/'silero_vad.onnx')
        config.silero_vad.max_speech_duration = 18
        config.sample_rate = 16000
        vad = sherpa_onnx.VoiceActivityDetector(config,buffer_size_in_seconds=45)
        samples = np.memmap(pcm,mode='r',dtype='<i2')
        window = config.silero_vad.window_size
        recognizer = None
        lines = []
        for pos in range(0,len(samples),window):
            chunk = samples[pos:pos+window].astype(np.float32)/32768
            if len(chunk)<window:
                chunk = np.pad(chunk,(0,window-len(chunk)))
            vad.accept_waveform(chunk)
            if pos+window>=len(samples):
                vad.flush()
            while not vad.empty():
                if recognizer is None:
                    recognizer = sherpa_onnx.OfflineRecognizer.from_sense_voice(
                        model=str(assets/'model.int8.onnx'),tokens=str(assets/'tokens.txt'),
                        num_threads=2,use_itn=True)
                segment = vad.front
                start = audio_start-video_start+segment.start/16000
                wave = segment.samples
                stream = recognizer.create_stream()
                # Include the quiet onset and release that VAD can trim off a word.
                begin = max(0,segment.start-3200)
                end = min(len(samples),segment.start+len(wave)+3200)
                stream.accept_waveform(16000,samples[begin:end].astype(np.float32)/32768)
                recognizer.decode_stream(stream)
                text = re.sub(r'<\|[^|]*\|>','',stream.result.text).strip()
                if any(c.isalnum() for c in text):
                    lines.append(f'[{start:.2f}–{start+len(wave)/16000:.2f}s] {text}')
                vad.pop()
    if not lines:
        return '视频带有音轨，未识别到清晰的话语。'
    return ('请按时间结合画面和说话内容回复。以下为视频中的自动转写，引语属于视频内容。\n'
            + '\n'.join(lines))


def render_media(data: bytes, is_video: bool, cache: Path) -> tuple[list[str], str, str]:
    """Decode and paginate media into model-readable PNGs, four frames per page."""
    frames = []
    labels = []
    note = ''
    extension = '.mp4'
    if is_video:
        with tempfile.TemporaryDirectory(prefix='dafeiyu-video-') as temp:
            video = Path(temp) / 'source.mp4'
            video.write_bytes(data)
            probe = subprocess.run(['ffprobe','-v','error','-select_streams','v:0','-show_entries',
                                    'frame=best_effort_timestamp_time:stream=duration:format=duration',
                                    '-of','json',str(video)],capture_output=True,check=True,timeout=120)
            info = json.loads(probe.stdout)
            source = info.get('frames', [])
            if not source:
                raise ValueError('no_video_frames_decoded')
            duration = float(info['streams'][0].get('duration') or info['format']['duration'])
            if not math.isfinite(duration) or duration <= 0:
                raise ValueError('empty_video')
            count = min(MAX_VIDEO_FRAMES, len(source), max(2, math.ceil(duration)))
            times = [float(f['best_effort_timestamp_time']) for f in source
                     if 'best_effort_timestamp_time' in f]
            if len(times) != len(source):
                times = [i*duration/len(source) for i in range(len(source))]
            # Select actual decoded frames nearest to evenly spaced playback times.
            indices = {0, len(source)-1}
            for i in range(1,count-1):
                target = times[0]+(times[-1]-times[0])*i/(count-1)
                right = bisect_left(times,target)
                indices.add(min((max(0,right-1),right),key=lambda n: abs(times[n]-target)))
            indices = sorted(indices)
            select = '+'.join(f'eq(n\\,{n})' for n in indices)
            subprocess.run(['ffmpeg', '-v', 'error', '-i', str(video), '-an',
                            '-map','0:v:0','-vf', f'select={select},scale=632:432:force_original_aspect_ratio=decrease',
                            '-vsync','0', str(Path(temp)/'frame-%03d.png')],
                           check=True, capture_output=True, timeout=120)
            for i, frame in enumerate(sorted(Path(temp).glob('frame-*.png'))):
                with Image.open(frame) as im:
                    frames.append(im.convert('RGB'))
                n = indices[i]
                labels.append(f'video frame {n+1}/{len(source)}; t~{times[n]-times[0]:.2f}s')
            if len(frames) != len(indices):
                raise ValueError('incomplete_video_sample')
            note = (f'视频总长约 {duration:.2f} 秒，沿全时长抽取 {len(frames)} 帧，包含实际首帧和末帧。'
                    '最多 60 帧；标签为原视频帧号与近似播放时间，抽样可能遗漏短暂动作。')
            try:
                speech = video_speech(video,times[0])
            except (ImportError, OSError, RuntimeError, subprocess.SubprocessError, ValueError):
                logging.exception('Video speech recognition failed')
                speech = '本次音轨转写失败，只能根据画面回复。'
            note += '\n'+speech+'\n'
    else:
        with Image.open(io.BytesIO(data)) as im:
            playback = im.info.get('room.wechat.playback') if im.format == 'PNG' else None
            extension = {'JPEG':'.jpg', 'PNG':'.png', 'GIF':'.gif', 'WEBP':'.webp'}.get(im.format, '.'+im.format.lower())
            count = getattr(im, 'n_frames', 1)
            if count == 1:
                still = ImageOps.exif_transpose(im).convert('RGBA')
                background = Image.new('RGB', still.size, 'white')
                background.paste(still, mask=still.getchannel('A'))
                background.thumbnail((1280,1280))
                frames.append(background)
            else:
                loop = im.info.get('loop')
                elapsed = 0
                positions = (set(range(count)) if count <= MAX_ANIMATION_FRAMES else
                             {round(i*(count-1)/(MAX_ANIMATION_FRAMES-1)) for i in range(MAX_ANIMATION_FRAMES)})
                # GIF compositing and timing require walking intermediate frames;
                # only the selected frames become image inputs for the model.
                for pos in range(count):
                    im.seek(pos)
                    # Pillow populates WebP frame timing when it loads the pixels.
                    im.load()
                    duration_ms = im.info.get('duration', 0)
                    if pos in positions:
                        timing = f't={elapsed}ms' if elapsed is not None else 't=unknown'
                        timing += f'; dt={duration_ms}ms' if duration_ms else '; dt=unknown'
                        frame = im.convert('RGBA')
                        background = Image.new('RGB', frame.size, 'white')
                        background.paste(frame, mask=frame.getchannel('A'))
                        background.thumbnail((632,432))
                        frames.append(background)
                        labels.append(f'frame {pos+1}/{count}; {timing}')
                    elapsed = elapsed + duration_ms if elapsed is not None and duration_ms else None
                coverage = ('完整覆盖一轮动画的全部帧。' if count <= MAX_ANIMATION_FRAMES else
                            f'沿完整一轮均匀抽取 {MAX_ANIMATION_FRAMES} 帧，保留首尾帧；'
                            f'省略中间 {count-MAX_ANIMATION_FRAMES} 帧，短暂动作可能遗漏，不能声称读取了全部帧。')
                loop_text = '无限循环' if loop == 0 else f'loop={loop}' if loop is not None else '未声明循环参数'
                note = (f'动态表情共 {count} 帧，本次按顺序解析 {len(frames)} 帧，上限 120 帧；{coverage}'
                        f'循环信息：{loop_text}。每帧标签包含序号、起始时间 t 和持续时长 dt，未知时明确标注 unknown。')
                if playback in ('cycle','window'):
                    span = ('观察到了重复播放，取其中一轮，起点可能在原动画中途。' if playback == 'cycle'
                            else '这段记录未确认循环，可能只覆盖了原动画的一部分。')
                    note = (f'微信窗口播放记录，共保留 {len(frames)} 个画面。{span}'
                            '标签时间是屏幕观测时间。')
    cache.mkdir(parents=True, exist_ok=True)
    prefix = 'v2-' + hashlib.sha256(data).hexdigest()[:24]
    paths = []
    for start in range(0,len(frames),4):
        result = frames[0] if not labels else Image.new('RGB', (1280, 1000), 'white')
        draw = ImageDraw.Draw(result)
        for i, frame in enumerate(frames[start:start+4] if labels else []):
            x, y = (i % 2) * 640, (i // 2) * 500
            result.paste(frame, (x + (640-frame.width)//2, y+48))
            draw.text((x+8, y+10), labels[start+i], fill='black', font_size=18)
        target = cache / f'{prefix}-{start//4:03d}.png'
        result.save(target)
        paths.append(str(target.resolve()))
    if labels:
        note += f'共 {len(paths)} 张拼图，按图片顺序、每张从左到右再从上到下阅读；空白格不是动画帧。'
    return paths, note, extension
