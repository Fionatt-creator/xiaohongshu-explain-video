"""拾句英语 · 精细讲解视频渲染器

统一规格：1080×1920（9:16），官网品牌配色，内容避开小红书顶部/底部 UI 遮挡区。
每个选题在 SPECS 里登记一份内容，产物写到 <精细讲解视频>/<选题>/ 下。
"""
from pathlib import Path
import subprocess as sp, json, hashlib, os, sys, time
from urllib.parse import quote
import requests
from PIL import Image, ImageDraw, ImageFont

BASE = Path(__file__).resolve().parent          # _tools
SERIES = BASE.parent                            # 精细讲解视频/
DEFAULT_SRC = '__DATA_ROOT__/小红书发帖-拾句英语/谷爱凌/高清版本.mp4'
SRC = DEFAULT_SRC   # 当前正在渲染的选题所用素材；render() 会按选题覆盖


def topic_dir(name):
    """选题目录。2026-09 起系列顶层改成 `01_谷爱凌_…` 这种带序号的形式，
    所以先按「序号_选题名」找；找不到就退回 `<SERIES>/<选题>`——新选题第一次渲染就是这种，
    渲染时会把目录建出来。build / covers / make_srt 都走这里，避免各写一套路径。"""
    d = SERIES/name
    if d.is_dir():
        return d
    for p in sorted(SERIES.iterdir()):
        if p.is_dir() and p.name.endswith('_'+name):
            return p
    return d

# ---- 画布（1080×1920；上下留白：上 190px，下 417px 避让小红书 UI）----
W, H = 1080, 1920
CHIP_R = 18
TITLE_Y = 318
DIV1_Y, DIV2_Y = 424, 1408
PIP_W, PIP_H, PIP_Y = 810, 456, 470      # 原片画中画（16:9），水平位置由样式的 pip_x 给
BRAND_CY = 1470
LOGO_H = 66
BRAND_NAME = '拾句英语'
BRAND_URL = 'https://shijuenglish.cn/'
# 页脚右侧那行小字：2026-09 起**整条页脚都不要了**（原先是 logo + 拾句英语 + 官网链接，
# 链接被小红书判成站外引流而限流）。去掉页脚连同底部分隔线，下半区全部让给正文：
# 正文下沿从 1380 延到 **1470**（1503 是小红色 UI 安全线，不能再往下压）。
# 已发布的老片在 SPEC 里写 'foot': True 锁住原样（'url' 再决定页脚里放不放官网链接）。
BRAND_TAIL = '听懂一句，再把它说出来'   # 只在老片回放时用得到
SHOW_FOOT = False       # render() 会按选题覆盖（SPEC 的 'foot'）
SHOW_URL = False        # render() 会按选题覆盖（SPEC 的 'url'）
LOGO_SRC = '__DATA_ROOT__/BrandLogo.png'

# ---- 样式预设 ----
# v2（默认，2026-09 起）：深色内容区 + 左右留白 120px。
#     原因：小红书官方按钮是白色，浅底上按钮与画面糊在一起；且视频被缩放显示后，
#     72px 的留白在手机上只剩约 5.6% 屏宽，显得贴边。
# v1（2026-09 之前做的四条）：浅色内容区 + 留白 72px。只为复现旧片保留，新片一律用 v2。
STYLES = {
    'v2': dict(bg='#191918', fg='#F7F7F5', mute='#9A9B98',
               green='#2DCE7B', green2='#6FE3A8', brand='#2DCE7B', line='#33342F',
               surface='#242421', on_brand='#191918', logo_mode='mark', foot_layout='left',
               side=120, pip_x=135),
    'v1': dict(bg='#F7F7F5', fg='#191918', mute='#7D7E7B',
               green='#0A7A47', green2='#12A45E', brand='#2DCE7B', line='#E1E1DC',
               surface='#FFFFFF', on_brand='#191918', logo_mode='badge', foot_layout='split',
               side=72, pip_x=135),
}
DEFAULT_STYLE = 'v2'


def apply_style(name=DEFAULT_STYLE):
    """把样式预设铺到模块全局，card() / render() / covers.py 直接读这些全局。"""
    global BG, FG, MUTE, GREEN, GREEN2, BRAND, LINE, SURFACE, SIDE, RIGHT, CHIP, PIP_X
    global ON_BRAND, LOGO_MODE, FOOT_LAYOUT, STYLE
    s = STYLES[name]; STYLE = name
    BG, FG, MUTE = s['bg'], s['fg'], s['mute']
    GREEN, GREEN2, BRAND, LINE, SURFACE = s['green'], s['green2'], s['brand'], s['line'], s['surface']
    SIDE, RIGHT = s['side'], W - s['side']
    CHIP = (SIDE, 190, SIDE + 200, 250)
    PIP_X = s['pip_x']
    ON_BRAND, LOGO_MODE, FOOT_LAYOUT = s['on_brand'], s['logo_mode'], s['foot_layout']


apply_style()

CN = '/System/Library/Fonts/STHeiti Medium.ttc'
EN = '/System/Library/Fonts/HelveticaNeue.ttc'
CN_IDX = EN_IDX = 0        # .ttc 里的字面序号；.ttf 一律 0

# ---- 字体预设（跟样式预设一个思路：换了字体，旧片至少还能按原字体重渲）----
# heiti：2026-09 之前做的片子（黑体 + Helvetica Neue）
# song ：2026-09 起的新片（宋体 + Arial 斜体）。Songti.ttc 里 0=Black 1=Bold 3=Light 6=Regular
FONTS = {
    'heiti': ('/System/Library/Fonts/STHeiti Medium.ttc',
              '/System/Library/Fonts/HelveticaNeue.ttc', 0, 0),
    'song': ('/System/Library/Fonts/Supplemental/Songti.ttc',
             '/System/Library/Fonts/Supplemental/Arial Italic.ttf', 1, 0),
}
DEFAULT_FONTS = 'song'   # 新片默认（2026-09 起）；老片在 SPEC 里显式写 'fonts': 'heiti'
FONTSET = DEFAULT_FONTS
# 页脚网址这类界面元素用的西文字体：不跟着正文字体走，Arial 斜体的网址看着不对
EN_UI = '/System/Library/Fonts/HelveticaNeue.ttc'


def apply_fonts(name=DEFAULT_FONTS):
    global CN, EN, CN_IDX, EN_IDX, FONTSET
    CN, EN, CN_IDX, EN_IDX = FONTS[name]
    FONTSET = name


apply_fonts()

DEFAULT_VOICE = '__VOICE_ID__'
VOICE = DEFAULT_VOICE    # 当前音色；render() 会按选题覆盖（SPEC 里可写 'voice': '<id>'）
DEFAULT_MODEL = 'eleven_v3'   # 新片默认模型（2026-09 起）
MODEL = DEFAULT_MODEL    # 当前模型；同样可按选题覆盖（老片写 'model': LEGACY_MODEL）
# 新片默认音色参数。⚠️ v3 不支持 speed，所以这里不带 speed（老片用 LEGACY_VOICE_SETTINGS）
DEFAULT_VOICE_SETTINGS = {'stability': 0.45, 'similarity_boost': 0.75, 'style': 0.4, 'use_speaker_boost': True}
VOICE_SETTINGS = DEFAULT_VOICE_SETTINGS   # 当前音色参数；render() 会按选题覆盖
# 2026-09 之前那批片子用的（v2 模型 + style 0 + 带 speed）：只在老片 SPEC 里显式引用，不要当默认
LEGACY_MODEL = 'eleven_multilingual_v2'
LEGACY_VOICE_SETTINGS = {'stability': 0.45, 'similarity_boost': 0.75, 'style': 0.0,
                         'use_speaker_boost': True, 'speed': 1.0}
DEFAULT_EN_SLOW = 0.8   # 英文旁白放慢到当前速度的 0.8 倍；中文保持原速
EN_SLOW = DEFAULT_EN_SLOW   # 可按选题覆盖（'en_slow': 1.0 表示英文也不变速）
DEFAULT_SPEED = 1.2     # 整体倍速：旁白 atempo，段长等比缩短。2026-09 起新片默认 1.2 倍速
SPEED = DEFAULT_SPEED   # 可按选题覆盖（老片写 'speed': 1.0 锁原速）
DEFAULT_SPEED_SRC = 1.0 # 访谈原声的倍速：不动——英文本就是学习材料，且英文旁白特意放到 0.8 倍教发音
SPEED_SRC = DEFAULT_SPEED_SRC   # 想让原声一起快，SPEC 里写 'speed_src': 1.2
PART_GAP = 0.22   # 中英分段之间的停顿

# ---- 字幕（带字幕版才启用，SPEC 里写 'subs': True）----
# 位置在画面中下方：放正中间会挡住访谈画面里说话人的表情和手势；
# 贴到底部分隔线又只剩二十几像素，还离小红书底部 UI 太近。
# 具体高度不能拍脑袋——各卡文字位置不一样，SPEC 里可以用 'sub_cy' 覆写，
# 加字幕前先用流程第 5 步的检测脚本，在这个区间里找一条整条空带。
SUB_FS = 40          # 字幕字号
SUB_CY_DEFAULT = 1282   # 字幕中心线默认值
SUB_CY = SUB_CY_DEFAULT
SUB_MAXW = 800       # 单行最大宽度（内容区 840，两侧各留 20）
SUB_BAND = 80        # 字幕条高度：只渲染这一窄条透明 PNG 再叠上去，不搬整张 1080×1920
SUB_TOP = SUB_CY - SUB_BAND // 2   # 字幕条在画面里的位置
SUB_FILL, SUB_STROKE = '#FFFFFF', '#000000'   # 白字 + 1px 黑描边
# 断行处：中文只认标点（认空格的话「2 分 5 秒」会被切成「分 5」这种碎条），
# 英文再加上空格，好在词与词之间断。
SUB_BREAK_ZH = '，。、；：？！…—,.;:?!'
SUB_BREAK_EN = SUB_BREAK_ZH + ' '


def load_key():
    if os.environ.get('ELEVENLABS_API_KEY'):
        return os.environ['ELEVENLABS_API_KEY']
    for p in [BASE/'.env.elevenlabs', SERIES/'.env.elevenlabs', Path('__WORKSPACE__/.env')]:
        if p.exists():
            for line in p.read_text().splitlines():
                if '=' in line and not line.lstrip().startswith('#'):
                    k, v = line.split('=', 1)
                    if k.strip() == 'ELEVENLABS_API_KEY' and v.strip().strip('"\''):
                        return v.strip().strip('"\'')
    raise SystemExit('未找到 ELEVENLABS_API_KEY')


KEY = load_key()
SESSION = requests.Session()
SESSION.headers.update({'xi-api-key': KEY})
HOST = 'https://api.elevenlabs.io/v1/'


def request(method, path, **kwargs):
    try:
        r = SESSION.request(method, HOST+path, timeout=120, **kwargs)
    except requests.RequestException as e:
        raise SystemExit('网络请求未完成：'+type(e).__name__)
    if not r.ok:
        try:
            d = r.json().get('detail', {})
            status = d.get('status', 'unknown') if isinstance(d, dict) else 'request_error'
        except Exception:
            status = 'unknown'
        raise SystemExit(f'ElevenLabs HTTP {r.status_code}; status={status}')
    return r


def tts(text, target, tries=4):
    sig = target.with_suffix('.sha256')
    payload = {'text': text, 'model_id': MODEL, 'voice_settings': VOICE_SETTINGS}
    signature = hashlib.sha256((VOICE+json.dumps(payload, ensure_ascii=False)).encode()).hexdigest()
    if not (target.exists() and sig.exists() and sig.read_text() == signature):
        # 实测会偶发 SSL 中断 / 极短的错误响应，一次抖动就能中断整片（缓存按签名命中，重跑不用重合成）。
        for i in range(tries):
            err = None
            try:
                r = request('POST', 'text-to-speech/'+quote(VOICE, safe=''), params={'output_format': 'mp3_44100_128'}, json=payload)
                if len(r.content) >= 1000:
                    break
                err = f'响应过短（{len(r.content)} 字节）'
            except SystemExit as e:
                err = str(e)
            if i == tries-1:
                raise SystemExit(f'TTS 连续 {tries} 次失败，停止。最后一次：{err}')
            print(f'  {target.stem} 第 {i+1} 次失败（{err}），重试…', flush=True)
            time.sleep(2 * (i+1))
        target.write_bytes(r.content)
        sig.write_text(signature)
    return target


def speech(name, parts):
    """逐段合成：中文原速，英文按 EN_SLOW 放慢，再拼接成整段旁白。

    合成前先把相邻的同语种片段合并。原来是「中文碎句 + 英文 + 中文碎句」逐段送 TTS，
    每段中文都是半句话，TTS 按句子给语调，半句的语调必然不对（听感就是中文很怪）。
    合并后中文回到完整句子，英文仍然只对 en 段做 atempo，两边都不受影响。
    """
    merged = []
    for lang, t in parts:
        if merged and merged[-1][0] == lang:
            merged[-1] = (lang, merged[-1][1] + t)
        else:
            merged.append((lang, t))
    files = []
    for i, (lang, t) in enumerate(merged):
        mp3 = tts(t, OUT/f'{name}_{i}.mp3')
        af = 'loudnorm=I=-18:TP=-1.5:LRA=11'
        if lang == 'en':
            af += f',atempo={EN_SLOW}'      # 英文先按 EN_SLOW 放慢
        if SPEED != 1.0:
            af += f',atempo={SPEED}'        # 再整体提速（1.2 倍速版就是这里起作用）
        # ElevenLabs 有时会返回带 2–3 秒尾部静音的短片段（实测一条片子里 106 片有 7 片，
        # 合计 17 秒干等），直接拼进来会出现半句之间停两秒半。反向后掐头＝掐尾。
        # ⚠️ start_duration 是「要看到多长的连续有声才停止掐」，不是「只掐超过多久的静音」：
        #    取 0.35 会把最后 0.4 秒的语音一起削掉（听感就是中文末字被吞、然后直接进英文）。
        #    取 0.05 且阈值放到 -55dB，实测与真实语音末尾只差 0.05 秒，而那 0.05 秒本就低于 -45dB。
        af += ',areverse,silenceremove=start_periods=1:start_duration=0.05:start_threshold=-55dB,areverse'
        af += f',apad=pad_dur={PART_GAP}'
        w = OUT/f'{name}_{i}.wav'
        sp.run(['ffmpeg', '-y', '-v', 'error', '-i', str(mp3), '-af', af, '-ar', '48000', '-ac', '2', str(w)], check=True)
        files.append(w)
    out = OUT/f'{name}.wav'
    if len(files) == 1:
        sp.run(['ffmpeg', '-y', '-v', 'error', '-i', str(files[0]), '-c:a', 'pcm_s16le', str(out)], check=True)
    else:
        lst = OUT/f'{name}_parts.txt'
        lst.write_text(''.join(f"file '{p}'\n" for p in files))
        sp.run(['ffmpeg', '-y', '-v', 'error', '-f', 'concat', '-safe', '0', '-i', str(lst), '-c:a', 'pcm_s16le', str(out)], check=True)
    print(name, '配音就绪', flush=True)
    # info = 每段的（语种, 文本, 时长），给字幕算时间轴用；时长含尾部 PART_GAP 的静音
    return out, [(lang, t, duration(w)) for (lang, t), w in zip(merged, files)]


def run(args):
    sp.run(args, check=True, stdout=sp.DEVNULL, stderr=sp.PIPE)


def duration(p):
    return float(sp.check_output(['ffprobe', '-v', 'quiet', '-show_entries', 'format=duration', '-of', 'csv=p=0', str(p)]))


def font(size, en=False):
    return ImageFont.truetype(EN if en else CN, size, index=EN_IDX if en else CN_IDX)


def ui_font(size):
    """界面元素用的西文字体（页脚网址）：固定 Helvetica Neue，不随正文字体预设变。"""
    return ImageFont.truetype(EN_UI, size)


def ui_w(s, size):
    return ui_font(size).getlength(s)


def text_ui_mid(d, x, cy, s, size, color):
    """网址这类界面元素：固定西文字体 + 垂直居中（不跟着 Arial 斜体走）。"""
    f = ui_font(size)
    asc, desc = f.getmetrics()
    d.text((x, cy-(asc+desc)//2), s, font=f, fill=color)


def C(role):
    """颜色角色 → 当前样式的实际颜色。
    SPECS 里只写 'fg' / 'green' 这类角色名，不写十六进制，否则会在 import 时
    被绑定到某个样式上（旧片用 v1、新片用 v2，同一份 SPEC 要能两边都对）。"""
    return {'fg': FG, 'green': GREEN, 'green2': GREEN2, 'mute': MUTE, 'brand': BRAND}.get(role, role)


def text(d, xy, s, size=38, color=None, en=False):
    d.text(xy, s, font=font(size, en), fill=color or FG)


def text_r(d, right_x, y, s, size=38, color=None, en=False):
    d.text((right_x-font(size, en).getlength(s), y), s, font=font(size, en), fill=color or FG)


def text_mid(d, left_x, cy, s, size=38, color=None, en=False):
    f = font(size, en)
    asc, desc = f.getmetrics()
    d.text((left_x, cy-(asc+desc)//2), s, font=f, fill=color or FG)


_logo = None
_logo_mode = None


def logo_rgba():
    """logo 原图是「深色圆角方徽 + 白色图形」，外圈纯黑是画布底（一律抠掉）。
    badge 模式（浅底）：连徽章本体一起保留；mark 模式（深底）：只留白色图形，
    因为徽章的深色在深底上看不见、只会留一圈若有若无的方边。"""
    global _logo, _logo_mode
    if _logo is None or _logo_mode != LOGO_MODE:
        im = Image.open(LOGO_SRC).convert('RGB')
        if LOGO_MODE == 'mark':     # 深色→透明，白色→不透明
            a = im.convert('L').point(lambda v: 0 if v <= 40 else (255 if v >= 190 else round((v-40)*255/150)))
        else:                        # 只抠掉外圈纯黑画布，徽章保留
            a = im.convert('L').point(lambda v: 0 if v <= 10 else (255 if v >= 26 else round((v-10)*255/16)))
        im = im.convert('RGBA')
        im.putalpha(a)
        _logo = im.resize((round(im.width*LOGO_H/im.height), LOGO_H), Image.LANCZOS)
        _logo_mode = LOGO_MODE
    return _logo


def card(n, title, lines, still=None):
    im = Image.new('RGB', (W, H), BG); d = ImageDraw.Draw(im)
    d.rounded_rectangle(CHIP, radius=CHIP_R, fill=BRAND)
    text_mid(d, CHIP[0]+20, (CHIP[1]+CHIP[3])//2, '拾句英语', 36, ON_BRAND)
    text_r(d, RIGHT, 205, '听 · 懂 · 说', 32, MUTE)
    ts = 62                      # 标题过长时自动缩号，避免顶到右边界
    while ts > 34 and font(ts).getlength(title) > RIGHT-SIDE:
        ts -= 2
    text(d, (SIDE, TITLE_Y), title, ts)
    d.line((SIDE, DIV1_Y, RIGHT, DIV1_Y), fill=LINE, width=3)
    if still:   # 「先讲解、再听原声」的卡：讲解阶段用定格帧占住画中画位置，避免出现空洞
        im.paste(Image.open(still).convert('RGB'), (PIP_X, PIP_Y))
    for y, s, size, col, en in lines:
        text(d, (SIDE, y), s, size, C(col), en)
    # 页脚品牌条（只有老片画）：底部分隔线 + logo + 拾句英语 + 右侧小字。
    # 新片整条不画，下半区让给正文（正文下沿 1380 → 1470）。
    if SHOW_FOOT:
        d.line((SIDE, DIV2_Y, RIGHT, DIV2_Y), fill=LINE, width=3)
        lg = logo_rgba()
        im.paste(lg, (SIDE, BRAND_CY-lg.height//2), lg)
        name_x = SIDE+lg.width+20
        text_mid(d, name_x, BRAND_CY, BRAND_NAME, 48, GREEN)
        tail_x = name_x + font(48).getlength(BRAND_NAME) + 24
        if SHOW_URL:
            if FOOT_LAYOUT != 'left':   # v1 浅色版：网址右对齐
                tail_x = RIGHT - ui_w(BRAND_URL, 32)
            text_ui_mid(d, tail_x, BRAND_CY, BRAND_URL, 32, MUTE)
        else:
            text_mid(d, tail_x, BRAND_CY, BRAND_TAIL, 30, MUTE)
    p = WORK/(n+'.png'); im.save(p); return p


def grab_still(start, name):
    """抽原声片段起点的那一帧，缩到画中画尺寸，给「先讲解」那段当占位。"""
    out = WORK/f'{name}_still.png'
    run(['ffmpeg', '-y', '-v', 'error', '-ss', str(start), '-i', SRC, '-frames:v', '1',
         '-vf', f'scale={PIP_W}:{PIP_H}', str(out)])
    return out


def wrap1(s, f, maxw, breaks):
    """按像素宽度把一句话切成若干条单行字幕，优先在标点/空格处断，免得断在半句中间。"""
    lines, cur = [], ''
    for ch in s:
        if f.getlength(cur + ch) <= maxw:
            cur += ch
            continue
        i = max(cur.rfind(p) for p in breaks)
        if i < len(cur) * 0.5:      # 断点太靠前（后半截会拖成长行）就不迁就标点
            i = cur.rfind(' ') if ' ' in breaks else -1
        if i <= 0:
            i = len(cur) - 1
        lines.append(cur[:i+1].strip())
        cur = cur[i+1:] + ch        # ch 就是触发换行的那个字，补到下一行开头
    if cur.strip():
        lines.append(cur.strip())
    return lines or ['']


def sub_cues(s, lang, dur):
    """一句话 → [(字幕条, 起, 止)]，时间按字数比例摊到这句的实际时长上。

    没有词级时间戳，只能按长度近似；但字幕是「边听边读」，宁可略早不可略晚，
    所以把尾部那次 PART_GAP 静音从可用时长里扣掉。"""
    f = font(SUB_FS, lang == 'en')
    lines = []
    for l in wrap1(s, f, SUB_MAXW, SUB_BREAK_EN if lang == 'en' else SUB_BREAK_ZH):
        # 中文句接在英文后面时，开头会挂一个逗号，显示时去掉
        lines.append(l.lstrip('，,。.、；;：: ') or l)
    scale = sum(len(l) for l in lines) or 1
    span = max(dur - PART_GAP, 0.6)
    t, cues = 0.0, []
    for i, l in enumerate(lines):
        d = span * len(l) / scale
        # 最后一条一直挂到本段末尾（含尾部那 0.22s 静音）：字幕停在上一句直到下一句出现，
        # 否则每段之间会闪断一下
        cues.append((l, t, dur if i == len(lines) - 1 else t + d))
        t += d
    return cues


def sub_png(name, s, lang):
    """把一条字幕画成透明 PNG（只画 SUB_BAND 高的一条）：白字 + 1px 黑描边，居中。"""
    im = Image.new('RGBA', (W, SUB_BAND), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    f = font(SUB_FS, lang == 'en')
    x0, y0, _, y1 = f.getbbox(s)
    d.text(((W - f.getlength(s)) / 2 - x0, SUB_BAND // 2 - (y0 + y1) / 2), s,
           font=f, fill=SUB_FILL, stroke_width=1, stroke_fill=SUB_STROKE)
    p = WORK/f'sub_{name}.png'
    im.save(p)
    return p


def build_subs(n, info):
    """一段旁白（含中英分段）→ [(字幕 PNG, 叠放 y, 起, 止)]，时间轴相对本段视频。"""
    subs, t = [], 0.0
    for i, (lang, txt, dur) in enumerate(info):
        for j, (s, a, b) in enumerate(sub_cues(txt, lang, dur)):
            subs.append((sub_png(f'{n}_{i}_{j}', s, lang), SUB_TOP, t + a, t + b))
        t += dur + 0.001    # 每段错开 1ms：上一段末条挂到段尾，不错开的话边界那一帧会两条叠着画
    return subs


segments = []


def segment(n, img, aud=None, source=None, start=None, end=None, tail=0.35, subs=None):
    """subs = [(字幕 PNG, 叠放 y, 起, 止)]：按时间窗叠上去。
    必须叠在画中画之后——画中画是后贴的，先画在卡上会被它盖住。"""
    out = WORK/f'{n}.mp4'
    subs = subs or []
    if source:
        raw = end-start                    # 原声片段本身的长度（取素材用）
        dur = raw/SPEED_SRC                # 原声段在成片里占多长（SPEED_SRC=1 就是原速）
        args = ['ffmpeg', '-y', '-v', 'error', '-loop', '1', '-framerate', '30', '-i', str(img),
                '-ss', str(start), '-t', str(raw), '-i', SRC]
        if aud:
            args += ['-i', str(aud)]
        args += sum([['-loop', '1', '-framerate', '30', '-i', str(p)] for p, _, _, _ in subs], [])
        # 原声一起提速时，画面也得跟着 setpts，否则声画对不上、画面还会提前播完
        pts = f'setpts=PTS/{SPEED_SRC},' if SPEED_SRC != 1.0 else ''
        af_src = f'atempo={SPEED_SRC},' if SPEED_SRC != 1.0 else ''
        fc = f'[1:v]{pts}scale={PIP_W}:{PIP_H},setsar=1[v];[0:v][v]overlay={PIP_X}:{PIP_Y}:shortest=1[o0]'
        base = 3 if aud else 2       # 输入：0 卡面、1 原片、[2 旁白]、其后才是字幕
        for i, (_, py, t0, t1) in enumerate(subs):
            fc += f";[o{i}][{base+i}:v]overlay=0:{py}:enable='between(t,{t0:.2f},{t1:.2f})'[o{i+1}]"
        args += ['-filter_complex', fc,
                 '-map', f'[o{len(subs)}]', '-map', '2:a' if aud else '1:a']
    else:
        dur = duration(aud)+tail if aud else 1.0
        af_src = ''
        args = ['ffmpeg', '-y', '-v', 'error', '-loop', '1', '-framerate', '30', '-i', str(img)]
        if aud:
            args += ['-i', str(aud)]
        else:
            args += ['-f', 'lavfi', '-i', 'anullsrc=r=48000:cl=stereo']
        args += sum([['-loop', '1', '-framerate', '30', '-i', str(p)] for p, _, _, _ in subs], [])
        if subs:
            fc = ''
            for i, (_, py, t0, t1) in enumerate(subs):
                fc += (f"[0:v]" if i == 0 else f'[o{i}]')
                fc += f"[{2+i}:v]overlay=0:{py}:enable='between(t,{t0:.2f},{t1:.2f})'[o{i+1}];"
            args += ['-filter_complex', fc.rstrip(';'), '-map', f'[o{len(subs)}]', '-map', '1:a']
        else:
            args += ['-map', '0:v', '-map', '1:a']
    args += ['-af', af_src + 'apad,alimiter=limit=0.95', '-t', str(dur), '-r', '30', '-c:v', 'libx264', '-preset', 'fast',
             '-crf', '20', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '160k', '-ar', '48000', '-ac', '2',
             '-movflags', '+faststart', str(out)]
    run(args); segments.append((out, dur)); print(n, round(dur, 2), flush=True)


# ============================== 内容 ==============================
# lines 建议纵向落在 470–1380；source=(起, 止)，止为 None 表示跟旁白等长。

SPECS = {
    '谷爱凌_勇敢开口': {
        'style': 'v1',          # 已发布的浅色版，锁定样式以便原样复现
        'foot': True,           # 已发布：保留底部分隔线与页脚
        'url': True,            # 已发布：页脚保持官网链接原样
        'speed': 1.0,           # 已发布：原速（2026-09 起新片默认 1.2 倍速）
        'fonts': 'heiti',       # 已发布：黑体（2026-09 起新片默认宋体）
        'model': LEGACY_MODEL,  # 已发布：eleven_multilingual_v2（新片默认 eleven_v3）
        'voice_settings': LEGACY_VOICE_SETTINGS,   # 已发布：style 0 + 带 speed（新片默认 style 0.4、不带 speed）
        'cards': [
            dict(n='01', title='想试，又怕做不好？',
                 lines=[(990, '听听谷爱凌怎么说。', 60, 'green', False),
                        (1110, '两句话，练习勇敢开口', 48, 'fg', False)],
                 speech=[('zh', '想试，又怕做不好？听听谷爱凌怎么说。')],
                 source=(150.0, None)),
            dict(n='02', title='先听原句 / 01',
                 lines=[(950, 'When you have an opportunity', 51, 'fg', True),
                        (1030, 'to try something,', 57, 'fg', True),
                        (1120, 'always take it.', 66, 'green', True),
                        (1260, '有机会尝试，就抓住它。', 45, 'fg', False)],
                 source=(157.90, 161.39)),
            dict(n='03', title='先听原句 / 02',
                 lines=[(950, 'Because the worst that can', 51, 'fg', True),
                        (1030, 'happen is', 57, 'fg', True),
                        (1120, 'you don’t like it.', 66, 'green', True),
                        (1260, '最坏的情况，就是你不喜欢它。', 45, 'fg', False)],
                 source=(161.39, 163.97)),
            dict(n='04', title='句式 01 / 抓住机会',
                 lines=[(480, 'have an opportunity to…', 70, 'green', True),
                        (600, '有机会做某事', 60, 'fg', False),
                        (860, 'When you have an opportunity', 54, 'fg', True),
                        (945, 'to try something,', 61, 'fg', True),
                        (1075, 'always take it.', 67, 'green2', True),
                        (1270, 'take it = 抓住这个机会', 54, 'fg', False)],
                 speech=[('zh', '第一句，有机会做某事。'), ('en', 'Have an opportunity to.'),
                         ('zh', '后面的 take it，指抓住这个机会。')]),
            dict(n='05', title='句式 02 / 最坏的情况',
                 lines=[(490, 'The worst that can', 73, 'green', True),
                        (595, 'happen is…', 73, 'green', True),
                        (780, '最坏的情况是……', 61, 'fg', False),
                        (1060, '后面接你担心会发生的事', 48, 'fg', False),
                        (1180, 'you don’t like it', 64, 'green2', True),
                        (1310, '你发现自己不喜欢它', 48, 'mute', False)],
                 speech=[('zh', '第二句，'), ('en', 'The worst that can happen is.'),
                         ('zh', '意思是，最坏的情况是。后面接你担心会发生的事。')]),
            dict(n='06', title='换成你自己的表达',
                 lines=[(490, 'try something', 70, 'mute', True),
                        (620, '↓', 87, 'green', False),
                        (760, 'speak English', 81, 'green2', True),
                        (1020, 'When you have an opportunity', 54, 'fg', True),
                        (1105, 'to speak English, take it.', 63, 'green', True),
                        (1290, '有机会说英语，就抓住它。', 50, 'fg', False)],
                 speech=[('zh', '换成说英语，就能用在你自己身上。'),
                         ('en', 'When you have an opportunity to speak English, take it.')]),
            dict(n='07', title='现在，练这一句',
                 lines=[(480, '01  听一句', 56, 'green2', False),
                        (680, 'When you have an opportunity', 54, 'fg', True),
                        (770, 'to speak English,', 69, 'green', True),
                        (890, 'take it.', 74, 'green', True),
                        (1180, '有机会说英语，就抓住它。', 48, 'mute', False)],
                 speech=[('zh', '先听一遍。'),
                         ('en', 'When you have an opportunity to speak English, take it.')]),
            dict(n='08', title='现在，轮到你开口',
                 lines=[(480, '02  不看英文，说一次', 56, 'green2', False),
                        (780, '有机会说英语，', 72, 'fg', False),
                        (900, '就抓住它。', 72, 'green', False),
                        (1180, '留 3 秒，试着说出来', 48, 'mute', False)],
                 speech=[('zh', '现在不看英文，自己说一遍。')],
                 tail=3.1),
            dict(n='09', title='最后，补完这句话',
                 lines=[(500, '最坏的情况，', 65, 'fg', False),
                        (600, '也就是我犯几个错误。', 65, 'green', False),
                        (900, 'The worst that can', 67, 'fg', True),
                        (1000, 'happen is ________.', 67, 'green2', True),
                        (1250, '你会怎么说？', 53, 'mute', False)],
                 speech=[('zh', '最坏的情况，也就是我犯几个错误。你会怎么说？')],
                 tail=3.0),
            dict(n='10', title='答案 / 你也可以这样说',
                 lines=[(500, 'The worst that can', 66, 'fg', True),
                        (600, 'happen is', 66, 'fg', True),
                        (800, 'I make a few mistakes.', 70, 'green', True),
                        (1190, '最坏的情况，', 54, 'mute', False),
                        (1280, '也就是我犯几个错误。', 54, 'mute', False)],
                 speech=[('en', 'The worst that can happen is I make a few mistakes.')]),
            dict(n='11', title='收藏，下次再练一次',
                 lines=[(480, '拾句英语', 105, 'green', False),
                        (660, '听懂一句', 72, 'fg', False),
                        (770, '再把它说出来', 72, 'fg', False),
                        (1040, '今天记住两个结构', 48, 'mute', False),
                        (1170, 'have an opportunity to…', 54, 'green2', True),
                        (1260, 'the worst that can happen is…', 48, 'green2', True)],
                 speech=[('zh', '先收藏，下次不敢开口时，把这两句说一遍。拾句英语，听懂一句，再把它说出来。')]),
        ],
    },
    '谷爱凌_继续成长': {
        'style': 'v1',          # 已发布的浅色版，锁定样式以便原样复现
        'foot': True,           # 已发布：保留底部分隔线与页脚
        'url': True,            # 已发布：页脚保持官网链接原样
        'speed': 1.0,           # 已发布：原速（2026-09 起新片默认 1.2 倍速）
        'fonts': 'heiti',       # 已发布：黑体（2026-09 起新片默认宋体）
        'model': LEGACY_MODEL,  # 已发布：eleven_multilingual_v2（新片默认 eleven_v3）
        'voice_settings': LEGACY_VOICE_SETTINGS,   # 已发布：style 0 + 带 speed（新片默认 style 0.4、不带 speed）
        'cards': [
            dict(n='01', title='总觉得自己还不够好？',
                 lines=[(990, '听听谷爱凌怎么说。', 60, 'green', False),
                        (1110, '两句话，练习继续成长', 48, 'fg', False)],
                 speech=[('zh', '总觉得自己还不够好？听听谷爱凌怎么说。')],
                 source=(66.0, None)),
            dict(n='02', title='先听原句 / 01',
                 lines=[(950, 'I wasn’t the only', 56, 'fg', True),
                        (1030, 'girl anymore.', 72, 'green', True),
                        (1220, '我不再是那个唯一的女孩了。', 45, 'fg', False)],
                 source=(70.03, 71.10)),
            dict(n='03', title='先听原句 / 02',
                 lines=[(950, 'Sport culture still has', 54, 'fg', True),
                        (1030, 'room to grow.', 72, 'green', True),
                        (1220, '体育文化还有成长的空间。', 45, 'fg', False)],
                 source=(86.74, 88.60)),
            dict(n='04', title='句式 01 / 不再……',
                 lines=[(480, 'not … anymore', 75, 'green', True),
                        (600, '不再……', 60, 'fg', False),
                        (860, 'I wasn’t the only girl', 54, 'fg', True),
                        (945, 'anymore.', 66, 'green2', True),
                        (1180, '说的是：以前是这样，', 45, 'mute', False),
                        (1250, '现在已经不是了。', 45, 'mute', False)],
                 speech=[('zh', '第一句，'), ('en', 'not anymore.'),
                         ('zh', '意思是，不再。它说的是，以前是这样，现在已经不是了。')]),
            dict(n='05', title='句式 02 / 还有成长空间',
                 lines=[(480, 'have room to grow', 75, 'green', True),
                        (600, '还有成长的空间', 60, 'fg', False),
                        (860, 'Sport culture still has', 54, 'fg', True),
                        (945, 'room to grow.', 66, 'green2', True),
                        (1180, 'room 不是房间，是空间；', 45, 'mute', False),
                        (1250, 'still 表示“到现在还是”。', 45, 'mute', False)],
                 speech=[('zh', '第二句，'), ('en', 'have room to grow.'),
                         ('zh', '意思是，还有成长的空间。room 不是房间，是空间。')]),
            dict(n='06', title='换成你自己的表达 / 01',
                 lines=[(490, 'I wasn’t the only', 51, 'mute', True),
                        (565, 'girl anymore.', 54, 'mute', True),
                        (680, '↓', 81, 'green', False),
                        (820, 'I’m not afraid to', 57, 'fg', True),
                        (900, 'speak English anymore.', 63, 'green2', True),
                        (1100, '我不再害怕说英语了。', 50, 'fg', False)],
                 speech=[('zh', '换掉主语，就能用在你自己身上。'),
                         ('en', 'I’m not afraid to speak English anymore.')]),
            dict(n='07', title='换成你自己的表达 / 02',
                 lines=[(490, 'Sport culture still has', 51, 'mute', True),
                        (565, 'room to grow.', 54, 'mute', True),
                        (680, '↓', 81, 'green', False),
                        (820, 'My English still has', 57, 'fg', True),
                        (900, 'room to grow.', 63, 'green2', True),
                        (1100, '我的英语还有进步空间。', 50, 'fg', False)],
                 speech=[('zh', '第二句也一样。'), ('en', 'My English still has room to grow.')]),
            dict(n='08', title='现在，练这两句',
                 lines=[(470, '01  听一遍', 56, 'green2', False),
                        (660, 'I’m not afraid to', 60, 'fg', True),
                        (740, 'speak English anymore.', 66, 'green', True),
                        (880, 'My English still has', 60, 'fg', True),
                        (960, 'room to grow.', 66, 'green', True),
                        (1160, '我不再害怕说英语了。', 48, 'mute', False),
                        (1230, '我的英语还有进步空间。', 48, 'mute', False)],
                 speech=[('zh', '先听一遍。'),
                         ('en', 'I’m not afraid to speak English anymore. My English still has room to grow.')]),
            dict(n='09', title='现在，轮到你开口',
                 lines=[(480, '02  不看英文，说一次', 56, 'green2', False),
                        (780, '我不再害怕说英语了。', 72, 'fg', False),
                        (900, '我的英语还有进步空间。', 72, 'green', False),
                        (1180, '留 3 秒，试着说出来', 48, 'mute', False)],
                 speech=[('zh', '现在不看英文，自己说一遍。')],
                 tail=3.1),
            dict(n='10', title='最后，补完这两句',
                 lines=[(500, 'I’m not afraid to', 60, 'fg', True),
                        (585, 'speak English ________.', 63, 'green2', True),
                        (860, 'My English still has', 60, 'fg', True),
                        (945, 'room to ________.', 63, 'green2', True),
                        (1220, '想一想，再看答案', 48, 'mute', False)],
                 speech=[('zh', '最后，把这两句补完整。想一想，再看答案。')],
                 tail=3.0),
            dict(n='11', title='答案 / 你也可以这样说',
                 lines=[(500, 'I’m not afraid to', 60, 'fg', True),
                        (585, 'speak English anymore.', 66, 'green', True),
                        (860, 'My English still has', 60, 'fg', True),
                        (945, 'room to grow.', 66, 'green', True),
                        (1190, '我不再害怕说英语了。', 46, 'mute', False),
                        (1260, '我的英语还有进步空间。', 46, 'mute', False)],
                 speech=[('en', 'I’m not afraid to speak English anymore. My English still has room to grow.')]),
            dict(n='12', title='收藏，下次再练一次',
                 lines=[(480, '拾句英语', 105, 'green', False),
                        (660, '听懂一句', 72, 'fg', False),
                        (770, '再把它说出来', 72, 'fg', False),
                        (1040, '今天记住两个结构', 48, 'mute', False),
                        (1170, 'not … anymore', 54, 'green2', True),
                        (1260, 'have room to grow', 54, 'green2', True)],
                 speech=[('zh', '先收藏，下次觉得自己不够好的时候，把这两句说一遍。拾句英语，听懂一句，再把它说出来。')]),
        ],
    },
    '谷爱凌_你也能': {
        'style': 'v1',          # 已发布的浅色版，锁定样式以便原样复现
        'foot': True,           # 已发布：保留底部分隔线与页脚
        'url': True,            # 已发布：页脚保持官网链接原样
        'speed': 1.0,           # 已发布：原速（2026-09 起新片默认 1.2 倍速）
        'fonts': 'heiti',       # 已发布：黑体（2026-09 起新片默认宋体）
        'model': LEGACY_MODEL,  # 已发布：eleven_multilingual_v2（新片默认 eleven_v3）
        'voice_settings': LEGACY_VOICE_SETTINGS,   # 已发布：style 0 + 带 speed（新片默认 style 0.4、不带 speed）
        'cards': [
            dict(n='01', title='别人行，我不行？',
                 lines=[(990, '听听谷爱凌怎么说。', 60, 'green', False),
                        (1110, '两句话，练习「我也行」', 48, 'fg', False)],
                 speech=[('zh', '看别人做得那么好，就觉得自己不行？听听谷爱凌怎么说。')],
                 source=(121.0, None)),
            dict(n='02', title='先听原句 / 01',
                 lines=[(950, 'We’re the same age and', 51, 'fg', True),
                        (1030, 'she’s out there doing that.', 51, 'fg', True),
                        (1120, 'I can too.', 66, 'green', True),
                        (1260, '她在那儿做着那件事，我也能。', 45, 'fg', False)],
                 source=(106.24, 109.50)),
            dict(n='03', title='先听原句 / 02',
                 lines=[(950, 'I’m great,', 57, 'fg', True),
                        (1030, 'I’m more than okay.', 66, 'green', True),
                        (1220, '我很好，而且是好得多。', 45, 'fg', False)],
                 source=(132.65, 134.55)),
            dict(n='04', title='句式 01 / 我也能',
                 lines=[(480, 'I can too.', 80, 'green', True),
                        (610, '我也能／我也行', 60, 'fg', False),
                        (880, 'too 放句末，表示「也」', 45, 'mute', False),
                        (960, 'She speaks English at work,', 54, 'fg', True),
                        (1040, 'and I can too.', 66, 'green2', True),
                        (1250, '她在工作中说英语，我也可以。', 45, 'fg', False)],
                 speech=[('zh', '第一句，'), ('en', 'I can too.'),
                         ('zh', '意思是，我也能。too 放在句末，表示「也」。')]),
            dict(n='05', title='句式 02 / 不止是「还行」',
                 lines=[(470, 'more than + 形容词', 72, 'green', False),
                        (600, '意思是「远不止……」「……得多」', 54, 'fg', False),
                        (880, 'I’m okay.', 58, 'mute', True),
                        (960, '还行。', 48, 'mute', False),
                        (1090, 'I’m more than okay.', 66, 'green2', True),
                        (1260, '好得多，好极了。', 48, 'fg', False)],
                 speech=[('zh', '第二句，'), ('en', 'more than okay.'),
                         ('zh', 'more than 后面接形容词，意思是，远不止。I am more than okay，就是好得多。')]),
            dict(n='06', title='换成你自己的表达',
                 lines=[(490, 'She’s out there doing that.', 51, 'mute', True),
                        (565, 'I can too.', 54, 'mute', True),
                        (680, '↓', 81, 'green', False),
                        (820, 'She speaks English at work,', 54, 'fg', True),
                        (900, 'and I can too.', 63, 'green2', True),
                        (1100, '她在工作中说英语，我也可以。', 50, 'fg', False)],
                 speech=[('zh', '换成你自己的事。'),
                         ('en', 'She speaks English at work, and I can too.')]),
            dict(n='07', title='现在，练这两句',
                 lines=[(470, '01  听一遍', 56, 'green2', False),
                        (650, 'I can too.', 66, 'green', True),
                        (730, '我也能。', 48, 'mute', False),
                        (880, 'I’m more than okay.', 66, 'green', True),
                        (960, '我很好，好得多。', 48, 'mute', False),
                        (1200, '两句连起来说一遍', 46, 'mute', False)],
                 speech=[('zh', '先听一遍。'), ('en', 'I can too. I’m more than okay.')]),
            dict(n='08', title='现在，轮到你开口',
                 lines=[(480, '02  不看英文，说一次', 56, 'green2', False),
                        (780, '我也能。', 72, 'fg', False),
                        (900, '我很好，好得多。', 72, 'green', False),
                        (1180, '留 3 秒，试着说出来', 48, 'mute', False)],
                 speech=[('zh', '现在不看英文，自己说一遍。')],
                 tail=3.1),
            dict(n='09', title='最后，补完这两句',
                 lines=[(500, 'She speaks English at work,', 54, 'mute', True),
                        (580, 'and I can ______.', 63, 'green2', True),
                        (880, 'I’m ______ than okay.', 63, 'green2', True),
                        (1200, '想一想，再看答案', 48, 'mute', False)],
                 speech=[('zh', '最后，把这两句补完整。想一想，再看答案。')],
                 tail=3.0),
            dict(n='10', title='答案 / 你也可以这样说',
                 lines=[(500, 'She speaks English at work,', 54, 'fg', True),
                        (580, 'and I can too.', 66, 'green', True),
                        (860, 'I’m more than okay.', 66, 'green', True),
                        (1160, '她在工作中说英语，我也可以。', 46, 'mute', False),
                        (1230, '我很好，而且是好得多。', 46, 'mute', False)],
                 speech=[('en', 'She speaks English at work, and I can too. I’m more than okay.')]),
            dict(n='11', title='收藏，下次再练一次',
                 lines=[(480, '拾句英语', 105, 'green', False),
                        (660, '听懂一句', 72, 'fg', False),
                        (770, '再把它说出来', 72, 'fg', False),
                        (1040, '今天记住两个结构', 48, 'mute', False),
                        (1170, 'I can too.', 54, 'green2', True),
                        (1260, 'more than + 形容词', 48, 'green2', False)],
                 speech=[('zh', '先收藏，下次觉得自己不如别人的时候，把这两句说一遍。拾句英语，听懂一句，再把它说出来。')]),
        ],
    },
    # ===== 播客素材（另一支片子）：开场寒暄 =====
    '谷爱凌_开场寒暄': {
        'style': 'v1',          # 已发布的浅色版，锁定样式以便原样复现
        'foot': True,           # 已发布：保留底部分隔线与页脚
        'url': True,            # 已发布：页脚保持官网链接原样
        'speed': 1.0,           # 已发布：原速（2026-09 起新片默认 1.2 倍速）
        'fonts': 'heiti',       # 已发布：黑体（2026-09 起新片默认宋体）
        'model': LEGACY_MODEL,  # 已发布：eleven_multilingual_v2（新片默认 eleven_v3）
        'voice_settings': LEGACY_VOICE_SETTINGS,   # 已发布：style 0 + 带 speed（新片默认 style 0.4、不带 speed）
        'src': '__DATA_ROOT__/小红书发帖-拾句英语/谷爱凌/谷爱凌最新全英访谈.mp4',
        'cards': [
            # ---- 第 0 章 钩子 + 完整听一遍 ----
            dict(n='01', title='只会说 Nice to meet you？',
                 lines=[(770, '跟着 69 秒访谈学寒暄', 46, 'green', False),
                        (920, '打招呼 · 夸人 · 接夸奖', 44, 'fg', False),
                        (1000, '三套话术，就在一段 69 秒的开场白里', 34, 'mute', False)],
                 speech=[('zh', '打招呼还只会说 Nice to meet you？这段 69 秒的播客开场，藏着五十多个地道表达。打招呼、夸人、接夸奖，三套话术全在里面。'),
                         ('zh', '我们先完整听一遍，再一句一句拆。')]),
            dict(n='02', title='先完整听一遍（上）',
                 lines=[(950, 'Honestly, my feed earlier this year', 46, 'fg', True),
                        (1012, 'was full of your interviews.', 46, 'fg', True),
                        (1170, '先听前 26 秒', 44, 'green2', False),
                        (1240, '不用急着听懂，注意语气和节奏就好', 40, 'mute', False)],
                 speech=[('zh', '先听前 26 秒。不用急着听懂，注意语气和节奏就好。')],
                 source=(0.0, 26.0)),
            dict(n='03', title='先完整听一遍（下）',
                 lines=[(950, '这后半段是客方的回应', 46, 'fg', False),
                        (1030, '也是整段里最值得学的地方', 46, 'green', False),
                        (1190, '听完这一遍，我们就开始拆', 40, 'mute', False)],
                 speech=[('zh', '再听后 43 秒。这后半段是客方的回应，也是整段里最值得学的地方。')],
                 source=(26.0, 69.0)),
            # ---- 第 1 章 打招呼与自我介绍 ----
            dict(n='04', title='先听主持人第一句',
                 lines=[(950, "Eileen, I'm a fan.", 54, 'fg', True),
                        (1025, 'I want you on the show.', 54, 'fg', True),
                        (1190, '他见到谷爱凌，说的是：我是你的粉丝。', 42, 'green', False)],
                 speech=[('zh', '先看主持人第一句话。他见到谷爱凌，说的是——'), ('en', "I'm a fan."),
                         ('zh', '我是你的粉丝。')],
                 source=(14.55, 20.0)),
            dict(n='05', title="I'm a fan.",
                 lines=[(490, "I'm a fan.", 62, 'green', True),
                        (595, '我是你的粉丝。', 46, 'fg', False),
                        (800, "I'm a big fan of your work.", 48, 'fg', True),
                        (880, '我是你作品的粉丝。', 42, 'mute', False),
                        (1070, '见面、发消息、开场白都能用', 42, 'mute', False),
                        (1135, '英语里就这么直接说，不用客套', 42, 'mute', False)],
                 speech=[('zh', '三个词，见面、发消息、开场白都能用。想更具体，可以说 '), ('en', "I'm a big fan"),
                         ('zh', '，或者 '), ('en', "I'm a big fan of your work"),
                         ('zh', '，我是你作品的粉丝。这句不用翻译成中文的客套话，英语里就这么直接说。')]),
            dict(n='06', title='want sb on sth',
                 lines=[(490, 'I want you on the show.', 54, 'fg', True),
                        (575, '我想请你上节目。', 46, 'green', False),
                        (790, 'want + 人 + on / in + 事', 52, 'green2', False),
                        (950, 'I want you on this project.', 48, 'fg', True),
                        (1030, '我想让你加入这个项目。', 42, 'mute', False),
                        (1190, '不是「想要你在」，是「想请你参与」', 42, 'mute', False)],
                 speech=[('zh', '注意这一句：'), ('en', 'I want you on the show.'),
                         ('zh', '这里的 want you on，不是「想要你在」，是「想请你参与」。这是英语里非常地道的一个框架：want 加上人，再加上介词短语，表示想让某人在某个位置、参与某件事。'),
                         ('zh', '迁移一句：'), ('en', 'I want you on this project.'), ('zh', '我想让你加入这个项目。')]),
            dict(n='07', title='come on 的三个意思',
                 lines=[(480, 'you wanted to come on too', 52, 'fg', True),
                        (560, '你也愿意来（上节目）', 46, 'green', False),
                        (760, '1  上节目、来参加', 44, 'green2', False),
                        (835, '2  加油   Come on!', 44, 'green2', False),
                        (910, '3  得了吧   Come on, that’s not true.', 44, 'green2', False),
                        (1120, '别说成 come on to sb，那是对某人搭讪', 42, 'mute', False)],
                 speech=[('zh', 'come on 这个词组有三个常用意思。第一，上节目、来参加，就是这里的用法：'), ('en', 'thanks for coming on the show.'),
                         ('zh', '第二，加油，'), ('en', 'Come on!'),
                         ('zh', '第三，得了吧、别闹了，'), ('en', "Come on, that's not true."),
                         ('zh', '靠语境分辨。另外注意，别说成 come on to somebody，那是对某人搭讪的意思。')]),
            dict(n='08', title='正式开场这三句',
                 lines=[(950, 'welcome to On Purpose.', 52, 'fg', True),
                        (1020, 'Thank you for having me, Jay.', 52, 'fg', True),
                        (1090, "I'm so happy to be here.", 52, 'fg', True),
                        (1250, '主方欢迎 · 客方致谢 · 补一句「很高兴来」', 40, 'mute', False)],
                 speech=[('zh', '正式开场这三句，是英语寒暄里最标准的一组：主方欢迎，客方致谢，再说一句「很高兴来」。')],
                 source=(65.0, 69.0)),
            dict(n='09a', title='welcome to …',
                 lines=[(490, 'welcome to On Purpose.', 56, 'fg', True),
                        (580, '欢迎来到「On Purpose」。', 46, 'green', False),
                        (800, 'welcome to + 节目名 / 公司名 / 城市', 48, 'green2', False),
                        (980, '不用加动词', 44, 'fg', False),
                        (1140, '别说 welcome you to，那是错的', 42, 'mute', False)],
                 speech=[('zh', '第一句，'), ('en', 'welcome to'), ('zh', '，后面直接接节目名、公司名、城市，不用加动词。别说 welcome you to，那是错的。')]),
            dict(n='09b', title='Thank you for having me.',
                 lines=[(490, 'Thank you for having me.', 56, 'fg', True),
                        (580, '谢谢邀请我来。', 46, 'green', False),
                        (800, '做客场景的固定礼貌语', 48, 'green2', False),
                        (950, '播客 · 访谈 · 会议 · 被请到家里', 44, 'fg', False),
                        (1140, 'having me = 招待我、请我来，不是「拥有」', 42, 'mute', False)],
                 speech=[('zh', '第二句，'), ('en', 'Thank you for having me.'), ('zh', '这是做客场景的固定礼貌语。这里的 having me 是「招待我、请我来」的意思，不是「拥有」。播客、访谈、会议、被请到别人家，都能用。')]),
            dict(n='09c', title="I'm so happy to be here.",
                 lines=[(490, "I'm so happy to be here.", 56, 'fg', True),
                        (580, '很高兴来到这里。', 46, 'green', False),
                        (800, '比 Nice to meet you 更贴合「受邀做客」', 48, 'green2', False),
                        (980, '而且常和上一句连起来说：', 44, 'fg', False),
                        (1060, 'Thanks for having me — so happy to be here.', 40, 'mute', True)],
                 speech=[('zh', '第三句，'), ('en', "I'm so happy to be here."), ('zh', '比 Nice to meet you 更贴合受邀做客的场景，而且和上一句常常连起来说。')]),
            # ---- 第 2 章 怎么夸人 ----
            dict(n='10', title='先听主持人怎么开场',
                 lines=[(950, 'Honestly, my feed earlier this year', 46, 'fg', True),
                        (1012, 'was full of your interviews.', 46, 'fg', True),
                        (1190, '他没说「你很红」，而是说自己看到的现象', 42, 'mute', False)],
                 speech=[('zh', '再看主持人的开场。他没说「你很红」，而是说自己看到的现象：我的信息流里全是你的采访。这是英语里很高级的一种夸法。')],
                 source=(0.0, 3.26)),
            dict(n='11', title='my feed / be full of / earlier this year',
                 lines=[(470, 'my feed', 52, 'green2', True),
                        (545, '（社媒的）信息流', 42, 'fg', False),
                        (680, 'be full of', 52, 'green2', True),
                        (755, '满是、全是', 42, 'fg', False),
                        (890, 'earlier this year', 52, 'green2', True),
                        (965, '今年早些时候', 42, 'fg', False),
                        (1150, 'earlier / later + this / that + 时间单位', 42, 'mute', False)],
                 speech=[('zh', '三个点。'), ('en', 'my feed'),
                         ('zh', '就是平台推给你的内容流，「我首页刷到的」就是 it showed up on my feed。'),
                         ('en', 'be full of'), ('zh', '，满是。我的周末全是会：'), ('en', 'My weekend was full of meetings.'),
                         ('en', 'earlier this year'), ('zh', '，今年早些时候。注意顺序是 earlier 加 this 加时间单位：earlier this year、later this month、earlier this week。别说成 this year earlier。')]),
            dict(n='12', title='先听这一句夸人',
                 lines=[(950, "who's this sharp, smart, eloquent,", 46, 'fg', True),
                        (1012, 'incredible athlete?', 46, 'fg', True),
                        (1190, '一口气用了四个形容词', 42, 'green2', False)],
                 speech=[('zh', '第二句夸人，一口气用了四个形容词。我们一个个看。')],
                 source=(3.76, 8.08)),
            dict(n='13', title='sharp / eloquent',
                 lines=[(520, 'sharp', 58, 'green2', True),
                        (605, '脑子快、看问题准', 44, 'fg', False),
                        (760, 'eloquent', 58, 'green2', True),
                        (845, '口才好、表达有说服力', 44, 'fg', False),
                        (1040, 'She’s sharp. 她脑子很快。', 46, 'fg', True),
                        (1120, 'He’s an eloquent presenter.', 46, 'fg', True)],
                 speech=[('zh', 'sharp 形容人的时候不是「锋利」，是「反应快、看问题准」。夸同事专业能力，这个词非常好用：'), ('en', "She's sharp."),
                         ('zh', '她脑子很快。'), ('en', 'eloquent'), ('zh', '是「口才好、表达有说服力」，比 good speaker 高级。名词是 eloquence。')]),
            dict(n='14', title='四个形容词，四个维度',
                 lines=[(490, 'sharp, smart, eloquent, incredible', 46, 'fg', True),
                        (580, '脑子快 · 聪明 · 会讲 · 了不起', 44, 'green', False),
                        (800, '换维度 = 真诚', 50, 'green2', False),
                        (905, '反复说 very good = 客套', 50, 'mute', False),
                        (1120, '这是英语夸人的一条原则', 42, 'mute', False)],
                 speech=[('zh', '四个形容词连着堆，是英语口语里表达热情赞美的常用手法，靠密度制造分量。'),
                         ('zh', '更值得注意的是，这四个词是从四个不同维度夸的：脑子快、聪明、会讲、了不起。这是英语夸人的一个原则——换维度等于真诚，反复说 very good 等于客套。')]),
            dict(n='15', title='再听谷爱凌怎么夸回去',
                 lines=[(950, 'What you do is so incredible.', 50, 'fg', True),
                        (1030, 'you bring this very enlightened', 46, 'fg', True),
                        (1092, 'but also highly accessible, high touch …', 46, 'fg', True),
                        (1250, '一个技巧 + 一串精准的形容词', 42, 'mute', False)],
                 speech=[('zh', '接下来轮到谷爱凌夸回去。她用了两个技巧：一个是把夸奖落在「你做的事」上，另一个是一串精准的形容词。')],
                 source=(26.22, 38.36)),
            dict(n='16', title='what you do is so incredible',
                 lines=[(490, 'What you do is so incredible.', 54, 'fg', True),
                        (575, '你做的事太了不起了。', 46, 'green', False),
                        (790, '主语不是 you，是 what you do', 48, 'green2', False),
                        (960, '夸事，不夸人', 50, 'green', False),
                        (1120, 'What your team pulled off is incredible.', 44, 'mute', True)],
                 speech=[('zh', '注意主语不是 '), ('en', 'you'), ('zh', '，而是 '), ('en', 'what you do'),
                         ('zh', '，你做的事。夸事，不夸人——英语里这样显得更有分量，也不容易让人觉得你在拍马屁。'),
                         ('zh', '迁移一句：'), ('en', 'What your team pulled off is incredible.'),
                         ('zh', '你们团队做成的事太厉害了。')]),
            dict(n='17', title='三个评价内容的词',
                 lines=[(470, 'enlightened', 50, 'green2', True),
                        (545, '有见地、能开人眼界', 42, 'fg', False),
                        (670, 'accessible', 50, 'green2', True),
                        (745, '平易近人、好懂、不设门槛', 42, 'fg', False),
                        (870, 'applicable to real life', 50, 'green2', True),
                        (945, '能用在真实生活里的', 42, 'fg', False),
                        (1130, 'real-life 作形容词要加连字符', 42, 'mute', False)],
                 speech=[('zh', '三个评价内容的词，配起来极好用。'), ('en', 'enlightened'),
                         ('zh', '，有见地的、能开人眼界的。'), ('en', 'accessible'),
                         ('zh', '，平易近人、不设门槛。两个一起用，就是「有深度但接地气」。'),
                         ('en', 'applicable to real life'), ('zh', '，能用在真实生活里的。注意 real-life 作形容词时中间加连字符。')]),
            dict(n='18', title="genuinely believe / make sb's life better",
                 lines=[(480, 'I genuinely believe', 52, 'fg', True),
                        (560, "you've made so many people's lives better.", 44, 'fg', True),
                        (760, "make sb's life better", 50, 'green2', True),
                        (840, '让某人的生活变好', 42, 'fg', False),
                        (1020, '复数人群：people’s lives（不是 lifes）', 42, 'mute', False),
                        (1140, '用现在完成时，强调「到现在造成的影响」', 42, 'mute', False)],
                 speech=[('zh', '最后一句赞美。'), ('en', 'genuinely believe'), ('zh', '，真心相信，比 really believe 更有分量。'),
                         ('en', "make somebody's life better"), ('zh', '，让某人的生活变好，这是评价影响力最地道的说法之一。注意人群是复数时，life 要变成 lives。'),
                         ('zh', '还有时态：you have made，用现在完成时，强调到目前为止造成的影响，比过去式更有分量。')]),
            # ---- 第 3 章 怎么接夸奖（重点）----
            dict(n='19', title='本片最值钱的部分',
                 lines=[(950, "I'm, first of all, so flattered", 46, 'fg', True),
                        (1012, 'to hear you say that.', 46, 'fg', True),
                        (1090, 'Secondly, the feeling is mutual.', 46, 'fg', True),
                        (1250, '她用三拍接下了这句夸奖', 42, 'green2', False)],
                 speech=[('zh', '现在看整段里最值钱的部分：谷爱凌怎么接夸奖。她用了三拍——先接受，再回赠，最后把话题转回对方。')],
                 source=(20.34, 26.22)),
            dict(n='20a', title='第一拍：接受 · be flattered',
                 lines=[(490, 'I’m so flattered to hear you say that.', 48, 'fg', True),
                        (580, '听你这么说，我受宠若惊。', 46, 'green', False),
                        (790, 'be flattered to do sth', 50, 'green2', False),
                        (980, '比一句 thank you 更谦逊、更有分量', 44, 'fg', False),
                        (1150, 'I’m flattered you’d ask.', 44, 'mute', True)],
                 speech=[('zh', '第一拍，接受。'), ('en', 'be flattered'), ('zh', '是「受宠若惊、过奖了」，被夸时的标准得体回应，比一句 thank you 更谦逊、更有分量。'),
                         ('zh', '固定搭配是 be flattered to do something，后面接动词。'), ('en', "I'm flattered you'd ask."), ('zh', '你这么问我很荣幸。')]),
            dict(n='20b', title='一个让口语显得有条理的技巧',
                 lines=[(490, 'first of all', 54, 'green2', True),
                        (570, '首先', 44, 'fg', False),
                        (700, 'secondly', 54, 'green2', True),
                        (780, '其次', 44, 'fg', False),
                        (960, '只要说了 first of all，', 44, 'fg', False),
                        (1030, '听的人就知道后面还有 second', 44, 'fg', False),
                        (1200, 'first of all 也可表「首先（也是最重要的）」', 40, 'mute', False)],
                 speech=[('zh', '一个细节：她用 '), ('en', 'first of all'), ('zh', '和 '), ('en', 'secondly'),
                         ('zh', '把回应标了号。这是让口语显得有条理的廉价技巧——只要你说 first of all，听的人就知道后面还有 second，会等你说完。'),
                         ('zh', '顺便提醒：first of all 也常用来表达「首先，也是最重要的一点」，带一点情绪，比如 First of all, that’s not what I said，首先，我没那么说。')]),
            dict(n='20c', title='第二拍：回赠 · the feeling is mutual',
                 lines=[(490, 'the feeling is mutual', 52, 'green2', True),
                        (580, '彼此彼此、我也有同感', 46, 'green', False),
                        (780, 'Same here. / Likewise.', 48, 'fg', True),
                        (870, '更随意，同样地道', 42, 'mute', False),
                        (1060, '原字幕把 mutual 听成了 neutral', 42, 'mute', False),
                        (1130, '若真是 neutral，那就是一句冷幽默', 42, 'mute', False)],
                 speech=[('zh', '第二拍，回赠。'), ('en', 'the feeling is mutual'),
                         ('zh', '，字面是「这种感觉是相互的」，实际就是「彼此彼此、我也有同感」。回应「我是你的粉丝」「我很喜欢你」这类话，这一句最地道。'),
                         ('zh', '更随意的说法有 '), ('en', 'Same here.'), ('zh', '或者 '), ('en', 'Likewise.'),
                         ('zh', '这里还有个花絮：原字幕把 mutual 听成了 neutral。如果真是 neutral，那就是「我完全没感觉」，是句冷幽默。')]),
            dict(n='21', title='接夸奖的三拍',
                 lines=[(470, '① 接受   I’m so flattered.', 48, 'green2', True),
                        (580, '② 回赠   The feeling is mutual.', 48, 'green2', True),
                        (690, '③ 转回去  What you do is incredible.', 48, 'green2', True),
                        (900, '中文母语者的两个极端：', 44, 'fg', False),
                        (975, '1  拼命推辞，显得不真诚', 40, 'mute', False),
                        (1040, '2  只说 thank you，接受得太快', 40, 'mute', False),
                        (1190, '这结构不是礼貌，是让对话继续下去的技巧', 42, 'green', False)],
                 speech=[('zh', '把三拍连起来看：接受、回赠、转回对方。'),
                         ('zh', '为什么这个结构重要？因为中文母语者最容易走两个极端。一个是拼命推辞，'), ('en', 'No no no, I’m not good.'),
                         ('zh', '在英语里听起来不真诚，甚至像在索要更多夸奖。另一个是只说一句 thank you，接受得太快，显得不够从容。'),
                         ('zh', '这个三拍结构不只是礼貌，它是让对话继续下去的技巧。下一次被夸，你至少可以说：'), ('en', 'That’s very kind of you. I feel the same.')]),
            # ---- 第 4 章 口语小词 ----
            dict(n='22', title='决定你像不像在说人话的小词',
                 lines=[(490, 'Honestly', 54, 'green2', True),
                        (570, '说实话、老实讲', 44, 'fg', False),
                        (700, 'I was like', 54, 'green2', True),
                        (780, '（我心想／我说）', 44, 'fg', False),
                        (910, 'And then / And yeah / just', 54, 'green2', True),
                        (990, '然后／嗯／只是', 44, 'fg', False),
                        (1180, '它们没实际意思，但决定你像不像母语者', 40, 'mute', False)],
                 speech=[('zh', '这一章讲「小词」。它们没有实际意思，但决定了你听起来像不像在说人话——中文母语者最容易漏掉的，就是这一类。')]),
            dict(n='23', title='Honestly / I was like',
                 lines=[(480, 'Honestly, my feed was full of it.', 48, 'fg', True),
                        (560, '说实话，我首页全是这个。', 42, 'mute', False),
                        (720, 'I was like, who is this?', 50, 'fg', True),
                        (800, '我当时心想，这是谁啊。', 42, 'mute', False),
                        (1010, '同族：to be honest / frankly', 44, 'green2', False),
                        (1140, '语域：非常口语，正式写作改用 I thought', 42, 'mute', False)],
                 speech=[('zh', 'Honestly 放在句首，是给后面的话加真诚度的信号。同类还有 to be honest、frankly。'),
                         ('en', 'I was like'), ('zh', '是英语口语第一高频的标记，用来引出你心里的想法，或者转述谁说了什么。'),
                         ('en', 'I was like, who is this?'), ('zh', '我当时心想，这是谁啊。注意语域：它非常口语，正式写作里要换成 I thought 或者 I said。')]),
            dict(n='24', title='And then / And yeah',
                 lines=[(490, 'And then we saw each other …', 50, 'fg', True),
                        (575, '然后我们碰面了……', 42, 'mute', False),
                        (740, 'And yeah, I’ll see you soon.', 50, 'fg', True),
                        (825, '嗯，回头见。', 42, 'mute', False),
                        (1030, '英语口语里大量句子以 And 开头', 44, 'green2', False),
                        (1110, '这不算语病，反而自然', 44, 'fg', False)],
                 speech=[('zh', 'And then，然后，口语叙事最常用的连接。注意英语口语里大量句子以 And 开头，这不算是语病，反而自然。'),
                         ('zh', 'And yeah 里的 yeah 是纯语气词，表示「接着说、随口一提」，没有实际意思。这类小词值得刻意收集。')]),
            dict(n='25', title='just 的软化作用',
                 lines=[(490, 'I was just thinking about you', 50, 'fg', True),
                        (575, '我只是刚好想到你', 42, 'mute', False),
                        (760, 'just 把话说轻，避免显得刻意', 44, 'green2', False),
                        (900, '同类弱化词：', 44, 'fg', False),
                        (975, 'a little / kind of / sort of / maybe', 46, 'fg', True),
                        (1160, '这类词用得越多，听起来越不硬', 42, 'mute', False)],
                 speech=[('zh', '看这句：'), ('en', 'I was just thinking about you.'),
                         ('zh', '这里的 just 不是「仅仅」，而是把话说轻，避免显得刻意或者冒犯。'),
                         ('zh', '同类弱化词还有 '), ('en', 'a little、kind of、sort of、maybe'),
                         ('zh', '。英语里这类词用得越多，听起来越不硬。')]),
            dict(n='26', title='for a minute / I was thinking about you',
                 lines=[(480, 'for a minute / for a second', 50, 'green2', True),
                        (560, '一小会儿（不真的指一分钟）', 42, 'fg', False),
                        (730, 'I was thinking about you.', 50, 'green2', True),
                        (810, '我刚想起你。', 42, 'fg', False),
                        (1000, '比 I remembered you 好听得多', 44, 'mute', False),
                        (1130, 'I was just thinking about you —', 40, 'mute', True),
                        (1190, 'how’s the new role?', 40, 'mute', True)],
                 speech=[('zh', 'for a minute 在口语里指很短的一段时间，通常不是真的指六十秒。同类的还有 for a second、for a moment。'),
                         ('en', 'I was thinking about you.'), ('zh', '，表示「突然想到某人」，用在关心、联络、开场寒暄都很自然，比 I remembered you 好听得多。'),
                         ('zh', '迁移一句：'), ('en', 'I was just thinking about you — how’s the new role?'), ('zh', '我刚还想到你，新岗位怎么样？')]),
            dict(n='27', title='最实用的两句关心话',
                 lines=[(950, 'I don’t know what your day’s been like…', 46, 'fg', True),
                        (1012, 'I hope you’re being a little patient', 46, 'fg', True),
                        (1074, 'with yourself …', 46, 'fg', True),
                        (1250, '主持人对着镜头说给听众的话', 42, 'mute', False)],
                 speech=[('zh', '最后这几句是主持人对着镜头说给听众的，是整段里最实用的两句关心话。我们下一章拆。')],
                 source=(41.78, 54.74)),
            # ---- 第 5 章 容易理解错的表达 ----
            dict(n='28', title='see each other 不是「看见对方」',
                 lines=[(950, 'we saw each other', 50, 'fg', True),
                        (1025, 'at the Dior show in LA.', 50, 'fg', True),
                        (1190, '我们碰面了，不是「我看见了他」', 42, 'green', False),
                        (1290, '小场合用 at，城市用 in', 42, 'mute', False)],
                 speech=[('zh', '第一句，'), ('en', 'we saw each other'), ('zh', '。这不是「我看见了他」，而是「我们碰面了」，暗示双方互相看到、打了招呼。对比一下：'),
                         ('en', 'I saw him.'), ('zh', '，那才是我单方面看到他。'),
                         ('zh', '顺便看这句的介词：'), ('en', 'at the Dior show'), ('zh', '，具体场合用 at；'), ('en', 'in LA'), ('zh', '，城市用 in。一句里两个介词都用对了。')],
                 source=(8.74, 10.95)),
            dict(n='29', title='right 不只是「右」',
                 lines=[(490, 'I came right to you.', 54, 'fg', True),
                        (575, '我径直走向你。', 46, 'green', False),
                        (790, 'right = 径直、直接', 50, 'green2', False),
                        (950, 'right now / right away / right here', 46, 'fg', True),
                        (1030, 'right after / right to the point', 46, 'fg', True),
                        (1200, '高频但中文母语者几乎不主动用', 42, 'mute', False)],
                 speech=[('zh', '这一句是 '), ('en', 'I came right to you.'), ('zh', '，我径直走向你。这里的 right 不是「右」，是「径直、直接」。这是英语里一个高频但中文母语者几乎不主动用的词。'),
                         ('zh', '一组搭配都是同类：'), ('en', 'right now'), ('zh', '现在马上、'), ('en', 'right away'), ('zh', '立刻、'), ('en', 'right here'), ('zh', '就在这里、'), ('en', 'right after'), ('zh', '紧接着、'), ('en', 'right to the point'), ('zh', '直入主题。')]),
            dict(n='30', title='do sth to sb / hand on my heart / in the world',
                 lines=[(470, 'I’ve never done this to anyone else', 48, 'fg', True),
                        (545, 'in the world.', 48, 'fg', True),
                        (740, 'do sth to sb', 48, 'green2', True),
                        (815, '强调动作作用在谁身上（对比 for sb）', 40, 'mute', False),
                        (950, 'hand on my heart', 48, 'green2', True),
                        (1025, '我把手放在心口上 = 千真万确', 40, 'mute', False),
                        (1160, 'anyone else in the world = 世上任何其他人', 40, 'mute', False)],
                 speech=[('zh', '最后这句有三个点。'), ('en', 'do something to somebody'),
                         ('zh', '，强调这个动作作用在谁身上。对比 do something for somebody，是「为某人做事」；用 to 的时候，往往带一点「对某人做了什么」的分量。这一句是「我从没为别人破例过」，用 to 反而更有力。'),
                         ('en', 'hand on my heart'), ('zh', '，我把手放在心口上，表示千真万确，比 believe me 有画面感。'),
                         ('en', 'anyone else in the world'), ('zh', '，世上任何其他人。else 跟在 anyone 后面表示「其他的」，in the world 是给这种绝对表达加码的常见手法。')]),
            # ---- 第 6 章 两个能整句背的句型 ----
            dict(n='31', title='句型一：I don’t know what …, but …',
                 lines=[(950, 'I don’t know what your day’s been like,', 46, 'fg', True),
                        (1012, 'but I was just thinking about you.', 46, 'fg', True),
                        (1190, '先示弱，再给话，让关心显得不冒犯', 42, 'green', False)],
                 speech=[('zh', '第一个句型：'), ('en', 'I don’t know what'), ('zh', '加上从句，'), ('en', 'but'), ('zh', '加后半句。先示弱，再给话，让关心或者建议显得不冒犯。')],
                 source=(41.78, 48.20)),
            dict(n='32', title='这个句型的三个用法',
                 lines=[(470, '给久没联系的同事发消息', 42, 'mute', False),
                        (530, 'I don’t know what your week’s been like,', 42, 'fg', True),
                        (592, 'but I was just thinking about you.', 42, 'fg', True),
                        (740, '约人聊事', 42, 'mute', False),
                        (800, 'I don’t know what the full picture is, but from', 42, 'fg', True),
                        (862, 'where I sit, the timeline is tight.', 42, 'fg', True),
                        (1010, '提意见', 42, 'mute', False),
                        (1070, 'I don’t know how you’re feeling about this,', 42, 'fg', True),
                        (1132, 'but I’d push the deadline.', 42, 'fg', True)],
                 speech=[('zh', '三个能直接用的场景。'),
                         ('zh', '给久没联系的同事发消息：'), ('en', 'I don’t know what your week’s been like, but I was just thinking about you.'),
                         ('zh', '约人聊事：'), ('en', 'I don’t know what the full picture is, but from where I sit, the timeline is tight.'),
                         ('zh', '提意见：'), ('en', 'I don’t know how you’re feeling about this, but I’d push the deadline.')]),
            dict(n='33', title='句型二：I hope you’re being … because you deserve it.',
                 lines=[(950, 'I hope you’re being a little patient with', 46, 'fg', True),
                        (1012, 'yourself, because you deserve it.', 46, 'fg', True),
                        (1200, 'you’re being + 形容词 = 你此刻的做法／状态', 42, 'green2', False)],
                 speech=[('zh', '第二个句型。')],
                 source=(48.76, 52.60)),
            dict(n='34', title='两个语法点 + 一个搭配',
                 lines=[(470, 'You’re kind.', 48, 'fg', True),
                        (545, '你人很好（长期评价）', 40, 'mute', False),
                        (680, 'You’re being kind.', 48, 'green2', True),
                        (755, '你此刻这个做法很体贴', 40, 'mute', False),
                        (910, 'be patient with sb/sth', 48, 'green2', True),
                        (985, '介词用 with，不要用 to', 40, 'mute', False),
                        (1130, 'you deserve it = 这是你应得的（褒贬两用）', 40, 'mute', False)],
                 speech=[('zh', '先说一个小语法点：'), ('en', 'you’re being'), ('zh', '加形容词，表示你现在的做法或者状态，和 '), ('en', 'you are'),
                         ('zh', '加形容词不一样。对比一下：'), ('en', 'You’re kind.'),
                         ('zh', '，是说你这个人的长期评价，你人很好。'), ('en', 'You’re being kind.'), ('zh', '，是说你此刻这个做法很体贴。'),
                         ('zh', '再看搭配：'), ('en', 'be patient with somebody'), ('zh', '，介词用 with，不要用 to。'),
                         ('zh', '最后一句 '), ('en', 'you deserve it'), ('zh', '，是你应得的。注意这一句褒贬两用：这里是正面的，你值得被善待；但如果是别人倒霉，He deserved it 就是他活该。')]),
            # ---- 第 7 章 收尾 ----
            dict(n='35', title='带着这些点，再听一遍',
                 lines=[(950, '现在再完整听一遍', 50, 'fg', False),
                        (1040, '你应该能听出更多东西了', 50, 'green', False),
                        (1210, '69 秒，五十多个地道表达', 40, 'mute', False)],
                 speech=[('zh', '现在带着刚才拆过的这些点，再完整听一遍这段 69 秒。你会发现，能听出来的东西比第一遍多得多。')],
                 source=(0.0, 69.0)),
            dict(n='36', title='跟着读三遍',
                 lines=[(470, '① Thank you for having me.', 48, 'green2', True),
                        (580, '② The feeling is mutual.', 48, 'green2', True),
                        (690, '③ I don’t know what your', 48, 'green2', True),
                        (752, 'day’s been like, but I was just', 48, 'green2', True),
                        (814, 'thinking about you.', 48, 'green2', True),
                        (960, '不用追求完美，先把它说出口', 44, 'fg', False),
                        (1130, '留 3 秒，试着说出来', 44, 'mute', False)],
                 speech=[('zh', '最后挑三句最常用的，跟着读三遍。第一句，做客万能：'), ('en', 'Thank you for having me.'),
                         ('zh', '第二句，接夸奖：'), ('en', 'The feeling is mutual.'),
                         ('zh', '第三句，关心开场：'), ('en', 'I don’t know what your day’s been like, but I was just thinking about you.'),
                         ('zh', '不用追求完美，先把它说出口。')],
                 tail=3.1),
            dict(n='37', title='收藏，下次见面前过一遍',
                 lines=[(480, '拾句英语', 100, 'green', False),
                        (650, '一段寒暄，三种话术', 56, 'fg', False),
                        (800, '打招呼   Thank you for having me.', 44, 'green2', True),
                        (880, '夸人     What you do is incredible.', 44, 'green2', True),
                        (960, '接夸奖   The feeling is mutual.', 44, 'green2', True),
                        (1150, '下一期拆「身份之争」', 42, 'mute', False),
                        (1225, '听懂一句，再把它说出来', 42, 'mute', False)],
                 speech=[('zh', '这一期我们拆了三套话术：怎么打招呼，怎么夸人，怎么接夸奖。下一期我们看第二段，也就是「身份之争」——她怎么回答「简历之外，你希望别人知道你什么」。'),
                         ('zh', '先收藏，下次见面之前，把这三句过一遍。拾句英语，听懂一句，再把它说出来。')]),
        ],
    },
    # ===== 播客素材（另一支片子）：身份之争 =====
    '谷爱凌_身份之争': {
        'foot': True,           # 已发布：保留底部分隔线与页脚
        'url': True,            # 已发布：页脚保持官网链接原样
        'speed': 1.0,           # 已发布：原速（2026-09 起新片默认 1.2 倍速）
        'fonts': 'heiti',       # 已发布：黑体（2026-09 起新片默认宋体）
        'model': LEGACY_MODEL,  # 已发布：eleven_multilingual_v2（新片默认 eleven_v3）
        'voice_settings': LEGACY_VOICE_SETTINGS,   # 已发布：style 0 + 带 speed（新片默认 style 0.4、不带 speed）
        'src': '__DATA_ROOT__/小红书发帖-拾句英语/谷爱凌/谷爱凌最新全英访谈.mp4',
        'cards': [
            # ---- 第 0 章 钩子 + 完整听一遍 ----
            dict(n='01', title='简历之外，你希望别人知道你什么？',
                 lines=[(770, '跟着 2 分钟访谈学表达', 46, 'green', False),
                        (920, '身份 · 标签 · 自我认知', 44, 'fg', False),
                        (1000, '52 个表达，就藏在 2 分 5 秒里', 34, 'mute', False)],
                 speech=[('zh', '简历之外，你希望别人知道你什么？这段 2 分 5 秒的访谈里，谷爱凌回答了一个最难的问题——怎么让人看见「运动员」标签之外的自己。'),
                         ('zh', '我们从 52 个表达里挑最值钱的一组，先完整听一遍，再一句一句拆。')]),
            dict(n='02', title='先完整听一遍（上）',
                 lines=[(950, 'athletes maybe go to school,', 46, 'fg', True),
                        (1022, 'but they don’t really', 46, 'fg', True),
                        (1094, 'go to school.', 46, 'fg', True),
                        (1230, '先听前 80 秒', 44, 'green2', False),
                        (1300, '不用急着听懂，注意语气和节奏就好', 40, 'mute', False)],
                 speech=[('zh', '先听前 80 秒。不用急着听懂，注意语气和节奏就好。')],
                 source=(65.11, 144.75)),
            dict(n='03', title='先完整听一遍（下）',
                 lines=[(950, '后半段讲的是教育时间线', 44, 'fg', False),
                        (1030, '提前毕业 · 间隔年 · 澄清误解', 44, 'green', False),
                        (1200, '听完这一遍，我们就开始拆', 40, 'mute', False)],
                 speech=[('zh', '再听后 46 秒。后半段讲的是她的教育时间线——怎么提前毕业、怎么安排间隔年，还有一句漂亮的澄清。听完这一遍，我们就开始拆。')],
                 source=(144.75, 190.77)),
            # ---- 第 1 章 提问与自我介绍的框架（Jay 的问法）----
            dict(n='04', title='主持人这样开场',
                 lines=[(490, 'start off by doing sth', 56, 'green', True),
                        (590, '先做某事、先来……', 46, 'fg', False),
                        (800, 'you’re doing everything', 56, 'green2', True),
                        (900, '你现在什么都做', 44, 'fg', False),
                        (1120, '后面接动名词，不是 to do', 44, 'mute', False)],
                 speech=[('zh', '主持人开场用的第一个结构：'), ('en', 'start off by doing something'),
                         ('zh', '，先做某事、先来……。后面接动名词，不是 to do，比 First, I want to ask 自然得多。'),
                         ('zh', '他顺手还夸了一句 '), ('en', 'you’re doing everything'),
                         ('zh', '，你现在什么都做、身兼数职，带一点佩服的语气，不是「什么事都做完了」。')]),
            dict(n='05', title='从哪儿毕业、在哪个领域',
                 lines=[(490, 'graduate from', 58, 'green', True),
                        (580, '从某校毕业，from 别漏', 46, 'fg', False),
                        (780, 'in your field', 56, 'green2', True),
                        (870, '在你所在的领域', 44, 'fg', False),
                        (1080, '正式场合里 from 一定要加', 44, 'mute', False)],
                 speech=[('zh', '这两个是简历和面试里的高频。'), ('en', 'graduate from'),
                         ('zh', '，从某校毕业，介词 from 千万别漏。美式口语里有人会省掉，正式场合一定要加。'),
                         ('zh', '再来一个：'), ('en', 'in your field'), ('zh', '，在你所在的领域。'),
                         ('zh', '主持人把这两个叠在一起说：'), ('en', 'you’ve graduated from one of the best schools in the world'), ('zh', '。')]),
            dict(n='06', title='one of + 最高级 + 复数名词',
                 lines=[(490, 'one of the highest regarded', 54, 'green', True),
                        (580, '最受推崇的……之一', 44, 'fg', False),
                        (780, 'one of the best schools', 52, 'green2', True),
                        (870, '最好的学校之一', 44, 'fg', False),
                        (1080, '后面接复数名词，动词用单数', 44, 'mute', False)],
                 speech=[('zh', '这个结构值得单拎出来：'), ('en', 'one of the highest regarded athletes in the world'),
                         ('zh', '，全世界最受推崇的运动员之一。结构是 one of the 加最高级，再加复数名词。'),
                         ('zh', '提醒一句：one of 后面永远接复数，但整个短语作主语时动词用单数，比如 '),
                         ('en', 'One of the best things is…'), ('zh', '。')]),
            dict(n='07', title='先承认，再问下一步',
                 lines=[(490, 'We know all of this', 56, 'fg', True),
                        (580, 'from your resume.', 60, 'green', True),
                        (780, '这些，我们都能从你简历上看到', 44, 'fg', False),
                        (990, 'resume 美式 / CV 英式', 46, 'green2', True),
                        (1160, '先摆出已知的，再问未知的', 44, 'mute', False)],
                 speech=[('zh', '这句话是引出「简历之外」的漂亮铺垫。'), ('en', 'We know all of this from your resume.'),
                         ('zh', '，这些我们都能从你的简历上看到——先承认已知的，再问未知的。'),
                         ('zh', '顺便记：'), ('en', 'resume'),
                         ('zh', ' 是美式说法，英式和学术场合说 CV，这条对求职、留学的人是刚需。')]),
            dict(n='08', title='本段最会问的一句',
                 lines=[(950, 'What’s something you wish', 50, 'fg', True),
                        (1030, 'people knew about you…?', 52, 'green', True),
                        (1200, '有没有什么是你希望别人知道的？', 44, 'mute', False),
                        (1300, '两层定语从句叠在一起', 44, 'green2', False)],
                 speech=[('zh', '这是访谈和面试里最会问的问题之一。'), ('en', 'What’s something you wish people knew about you that you couldn’t read on your resume?'),
                         ('zh', '有没有什么，是你希望别人知道、又不会出现在简历上的？'),
                         ('zh', '两层定语从句叠在一起，拆开就是万能模块：What’s something you wish 加从句——面试、自我介绍都能直接套用。')],
                 source=(83.95, 87.79)),
            # ---- 第 2 章 描述「人设」与标签 ----
            dict(n='09', title='最有共鸣的一句',
                 lines=[(950, 'wanting to justify my academics', 48, 'fg', True),
                        (1030, 'as independent from sport', 50, 'green', True),
                        (1200, '想证明「学业和运动彼此独立」', 44, 'mute', False),
                        (1300, 'justify A as B = 把 A 说成 B', 44, 'green2', False)],
                 speech=[('zh', '第一句，先说一个动词结构。'), ('en', 'justify A as B'),
                         ('zh', '，把 A 说成 B、为 A 辩解。justify 后面直接接宾语，不要说 justify for。'),
                         ('zh', '她原话是：'), ('en', 'there was this sense of wanting to justify my academics as independent from sport'),
                         ('zh', '，有一种想要证明「我的学业和运动彼此独立」的冲动。'),
                         ('zh', '里面还有两个点：'), ('en', 'be independent from'), ('zh', '，与……无关；以及 '),
                         ('en', 'there was this sense of wanting to do something'), ('zh', '，适合描述说不清的心态。')],
                 source=(88.11, 94.93)),
            dict(n='10', title='自嘲，是英语社交的安全区',
                 lines=[(490, 'the biggest nerd', 58, 'green', True),
                        (580, '最大的书呆子（自嘲）', 46, 'fg', False),
                        (780, 'be known as', 56, 'green2', True),
                        (870, '被当成……（as 接身份）', 44, 'fg', False),
                        (1080, 'be known for 接特点，别混', 44, 'mute', False)],
                 speech=[('zh', '她在运动圈里说：'), ('en', 'I would be, you know, the biggest nerd'),
                         ('zh', '，我就是那个最大的书呆子。'), ('en', 'nerd'),
                         ('zh', ' 这个词在英语里褒贬皆可，如今更偏「对某个领域超投入的人」，自嘲时最好用，是英语社交的安全区。'),
                         ('zh', '再看 '), ('en', 'be known as'),
                         ('zh', '，被当成某种身份；'), ('en', 'be known for'),
                         ('zh', ' 后面接特点，比如 known for his humor。as 接身份，for 接原因，这两个别混。')]),
            dict(n='11', title='换成你自己的标签',
                 lines=[(490, 'be known as …', 56, 'green2', True),
                        (580, '↓ 换成你自己的', 44, 'fg', False),
                        (760, 'I’m known as the person', 54, 'fg', True),
                        (845, 'who always asks questions.', 56, 'green', True),
                        (1080, '大家都当我是那个总爱提问的人。', 44, 'mute', False)],
                 speech=[('zh', '迁移一句，换成你自己：'), ('en', 'I’m known as the person who always asks questions.'),
                         ('zh', '这是我们的原创练习句，不是她说的。你可以把 as 后面的身份换成自己的，比如 the person who always takes notes。')]),
            # ---- 第 3 章 说「成见」与「普遍看法」 ----
            dict(n='12', title='成见，才是最难的对手',
                 lines=[(950, 'the general assumption', 52, 'fg', True),
                        (1030, 'is that athletes maybe', 52, 'fg', True),
                        (1110, 'go to school, but they don’t', 52, 'fg', True),
                        (1190, 'really go to school.', 52, 'green', True),
                        (1330, '普遍的看法（成见）是……', 44, 'green2', False)],
                 speech=[('zh', '她先点出成见：'), ('en', 'the general assumption or presumption is that athletes maybe go to school, but they don’t really go to school'),
                         ('zh', '。普遍的看法是：运动员也许上学，但并不是真的在上学。'),
                         ('zh', '结构是 '), ('en', 'the general assumption is that'),
                         ('zh', ' 加一个完整句子。assumption 偏「默认想法」，presumption 更带主观的「想当然」，议论文、演讲切入观点时非常好用。')],
                 source=(105.53, 116.81)),   # 切点按词级时间戳对齐：到第 2 个 school 结束，讲全「assumption … is that」
            dict(n='13', title='把它说成「整个社会」的想法',
                 lines=[(490, 'hold a presumption', 56, 'green2', True),
                        (580, '抱着某种想当然', 46, 'fg', False),
                        (780, 'as a society', 56, 'green2', True),
                        (870, '从整个社会的层面', 44, 'fg', False),
                        (1080, 'hold a view / hold a belief', 46, 'mute', True)],
                 speech=[('zh', '接着她说，这是整个社会抱有的想法：'), ('en', 'the assumption or presumption that maybe we hold socially, as a society'),
                         ('zh', '。'), ('en', 'hold'),
                         ('zh', ' 后面直接接看法，hold an opinion、hold a belief、hold a view，都表示抱持某种看法，书面但不生硬。'),
                         ('zh', '再看 '), ('en', 'as a society'), ('zh', '，从整个社会的层面来说，议论文里很好用。')]),
            dict(n='14', title='同一句话，说出两重意思',
                 lines=[(950, 'athletes maybe go to school,', 50, 'fg', True),
                        (1030, 'but they don’t really', 50, 'fg', True),
                        (1110, 'go to school.', 54, 'green', True),
                        (1290, '同一句话，说出两重意思', 44, 'mute', False)],
                 speech=[('zh', '这句非常妙。'), ('en', 'athletes maybe go to school, but they don’t really go to school'),
                         ('zh', '，运动员也许「上学」，但并不是真的在「上学」。'),
                         ('zh', '同一个短语重复，靠重音和 really 把两个 go to school 说出两重意思。这是英语里制造反差的常用手法，写标题、演讲都好用。')],
                 source=(114.80, 116.81)),   # 只截这两个 go to school，干净的一小段
            # ---- 第 4 章 谈自我认知 ----
            dict(n='15', title='undercut：暗中拆掉一种印象',
                 lines=[(490, 'undercut sth', 58, 'green', True),
                        (580, '削弱、暗中拆掉（观点／印象）', 46, 'fg', False),
                        (780, 'undercutting that was harder', 50, 'green2', True),
                        (865, 'for me and, at the same time,', 50, 'fg', True),
                        (1080, '比 break 精准，多接抽象对象', 44, 'mute', False)],
                 speech=[('zh', '先说一个比 break 精准得多的动词：'), ('en', 'undercut'),
                         ('zh', '，削弱、暗中拆掉，多接观点、印象、地位这类抽象对象。'),
                         ('zh', '她原话是：'), ('en', 'And I think undercutting that was harder for me'),
                         ('zh', '，而要打破这种成见，对我来说更难。')]),
            dict(n='16', title='本片金句：骨子里，我是……',
                 lines=[(950, 'at my core, I think of myself', 48, 'fg', True),
                        (1030, 'more as an intellectual person', 48, 'green', True),
                        (1210, '骨子里我是个靠脑子的人', 44, 'mute', False),
                        (1310, 'think of oneself as = 把自己看作', 44, 'green2', False)],
                 speech=[('zh', '本片最值钱的一句。'), ('en', 'at my core'),
                         ('zh', '，骨子里、本质上是，谈价值观和自我认知的黄金短语。'),
                         ('zh', '她说：'), ('en', 'at my core, I think of myself more as an intellectual person'),
                         ('zh', '，骨子里，我更把自己看作一个靠脑子的人。'),
                         ('zh', '注意 '), ('en', 'think of oneself as'),
                         ('zh', '，as 不能省；同样说法的还有 see myself as、regard myself as，但 consider myself 后面不加 as。')],
                 source=(125.07, 130.53)),   # 从「at my core」起，到「chose to do sports」止，整句干净
            dict(n='17', title='intellectual：重思考的',
                 lines=[(490, 'intellectual', 58, 'green', True),
                        (580, '重思考的、知识型的', 46, 'fg', False),
                        (780, 'choose to do sth', 56, 'green2', True),
                        (870, '主动选择去做某事', 44, 'fg', False),
                        (1080, '比 smart 更强调爱思考、有学养', 44, 'mute', False)],
                 speech=[('zh', '她说自己想被看成 '), ('en', 'an intellectual person who chose to do sports'),
                         ('zh', '，一个重思考的人，只是选择了做运动。'),
                         ('en', 'intellectual'), ('zh', ' 比 smart 更强调爱思考、有学养，作名词就是「知识分子」。'),
                         ('zh', '再看 '), ('en', 'choose to do something'),
                         ('zh', '，比 decide to 更强调「主动选的」，用来说这是自己的意愿，而不是被安排的。')]),
            dict(n='18', title='cerebral：用脑的',
                 lines=[(490, 'cerebral', 58, 'green2', True),
                        (580, '重思考的、用脑的（书面偏褒）', 46, 'fg', False),
                        (780, 'apply A in a B context', 52, 'green2', True),
                        (870, '把 A 用在 B 场景里', 44, 'fg', False),
                        (1080, 'take 作名词 = 看法、做法', 44, 'mute', False)],
                 speech=[('zh', '再看一组。'), ('en', 'cerebral'),
                         ('zh', '，重思考的、用脑的，书面偏褒。'),
                         ('zh', '她要把这种用脑的做法用到运动里：'), ('en', 'to apply that kind of cerebral take in like an athletic context'),
                         ('zh', '。'), ('en', 'apply A in a B context'),
                         ('zh', '，把 A 用在 B 场景里，in a … context 是学术和职场高频。'),
                         ('zh', '顺便记 '), ('en', 'take'), ('zh', ' 作名词是「看法、做法」，口语里 '),
                         ('en', 'What’s your take?'), ('zh', ' 就是「你怎么看」。')]),
            dict(n='19', title='本可以是别的，而不是……',
                 lines=[(950, 'It could have been something else', 46, 'fg', True),
                        (1030, 'versus an athlete who thinks', 48, 'fg', True),
                        (1110, 'they are smart, right?', 52, 'green', True),
                        (1290, '本可以是别的，而不是……', 44, 'mute', False)],
                 speech=[('zh', '这句在做一个身份区分。'), ('en', 'It could have been something else versus an athlete who thinks they are smart, right?'),
                         ('zh', '本可以是别的，我只是恰好选了运动，而不是「一个自以为聪明的运动员」。'),
                         ('zh', '两个点：'), ('en', 'could have been'),
                         ('zh', ' 是虚拟语气，本来可能是、实际没发生；这里的 '), ('en', 'versus'),
                         ('zh', ' 不是「对抗」，是「而不是」。')],
                 source=(135.77, 141.67)),
            dict(n='20', title='名词 + to make 的结构',
                 lines=[(950, 'I think that’s like an', 50, 'fg', True),
                        (1030, 'important distinction to make.', 50, 'green', True),
                        (1210, '我觉得这个区分很重要', 44, 'mute', False),
                        (1310, '名词 + to make 很好用', 44, 'green2', False)],
                 speech=[('zh', '她说：'), ('en', 'I think that’s like an important distinction to make.'),
                         ('zh', '，我觉得这个区分很重要。'),
                         ('zh', '记住这个结构：名词加 to make。除了 distinction，你还可以说 '),
                         ('en', 'a point to make'), ('zh', ' 一个要说明的点、'), ('en', 'a call to make'),
                         ('zh', ' 一个要做的决定、'), ('en', 'a decision to make'), ('zh', ' 一个要做的选择。')],
                 source=(141.89, 144.21)),   # 从词的起点起，避开前一句 right? 的尾音
            # ---- 第 5 章 教育与时间线 ----
            dict(n='21', title='get into：考上',
                 lines=[(490, 'get into Stanford', 58, 'green', True),
                        (580, '考上斯坦福', 46, 'fg', False),
                        (780, 'get into + 学校 = 被录取', 46, 'green2', True),
                        (870, '比 be admitted to 口语得多', 46, 'fg', False),
                        (1080, '单独问：Did you get in?', 44, 'mute', False)],
                 speech=[('zh', '接下来进入她的教育时间线。第一句。'), ('en', 'getting into Stanford when I was 16'),
                         ('zh', '，16 岁考上斯坦福。'), ('en', 'get into'),
                         ('zh', ' 加学校，就是被录取，比 be admitted to 口语得多；单独用 '),
                         ('en', 'get in'), ('zh', ' 也行，比如 Did you get in，考上了吗。')]),
            dict(n='22', title='so that：这样我就有了',
                 lines=[(490, 'so that I had …', 58, 'green', True),
                        (580, '这样我就有了……', 46, 'fg', False),
                        (780, 'doing that before the Olympics', 48, 'green2', True),
                        (865, 'so that + 从句，表目的或结果', 44, 'fg', False),
                        (1080, '比单用 so 更完整', 44, 'mute', False)],
                 speech=[('zh', '她讲自己怎么排时间：'), ('en', 'doing that before the Olympics so that I had my, what would have been my senior year and then a gap year'),
                         ('zh', '。'), ('en', 'so that'),
                         ('zh', ' 后面接一个完整从句，表示目的或结果，比单用 so 更完整。')]),
            dict(n='23', title='虚拟语气做定语：本该是……的',
                 lines=[(950, 'what would have been', 52, 'fg', True),
                        (1030, 'my senior year and then a gap year.', 46, 'green', True),
                        (1210, '本该是我的高四，再加一个间隔年', 44, 'mute', False),
                        (1310, '虚拟语气做定语，很地道', 44, 'green2', False)],
                 speech=[('zh', '这句很地道。'), ('en', 'what would have been my senior year'),
                         ('zh', '，本该是我的高四。这是虚拟语气做定语，表示「本来会是、但实际不是」，中文母语者几乎不会主动用，是拉开差距的一句。'),
                         ('zh', '后面还有 '), ('en', 'and then a gap year'),
                         ('zh', '，间隔年，动词用 take——take a gap year，不用 do。')],
                 source=(152.83, 155.19)),
            dict(n='24', title='full time 与 go pro',
                 lines=[(490, 'full time / full-time', 56, 'green2', True),
                        (590, '全职（作形容词加连字符）', 46, 'fg', False),
                        (800, 'go pro / turn pro', 54, 'green2', True),
                        (890, '转为职业选手', 44, 'fg', False),
                        (1090, 'work full time / a full-time job', 46, 'fg', True)],
                 speech=[('zh', '两个跟职业相关的说法。'), ('en', 'those two years to be like full time'),
                         ('zh', '，那两年她是全职。作状语写 full time，作形容词要加连字符，a full-time job。'),
                         ('en', 'that was my first time being pro'),
                         ('zh', '，那是她第一次转为职业。也可以说 turn pro，转职业。')]),
            dict(n='25', title='口语里的两个小连接',
                 lines=[(490, 'as in …', 58, 'green', True),
                        (580, '也就是说、我的意思是', 46, 'fg', False),
                        (780, 'Monday through Friday', 52, 'green2', True),
                        (870, '周一到周五（美式用 through）', 44, 'fg', False),
                        (1080, '英式说 Monday to Friday', 44, 'mute', False)],
                 speech=[('zh', '两个口语里的小表达。'), ('en', 'as in'),
                         ('zh', '，也就是说、我的意思是，用来补充说明前一句，等于 I mean；也可以用来反问澄清，as in?'),
                         ('zh', '再看 '), ('en', 'Monday through Friday'),
                         ('zh', '，周一到周五，美式用 through，英式用 to。原句把时间状语当成身份状态用，非常口语。')]),
            dict(n='26', title='讲成就：史上第一个',
                 lines=[(470, 'the first person in', 52, 'green', True),
                        (550, 'our high school’s history', 52, 'green', True),
                        (640, 'to graduate early', 56, 'green', True),
                        (830, '我们高中历史上第一个提前毕业的人', 42, 'fg', False),
                        (1030, 'make sth work = 想办法让它可行', 42, 'mute', False)],
                 speech=[('zh', '讲自己的成就，用这个结构最完整：'), ('en', 'the first person in our high school’s history to graduate early'),
                         ('zh', '，我是我们高中历史上第一个提前毕业的人。结构是 the first 加人 加 in 加范围 加 to do，这里的 to do 是不定式做定语，不能写成 doing。'),
                         ('zh', '后面还有 '), ('en', 'make sth work'),
                         ('zh', '，想办法让这个安排运作起来、把事情凑成，口语里非常常用。')]),
            # ---- 第 6 章 澄清与强调 ----
            dict(n='27', title='先听一句漂亮的澄清',
                 lines=[(950, 'but it was not because it was', 46, 'fg', True),
                        (1030, 'an Olympic accommodation,', 48, 'fg', True),
                        (1110, 'it was because I had done', 46, 'fg', True),
                        (1190, 'the credits …', 46, 'green', True),
                        (1330, '先听，注意这句话怎么排掉误解', 40, 'mute', False)],
                 speech=[('zh', '最后一段，她在澄清一个误解。先听一遍。')],
                 source=(174.07, 179.73)),
            dict(n='28', title='本段最值得背的澄清句式',
                 lines=[(480, 'it was not because A,', 54, 'green', True),
                        (580, 'it was because B', 58, 'green', True),
                        (790, '不是 A，而是 B', 46, 'fg', False),
                        (990, '先排掉误解，再给真正的原因', 44, 'mute', False),
                        (1160, '比直接说 You’re wrong 温和得多', 44, 'mute', False)],
                 speech=[('zh', '这是全段最值得背下来的澄清句式。'), ('en', 'It was not because A, it was because B.'),
                         ('zh', '先用 not because 排掉那个误解，再用 it was because 给出真正的原因。辟谣、解释误会、面试回答，全都用得上，比直接说 You are wrong 温和得多。')]),
            dict(n='29', title='accommodation：不只是住宿',
                 lines=[(470, 'accommodation', 54, 'green', True),
                        (570, '迁就、特殊安排', 44, 'fg', False),
                        (760, 'do the credits', 54, 'green2', True),
                        (860, '修完学分', 44, 'fg', False),
                        (1060, 'make accommodations for sb', 46, 'mute', True)],
                 speech=[('zh', '两个词。'), ('en', 'accommodation'),
                         ('zh', '，除了住宿，还有「迁就、特殊安排」的意思，make accommodations for somebody 在考试、职场场景很常见。'),
                         ('en', 'do the credits'), ('zh', '，修完学分，do、earn、complete the credits 都可以。')]),
            dict(n='30', title='find a way to do sth',
                 lines=[(470, 'find a way to do sth', 52, 'green', True),
                        (580, '想办法做到某事', 44, 'fg', False),
                        (780, 'found a way to graduate early', 46, 'fg', True),
                        (980, '语气积极务实，比 try to 更笃定', 44, 'mute', False),
                        (1150, 'We’ll find a way to make it work.', 44, 'green2', True)],
                 speech=[('zh', '一个很务实的说法：'), ('en', 'find a way to do something'),
                         ('zh', '，想办法做到某事。语气积极务实，比 try to 更笃定。'),
                         ('zh', '迁移一句，'), ('en', 'We’ll find a way to make it work.'),
                         ('zh', '这是我们的原创练习句——我们会想办法办成的。')]),
            dict(n='31', title='被误解的是……',
                 lines=[(470, 'what’s misunderstood is …', 52, 'green', True),
                        (570, '被误解的地方是……', 46, 'fg', False),
                        (770, 'so I think what’s misunderstood is', 46, 'fg', True),
                        (970, '被动 + 主语从句，客观、不指责对方', 40, 'mute', False),
                        (1140, '比 You misunderstood me 高明', 40, 'mute', False)],
                 speech=[('zh', '这一句是「优雅澄清」的模板。'), ('en', 'what’s misunderstood is'),
                         ('zh', '，被误解的地方是……。被动语态加主语从句，客观、不指责对方，比直接说 You misunderstood me 高明得多。'),
                         ('zh', '她原话是：'), ('en', 'what’s misunderstood is maybe that, how much I value education.')]),
            dict(n='32', title='程度：到……的程度 / 重视',
                 lines=[(470, 'to the extent that', 52, 'green', True),
                        (560, '到……的程度', 44, 'fg', False),
                        (740, 'I value education', 52, 'green2', True),
                        (830, '我重视教育', 44, 'fg', False),
                        (1020, 'value 直接接宾语，不加介词', 44, 'mute', False)],
                 speech=[('zh', '怎么表达程度。'), ('en', 'to the extent that'),
                         ('zh', '，到……的程度。她原话把 how much 和 to the extent 叠在了一起，规范写法是二选一。'),
                         ('zh', '再看 '), ('en', 'value something'),
                         ('zh', '，重视。value 直接接宾语，不加介词，比 think it’s important 简洁。')]),
            dict(n='33', title='把教育当成最底层的地基',
                 lines=[(490, 'seeing that as the', 52, 'green', True),
                        (585, 'fundamental layer', 56, 'green', True),
                        (780, 'and building on top of that', 48, 'green2', True),
                        (970, '把教育看成最底层的地基，在上面叠加', 40, 'mute', False),
                        (1140, '谈方法论、学习路径时非常好用', 44, 'mute', False)],
                 speech=[('zh', '最后一句。'), ('en', 'seeing that as the fundamental layer and building on top of that'),
                         ('zh', '，把教育看成最底层的地基，然后在上面叠加。layer 是层，build on top of 是在某个基础之上继续。'),
                         ('zh', '谈方法论、谈学习路径的时候，这个说法非常好用。')]),
            # ---- 第 7 章 连接与时间轴 ----
            dict(n='34', title='讲故事用的时间轴',
                 lines=[(470, 'for a long time', 54, 'green2', True),
                        (570, '很长一段时间以来', 44, 'fg', False),
                        (760, 'initially …  over time …', 52, 'green2', True),
                        (860, '起初……；随着时间推移……', 44, 'fg', False),
                        (1060, '比 first / then 自然得多', 44, 'mute', False)],
                 speech=[('zh', '这一组是讲故事用的时间轴连接词。'),
                         ('en', 'for a long time'), ('zh', '，很长一段时间以来，用来引出长期的心态。'),
                         ('en', 'initially'), ('zh', '，起初；'), ('en', 'over time'),
                         ('zh', '，随着时间推移。讲个人经历时，比 first、then 自然得多。'),
                         ('zh', '迁移一句：'), ('en', 'Initially I hated it; over time I got used to it.'),
                         ('zh', '这是我们的原创练习句——一开始我讨厌它，后来慢慢习惯了。')]),
            dict(n='35', title='at the same time',
                 lines=[(470, 'at the same time', 54, 'green', True),
                        (570, '同时、另一方面', 46, 'fg', False),
                        (770, '用来并列两个看似矛盾的面', 44, 'fg', False),
                        (970, '同类：then again / that said', 48, 'green2', True),
                        (1160, '两个「面」都说出口，表达才完整', 44, 'mute', False)],
                 speech=[('zh', '这个词是 '), ('en', 'at the same time'),
                         ('zh', '，同时、另一方面。它专门用来并列两个看似矛盾的面：undercutting that was harder for me and, at the same time, really important。'),
                         ('zh', '同类的说法还有 then again、that said。两个「面」都说出口，表达才完整。')]),
            dict(n='36', title='just because：只是因为',
                 lines=[(470, 'just because', 56, 'green', True),
                        (570, '只是因为……', 46, 'fg', False),
                        (770, 'just because at my core,', 48, 'fg', True),
                        (860, 'I think of myself more as …', 48, 'green2', True),
                        (1060, '语气比 because 更随口', 44, 'mute', False)],
                 speech=[('zh', '一个很简单但很地道的词。'), ('en', 'just because'),
                         ('zh', '，只是因为……。它引出原因时，语气比 because 更随口，像在解释给自己听。'),
                         ('zh', '注意别和 just because A doesn’t mean B 那个句型混起来。')]),
            # ---- 第 8 章 口语标记与语气 ----
            dict(n='37', title='决定你像不像在说人话的小词',
                 lines=[(470, 'I mean', 56, 'green2', True),
                        (570, '我是说、这么说吧（填充语）', 42, 'fg', False),
                        (760, 'you know', 56, 'green2', True),
                        (860, '你知道的（不逐字翻译）', 42, 'fg', False),
                        (1060, '一条回答里 1–2 次刚好，多了显啰嗦', 44, 'mute', False)],
                 speech=[('zh', '这一章的小词没有实际意思，但决定你像不像在说人话。'),
                         ('en', 'I mean'), ('zh', '，不是「意思」，是填充语，用来补充或强调，句首句中都能插，比如 I mean, it’s not that hard。'),
                         ('en', 'you know'), ('zh', '，用来拉近距离、给自己争取思考时间。一条回答里一到两次刚好，多了显啰嗦。它不是「你知道」，不要逐字翻译。')]),
            dict(n='38', title='like / kind of / sort of',
                 lines=[(470, 'kind of / sort of', 52, 'green2', True),
                        (570, '有点像、算是（软化语气）', 42, 'fg', False),
                        (760, 'like', 56, 'green', True),
                        (860, '口语停顿词，也用来举例', 42, 'fg', False),
                        (1060, '读音常缩成 kinda / sorta', 44, 'mute', False)],
                 speech=[('zh', '两个软化语气的小词。'), ('en', 'kind of / sort of'),
                         ('zh', '，有点像、算是，让断言不那么绝对，读音常缩成 kinda、sorta。'),
                         ('en', 'like'), ('zh', '，母语者最高频的停顿词，用来缓冲或举例，like an academic person。位置有讲究：kind of 放形容词前，like 放名词或从句前。写作里要删掉，口语里保留。')]),
            dict(n='39', title='just：既能弱化，也能加强',
                 lines=[(470, 'just totally … normal', 52, 'green', True),
                        (570, '完全就是个普通人', 44, 'fg', False),
                        (770, 'just checking in（弱化）', 46, 'green2', False),
                        (860, 'just perfect（加强）', 46, 'green2', False),
                        (1060, '作用完全靠语气判断', 44, 'mute', False)],
                 speech=[('zh', '最后一个小词，'), ('en', 'just'),
                         ('zh', '。它不只是「只是」——口语里既能弱化，也能加强。'),
                         ('zh', '弱化的时候，'), ('en', 'just checking in'),
                         ('zh', '，就是随便问问；加强的时候，'), ('en', 'just perfect'), ('zh', '，简直完美。同一个词的作用，完全靠语气判断。')]),
            # ---- 第 9 章 收尾 ----
            dict(n='40', title='带着这些点，再听一遍',
                 lines=[(950, '现在再完整听一遍', 50, 'fg', False),
                        (1040, '你应该能听出更多东西了', 52, 'green', False),
                        (1210, '2 分钟，52 个地道表达', 44, 'mute', False)],
                 speech=[('zh', '现在带着刚才拆过的这些点，再完整听一遍这 2 分钟。你会发现，能听出来的东西比第一遍多得多。')],
                 source=(65.11, 190.77)),
            dict(n='41', title='跟着读三遍',
                 lines=[(470, '1. What’s something you wish', 46, 'green2', True),
                        (545, 'people knew about you?', 46, 'green2', True),
                        (670, '2. at my core, I think of myself', 46, 'green2', True),
                        (745, 'as an intellectual person.', 46, 'green2', True),
                        (960, '3. it was not because A, it was because B.', 40, 'green2', True)],
                 speech=[('zh', '最后挑三句最常用的，跟着读一遍。'),
                         ('en', 'What’s something you wish people knew about you?'),
                         ('en', 'At my core, I think of myself as an intellectual person.'),
                         ('en', 'It was not because A, it was because B.'),
                         ('zh', '不用追求完美，先把它说出口。')],
                 tail=3.1),
            dict(n='42', title='收藏，下次聊天时过一遍',
                 lines=[(480, '拾句英语', 100, 'green', False),
                        (650, '两分钟，学会谈自己、说清楚误会', 52, 'fg', False),
                        (850, '谈自己   at my core, I think of myself as…', 38, 'green2', False),
                        (930, '澄清   not because A, but because B', 40, 'green2', False),
                        (1160, '下一期拆「童年什么都试」', 44, 'mute', False)],
                 speech=[('zh', '这一期我们拆了两个最值钱的说法：怎么谈自己，怎么优雅地澄清误会。下一期我们看第三段，也就是「童年什么都试」——她怎么讲小时候的经历。'),
                         ('zh', '先收藏，下次要介绍自己的时候，把这两句过一遍。拾句英语，听懂一句，再把它说出来。')]),
        ],
    },
}

# ===== 派生版共用的卡片补丁 =====
# 原脚本里有几张卡的原声区间夹带了非对话内容（见下面注释），派生版在这里统一覆盖，
# 不改动原选题目身——原片要能按它自己的样子复现。
PATCH = {
    # 03：原片 26→69s 里，客方回应只到 41.5s，42.3–55s 是节目组的固定插入（「Hey, it's Jay…」
    # 对听众说的），55s 之后是垫场。这段插入留给后面讲关心话的章节当正片素材，不混进「完整听一遍」。
    '03': dict(source=(26.0, 42.0),
               speech=[('zh', '再听 16 秒。这后半段是客方的回应，也是整段里最值得学的地方。')]),
    # 35：收尾重听保留那段插入（第 4/5 章已经专门讲过它），但去掉末尾 14 秒垫场。
    '35': dict(source=(0.0, 55.0),
               speech=[('zh', '现在带着刚才拆过的这些点，再完整听一遍这段 55 秒。你会发现，'
                              '能听出来的东西比第一遍多得多。')],
               lines=[(950, '现在再完整听一遍', 50, 'fg', False),
                      (1040, '你应该能听出更多东西了', 50, 'green', False),
                      (1210, '55 秒，五十多个地道表达', 40, 'mute', False)]),
}


def patch_cards(cards, patch=PATCH):
    """按补丁换掉某几张卡的原声区间 / 旁白 / 卡面文字。"""
    return [dict(c, **patch[c['n']]) if c['n'] in patch else c for c in cards]


# 试听版：同一批卡片，换音色、只取前 120 秒。
# 选卡：01 钩子 + 16（at my core）+ 26（the first person in…）+ 27（not because A, because B）+ 41 跟读，
# 让 2 分钟里新音色占满，只在 16/27 各带一小段原声。渲染到累计 ≥120s 自动停。
SPECS['谷爱凌_身份之争_2分钟版'] = dict(
    SPECS['谷爱凌_身份之争'],
    voice='TWutjvRaJqAX89preB4e',
    limit=120,
    cards=[c for c in SPECS['谷爱凌_身份之争']['cards']
           if c['n'] in ('01', '16', '26', '27', '41')],
)


SPECS['谷爱凌_身份之争_1分钟版'] = dict(
    SPECS['谷爱凌_身份之争'],
    voice='lt7GBaCoAHWbT7JSZ5Xs',
    limit=60,
    cards=[c for c in SPECS['谷爱凌_身份之争']['cards']
           if c['n'] in ('01', '16', '27')],
)


SPECS['谷爱凌_身份之争_1分钟版B'] = dict(
    SPECS['谷爱凌_身份之争_1分钟版'],
    voice='brChkoggsUHF1stW6omH',
)

# 语调实验：只动 style / stability，其余（音色、卡片、限长）与 B 完全一致，便于 A/B
EXPRESSIVE = {'stability': 0.45, 'similarity_boost': 0.75, 'style': 0.4,
              'use_speaker_boost': True, 'speed': 1.0}      # style 0.4：C 的方案，实测语调起伏比 0.0 高 8.5%
SPECS['谷爱凌_身份之争_1分钟版C'] = dict(SPECS['谷爱凌_身份之争_1分钟版B'], voice_settings=EXPRESSIVE)
SPECS['谷爱凌_身份之争_1分钟版D'] = dict(
    SPECS['谷爱凌_身份之争_1分钟版B'],
    voice_settings={'stability': 0.35, 'similarity_boost': 0.75, 'style': 0.6,
                    'use_speaker_boost': True, 'speed': 1.0},
)

# 2 分钟版 + 原音色（主片那个）+ C 的语调参数
SPECS['谷爱凌_身份之争_2分钟版B'] = dict(
    SPECS['谷爱凌_身份之争_2分钟版'],
    voice=DEFAULT_VOICE,
    voice_settings=EXPRESSIVE,
)

# 同上，再加讲解旁白字幕（给中文母语用户看：边听边读），原声片段不打字幕。
# work 指到 B 版目录：复用同一条旁白音轨，两版差别只有字幕。
# sub_cy=1282 是按这批卡片的空带量出来的（y 1260–1305），钉住以免以后默认值变了跑不回来。
SPECS['谷爱凌_身份之争_2分钟版B_字幕版'] = dict(
    SPECS['谷爱凌_身份之争_2分钟版B'],
    subs=True,
    work='谷爱凌_身份之争_2分钟版B',
    sub_cy=1282,
)

# 音色调试台 R01 的 07 号方案（eleven_v3 + style 0.4）：用户指定拿它出一版成片看效果。
# 原音色不变，卡片跟 1 分钟版一致，只换模型和语调参数，方便跟 C/D 直接对比。
# 注意 v3 不支持 speed 参数，所以这里的 voice_settings 不带 speed。
# limit=None：v3 比 v2 慢约 25–40%，沿用 60s 上限的话第 27 张卡会被挤掉，
# 内容就跟 C/D 对不上了；放开限长，保证这几版装的是同一批卡片。
V3_EXPRESSIVE = DEFAULT_VOICE_SETTINGS   # 就是新片默认那组，留个名字给派生版引用
SPECS['谷爱凌_身份之争_1分钟版E'] = dict(
    SPECS['谷爱凌_身份之争_1分钟版B'],
    voice=DEFAULT_VOICE,
    model='eleven_v3',
    voice_settings=V3_EXPRESSIVE,
    limit=None,
)

# E 的对照组：其余完全一样，只把英文变速关掉（v3 本身已经慢，再压 0.8 可能过慢）。
# work 指到 E 的目录：TTS 音频原样复用，差别只有英文那一步 atempo。
SPECS['谷爱凌_身份之争_1分钟版E_英文原速'] = dict(
    SPECS['谷爱凌_身份之争_1分钟版E'],
    en_slow=1.0,
    work='谷爱凌_身份之争_1分钟版E',
)

# 「开场寒暄」前 2 分钟重做：换 v2 深色配色 + v3 音色参数 + 宋体/Arial 斜体。
# 原片是 v1 浅色 + 黑体，所以这里三样都显式覆盖，不改动原选题目身（它要能原样复现）。
SPECS['谷爱凌_开场寒暄_2分钟版'] = dict(
    SPECS['谷爱凌_开场寒暄'],
    style='v2',
    fonts='song',
    speed=1.0,              # 已出片：原速（2026-09 起新片默认 1.2 倍速）
    voice=DEFAULT_VOICE,
    model='eleven_v3',
    voice_settings=V3_EXPRESSIVE,
    limit=120,
    cards=patch_cards(SPECS['谷爱凌_开场寒暄']['cards']),
)

# 「开场寒暄」整片重做（41 张卡）：同一套新规格，不限长。
SPECS['谷爱凌_开场寒暄_完整版'] = dict(
    SPECS['谷爱凌_开场寒暄'],
    style='v2',
    fonts='song',
    foot=False,             # 2026-09 重渲：跟随新片去掉页脚（下半区让给正文）
    speed=1.0,              # 已发布：原速（重渲只是去页脚，不跟着新片提速）
    voice=DEFAULT_VOICE,
    model='eleven_v3',
    voice_settings=V3_EXPRESSIVE,
    cards=patch_cards(SPECS['谷爱凌_开场寒暄']['cards']),
)

# 「身份之争」按 2026-09 锁定规格再做一遍：内容与卡片一个字不动，只把字体换成宋体/Arial 斜体、
# 模型换成 eleven_v3。原片是 v2 深色 + 黑体 + eleven_multilingual_v2，要能按原样复现，故不改动原选题。
SPECS['谷爱凌_身份之争_重制版'] = dict(
    SPECS['谷爱凌_身份之争'],
    style='v2',
    fonts='song',
    foot=False,             # 2026-09 重渲：跟随新片去掉页脚（下半区让给正文）
    speed=1.0,              # 已发布：原速（重渲只是去页脚，不跟着新片提速）
    voice=DEFAULT_VOICE,
    model='eleven_v3',
    voice_settings=V3_EXPRESSIVE,
)

# 「童年什么都试」（第 03 段，原片 03:10–05:13，122 秒）：26 张卡，直接按 2026-09 的锁定规格写。
# 收尾卡只留收藏引导，不做下集预告（后面新片一律如此）。
SPECS['谷爱凌_童年什么都试'] = dict(
    src='__DATA_ROOT__/小红书发帖-拾句英语/谷爱凌/谷爱凌最新全英访谈.mp4',
    style='v2',
    fonts='song',
    speed=1.0,              # 已出片：原速（2026-09 起新片默认 1.2 倍速）
    voice=DEFAULT_VOICE,
    model='eleven_v3',
    voice_settings=V3_EXPRESSIVE,
    cards=[
        # ---- 第 0 章 钩子 + 完整听一遍 ----
        dict(n='01', title='一聊自己，只会说「我挺爱学习的」？',
             lines=[(770, '跟着 2 分钟访谈学表达', 46, 'green', False),
                    (920, '成长经历 · 标签 · 看世界的方式', 44, 'fg', False),
                    (1000, '21 个表达，就藏在 2 分 2 秒里', 34, 'mute', False)],
             speech=[('zh', '一聊自己，你只会说「我挺爱学习的」「我喜欢运动」？这段 2 分 2 秒的访谈里，'
                            '谷爱凌被问「你小时候是不是学习和运动都在行」，她的回答把「我是个什么样的人」讲得清清楚楚。'),
                     ('zh', '我们挑出最值钱的三组说法，先完整听一遍，再一句一句拆。')]),
        dict(n='02', title='先完整听一遍（上）',
             lines=[(950, 'athletically and academically', 44, 'fg', True),
                    (1022, 'inclined at the same time?', 44, 'green', True),
                    (1230, '先听前 59 秒', 44, 'green2', False),
                    (1300, '不用急着听懂，注意语气和节奏就好', 40, 'mute', False)],
             speech=[('zh', '先听前 59 秒。不用急着听懂，注意语气和节奏就好。')],
             source=(190.97, 250.31)),
        dict(n='03', title='先完整听一遍（下）',
             lines=[(950, '后半段讲她怎么找到', 44, 'fg', False),
                    (1030, '自己的「强项」和看问题的方式', 44, 'green', False),
                    (1200, '听完这一遍，我们就开始拆', 40, 'mute', False)],
             speech=[('zh', '再听 63 秒。后半段讲她怎么从数学、科学走到文学、哲学，'
                            '最后说出自己看世界的方式。听完这一遍，我们就开始拆。')],
             source=(250.31, 313.19)),
        # ---- 第 1 章 谁把你养成这样 ----
        dict(n='04', title='把功劳说给别人',
             lines=[(950, 'My mom did an incredible job', 48, 'green2', True),
                    (1030, 'just putting me into everything.', 46, 'green2', True),
                    (1190, '我妈特别厉害，就是把我塞进所有事情里', 44, 'fg', False),
                    (1330, 'do an incredible job of doing sth', 40, 'green', True)],
             speech=[('zh', '第一组，先说怎么夸人。'), ('en', 'do an incredible job of doing something'),
                     ('zh', '，做某事做得特别出色。原句里她把 of 省掉了，口语里很常见，写下来要补上。'),
                     ('zh', '她说：'), ('en', 'My mom did an incredible job just putting me into everything.'),
                     ('zh', '，我妈特别厉害，就是把我塞进所有事情里。')],
             source=(199.17, 202.93)),
        dict(n='05', title='put sb into sth',
             lines=[(490, 'put sb into sth', 56, 'green', True),
                    (580, '让某人去尝试某事', 46, 'fg', False),
                    (790, 'putting me into everything', 48, 'green2', True),
                    (880, '把我塞进所有事情里', 44, 'fg', False),
                    (1090, 'into 是「推进去」的画面感', 44, 'mute', False)],
             speech=[('zh', '再看这个搭配：'), ('en', 'put somebody into something'),
                     ('zh', '，让某人去尝试某事、把某人送进某个场景。'),
                     ('zh', '她说 '), ('en', 'putting me into everything'),
                     ('zh', '，把我塞进所有事情里。注意介词是 into，不是 to，里面有「推进去」的画面感。')]),
        dict(n='06', title='八竿子打不着的兴趣',
             lines=[(950, 'very obscure things if you think', 44, 'fg', True),
                    (1030, 'about it, and have no interaction', 44, 'green2', True),
                    (1110, 'with one another', 46, 'green2', True),
                    (1190, '冷门、八竿子打不着的东西', 44, 'fg', False),
                    (1330, 'obscure / have no interaction with', 36, 'mute', True)],
             speech=[('zh', '她形容自己小时候学的那些东西。'), ('en', 'obscure'),
                     ('zh', '，冷门的、稀奇古怪的；'), ('en', 'have no interaction with one another'),
                     ('zh', '，彼此之间毫无关联。'),
                     ('zh', '她说她学的那堆东西 '), ('en', 'have no interaction with one another'),
                     ('zh', '，八竿子打不着，还补了一个 right? 让听的人点头。')],
             source=(204.29, 208.85)),
        dict(n='07', title='换成你自己的',
             lines=[(490, 'My parents did an incredible job', 46, 'green2', True),
                    (575, 'of putting me into everything.', 46, 'green2', True),
                    (780, '↓ 换成你的版本', 44, 'fg', False),
                    (960, 'They did an incredible job of', 44, 'fg', True),
                    (1040, 'letting me try things and fail.', 44, 'green', True)],
             speech=[('zh', '换你来说一句。'), ('en', 'My parents did an incredible job of putting me into everything.'),
                     ('zh', '，我爸妈特别厉害，就是让我什么都去试。'),
                     ('zh', '这是我们的原创练习句，不是她说的。你也可以说 '),
                     ('en', 'They did an incredible job of letting me try things and fail.'),
                     ('zh', '——他们做得最好的一点，是让我去试，也让我去失败。')]),
        dict(n='08', title='先听主持人怎么问',
             lines=[(950, 'were you always athletically', 44, 'fg', True),
                    (1022, 'and academically inclined?', 44, 'green', True),
                    (1230, '先听主持人怎么问', 44, 'green2', False),
                    (1300, '两个问句叠在一起，把话题打开了', 38, 'mute', False)],
             speech=[('zh', '先听主持人怎么问。'),
                     ('en', 'As a young girl, were you always athletically and academically inclined at the same time? Were they two paths that always existed?'),
                     ('zh', '，你小时候，是不是运动和学业同时都在行？这两条路是一直都在的吗？')],
             source=(190.97, 197.13)),
        dict(n='09', title='两个采访里最好用的问法',
             lines=[(470, 'be inclined to sth', 50, 'green', True),
                    (560, '在某方面有天赋、偏向某个方向', 40, 'fg', False),
                    (770, 'Were they two paths', 48, 'green2', True),
                    (850, 'that always existed?', 48, 'green2', True),
                    (1070, '用 paths 比喻人生选择', 44, 'mute', False)],
             speech=[('zh', '他的问法里有两个点可以搬走。'), ('en', 'be inclined'),
                     ('zh', '，在某方面有天赋、偏向某个方向，'),
                     ('en', 'athletically and academically inclined'),
                     ('zh', ' 就是「运动和学业都在行」。'),
                     ('zh', '第二句更值得学：'), ('en', 'Were they two paths that always existed?'),
                     ('zh', '，这两条路是一直都在的吗？用 paths 比喻人生选择，比 choices 具体得多。')]),
        # ---- 第 2 章 讲经历的时间线 ----
        dict(n='10', title='讲经历的时间线',
             lines=[(950, 'at one point I tried swimming and', 42, 'fg', True),
                    (1030, 'tennis, but then longer term I did', 42, 'green2', True),
                    (1110, 'soccer and basketball and cross country', 42, 'green2', True),
                    (1190, '有段时间试过…，长期来看…', 44, 'fg', False),
                    (1330, 'at one point / longer term', 40, 'green', True)],
             speech=[('zh', '第二组：怎么讲自己的经历。'), ('en', 'at one point'),
                     ('zh', '，有段时间、曾经；'), ('en', 'longer term'), ('zh', '，长期来看。'),
                     ('zh', '她原话是：'),
                     ('en', 'at one point I tried swimming and tennis, but then longer term I did soccer and basketball and cross country'),
                     ('zh', '。先说她试过什么，再说她长期做什么——一次尝试和一段长期投入，用两组时间词就交代清楚了。')],
             source=(214.15, 220.51)),
        dict(n='11', title='would：过去的习惯',
             lines=[(950, 'My mom would say that', 50, 'green2', True),
                    (1030, 'I was athletic.', 54, 'green2', True),
                    (1190, '我妈那时总说我是运动型的', 46, 'fg', False),
                    (1330, 'would = 过去常常（不是「会」）', 42, 'mute', False)],
             speech=[('zh', '这里还藏着一个语法点。'), ('en', 'My mom would say that I was athletic.'),
                     ('zh', '，我妈那时候总说我是运动型的。'),
                     ('zh', 'would 在这里不表示「会」，而是表示过去的习惯，等于 used to。'
                            '说小时候的事，用 would 比 usually said 自然得多，而且只用在过去。')],
             source=(224.77, 226.93)),
        dict(n='12', title='至今仍然这么认为',
             lines=[(950, 'I thought they were pretty impactful,', 42, 'fg', True),
                    (1030, 'running being one of them, and', 42, 'green2', True),
                    (1110, 'I hold that to this day.', 46, 'green2', True),
                    (1190, '跑步是其中之一，这个看法我至今没变', 42, 'fg', False),
                    (1330, 'hold that to this day = 至今仍这么认为', 38, 'mute', False)],
             speech=[('zh', '这一句有两个点。'), ('en', 'I hold that to this day'),
                     ('zh', '，这个看法我至今没变。hold 是「坚持、持有」，比 I still think so 更有分量。'),
                     ('zh', '前面还有 '), ('en', 'running being one of them'),
                     ('zh', '，跑步是其中之一。这是一个独立主格结构，用逗号挂在前半句后面补充说明，不用另起一句。')],
             source=(227.19, 232.31)),
        dict(n='13', title='换成你自己的',
             lines=[(470, 'At one point I tried a lot of things,', 44, 'green2', True),
                    (555, 'but longer term I stuck with one.', 44, 'green2', True),
                    (780, '↓ 换成你的版本', 44, 'fg', False),
                    (960, 'At one point I was learning three', 44, 'fg', True),
                    (1040, 'languages, but longer term I kept', 44, 'fg', True),
                    (1120, 'only one.', 46, 'green', True)],
             speech=[('zh', '换你来说一句。'), ('en', 'At one point I tried a lot of things, but longer term I stuck with one.'),
                     ('zh', '，有段时间我什么都试，但长期来看我只坚持了一件事。'),
                     ('zh', '这是我们的原创练习句。把你自己的经历填进这组时间词，一段话就有了层次。')]),
        # ---- 第 3 章 别人眼里的我 ----
        dict(n='14', title='别人眼里的我，是……而不是……',
             lines=[(950, 'I was much more known as the', 44, 'fg', True),
                    (1030, 'nerd in my class than the', 44, 'green', True),
                    (1110, 'athlete in my class.', 46, 'green', True),
                    (1190, '在班里，我更像个书呆子，而不是运动员', 42, 'fg', False),
                    (1330, 'be much more known as A than B', 40, 'green', True)],
             speech=[('zh', '第三组，专门用来讲别人怎么看你。'),
                     ('en', 'be much more known as A than B'),
                     ('zh', '，别人更把我当成 A，而不是 B。'),
                     ('zh', '她说：'),
                     ('en', 'I was much more known as the nerd in my class than the athlete in my class.'),
                     ('zh', '，在班里，我更像个书呆子，而不是运动员。想解释「我不止一面」，这句最好用。')],
             source=(237.23, 244.97)),
        dict(n='15', title='as 接身份，for 接特点',
             lines=[(470, 'be known as', 54, 'green2', True),
                    (570, '被当成某种身份', 46, 'fg', False),
                    (770, 'be known for', 54, 'green2', True),
                    (870, '因为某个特点而出名', 46, 'fg', False),
                    (1080, 'as 接「谁」，for 接「什么」', 44, 'mute', False)],
             speech=[('zh', '顺手分清两个高频搭配。'), ('en', 'be known as'),
                     ('zh', '，被当成某种身份；'), ('en', 'be known for'), ('zh', '，因为某个特点而出名。'),
                     ('zh', 'as 后面接「谁」，for 后面接「什么」，比如 known for his humor、known as a writer。'
                            '这两个混用，意思就完全不一样了。')]),
        dict(n='16', title='换成你自己的',
             lines=[(470, 'I’m much more known as the person', 44, 'green2', True),
                    (555, 'who always asks questions.', 44, 'green2', True),
                    (780, '↓ 换成你的版本', 44, 'fg', False),
                    (960, 'In my team I’m known as the one', 42, 'fg', True),
                    (1035, 'who takes notes, not the one', 42, 'fg', True),
                    (1110, 'who speaks up.', 44, 'green', True)],
             speech=[('zh', '换你来说一句。'), ('en', 'I’m much more known as the person who always asks questions.'),
                     ('zh', '，别人更把我当成那个总爱提问的人。'),
                     ('zh', '这是我们的原创练习句，不是她说的。把 as 后面的身份换成你自己的，'
                            '比如 the one who takes notes。')]),
        # ---- 第 4 章 兴趣怎么说才不像报菜名 ----
        dict(n='17', title='主持人追问：你对什么着迷？',
             lines=[(950, 'And what would you nerd out on?', 44, 'fg', True),
                    (1030, 'What were the things that you were', 40, 'green2', True),
                    (1110, 'fascinated by or drawn towards?', 40, 'green2', True),
                    (1190, '你会对什么津津乐道？被什么吸引？', 44, 'fg', False),
                    (1330, 'nerd out on / be fascinated by / be drawn towards', 30, 'mute', True)],
             speech=[('zh', '主持人追问的这一句，全是宝。'), ('en', 'And what would you nerd out on?'),
                     ('zh', '，你会对什么津津乐道？nerd out on something，非常地道的口语说法，'
                            '带一点自嘲，说自己痴迷什么研究什么。'),
                     ('zh', '后面一句正好给了两个替换：'), ('en', 'be fascinated by'),
                     ('zh', '，被深深吸引；'), ('en', 'be drawn towards'),
                     ('zh', '，不由自主地被吸引过去。三个轮着用，聊兴趣就不会重复。')],
             source=(245.17, 250.31)),
        dict(n='18', title='go through：读完、经历完',
             lines=[(950, 'I went through a K to eight', 46, 'green2', True),
                    (1030, 'all-girls school.', 48, 'green2', True),
                    (1190, '我读的是幼儿园到八年级的女校', 44, 'fg', False),
                    (1330, 'go through a school = 读完某个阶段', 40, 'mute', False)],
             speech=[('zh', '讲学历背景时很好用的一句。'), ('en', 'go through a school'),
                     ('zh', '，在这里读完某个阶段。'),
                     ('zh', '她说：'), ('en', 'I went through a K to eight all-girls school.'),
                     ('zh', 'K to eight 是幼儿园到八年级，K 是 kindergarten。'
                            '注意她用 went through 而不是 studied，强调的是完整经历过。')],
             source=(250.31, 254.31)),
        dict(n='19', title='我的强项，这么说更口语',
             lines=[(950, 'math and science were', 50, 'green2', True),
                    (1030, 'definitely my big things.', 50, 'green2', True),
                    (1190, '数学和科学绝对是我的拿手项', 44, 'fg', False),
                    (1330, 'my big things = 我最在意的几件事', 40, 'mute', False)],
             speech=[('zh', '一个特别口语的说法。'), ('en', 'my big things'),
                     ('zh', '，我最在意、最擅长的几件事。'),
                     ('zh', '她说：'), ('en', 'math and science were definitely my big things.'),
                     ('zh', '，数学和科学绝对是我的拿手项。比你真去说 My strengths are… 更像人说的话，'
                            '适合口语和面试里的自我介绍。')],
             source=(269.17, 272.29)),
        dict(n='20', title='兴趣是怎么转移的',
             lines=[(950, 'when I got into high school, it', 42, 'fg', True),
                    (1030, 'kind of moved more into literature', 42, 'green2', True),
                    (1110, 'and philosophy.', 46, 'green2', True),
                    (1190, '上了高中，它慢慢转向了文学和哲学', 42, 'fg', False),
                    (1330, 'interestingly / it kind of moved into', 36, 'mute', True)],
             speech=[('zh', '讲兴趣怎么变化，这句是模板。'), ('en', 'interestingly'),
                     ('zh', '，有意思的是，用来引出一个出乎意料的转折；'),
                     ('en', 'it kind of moved into'),
                     ('zh', '，它慢慢转移到了……。'),
                     ('zh', '她说：'), ('en', 'when I got into high school, it kind of moved more into literature and philosophy.'),
                     ('zh', 'kind of 让断言不那么绝对，听起来像在回忆，而不是在下结论。')],
             source=(272.45, 277.01)),
        # ---- 第 5 章 说出你看世界的方式 ----
        dict(n='21', title='lens：你用什么视角看世界',
             lines=[(950, 'I would say I have an analytical', 44, 'green2', True),
                    (1030, 'lens to everything.', 48, 'green2', True),
                    (1190, '我会说我做任何事都带着分析的眼光', 44, 'fg', False),
                    (1330, 'have an analytical lens to sth', 40, 'green', True)],
             speech=[('zh', '这一条是本片最值钱的隐喻。'), ('en', 'have an analytical lens to something'),
                     ('zh', '，用分析的眼光看某事。lens 本来是镜头，引申成「看问题的角度」。'),
                     ('zh', '她说：'), ('en', 'I would say I have an analytical lens to everything.'),
                     ('zh', '，我会说我做任何事都带着分析的眼光。注意她先说 I would say，'
                            '给自己留余地，比直接说 I have 稳得多。')],
             source=(279.19, 281.35)),
        dict(n='22', title='在这个视角上再叠加一层',
             lines=[(950, 'I take more of a philosophical', 44, 'fg', True),
                    (1030, 'overview on top of that.', 46, 'green2', True),
                    (1190, '在这之上，再叠一层整体视角', 44, 'fg', False),
                    (1330, 'a philosophical overview / on top of that', 36, 'green', True)],
             speech=[('zh', '最后一句。'), ('en', 'take a philosophical overview on top of that'),
                     ('zh', '，在这之上再叠一层哲学层面的整体看法。'),
                     ('zh', 'overview 是整体视角，on top of that 是「在这之上」。'
                            '谈方法论、谈自己的学习路径，这两个词非常好用。')],
             source=(281.81, 287.39)),
        dict(n='23', title='换成你自己的',
             lines=[(470, 'I’ve started to have a more', 44, 'green2', True),
                    (555, 'analytical lens to my own decisions.', 44, 'green2', True),
                    (780, '↓ 换成你的版本', 44, 'fg', False),
                    (960, 'I’ve started to have a calmer lens', 44, 'fg', True),
                    (1040, 'to the things I can’t control.', 44, 'green', True)],
             speech=[('zh', '换你来说一句。'), ('en', 'I’ve started to have a more analytical lens to my own decisions.'),
                     ('zh', '，我开始用更分析的眼光看待自己的决定。'),
                     ('zh', '这是我们的原创练习句。lens 前面那个形容词随便换，'
                            '换成 calmer，就是另一句完全属于你的话。')]),
        # ---- 第 6 章 收尾 ----
        dict(n='24', title='带着这些点，再听一遍',
             lines=[(950, '现在再完整听一遍', 50, 'fg', False),
                    (1040, '你应该能听出更多东西了', 52, 'green', False),
                    (1210, '2 分 2 秒，21 个地道表达', 44, 'mute', False)],
             speech=[('zh', '现在带着刚才拆过的这些点，再完整听一遍这 2 分钟。'
                            '你会发现，能听出来的东西比第一遍多得多。')],
             source=(190.97, 313.19)),
        dict(n='25', title='跟着读三遍',
             lines=[(470, '1. My mom did an incredible job', 44, 'green2', True),
                    (545, 'putting me into everything.', 44, 'green2', True),
                    (670, '2. At one point I tried a lot of', 44, 'green2', True),
                    (745, 'things, but longer term I stuck', 44, 'green2', True),
                    (820, 'with one.', 44, 'green2', True),
                    (1040, '3. I’m much more known as A than B.', 42, 'green2', True)],
             speech=[('zh', '最后挑三句最常用的，跟着读一遍。'),
                     ('en', 'My mom did an incredible job putting me into everything.'),
                     ('en', 'At one point I tried a lot of things, but longer term I stuck with one.'),
                     ('en', 'I’m much more known as the person who asks questions than the person who has answers.'),
                     ('zh', '不用追求完美，先把它说出口。')],
             tail=3.1),
        dict(n='26', title='收藏，下次介绍自己时过一遍',
             lines=[(480, '拾句英语', 100, 'green', False),
                    (650, '两分钟，把「我是个什么样的人」说清楚', 42, 'fg', False),
                    (850, '夸人   do an incredible job of doing sth', 36, 'green2', False),
                    (925, '讲经历   at one point … but longer term …', 36, 'green2', False),
                    (1000, '说标签   be much more known as A than B', 36, 'green2', False),
                    (1200, '听懂一句，再把它说出来', 40, 'mute', False)],
             speech=[('zh', '这一期我们拆了三组说法：怎么把功劳说给别人，怎么讲自己的经历，'
                            '怎么讲别人眼里的自己。先收藏，下次要介绍自己的时候，把这三句过一遍。'),
                     ('zh', '拾句英语，听懂一句，再把它说出来。')]),
    ],
)

# 「写日记」（第 04 段，原片 05:13–07:36，141 秒；07:36 起是 Ultra Running 广告，已避开）：26 张卡。
# 有原声的卡正文一律排在画中画下方（950/1030/1110/1190/1330）。
SPECS['谷爱凌_写日记'] = dict(
    src='__DATA_ROOT__/小红书发帖-拾句英语/谷爱凌/谷爱凌最新全英访谈.mp4',
    style='v2',
    fonts='song',
    speed=1.0,              # 已出片：原速（2026-09 起新片默认 1.2 倍速）
    voice=DEFAULT_VOICE,
    model='eleven_v3',
    voice_settings=V3_EXPRESSIVE,
    cards=[
        # ---- 第 0 章 钩子 + 完整听一遍 ----
        dict(n='01', title='怎么把一件小事，讲成「这就是我」？',
             lines=[(770, '跟着 2 分钟访谈学表达', 46, 'green', False),
                    (920, '童年记忆 · 被夸 · 讲自己的故事', 44, 'fg', False),
                    (1000, '18 个表达，就藏在 2 分 21 秒里', 34, 'mute', False)],
             speech=[('zh', '别人问「讲一件定义了你今天的童年记忆」，你能讲出一件小事，还讲出它为什么是你吗？'
                            '这段 2 分 21 秒的访谈里，谷爱凌从一个四岁的日记本讲起，讲到她为什么敢想「有一天我要把它出版」。'),
                     ('zh', '我们挑出最值钱的三组说法，先完整听一遍，再一句一句拆。')]),
        dict(n='02', title='先完整听一遍（上）',
             lines=[(950, 'But before we do, can you take me', 42, 'fg', True),
                    (1030, 'back to a childhood memory…', 42, 'green', True),
                    (1230, '先听前 67 秒', 44, 'green2', False),
                    (1300, '不用急着听懂，注意语气和节奏就好', 40, 'mute', False)],
             speech=[('zh', '先听前 67 秒。不用急着听懂，注意语气和节奏就好。')],
             source=(313.63, 380.41)),
        dict(n='03', title='先完整听一遍（下）',
             lines=[(950, '后半段是她四岁那年的日记本', 44, 'fg', False),
                    (1030, '和一个四岁小孩的「野心」', 44, 'green', False),
                    (1200, '听完这一遍，我们就开始拆', 40, 'mute', False)],
             speech=[('zh', '再听 75 秒。后半段是她四岁那年那本带锁的日记——她在第一页写下'
                            '「亲爱的日记，我叫谷爱凌，我四岁」，还想着有一天要把它出版。听完这一遍，我们就开始拆。')],
             source=(380.41, 455.09)),
        # ---- 第 1 章 请对方讲一段记忆 ----
        dict(n='04', title='请对方讲一段记忆',
             lines=[(950, 'Can you take me back to a', 44, 'fg', True),
                    (1030, 'childhood memory that you', 44, 'green2', True),
                    (1110, 'feel defines who you are today?', 42, 'green2', True),
                    (1190, '能带我回到……那段记忆吗？', 44, 'fg', False),
                    (1330, 'take sb back to + 记忆', 40, 'green', True)],
             speech=[('zh', '主持人是怎么开口请她讲故事的。'), ('en', 'take somebody back to something'),
                     ('zh', '，把某人带回某段记忆——访谈、破冰、复盘经历都能用。'),
                     ('zh', '他问：'),
                     ('en', 'Can you take me back to a childhood memory that you have that you feel defines who you are today?'),
                     ('zh', '，能带我回到一段你觉得定义了你今天的童年记忆吗？')],
             source=(314.31, 318.97)),
        dict(n='05', title='一段记忆「定义」了你',
             lines=[(490, 'define who you are', 54, 'green', True),
                    (580, '定义了你这个人', 46, 'fg', False),
                    (790, 'a memory that defines who you are', 42, 'green2', True),
                    (880, '一段塑造了你的记忆', 44, 'fg', False),
                    (1090, 'define 是「决定本质」，不是「下定义」', 42, 'mute', False)],
             speech=[('zh', '这个短语里的 define 值得单独说。'), ('en', 'define who you are'),
                     ('zh', '，定义了你这个人——这里的 define 是「决定本质」，不是查词典的「下定义」。'),
                     ('zh', '所以 '), ('en', 'a memory that defines who you are'),
                     ('zh', '，不是「一段能解释你的记忆」，而是「一段塑造了你的记忆」。')]),
        # ---- 第 2 章 被夸之后怎么接 ----
        dict(n='06', title='被夸之后，先接住',
             lines=[(950, 'Firstly, thank you so much', 44, 'fg', True),
                    (1030, 'for saying that. I’m deeply', 44, 'green2', True),
                    (1110, 'flattered and humbled.', 46, 'green2', True),
                    (1190, '太抬举我了，我受宠若惊', 44, 'fg', False),
                    (1330, 'flattered 是被夸到，humbled 是被折服', 36, 'mute', False)],
             speech=[('zh', '被夸之后怎么接。'), ('en', 'I’m deeply flattered and humbled.'),
                     ('zh', '，deeply 同时修饰后面两个形容词：flattered 是被夸得不好意思，'
                            'humbled 是被折服、觉得自己配不上。'),
                     ('zh', '两个词一起用，比单说 thank you 得体得多，也顺手把夸奖推回去一点。')],
             source=(319.55, 322.89)),
        dict(n='07', title='calculated：刻意、有心机',
             lines=[(950, 'And I do want to say that', 44, 'fg', True),
                    (1030, 'nothing that I said during', 44, 'green2', True),
                    (1110, 'the Olympics was calculated.', 44, 'green2', True),
                    (1190, '我说的每句话都不是算计好的', 42, 'fg', False),
                    (1330, 'calculated = 精心设计过的', 40, 'mute', True)],
             speech=[('zh', '这个词是理解她言外之意的关键。'), ('en', 'calculated'),
                     ('zh', '，算准的、精心设计过的；说一句话 calculated，等于说它有目的、有心机。'),
                     ('zh', '她说：'),
                     ('en', 'nothing that I said during the Olympics was calculated'),
                     ('zh', '，我在奥运会期间说的每一句话，都不是算计好的。否定加被动，比 I didn’t plan it 有力得多。')],
             source=(323.43, 327.89)),
        dict(n='08', title='换你来说',
             lines=[(490, 'I’m deeply flattered and humbled.', 48, 'green2', True),
                    (580, '↓ 换成你的版本', 44, 'fg', False),
                    (760, 'Thank you — I’m genuinely flattered,', 44, 'fg', True),
                    (840, 'and honestly a little humbled.', 44, 'green', True),
                    (1060, '把 deeply 换成 genuinely，语气更像你', 42, 'mute', False)],
             speech=[('zh', '换你来说一句。'), ('en', 'I’m deeply flattered and humbled.'),
                     ('zh', '，太抬举我了，我受宠若惊。'),
                     ('zh', '这是我们的原创练习句，你也可以说 '),
                     ('en', 'Thank you — I’m genuinely flattered, and honestly a little humbled.'),
                     ('zh', '。把 deeply 换成 genuinely、再加上 a little，语气就更像你自己在说话。')]),
        # ---- 第 3 章 对过去的假设 ----
        dict(n='09', title='毫无心理准备',
             lines=[(950, 'I had no idea what any of', 44, 'fg', True),
                    (1030, 'the questions were going to be.', 42, 'green2', True),
                    (1190, '那些问题会问什么，我一点都不知道', 42, 'fg', False),
                    (1330, 'have no idea = 完全没有头绪', 40, 'mute', True)],
             speech=[('zh', '先说「毫无准备」。'),
                     ('en', 'I had no idea what any of the questions were going to be.'),
                     ('zh', '，那些问题会问什么，我一点都不知道。'),
                     ('zh', 'have no idea 比 I didn’t know 强，意思是「完全没头绪」；后面接 what、how、why 引导的从句，比接 that 自然。')],
             source=(328.17, 330.31)),
        dict(n='10', title='如果当时是别的，我就会……',
             lines=[(950, 'So if it had been something', 44, 'fg', True),
                    (1030, 'else, I would have answered', 44, 'green2', True),
                    (1110, 'something else.', 46, 'green2', True),
                    (1190, '当时是别的问题，我答的也会是别的', 40, 'fg', False),
                    (1330, 'if + had done, would have done', 40, 'green', True)],
             speech=[('zh', '这一句是语法点里最值钱的一条。'),
                     ('en', 'So if it had been something else, I would have answered something else.'),
                     ('zh', '，如果当时是别的问题，我答的也会是别的。'),
                     ('zh', '结构是 if 加 had done，主句用 would have done——对过去的假设。'
                            '她说这句是为了说明「我没有准备、也没有剧本」，一个条件句就把自己说清楚了。')],
             source=(330.85, 333.51)),
        dict(n='11', title='换你来说',
             lines=[(470, 'If it had been a different', 46, 'green2', True),
                    (560, 'question, I would have answered', 46, 'green2', True),
                    (650, 'differently.', 48, 'green2', True),
                    (870, '如果换成别的问题，我当时的答案会不一样', 42, 'fg', False),
                    (1090, '把 something else 换成你自己的场景', 42, 'mute', False)],
             speech=[('zh', '换你来说一句。'),
                     ('en', 'If it had been a different question, I would have answered differently.'),
                     ('zh', '，如果换成别的问题，我当时的答案会不一样。'),
                     ('zh', '这是我们的原创练习句。把 question 换成 meeting、把 answered 换成 reacted，就是另一个场景。')]),
        # ---- 第 4 章 把原因说清楚 ----
        dict(n='12', title='归因：很大一部分是因为……',
             lines=[(950, 'And I think a big part of', 44, 'fg', True),
                    (1030, 'that was having an academic', 44, 'green2', True),
                    (1110, 'foundation to be able to think,', 42, 'green2', True),
                    (1190, '很大一部分原因，是我有学业底子', 40, 'fg', False),
                    (1330, 'a big part of that was + doing sth', 34, 'green', True)],
             speech=[('zh', '怎么归因。'), ('en', 'a big part of that was doing something'),
                     ('zh', '，很大一部分原因在于……后面接动名词，不接 to do。'),
                     ('zh', '句尾她还加了一句 '), ('en', 'to begin with'),
                     ('zh', '，这里不是「首先」，而是「最根本的一点是」。她说：'),
                     ('en', 'a big part of that was having an academic foundation to be able to think, to begin with.'),
                     ('zh', '——能想问题，根子上是先有学业底子。')],
             source=(334.91, 339.49)),
        dict(n='13', title='entail：必然涉及什么',
             lines=[(950, 'I don’t really know what', 44, 'fg', True),
                    (1030, 'that would entail.', 46, 'green2', True),
                    (1190, '我不太清楚那意味着什么、要做些什么', 40, 'fg', False),
                    (1330, 'entail = 必然带来、涉及', 40, 'mute', True)],
             speech=[('zh', '一个很好用、但很多人不认识的词。'), ('en', 'entail'),
                     ('zh', '，必然带来、涉及到——谈项目范围、岗位职责时特别高频。'),
                     ('zh', '她说：'), ('en', 'I don’t really know what that would entail.'),
                     ('zh', '，我不太清楚那意味着什么、具体要做些什么。比 I don’t know what it includes 准确得多。')],
             source=(342.19, 344.43)),
        dict(n='14', title='on board：认同、愿意配合',
             lines=[(950, 'I’m sure that you’re so', 44, 'fg', True),
                    (1030, 'on board with that.', 46, 'green2', True),
                    (1190, '我确定你完全认同这一点', 44, 'fg', False),
                    (1330, 'be on board with sth', 40, 'green', True)],
             speech=[('zh', '团队协作里最高频的一句。'), ('en', 'be on board with something'),
                     ('zh', '，认同、愿意配合——比 I agree 多一层「我愿意跟你一起做」。'),
                     ('zh', '她说 '), ('en', 'I’m sure that you’re so on board with that'),
                     ('zh', '，我确定你完全认同这一点——说这句的时候她在跟主持人打趣。')],
             source=(347.81, 350.45)),
        # ---- 第 5 章 讲那本日记 ----
        dict(n='15', title='讲惊人事实前的铺垫',
             lines=[(950, 'This is going to sound', 44, 'fg', True),
                    (1030, 'really crazy.', 48, 'green2', True),
                    (1190, '接下来这句听起来可能有点离谱', 42, 'fg', False),
                    (1330, 'gonna 就是 going to 的口语写法', 38, 'mute', False)],
             speech=[('zh', '讲一件让人吃惊的事之前，先垫一句。'), ('en', 'This is going to sound really crazy.'),
                     ('zh', '，接下来这句听起来可能有点离谱。'),
                     ('zh', '有了这句缓冲，后面说什么都不显得自大；gonna 就是 going to 的口语写法。')],
             source=(350.63, 352.31)),
        dict(n='16', title='「只属于我」的东西',
             lines=[(950, 'it was my first thing that', 44, 'fg', True),
                    (1030, 'I felt like was really mine.', 44, 'green2', True),
                    (1190, '那是我第一件真正属于我自己的东西', 40, 'fg', False),
                    (1330, 'feel like 插在句子中间，口语感很强', 38, 'mute', False)],
             speech=[('zh', '这一句的语感值得学。'),
                     ('en', 'it was my first thing that I felt like was really mine'),
                     ('zh', '，那是我第一件觉得真正属于我自己的东西。'),
                     ('zh', '规范写法是 '), ('en', 'my first thing that was really mine'),
                     ('zh', '，她把 '), ('en', 'I felt like'),
                     ('zh', ' 插在中间——等于把「这是我的感觉」标出来，口语里非常自然。')],
             source=(366.77, 369.99)),
        dict(n='17', title='along these lines：大意是这样',
             lines=[(950, 'I wrote along these lines,', 44, 'fg', True),
                    (1030, 'Dear Journal, my name is', 44, 'green2', True),
                    (1110, 'Eileen, I’m four years old.', 44, 'green2', True),
                    (1190, '大意是：亲爱的日记，我叫谷爱凌，我四岁', 36, 'fg', False),
                    (1330, 'along these lines = 大致是这样', 40, 'green', True)],
             speech=[('zh', '要转述别人（或自己）写过的话，用这一句。'), ('en', 'along these lines'),
                     ('zh', '，大意是这样、差不多是这么说的。'),
                     ('zh', '她说 '), ('en', 'I wrote along these lines, Dear Journal, my name is Eileen, I’m four years old.'),
                     ('zh', '——先给「大意」，再念原话，转述时特别清楚。')],
             source=(382.53, 387.89)),
        dict(n='18', title='目的 + 时间：两层从句套着说',
             lines=[(950, 'I’m writing this now so that when', 40, 'fg', True),
                    (1030, 'you are reading this, when it is', 40, 'green2', True),
                    (1110, 'published, you will believe that I', 40, 'green2', True),
                    (1190, '我现在写下这些，是为了让你读到时相信', 38, 'fg', False),
                    (1330, 'so that + 从句，when 再嵌一层', 36, 'green', True)],
             speech=[('zh', '这一句是「说明动机」最规范的写法。'),
                     ('en', 'I’m writing this now so that when you are reading this, when it is published, you will believe that I actually was four and wrote this.'),
                     ('zh', '，我现在写下这些，是为了等你读到、等它出版的时候，会相信我真的是四岁写的。'),
                     ('zh', '结构上 so that 引出目的，里面再嵌一层 when 的时间从句。说明动机时，比 because 更清楚地指向「为了什么结果」。')],
             source=(388.57, 395.83)),
        # ---- 第 6 章 拆解自己那点狂妄 ----
        dict(n='19', title='unpack：一层层拆开看',
             lines=[(950, 'Which, I think about now, and', 42, 'fg', True),
                    (1030, 'there’s just like, let’s', 42, 'green2', True),
                    (1110, 'unpack this, right?', 46, 'green2', True),
                    (1190, '现在回头想，咱们把它拆开来看', 42, 'fg', False),
                    (1330, 'unpack = 逐层剖析', 40, 'green', True)],
             speech=[('zh', '一个在汇报和复盘里非常好用的动词。'), ('en', 'Let’s unpack this.'),
                     ('zh', '，咱们把它拆开来看——unpack 本意是拆行李，引申成「把一件事逐层分析清楚」。'),
                     ('zh', '她聊自己四岁写的日记，用的就是这个词：不是「说说」，而是「一层层拆」。')],
             source=(397.11, 401.23)),
        dict(n='20', title='hubris：那种不自量力的自信',
             lines=[(950, 'the hubris that I had as a', 42, 'fg', True),
                    (1030, 'four-year-old to think that I', 42, 'green2', True),
                    (1110, 'would do something substantive.', 40, 'green2', True),
                    (1190, '四岁的我居然狂妄地觉得，我会做出点实打实的事', 34, 'fg', False),
                    (1330, 'the + 名词 + to do：那种……去做……', 34, 'mute', False)],
             speech=[('zh', '一个高级词，加一个高级结构。'), ('en', 'hubris'),
                     ('zh', '，狂妄、不自量力，带批评意味——这里她是在自嘲四岁的自己。'),
                     ('zh', '结构上 '), ('en', 'the hubris to think that'),
                     ('zh', ' 是「the 加名词 加 to do」，表示「那种去做某事的（不当）心态」；'
                            '同一类的还有 the nerve to、the courage to。')],
             source=(401.93, 405.89)),
        dict(n='21', title='够……才值得……',
             lines=[(950, 'And that this is going to be', 42, 'fg', True),
                    (1030, 'meaningful and impactful enough', 40, 'green2', True),
                    (1110, 'to be worth writing about.', 42, 'green2', True),
                    (1190, '它得足够有意义、有力量，才值得写下来', 36, 'fg', False),
                    (1330, 'enough to + be worth doing', 36, 'green', True)],
             speech=[('zh', '这一句里叠了两个结构。'),
                     ('en', 'meaningful and impactful enough to be worth writing about'),
                     ('zh', '，足够有意义、有力量，才值得写。'),
                     ('zh', 'enough to 是「足够……以至于」，后面接 '), ('en', 'be worth doing'),
                     ('zh', '——注意 worth 后面只能接动名词，不能接 to do，这是最常见的错点之一。')],
             source=(430.55, 435.57)),
        dict(n='22', title='换你来说',
             lines=[(470, 'The question is whether it’s', 46, 'green2', True),
                    (560, 'important enough to be worth', 46, 'green2', True),
                    (650, 'writing down.', 48, 'green2', True),
                    (870, '问题在于它是否重要到值得记下来', 42, 'fg', False),
                    (1090, 'enough to + worth doing，连着说', 42, 'mute', False)],
             speech=[('zh', '换你来说一句。'),
                     ('en', 'The question is whether it’s important enough to be worth writing down.'),
                     ('zh', '，问题在于它是否重要到值得记下来。'),
                     ('zh', '这是我们的原创练习句。enough to 加 worth doing 连着说，是把「判断标准」讲清楚的好办法。')]),
        # ---- 第 7 章 收尾 ----
        dict(n='23', title='说不清来源，也是一种回答',
             lines=[(950, 'So yeah, I don’t really know', 42, 'fg', True),
                    (1030, 'where that confidence came from.', 40, 'green2', True),
                    (1190, '我也说不清那份自信是哪儿来的', 42, 'fg', False),
                    (1330, 'where sth came from = 某物的来源', 36, 'green', True)],
             speech=[('zh', '最后一句。'), ('en', 'I don’t really know where that confidence came from.'),
                     ('zh', '，我也说不清那份自信是哪儿来的。'),
                     ('zh', 'where something came from 就是「某件事是从哪儿来的」。'
                            '讲不清原因的时候，这一句比 I don’t know why 更具体，也不显得敷衍。')],
             source=(443.43, 446.01)),
        dict(n='24', title='带着这些点，再听一遍',
             lines=[(950, '现在再完整听一遍', 50, 'fg', False),
                    (1040, '你应该能听出更多东西了', 52, 'green', False),
                    (1210, '2 分 21 秒，18 个地道表达', 44, 'mute', False)],
             speech=[('zh', '现在带着刚才拆过的这些点，再完整听一遍这 2 分 21 秒。'
                            '你会发现，能听出来的东西比第一遍多得多。')],
             source=(313.63, 455.09)),
        dict(n='25', title='跟着读三遍',
             lines=[(470, '1. Can you take me back to a', 44, 'green2', True),
                    (545, 'childhood memory that defines you?', 42, 'green2', True),
                    (670, '2. If it had been something else, I', 44, 'green2', True),
                    (745, 'would have answered something else.', 42, 'green2', True),
                    (870, '3. It was meaningful enough to be', 44, 'green2', True),
                    (945, 'worth writing about.', 44, 'green2', True)],
             speech=[('zh', '最后挑三句最常用的，跟着读一遍。'),
                     ('en', 'Can you take me back to a childhood memory that you feel defines who you are?'),
                     ('en', 'If it had been something else, I would have answered something else.'),
                     ('en', 'It was meaningful and impactful enough to be worth writing about.'),
                     ('zh', '不用追求完美，先把它说出口。')],
             tail=3.1),
        dict(n='26', title='收藏，下次讲自己时过一遍',
             lines=[(480, '拾句英语', 100, 'green', False),
                    (650, '两分钟，把一件小事讲成「这就是我」', 44, 'fg', False),
                    (850, '请人讲   take sb back to + 记忆', 36, 'green2', False),
                    (925, '做假设   if it had been A, I would have done B', 34, 'green2', False),
                    (1000, '讲清楚   … enough to be worth doing', 36, 'green2', False),
                    (1200, '听懂一句，再把它说出来', 40, 'mute', False)],
             speech=[('zh', '这一期我们讲了一件小事怎么讲成「这就是我」：怎么请人讲一段记忆，'
                            '怎么对过去做假设，怎么把一件事说成「值得」。先收藏，下次要讲自己的故事时，把这三句过一遍。'),
                     ('zh', '拾句英语，听懂一句，再把它说出来。')]),
    ],
)


# ---- 05 女性气质（原片 490.25–685.79，195 秒）----
# 2026-09 新片规格全用默认：v2 深色 + 宋体 + eleven_v3 + 1.2 倍速 + 无页脚，SPEC 里不用再写。
# 有原声的卡正文排 950 起（下半区放开后最多 7 行：950/1030/1110/1190/1270/1350/1410）。
SPECS['谷爱凌_女性气质'] = dict(
    src='__DATA_ROOT__/小红书发帖-拾句英语/谷爱凌/谷爱凌最新全英访谈.mp4',
    cards=[
        # ---- 第 0 章 钩子 + 完整听一遍（这一段 195 秒，比前几条长，拆成上中下三张）----
        dict(n='01', title='你是团队里「唯一的那一个」吗？',
             lines=[(770, '跟着 3 分钟访谈学表达', 46, 'green', False),
                    (920, '习惯 · 唯一的身份 · 还没完成的事', 40, 'fg', False),
                    (1000, '20 个表达，就藏在 3 分 15 秒里', 34, 'mute', False)],
             speech=[('zh', '你是团队里唯一的那一个吗？唯一的女生、唯一的外国人、唯一的新人。'
                            '谷爱凌七岁就碰到这个问题——她是滑雪队里唯一的女孩。'),
                     ('zh', '这段 3 分 15 秒里，她讲了那种压力从哪来，也讲了怎么和自己的女性身份相处。'
                            '我们先完整听一遍，再一句一句拆。')]),
        dict(n='02', title='先完整听一遍（上）',
             lines=[(950, 'Have you journaled pretty much', 42, 'fg', True),
                    (1030, 'every day since that time?', 42, 'green', True),
                    (1230, '先听前 65 秒', 44, 'green2', False),
                    (1300, '不用急着听懂，注意语气和节奏就好', 40, 'mute', False)],
             speech=[('zh', '先听前 65 秒。不用急着听懂，注意语气和节奏就好。')],
             source=(490.25, 555.41)),
        dict(n='03', title='先完整听一遍（中）',
             lines=[(950, 'the only girl on my ski team', 42, 'fg', True),
                    (1030, 'carrying all of womanhood', 42, 'green', True),
                    (1230, '再听 65 秒', 44, 'green2', False),
                    (1300, '这一段讲「一个人代表一群人」', 38, 'mute', False)],
             speech=[('zh', '再听 65 秒。这一段她讲的是「一个人代表一群人」，也聊到了和 Dior 的合作。')],
             source=(555.41, 620.45)),
        dict(n='04', title='先完整听一遍（下）',
             lines=[(950, 'femininity is not the color pink', 42, 'fg', True),
                    (1030, 'in all its multi-dimensional nuance', 40, 'green', True),
                    (1230, '最后 65 秒', 44, 'green2', False),
                    (1300, '听完这一遍，我们就开始拆', 40, 'mute', False)],
             speech=[('zh', '最后 65 秒。她说女性气质不是粉色，不是大家都笑、都留同一个发型。'
                            '听完这一遍，我们就开始拆。')],
             source=(620.45, 685.79)),
        # ---- 第 1 章 对一件事忽冷忽热 ----
        dict(n='05', title='对一件事忽冷忽热',
             lines=[(950, 'Have you journaled pretty much', 42, 'fg', True),
                    (1030, 'every day, or did you fall in', 42, 'green2', True),
                    (1110, 'and out of love with it?', 42, 'green2', True),
                    (1190, '你是天天写，还是写着写着就撂下了？', 38, 'fg', False),
                    (1330, 'fall in and out of love with sth', 34, 'green', True)],
             speech=[('zh', '先说一个谈习惯很好用的说法。'),
                     ('en', 'fall in and out of love with something'),
                     ('zh', '，对某件事忽冷忽热——一阵子爱得不行，一阵子又完全不想碰。'),
                     ('zh', '主持人问她：'),
                     ('en', 'Have you journaled pretty much every day since that time, or did you fall in and out of love with it?'),
                     ('zh', '，你是从那时候起几乎天天写，还是写着写着就撂下了？'),
                     ('zh', '句子里还有 '), ('en', 'pretty much'),
                     ('zh', '，等于 almost、basically，但更口语，意思是「差不多、基本上」。')],
             source=(496.17, 501.53)),
        dict(n='06', title='换你来说',
             lines=[(470, 'I fall in and out of love with', 46, 'green2', True),
                    (560, 'things — I’ve never kept one', 46, 'green2', True),
                    (650, 'habit for a whole year.', 46, 'green2', True),
                    (870, '我做事总忽冷忽热，没一个习惯撑满过一年', 40, 'fg', False),
                    (1090, 'things 换成你的事：背单词 / 跑步 / 早睡', 38, 'mute', False)],
             speech=[('zh', '换你来说一句。'),
                     ('en', 'I fall in and out of love with things — I’ve never kept one habit for a whole year.'),
                     ('zh', '，我做事总忽冷忽热，没一个习惯撑满过一年。'),
                     ('zh', '这是我们的原创练习句。把 things 换成你的事——背单词、跑步、早睡，都能直接套。')]),
        # ---- 第 2 章 换个说法 / 反复出现的主题 ----
        dict(n='07', title='换个说法：更像是……',
             lines=[(950, 'I would describe it more as', 44, 'green2', True),
                    (1030, 'an anthology of essays.', 44, 'green2', True),
                    (1190, '我会说它更像一本散文选集', 42, 'fg', False),
                    (1330, 'I would describe it more as …', 36, 'green', True)],
             speech=[('zh', '别人理解得不准，怎么换个说法纠正。'),
                     ('en', 'I would describe it more as an anthology of essays.'),
                     ('zh', '，我会说它更像一本散文选集。'),
                     ('zh', '句式 '), ('en', 'I would describe it more as …'),
                     ('zh', '，把「我不同意你」换成了「我会这么描述」——语气软，立场还是清楚的。'),
                     ('en', 'anthology'), ('zh', ' 是选集，作品集、案例集都能用这个词。')],
             source=(509.49, 511.81)),
        dict(n='08', title='「反复出现的主题」',
             lines=[(950, 'what is one thematic principle', 42, 'fg', True),
                    (1030, 'that keeps recurring, maybe', 42, 'green2', True),
                    (1110, 'today or this week?', 42, 'green2', True),
                    (1190, '有没有哪个主题一直在反复出现？', 42, 'fg', False),
                    (1330, 'a recurring theme / keep recurring', 32, 'green', True)],
             speech=[('zh', '要谈自己的长期课题，这句是现成的说法。'), ('en', 'recurring'),
                     ('zh', '，反复出现的；'), ('en', 'a recurring theme'),
                     ('zh', '，一个反复出现的主题。'),
                     ('zh', '她说写日记不记流水账，而是每周挑一个问题问自己：'),
                     ('en', 'what is one thematic principle that keeps recurring, maybe today or this week or within a month?'),
                     ('zh', '。工作里也一样，'), ('en', 'a recurring issue'),
                     ('zh', ' 就是「反复出现的问题」。')],
             source=(512.79, 518.49)),
        # ---- 第 3 章 我的长期课题 ----
        dict(n='09', title='grapple：一直在跟自己较劲',
             lines=[(950, 'it’s like my continual grappling', 42, 'fg', True),
                    (1030, 'with my sense of femininity,', 42, 'green2', True),
                    (1110, 'like growing into that.', 42, 'green2', True),
                    (1190, '我一直在跟「什么是女性气质」较劲', 38, 'fg', False),
                    (1330, 'grapple with sth', 40, 'green', True)],
             speech=[('zh', '要讲「长期在对付一件难事」，用这个动词。'), ('en', 'grapple with something'),
                     ('zh', '，努力应对、一直跟它较劲——比 deal with 有分量，也比 struggle with 更强调「在想、在琢磨」。'),
                     ('zh', '她说：'),
                     ('en', 'it’s like my continual grappling with my sense of femininity, like growing into that'),
                     ('zh', '，我一直在跟自己对女性气质的理解较劲，学着长成那个样子。')],
             source=(523.53, 529.89)),
        dict(n='10', title='自问自答：怎么平衡 A 和 B？',
             lines=[(950, 'How do I balance my', 44, 'green2', True),
                    (1030, 'masculine feminine sides?', 44, 'green2', True),
                    (1190, '我怎么平衡自己身上刚和柔的两面？', 40, 'fg', False),
                    (1330, 'How do I balance A and B?', 38, 'green', True)],
             speech=[('zh', '她把心里的问题直接问了出来。'),
                     ('en', 'How do I balance my masculine feminine sides?'),
                     ('zh', '，我怎么平衡自己身上刚和柔的两面？'),
                     ('zh', '用疑问句讲内心活动，是自述和演讲里很好用的一招：'),
                     ('en', 'How do I balance A and B?'),
                     ('zh', ' 比 I have to balance A and B 更像在思考，而不是在汇报。')],
             source=(530.03, 532.81)),
        dict(n='11', title='既要用上自己的力量，又不想……',
             lines=[(950, 'How do I inhabit my power', 42, 'green2', True),
                    (1030, 'without feeling shameful', 42, 'green2', True),
                    (1110, 'about it and also without', 42, 'green2', True),
                    (1190, 'feeling performative about it?', 42, 'green2', True),
                    (1330, 'without feeling + 形容词 + about it', 30, 'green', True)],
             speech=[('zh', '这一句讲自我认同，结构值得记。'), ('en', 'How do I inhabit my power'),
                     ('zh', '，我怎么真正用上自己的力量——'), ('en', 'inhabit'),
                     ('zh', ' 本来是「住进」，这里指安住在某个身份里，不是装出来，也不是退回去。'),
                     ('zh', '后面两个 '),
                     ('en', 'without feeling shameful about it and also without feeling performative about it'),
                     ('zh', '，既不为它羞愧，也不像在表演。'),
                     ('zh', '框架是 '), ('en', 'without feeling + 形容词 + about it'),
                     ('zh', '，谈自我认同、谈边界都能用。')],
             source=(533.49, 539.69)),
        dict(n='12', title='换你来说',
             lines=[(470, 'How do I speak up without', 46, 'green2', True),
                    (560, 'sounding aggressive, and', 46, 'green2', True),
                    (650, 'without staying quiet?', 46, 'green2', True),
                    (870, '怎么说出口才不像挑事，又不至于憋着', 40, 'fg', False),
                    (1090, '两个 without 后面，换成你自己的顾虑', 38, 'mute', False)],
             speech=[('zh', '换你来说一句。'),
                     ('en', 'How do I speak up without sounding aggressive, and without staying quiet?'),
                     ('zh', '，怎么说出口才不像在挑事，又不至于憋着不说。'),
                     ('zh', '这是我们的原创练习句。把两个 without 后面的形容词换成你自己的顾虑就行。')]),
        # ---- 第 4 章 一个人代表一群人 ----
        dict(n='13', title='acutely aware：格外清楚',
             lines=[(950, 'So I was like acutely aware', 42, 'fg', True),
                    (1030, 'of gender and gender dynamics.', 42, 'green2', True),
                    (1190, '所以我那时特别在意性别这件事', 40, 'fg', False),
                    (1330, 'be acutely aware of sth', 38, 'green', True)],
             speech=[('zh', '「非常清楚」有更准的说法。'), ('en', 'be acutely aware of something'),
                     ('zh', '，格外清楚、敏感地意识到——比 very aware 更用力，还带一点不自在的意味。'),
                     ('zh', '她说：'), ('en', 'So I was like acutely aware of gender and gender dynamics.'),
                     ('zh', '，所以我那时特别在意性别，也在意性别带来的那些微妙关系。'),
                     ('zh', '写风险提示、讲合规的时候，'), ('en', 'we are acutely aware of the risk'),
                     ('zh', ' 比 we know the risk 专业得多。')],
             source=(552.15, 555.13)),
        dict(n='14', title='一个人背着整个群体',
             lines=[(950, 'you feel like you’re carrying', 42, 'fg', True),
                    (1030, 'all of womanhood on your', 42, 'green2', True),
                    (1110, 'shoulders, because you’re', 42, 'green2', True),
                    (1190, 'the only one who’s representing.', 40, 'green2', True),
                    (1330, 'carry sth on your shoulders', 34, 'green', True)],
             speech=[('zh', '「一个人代表一群人」的压力，英语里有现成的说法。'),
                     ('en', 'carry something on your shoulders'), ('zh', '，把某事扛在肩上。'),
                     ('zh', '她说：'),
                     ('en', 'if you’re the only girl in a ski team, you feel like you’re carrying all of womanhood on your shoulders, because you’re the only one who’s representing.'),
                     ('zh', '，滑雪队里只有你一个女生，你会觉得自己背着「全体女性」，因为只有你在代表她们。')],
             source=(558.37, 563.35)),
        dict(n='15', title='做好了是破除，做砸了是坐实',
             lines=[(950, 'if you’re good, then you’re', 42, 'fg', True),
                    (1030, 'dispelling all of these myths.', 42, 'green2', True),
                    (1110, 'But if you’re bad, then you’re', 42, 'green2', True),
                    (1190, 'corroborating them.', 42, 'green2', True),
                    (1330, 'dispel the myths / corroborate them', 30, 'green', True)],
             speech=[('zh', '这一组对照，讲群体偏见时很好用。'), ('en', 'dispel the myths'),
                     ('zh', '，破除那些成见；'), ('en', 'corroborate them'),
                     ('zh', '，坐实它们、给它们当佐证。'),
                     ('zh', '她说：'),
                     ('en', 'if you’re good, then you’re dispelling all of these myths. But if you’re bad, then you’re corroborating them.'),
                     ('zh', '，做得好，就是在破除成见；做砸了，就是在给成见递证据。'),
                     ('zh', 'corroborate 也常用来讲「互相印证」，比如两份报告相互印证。')],
             source=(566.07, 572.07)),
        dict(n='16', title='uphold：让一个成见继续成立',
             lines=[(950, 'one sample that is upholding', 42, 'fg', True),
                    (1030, 'all of these stereotypes.', 42, 'green2', True),
                    (1190, '一个人的表现，被当成整个群体的证据', 38, 'fg', False),
                    (1330, 'uphold a stereotype', 38, 'green', True)],
             speech=[('zh', '这句讲的是「以偏概全」是怎么发生的。'), ('en', 'uphold a stereotype'),
                     ('zh', '，让一个刻板印象继续成立。'),
                     ('zh', '她说：'),
                     ('en', 'suddenly, one sample that is upholding all of these stereotypes'),
                     ('zh', '——突然之间，一个人就成了那个「唯一的样本」，一个人的表现被当成整个群体的证据。'),
                     ('zh', '注意 uphold 在这里不是「支持」，而是「维持、让它继续成立」。')],
             source=(572.43, 577.93)),
        # ---- 第 5 章 还没完成的事 ----
        dict(n='17', title='承认「还在努力」',
             lines=[(950, 'I’ve grown a lot, but I would', 42, 'fg', True),
                    (1030, 'say I’m still working on it.', 42, 'green2', True),
                    (1190, '我成长了不少，但我会说我还在努力', 42, 'fg', False),
                    (1330, 'I’m still working on it.', 40, 'green', True)],
             speech=[('zh', '讲自己的短板，这两句连在一起用最稳。'),
                     ('en', 'I’ve grown a lot, but I would say I’m still working on it.'),
                     ('zh', '，我成长了不少，但我会说我还在努力。'),
                     ('zh', '先说进步，再说还没完成——比 I haven’t finished 积极，也不像 I’m not good at it '
                            '那样把自己说死。面试和述职里承认不足，这句很稳。')],
             source=(586.19, 588.51)),
        dict(n='18', title='public eye：公众视线',
             lines=[(950, 'a space that is beyond the', 42, 'fg', True),
                    (1030, 'public eye, that’s private', 42, 'green2', True),
                    (1110, 'to you, with that lock and key', 42, 'green2', True),
                    (1190, '一个在公众视线之外、只属于你的空间', 38, 'fg', False),
                    (1330, 'in / beyond the public eye', 38, 'green', True)],
             speech=[('zh', '写人物、聊名人，这个说法绕不开。'), ('en', 'in the public eye'),
                     ('zh', '，在公众视线里；'), ('en', 'beyond the public eye'), ('zh', '，在公众视线之外。'),
                     ('zh', '主持人说：'),
                     ('en', 'a space that is beyond the public eye, that’s private to you, with that lock and key'),
                     ('zh', '，一个在公众视线之外、只属于你的空间，还带一把锁。')],
             source=(591.35, 595.97)),
        # ---- 第 6 章 提问与回答里的说法 ----
        dict(n='19', title='问「你最近的思考」',
             lines=[(950, 'what have been your latest', 42, 'fg', True),
                    (1030, 'reflections on your masculinity', 40, 'green2', True),
                    (1110, 'and femininity and where they', 40, 'green2', True),
                    (1190, 'fit into your life and where', 40, 'green2', True),
                    (1270, 'you see them being expressed?', 40, 'green2', True),
                    (1410, 'sb’s latest reflections on sth', 34, 'green', True)],
             speech=[('zh', '主持人问「你最近怎么想」，用的不是 what do you think。'),
                     ('en', 'what have been your latest reflections on …?'),
                     ('zh', '，你最近对……有什么新的思考？'),
                     ('zh', '他问：'),
                     ('en', 'what have been your latest reflections on your masculinity and femininity and where they fit into your life?'),
                     ('zh', '。reflection 在这里是「思考、省思」，不是「反射」；'
                            '访谈和圆桌里问观点，这句比 What’s your opinion 客气，也更具体。')],
             source=(606.15, 614.09)),
        dict(n='20', title='play with：把玩一个想法',
             lines=[(950, 'I think he plays with it', 44, 'green2', True),
                    (1030, 'so interestingly.', 46, 'green2', True),
                    (1190, '我觉得他把这件事处理得很有意思', 42, 'fg', False),
                    (1330, 'play with sth', 40, 'green', True)],
             speech=[('zh', '聊设计、聊创意，这个动词很好用。'), ('en', 'play with something'),
                     ('zh', '，把玩、自由地处理——不是「玩」，而是「不按套路来」。'),
                     ('zh', '她说设计师：'), ('en', 'I think he plays with it so interestingly'),
                     ('zh', '，我觉得他把这件事处理得很有意思。')],
             source=(620.95, 623.05)),
        dict(n='21', title='reductive：把复杂的事削平',
             lines=[(950, 'but the outfit is not', 44, 'fg', True),
                    (1030, 'reductive in that sense, right?', 42, 'green2', True),
                    (1190, '但这身衣服并没有把这件事简单化', 42, 'fg', False),
                    (1330, 'reductive = 过度简化、削平', 38, 'mute', True)],
             speech=[('zh', '一个评价用的形容词。'), ('en', 'reductive'),
                     ('zh', '，把复杂的东西削成一句话、一个标签——听着像批评，但很克制。'),
                     ('zh', '她说这身衣服：'), ('en', 'the outfit is not reductive in that sense'),
                     ('zh', '，它没有把「年轻女孩」简化成一个刻板印象。'),
                     ('zh', '后面她还补了一个同义的 '), ('en', 'one-dimensional'),
                     ('zh', '，一个维度的、单一的。')],
             source=(628.93, 632.43)),
        dict(n='22', title='「以其全部的微妙」',
             lines=[(950, 'It’s like understanding it', 44, 'fg', True),
                    (1030, 'in all its multi-dimensional', 42, 'green2', True),
                    (1110, 'nuance.', 46, 'green2', True),
                    (1190, '是去理解它全部的多面与微妙', 42, 'fg', False),
                    (1330, 'in all its + 名词 / nuance', 36, 'green', True)],
             speech=[('zh', '这一句是整段的收尾。'),
                     ('en', 'understanding it in all its multi-dimensional nuance'),
                     ('zh', '，去理解它全部的多面与微妙。'),
                     ('zh', '框架 '), ('en', 'in all its + 名词'), ('zh', '，以其全部的……；'),
                     ('en', 'nuance'), ('zh', ' 是「微妙差别」，比 difference 更细。'),
                     ('zh', '同类的还有 '), ('en', 'in all its complexity'), ('zh', '、'),
                     ('en', 'in all its glory'), ('zh', '。')],
             source=(678.95, 681.87)),
        # ---- 第 7 章 收尾 ----
        dict(n='23', title='换你来说',
             lines=[(470, 'The tricky part is doing it', 46, 'green2', True),
                    (560, 'without feeling like you have', 46, 'green2', True),
                    (650, 'to prove something.', 46, 'green2', True),
                    (870, '难的地方在于：做的时候别像在证明什么', 38, 'fg', False),
                    (1090, 'without feeling like + 从句，接着用', 38, 'mute', False)],
             speech=[('zh', '换你来说一句。'),
                     ('en', 'The tricky part is doing it without feeling like you have to prove something.'),
                     ('zh', '，难的地方在于：做的时候别像在证明什么。'),
                     ('zh', '这是我们的原创练习句，用的就是这一章的 without 框架。')]),
        dict(n='24', title='带着这些点，再听一遍',
             lines=[(950, '现在再完整听一遍', 50, 'fg', False),
                    (1040, '你应该能听出更多东西了', 52, 'green', False),
                    (1210, '3 分 15 秒，20 个地道表达', 44, 'mute', False)],
             speech=[('zh', '现在带着刚才拆过的这些点，再完整听一遍这 3 分 15 秒。'
                            '你会发现，能听出来的东西比第一遍多得多。')],
             source=(490.25, 685.79)),
        dict(n='25', title='跟着读三遍',
             lines=[(470, '1. I fall in and out of love', 44, 'green2', True),
                    (545, 'with it every few months.', 44, 'green2', True),
                    (670, '2. I’m still working on it.', 46, 'green2', True),
                    (795, '3. I was acutely aware of how', 44, 'green2', True),
                    (870, 'the room was reading me.', 44, 'green2', True)],
             speech=[('zh', '最后挑三句最常用的，跟着读一遍。'),
                     ('en', 'I fall in and out of love with it every few months.'),
                     ('en', 'I’m still working on it.'),
                     ('en', 'I was acutely aware of how the room was reading me.'),
                     ('zh', '不用追求完美，先把它说出口。')],
             tail=3.1),
        dict(n='26', title='收藏，下次讲自己的时候过一遍',
             lines=[(480, '拾句英语', 100, 'green', False),
                    (650, '三分钟，讲清「我还没做完的那件事」', 42, 'fg', False),
                    (850, '习惯   fall in and out of love with sth', 36, 'green2', False),
                    (925, '认同   How do I … without feeling …?', 36, 'green2', False),
                    (1000, '压力   carry sth on your shoulders', 36, 'green2', False),
                    (1200, '听懂一句，再把它说出来', 40, 'mute', False)],
             speech=[('zh', '这一期讲的是「我是谁」里最难说清的那部分：怎么讲自己对一件事忽冷忽热，'
                            '怎么讲还在努力，怎么讲「一个人代表一群人」的压力。'
                            '先收藏，下次要讲自己的时候，把这三句过一遍。'),
                     ('zh', '拾句英语，听懂一句，再把它说出来。')]),
    ],
)


# ---- 06 训练日常（原片 686.15–875.27，189 秒）----
# 2026-09 新片规格全用默认：v2 深色 + 宋体 + eleven_v3 + style 0.4 + 1.2 倍速 + 无页脚。
SPECS['谷爱凌_训练日常'] = dict(
    src='__DATA_ROOT__/小红书发帖-拾句英语/谷爱凌/谷爱凌最新全英访谈.mp4',
    cards=[
        # ---- 第 0 章 钩子 + 完整听一遍（189 秒，拆上中下三张）----
        dict(n='01', title='被夸的时候，还能怎么说？',
             lines=[(770, '跟着 3 分钟访谈学表达', 46, 'green', False),
                    (920, '接夸奖 · 讲日常 · 说分量', 40, 'fg', False),
                    (1000, '21 个表达，就藏在 3 分 09 秒里', 34, 'mute', False)],
             speech=[('zh', '被夸的时候，你只会说「没有没有」吗？别人说你太厉害了、真刻苦，'
                            '除了谦虚地摆手，还能怎么说？'),
                     ('zh', '谷爱凌在这段 3 分 09 秒里示范了一次：她先说「你把我想得太好了」，'
                            '然后把真实的样子讲了出来——周末的滑雪队、周五开车四个小时、妈妈让她睡到自然醒。'
                            '我们先完整听一遍，再一句一句拆。')]),
        dict(n='02', title='先完整听一遍（上）',
             lines=[(950, 'You started training when you', 42, 'fg', True),
                    (1030, 'were seven or eight.', 42, 'green', True),
                    (1230, '先听前 65 秒', 44, 'green2', False),
                    (1300, '注意她怎么接那句夸奖', 40, 'mute', False)],
             speech=[('zh', '先听前 65 秒。注意她怎么接那句夸奖。')],
             source=(686.15, 751.11)),
        dict(n='03', title='先完整听一遍（中）',
             lines=[(950, 'she would let me sleep until', 42, 'fg', True),
                    (1030, 'I woke up naturally', 42, 'green', True),
                    (1230, '再听 65 秒', 44, 'green2', False),
                    (1300, '这一段她讲「那时候的日常」', 38, 'mute', False)],
             speech=[('zh', '再听 65 秒。这一段她讲的是那时候的日常——周五开车四个小时去太浩湖，'
                            '妈妈让她睡到自然醒。')],
             source=(751.11, 815.71)),
        dict(n='04', title='先完整听一遍（下）',
             lines=[(950, 'skiing was a great equalizer', 42, 'fg', True),
                    (1030, 'we form lifelong bonds', 42, 'green', True),
                    (1230, '最后 60 秒', 44, 'green2', False),
                    (1300, '听完这一遍，我们就开始拆', 40, 'mute', False)],
             speech=[('zh', '最后 60 秒。她讲了第一次滑栏杆的那天，还有队友一起喊出来的那一声。'
                            '听完这一遍，我们就开始拆。')],
             source=(815.71, 875.27)),
        # ---- 第 1 章 被夸的时候怎么接 ----
        dict(n='05', title='被夸过头了，怎么接',
             lines=[(950, 'Jay, I think you’re giving me', 42, 'fg', True),
                    (1030, 'a little too much credit.', 42, 'green2', True),
                    (1110, 'What do you mean?', 42, 'green2', True),
                    (1190, '你把我想得太好了', 42, 'fg', False),
                    (1330, 'give sb too much credit', 38, 'green', True)],
             speech=[('zh', '别人夸你，第一句可以这么接。'), ('en', 'give someone too much credit'),
                     ('zh', '，把功劳给多了、把对方想得太好了——不是否认，是「你夸过头了」。'),
                     ('zh', '主持人说她训练刻苦，她回：'),
                     ('en', 'Jay, I think you’re giving me a little too much credit. What do you mean?'),
                     ('zh', '， Jay，我觉得你把我夸过头了。主持人又问「怎么说？」'),
                     ('zh', '比起直接说 no，这句既接住了对方的好意，又把话头递了回去。')],
             source=(704.07, 706.31)),
        dict(n='06', title='请人介绍：Talk to me about …',
             lines=[(950, 'Talk to me about the regime,', 42, 'fg', True),
                    (1030, 'the discipline, the diet.', 42, 'green2', True),
                    (1190, '跟我讲讲你的训练、纪律、饮食', 38, 'fg', False),
                    (1330, 'Talk to me about …', 40, 'green', True)],
             speech=[('zh', '主持人问问题有个固定开场：'), ('en', 'Talk to me about …'), ('zh', '，跟我聊聊……。'),
                     ('zh', '他问：'),
                     ('en', 'Talk to me about the regime, the discipline, the diet.'),
                     ('zh', '，说说训练安排、纪律和饮食。'),
                     ('zh', '后面可以直接接名词，也可以接从句，比如 '),
                     ('en', 'Talk to me about how you started.'),
                     ('zh', ' 商务沟通里请人介绍情况，这句比 Please introduce 自然得多。')],
             source=(695.89, 699.85)),
        dict(n='07', title='换你来说',
             lines=[(470, 'Thanks — but I think you’re', 46, 'green2', True),
                    (560, 'giving me too much credit.', 46, 'green2', True),
                    (650, 'It was the team, really.', 46, 'green2', True),
                    (870, '谢谢，不过我觉得你把我夸过头了'  , 40, 'fg', False),
                    (1090, '后面接 it was the team, really. 把功劳让出去', 36, 'mute', False)],
             speech=[('zh', '换你来说一句。'),
                     ('en', 'Thanks — but I think you’re giving me too much credit. It was the team, really.'),
                     ('zh', '，谢谢，不过我觉得你把我夸过头了，其实是团队的功劳。'),
                     ('zh', '这是我们的原创练习句。先说 thanks，再用 too much credit 把夸奖推回去，最后把功劳给别人。')]),
        # ---- 第 2 章 讲「那时候的日常」----
        dict(n='08', title='讲惯例：平时一般都是这样',
             lines=[(950, 'what would usually happen', 42, 'fg', True),
                    (1030, 'would be Monday to Friday', 42, 'green2', True),
                    (1110, 'in school normally.', 42, 'green2', True),
                    (1190, '通常是这样：周一到周五正常上学', 38, 'fg', False),
                    (1330, 'what would usually happen would be …', 30, 'green', True)],
             speech=[('zh', '要讲「平时都是怎么运转的」，用这个句式。'),
                     ('en', 'what would usually happen would be …'),
                     ('zh', '，通常会是……。'),
                     ('zh', '她说：'),
                     ('en', 'what would usually happen would be Monday to Friday in school normally'),
                     ('zh', '，周一到周五就正常上学。'),
                     ('zh', '两个 would 叠在一起，讲的是惯例，不是某一次；写流程、讲 SOP、交代背景都能用。')],
             source=(717.75, 721.77)),
        dict(n='09', title='would：那时候总是……',
             lines=[(950, 'And so she would let me sleep', 42, 'fg', True),
                    (1030, 'until I woke up naturally.', 42, 'green2', True),
                    (1190, '我妈会让我一直睡到自然醒', 42, 'fg', False),
                    (1330, 'would = 那时候总是……', 40, 'green', True)],
             speech=[('zh', '讲过去的习惯，一个 would 就够了。'),
                     ('en', 'she would let me sleep until I woke up naturally'),
                     ('zh', '，她会让我一直睡到自然醒。'),
                     ('zh', '这里不是「将要」，而是「那时候总是」——和 used to 意思接近，但 would 更常用来讲重复的动作，'
                            '听起来也更像在讲画面。')],
             source=(751.85, 754.67)),
        dict(n='10', title='该干嘛干嘛：do whatever I need to do',
             lines=[(950, 'do homework, eat, prep,', 42, 'fg', True),
                    (1030, 'do whatever I need to do.', 42, 'green2', True),
                    (1190, '写作业、吃饭、准备，该干嘛干嘛', 40, 'fg', False),
                    (1330, 'do whatever I need to do', 38, 'green', True)],
             speech=[('zh', '路上那四个小时干什么？她一句带过。'),
                     ('en', 'do homework, eat, prep, do whatever I need to do'),
                     ('zh', '，写作业、吃饭、准备，该干嘛干嘛。'),
                     ('zh', '把话收在 '), ('en', 'whatever I need to do'),
                     ('zh', ' 上，等于「看情况、要什么做什么」。同源的还有 '),
                     ('en', 'whatever it takes'), ('zh', '，不惜一切代价。')],
             source=(730.55, 733.63)),
        dict(n='11', title='不浪费：just to take advantage',
             lines=[(950, 'my mom and I would probably', 42, 'fg', True),
                    (1030, 'ski another hour just to', 42, 'green2', True),
                    (1110, 'take advantage.', 42, 'green2', True),
                    (1190, '我们俩会再滑一小时，不浪费这趟', 38, 'fg', False),
                    (1330, 'just to take advantage (of it)', 34, 'green', True)],
             speech=[('zh', '「既然都来了，就别浪费」这句话她只说了一半。'),
                     ('en', 'my mom and I would probably ski another hour just to take advantage'),
                     ('zh', '，我们俩多半会再滑一个小时，就为了把这一趟用足。'),
                     ('zh', '完整说法是 '), ('en', 'take advantage of something'),
                     ('zh', '，好好利用；口语里 of it 常常省掉。'),
                     ('zh', '注意它和「占便宜」是两回事——占便宜是 '),
                     ('en', 'take advantage of someone'), ('zh', '，对象是人。')],
             source=(765.27, 768.97)),
        # ---- 第 3 章 划重点：不是虎妈 ----
        dict(n='12', title='要划重点了',
             lines=[(950, 'and this is actually', 44, 'fg', True),
                    (1030, 'an important distinction.', 42, 'green2', True),
                    (1190, '这一点其实很关键', 44, 'fg', False),
                    (1330, 'this is an important distinction', 32, 'green', True)],
             speech=[('zh', '讲一段话，怎么告诉别人「注意，这里是重点」。'),
                     ('en', 'this is actually an important distinction'),
                     ('zh', '，这一点其实很关键——distinction 是「区别」，'
                            '背后意思是「这两件事常被混为一谈，其实不一样」。'),
                     ('zh', '比 '), ('en', 'this is important'),
                     ('zh', ' 更具体，也比 flag 之类的行话自然。')],
             source=(735.81, 737.89)),
        dict(n='13', title='tiger mom：虎妈，和一句强否定',
             lines=[(950, 'A lot of people think my mom', 40, 'fg', True),
                    (1030, 'is a tiger mom. She’s totally not.', 40, 'green2', True),
                    (1110, 'Her number one thing was always sleep.', 38, 'green2', True),
                    (1270, '很多人以为我妈是虎妈，她完全不是', 36, 'fg', False),
                    (1350, '她最在意的永远是睡觉', 36, 'mute', False),
                    (1410, 'tiger mom / one’s number one thing', 32, 'green', True)],
             speech=[('zh', '先记一个跨文化词。'), ('en', 'tiger mom'),
                     ('zh', '，虎妈——这个词已经进了英语词典，聊教育、聊原生家庭都用得到。'),
                     ('zh', '否认要说得干脆，她用的是 '), ('en', 'She’s totally not.'),
                     ('zh', '，她完全不是——totally 加否定，一点余地都不留。'),
                     ('zh', '接着她说 '), ('en', 'Her number one thing was always sleep.'),
                     ('zh', '，她最在意的一件事永远是睡觉。'),
                     ('en', 'one’s number one thing'), ('zh', ' 就是「某人最看重的东西」，'
                            '换成 you 也一样：'), ('en', 'My number one priority is sleep.')],
             source=(738.11, 743.19)),
        dict(n='14', title='换你来说',
             lines=[(470, 'I’m not a morning person —', 46, 'green2', True),
                    (560, 'my number one thing is sleep.', 46, 'green2', True),
                    (650, 'Work can wait.', 46, 'green2', True),
                    (870, '我不是早起型的人，我最在意的就是睡觉'  , 40, 'fg', False),
                    (1090, 'number one thing 换成你最在意的那件事', 38, 'mute', False)],
             speech=[('zh', '换你来说一句。'),
                     ('en', 'I’m not a morning person — my number one thing is sleep. Work can wait.'),
                     ('zh', '，我不是早起型的人，我最在意的就是睡觉，工作可以等。'),
                     ('zh', '这是我们的原创练习句。把 number one thing 换成你最在意的那件事。')]),
        # ---- 第 4 章 把一句话说出分量 ----
        dict(n='15', title='加上「时至今日仍然如此」',
             lines=[(950, 'that was the most important', 42, 'fg', True),
                    (1030, 'factor, and still is to this day.', 40, 'green2', True),
                    (1190, '那是最重要的因素，时至今日仍然如此', 38, 'fg', False),
                    (1330, 'and still is to this day', 38, 'green', True)],
             speech=[('zh', '一句话怎么说出分量？她加了一个尾巴。'),
                     ('en', 'that was the most important factor, and still is to this day'),
                     ('zh', '，那是最重要的因素，时至今日仍然如此。'),
                     ('zh', '前面用过去时 '), ('en', 'was'), ('zh', '，后面 '),
                     ('en', 'and still is'), ('zh', ' 把时态拉回现在——一个小小的转折，'
                            '就把「当时」变成了「一直都是」。'),
                     ('en', 'to this day'), ('zh', '，直到今天。')],
             source=(775.07, 779.79)),
        dict(n='16', title='great equalizer：把差别抹平的东西',
             lines=[(950, 'but beyond that, skiing was', 42, 'fg', True),
                    (1030, 'a great equalizer, right?', 42, 'green2', True),
                    (1190, '但除此之外，滑雪是件很公平的事', 40, 'fg', False),
                    (1330, 'a great equalizer', 40, 'green', True)],
             speech=[('zh', '谈「什么东西对所有人一视同仁」，这个词很准。'),
                     ('en', 'a great equalizer'), ('zh', '，伟大的平衡器——'
                            '把差距拉平的东西。'),
                     ('zh', '她说：'),
                     ('en', 'but beyond that, skiing was a great equalizer, right?'),
                     ('zh', '，但除此之外，滑雪是件很公平的事。'),
                     ('zh', '后面她解释为什么：任何人只要是人类，都知道害怕是什么感觉——'
                            '而害怕不分性别。写观点类文章时，这是一个能撑起一段话的名词。')],
             source=(782.13, 784.67)),
        dict(n='17', title='让身体去做它从没做过的事',
             lines=[(950, 'how elated you feel when you’re', 40, 'fg', True),
                    (1030, 'asking your body to do something', 40, 'green2', True),
                    (1110, 'it’s never done before.', 40, 'green2', True),
                    (1190, '让身体去做一件它从没做过的事', 40, 'fg', False),
                    (1330, 'ask your body to do sth it’s never done before', 28, 'green', True)],
             speech=[('zh', '这句把运动讲得很动人。' ), ('en', 'elated'),
                     ('zh', '，兴高采烈、狂喜——比 happy 高一档。'),
                     ('zh', '她说：'),
                     ('en', 'how elated you feel when you’re asking your body to do something it’s never done before'),
                     ('zh', '，当你让身体去做一件它从没做过的事，那种兴奋你懂。'),
                     ('zh', '把身体当成人来写——'), ('en', 'ask your body to do something'),
                     ('zh', '——是英语里很常见的拟人手法，讲运动、讲突破都能借。')],
             source=(793.09, 797.55)),
        dict(n='18', title='bond with sb：一下就拉近了',
             lines=[(950, 'it just makes you bond with', 42, 'fg', True),
                    (1030, 'people that you’re experiencing', 40, 'green2', True),
                    (1110, 'it with that much more.', 40, 'green2', True),
                    (1190, '你会和一起经历的人靠得更近', 42, 'fg', False),
                    (1330, 'bond with sb / that much more', 34, 'green', True)],
             speech=[('zh', '讲「关系变近」，用这个动词。'), ('en', 'bond with someone'),
                     ('zh', '，和某人建立情感联结——比 get closer 更实，也更常用于团队。'),
                     ('zh', '她说：'),
                     ('en', 'it just makes you bond with people that you’re experiencing it with that much more'),
                     ('zh', '，这种很人类、很浓的情绪，会让你和一起经历的人贴得更近。'),
                     ('zh', '句尾的 '), ('en', 'that much more'), ('zh', '，也就是「还要再多上几分」。')],
             source=(803.25, 806.83)),
        # ---- 第 5 章 讲自己的队伍 ----
        dict(n='19', title='healthy competition：良性的竞争',
             lines=[(950, 'it just encouraged this really', 42, 'fg', True),
                    (1030, 'healthy sportsmanship and really', 40, 'green2', True),
                    (1110, 'healthy competition.', 42, 'green2', True),
                    (1190, '它养出了很健康的竞争心态', 42, 'fg', False),
                    (1330, 'healthy sportsmanship / competition', 30, 'green', True)],
             speech=[('zh', '讲团队氛围，这两个词很管用。'), ('en', 'sportsmanship'),
                     ('zh', '，运动家精神——不是「胜者为王」那种，而是守规矩、服输、为对手叫好。'),
                     ('zh', '她说教练那点小奖励：'),
                     ('en', 'it just encouraged this really healthy sportsmanship and really healthy competition'),
                     ('zh', '，它反而养出了很健康的运动精神和竞争心态。'),
                     ('zh', 'healthy 加在 competition 前面，就把「内卷」和「比着进步」区分开了。')],
             source=(815.71, 819.89)),
        dict(n='20', title='if not the best：留了余地的最高级',
             lines=[(950, 'I was definitely one of the best,', 40, 'fg', True),
                    (1030, 'if not the best on the team.', 42, 'green2', True),
                    (1190, '我肯定是队里最好的之一，或者说就是最好的', 34, 'fg', False),
                    (1330, 'one of the best, if not the best', 32, 'green', True)],
             speech=[('zh', '想夸自己又不想显得狂，可以这么写。'),
                     ('en', 'one of the best, if not the best'),
                     ('zh', '，最好的之一——如果不是最好的话。'),
                     ('zh', '她说：'),
                     ('en', 'I was definitely one of the best, if not the best on the team.'),
                     ('zh', '，if not 是插入语，语气上退了一步，实际上把话推到了最高级。'
                            '写履历、做自评都能用。')],
             source=(821.89, 824.59)),
        dict(n='21', title='jostle for position：争那个位置',
             lines=[(950, 'there were several others', 42, 'fg', True),
                    (1030, 'and we would be jostling', 42, 'green2', True),
                    (1110, 'for that position', 42, 'green2', True),
                    (1190, '还有好几个人，我们都在争那个位置', 40, 'fg', False),
                    (1330, 'jostle for position', 40, 'green', True)],
             speech=[('zh', '讲竞争，这个动词有画面。'), ('en', 'jostle for position'),
                     ('zh', '，挤着争一个位置——jostle 本来是人在人群里挤来挤去。'),
                     ('zh', '她说：'),
                     ('en', 'there were several others and we would be jostling for that position'),
                     ('zh', '，还有好几个人，我们都在争那个位置。'),
                     ('zh', '比 '), ('en', 'compete for'), ('zh', ' 多一点画面感和分寸感，'
                            '放在职场语境里也不刺耳。')],
             source=(824.89, 828.85)),
        dict(n='22', title='keyed up：又紧张又兴奋',
             lines=[(950, 'I was like, keyed up,', 44, 'fg', True),
                    (1030, 'I do it.', 46, 'green2', True),
                    (1190, '我绷着一股劲，就上了', 42, 'fg', False),
                    (1330, 'keyed up = 又紧张又兴奋', 40, 'green', True)],
             speech=[('zh', '比 nervous 多一层兴奋。'), ('en', 'keyed up'),
                     ('zh', '，因为期待而紧绷——手心出汗，但你想上。'),
                     ('zh', '轮到她第一次滑栏杆：'),
                     ('en', 'I was like, keyed up, I do it.'),
                     ('zh', '，我绷着一股劲，就上了。'),
                     ('zh', '上台前、提案前那种状态，用这个词比 I was nervous 更像在期待。')],
             source=(850.49, 852.81)),
        dict(n='23', title='一辈子交情：lifelong bonds',
             lines=[(950, 'you’re really sharing it with', 42, 'fg', True),
                    (1030, 'people that you form', 42, 'green2', True),
                    (1110, 'lifelong bonds with', 42, 'green2', True),
                    (1190, '你是在和这些人结下一辈子的交情', 38, 'fg', False),
                    (1330, 'form lifelong bonds with sb', 36, 'green', True)],
             speech=[('zh', '讲一段共同经历留下了什么，这句很收得住。'),
                     ('en', 'form lifelong bonds with someone'),
                     ('zh', '，和某人结下一辈子的交情。'),
                     ('zh', '她说：'),
                     ('en', 'you’re really sharing it with people that you form lifelong bonds with'),
                     ('zh', '，你是在和这些人分享，而你们会结下一辈子的交情。'),
                     ('zh', '离职感言、团队总结里用 form lifelong bonds，比 become good friends 更有分量。')],
             source=(863.45, 866.91)),
        dict(n='24', title='go on to become：后来做到了',
             lines=[(950, 'Even though the others', 44, 'fg', True),
                    (1030, 'didn’t go on to become', 42, 'green2', True),
                    (1110, 'professional skiers', 44, 'green2', True),
                    (1190, '虽然其他人后来没有成为职业选手', 40, 'fg', False),
                    (1330, 'go on to become …', 40, 'green', True)],
             speech=[('zh', '讲履历、讲后来，这个短语很关键。'),
                     ('en', 'go on to become …'), ('zh', '，后来进而成了……。'),
                     ('zh', '她说：'),
                     ('en', 'Even though the others didn’t go on to become professional skiers'),
                     ('zh', '，虽然其他人后来没有成为职业选手。'),
                     ('zh', 'go on to 后面还可以接 do 或 achieve：'),
                     ('en', 'She went on to lead the team.'), ('zh', ' 讲「在那之后做到了」，就用它。')],
             source=(869.19, 872.17)),
        # ---- 第 6 章 收尾 ----
        dict(n='25', title='换你来说',
             lines=[(470, 'We were competing back then,', 46, 'green2', True),
                    (560, 'but we went on to become', 46, 'green2', True),
                    (650, 'friends for life.', 46, 'green2', True),
                    (870, '我们那时候在争，后来成了一辈子的朋友'  , 38, 'fg', False),
                    (1090, 'go on to become 后面接你后来做到的事', 38, 'mute', False)],
             speech=[('zh', '换你来说一句。'),
                     ('en', 'We were competing back then, but we went on to become friends for life.'),
                     ('zh', '，我们那时候在争，后来成了一辈子的朋友。'),
                     ('zh', '这是我们的原创练习句。go on to become 后面，接你后来真正做到的事。')]),
        dict(n='26', title='带着这些点，再听一遍',
             lines=[(950, '现在再完整听一遍', 50, 'fg', False),
                    (1040, '你应该能听出更多东西了', 52, 'green', False),
                    (1210, '3 分 09 秒，21 个地道表达', 44, 'mute', False)],
             speech=[('zh', '现在带着刚才拆过的这些点，再完整听一遍这 3 分 09 秒。'
                            '这一次，你会听出她是怎么把一句夸奖接住的，也会听到她讲那件滑栏杆的事。')],
             source=(686.15, 875.27)),
        dict(n='27', title='跟着读三遍',
             lines=[(470, '1. I think you’re giving me', 44, 'green2', True),
                    (545, 'a little too much credit.', 44, 'green2', True),
                    (670, '2. It was so much fun, and', 44, 'green2', True),
                    (740, 'still is to this day.', 44, 'green2', True),
                    (865, '3. We form lifelong bonds.', 44, 'green2', True)],
             speech=[('zh', '最后挑三句最常用的，跟着读一遍。'),
                     ('en', 'I think you’re giving me a little too much credit.'),
                     ('en', 'It was so much fun, and still is to this day.'),
                     ('en', 'We form lifelong bonds.'),
                     ('zh', '不用追求完美，先把它说出口。')],
             tail=3.1),
        dict(n='28', title='收藏，下次被夸的时候过一遍',
             lines=[(480, '拾句英语', 100, 'green', False),
                    (650, '三分钟，学会接住别人的夸奖', 42, 'fg', False),
                    (850, '接夸   give sb too much credit', 36, 'green2', False),
                    (925, '日常   what would usually happen would be …', 32, 'green2', False),
                    (1000, '分量   and still is to this day', 36, 'green2', False),
                    (1200, '听懂一句，再把它说出来', 40, 'mute', False)],
             speech=[('zh', '这一期讲的是三件小事：别人夸你的时候怎么接得住，'
                            '小时候的日常怎么讲清楚，还有怎么给一句话加上「时至今日仍然如此」的分量。'),
                     ('zh', '先收藏，下次被夸的时候，把这三句过一遍。'
                            '拾句英语，听懂一句，再把它说出来。')]),
    ],
)


# ---- 07 妈妈和奶奶（原片 875.71–998.42，122.71 秒）----
# 与 06 章的边界（原片 16:35）原来切在「And so she」半句上，本条把结尾挪到 16:38.31
# （`okay, how?` 说完）——是完整句子；08 章从 16:38.4 接。
# 2026-09 新片规格全用默认：v2 深色 + 宋体 + eleven_v3 + style 0.4 + 1.2 倍速 + 无页脚。
SPECS['谷爱凌_妈妈和奶奶'] = dict(
    src='__DATA_ROOT__/小红书发帖-拾句英语/谷爱凌/谷爱凌最新全英访谈.mp4',
    cards=[
        # ---- 第 0 章 钩子 + 完整听一遍（122.71 秒，拆上下两张）----
        dict(n='01', title='讲一个人，怎么讲得不空？',
             lines=[(770, '跟着 2 分钟访谈学表达', 46, 'green', False),
                    (920, '提炼 · 强调 · 传承', 40, 'fg', False),
                    (1000, '20 个表达，就藏在 2 分 03 秒里', 34, 'mute', False)],
             speech=[('zh', '被问到「谁对你影响最大」，你是不是只能憋出一句 she is very nice？'
                            '别人讲家里人讲得又具体又动人，你只会说「我妈很伟大」。'),
                     ('zh', '谷爱凌在这段 2 分 03 秒里示范了一次：她先用一句话把奶奶说清楚——'),
                     ('en', 'my grandma was the dreamer'),
                     ('zh', '，再讲奶奶 21 岁在铜矿管着一群男人，最后说到这股劲头怎么传给了妈妈。'
                            '我们先完整听一遍，再一句一句拆。')]),
        dict(n='02', title='先听前 64 秒',
             lines=[(950, 'You speak about your mom', 44, 'green2', True),
                    (1030, 'so beautifully.', 44, 'green2', True),
                    (1190, '先听前 64 秒', 42, 'fg', False),
                    (1330, '注意她怎么用一个词概括一个人', 38, 'mute', False)],
             speech=[('zh', '先听前 64 秒。她先被问到从妈妈和奶奶身上学到了什么，'
                            '然后用一句话把奶奶说清楚，再讲奶奶 21 岁在铜矿的事。')],
             source=(875.71, 939.95)),
        dict(n='03', title='再听最后 58 秒',
             lines=[(950, 'Not once has she ever', 44, 'green2', True),
                    (1030, 'had a victim mentality.', 44, 'green2', True),
                    (1190, '最后 58 秒', 42, 'fg', False),
                    (1330, '这一段她讲「那股劲怎么传下来」', 38, 'mute', False)],
             speech=[('zh', '最后 58 秒。她讲了奶奶从来没有受害者心态，也讲了这份劲头怎么传到妈妈身上。'
                            '听完这一遍，我们就开始拆。')],
             source=(940.49, 998.42)),
        # ---- 第 1 章 一句话把她说清楚 ----
        dict(n='04', title='一句话把她说清楚',
             lines=[(950, 'If I were to distill it,', 44, 'green2', True),
                    (1030, 'I would say my grandma', 42, 'green2', True),
                    (1110, 'was the dreamer.', 42, 'green2', True),
                    (1190, '要概括一个人，先用这句起手', 40, 'fg', False),
                    (1330, 'If I were to distill it, I would say …', 38, 'green', True)],
             speech=[('zh', '要把一个人说清楚，先用这句起手。'),
                     ('en', 'If I were to distill it, I would say …'),
                     ('zh', '，如果要我提炼一句，我会说……。distill 是「蒸馏」，'
                            '也就是把一堆细节浓缩成一句话。她说：'),
                     ('en', 'If I were to distill it, I would say my grandma was the dreamer.'),
                     ('zh', '，要我说，我奶奶是个梦想家。虚拟语气 were to 让语气谦和，不像在下定论。')],
             source=(904.61, 908.31)),
        dict(n='05', title='形容人，说到顶',
             lines=[(950, 'She is the most dauntless,', 42, 'green2', True),
                    (1030, 'just go-getter optimist', 42, 'green2', True),
                    (1110, 'that I’ve ever met', 42, 'green2', True),
                    (1190, '我这辈子见过的最……的人', 40, 'fg', False),
                    (1330, 'the most … that I’ve ever met', 38, 'green', True)],
             speech=[('zh', '夸一个人夸到顶，用这个句式。'),
                     ('en', 'the most … that I’ve ever met'),
                     ('zh', '，我这辈子见过的最……的。她说：'),
                     ('en', 'She is the most dauntless, just go-getter optimist '
                            'that I’ve ever met in my entire life.'),
                     ('zh', '，她是我这辈子见过最无所畏惧、最有行动力的乐观主义者。'
                            'dauntless 是不怕事，go-getter 是想要就去拿的人——两个词都比 brave 具体。')],
             source=(908.31, 915.63)),
        dict(n='06', title='换你来说',
             lines=[(470, 'If I were to distill it, my dad', 44, 'green2', True),
                    (560, 'is the calmest person in any', 44, 'green2', True),
                    (650, 'room — nothing flusters him.', 44, 'green2', True),
                    (870, '要我说，我爸是屋里最沉得住气的人', 38, 'fg', False),
                    (1090, 'distill 后面接你最想说的那一句', 38, 'mute', False)],
             speech=[('zh', '换你来说一句。'),
                     ('en', 'If I were to distill it, my dad is the calmest person in any room '
                            '— nothing flusters him.'),
                     ('zh', '，要我说，我爸是屋里最沉得住气的人，什么事都慌不到他。'
                            '这是我们的原创练习句。把 distill 后面那半句，换成你最想说的那一句。')]),
        # ---- 第 2 章 她有多不一样 ----
        dict(n='07', title='把否定说得很重',
             lines=[(950, 'Not once has she ever', 44, 'green2', True),
                    (1030, 'had a victim mentality.', 44, 'green2', True),
                    (1190, '她从来没有过受害者心态', 40, 'fg', False),
                    (1330, 'Not once has she ever …', 38, 'green', True)],
             speech=[('zh', '要把「从来没有」说得重，就把 Not once 提到句首。'),
                     ('en', 'Not once has she ever had a victim mentality.'),
                     ('zh', '，她从来没有过受害者心态。否定词一提前，语序就倒装，'
                            '语气比 She never had 重得多。这一句之后她又说了一遍：'),
                     ('en', 'Not once has she ever thought, oh, it was so difficult.'),
                     ('zh', '，她从没想过「那太难了」。同一个句式连说两遍，就是在强调。')],
             source=(940.65, 946.09)),
        dict(n='08', title='oversee：管着一群人',
             lines=[(950, 'She was in the mines,', 44, 'green2', True),
                    (1030, 'overseeing men in the mines.', 42, 'green2', True),
                    (1190, '她在矿上，管着一群男人', 40, 'fg', False),
                    (1330, 'oversee = 统揽、盯着整个摊子', 38, 'green', True)],
             speech=[('zh', '管着一个摊子、一群人的时候，动词用 oversee。'),
                     ('en', 'She was in the mines, overseeing men in the mines.'),
                     ('zh', '，她在矿上，管着矿里的一群男人。oversee 比 manage 更强调'
                            '盯着全局、替结果负责，简历里写 oversee a team of ten 很常见。')],
             source=(933.27, 936.49)),
        dict(n='09', title='keep sb in line',
             lines=[(950, 'she would always say how she', 42, 'green2', True),
                    (1030, 'was keeping them in line', 42, 'green2', True),
                    (1190, '她总说自己把几个哥哥管得服服帖帖', 38, 'fg', False),
                    (1330, 'keep sb in line = 镇得住', 38, 'green', True)],
             speech=[('zh', '讲「镇得住、管得住」，用 keep someone in line。她说奶奶有几个哥哥，'),
                     ('en', 'she would always say how she was keeping them in line'),
                     ('zh', '，她总说自己把几个哥哥管得服服帖帖。line 是一条线，让人不越线；'
                            '团队里也能用，意思接近把节奏和规矩看住。')],
             source=(954.11, 957.45)),
        dict(n='10', title='从来没有过那种感觉',
             lines=[(950, 'So there was never a sense', 42, 'green2', True),
                    (1030, 'of like oppression for her.', 42, 'green2', True),
                    (1190, '她从来没有过那种被压制的感觉', 38, 'fg', False),
                    (1330, 'there was never a sense of …', 38, 'green', True)],
             speech=[('zh', '要讲一种感觉从来没有过，用 '),
                     ('en', 'there was never a sense of …'),
                     ('zh', '。'),
                     ('en', 'So there was never a sense of like oppression for her.'),
                     ('zh', '，她从来没有过那种被压制的感觉。sense of 后面接名词：'
                            'a sense of pressure、a sense of urgency——讲人、讲团队都能用。')],
             source=(958.03, 961.03)),
        dict(n='11', title='先承认事实，再讲她',
             lines=[(950, 'Even if objectively the', 42, 'green2', True),
                    (1030, 'circumstances she grew up in', 42, 'green2', True),
                    (1110, 'were very difficult …', 42, 'green2', True),
                    (1190, '就算客观上，她成长的环境非常难', 38, 'fg', False),
                    (1330, 'Even if objectively …, she still …', 38, 'green', True)],
             speech=[('zh', '要讲一个人不容易，先承认客观事实，再讲她怎么走过来。'),
                     ('en', 'Even if objectively the circumstances she grew up in were very difficult'),
                     ('zh', '，就算客观上，她成长的环境非常难。objectively 一放进去，'
                            '等于告诉对方我不是在替她说话。这句后面接的是她怎么走过来——'
                            '写作、演讲里都是很稳的一段结构。')],
             source=(961.47, 965.41)),
        dict(n='12', title='换你来说',
             lines=[(470, 'Even if objectively she had', 44, 'green2', True),
                    (560, 'every reason to complain,', 44, 'green2', True),
                    (650, 'she never did.', 44, 'green2', True),
                    (870, '就算她有理由抱怨，她一次也没抱怨过', 38, 'fg', False),
                    (1090, '用 Even if objectively … 先让步，再转折', 38, 'mute', False)],
             speech=[('zh', '换你来说一句。'),
                     ('en', 'Even if objectively she had every reason to complain, she never did.'),
                     ('zh', '，就算她有理由抱怨，她一次也没抱怨过。这是我们的原创练习句。'
                            '先用 Even if objectively 让一步，再说 she never did，后半句的力量就出来了。')]),
        # ---- 第 3 章 那时候的她 ----
        dict(n='13', title='拿她跟我比',
             lines=[(950, 'When she was my age, she was', 42, 'green2', True),
                    (1030, 'an electrical engineer at one of', 38, 'green2', True),
                    (1110, 'the largest copper mines in China.', 36, 'green2', True),
                    (1190, '她在我这个年纪，已经是', 38, 'fg', False),
                    (1270, '中国最大铜矿之一的电气工程师', 38, 'fg', False),
                    (1350, 'When she was my age, …', 38, 'green', True)],
             speech=[('zh', '讲一个人的经历，最省力的开头是拿自己当坐标。'),
                     ('en', 'When she was my age, she was an electrical engineer '
                            'at one of the largest copper mines in China.'),
                     ('zh', '，她在我这个年纪，已经是中国最大的铜矿之一的电气工程师。'
                            'one of the largest 加名词复数，「最大的……之一」，讲平台、讲公司也常用。')],
             source=(916.01, 921.93)),
        dict(n='14', title='把两个数字摆在一起',
             lines=[(950, 'At 21, which is crazy.', 46, 'green2', True),
                    (1030, 'I’m 22 now.', 46, 'green2', True),
                    (1190, '21 岁——我现在 22', 40, 'fg', False),
                    (1330, '把两个数字并排，比形容词管用', 38, 'green', True)],
             speech=[('zh', '数字摆在一起，比什么形容词都有劲。'),
                     ('en', 'At 21, which is crazy. I’m 22 now.'),
                     ('zh', '，21 岁，太夸张了，我现在 22。她没说奶奶很了不起，'
                            '只把 21 和 22 并排放着，落差自己就出来了。'
                            '中间那句 which is crazy 是口语里的补一句，写邮件别用，说话时很自然。')],
             source=(922.17, 925.33)),
        dict(n='15', title='讲亲人的离开',
             lines=[(950, 'She lost her mother', 46, 'green2', True),
                    (1030, 'at a very young age.', 46, 'green2', True),
                    (1190, '她很小的时候就失去了母亲', 40, 'fg', False),
                    (1330, 'lose sb at a very young age', 38, 'green', True)],
             speech=[('zh', '要提到亲人离世，英语里最常用的说法是 lose。'),
                     ('en', 'She lost her mother at a very young age.'),
                     ('zh', '，她很小的时候就失去了母亲。用 lose 不用 die，'
                            '语气留了余地，也不刺人。写家族故事、'
                            '或者跟外国同事聊起家里的情况，这个说法都用得上。')],
             source=(965.85, 968.27)),
        dict(n='16', title='一句共情',
             lines=[(950, 'And so losing that kind of', 42, 'green2', True),
                    (1030, 'female force in her life,', 42, 'green2', True),
                    (1110, 'I just can’t even imagine.', 42, 'green2', True),
                    (1190, '失去生活里那个女性力量，我根本不敢想', 38, 'fg', False),
                    (1330, 'I just can’t even imagine.', 38, 'green', True)],
             speech=[('zh', '别人讲了一段难过的经历，怎么接？她说的是 '),
                     ('en', 'I just can’t even imagine.'),
                     ('zh', '，我根本不敢想。这句比 That’s hard 更有温度——'
                            '承认对方的经历超出自己的经验，就是共情。'
                            '听完别人讲困难之后说这句，比急着给建议更合适。')],
             source=(968.51, 972.93)),
        dict(n='17', title='把敬佩说成一句',
             lines=[(950, 'And for that, I will always,', 42, 'green2', True),
                    (1030, 'always admire her.', 44, 'green2', True),
                    (1190, '就因为这一点，我会一直敬佩她', 40, 'fg', False),
                    (1330, 'For that, I will always admire sb.', 38, 'green', True)],
             speech=[('zh', '讲完一个人的故事，收在一句敬佩上。'),
                     ('en', 'And for that, I will always, always admire her.'),
                     ('zh', '，就因为这一点，我会一直、一直敬佩她。'
                            '重复的 always 是最省事的加强方式，说的时候自然会重读。'
                            '致谢、写推荐、给同事做总结，这句都能收尾。')],
             source=(978.65, 981.19)),
        # ---- 第 4 章 影响怎么传下来 ----
        dict(n='18', title='把劲头传下去',
             lines=[(950, 'She definitely passed', 46, 'green2', True),
                    (1030, 'that on to my mom.', 46, 'green2', True),
                    (1190, '她把这一点传给了我妈妈', 40, 'fg', False),
                    (1330, 'pass sth on to sb', 38, 'green', True)],
             speech=[('zh', '讲「传下来」，用 pass something on to someone。'),
                     ('en', 'She definitely passed that on to my mom.'),
                     ('zh', '，她肯定是把这一点传给了我妈妈。that 指的是前面说的那股劲头。'
                            '传经验、传手艺、传习惯都能用：pass on the know-how、'
                            'pass it on to the next team。')],
             source=(982.15, 983.73)),
        dict(n='19', title='给人贴个俏皮标签',
             lines=[(950, 'My mom, I would say, is', 42, 'green2', True),
                    (1030, 'the efficiency queen.', 44, 'green2', True),
                    (1190, '我妈，要我说，是效率女王', 40, 'fg', False),
                    (1330, 'the … queen：用一个人设概括一个人', 38, 'green', True)],
             speech=[('zh', '用一个头衔概括一个人，是个很好用的办法。'),
                     ('en', 'My mom, I would say, is the efficiency queen.'),
                     ('zh', '，我妈，要我说，是效率女王。the 加名词加 queen，'
                            '比如 the spreadsheet queen、the deadline queen，说得俏皮又不刻薄。'
                            '中间的 I would say 是缓冲语，像在给评价，而不是下结论。')],
             source=(984.29, 988.01)),
        dict(n='20', title='职场里很高的评价',
             lines=[(950, 'So she gets things done.', 48, 'green2', True),
                    (1190, '她能把事办成', 42, 'fg', False),
                    (1330, 'get things done', 40, 'green', True)],
             speech=[('zh', '夸同事，这个词比 hardworking 有用得多。'),
                     ('en', 'get things done'),
                     ('zh', '，能把事办成——注意是复数 things 加 done，说的是结果，不是忙。她说：'),
                     ('en', 'So she gets things done.'),
                     ('zh', '，她妈妈不做无用功，走最短的路径、要最高的质量。'
                            '给推荐语、做绩效总结，这句都可以直接用。')],
             source=(988.51, 991.13)),
        dict(n='21', title='借一个圈子里的话',
             lines=[(950, 'In modern speak, in like', 42, 'green2', True),
                    (1030, 'Silicon Valley speak,', 42, 'green2', True),
                    (1110, 'she’s an operator.', 44, 'green2', True),
                    (1190, '用现在的话说，在硅谷的说法里，她是个 operator', 36, 'fg', False),
                    (1330, 'in ___ speak / sb is an operator', 36, 'green', True)],
             speech=[('zh', '要介绍一个圈子里的说法，可以先铺垫一句 '),
                     ('en', 'in … speak'),
                     ('zh', '。'),
                     ('en', 'In modern speak, in Silicon Valley speak, she’s an operator.'),
                     ('zh', '，用现在的话说，在硅谷的说法里，她是个 operator。'
                            'operator 指的是真正落地、能把系统跑起来的人，不是空谈的人。'
                            'in marketing speak、in engineer speak 都能这么套。')],
             source=(991.13, 994.85)),
        dict(n='22', title='换你来说',
             lines=[(470, 'She gets things done, and', 44, 'green2', True),
                    (560, 'she passes that on — my', 44, 'green2', True),
                    (650, 'whole team works that way.', 44, 'green2', True),
                    (870, '她能成事，也把这一点传下去，团队都是这个风格', 34, 'fg', False),
                    (1090, 'get things done / pass sth on 连起来说', 36, 'mute', False)],
             speech=[('zh', '换你来说一句。'),
                     ('en', 'She gets things done, and she passes that on — '
                            'my whole team works that way.'),
                     ('zh', '，她能成事，也把这一点传下去，我们整个团队都是这个风格。'
                            '这是我们的原创练习句。把 get things done 和 pass something on '
                            '连起来，就是一段完整的评价。')]),
        # ---- 第 5 章 收尾 ----
        dict(n='23', title='带着这些点，再听一遍',
             lines=[(950, '现在再完整听一遍', 50, 'fg', False),
                    (1040, '你应该能听出更多东西了', 52, 'green', False),
                    (1210, '2 分 03 秒，20 个地道表达', 44, 'mute', False)],
             speech=[('zh', '现在带着刚才拆过的这些点，再完整听一遍这 2 分 03 秒。'
                            '这一次，你会听出她是怎么用一句话把奶奶说清楚的，也会听出那句 '),
                     ('en', 'Not once'),
                     ('zh', ' 为什么说得那么重。')],
             source=(875.71, 998.42)),
        dict(n='24', title='跟着读三遍',
             lines=[(470, '1. If I were to distill it,', 44, 'green2', True),
                    (545, 'I would say she was the dreamer.', 42, 'green2', True),
                    (670, '2. Not once has she ever', 44, 'green2', True),
                    (740, 'had a victim mentality.', 44, 'green2', True),
                    (865, '3. She gets things done.', 44, 'green2', True)],
             speech=[('zh', '最后挑三句最常用的，跟着读一遍。'),
                     ('en', 'If I were to distill it, I would say she was the dreamer.'),
                     ('en', 'Not once has she ever had a victim mentality.'),
                     ('en', 'She gets things done.'),
                     ('zh', '不用追求完美，先把它说出口。')],
             tail=3.1),
        dict(n='25', title='收藏，下次讲家人的时候过一遍',
             lines=[(480, '拾句英语', 100, 'green', False),
                    (650, '两分钟，学会把人讲清楚', 42, 'fg', False),
                    (850, '提炼   If I were to distill it, I would say …', 32, 'green2', False),
                    (925, '强调   Not once has she ever …', 34, 'green2', False),
                    (1000, '传承   pass sth on to sb', 36, 'green2', False),
                    (1200, '听懂一句，再把它说出来', 40, 'mute', False)],
             speech=[('zh', '这一期讲的是怎么把一个人讲清楚：先用一句话提炼出她是谁，'
                            '再用倒装把话说重，最后讲这份劲头怎么传下来。'),
                     ('zh', '先收藏，下次要讲家里人的时候，把这三句过一遍。'
                            '拾句英语，听懂一句，再把它说出来。')]),
    ],
)


# ---- 08 努力 vs 方向（原片 998.42–1249.60，251.18 秒）----
# 与 07 章的边界：07 收在 `okay, how?`（16:38.31），本条从 16:38.42 接，
# 起点第一句是完整的 `She will not do unnecessary suffering.`，不含半句。
# 2026-09 新片规格全用默认：v2 深色 + 宋体 + eleven_v3 + style 0.4 + 1.2 倍速 + 无页脚。
# 口吻新规：练习句用邀请式（「你也可以试着这样说」），不再写「这是我们的原创练习句」。
SPECS['谷爱凌_努力vs方向'] = dict(
    src='__DATA_ROOT__/小红书发帖-拾句英语/谷爱凌/谷爱凌最新全英访谈.mp4',
    cards=[
        # ---- 第 0 章 钩子 + 完整听一遍（251 秒，拆上中下三张）----
        dict(n='01', title='努力和方向，哪个更重要？',
             lines=[(770, '跟着 4 分钟访谈学表达', 46, 'green', False),
                    (920, '方向 · 焦虑 · 判断', 40, 'fg', False),
                    (1000, '27 个表达，就藏在 4 分 11 秒里', 34, 'mute', False)],
             speech=[('zh', '你有没有过这种感觉：每天都很忙，却总觉得自己落后了？'),
                     ('zh', '谷爱凌在这段 4 分 11 秒里把这件事说透了。她先讲家里两位长辈各给了她什么——'
                            '奶奶定方向，妈妈给工具；再解释为什么越努力越焦虑；最后落到一句判断：'),
                     ('en', 'hard work, super important, but overpraised, direction underrated.'),
                     ('zh', '我们先完整听一遍，再一句一句拆。')]),
        dict(n='02', title='先听前 82 秒',
             lines=[(950, 'my grandma will set the stage', 42, 'green2', True),
                    (1030, 'and set the direction', 42, 'green2', True),
                    (1190, '先听前 82 秒', 42, 'fg', False),
                    (1330, '这一段讲「两个人各给了我什么」', 38, 'mute', False)],
             speech=[('zh', '先听前 82 秒。她讲妈妈做事的方式，也讲奶奶和妈妈各给了她什么。')],
             source=(998.42, 1080.70)),
        dict(n='03', title='再听 80 秒',
             lines=[(950, 'the faster you run,', 44, 'green2', True),
                    (1030, 'the faster it moves', 44, 'green2', True),
                    (1190, '再听 80 秒', 42, 'fg', False),
                    (1330, '这一段解释「为什么越跑越累」', 38, 'mute', False)],
             speech=[('zh', '再听 80 秒。主持人问「那些觉得自己落后的人，你会对他们说什么」，'
                            '她先承认自己也是这样，然后讲了一个心理学概念。')],
             source=(1080.70, 1161.05)),
        dict(n='04', title='最后 88 秒',
             lines=[(950, 'hard work, super important,', 40, 'green2', True),
                    (1030, 'but overpraised,', 40, 'green2', True),
                    (1110, 'direction underrated', 40, 'green2', True),
                    (1190, '最后 88 秒', 42, 'fg', False),
                    (1330, '听完这一遍，我们就开始拆', 38, 'mute', False)],
             speech=[('zh', '最后 88 秒。她讲了努力和方向的关系，也讲了自己夜里都在焦虑什么。'
                            '听完这一遍，我们就开始拆。')],
             source=(1161.05, 1249.60)),
        # ---- 第 1 章 一个给方向，一个给工具 ----
        dict(n='05', title='for the sake of：为了……而……',
             lines=[(950, 'She will not work', 46, 'green2', True),
                    (1030, 'for the sake of working.', 46, 'green2', True),
                    (1190, '她不会为了工作而工作', 40, 'fg', False),
                    (1330, 'for the sake of sth', 38, 'green', True)],
             speech=[('zh', '先记一个短语。'),
                     ('en', 'for the sake of something'),
                     ('zh', '，为了……而……，重点在「就为了这件事本身」。她说妈妈不会 '),
                     ('en', 'work for the sake of working'),
                     ('zh', '，不会为了忙而忙。后面接名词或动名词，比 because of 更强调目的。')],
             source=(1001.05, 1003.05)),
        dict(n='06', title='夸做事，两个词就够',
             lines=[(950, 'with high quality and', 42, 'green2', True),
                    (1030, 'uncompromising results', 42, 'green2', True),
                    (1110, 'and attention to detail.', 42, 'green2', True),
                    (1190, '高质量、不打折扣，还盯着细节', 38, 'fg', False),
                    (1330, 'uncompromising / attention to detail', 36, 'green', True)],
             speech=[('zh', '夸做事，两个词就够。uncompromising 是不打折扣、不让步；'
                            'attention to detail 是盯细节。她说妈妈做事 '),
                     ('en', 'with high quality and uncompromising results and attention to detail'),
                     ('zh', '，质量高、结果不打折扣、细节也不放过。'
                            '写推荐语、做自评，这两个词比「认真负责」具体得多。')],
             source=(1007.97, 1012.10)),
        dict(n='07', title='给一个人贴行为标签',
             lines=[(950, 'but she is not the one', 42, 'green2', True),
                    (1030, 'who’s going to stay up', 42, 'green2', True),
                    (1110, 'late all night to do it.', 42, 'green2', True),
                    (1190, '她不是那种会熬夜硬扛的人', 38, 'fg', False),
                    (1330, 'sb is not the one who …', 38, 'green', True)],
             speech=[('zh', '要给一个人贴行为标签，用 '),
                     ('en', 'not the one who …'),
                     ('zh', '。她说 '),
                     ('en', 'but she is not the one who’s going to stay up late all night to do it'),
                     ('zh', '，她不是那种会熬夜硬扛的人。前面说的是她要求高，'
                            '这句补的是她不拼时长——两句一正一反，人就说清楚了。')],
             source=(1015.03, 1018.75)),
        dict(n='08', title='set the stage：搭台、定调',
             lines=[(950, 'my grandma will set', 42, 'green2', True),
                    (1030, 'the stage and set', 42, 'green2', True),
                    (1110, 'the direction.', 42, 'green2', True),
                    (1190, '奶奶负责搭台、定方向', 38, 'fg', False),
                    (1330, 'set the stage / set the direction', 36, 'green', True)],
             speech=[('zh', '讲一段影响的来源，可以分成「搭台」和「定调」。'),
                     ('en', 'set the stage'),
                     ('zh', '本来是戏剧里的搭台，引申为把条件铺好；'),
                     ('en', 'set the direction'),
                     ('zh', ' 是定方向。她说 '),
                     ('en', 'my grandma will set the stage and set the direction'),
                     ('zh', '，我奶奶把台子搭起来、把方向定下来。')],
             source=(1023.33, 1026.25)),
        dict(n='09', title='if you will：自造比喻后标注一下',
             lines=[(950, 'my mom gave me kind', 42, 'green2', True),
                    (1030, 'of the toolkit, if you will,', 42, 'green2', True),
                    (1190, '妈妈给我的是工具箱——可以说', 38, 'fg', False),
                    (1330, '… , if you will,', 38, 'green', True)],
             speech=[('zh', '自己造了个比喻，怕对方觉得突兀，就补一句 '),
                     ('en', 'if you will'),
                     ('zh', '，可以说是、姑且这么说。她说 '),
                     ('en', 'and my mom gave me kind of the toolkit, if you will'),
                     ('zh', '，我妈妈给我的是工具箱，可以说是工具箱。写作用它来自我标注，比打引号自然。')],
             source=(1026.35, 1029.90)),
        dict(n='10', title='换你来说',
             lines=[(470, 'My grandma set the direction,', 42, 'green2', True),
                    (560, 'and my dad gave me the', 42, 'green2', True),
                    (650, 'toolkit — that’s how I got here.', 42, 'green2', True),
                    (870, '你可以试着这样说', 38, 'fg', False),
                    (1090, '把这两样换成真正影响你的那两个人', 36, 'mute', False)],
             speech=[('zh', '你也可以试着这样说。'),
                     ('en', 'My grandma set the direction, and my dad gave me the toolkit '
                            '— that’s how I got here.'),
                     ('zh', '，我奶奶定方向，我爸给我工具，我就是这么走到今天的。'
                            '把这两个位置，换成真正影响你的那两个人。')]),
        # ---- 第 2 章 主持人这三句，先记下来 ----
        dict(n='11', title='The fact that：写作最实用的结构之一',
             lines=[(950, 'The fact that she was doing', 40, 'green2', True),
                    (1030, 'that at 21 in her generation', 40, 'green2', True),
                    (1110, 'in China is unbelievable.', 40, 'green2', True),
                    (1190, '她那个年代在中国，21 岁做这件事，难以置信', 36, 'fg', False),
                    (1330, 'The fact that … is unbelievable.', 36, 'green', True)],
             speech=[('zh', 'The fact that 后面直接跟一个完整句子，整块当主语——写作里最实用的结构之一。'
                            '主持人说 '),
                     ('en', 'The fact that she was doing that at 21 in her generation in China '
                            'is unbelievable.'),
                     ('zh', '，她那个年代在中国、21 岁就做这件事，这太难以置信了。'
                            '写邮件、写发言稿，想强调一个事实，用这个开头最稳。')],
             source=(1049.77, 1055.10)),
        dict(n='12', title='两句说清「我很焦虑」',
             lines=[(950, 'I feel behind.', 50, 'green2', True),
                    (1030, 'I feel stuck.', 50, 'green2', True),
                    (1190, '我觉得自己落后了，卡住了', 40, 'fg', False),
                    (1330, 'I feel behind. / I feel stuck.', 38, 'green', True)],
             speech=[('zh', '两句就把焦虑说清楚。'),
                     ('en', 'I feel behind'),
                     ('zh', ' 是「我觉得自己落后了」，'),
                     ('en', 'I feel stuck'),
                     ('zh', ' 是「我卡住了」。主持人是替观众问的：他们要跟谷爱凌说 '),
                     ('en', 'I feel behind. I feel stuck.'),
                     ('zh', ' 这两句短，写邮件开场、跟人聊职业状态时都好用。')],
             source=(1068.49, 1070.95)),
        dict(n='13', title='把话筒递回去',
             lines=[(950, 'What would you say', 46, 'green2', True),
                    (1030, 'to them?', 46, 'green2', True),
                    (1190, '你会对他们说什么？', 40, 'fg', False),
                    (1330, 'What would you say to sb?', 38, 'green', True)],
             speech=[('zh', '把话筒递回去的一句话。'),
                     ('en', 'What would you say to them?'),
                     ('zh', '，你会对他们说什么？访谈、分享会、直播里想请人给建议，这句最省事；'
                            '主语换成 to someone starting out，就能用在自己的场合。')],
             source=(1076.77, 1077.75)),
        # ---- 第 3 章 为什么越跑越累 ----
        dict(n='14', title='hedonic treadmill：享乐跑步机',
             lines=[(950, 'A, hedonic treadmill', 44, 'green2', True),
                    (1030, 'theory, generally', 44, 'green2', True),
                    (1110, 'speaking, right?', 44, 'green2', True),
                    (1190, '享乐跑步机理论', 40, 'fg', False),
                    (1330, 'hedonic treadmill', 38, 'green', True)],
             speech=[('zh', '她先给了一个概念：'),
                     ('en', 'hedonic treadmill theory'),
                     ('zh', '，享乐跑步机理论。意思是人会在原地跑——过得越好，标准跟着涨，快乐却没多。'
                            '谈到「为什么日子变好了还是不满足」，这个词能一句话说清。')],
             source=(1083.11, 1086.25)),
        dict(n='15', title='the idea being：也就是说',
             lines=[(950, 'the idea being you acclimate', 40, 'green2', True),
                    (1030, 'so quickly to your circumstances', 38, 'green2', True),
                    (1110, 'that it’s no longer objective.', 38, 'green2', True),
                    (1190, '也就是说，你很快就适应了现状，快到你不再客观', 34, 'fg', False),
                    (1330, 'the idea being … / acclimate to', 36, 'green', True)],
             speech=[('zh', '要解释一个概念，用 '),
                     ('en', 'the idea being'),
                     ('zh', ' 起头，也就是说……。'),
                     ('en', 'acclimate to'),
                     ('zh', ' 是适应新环境。她说 '),
                     ('en', 'the idea being you acclimate so quickly to your circumstances '
                            'that it’s no longer objective'),
                     ('zh', '，也就是说，你适应得太快，快到眼前的一切不再客观。'
                            'so … that … 把因果串在一起。')],
             source=(1086.27, 1092.75)),
        dict(n='16', title='越跑越快，标准也跟着跑',
             lines=[(950, 'It’s the faster you run,', 44, 'green2', True),
                    (1030, 'the faster it moves.', 44, 'green2', True),
                    (1190, '你跑得越快，它跟着越快', 40, 'fg', False),
                    (1330, 'the + 比较级 …, the + 比较级 …', 36, 'green', True)],
             speech=[('zh', 'the 加比较级，再加 the 加比较级，越……就越……。她说 '),
                     ('en', 'It’s the faster you run, the faster it moves and you just keep '
                            'going and going and going.'),
                     ('zh', '，你跑得越快，它跟着越快，你就只能一直跑下去。'
                            '写总结、讲规律，这个句式一比就立住了。')],
             source=(1096.17, 1099.95)),
        dict(n='17', title='peer group：同龄人这个圈',
             lines=[(950, 'you can feel exactly', 42, 'green2', True),
                    (1030, 'the same as anybody', 42, 'green2', True),
                    (1110, 'in your peer group', 42, 'green2', True),
                    (1190, '你可以跟你圈子里的人一样焦虑', 38, 'fg', False),
                    (1330, 'peer group', 38, 'green', True)],
             speech=[('zh', 'peer group 是同龄人、同层次的那个圈子。她说 '),
                     ('en', 'you can feel exactly the same as anybody in your peer group'),
                     ('zh', '，你可以和你圈子里的人一样焦虑——同事升职、同学买房，'
                            '焦虑从来不看绝对值。')],
             source=(1102.01, 1105.65)),
        dict(n='18', title='irrespective of：无论……',
             lines=[(950, 'irrespective of these', 42, 'green2', True),
                    (1030, 'objective goals', 42, 'green2', True),
                    (1110, 'and achievements.', 42, 'green2', True),
                    (1190, '不管那些客观的目标和成绩', 38, 'fg', False),
                    (1330, 'irrespective of sth', 38, 'green', True)],
             speech=[('zh', 'irrespective of 是「无论、不管」，比 regardless of 更书面。她说 '),
                     ('en', 'irrespective of these kind of like objective goals and achievements'),
                     ('zh', '，不管你达成了多少客观目标。用在句子里就是把「例外」先摘掉：'),
                     ('en', 'irrespective of the outcome'),
                     ('zh', '，不管结果怎样。')],
             source=(1105.73, 1109.10)),
        dict(n='19', title='换你来说',
             lines=[(470, 'I hit every goal this year', 44, 'green2', True),
                    (560, 'and still feel behind —', 44, 'green2', True),
                    (650, 'that’s the treadmill.', 44, 'green2', True),
                    (870, '你可以试着这样说', 38, 'fg', False),
                    (1090, '把 still feel behind 换成你真实的感受', 36, 'mute', False)],
             speech=[('zh', '你也可以试着这样说。'),
                     ('en', 'I hit every goal this year and still feel behind '
                            '— that’s the treadmill.'),
                     ('zh', '，今年的目标我都完成了，还是觉得自己落后——这就是那台跑步机。'
                            '把 still feel behind 换成你真实的感受。')]),
        # ---- 第 4 章 那股绷着的劲，其实是能量 ----
        dict(n='20', title='activation energy：活化能',
             lines=[(950, 'I almost think of that', 42, 'green2', True),
                    (1030, 'as activation energy.', 42, 'green2', True),
                    (1190, '我几乎把它当成一种活化能', 40, 'fg', False),
                    (1330, 'think of A as B', 38, 'green', True)],
             speech=[('zh', '定义一个东西，用 '),
                     ('en', 'think of A as B'),
                     ('zh', '，把 A 看成 B。她说 '),
                     ('en', 'I almost think of that as activation energy'),
                     ('zh', '，我几乎把那种不安当成活化能——化学里，反应开始前必须先给的那份能量。'
                            '这个说法把「焦虑」换了个名字，听着就没那么糟。')],
             source=(1120.13, 1122.70)),
        dict(n='21', title='拨开情绪，直指本质',
             lines=[(950, 'the fact of the matter is', 42, 'green2', True),
                    (1030, 'it’s energy that doesn’t', 42, 'green2', True),
                    (1110, 'know where to go.', 42, 'green2', True),
                    (1190, '事实是，它是不知道该往哪去的能量', 36, 'fg', False),
                    (1330, 'The fact of the matter is …', 36, 'green', True)],
             speech=[('zh', '拨开情绪、直指本质，用 '),
                     ('en', 'the fact of the matter is …'),
                     ('zh', '，事实是……。她说 '),
                     ('en', 'the fact of the matter is it’s energy that doesn’t know where to go'),
                     ('zh', '，它只是不知道该往哪去的能量。会议里跑题了、讨论陷进情绪了，'
                            '这句能把话拉回重点。')],
             source=(1141.31, 1143.40)),
        dict(n='22', title='It’s more about …：把重点挪一下',
             lines=[(950, 'It’s more about redirecting it', 40, 'green2', True),
                    (1030, 'instead of like sitting', 40, 'green2', True),
                    (1110, 'with this golf ball', 40, 'green2', True),
                    (1190, '重点不是憋着它，而是把它引开', 38, 'fg', False),
                    (1330, 'It’s more about A instead of B.', 36, 'green', True)],
             speech=[('zh', '要委婉地把重点挪一下，用 '),
                     ('en', 'It’s more about A instead of B'),
                     ('zh', '。她说 '),
                     ('en', 'It’s more about redirecting it instead of like sitting with this '
                            'golf ball'),
                     ('zh', '，重点不是把那股劲憋在胸口，而是把它引开。'
                            'golf ball 是她自己加的比喻，接着说 or butterfly，随你怎么想。')],
             source=(1145.55, 1149.85)),
        dict(n='23', title='self-work：自己先想清楚',
             lines=[(950, 'It’s more about doing', 42, 'green2', True),
                    (1030, 'the self-work to know', 42, 'green2', True),
                    (1110, 'where that energy goes.', 42, 'green2', True),
                    (1190, '先做自己的功课，想清楚这股劲该去哪', 36, 'fg', False),
                    (1330, 'do the self-work', 38, 'green', True)],
             speech=[('zh', 'the self-work 是自己下的功夫——不是做事，是想清楚自己。她说 '),
                     ('en', 'It’s more about doing the self-work to know where that energy goes'),
                     ('zh', '，重点是先把自己的功课做了，想清楚那股劲该往哪去。'
                            '跟人聊职业选择时，这个词比 think about it 更实。')],
             source=(1154.27, 1157.10)),
        # ---- 第 5 章 努力 vs 方向 ----
        dict(n='24', title='反射式倾听：先复述，再回应',
             lines=[(950, 'what I’m hearing', 44, 'green2', True),
                    (1030, 'you say is …', 44, 'green2', True),
                    (1190, '我听下来你的意思是……', 40, 'fg', False),
                    (1330, 'What I’m hearing you say is …', 36, 'green', True)],
             speech=[('zh', '主持人这一句是反射式倾听。'),
                     ('en', 'What I’m hearing you say is …'),
                     ('zh', '，我听下来你的意思是……，先把对方的话复述一遍，再给回应。他说 '),
                     ('en', 'What I’m hearing you say is: if you channel it, if you redirect it, '
                            'then that’s going to propel you.'),
                     ('zh', ' 开会、谈判里用这个开头，对方会更愿意听你后面的话。')],
             source=(1167.09, 1173.35)),
        dict(n='25', title='much 加在比较级前',
             lines=[(950, 'knowing what direction', 42, 'green2', True),
                    (1030, 'to take is so much', 42, 'green2', True),
                    (1110, 'harder than people think.', 42, 'green2', True),
                    (1190, '知道往哪走，比人们想的难得多', 38, 'fg', False),
                    (1330, 'so much harder than …', 38, 'green', True)],
             speech=[('zh', 'much 加在比较级前面表示程度：'),
                     ('en', 'so much harder than people think'),
                     ('zh', '，比人们想的难得多。她说 '),
                     ('en', 'But knowing what direction to take is so much harder than people think.'),
                     ('zh', '，知道该往哪走这件事，比人们想的难得多。'
                            '同类的还有 a lot easier than expected。')],
             source=(1175.97, 1180.65)),
        dict(n='26', title='一句话把判断说清',
             lines=[(950, 'hard work, super important,', 42, 'green2', True),
                    (1030, 'but overpraised,', 42, 'green2', True),
                    (1110, 'direction underrated.', 42, 'green2', True),
                    (1190, '努力很重要，但被高估了；方向被低估了', 34, 'fg', False),
                    (1330, 'A is overpraised; B is underrated.', 36, 'green', True)],
             speech=[('zh', '一句话把判断说清：努力被高估，方向被低估。'),
                     ('en', 'overpraised'),
                     ('zh', ' 是被夸过头，'),
                     ('en', 'underrated'),
                     ('zh', ' 是被低估。她说 '),
                     ('en', 'hard work, super important, but overpraised, direction underrated'),
                     ('zh', '，先给努力留了面子，再翻转判断。写观点、做复盘，'
                            '这个对子比「都很重要」有力。')],
             source=(1183.63, 1190.00)),
        dict(n='27', title='一个比喻：对着墙使劲',
             lines=[(950, 'if you’re punching a wall,', 42, 'green2', True),
                    (1030, 'who’s punching the', 42, 'green2', True),
                    (1110, 'wall the hardest?', 42, 'green2', True),
                    (1190, '都在捶墙的时候，谁捶得最狠没有意义', 34, 'fg', False),
                    (1330, 'punch a wall / walk around a column', 34, 'green', True)],
             speech=[('zh', '她用了一个很直白的比喻。'),
                     ('en', 'But if you’re punching a wall, who’s punching the wall the hardest?'),
                     ('zh', '，都在捶同一堵墙的时候，谁捶得最狠没有意义。后面那句更妙：'),
                     ('en', 'If you can walk around a column, maybe it’s easier than punching '
                            'the wall.'),
                     ('zh', '，能绕开柱子就绕开，比硬捶省事。')],
             source=(1194.57, 1198.40)),
        dict(n='28', title='先否定，再立论',
             lines=[(950, 'It’s not necessarily about', 40, 'green2', True),
                    (1030, 'doing the most. What’s more', 40, 'green2', True),
                    (1110, 'important is the direction.', 40, 'green2', True),
                    (1190, '不是做得多，方向才更重要', 38, 'fg', False),
                    (1330, 'It’s not about A. What’s more important is B.', 32, 'green', True)],
             speech=[('zh', '先否定，再立论，两步走完：'),
                     ('en', 'It’s not necessarily about doing the most. What’s more important '
                            'is the direction.'),
                     ('zh', '，重点不是做得最多，更重要的是方向。not necessarily 留了余地，'
                            '不会把人一棍子打死；What’s more important is 把结论托住。'
                            '汇报、发言的收尾都能用。')],
             source=(1203.71, 1208.45)),
        dict(n='29', title='worth：这个时间花得值',
             lines=[(950, 'that’s worth the time', 44, 'green2', True),
                    (1030, 'that it takes to explore.', 42, 'green2', True),
                    (1190, '花时间去探索，是值得的', 40, 'fg', False),
                    (1330, 'It’s worth the time that it takes to …', 34, 'green', True)],
             speech=[('zh', '讲「这时间花得值」，用 '),
                     ('en', 'be worth the time that it takes to do'),
                     ('zh', '。她说 '),
                     ('en', 'And that’s worth the time that it takes to explore.'),
                     ('zh', '，花在探索上的时间是值得的。前面她刚说，'
                            '年轻人更该做的是拿时间把方向想清楚——这句就是收尾。')],
             source=(1216.67, 1219.30)),
        dict(n='30', title='live up to your potential',
             lines=[(950, 'I feel like I’m not', 44, 'green2', True),
                    (1030, 'living up to my potential.', 42, 'green2', True),
                    (1190, '我觉得自己没发挥出该有的样子', 38, 'fg', False),
                    (1330, 'live up to one’s potential', 38, 'green', True)],
             speech=[('zh', 'live up to your potential，发挥出你该有的水平。她说 '),
                     ('en', 'I feel like I’m not living up to my potential.'),
                     ('zh', '，我觉得自己没发挥出该有的样子。这句在职场里出现频率极高——'
                            '绩效面谈、离职信、跟人聊焦虑都用得上。'
                            'live up to 后面还可以接 expectations。')],
             source=(1230.51, 1232.35)),
        dict(n='31', title='换你来说',
             lines=[(470, 'I don’t know what direction', 42, 'green2', True),
                    (560, 'to take yet, and that’s', 42, 'green2', True),
                    (650, 'worth the time it takes.', 42, 'green2', True),
                    (870, '你可以试着这样说', 38, 'fg', False),
                    (1090, '把 direction 换成你真正在想的那件事', 36, 'mute', False)],
             speech=[('zh', '你也可以试着这样说。'),
                     ('en', 'I don’t know what direction to take yet, and that’s worth '
                            'the time it takes.'),
                     ('zh', '，我还没想清楚往哪个方向走，但这个时间值得花。'
                            '把 direction 换成你真正在想的那件事。')]),
        # ---- 第 6 章 收尾 ----
        dict(n='32', title='带着这些点，再听一遍',
             lines=[(950, '现在再完整听一遍', 50, 'fg', False),
                    (1040, '你应该能听出更多东西了', 52, 'green', False),
                    (1210, '4 分 11 秒，27 个地道表达', 44, 'mute', False)],
             speech=[('zh', '现在带着刚才拆过的这些点，再完整听一遍这 4 分 11 秒。'
                            '这一次，你会听清她怎么把「焦虑」讲成「能量」，也会听清那句 '),
                     ('en', 'hard work overpraised, direction underrated'),
                     ('zh', ' 是怎么落下来的。')],
             source=(998.42, 1249.60)),
        dict(n='33', title='跟着读三遍',
             lines=[(470, '1. The faster you run,', 44, 'green2', True),
                    (545, 'the faster it moves.', 44, 'green2', True),
                    (670, '2. The fact of the matter is', 42, 'green2', True),
                    (740, 'it’s energy that doesn’t know where to go.', 36, 'green2', True),
                    (865, '3. I’m not living up to my potential.', 42, 'green2', True)],
             speech=[('zh', '最后挑三句最常用的，跟着读一遍。'),
                     ('en', 'The faster you run, the faster it moves.'),
                     ('en', 'The fact of the matter is it’s energy that doesn’t know where to go.'),
                     ('en', 'I’m not living up to my potential.'),
                     ('zh', '不用追求完美，先把它说出口。')],
             tail=3.1),
        dict(n='34', title='收藏，下次焦虑的时候过一遍',
             lines=[(480, '拾句英语', 100, 'green', False),
                    (650, '四分钟，想清楚努力和方向', 42, 'fg', False),
                    (850, '焦虑   I feel behind. I feel stuck.', 34, 'green2', False),
                    (925, '本质   the fact of the matter is …', 32, 'green2', False),
                    (1000, '判断   overpraised / underrated', 36, 'green2', False),
                    (1200, '听懂一句，再把它说出来', 40, 'mute', False)],
             speech=[('zh', '这一期讲的是努力和方向：怎么把「我很焦虑」说清楚，'
                            '怎么拨开情绪看本质，怎么用一句话把判断说出来。'),
                     ('zh', '先收藏，下次觉得落后的时候，把这三句过一遍。'
                            '拾句英语，听懂一句，再把它说出来。')]),
    ],
)


# ---- 09 怎么选方向（原片 1249.60–1588.00，338.40 秒）----
# 与 08 章的边界：08 收在「shared sentiment for everybody.」（20:49），本条从 20:49 接。
# 2026-09 新片规格全用默认：v2 深色 + 宋体 + eleven_v3 + style 0.4 + 1.2 倍速 + 无页脚。
# 口吻：练习句用邀请式（「你也可以试着这样说」）。
SPECS['谷爱凌_怎么选方向'] = dict(
    src='__DATA_ROOT__/小红书发帖-拾句英语/谷爱凌/谷爱凌最新全英访谈.mp4',
    cards=[
        # ---- 第 0 章 钩子 + 完整听一遍（338 秒，拆四张）----
        dict(n='01', title='离开学校以后，标准去哪了？',
             lines=[(770, '跟着 5 分钟访谈学表达', 46, 'green', False),
                    (920, '指标 · 方向 · 价值观', 40, 'fg', False),
                    (1000, '22 个表达，就藏在 5 分 38 秒里', 34, 'mute', False)],
             speech=[('zh', '上学的时候，你很清楚什么叫「好」：考到 90 分、拿 A、排进前几名。'),
                     ('zh', '可一离开学校，评分系统就没了——'),
                     ('en', 'it’s all up to you.'),
                     ('zh', '谷爱凌在这段 5 分 38 秒里，讲了怎么在没有标准答案的地方给自己定标准：'
                            '先用价值观当筛子，再承认自己也不知道，只能多试。'),
                     ('zh', '我们先完整听一遍，再一句一句拆。')]),
        dict(n='02', title='先听前 94 秒',
             lines=[(950, 'it’s a generational thing', 42, 'green2', True),
                    (1030, 'and it’s an age thing', 42, 'green2', True),
                    (1190, '先听前 94 秒', 42, 'fg', False),
                    (1330, '这一段讲「毕业后的落差」', 38, 'mute', False)],
             speech=[('zh', '先听前 94 秒。主持人先说了毕业之后最大的落差：'
                            '以前的人生是排好的，现在要自己定。')],
             source=(1249.60, 1343.55)),
        dict(n='03', title='再听 105 秒',
             lines=[(950, 'You can push a rock up a hill', 40, 'green2', True),
                    (1030, 'as hard as you want …', 40, 'green2', True),
                    (1190, '再听 105 秒', 42, 'fg', False),
                    (1330, '这一段讲「方向比努力重要」', 38, 'mute', False)],
             speech=[('zh', '再听 105 秒。这一段里她讲了两种完全不同的生活形态，'
                            '还有一句关于方向的话，主持人当场说「这是世界级的」。')],
             source=(1343.83, 1449.45)),
        dict(n='04', title='再听 72 秒',
             lines=[(950, 'I need to take the time', 42, 'green2', True),
                    (1030, 'to learn, I need to take', 42, 'green2', True),
                    (1110, 'the time to fail.', 42, 'green2', True),
                    (1190, '再听 72 秒', 42, 'fg', False),
                    (1330, '这一段讲「她怎么给自己定边界」', 38, 'mute', False)],
             speech=[('zh', '再听 72 秒。她讲了自己怎么筛机会：先有价值观，再有边界。')],
             source=(1449.60, 1522.11)),
        dict(n='05', title='最后 65 秒',
             lines=[(950, 'just by virtue of how many', 40, 'green2', True),
                    (1030, 'times you flip the coin', 40, 'green2', True),
                    (1190, '最后 65 秒', 42, 'fg', False),
                    (1330, '听完这一遍，我们就开始拆', 38, 'mute', False)],
             speech=[('zh', '最后 65 秒。她说了自己也没想清楚，还讲了一个抛硬币的道理。'
                            '听完这一遍，我们就开始拆。')],
             source=(1522.57, 1588.00)),
        # ---- 第 1 章 离开学校，指标就没了 ----
        dict(n='06', title='map out：把人生排好',
             lines=[(950, 'most of your life', 46, 'green2', True),
                    (1030, 'is mapped out for you.', 46, 'green2', True),
                    (1190, '你人生的一大半，早就被人排好了', 38, 'fg', False),
                    (1330, 'be mapped out for sb', 38, 'green', True)],
             speech=[('zh', '主持人先给了个说法：'),
                     ('en', 'most of your life is mapped out for you'),
                     ('zh', '，你人生的一大半，早就被人排好了——七年级升八年级、上大学、拿学位。'
                            'map out 是「规划、排布」，也可以说 map out a career path。')],
             source=(1257.97, 1259.95)),
        dict(n='07', title='choices that don’t have a timeline',
             lines=[(950, 'you actually have to make', 42, 'green2', True),
                    (1030, 'choices that don’t', 42, 'green2', True),
                    (1110, 'have a timeline.', 42, 'green2', True),
                    (1190, '要做的决定，突然没有时间表了', 38, 'fg', False),
                    (1330, 'choices that don’t have a timeline', 34, 'green', True)],
             speech=[('zh', '毕业后最难适应的一件事：'),
                     ('en', 'you actually have to make choices that don’t have a timeline'),
                     ('zh', '，你要做的决定，突然没有截止日期了。考试有日期、毕业有日期，'
                            '而「要不要换城市、要不要转行」都没有。')],
             source=(1265.55, 1267.75)),
        dict(n='08', title='metrics：学校里的指标',
             lines=[(950, 'the metrics of success', 44, 'green2', True),
                    (1030, 'are there. You have a rubric.', 40, 'green2', True),
                    (1190, '成功的指标摆在那儿，还有评分表', 38, 'fg', False),
                    (1330, 'the metrics of success / a rubric', 36, 'green', True)],
             speech=[('zh', '她接着主持人的话说：在学校，'),
                     ('en', 'the metrics of success are there. You have a rubric.'),
                     ('zh', '，成功的指标摆在那儿，你还有一张评分表。metric 是指标，'
                            'rubric 是评分表——这两个词换到工作里，就是 KPI 和考核标准。')],
             source=(1275.15, 1277.75)),
        dict(n='09', title='成功，对每个人都不一样',
             lines=[(950, 'success looks so different', 42, 'green2', True),
                    (1030, 'for so many', 42, 'green2', True),
                    (1110, 'different people.', 42, 'green2', True),
                    (1190, '成功对不同的人，样子差得太远', 38, 'fg', False),
                    (1330, 'sth looks different for sb', 38, 'green', True)],
             speech=[('zh', '接着她把「标准」这件事拆开了：'),
                     ('en', 'success looks so different for so many different people'),
                     ('zh', '，成功对不同的人，样子差得太远。她说有人很有钱却很不快乐，'
                            '同样处境的人，一个觉得自己很失败，另一个觉得自己很成功。')],
             source=(1287.55, 1289.99)),
        dict(n='10', title='it’s all up to you',
             lines=[(950, 'there is no grading system —', 40, 'green2', True),
                    (1030, 'because now it’s all up to you.', 40, 'green2', True),
                    (1190, '没有评分系统了，全都看你自己', 38, 'fg', False),
                    (1330, 'as soon as … / it’s all up to you', 36, 'green', True)],
             speech=[('zh', '主持人把这件事说到底：'),
                     ('en', 'as soon as you leave, there is no grading system — '
                            'because now it’s all up to you'),
                     ('zh', '，一离开学校就没有评分系统了，因为现在全看你自己。'
                            'as soon as 是一……就……；be up to you 是「由你决定、也由你负责」。')],
             source=(1311.65, 1316.60)),
        dict(n='11', title='换你来说',
             lines=[(470, 'In school the rubric was clear.', 44, 'green2', True),
                    (560, 'At work, it’s all up to me —', 44, 'green2', True),
                    (650, 'and that took some getting used to.', 42, 'green2', True),
                    (870, '你可以试着这样说', 38, 'fg', False),
                    (1090, '把 rubric / up to me 换成你自己的工作', 36, 'mute', False)],
             speech=[('zh', '你也可以试着这样说。'),
                     ('en', 'In school the rubric was clear. At work, it’s all up to me '
                            '— and that took some getting used to.'),
                     ('zh', '，学校里评分表很清楚，到了工作全看我自己，我花了些时间才适应。'
                            '把 rubric 和 up to me 换成你自己的情况。')]),
        # ---- 第 2 章 方向比努力重要 ----
        dict(n='12', title='momentum 是从方向来的',
             lines=[(950, 'we get momentum', 46, 'green2', True),
                    (1030, 'from direction, not hard work.', 42, 'green2', True),
                    (1190, '势头来自方向，不是来自努力', 38, 'fg', False),
                    (1330, 'gather momentum from sth', 38, 'green', True)],
             speech=[('zh', '主持人接她那句「努力被高估」，说了自己的体会：'),
                     ('en', 'we get momentum from direction, not hard work'),
                     ('zh', '，势头是从方向来的，不是从努力来的。momentum 是惯性、势头：'
                            '方向对了，事情会自己滚起来（it snowballs）；方向错了，越用力越沉。')],
             source=(1334.81, 1338.01)),
        dict(n='13', title='as hard as you want',
             lines=[(950, 'You can push a rock up a hill', 40, 'green2', True),
                    (1030, 'as hard as you want, and you', 40, 'green2', True),
                    (1110, 'won’t gather momentum …', 40, 'green2', True),
                    (1190, '你再用力推，也攒不出势头', 38, 'fg', False),
                    (1330, 'as hard as you want', 38, 'green', True)],
             speech=[('zh', '这句是本条最值得背下来的一句。'),
                     ('en', 'You can push a rock up a hill as hard as you want, '
                            'and you won’t gather momentum because the direction’s wrong.'),
                     ('zh', '，你可以用尽全力把石头往山上推，但因为方向错了，'
                            '你攒不出任何势头。as hard as you want，你想要多用力就多用力——'
                            '前面让一步，后面的结论才砸得响。')],
             source=(1345.47, 1351.60)),
        dict(n='14', title='换你来说',
             lines=[(470, 'I was pushing hard in', 44, 'green2', True),
                    (560, 'the wrong direction —', 44, 'green2', True),
                    (650, 'that’s why nothing moved.', 42, 'green2', True),
                    (870, '你可以试着这样说', 38, 'fg', False),
                    (1090, '把方向换成你正在使劲的那件事', 36, 'mute', False)],
             speech=[('zh', '你也可以试着这样说。'),
                     ('en', 'I was pushing hard in the wrong direction — that’s why '
                            'nothing moved.'),
                     ('zh', '，我一直在错误的方向上使劲，所以什么都没推动。'
                            '把方向，换成你正在使劲的那件事。')]),
        # ---- 第 3 章 她怎么选：先说边界 ----
        dict(n='15', title='自曝式开场',
             lines=[(950, 'A lot of people', 46, 'green2', True),
                    (1030, 'don’t know this, but', 44, 'green2', True),
                    (1110, 'I’m very introverted.', 44, 'green2', True),
                    (1190, '很多人不知道，我其实很内向', 38, 'fg', False),
                    (1330, 'A lot of people don’t know this, but …', 34, 'green', True)],
             speech=[('zh', '要做一段自我暴露，先说一句 '),
                     ('en', 'A lot of people don’t know this, but …'),
                     ('zh', '，很多人不知道……。她说 A lot of people don’t know this, '
                            'but I’m very introverted.，很多人不知道，我其实很内向。'
                            '这句一出来，后面的话就有了亲近感。')],
             source=(1382.41, 1384.95)),
        dict(n='16', title='the older I’ve gotten, the more …',
             lines=[(950, 'The older I’ve gotten,', 44, 'green2', True),
                    (1030, 'the more I’ve realized', 44, 'green2', True),
                    (1110, 'that it’s actually …', 42, 'green2', True),
                    (1190, '越长大我越发现', 38, 'fg', False),
                    (1330, 'The older I’ve gotten, the more I’ve realized …', 32, 'green', True)],
             speech=[('zh', '讲「认知变了」，用这个句式：'),
                     ('en', 'The older I’ve gotten, the more I’ve realized that it’s actually '
                            'really important for me to have a little bit of personal space '
                            'and time'),
                     ('zh', '，越长大我越发现，留一点自己的空间和时间，对我来说真的很重要。'
                            'the 加比较级可以套 now that I’m working、the longer I stay——'
                            '比 I learned 更能说出变化的过程。')],
             source=(1385.21, 1392.57)),
        dict(n='17', title='outward facing / which means',
             lines=[(950, 'a lot of it is outward facing,', 40, 'green2', True),
                    (1030, 'which means I’ve already done', 40, 'green2', True),
                    (1110, 'the work to get here.', 40, 'green2', True),
                    (1190, '大部分是对外的事，也就是说，功课我早做完了', 34, 'fg', False),
                    (1330, 'be outward facing / which means …', 36, 'green', True)],
             speech=[('zh', '她把工作和成长分成两半，先说工作那一半：'),
                     ('en', 'a lot of it is outward facing, which means I’ve already done '
                            'the work to get here'),
                     ('zh', '，大部分是对外的事，也就是说，走到这一步的功课我早做完了。'
                            'outward facing 是对外的、面向公众的；which means 用来把话往前推一步。')],
             source=(1399.35, 1403.87)),
        dict(n='18', title='take the time to …（排比）',
             lines=[(950, 'I need to take the time', 44, 'green2', True),
                    (1030, 'to learn, I need to take', 42, 'green2', True),
                    (1110, 'the time to fail.', 44, 'green2', True),
                    (1190, '我需要拿时间去学，也需要拿时间去失败', 34, 'fg', False),
                    (1330, 'take the time to do sth', 38, 'green', True)],
             speech=[('zh', '讲「给自己留时间」，用 take the time to do。她说：'),
                     ('en', 'I need to take the time to learn. I need to take the time to fail.'),
                     ('zh', '，我需要拿时间去学，也需要拿时间去失败。同一个句式连着说两遍，'
                            '节奏就出来了；take the time to fail 这种反直觉的搭配，'
                            '比 try and fail 更有分量。')],
             source=(1429.49, 1433.15)),
        dict(n='19', title='say yes to sth',
             lines=[(950, 'It’s important to say yes to', 40, 'green2', True),
                    (1030, 'something that you didn’t', 40, 'green2', True),
                    (1110, 'think you would have fun doing.', 38, 'green2', True),
                    (1190, '去答应一件你没想到会有意思的事', 34, 'fg', False),
                    (1330, 'say yes to sth', 38, 'green', True)],
             speech=[('zh', '她接着列了三件对成长重要的事：去旅行、学个新爱好、交个新朋友，然后是'),
                     ('en', 'It’s important to say yes to something that you didn’t think '
                            'you would have fun doing.'),
                     ('zh', '，去答应一件你事先没想到会有意思的事。'
                            'say yes to 是接受、答应；后面接 you didn’t think you would 这种'
                            '否定从句，语气更像是「给未来的自己留个口子」。')],
             source=(1444.13, 1447.33)),
        dict(n='20', title='as far as … goes',
             lines=[(950, 'as far as knowing', 44, 'green2', True),
                    (1030, 'what’s important within work,', 40, 'green2', True),
                    (1110, 'that’s very easy for me', 42, 'green2', True),
                    (1190, '要说工作里什么重要，我很好判断', 36, 'fg', False),
                    (1330, 'as far as … (goes)', 38, 'green', True)],
             speech=[('zh', '讲长回答，先用 as far as 划定范围：'),
                     ('en', 'as far as knowing what’s important within work, '
                            'that’s very easy for me to decide'),
                     ('zh', '，要说工作里什么重要，我很好判断。as far as 后面接名词或动名词，'
                            '等于「在……这件事上」；面试答题时先划范围再讲，听着就有条理。')],
             source=(1450.17, 1454.70)),
        dict(n='21', title='换你来说',
             lines=[(470, 'As far as what I want to do', 42, 'green2', True),
                    (560, 'next, I don’t know yet —', 42, 'green2', True),
                    (650, 'but I know what I won’t do.', 42, 'green2', True),
                    (870, '你可以试着这样说', 38, 'fg', False),
                    (1090, '先划范围（as far as），再给答案', 36, 'mute', False)],
             speech=[('zh', '你也可以试着这样说。'),
                     ('en', 'As far as what I want to do next, I don’t know yet — but I know '
                            'what I won’t do.'),
                     ('zh', '，要说我接下来想做什么，我还没想清楚，但我知道自己不会做什么。'
                            '先用 as far as 划好范围，再给答案。')]),
        # ---- 第 4 章 价值观当筛子 ----
        dict(n='22', title='be aligned with',
             lines=[(950, 'I only do things that', 44, 'green2', True),
                    (1030, 'I feel aligned with', 44, 'green2', True),
                    (1110, 'me, my values.', 44, 'green2', True),
                    (1190, '我只做和我的价值观一致的事', 38, 'fg', False),
                    (1330, 'be aligned with sth', 38, 'green', True)],
             speech=[('zh', '她讲自己怎么筛机会：'),
                     ('en', 'I only do things that I feel aligned with me, my values'),
                     ('zh', '，我只做和我的价值观一致的事。这句话前面还有一句：'
                            'I have very clear boundaries. be aligned with 是当代职场的高频说法，'
                            '换成中文就是「对得上」；反过来说就是 misaligned。')],
             source=(1457.55, 1460.79)),
        dict(n='23', title='What’s great about X is that …',
             lines=[(950, 'What’s great about my brand', 40, 'green2', True),
                    (1030, 'is that it’s actually just', 40, 'green2', True),
                    (1110, 'my values and who I am.', 40, 'green2', True),
                    (1190, '我的品牌好在，它就是我的价值观和我本人', 32, 'fg', False),
                    (1330, 'What’s great about X is that …', 36, 'green', True)],
             speech=[('zh', '要夸一个东西好在哪，用 What’s great about X is that …。她说 '),
                     ('en', 'What’s great about my brand is that it’s actually just my values '
                            'and what I like to do and who I am.'),
                     ('zh', '，我的品牌好在，它就是我的价值观、我喜欢做的事和我这个人。'
                            '主语从句开头，把「好在哪」摆到最前面；介绍产品、团队、自己都能用。')],
             source=(1461.43, 1466.13)),
        dict(n='24', title='lead sb astray',
             lines=[(950, 'Those values guide me, and', 40, 'green2', True),
                    (1030, 'I feel they have not', 40, 'green2', True),
                    (1110, 'really led me astray.', 40, 'green2', True),
                    (1190, '这些价值观带着我，没让我走弯路', 36, 'fg', False),
                    (1330, 'lead sb astray', 38, 'green', True)],
             speech=[('zh', '讲「没有走弯路」，反着说更有味道：'),
                     ('en', 'Those values guide me, and I feel they have not really led me astray'),
                     ('zh', '，这些价值观带着我走，我觉得它们没让我走偏。'
                            'lead someone astray 是「把某人带偏」，反过来说就是「一直没走错」。')],
             source=(1496.31, 1499.10)),
        dict(n='25', title='just by virtue of …',
             lines=[(950, 'it’ll land on heads more than', 36, 'green2', True),
                    (1030, 'if you flip it five times,', 38, 'green2', True),
                    (1110, 'just by virtue of how', 40, 'green2', True),
                    (1190, '就因为抛得次数多', 38, 'fg', False),
                    (1330, 'just by virtue of sth', 38, 'green', True)],
             speech=[('zh', '她讲自己面对未知的办法，先抛了个硬币的比喻：抛一百次，'
                            '正面朝上的次数会比抛五次多——'),
                     ('en', 'just by virtue of how many times you flip the coin'),
                     ('zh', '，就因为抛的次数多。just by virtue of 是「仅仅因为」，'
                            '比 because of 更书面；后面接名词或动名词。')],
             source=(1515.67, 1522.11)),
        dict(n='26', title='Life is more about A than it is about B',
             lines=[(950, 'life is more about collecting', 38, 'green2', True),
                    (1030, 'and connecting things than', 38, 'green2', True),
                    (1110, 'it is about doing or being anything.', 34, 'green2', True),
                    (1190, '人生更像是收集和连接，而不是成为某个身份', 30, 'fg', False),
                    (1330, 'Life is more about A than (it is about) B.', 32, 'green', True)],
             speech=[('zh', '主持人用一句比较级给人生下了个定义：'),
                     ('en', 'life is more about collecting and connecting things than it is '
                            'about doing or being anything'),
                     ('zh', '，人生更像是收集和连接，而不是成为某个身份。'
                            'more about A than it is about B，用它下定义，比 A is B 留有余地，'
                            '也更像在想事情而不是下结论。')],
             source=(1544.73, 1551.65)),
        dict(n='27', title='as opposed to / put sb in a box',
             lines=[(950, 'you’re a collection and', 40, 'green2', True),
                    (1030, 'connection of all these ideas,', 36, 'green2', True),
                    (1110, 'as opposed to, like, oh, I’m an athlete', 34, 'green2', True),
                    (1190, '你是一堆想法和经历的连接，而不是一个标签', 30, 'fg', False),
                    (1330, 'as opposed to / put sb in a box', 34, 'green', True)],
             speech=[('zh', '他接着往下列：'),
                     ('en', 'you’re a collection and connection of all these ideas, '
                            'philosophies, beliefs, interests, values, as opposed to, like, '
                            'oh, I’m an athlete'),
                     ('zh', '，你是一堆想法、信念、兴趣、价值观的集合与连接，而不是「我是个运动员」'
                            '这样一个标签。as opposed to 放在句尾做对比，比 but 书面；'
                            '这种「用标签把人装进去」的说法，英语里叫 put someone in a box。')],
             source=(1566.11, 1575.33)),
        dict(n='28', title='换你来说',
             lines=[(470, 'I’m not just a designer —', 44, 'green2', True),
                    (560, 'I’m a collection of the', 44, 'green2', True),
                    (650, 'things I’ve collected.', 44, 'green2', True),
                    (870, '你可以试着这样说', 38, 'fg', False),
                    (1090, '用 as opposed to 把标签推开', 36, 'mute', False)],
             speech=[('zh', '你也可以试着这样说。'),
                     ('en', 'I’m not just a designer — I’m a collection of the things '
                            'I’ve collected, as opposed to one job title.'),
                     ('zh', '，我不只是一个设计师，我是一堆经历攒起来的人，而不是一个职位。'
                            '用 as opposed to 把别人给你的标签推开。')]),
        # ---- 第 5 章 收尾 ----
        dict(n='29', title='带着这些点，再听一遍',
             lines=[(950, '现在再完整听一遍', 50, 'fg', False),
                    (1040, '你应该能听出更多东西了', 52, 'green', False),
                    (1210, '5 分 38 秒，22 个地道表达', 44, 'mute', False)],
             speech=[('zh', '现在带着刚才拆过的这些点，再完整听一遍这 5 分 38 秒。'
                            '这一次，你会听清她怎么用价值观筛机会，也会听清那句 '),
                     ('en', 'you won’t gather momentum because the direction’s wrong'),
                     ('zh', ' 是怎么落下来的。')],
             source=(1249.60, 1588.00)),
        dict(n='30', title='跟着读三遍',
             lines=[(470, '1. As far as what I want', 42, 'green2', True),
                    (545, 'next, I don’t know yet.', 42, 'green2', True),
                    (670, '2. I only do things that', 42, 'green2', True),
                    (740, 'I feel aligned with.', 42, 'green2', True),
                    (865, '3. The older I’ve gotten,', 42, 'green2', True),
                    (938, 'the more I’ve realized.', 42, 'green2', True)],
             speech=[('zh', '最后挑三句最常用的，跟着读一遍。'),
                     ('en', 'As far as what I want next, I don’t know yet.'),
                     ('en', 'I only do things that I feel aligned with.'),
                     ('en', 'The older I’ve gotten, the more I’ve realized.'),
                     ('zh', '不用追求完美，先把它说出口。')],
             tail=3.1),
        dict(n='31', title='收藏，下次选方向的时候过一遍',
             lines=[(480, '拾句英语', 100, 'green', False),
                    (650, '五分钟，想清楚「往哪走」', 42, 'fg', False),
                    (850, '落差   it’s all up to you', 36, 'green2', False),
                    (925, '方向   you won’t gather momentum …', 34, 'green2', False),
                    (1000, '筛选   aligned with my values', 36, 'green2', False),
                    (1200, '听懂一句，再把它说出来', 40, 'mute', False)],
             speech=[('zh', '这一期讲的是怎么给自己定方向：先承认离开学校后没有评分系统，'
                            '再看势头是从方向来的，最后用价值观当筛子。'),
                     ('zh', '先收藏，下次不知道该往哪走的时候，把这三句过一遍。'
                            '拾句英语，听懂一句，再把它说出来。')]),
    ],
)


# ---- 10 学习是超能力（原片 1588.00–1880.00，292.00 秒）----
# 与 09 章的边界：09 收在「fighting between them.」（26:28），本条从 26:28 接。
# 2026-09 新片规格全用默认；口吻：练习句用邀请式（「你也可以试着这样说」）。
SPECS['谷爱凌_学习是超能力'] = dict(
    src='__DATA_ROOT__/小红书发帖-拾句英语/谷爱凌/谷爱凌最新全英访谈.mp4',
    cards=[
        # ---- 第 0 章 钩子 + 完整听一遍（292 秒，拆三张）----
        dict(n='01', title='把学习当成超能力',
             lines=[(770, '跟着 5 分钟访谈学表达', 46, 'green', False),
                    (920, '空杯 · 超能力 · 母女', 40, 'fg', False),
                    (1000, '21 个表达，就藏在 4 分 52 秒里', 34, 'mute', False)],
             speech=[('zh', '有一句话她说了三遍，而且一次比一次重：'),
                     ('en', 'the sooner … the better.'),
                     ('zh', '在这段 4 分 52 秒里，她讲了自己 12 岁读育儿手册、'
                            '把「学习」当成超能力的过程，也讲了和妈妈那种「一个人也是两个人」的关系。'),
                     ('zh', '我们先完整听一遍，再一句一句拆。')]),
        dict(n='02', title='先听前 98 秒',
             lines=[(950, 'when one of us doesn’t know,', 40, 'green2', True),
                    (1030, 'we don’t pretend that we do', 40, 'green2', True),
                    (1190, '先听前 98 秒', 42, 'fg', False),
                    (1330, '这一段讲「我们家的学习方式」', 38, 'mute', False)],
             speech=[('zh', '先听前 98 秒。她先讲了自己家的一条规矩：'
                            '谁不懂，就不装懂。')],
             source=(1588.00, 1686.30)),
        dict(n='03', title='再听 63 秒',
             lines=[(950, 'It’s not about becoming', 42, 'green2', True),
                    (1030, 'an expert. It’s about knowing', 40, 'green2', True),
                    (1110, 'you have the power to learn.', 38, 'green2', True),
                    (1190, '再听 63 秒', 42, 'fg', False),
                    (1330, '这一段是本条的核心定义', 38, 'mute', False)],
             speech=[('zh', '再听 63 秒。这一段是她整段回答的核心：'
                            '学习不是要变成专家，而是知道自己有学会的能力。')],
             source=(1688.11, 1751.19)),
        dict(n='04', title='最后 128 秒',
             lines=[(950, 'I did everything to a tee', 40, 'green2', True),
                    (1030, 'and you turned out pretty well.', 38, 'green2', True),
                    (1190, '最后 128 秒', 42, 'fg', False),
                    (1330, '听完这一遍，我们就开始拆', 38, 'mute', False)],
             speech=[('zh', '最后 128 秒。她讲了自己 12 岁读育儿手册的事，'
                            '也讲了那种「既是同一个人，又是一枚硬币的两面」的关系。'
                            '听完这一遍，我们就开始拆。')],
             source=(1751.59, 1880.00)),
        # ---- 第 1 章 我家的规矩：不装懂 ----
        dict(n='05', title='preface this by saying',
             lines=[(950, 'I will preface this', 44, 'green2', True),
                    (1030, 'by saying I’m an only child.', 42, 'green2', True),
                    (1190, '先说一句：我是独生女', 40, 'fg', False),
                    (1330, 'I’ll preface this by saying …', 36, 'green', True)],
             speech=[('zh', '要讲一件容易被误读的事，先说一句 '),
                     ('en', 'I will preface this by saying I’m an only child.'),
                     ('zh', '，我先声明一下，我是独生女。preface 本来是「序言」，'
                            '当动词就是「先说一句、先交代一下」——'
                            '等于提前把背景铺好，后面说什么都不显得突兀。')],
             source=(1624.53, 1626.40)),
        dict(n='06', title='we don’t pretend that we do',
             lines=[(950, 'when one of us doesn’t know,', 40, 'green2', True),
                    (1030, 'we don’t pretend that we do.', 40, 'green2', True),
                    (1190, '谁不懂，就不装懂', 40, 'fg', False),
                    (1330, 'we don’t pretend that we do', 36, 'green', True)],
             speech=[('zh', '她形容家里的相处方式：'),
                     ('en', 'when one of us doesn’t know, we don’t pretend that we do'),
                     ('zh', '，谁不懂就不装懂。句尾的 do 代替前面的 know，'
                            '英语里最不喜欢重复动词，用 do / does 顶上去就够了——'
                            '中式英语常见的毛病就是把 know 再说一遍。')],
             source=(1662.00, 1664.90)),
        dict(n='07', title='student mentality / I’ll learn',
             lines=[(950, 'a humble and almost like', 40, 'green2', True),
                    (1030, 'student mentality where it’s like,', 38, 'green2', True),
                    (1110, 'I don’t know, but I’ll learn.', 40, 'green2', True),
                    (1190, '一种「我不懂，但我可以学」的心态', 36, 'fg', False),
                    (1330, 'student mentality', 38, 'green', True)],
             speech=[('zh', '一句话概括这种状态：'),
                     ('en', 'there’s this kind of humble and almost like student mentality '
                            'where it’s like, I don’t know, but I’ll learn'),
                     ('zh', '，有一种很谦逊、几乎是学生的心态：我不懂，但我可以学。'
                            'student mentality 搬到职场就是「空杯心态」；'
                            '后面那半句 I don’t know, but I’ll learn 短、狠、能直接用。')],
             source=(1665.25, 1671.60)),
        dict(n='08', title='not everyone has all the answers',
             lines=[(950, 'not everyone has', 44, 'green2', True),
                    (1030, 'all the answers.', 44, 'green2', True),
                    (1190, '不是每个人都有答案', 40, 'fg', False),
                    (1330, 'not everyone has all the answers', 34, 'green', True)],
             speech=[('zh', '这句是她那句「我不懂，但我可以学」的放大版：'),
                     ('en', 'not everyone has all the answers'),
                     ('zh', '，不是每个人都有答案。她在后面补了一句：'
                            'as a young person, the sooner you learn that, the better.——'
                            '越早明白这一点越好。这句话安慰别人、也安慰自己，'
                            '跟人聊焦虑时特别顺手。')],
             source=(1674.95, 1677.90)),
        dict(n='09', title='换你来说',
             lines=[(470, 'I don’t know this yet —', 44, 'green2', True),
                    (560, 'but I’ll learn it.', 44, 'green2', True),
                    (870, '你可以试着这样说', 38, 'fg', False),
                    (1090, '把 this 换成你正在硬撑的那件事', 36, 'mute', False)],
             speech=[('zh', '你也可以试着这样说。'),
                     ('en', 'I don’t know this yet — but I’ll learn it.'),
                     ('zh', '，这个我还不懂，但我可以学。把 this，换成你正在硬撑的那件事。')]),
        # ---- 第 2 章 学习是超能力 ----
        dict(n='10', title='the sooner …, the better',
             lines=[(950, 'the sooner you learn that,', 42, 'green2', True),
                    (1030, 'the better.', 44, 'green2', True),
                    (1190, '越早明白越好', 40, 'fg', False),
                    (1330, 'the sooner …, the better', 38, 'green', True)],
             speech=[('zh', '这句话她在这一章里用了三次。'),
                     ('en', 'the sooner you learn that, the better'),
                     ('zh', '，越早明白越好。the 加比较级，再加 the 加比较级：越……就越……。'
                            '后面还有一句用同一个结构：'),
                     ('en', 'the sooner you take your fate and agency of learning into your own hands, '
                            'the better'),
                     ('zh', '，越早把学习的主动权拿到自己手里越好。')],
             source=(1678.31, 1680.10)),
        dict(n='11', title='take sth into your own hands',
             lines=[(950, 'take your fate and agency', 40, 'green2', True),
                    (1030, 'of learning into', 40, 'green2', True),
                    (1110, 'your own hands', 42, 'green2', True),
                    (1190, '把学习的主动权拿到自己手里', 38, 'fg', False),
                    (1330, 'take sth into your own hands', 36, 'green', True)],
             speech=[('zh', '讲「自己接手」，用 '),
                     ('en', 'take something into your own hands'),
                     ('zh', '。她说 the sooner you take your fate and agency of learning '
                            'into your own hands, the better，越早把命运和学习的主动权'
                            '拿到自己手里越好。agency 是「能动性」，现在职场里很常听到。')],
             source=(1682.97, 1686.21)),
        dict(n='12', title='It’s not about A. It’s about B.',
             lines=[(950, 'It’s not about becoming', 42, 'green2', True),
                    (1030, 'an expert. It’s about knowing', 40, 'green2', True),
                    (1110, 'you have the power to learn.', 38, 'green2', True),
                    (1190, '不是要变成专家，而是知道你有学会的能力', 32, 'fg', False),
                    (1330, 'It’s not about A. It’s about B.', 36, 'green', True)],
             speech=[('zh', '要重新定义一件事，用两步：'),
                     ('en', 'It’s not about becoming an expert. It’s about knowing that you '
                            'have the power to learn.'),
                     ('zh', '，重点不是变成专家，而是知道你有学会的能力。'
                            '先否掉大家默认的那个答案，再给出你的版本——'
                            '这个结构在讲观点、讲产品、讲自己时都好用。')],
             source=(1686.65, 1689.90)),
        dict(n='13', title='your greatest superpower',
             lines=[(950, 'and that is', 46, 'green2', True),
                    (1030, 'your greatest superpower.', 42, 'green2', True),
                    (1190, '那就是你最大的超能力', 40, 'fg', False),
                    (1330, 'one’s greatest superpower', 36, 'green', True)],
             speech=[('zh', '她给这份能力起了个名字：'),
                     ('en', 'and that is your greatest superpower'),
                     ('zh', '，那就是你最大的超能力。superpower 比 strength 生动得多，'
                            '夸自己的核心竞争力、夸别人都行；'
                            '类似的还有 secret weapon、edge。')],
             source=(1689.95, 1691.15)),
        dict(n='14', title='come to the understanding that …',
             lines=[(950, 'I came to the', 44, 'green2', True),
                    (1030, 'understanding that learning', 42, 'green2', True),
                    (1110, 'was my superpower', 42, 'green2', True),
                    (1190, '我很早就明白，学习就是我的超能力', 36, 'fg', False),
                    (1330, 'come to the understanding that …', 34, 'green', True)],
             speech=[('zh', '讲「我想明白了」，用一个更成熟的说法：'),
                     ('en', 'I came to the understanding that learning was my superpower '
                            'very early'),
                     ('zh', '，我很早就明白，学习就是我的超能力。'
                            '比 I realized 更书面、更有过程感——'
                            '像「经过一段时间，我形成了这个认识」。')],
             source=(1699.89, 1703.75)),
        dict(n='15', title='with high agency',
             lines=[(950, 'I employed that with', 42, 'green2', True),
                    (1030, 'kind of like high agency', 42, 'green2', True),
                    (1110, 'over time.', 44, 'green2', True),
                    (1190, '后来我一直用很强的能动性在做这件事', 36, 'fg', False),
                    (1330, 'with high agency', 38, 'green', True)],
             speech=[('zh', '她接着说：'),
                     ('en', 'I feel like I employed that with kind of like high agency over time'),
                     ('zh', '，后来的这些年，我一直用很强的能动性在做这件事。'
                            'agency 是「能动性、主导权」——自己决定、自己推进，'
                            '而不是等别人安排；high agency 现在常用来形容这类人。')],
             source=(1704.01, 1707.60)),
        dict(n='16', title='换你来说',
             lines=[(470, 'It’s not about waiting to be', 42, 'green2', True),
                    (560, 'picked. It’s about learning', 42, 'green2', True),
                    (650, 'faster than anyone else.', 42, 'green2', True),
                    (870, '你可以试着这样说', 38, 'fg', False),
                    (1090, '用 It’s not about A. It’s about B. 换掉你的版本', 34, 'mute', False)],
             speech=[('zh', '你也可以试着这样说。'),
                     ('en', 'It’s not about waiting to be picked. It’s about learning faster '
                            'than anyone else.'),
                     ('zh', '，重点不是等着被挑中，而是比别人学得快。'
                            '把 A 和 B 换成你自己的两个答案。')]),
        # ---- 第 3 章 12 岁读育儿手册 ----
        dict(n='17', title='by the book',
             lines=[(950, 'I raised you by the book,', 40, 'green2', True),
                    (1030, 'like when you were born.', 40, 'green2', True),
                    (1190, '我都是照着书把你养大的', 40, 'fg', False),
                    (1330, 'by the book', 38, 'green', True)],
             speech=[('zh', '她转述妈妈的话：'),
                     ('en', 'I raised you by the book like when you were born'),
                     ('zh', '，你刚出生那阵，我都是照着书把你养大的。'
                            'by the book 是「严格按规矩、按手册来」，'
                            '工作里也可以说 We did it by the book，就是「我们完全按流程走的」。')],
             source=(1725.59, 1727.30)),
        dict(n='18', title='to a tee',
             lines=[(950, 'I did everything', 44, 'green2', True),
                    (1030, 'to a tee', 46, 'green2', True),
                    (1110, 'and you turned out pretty well.', 38, 'green2', True),
                    (1190, '我每一步都做到位，你也长得挺好', 36, 'fg', False),
                    (1330, 'do sth to a tee', 38, 'green', True)],
             speech=[('zh', '妈妈原话里的第二句：'),
                     ('en', 'I did everything to a tee and you turned out pretty well'),
                     ('zh', '，我每一步都做到位，你后来长得挺好。to a tee 是「分毫不差、'
                            '严丝合缝」，比 perfectly 更口语；'
                            '写成 to a T 也对，两种拼法都常见。')],
             source=(1730.07, 1732.99)),
        dict(n='19', title='the people you surround yourself with',
             lines=[(950, 'so much of it is the people', 38, 'green2', True),
                    (1030, 'who you surround yourself with', 38, 'green2', True),
                    (1110, 'and your self-learning.', 40, 'green2', True),
                    (1190, '很大一部分取决于你身边的人和你自己的学习', 32, 'fg', False),
                    (1330, 'the people you surround yourself with', 32, 'green', True)],
             speech=[('zh', '妈妈还有一个说法：十三岁以后，'),
                     ('en', 'so much of it is the people who you surround yourself with '
                            'and your self-learning'),
                     ('zh', '，很大一部分取决于你身边是什么人，以及你自己学不学。'
                            'surround yourself with 是高频道法：'
                            'surround yourself with good people，把自己放在好的人中间。')],
             source=(1748.85, 1751.19)),
        dict(n='20', title='get on that',
             lines=[(950, 'I’m 12, 13, so I', 42, 'green2', True),
                    (1030, 'should probably get on that.', 40, 'green2', True),
                    (1190, '我都十二三了，这事得赶紧着手', 38, 'fg', False),
                    (1330, 'get on sth（赶紧着手）', 38, 'green', True)],
             speech=[('zh', '听完妈妈那句话，她的反应是：'),
                     ('en', 'I’m 12, 13, so I should probably get on that, you know?'),
                     ('zh', '，我都十二三了，这事得赶紧着手了吧。get on something 是'
                            '「开始做、抓紧处理」，口语里很常用：'
                            'I should get on that. 就是「我该去做这件事了」。')],
             source=(1754.83, 1756.97)),
        dict(n='21', title='an easy read',
             lines=[(950, 'They were like', 44, 'green2', True),
                    (1030, 'an easy read.', 46, 'green2', True),
                    (1190, '那本书挺好懂的', 40, 'fg', False),
                    (1330, 'sth is an easy read', 38, 'green', True)],
             speech=[('zh', '她评价那本育儿手册：'),
                     ('en', 'They were like an easy read.'),
                     ('zh', '，挺好懂的。an easy read 是把「好不好读」名词化，'
                            '比 it is easy to read 更像母语者的说法；'
                            '反过来可以说 a heavy read、a tough read。')],
             source=(1764.05, 1765.17)),
        dict(n='22', title='be locked in',
             lines=[(950, 'I was reading that,', 42, 'green2', True),
                    (1030, 'I was super locked in.', 42, 'green2', True),
                    (1190, '我读那本书的时候，完全进去了', 38, 'fg', False),
                    (1330, 'be locked in（全神贯注）', 36, 'green', True)],
             speech=[('zh', '讲「完全投入」，用 be locked in：'),
                     ('en', 'I was reading that. I was super locked in.'),
                     ('zh', '，我读那本书的时候，整个人都进去了。它比 very focused 更地道，'
                            '也更像在描述状态——打游戏、看剧、写代码入迷了，都可以说 I was locked in。')],
             source=(1782.87, 1784.47)),
        dict(n='23', title='换你来说',
             lines=[(470, 'I read it twice and got', 42, 'green2', True),
                    (560, 'totally locked in — it', 42, 'green2', True),
                    (650, 'was an easy read.', 42, 'green2', True),
                    (870, '你可以试着这样说', 38, 'fg', False),
                    (1090, 'easy read / locked in 都能直接用', 36, 'mute', False)],
             speech=[('zh', '你也可以试着这样说。'),
                     ('en', 'I read it twice and got totally locked in — it was an easy read.'),
                     ('zh', '，那本书我读了两遍，完全看进去了，而且很好懂。'
                            '把 it 换成你手边那本书、那份报告。')]),
        # ---- 第 4 章 一个人，也是两个人 ----
        dict(n='24', title='different sides of the same coin',
             lines=[(950, 'we are both the same person', 38, 'green2', True),
                    (1030, 'and different sides', 40, 'green2', True),
                    (1110, 'of the same coin.', 42, 'green2', True),
                    (1190, '我们既是同一个人，又是同一枚硬币的两面', 32, 'fg', False),
                    (1330, 'two sides of the same coin', 34, 'green', True)],
             speech=[('zh', '讲她和妈妈的关系，她用了一个习语：'),
                     ('en', 'we are both the same person and different sides of the same coin'),
                     ('zh', '，我们既是同一个人，又是同一枚硬币的两面。'
                            '常见写法是 two sides of the same coin，'
                            '用来讲「看着相反，其实是一回事」——'
                            '比如风险和机会、压力和动力。')],
             source=(1806.40, 1811.10)),
        dict(n='25', title='inextricably connected',
             lines=[(950, 'We are inextricably', 42, 'green2', True),
                    (1030, 'connected and we’re both', 42, 'green2', True),
                    (1110, 'really invested in me.', 40, 'green2', True),
                    (1190, '我们分不开，而且都在为「我」投入', 34, 'fg', False),
                    (1330, 'be inextricably connected', 34, 'green', True)],
             speech=[('zh', '接着她把关系说重了一层：'),
                     ('en', 'We are inextricably connected and we’re both really invested in me'),
                     ('zh', '，我们分不开，而且两个人都在为「我」这件事投入。'
                            'inextricably 是「解不开地」，写作用得多，'
                            '讲因果、讲绑定关系都很准。')],
             source=(1811.19, 1816.81)),
        dict(n='26', title='my greatest blessing',
             lines=[(950, 'I think truly my', 44, 'green2', True),
                    (1030, 'greatest blessing is that I do.', 40, 'green2', True),
                    (1190, '说真的，我最大的幸运就是我有', 38, 'fg', False),
                    (1330, 'one’s greatest blessing', 38, 'green', True)],
             speech=[('zh', '她承认不是每个人都能有这种关系，然后说：'),
                     ('en', 'I think truly my greatest blessing is that I do.'),
                     ('zh', '，说真的，我最大的幸运就是我有。blessing 是「福气、幸运」，'
                            '比 luck 更重、更暖；句尾的 do 代替前面那个动词（have that '
                            'relationship），又是那个「用 do 顶替」的用法。')],
             source=(1826.03, 1828.45)),
        dict(n='27', title='be game to do sth',
             lines=[(950, 'your mom was game', 44, 'green2', True),
                    (1030, 'to actually collaborate', 42, 'green2', True),
                    (1110, 'with you', 46, 'green2', True),
                    (1190, '你妈妈真的愿意跟你配合', 40, 'fg', False),
                    (1330, 'be game to do sth', 38, 'green', True)],
             speech=[('zh', '主持人这句话里有个很地道的形容词：'),
                     ('en', 'your mom was game to actually collaborate with you'),
                     ('zh', '，你妈妈真的愿意跟你一起做这件事。be game to do 是'
                            '「乐意、愿意参与」，比 willing 更有兴致；'
                            '口语里也可以直接说 I’m game.（我来 / 我参加）。')],
             source=(1841.55, 1845.20)),
        dict(n='28', title='换你来说',
             lines=[(470, 'My dad was game to read', 42, 'green2', True),
                    (560, 'it with me — we’re', 42, 'green2', True),
                    (650, 'different sides of the same coin.', 38, 'green2', True),
                    (870, '你可以试着这样说', 38, 'fg', False),
                    (1090, '把 game to / same coin 换成你的那两个人', 34, 'mute', False)],
             speech=[('zh', '你也可以试着这样说。'),
                     ('en', 'My dad was game to read it with me — we’re different sides of '
                            'the same coin.'),
                     ('zh', '，我爸愿意跟我一起读，我们是同一枚硬币的两面。'
                            '把这两个人，换成你身边愿意陪你做这件事的人。')]),
        # ---- 第 5 章 收尾 ----
        dict(n='29', title='带着这些点，再听一遍',
             lines=[(950, '现在再完整听一遍', 50, 'fg', False),
                    (1040, '你应该能听出更多东西了', 52, 'green', False),
                    (1210, '4 分 52 秒，21 个地道表达', 44, 'mute', False)],
             speech=[('zh', '现在带着刚才拆过的这些点，再完整听一遍这 4 分 52 秒。'
                            '这一次，你会听清她怎么把「学习」讲成一种能力，'
                            '也会听清那句 '),
                     ('en', 'the sooner you realize that she’s a person, the better'),
                     ('zh', ' 是怎么收的。')],
             source=(1588.00, 1880.00)),
        dict(n='30', title='跟着读三遍',
             lines=[(470, '1. I don’t know,', 44, 'green2', True),
                    (545, 'but I’ll learn.', 44, 'green2', True),
                    (670, '2. It’s not about becoming an expert.', 40, 'green2', True),
                    (740, 'It’s about knowing you can learn.', 40, 'green2', True),
                    (865, '3. I was super locked in.', 42, 'green2', True)],
             speech=[('zh', '最后挑三句最常用的，跟着读一遍。'),
                     ('en', 'I don’t know, but I’ll learn.'),
                     ('en', 'It’s not about becoming an expert. It’s about knowing you can learn.'),
                     ('en', 'I was super locked in.'),
                     ('zh', '不用追求完美，先把它说出口。')],
             tail=3.1),
        dict(n='31', title='收藏，下次觉得自己不懂的时候过一遍',
             lines=[(480, '拾句英语', 100, 'green', False),
                    (650, '五分钟，把「不会」变成「能学」', 40, 'fg', False),
                    (850, '心态   student mentality', 36, 'green2', False),
                    (925, '定义   It’s not about becoming an expert.', 32, 'green2', False),
                    (1000, '状态   be locked in', 36, 'green2', False),
                    (1200, '听懂一句，再把它说出来', 40, 'mute', False)],
             speech=[('zh', '这一期讲的是把学习当成超能力：先承认自己不懂，'
                            '再重新定义「学」这件事，最后讲怎么跟家人一起长。'),
                     ('zh', '先收藏，下次觉得自己什么都不懂的时候，把这三句过一遍。'
                            '拾句英语，听懂一句，再把它说出来。')]),
    ],
)


# ---- 11 比赛心态（原片 1880.00–2146.00，266.00 秒）----
# 与 10 章的边界：10 收在「pattern matching type style.」（31:20），本条从 31:20 接。
# 2026-09 新片规格全用默认；口吻：练习句用邀请式（你也可以试着这样说）。
SPECS['谷爱凌_比赛心态'] = dict(
    src='__DATA_ROOT__/小红书发帖-拾句英语/谷爱凌/谷爱凌最新全英访谈.mp4',
    cards=[
        # ---- 第 0 章 钩子 + 完整听一遍（266 秒，拆三张）----
        dict(n='01', title='训练像没赢过，比赛像没输过',
             lines=[(770, '跟着 4 分钟访谈学表达', 46, 'green', False),
                    (920, '心态 · 切换 · 自我', 40, 'fg', False),
                    (1000, '21 个表达，就藏在 4 分 26 秒里', 34, 'mute', False)],
             speech=[('zh', '有一段话，主持人听完直接说「再说一遍」：'),
                     ('en', 'I train like I’ve never won and I compete like I’ve never lost.'),
                     ('zh', '在这段 4 分 26 秒里，她讲了自己怎么把「训练的自己」'
                            '和「比赛时的自己」分开——不分开，人会疯。'),
                     ('zh', '我们先完整听一遍，再一句一句拆。')]),
        dict(n='02', title='先听前 88 秒',
             lines=[(950, 'I train like I’ve never won', 42, 'green2', True),
                    (1030, 'and I compete like I’ve never lost', 40, 'green2', True),
                    (1190, '先听前 88 秒', 42, 'fg', False),
                    (1330, '那段金句就在这一段里', 38, 'mute', False)],
             speech=[('zh', '先听前 88 秒。她先说了自己的一个说法，'
                            '再说为什么「赢了以后更难」。')],
             source=(1880.00, 1968.30)),
        dict(n='03', title='再听 87 秒',
             lines=[(950, 'that’s what creates really', 40, 'green2', True),
                    (1030, 'dangerous egos', 42, 'green2', True),
                    (1190, '再听 87 秒', 42, 'fg', False),
                    (1330, '这一段讲「训练时怎么挑自己的毛病」', 36, 'mute', False)],
             speech=[('zh', '再听 87 秒。她讲了为什么「全情投入」不能一直挂着，'
                            '也讲了训练时怎么看自己。')],
             source=(1968.80, 2055.40)),
        dict(n='04', title='最后 90 秒',
             lines=[(950, 'I just have to be the very', 40, 'green2', True),
                    (1030, 'best version of myself', 42, 'green2', True),
                    (1190, '最后 90 秒', 42, 'fg', False),
                    (1330, '听完这一遍，我们就开始拆', 38, 'mute', False)],
             speech=[('zh', '最后 90 秒。她讲了妈妈怎么把「干活的态度」传给她，'
                            '也讲了为什么她把自己当成最大的项目。听完这一遍，我们就开始拆。')],
             source=(2056.10, 2146.00)),
        # ---- 第 1 章 训练像没赢过，比赛像没输过 ----
        dict(n='05', title='引出金句的开头',
             lines=[(950, 'I have a saying', 46, 'green2', True),
                    (1030, 'where I say …', 46, 'green2', True),
                    (1190, '我有一句话是这么说的', 40, 'fg', False),
                    (1330, 'I have a saying where I say …', 36, 'green', True)],
             speech=[('zh', '要引出一句自己的口头禅，先说：'),
                     ('en', 'I have a saying where I say …'),
                     ('zh', '，我有一句话是这么说的。where I say 后面的从句'
                            '就是那句原话——比直接抛金句多了一层「这是我的习惯说法」，'
                            '听着不像在背稿。')],
             source=(1895.30, 1897.35)),
        dict(n='06', title='全片最出圈的那句',
             lines=[(950, 'I train like I’ve never won', 40, 'green2', True),
                    (1030, 'and I compete like', 40, 'green2', True),
                    (1110, 'I’ve never lost.', 42, 'green2', True),
                    (1190, '训练时像从没赢过，比赛时像从没输过', 32, 'fg', False),
                    (1330, 'train like … / compete like …', 36, 'green', True)],
             speech=[('zh', '这句是本条最值得背下来的一句。'),
                     ('en', 'I train like I’ve never won and I compete like I’ve never lost.'),
                     ('zh', '，训练的时候像从没赢过，比赛的时候像从没输过。'
                            '两半用同一个结构对照：训练要空杯、要挑毛病；'
                            '上场要自信、要当自己是最强的那个。')],
             source=(1904.00, 1907.95)),
        dict(n='07', title='way + 比较级',
             lines=[(950, 'it’s difficult to win,', 42, 'green2', True),
                    (1030, 'but it’s way harder', 42, 'green2', True),
                    (1110, 'to stay there.', 44, 'green2', True),
                    (1190, '赢很难，守在那儿难得多', 38, 'fg', False),
                    (1330, 'way + 比较级', 38, 'green', True)],
             speech=[('zh', '讲递进，用 way 加比较级：'),
                     ('en', 'it’s difficult to win, but it’s way harder to stay there'),
                     ('zh', '，赢下来很难，守在那儿要难得多。way harder 比 much harder 更口语，'
                            '等于「难太多了」；职场里说守成、说维持成绩，都能套这句。')],
             source=(1911.00, 1913.80)),
        dict(n='08', title='stay hungry',
             lines=[(950, 'it keeps you hungry,', 42, 'green2', True),
                    (1030, 'and that’s what allows you', 40, 'green2', True),
                    (1110, 'to perform over time.', 40, 'green2', True),
                    (1190, '它会让你一直饿着，才能长期出成绩', 32, 'fg', False),
                    (1330, 'keep sb hungry / stay hungry', 34, 'green', True)],
             speech=[('zh', '她解释为什么「赢过之后更难」：'),
                     ('en', 'it keeps you hungry, and that’s what allows you to perform over time'),
                     ('zh', '，它让你一直保持着那股饿劲，而正是这股劲让你能长期出成绩。'
                            'stay hungry 是英语里最经典的激励说法之一；'
                            'keep sb hungry 是「让人不敢松劲」。')],
             source=(1934.60, 1939.80)),
        dict(n='09', title='换你来说',
             lines=[(470, 'I train like I have everything', 40, 'green2', True),
                    (560, 'to prove, and I show up like', 40, 'green2', True),
                    (650, 'I have nothing to lose.', 40, 'green2', True),
                    (870, '你可以试着这样说', 38, 'fg', False),
                    (1090, '把 train / show up 换成你的两个场景', 34, 'mute', False)],
             speech=[('zh', '你也可以试着这样说。'),
                     ('en', 'I train like I have everything to prove, and I show up like '
                            'I have nothing to lose.'),
                     ('zh', '，练的时候像什么都得证明，上场的时候像没什么可输的。'
                            '把这两个场景，换成你自己的。')]),
        # ---- 第 2 章 巅峰期有多难 ----
        dict(n='10', title='stay in peak form',
             lines=[(950, 'staying in peak form during', 38, 'green2', True),
                    (1030, 'that period of your life', 40, 'green2', True),
                    (1110, 'is very, very difficult.', 40, 'green2', True),
                    (1190, '在人生那段时期保持巅峰状态，非常非常难', 32, 'fg', False),
                    (1330, 'stay in peak form', 38, 'green', True)],
             speech=[('zh', '讲「保持巅峰」，用 '),
                     ('en', 'stay in peak form'),
                     ('zh', '。她说 18 到 22 岁那几年，身体、学业、赛场都在变，'
                            'staying in peak form during that period of your life '
                            'specifically as a woman is very, very difficult，'
                            '这个阶段还要保持巅峰状态，太难了。')],
             source=(1919.70, 1925.55)),
        dict(n='11', title='that’s just two different people',
             lines=[(950, 'I was a high school grad,', 38, 'green2', True),
                    (1030, 'and now I’m a college grad,', 36, 'green2', True),
                    (1110, 'and that’s just two different people.', 34, 'green2', True),
                    (1190, '那时候的我，和现在根本是两个人', 34, 'fg', False),
                    (1330, 'that’s just two different people', 32, 'green', True)],
             speech=[('zh', '形容变化之大，用一句口语夸张：'),
                     ('en', 'I was a high school grad, and now I’m a college grad, '
                            'and that’s just two different people'),
                     ('zh', '，上一届奥运会时我高中刚毕业，现在大学毕业了——'
                            '那根本是两个人。写自我介绍、讲几年间的变化，这句比 I changed a lot 有画面。')],
             source=(1929.30, 1932.05)),
        dict(n='12', title='用序数词把观点摆开',
             lines=[(950, 'So that’s one.', 46, 'green2', True),
                    (1030, 'The second thing is …', 44, 'green2', True),
                    (1190, '第一……，第二……', 40, 'fg', False),
                    (1330, 'that’s one / the second thing is', 34, 'green', True)],
             speech=[('zh', '讲三点理由，她用最朴素的办法：'),
                     ('en', 'So that’s one. The second thing is …'),
                     ('zh', '，这是第一点，第二点是……后面她说 the third thing is。'
                            'that’s one 这种收尾方式比 firstly 自然得多；'
                            '口头汇报、面试答题，先把编号报出来，对方就知道你要说几点。')],
             source=(1932.40, 1934.70)),
        dict(n='13', title='insatiable, all-in',
             lines=[(950, 'you have to have this insatiable,', 36, 'green2', True),
                    (1030, 'almost obsessive religious', 36, 'green2', True),
                    (1110, 'all-in mentality', 40, 'green2', True),
                    (1190, '要有一种贪得无厌、近乎偏执的全情投入', 32, 'fg', False),
                    (1330, 'all-in mentality', 38, 'green', True)],
             speech=[('zh', '第二个理由是：'),
                     ('en', 'you have to have this insatiable, almost obsessive religious '
                            'all-in mentality'),
                     ('zh', '，你得有那种贪得无厌、近乎偏执的、全都押上的心态。'
                            'insatiable 是「永远填不满」，all-in 是「全押」——'
                            '她接着补了一句：这种状态不可能一直挂着，'
                            '一直挂着会长出危险的自大（dangerous egos）。')],
             source=(1944.20, 1952.50)),
        dict(n='14', title='换你来说',
             lines=[(470, 'I go all-in while I’m', 42, 'green2', True),
                    (560, 'building, then I step back', 42, 'green2', True),
                    (650, 'and stay critical.', 42, 'green2', True),
                    (870, '你可以试着这样说', 38, 'fg', False),
                    (1090, 'all-in 和 critical 都能直接搬', 36, 'mute', False)],
             speech=[('zh', '你也可以试着这样说。'),
                     ('en', 'I go all-in while I’m building, then I step back and stay critical.'),
                     ('zh', '，做的时候我全情投入，做完再退回来挑自己的毛病。'
                            '把 building 换成你正在做的那件事。')]),
        # ---- 第 3 章 上场前要切换 ----
        dict(n='15', title='be critical of sth',
             lines=[(950, 'you have to be very', 42, 'green2', True),
                    (1030, 'critical of your', 42, 'green2', True),
                    (1110, 'own training.', 44, 'green2', True),
                    (1190, '你必须对自己的训练非常挑剔', 38, 'fg', False),
                    (1330, 'be critical of sth', 38, 'green', True)],
             speech=[('zh', '讲「挑毛病、找问题」，用 '),
                     ('en', 'be critical of sth'),
                     ('zh', '。她说 because you have to be very critical of your own training，'
                            '因为你必须对自己的训练非常挑剔。be critical of 是对事不对人，'
                            '比 complain about 专业；做复盘、做评审都用得上。')],
             source=(1966.40, 1968.70)),
        dict(n='16', title='two degrees off',
             lines=[(950, 'Every single thing, I’m like,', 40, 'green2', True),
                    (1030, 'oh, I’m two degrees', 42, 'green2', True),
                    (1110, 'off on that.', 44, 'green2', True),
                    (1190, '每一处我都能看出「差了两度」', 36, 'fg', False),
                    (1330, 'be two degrees off', 38, 'green', True)],
             speech=[('zh', '形容「差了一点点」，她用了角度：'),
                     ('en', 'Every single thing, I’m like, oh, I’m two degrees off on that'),
                     ('zh', '，每个动作我都觉得差了两度。后面还有一句：I was like a second early，'
                            '早了那么一秒。be two degrees off 比 slightly wrong 具体，'
                            '也更好听。')],
             source=(1972.80, 1975.98)),
        dict(n='17', title='make the switch',
             lines=[(950, 'when I’m competing, you', 42, 'green2', True),
                    (1030, 'need to make the switch', 42, 'green2', True),
                    (1190, '一到比赛，就得切换过来', 40, 'fg', False),
                    (1330, 'make the switch', 38, 'green', True)],
             speech=[('zh', '讲「换一个状态」，用 '),
                     ('en', 'make the switch'),
                     ('zh', '。她说 But when I’m competing, you need to make the switch，'
                            '但一到比赛，你就得把这套切掉、换过来。'
                            '这个词组也能讲换工作、换系统：make the switch to a new tool。')],
             source=(1981.60, 1984.05)),
        dict(n='18', title='Nobody’s even gonna touch me.',
             lines=[(950, 'I am the best person who has', 36, 'green2', True),
                    (1030, 'ever stepped foot here.', 38, 'green2', True),
                    (1110, 'Nobody’s even gonna touch me.', 36, 'green2', True),
                    (1190, '我是站在这儿的史上最强，没人碰得到我', 32, 'fg', False),
                    (1330, 'Nobody’s even gonna touch me.', 34, 'green', True)],
             speech=[('zh', '上场那一刻，她脑子里想的是：'),
                     ('en', 'I am the best person who has ever stepped foot here. '
                            'Nobody’s even gonna touch me. Everyone’s competing for a second.'),
                     ('zh', '，站在这儿的史上最强就是我，没人碰得到我，其他人都在争第二名。'
                            '注意这是比赛时的自我暗示，不是日常说话的语气——'
                            '她说得很清楚：这两套状态必须分开。')],
             source=(1984.30, 1989.60)),
        dict(n='19', title='alter ego / go time',
             lines=[(950, 'okay, alter ego, go time.', 40, 'green2', True),
                    (1190, '好，切换到第二自我，上场', 40, 'fg', False),
                    (1330, 'alter ego / go time', 38, 'green', True)],
             speech=[('zh', '她把这次切换叫得很具体：'),
                     ('en', 'It’s only when I compete, I’m like, okay, alter ego, go time.'),
                     ('zh', '，只有比赛的时候，我会说：好，第二自我，上。'
                            'alter ego 是「另一个我」，go time 是「该上场了」——'
                            '两个词放在一起，等于给自己按了开关。')],
             source=(2017.70, 2022.20)),
        dict(n='20', title='换你来说',
             lines=[(470, 'I keep the critic and the', 42, 'green2', True),
                    (560, 'competitor apart — that’s', 42, 'green2', True),
                    (650, 'how I make the switch.', 42, 'green2', True),
                    (870, '你可以试着这样说', 38, 'fg', False),
                    (1090, '把 critic / competitor 换成你的两种身份', 34, 'mute', False)],
             speech=[('zh', '你也可以试着这样说。'),
                     ('en', 'I keep the critic and the competitor apart — that’s how I make '
                            'the switch.'),
                     ('zh', '，我把「挑毛病的那个人」和「上场的那个人」分开——'
                            '这就是我切换的方式。把这两个身份换成你自己的。')]),
        # ---- 第 4 章 把两套状态分开 ----
        dict(n='21', title='the former … the latter',
             lines=[(950, 'I would say it’s like 95%', 40, 'green2', True),
                    (1030, 'the former and 5%', 42, 'green2', True),
                    (1110, 'the latter', 44, 'green2', True),
                    (1190, '大概 95% 是前者，5% 是后者', 36, 'fg', False),
                    (1330, 'the former … the latter', 36, 'green', True)],
             speech=[('zh', '英语里指代「前一个 / 后一个」，用 the former / the latter。'
                            '主持人问她：这两套状态（训练时的挑剔、比赛时的自信）'
                            '是不是分开的？她说 '),
                     ('en', 'I would say it’s like 95% the former and 5% the latter'),
                     ('zh', '，大概九成五是前者，百分之五是后者。'
                            '写报告、写对比段落，这两个词比 the first one 书面得多。')],
             source=(1990.80, 1996.80)),
        dict(n='22', title='protect sb from doing sth',
             lines=[(950, 'Creating that really conscious', 36, 'green2', True),
                    (1030, 'distinction is what protects me', 36, 'green2', True),
                    (1110, 'from going absolutely insane.', 34, 'green2', True),
                    (1190, '正是这种有意的区分，让我没疯掉', 32, 'fg', False),
                    (1330, 'protect sb from doing sth', 36, 'green', True)],
             speech=[('zh', '她把这件事说得挺重：'),
                     ('en', 'Creating that really conscious distinction is what protects me '
                            'from going absolutely insane.'),
                     ('zh', '，正是有意做出这个区分，才让我没彻底发疯。'
                            'protect sb from doing sth 是「让某人免于……」；'
                            'go insane / go crazy 在口语里就是「要疯了」。')],
             source=(1997.30, 2001.85)),
        dict(n='23', title='a normal amount of …',
             lines=[(950, 'I’m like a normal', 44, 'green2', True),
                    (1030, 'amount of competitive,', 42, 'green2', True),
                    (1110, 'right?', 46, 'green2', True),
                    (1190, '我的好胜心就是正常水平吧？', 38, 'fg', False),
                    (1330, 'a normal amount of + 形容词', 34, 'green', True)],
             speech=[('zh', '自嘲可以用 '),
                     ('en', 'a normal amount of + 形容词'),
                     ('zh', '。她说 I’m also not that competitive in my daily life. '
                            'I’m like a normal amount of competitive, right?，'
                            '平时我没那么好胜，就正常水平吧。'
                            '英语里 a normal amount of 后面常接各种词来自嘲，'
                            '比如 a normal amount of coffee。')],
             source=(2004.00, 2005.68)),
        dict(n='24', title='换你来说',
             lines=[(470, 'I’m a normal amount of ambitious', 40, 'green2', True),
                    (560, 'at work — and completely', 40, 'green2', True),
                    (650, 'different on game day.', 40, 'green2', True),
                    (870, '你可以试着这样说', 38, 'fg', False),
                    (1090, '正常水平 + 例外场景，这个对比很好用', 32, 'mute', False)],
             speech=[('zh', '你也可以试着这样说。'),
                     ('en', 'I’m a normal amount of ambitious at work — and completely different '
                            'on game day.'),
                     ('zh', '，上班时我的野心就是正常水平，一到大日子就完全是另一个人。'
                            '把 game day 换成你的关键时刻。')]),
        # ---- 第 5 章 后来叠加的东西 ----
        dict(n='25', title='instill sth in sb',
             lines=[(950, 'The way she instilled', 42, 'green2', True),
                    (1030, 'work ethic in me is', 42, 'green2', True),
                    (1110, 'just unparalleled.', 42, 'green2', True),
                    (1190, '她往我身上装进去的工作态度，无人能比', 32, 'fg', False),
                    (1330, 'instill sth in sb', 38, 'green', True)],
             speech=[('zh', '讲「把某种品质装进一个人身上」，用 '),
                     ('en', 'instill sth in sb'),
                     ('zh', '。她说 The way she instilled work ethic in me is just unparalleled，'
                            '她给我装进去的工作态度，没有人比得上。'
                            'instill 比 teach 更强调「慢慢渗进去」，'
                            'instill confidence in a team 也常这么说。')],
             source=(2059.20, 2063.35)),
        dict(n='26', title='layer on top of that / supercharge',
             lines=[(950, 'applying the work ethic layer', 36, 'green2', True),
                    (1030, 'on top of that totally', 38, 'green2', True),
                    (1110, 'supercharges the whole thing.', 34, 'green2', True),
                    (1190, '把工作态度叠上去，整件事就被加满了劲', 30, 'fg', False),
                    (1330, 'layer on top of / supercharge', 34, 'green', True)],
             speech=[('zh', '讲「叠加优势」，两个词都好用：'),
                     ('en', 'applying the work ethic layer on top of that totally supercharges '
                            'the whole thing'),
                     ('zh', '，在这个底子上再叠一层「肯干」，整件事就被加满了劲。'
                            'layer on top of 是「在上面再叠一层」，supercharge 是「大幅增强」，'
                            '讲组合优势时比 very good 具体得多。')],
             source=(2086.10, 2091.35)),
        dict(n='27', title='I am my own greatest project.',
             lines=[(950, 'I am my own', 48, 'green2', True),
                    (1030, 'greatest project.', 46, 'green2', True),
                    (1190, '我自己就是我最大的项目', 40, 'fg', False),
                    (1330, 'one’s own greatest project', 36, 'green', True)],
             speech=[('zh', '她在这一段里给了一句特别好的自我定义：'),
                     ('en', 'I am my own greatest project.'),
                     ('zh', '，我自己就是我最大的项目。她说我人生里没有哪个项目，'
                            '比「每天住在自己的身体里」更花时间；'
                            '所以为什么不把自己当创始人来经营？'
                            '写个人简介、做年度总结，这句都能用。')],
             source=(2112.20, 2113.95)),
        dict(n='28', title='the very best version of myself',
             lines=[(950, 'I just have to be the very', 40, 'green2', True),
                    (1030, 'best version of myself', 42, 'green2', True),
                    (1190, '我只要做到最好的那个自己', 40, 'fg', False),
                    (1330, 'the very best version of oneself', 34, 'green', True)],
             speech=[('zh', '最后她给出结论：'),
                     ('en', 'I just have to be the very best version of myself'),
                     ('zh', '，我只要做到「最好的那个自己」就行。'
                            'the very best version of yourself 是英语里最高频的励志表达之一；'
                            'very 加在最高级前是加强语气，等于「就是那个最好的」。')],
             source=(2134.40, 2137.18)),
        dict(n='29', title='换你来说',
             lines=[(470, 'I stopped comparing myself', 42, 'green2', True),
                    (560, 'to other people — I’m just', 42, 'green2', True),
                    (650, 'building the best version of me.', 38, 'green2', True),
                    (870, '你可以试着这样说', 38, 'fg', False),
                    (1090, '把 the best version of me 接上你的动作', 32, 'mute', False)],
             speech=[('zh', '你也可以试着这样说。'),
                     ('en', 'I stopped comparing myself to other people — I’m just building '
                            'the best version of me.'),
                     ('zh', '，我不再跟别人比了，我只在搭最好的那个自己。'
                            '把 building 换成你正在做的事。')]),
        # ---- 第 6 章 收尾 ----
        dict(n='30', title='带着这些点，再听一遍',
             lines=[(950, '现在再完整听一遍', 50, 'fg', False),
                    (1040, '你应该能听出更多东西了', 52, 'green', False),
                    (1210, '4 分 26 秒，21 个地道表达', 44, 'mute', False)],
             speech=[('zh', '现在带着刚才拆过的这些点，再完整听一遍这 4 分 26 秒。'
                            '这一次，你会听清她怎么把「训练的我」和「上场的我」分开，'
                            '也会听清那句 '),
                     ('en', 'I train like I’ve never won and I compete like I’ve never lost'),
                     ('zh', ' 是怎么落下来的。')],
             source=(1880.00, 2146.00)),
        dict(n='31', title='跟着读三遍',
             lines=[(470, '1. I train like I’ve never won', 40, 'green2', True),
                    (545, 'and I compete like I’ve never lost.', 36, 'green2', True),
                    (670, '2. It keeps you hungry.', 44, 'green2', True),
                    (795, '3. I am my own greatest project.', 42, 'green2', True)],
             speech=[('zh', '最后挑三句最常用的，跟着读一遍。'),
                     ('en', 'I train like I’ve never won and I compete like I’ve never lost.'),
                     ('en', 'It keeps you hungry.'),
                     ('en', 'I am my own greatest project.'),
                     ('zh', '不用追求完美，先把它说出口。')],
             tail=3.1),
        dict(n='32', title='收藏，下次上场前过一遍',
             lines=[(480, '拾句英语', 100, 'green', False),
                    (650, '四分钟，学会切换状态', 42, 'fg', False),
                    (850, '金句   I train like I’ve never won', 34, 'green2', False),
                    (925, '切换   alter ego, go time', 34, 'green2', False),
                    (1000, '定义   I’m my own greatest project', 34, 'green2', False),
                    (1200, '听懂一句，再把它说出来', 40, 'mute', False)],
             speech=[('zh', '这一期讲的是比赛心态：训练时怎么挑自己的毛病，'
                            '上场前怎么切换，以及为什么要把自己当成最大的项目。'),
                     ('zh', '先收藏，下次要上场、要交东西之前，把这三句过一遍。'
                            '拾句英语，听懂一句，再把它说出来。')]),
    ],
)


# ---- 12 严于律己不自我攻击（原片 2146.00–2419.00，273.00 秒）----
# 与 11 章的边界：11 收在「in my body, every single day.」一带（35:46），本条从 35:46 接。
# 2026-09 新片规格全用默认；口吻：练习句用邀请式（你也可以试着这样说）。
SPECS['谷爱凌_严于律己不自我攻击'] = dict(
    src='__DATA_ROOT__/小红书发帖-拾句英语/谷爱凌/谷爱凌最新全英访谈.mp4',
    cards=[
        # ---- 第 0 章 钩子 + 完整听一遍（273 秒，拆三张）----
        dict(n='01', title='对自己狠，不等于骂自己',
             lines=[(770, '跟着 4 分钟访谈学表达', 46, 'green', False),
                    (920, '批评 · 边界 · 友谊', 40, 'fg', False),
                    (1000, '20 个表达，就藏在 4 分 33 秒里', 34, 'mute', False)],
             speech=[('zh', '主持人问了一个很多人都卡住的问题：'),
                     ('en', 'you have to be critical of yourself, but you don’t have to '
                            'beat yourself up.'),
                     ('zh', '对自己要求高，和骂自己，是两件事。'
                            '在这段 4 分 33 秒里，她讲了怎么把这两件事分开，'
                            '还有她和朋友之间那个「互相挑毛病」的约定。'),
                     ('zh', '我们先完整听一遍，再一句一句拆。')]),
        dict(n='02', title='先听前 92 秒',
             lines=[(950, 'you are not your craft', 42, 'green2', True),
                    (1030, 'and that distinction is so important', 36, 'green2', True),
                    (1190, '先听前 92 秒', 42, 'fg', False),
                    (1330, '这一段在讲「你和你的作品不是一回事」', 34, 'mute', False)],
             speech=[('zh', '先听前 92 秒。她讲了什么叫「真正的抗压」，'
                            '也讲了自己怎么处理被戳到的自尊。')],
             source=(2146.00, 2238.20)),
        dict(n='03', title='再听 92 秒',
             lines=[(950, 'the greatest act of love', 42, 'green2', True),
                    (1030, 'is to give them constructive criticism', 36, 'green2', True),
                    (1190, '再听 92 秒', 42, 'fg', False),
                    (1330, '这一段讲「给建议才是真的对人好」', 34, 'mute', False)],
             speech=[('zh', '再听 92 秒。她讲了自己和朋友的 CCC 约定——'
                            '为什么「给得出建议」比「说好话」更难，也更珍贵。')],
             source=(2238.40, 2330.90)),
        dict(n='04', title='最后 88 秒',
             lines=[(950, 'that is not who I am', 44, 'green2', True),
                    (1190, '最后 88 秒', 42, 'fg', False),
                    (1330, '听完这一遍，我们就开始拆', 38, 'mute', False)],
             speech=[('zh', '最后 88 秒。她把话说到根上：批评只说到事实上，'
                            '别往「我是个什么样的人」上延伸。听完这一遍，我们就开始拆。')],
             source=(2331.00, 2419.00)),
        # ---- 第 1 章 你不是你的作品 ----
        dict(n='05', title='You are not your craft.',
             lines=[(950, 'You are not your craft.', 46, 'green2', True),
                    (1190, '你不是你的作品', 40, 'fg', False),
                    (1330, 'You are not your craft.', 38, 'green', True)],
             speech=[('zh', '这一句是整段的根：'),
                     ('en', 'You are not your craft.'),
                     ('zh', '，你不是你的作品。craft 是手艺、专业、作品；'
                            '她说这个区分太重要了，因为 '),
                     ('en', 'I can beat my craft to death and I will never die'),
                     ('zh', '，我可以把自己的作品批到死，而我永远不会死。'
                            '一句话把「评价作品」和「评价人」切开了。')],
             source=(2188.90, 2192.30)),
        dict(n='06', title='beat sth to death',
             lines=[(950, 'I can beat my craft', 44, 'green2', True),
                    (1030, 'to death and I will', 42, 'green2', True),
                    (1110, 'never die.', 46, 'green2', True),
                    (1190, '我可以把作品批到死，我自己不会死', 34, 'fg', False),
                    (1330, 'beat sth to death', 38, 'green', True)],
             speech=[('zh', 'beat something to death 本来是「把话题说烂」，'
                            '她说的是把作品反复挑毛病：'),
                     ('en', 'I can beat my craft to death and I will never die'),
                     ('zh', '。配合上一句一起记：作品可以被批，人不受影响。')],
             source=(2192.60, 2194.50)),
        dict(n='07', title='真正的抗压是什么',
             lines=[(950, 'real resilience is being able', 38, 'green2', True),
                    (1030, 'to take constructive criticism', 38, 'green2', True),
                    (1110, 'without the emotions.', 40, 'green2', True),
                    (1190, '真正的抗压，是能不带情绪地听批评', 32, 'fg', False),
                    (1330, 'Real X is being able to …', 36, 'green', True)],
             speech=[('zh', '她用 Real X is being able to … 给「抗压」下了个定义：'),
                     ('en', 'real resilience is being able to take constructive criticism '
                            'without the emotions'),
                     ('zh', '，真正的抗压，是能不带情绪地接住建设性批评。'
                            'constructive criticism 是职场高频词；'
                            'without the emotions 说的是「不掺情绪」，不是「不许有情绪」。')],
             source=(2197.80, 2203.60)),
        dict(n='08', title='bruise one’s ego',
             lines=[(950, 'instead of spending that energy', 38, 'green2', True),
                    (1030, 'to metabolize something', 38, 'green2', True),
                    (1110, 'that made my ego bruise', 36, 'green2', True),
                    (1190, '而不是把力气花在消化「自尊被戳到」这件事上', 30, 'fg', False),
                    (1330, 'metabolize sth / bruise one’s ego', 32, 'green', True)],
             speech=[('zh', '她问自己的是：我能多快把有用的部分用起来——'),
                     ('en', 'instead of spending that energy to metabolize something that '
                            'made my ego bruise'),
                     ('zh', '，而不是把那股力气花在消化「被戳到自尊」上。'
                            'metabolize 是「代谢」，这里指慢慢消化掉；'
                            'bruise one’s ego 是「挫伤自尊」。')],
             source=(2210.70, 2214.10)),
        dict(n='09', title='换你来说',
             lines=[(470, 'Take the note, drop the sting.', 42, 'green2', True),
                    (560, 'It’s about the work,', 42, 'green2', True),
                    (650, 'not about me.', 44, 'green2', True),
                    (870, '你可以试着这样说', 38, 'fg', False),
                    (1090, 'note / sting 这一对很地道', 36, 'mute', False)],
             speech=[('zh', '你也可以试着这样说。'),
                     ('en', 'Take the note, drop the sting. It’s about the work, not about me.'),
                     ('zh', '，把意见收下，把刺放下——说的是事，不是说我。'
                            'note 是「意见」，sting 是「刺」，这一对特别好用。')]),
        # ---- 第 2 章 把「耗竭」和「自我攻击」分开 ----
        dict(n='10', title='beat yourself up',
             lines=[(950, 'it sounds like you', 44, 'green2', True),
                    (1030, 'beat yourself up.', 44, 'green2', True),
                    (1190, '听起来不像是在骂自己', 40, 'fg', False),
                    (1330, 'beat yourself up', 38, 'green', True)],
             speech=[('zh', '主持人的原话是：你对自己这么严格，'),
                     ('en', 'but I don’t feel like it sounds like you beat yourself up'),
                     ('zh', '，但听起来不像是在骂自己。beat yourself up 是这段的招牌习语：'
                            '字面是「揍自己」，实际是「一个劲地责怪自己」。'
                            '它和 be critical of yourself 是两件完全不同的事。')],
             source=(2158.10, 2161.30)),
        dict(n='11', title='push so hard they break',
             lines=[(950, 'pushing themselves so hard', 40, 'green2', True),
                    (1030, 'they break', 46, 'green2', True),
                    (1190, '把自己逼到断掉', 40, 'fg', False),
                    (1330, 'so + 副词 + (that) + 结果', 36, 'green', True)],
             speech=[('zh', '他说很多人卡在中间：'),
                     ('en', 'trying to push themselves to be better and then pushing themselves '
                            'so hard they break'),
                     ('zh', '，一边想把自己逼得更好，一边把自己逼到「断了」。'
                            'so + 副词 + 结果，口语里 that 常常省掉，'
                            '直接说 so hard they break。')],
             source=(2174.50, 2178.60)),
        dict(n='12', title='burn yourself out',
             lines=[(950, 'not burn yourself out', 42, 'green2', True),
                    (1030, 'or beat yourself up', 42, 'green2', True),
                    (1190, '别把自己耗干，也别骂自己', 40, 'fg', False),
                    (1330, 'burn oneself out', 38, 'green', True)],
             speech=[('zh', '同义的一对：'),
                     ('en', 'not burn yourself out or beat yourself up'),
                     ('zh', '，别把自己耗干，也别一个劲骂自己。burn out 是「燃尽、耗竭」，'
                            '现在职场里常用来讲职业倦怠：I burned out after two years。')],
             source=(2184.80, 2188.70)),
        dict(n='13', title='换你来说',
             lines=[(470, 'I hold a high bar, but I', 42, 'green2', True),
                    (560, 'don’t beat myself up when', 42, 'green2', True),
                    (650, 'I miss it.', 44, 'green2', True),
                    (870, '你可以试着这样说', 38, 'fg', False),
                    (1090, 'high bar / beat myself up 直接可用', 34, 'mute', False)],
             speech=[('zh', '你也可以试着这样说。'),
                     ('en', 'I hold a high bar, but I don’t beat myself up when I miss it.'),
                     ('zh', '，我标准很高，但没做到的时候我不会骂自己。'
                            '把 high bar 换成你的标准。')]),
        # ---- 第 3 章 给建议才是真的对人好 ----
        dict(n='14', title='You’ll laugh at this. / CCC',
             lines=[(950, 'You’ll laugh at this.', 44, 'green2', True),
                    (1030, 'It’s called the CCC —', 42, 'green2', True),
                    (1110, 'the Constructive Criticism Circle.', 34, 'green2', True),
                    (1190, '你听了会笑：我们有个 CCC', 36, 'fg', False),
                    (1330, 'You’ll laugh at this.', 38, 'green', True)],
             speech=[('zh', '要讲一件有点离谱的事，先说 '),
                     ('en', 'You’ll laugh at this.'),
                     ('zh', '，你听了会笑。然后她讲了那个 CCC：'),
                     ('en', 'I have a practice that I do with my friends called the CCC, '
                            'it’s called the Constructive Criticism Circle.'),
                     ('zh', '，我和朋友有个固定项目叫 CCC——建设性批评圈。'
                            'practice 在这里是「习惯做法、固定项目」，不是「练习」。')],
             source=(2214.50, 2219.10)),
        dict(n='15', title='The greatest act of love …',
             lines=[(950, 'the greatest act of love', 42, 'green2', True),
                    (1030, 'you can give anybody is to give', 36, 'green2', True),
                    (1110, 'them constructive criticism', 38, 'green2', True),
                    (1190, '你能给人的最大的爱，是给出真实的建议', 30, 'fg', False),
                    (1330, 'The greatest act of love is to …', 34, 'green', True)],
             speech=[('zh', '她说：'),
                     ('en', 'the greatest act of love that you can give anybody is to give them '
                            'constructive criticism'),
                     ('zh', '，你能给一个人最大的爱，就是给他建设性的批评——'
                            '前提是你真的爱他，也足够了解他，说得出有用的建议。'
                            'The greatest X that you can give sb is to …，用来讲「什么最珍贵」很有力。')],
             source=(2219.50, 2223.90)),
        dict(n='16', title='What’s more difficult is …',
             lines=[(950, 'What’s more difficult is', 42, 'green2', True),
                    (1030, 'for me to know you', 42, 'green2', True),
                    (1110, 'well enough …', 42, 'green2', True),
                    (1190, '更难的是，我得足够了解你', 36, 'fg', False),
                    (1330, 'What’s more difficult is …', 36, 'green', True)],
             speech=[('zh', '夸人很容易，难的是真话：'),
                     ('en', 'What’s more difficult is for me to know you well enough, to know '
                            'what your goals are, what your shortcomings are'),
                     ('zh', '，更难的是我得足够了解你——知道你的目标、你的短板，'
                            '然后帮你把这两点对上，说出一句你自己都没看到、'
                            '或者还没准备好听的建议。这个句型用来推进第二层观点，'
                            '比 Secondly 自然。')],
             source=(2238.40, 2244.90)),
        dict(n='17', title='so much more meaningful / act of service',
             lines=[(950, 'that is so much more meaningful', 38, 'green2', True),
                    (1030, 'and so much more powerful.', 38, 'green2', True),
                    (1110, 'the deepest act of service', 36, 'green2', True),
                    (1190, '这要有意义得多，也强得多', 36, 'fg', False),
                    (1330, 'so much more + 形容词', 38, 'green', True)],
             speech=[('zh', '她接着说：'),
                     ('en', 'that is so much more meaningful and so much more powerful. It is like '
                            'the deepest act of service I could possibly imagine.'),
                     ('zh', '，这要有意义得多、也强得多——几乎是我能想到的、'
                            '最深的一种「服务」。so much more 加形容词，'
                            '是加强比较级最顺口的说法；act of service 是「为别人做的事」。')],
             source=(2253.70, 2260.20)),
        dict(n='18', title='换你来说',
             lines=[(470, 'The most useful thing you can', 40, 'green2', True),
                    (560, 'give a friend isn’t praise —', 40, 'green2', True),
                    (650, 'it’s the thing they can’t see.', 36, 'green2', True),
                    (870, '你可以试着这样说', 38, 'fg', False),
                    (1090, '把 praise / the thing they can’t see 换成你的版本', 30, 'mute', False)],
             speech=[('zh', '你也可以试着这样说。'),
                     ('en', 'The most useful thing you can give a friend isn’t praise — '
                            'it’s the thing they can’t see.'),
                     ('zh', '，你能给朋友最有用的东西不是夸奖，而是他自己看不见的那件事。'
                            '把 praise 换成你常给的东西。')]),
        # ---- 第 4 章 批评只说到事实上 ----
        dict(n='19', title='hold yourself to that standard',
             lines=[(950, 'you’re not very consistent with it.', 36, 'green2', True),
                    (1030, 'You’re not holding yourself', 36, 'green2', True),
                    (1110, 'to that standard.', 40, 'green2', True),
                    (1190, '你自己并没有按这个标准来', 36, 'fg', False),
                    (1330, 'hold sb to a standard / be consistent with', 30, 'green', True)],
             speech=[('zh', '她举了一个真实的例子：朋友说要做内容，'),
                     ('en', 'But you’re not very consistent with it and you’re not holding '
                            'yourself to that standard.'),
                     ('zh', '，但更新得并不稳定，也没有拿这个标准要求自己。'
                            'be consistent with 讲的是「持续做到」；'
                            'hold sb / yourself to a standard 讲的是「按这个标准要求」。'
                            '两个都是执行力话题的高频词。')],
             source=(2289.50, 2293.40)),
        dict(n='20', title='could have had a nicer tone of voice',
             lines=[(950, 'maybe you could have had', 40, 'green2', True),
                    (1030, 'a nicer tone of voice.', 40, 'green2', True),
                    (1190, '也许你当时的语气可以更好一点', 36, 'fg', False),
                    (1330, 'could have + 过去分词', 38, 'green', True)],
             speech=[('zh', '要给一句很软的建议，用 could have + 过去分词：'),
                     ('en', 'maybe you could have had a nicer tone of voice'),
                     ('zh', '，也许你当时的语气可以更好一点。'
                            '它说的是「本来可以」，不指责、也不翻旧账，'
                            '是英语里提出委婉意见的固定方式。')],
             source=(2303.10, 2304.70)),
        dict(n='21', title='things, big and small',
             lines=[(950, 'There’s so many things,', 40, 'green2', True),
                    (1030, 'big and small,', 44, 'green2', True),
                    (1110, 'that you genuinely don’t even know.', 34, 'green2', True),
                    (1190, '有很多事，大的小的，你根本不知道', 34, 'fg', False),
                    (1330, 'things, big and small', 38, 'green', True)],
             speech=[('zh', '她说这就是为什么要有人告诉你：'),
                     ('en', 'There’s so many things, big and small, that you genuinely don’t '
                            'even know.'),
                     ('zh', '，有很多事，大的小的，你自己根本不知道。'
                            'big and small 放在名词后面做后置修饰，'
                            '比 all kinds of things 更书面、也更收得住。')],
             source=(2306.60, 2310.20)),
        dict(n='22', title='It’s not about you.',
             lines=[(950, 'And it’s not about you.', 44, 'green2', True),
                    (1190, '这不是冲着你这个人来的', 40, 'fg', False),
                    (1330, 'It’s not about you.', 38, 'green', True)],
             speech=[('zh', '被批评时最该记住的一句：'),
                     ('en', 'And it’s not about you. It’s not like, oh, my ego is going to be hurt.'),
                     ('zh', '，这不是冲着你来的，不是「我的自尊要受伤了」。'
                            'it’s not about you 在英语里有两层意思：'
                            '一层是「别往自己身上想」，另一层（不太友好时）是「不关你的事」——'
                            '这里显然是前者。')],
             source=(2315.80, 2316.80)),
        dict(n='23', title='That’s the end of the sentence.',
             lines=[(950, 'It’s really bad. Like, that’s it.', 38, 'green2', True),
                    (1030, 'That’s the end of the sentence.', 38, 'green2', True),
                    (1190, '到此为止，句子就结束了', 36, 'fg', False),
                    (1330, 'That’s the end of the sentence.', 34, 'green', True)],
             speech=[('zh', '她形容自己怎么处理技术批评：这个动作很糟，'),
                     ('en', 'It’s really bad. Like, that’s it. That’s the end of the sentence.'),
                     ('zh', '，就这样，句子到这儿就结束了。后面不会再有「'
                            '这说明我是个什么样的人」。'
                            'That’s the end of the sentence 是个很好用的说法：'
                            '把话停在事实上，不再往外延伸。')],
             source=(2329.40, 2331.00)),
        dict(n='24', title='换你来说',
             lines=[(470, 'The draft is bad. That’s the', 40, 'green2', True),
                    (560, 'end of the sentence — it says', 40, 'green2', True),
                    (650, 'nothing about who I am.', 38, 'green2', True),
                    (870, '你可以试着这样说', 38, 'fg', False),
                    (1090, 'the end of the sentence 后面接你的克制', 30, 'mute', False)],
             speech=[('zh', '你也可以试着这样说。'),
                     ('en', 'The draft is bad. That’s the end of the sentence — it says nothing '
                            'about who I am.'),
                     ('zh', '，这版稿子不好，话就到此为止——它说明不了我是什么样的人。')]),
        # ---- 第 5 章 我是我，职业是职业 ----
        dict(n='25', title='That is not who I am.',
             lines=[(950, 'That is not who I am.', 46, 'green2', True),
                    (1190, '那不是我这个人', 40, 'fg', False),
                    (1330, 'That is not who I am.', 38, 'green', True)],
             speech=[('zh', '把技术问题拆完，她给自己一句话收口：'),
                     ('en', 'That is not who I am.'),
                     ('zh', '，那不是我这个人。who I am 是「我是什么样的人」；'
                            '这句话短、稳，被否定的时候能把自己接住。')],
             source=(2345.40, 2347.20)),
        dict(n='26', title='I am me and my career is my career.',
             lines=[(950, 'I am me and my', 44, 'green2', True),
                    (1030, 'career is my career.', 42, 'green2', True),
                    (1190, '我是我，我的职业是我的职业', 38, 'fg', False),
                    (1330, 'A is A and B is B', 38, 'green', True)],
             speech=[('zh', '她说很多人把这两件事混在一起：事业顺利就觉得自己很行，'
                            '事业不顺就觉得自己很失败。她的分法是：'),
                     ('en', 'I am me and my career is my career'),
                     ('zh', '，我是我，我的职业是我的职业。她还补了一句：'
                            '别人说「你滑雪真好」，她不会翻译成「你这个人真好」——'
                            'A is A and B is B，用一个重复结构把两件事分开，'
                            '讲边界时特别好用。')],
             source=(2362.00, 2363.90)),
        dict(n='27', title='换你来说',
             lines=[(470, 'The project slipped. I’m still', 40, 'green2', True),
                    (560, 'the same person I was', 40, 'green2', True),
                    (650, 'on Monday.', 44, 'green2', True),
                    (870, '你可以试着这样说', 38, 'fg', False),
                    (1090, '把 slip 换成你最近的一次失手', 34, 'mute', False)],
             speech=[('zh', '你也可以试着这样说。'),
                     ('en', 'The project slipped. I’m still the same person I was on Monday.'),
                     ('zh', '，项目黄了，我还是周一那个人。'
                            '把 slip 换成你最近的一次失手。')]),
        # ---- 第 6 章 当面说那句背后的话 ----
        dict(n='28', title='to sb’s face / behind sb’s back',
             lines=[(950, 'we have to say to each other’s face', 34, 'green2', True),
                    (1030, 'the thing we all say', 38, 'green2', True),
                    (1110, 'behind each other’s back.', 34, 'green2', True),
                    (1190, '我们得当面说出彼此背后说的那句话', 30, 'fg', False),
                    (1330, 'to sb’s face / behind sb’s back', 30, 'green', True)],
             speech=[('zh', '主持人讲了他自己的版本。他跟最好的朋友说：'),
                     ('en', 'we have to say to each other’s face the thing we all say behind '
                            'each other’s back'),
                     ('zh', '，我们得当面说出平时在背后说的那句话。'
                            'to someone’s face 是「当着面」，behind someone’s back 是「背着人」——'
                            '这一对放在一起，把「当面对质」和「背后议论」一次说清。')],
             source=(2396.80, 2403.00)),
        dict(n='29', title='换你来说',
             lines=[(470, 'Let’s say to each other’s face', 42, 'green2', True),
                    (560, 'what we’d normally say', 42, 'green2', True),
                    (650, 'behind each other’s back.', 42, 'green2', True),
                    (870, '你可以试着这样说', 38, 'fg', False),
                    (1090, '把 each other 换成你那个小圈子', 34, 'mute', False)],
             speech=[('zh', '你也可以试着这样说。'),
                     ('en', 'Let’s say to each other’s face what we’d normally say behind '
                            'each other’s back.'),
                     ('zh', '，把平时背后说的话，当面说出来。'
                            '把 each other 换成你那个小圈子。')]),
        # ---- 第 7 章 收尾 ----
        dict(n='30', title='带着这些点，再听一遍',
             lines=[(950, '现在再完整听一遍', 50, 'fg', False),
                    (1040, '你应该能听出更多东西了', 52, 'green', False),
                    (1210, '4 分 33 秒，20 个地道表达', 44, 'mute', False)],
             speech=[('zh', '现在带着刚才拆过的这些点，再完整听一遍这 4 分 33 秒。'
                            '这一次，你会听清她怎么把「挑毛病」和「骂自己」分开，'
                            '也会听清那句 '),
                     ('en', 'you are not your craft'),
                     ('zh', ' 是怎么立住的。')],
             source=(2146.00, 2419.00)),
        dict(n='31', title='跟着读三遍',
             lines=[(470, '1. You are not your craft.', 42, 'green2', True),
                    (670, '2. It’s not about you.', 44, 'green2', True),
                    (865, '3. That is not who I am.', 44, 'green2', True)],
             speech=[('zh', '最后挑三句最常用的，跟着读一遍。'),
                     ('en', 'You are not your craft.'),
                     ('en', 'It’s not about you.'),
                     ('en', 'That is not who I am.'),
                     ('zh', '不用追求完美，先把它说出口。')],
             tail=3.1),
        dict(n='32', title='收藏，下次被批评的时候过一遍',
             lines=[(480, '拾句英语', 100, 'green', False),
                    (650, '四分钟，学会接住批评', 42, 'fg', False),
                    (850, '分开   You are not your craft', 34, 'green2', False),
                    (925, '接住   take the note, drop the sting', 32, 'green2', False),
                    (1000, '收口   That is not who I am', 36, 'green2', False),
                    (1200, '听懂一句，再把它说出来', 40, 'mute', False)],
             speech=[('zh', '这一期讲的是严于律己和自我攻击的区别：'
                            '对事可以狠，对人别下嘴；批评只说到事实上。'),
                     ('zh', '先收藏，下次被批评、被退稿的时候，把这三句过一遍。'
                            '拾句英语，听懂一句，再把它说出来。')]),
    ],
)


# ---- 13 脆弱与友谊（原片 2419.00–2651.40，232.40 秒）----
# 与 12 章的边界：12 收在「And it was unbelievable.」（40:19），本条从 40:19 接。
# ⚠️ 原片 44:11（2651.6s）起是 Mazda 广告读稿（This episode is brought to you…），整段排除。
SPECS['谷爱凌_脆弱与友谊'] = dict(
    src='__DATA_ROOT__/小红书发帖-拾句英语/谷爱凌/谷爱凌最新全英访谈.mp4',
    cards=[
        # ---- 第 0 章 钩子 + 完整听一遍（232 秒，拆三张）----
        dict(n='01', title='敢说真话，才是真朋友',
             lines=[(770, '跟着 3 分钟访谈学表达', 46, 'green', False),
                    (920, '真话 · 信任 · 临场', 40, 'fg', False),
                    (1000, '21 个表达，就藏在 3 分 52 秒里', 34, 'mute', False)],
             speech=[('zh', '有一段话，把「关系能不能再往前走」说得特别清楚：'),
                     ('en', 'we actually can’t go to the next level in our relationship '
                            'if we don’t do this.'),
                     ('zh', '这个 this，指的是敢当面说真话。'
                            '在这段 3 分 52 秒里，她讲了为什么真话才是信任，'
                            '也讲了临场那一秒为什么骗不了人。'),
                     ('zh', '我们先完整听一遍，再一句一句拆。')]),
        dict(n='02', title='先听前 77 秒',
             lines=[(950, 'who really owned it', 42, 'green2', True),
                    (1030, 'put their ego aside', 42, 'green2', True),
                    (1190, '先听前 77 秒', 42, 'fg', False),
                    (1330, '这一段讲「谁真的把话接住了」', 36, 'mute', False)],
             speech=[('zh', '先听前 77 秒。主持人描述那晚的场景：'
                            '有人害怕、有人紧张，也有人真的把话接住了。')],
             source=(2419.00, 2496.00)),
        dict(n='03', title='再听 78 秒',
             lines=[(950, 'evidence over affirmation', 42, 'green2', True),
                    (1190, '再听 78 秒', 42, 'fg', False),
                    (1330, '这一段讲「证据比鼓励重要」', 38, 'mute', False)],
             speech=[('zh', '再听 78 秒。她解释了自己的一个说法：evidence over affirmation——'
                            '先看证据，再谈鼓励。')],
             source=(2496.00, 2573.60)),
        dict(n='04', title='最后 78 秒',
             lines=[(950, 'it’s game over', 46, 'green2', True),
                    (1190, '最后 78 秒', 42, 'fg', False),
                    (1330, '听完这一遍，我们就开始拆', 38, 'mute', False)],
             speech=[('zh', '最后 78 秒。她讲了临场那一秒：身体到底信不信，'
                            '上场就见分晓。听完这一遍，我们就开始拆。')],
             source=(2573.60, 2651.40)),
        # ---- 第 1 章 敢说真话的友谊 ----
        dict(n='05', title='own it',
             lines=[(950, 'who really owned it.', 44, 'green2', True),
                    (1190, '谁真的把这件事接住了', 40, 'fg', False),
                    (1330, 'own it', 40, 'green', True)],
             speech=[('zh', '主持人说那晚他看得出三种人：'),
                     ('en', 'who was scared by it, who was nervous about it, who really owned it'),
                     ('zh', '，有人被吓到、有人紧张，也有人真的把话接住了。'
                            'own 当动词是「认领、担下来」：own it 就是「这是我的问题，我认」。'
                            '比 take responsibility 更干脆，也更有担当感。')],
             source=(2419.60, 2423.90)),
        dict(n='06', title='put your ego aside',
             lines=[(950, 'put their ego aside', 42, 'green2', True),
                    (1030, 'on both ends', 44, 'green2', True),
                    (1190, '两边都放下面子', 40, 'fg', False),
                    (1330, 'put one’s ego aside', 38, 'green', True)],
             speech=[('zh', '他说能做到的人是：'),
                     ('en', 'who opened up and had the humility and put their ego aside '
                            'on both ends'),
                     ('zh', '，愿意开口、有那份谦逊，而且两边都把面子放下了。'
                            'put your ego aside 是「放下面子」；'
                            'on both ends 是「两头都是」——说真话这件事，双方都得放。')],
             source=(2424.40, 2427.80)),
        dict(n='07', title='have the vulnerability to …',
             lines=[(950, 'you also have to have', 40, 'green2', True),
                    (1030, 'vulnerability to tell someone', 36, 'green2', True),
                    (1110, 'the truth, and be humble enough to take it', 30, 'green2', True),
                    (1190, '你得敢说真话，也得谦逊到能听进去', 30, 'fg', False),
                    (1330, 'have the vulnerability to / be humble enough to', 30, 'green', True)],
             speech=[('zh', '两个结构一起记：'),
                     ('en', 'you also have to have vulnerability to tell someone the truth, '
                            'and you’ve got to be humble enough to take it yourself'),
                     ('zh', '，你得有勇气把真话说出来，还得谦逊到能自己听进去。'
                            'have the vulnerability to do＝有勇气做（敢暴露自己）；'
                            'be humble enough to do＝谦逊到能……。'
                            'give feedback / receive feedback 这两件事，各配一个结构。')],
             source=(2427.80, 2432.90)),
        dict(n='08', title='换你来说',
             lines=[(470, 'I can say the hard thing to you,', 40, 'green2', True),
                    (560, 'and I’m humble enough to', 40, 'green2', True),
                    (650, 'hear it back.', 44, 'green2', True),
                    (870, '你可以试着这样说', 38, 'fg', False),
                    (1090, '两个结构各用一次，正好成对', 34, 'mute', False)],
             speech=[('zh', '你也可以试着这样说。'),
                     ('en', 'I can say the hard thing to you, and I’m humble enough to hear '
                            'it back.'),
                     ('zh', '，我能跟你把难听的话说出来，也谦逊到能听你回来说我。'
                            '把 the hard thing 换成你一直没说出口的那件事。')]),
        # ---- 第 2 章 关系要往前走 ----
        dict(n='09', title='go to the next level',
             lines=[(950, 'we actually can’t go to', 40, 'green2', True),
                    (1030, 'the next level in our relationship', 36, 'green2', True),
                    (1110, 'if we don’t do this.', 40, 'green2', True),
                    (1190, '不做这件事，我们的关系就没法再往前走', 30, 'fg', False),
                    (1330, 'go to the next level', 38, 'green', True)],
             speech=[('zh', '她当时心里的判断是：'),
                     ('en', 'we actually can’t go to the next level in our relationship '
                            'if we don’t do this'),
                     ('zh', '，不做这件事，我们的关系就到头了，没法再上一个台阶。'
                            'go to the next level 是商务高频说法，'
                            '讲合作、讲团队、讲关系都能用。')],
             source=(2444.00, 2448.20)),
        dict(n='10', title='pretend like',
             lines=[(950, 'We all think we’re close.', 44, 'green2', True),
                    (1110, 'We all pretend like we’re close.', 40, 'green2', True),
                    (1190, '我们都以为很熟——我们只是装作很熟', 32, 'fg', False),
                    (1330, 'pretend like + 句子', 38, 'green', True)],
             speech=[('zh', '他把很多人点破了：'),
                     ('en', 'We all think we’re close. We all pretend like we’re close.'),
                     ('zh', '，我们都以为自己很熟，其实只是装作很熟。'
                            'pretend like 后面直接接句子，比 pretend to be 更口语；'
                            '这两句放在一起，落差就出来了。')],
             source=(2448.70, 2451.50)),
        dict(n='11', title='the test of actual intimacy',
             lines=[(950, 'this is the test of actual', 40, 'green2', True),
                    (1030, 'intimacy, vulnerability,', 40, 'green2', True),
                    (1110, 'and friendship', 42, 'green2', True),
                    (1190, '这才是真正亲密、袒露和友谊的考验', 32, 'fg', False),
                    (1330, 'the test of actual + 名词', 34, 'green', True)],
             speech=[('zh', '他说这才是分水岭：'),
                     ('en', 'this is the test of actual intimacy, vulnerability, and friendship '
                            'after 20 years'),
                     ('zh', '，这才是认识二十年之后，真正的亲密、袒露和友谊的考验。'
                            'the test of 后面接抽象名词并列，句子立刻上了一个档次；'
                            'intimacy 是「亲密」，vulnerability 是「敢露出软肋」。')],
             source=(2451.80, 2457.20)),
        dict(n='12', title='换你来说',
             lines=[(470, 'We call each other close,', 40, 'green2', True),
                    (560, 'but this is the test of', 40, 'green2', True),
                    (650, 'whether we really are.', 40, 'green2', True),
                    (870, '你可以试着这样说', 38, 'fg', False),
                    (1090, 'the test of 后面接你真正在意的东西', 32, 'mute', False)],
             speech=[('zh', '你也可以试着这样说。'),
                     ('en', 'We call each other close, but this is the test of whether we '
                            'really are.'),
                     ('zh', '，我们管彼此叫好朋友，但这件事才是真假的试金石。'
                            'the test of 后面接你真正在意的东西。')]),
        # ---- 第 3 章 一群人怎么做这件事 ----
        dict(n='13', title='put sb on the spot',
             lines=[(950, 'like put them on the spot,', 40, 'green2', True),
                    (1030, 'and then there’s kind of', 40, 'green2', True),
                    (1110, 'responsibility there.', 40, 'green2', True),
                    (1190, '把人架到台面上，责任就落下来了', 32, 'fg', False),
                    (1330, 'put sb on the spot', 38, 'green', True)],
             speech=[('zh', '一群人做这件事，和一对一不一样：'),
                     ('en', 'like put them on the spot, and then there’s like kind of '
                            'responsibility there'),
                     ('zh', '，把人架到台面上，责任就跟着落下来了。'
                            'put someone on the spot 是「让某人当场表态、下不来台」;'
                            '会议里被点名、面试被追问，都是 on the spot。')],
             source=(2479.00, 2481.60)),
        dict(n='14', title='foster group connections and growth',
             lines=[(950, 'truly fostering', 44, 'green2', True),
                    (1030, 'group connections and growth', 40, 'green2', True),
                    (1190, '真正在培育一群人之间的连接和成长', 32, 'fg', False),
                    (1330, 'foster sth', 38, 'green', True)],
             speech=[('zh', '他总结这件事的价值：'),
                     ('en', 'This is just like truly fostering like group connections and growth, '
                            'but so special.'),
                     ('zh', '，这才是在真正培育一群人之间的连接和成长，而且特别。'
                            'foster 是「培育、促进」，比 build 更有温度，'
                            '团队建设、文化培育都用它：foster a culture of feedback。')],
             source=(2481.90, 2487.90)),
        dict(n='15', title='换你来说',
             lines=[(470, 'Our retros foster honesty,', 40, 'green2', True),
                    (560, 'not comfort.', 44, 'green2', True),
                    (870, '你可以试着这样说', 38, 'fg', False),
                    (1090, '把 foster 用在你在意的东西上', 34, 'mute', False)],
             speech=[('zh', '你也可以试着这样说。'),
                     ('en', 'Our retros foster honesty, not comfort.'),
                     ('zh', '，我们的复盘培育的是坦诚，不是舒服。'
                            '把 retros 换成你们团队的那件事。')]),
        # ---- 第 4 章 证据比鼓励重要 ----
        dict(n='16', title='evidence over affirmation',
             lines=[(950, 'evidence over affirmation', 44, 'green2', True),
                    (1190, '证据比鼓励重要', 40, 'fg', False),
                    (1330, 'A over B（A 优于 B）', 38, 'green', True)],
             speech=[('zh', '主持人提到她以前说过的一句话：'),
                     ('en', 'you’ve said before: evidence over affirmation'),
                     ('zh', '，你说过：证据优于肯定。'
                            'A over B 这个结构一次记牢：quality over quantity、'
                            'evidence over affirmation——都是「A 比 B 重要」。')],
             source=(2493.50, 2497.40)),
        dict(n='17', title='shoot for the moon',
             lines=[(950, 'you want to shoot for the moon?', 40, 'green2', True),
                    (1030, 'Okay, how do you get there?', 40, 'green2', True),
                    (1190, '你想登月？好，那怎么去？', 36, 'fg', False),
                    (1330, 'shoot for the moon', 38, 'green', True)],
             speech=[('zh', '她解释自己怎么把大目标掰开：'),
                     ('en', 'you want to shoot for the moon? Okay, how do you get there?'),
                     ('zh', '，你想登月？好，那怎么去？谁造火箭、谁来设计、谁来供电？'
                            'shoot for the moon 就是「定一个极大的目标」；'
                            '她这套问法——先接住愿望，再追问路径——特别适合用来做规划。')],
             source=(2504.50, 2506.70)),
        dict(n='18', title='the bulk of it',
             lines=[(950, 'most of the work, the bulk of it,', 38, 'green2', True),
                    (1030, 'needs to be ready so that', 38, 'green2', True),
                    (1110, 'you have that 5%.', 40, 'green2', True),
                    (1190, '绝大部分的活儿，都要提前备好', 34, 'fg', False),
                    (1330, 'the bulk of it', 38, 'green', True)],
             speech=[('zh', '讲「绝大部分」，用 '),
                     ('en', 'the bulk of it'),
                     ('zh', '。她说 all the work, the bulk of it, needs to be ready '
                            'so that you have that 5%，绝大部分的活儿都得先备好，'
                            '才能换来最后那 5% 的临场发挥。bulk 是「大宗、主体」，'
                            '比 most of it 更书面。')],
             source=(2529.40, 2535.70)),
        dict(n='19', title='in the same vein / insofar as',
             lines=[(950, 'it’s in the same vein', 42, 'green2', True),
                    (1030, 'where you can only succeed', 40, 'green2', True),
                    (1110, 'insofar as you are prepared', 36, 'green2', True),
                    (1190, '是一个脉络：你只能在你准备好的范围内成功', 30, 'fg', False),
                    (1330, 'in the same vein / insofar as', 34, 'green', True)],
             speech=[('zh', '她把「自己造运气」和「提前准备」归到一条线上：'),
                     ('en', 'and I think it’s in the same vein where like you can only succeed '
                            'insofar as you are prepared'),
                     ('zh', '，我觉得这属于同一个脉络：你只能在「你准备好的范围内」成功。'
                            'in the same vein 是「同一脉络、同理」；'
                            'insofar as 是「在……的范围内」（偏书面，写作用得多）。')],
             source=(2535.70, 2544.70)),
        dict(n='20', title='set your own ceiling',
             lines=[(950, 'you’re kind of setting your', 40, 'green2', True),
                    (1030, 'own ceiling there with the base', 38, 'green2', True),
                    (1110, 'that you have accumulated', 38, 'green2', True),
                    (1190, '你是在用攒下的底子，给自己定天花板', 30, 'fg', False),
                    (1330, 'set one’s own ceiling', 38, 'green', True)],
             speech=[('zh', '接着她说，准备到什么程度，天花板就在哪里：'),
                     ('en', 'you’re kind of setting your own ceiling there with the base that '
                            'you have accumulated'),
                     ('zh', '，你其实是在用自己攒下的底子，给自己定天花板。'
                            'ceiling 是「上限」；底子（base）厚，天花板才高。')],
             source=(2544.90, 2549.30)),
        dict(n='21', title='换你来说',
             lines=[(470, 'I’d rather set my own ceiling', 40, 'green2', True),
                    (560, 'with preparation than have it', 40, 'green2', True),
                    (650, 'set by luck.', 44, 'green2', True),
                    (870, '你可以试着这样说', 38, 'fg', False),
                    (1090, 'rather A than B 配 set a ceiling 很顺', 32, 'mute', False)],
             speech=[('zh', '你也可以试着这样说。'),
                     ('en', 'I’d rather set my own ceiling with preparation than have it set '
                            'by luck.'),
                     ('zh', '，我宁愿用准备给自己定天花板，也不愿让运气来定。')]),
        # ---- 第 5 章 临场那一刻 ----
        dict(n='22', title='the difference between A and B is',
             lines=[(950, 'the difference between success', 40, 'green2', True),
                    (1030, 'and failure is quite literally', 38, 'green2', True),
                    (1110, 'broken bones and top of the podium', 32, 'green2', True),
                    (1190, '成功和失败的区别，literally 就是骨折和领奖台', 30, 'fg', False),
                    (1330, 'the difference between A and B is', 32, 'green', True)],
             speech=[('zh', '她讲滑雪为什么残酷：'),
                     ('en', 'the difference between success and failure is quite literally '
                            'broken bones and top of the podium'),
                     ('zh', '，成功和失败的区别，literally 就是「骨折」和「站上领奖台」。'
                            'the difference between A and B is …，讲对比最好用的框架；'
                            'quite literally 用来强调「我不是打比方」。')],
             source=(2559.70, 2564.80)),
        dict(n='23', title='had the reps / believe to my core',
             lines=[(950, 'Do I feel like I had the reps?', 40, 'green2', True),
                    (1030, 'Do I genuinely believe', 40, 'green2', True),
                    (1110, 'to my core?', 44, 'green2', True),
                    (1190, '我练够了吗？我打心底里信吗？', 34, 'fg', False),
                    (1330, 'had the reps / believe to my core', 32, 'green', True)],
             speech=[('zh', '临上场前，她问自己两个问题：'),
                     ('en', 'Do I feel like I had the reps? Do I genuinely believe to my core?'),
                     ('zh', '，我感觉自己练够次数了吗？我是打心底里相信吗？'
                            'reps 是健身里的「次数」，引申为「练的量」；'
                            'believe to my core 比 I believe 深得多——核心都信。')],
             source=(2572.30, 2575.40)),
        dict(n='24', title='buy in (all the way down)',
             lines=[(950, 'the subconscious thing of', 40, 'green2', True),
                    (1030, 'buying in all the way down', 38, 'green2', True),
                    (1110, 'to actually commit the action.', 34, 'green2', True),
                    (1190, '潜意识里真的买账，才会做出那个动作', 30, 'fg', False),
                    (1330, 'buy in / all the way down', 34, 'green', True)],
             speech=[('zh', '她说最表层的东西谁都能说服自己，难的是：'),
                     ('en', 'the subconscious thing of buying in all the way down to actually '
                            'commit the action'),
                     ('zh', '，潜意识里真正买账、一直信到底，才会真的做出那个动作。'
                            'buy in 是「认同、买账」（名词 buy-in 就是「争取支持」）；'
                            'all the way down 是「一路到底」。')],
             source=(2583.10, 2590.20)),
        dict(n='25', title='build trust over repetition and practice',
             lines=[(950, 'you can only build trust', 40, 'green2', True),
                    (1030, 'over repetition and over practice', 36, 'green2', True),
                    (1110, 'and true preparation.', 38, 'green2', True),
                    (1190, '信任只能靠重复、练习和真正的准备积累', 30, 'fg', False),
                    (1330, 'build trust over sth', 38, 'green', True)],
             speech=[('zh', '结论是：'),
                     ('en', 'you can only build trust over repetition and over practice and '
                            'true preparation'),
                     ('zh', '，信任只能靠重复、练习和真正的准备建立起来。'
                            'build trust over + 名词，是职场里讲信任最地道的搭配；'
                            'over 在这里是「通过、凭借」。')],
             source=(2590.40, 2594.10)),
        dict(n='26', title='it’s game over',
             lines=[(950, 'you just rush it a little because', 36, 'green2', True),
                    (1030, 'literally just because you’re nervous', 34, 'green2', True),
                    (1110, 'and it’s game over.', 42, 'green2', True),
                    (1190, '只是因为你紧张，抢了半拍——就完了', 30, 'fg', False),
                    (1330, 'it’s game over', 38, 'green', True)],
             speech=[('zh', '她形容临场那一秒有多狠：'),
                     ('en', 'if your timing is slightly off because you’re nervous and you rush '
                            'a trick, it’s game over'),
                     ('zh', '，如果你因为紧张、抢了半拍，动作稍微偏一点，那就完了。'
                            'it’s game over 是「结束、没救了」，'
                            '游戏里来的说法，日常讲砸了的事也很常用；'
                            'slightly off 是「稍微偏了」。')],
             source=(2632.10, 2635.90)),
        dict(n='27', title='换你来说',
             lines=[(470, 'One second of nerves and', 40, 'green2', True),
                    (560, 'it’s game over — that’s why', 40, 'green2', True),
                    (650, 'I rehearse.', 44, 'green2', True),
                    (870, '你可以试着这样说', 38, 'fg', False),
                    (1090, '把 rehearse 换成你的准备方式', 34, 'mute', False)],
             speech=[('zh', '你也可以试着这样说。'),
                     ('en', 'One second of nerves and it’s game over — that’s why I rehearse.'),
                     ('zh', '，紧张一秒就全完了——所以我每次都提前过一遍。'
                            '把 rehearse 换成你的准备方式。')]),
        # ---- 第 6 章 收尾 ----
        dict(n='28', title='At the end of the day …',
             lines=[(950, 'the results will tell you', 42, 'green2', True),
                    (1030, 'what you really believe.', 42, 'green2', True),
                    (1190, '归根到底，结果会告诉你：你到底信什么', 34, 'fg', False),
                    (1330, 'At the end of the day, …', 36, 'green', True)],
             speech=[('zh', '这一段最好的收尾：'),
                     ('en', 'At the end of the day, the results will tell you what you really '
                            'believe.'),
                     ('zh', '，归根到底，结果会告诉你，你到底相信什么。'
                            'at the end of the day 是「说到底、归根结底」；'
                            '这句话可以用来收任何一段讲「信念与行动」的话。')],
             source=(2647.60, 2651.20)),
        dict(n='29', title='带着这些点，再听一遍',
             lines=[(950, '现在再完整听一遍', 50, 'fg', False),
                    (1040, '你应该能听出更多东西了', 52, 'green', False),
                    (1210, '3 分 52 秒，21 个地道表达', 44, 'mute', False)],
             speech=[('zh', '现在带着刚才拆过的这些点，再完整听一遍这 3 分 52 秒。'
                            '这一次，你会听清他为什么说「真话才是亲密」，'
                            '也会听清那句 '),
                     ('en', 'the results will tell you what you really believe'),
                     ('zh', ' 是怎么收的。')],
             source=(2419.00, 2651.40)),
        dict(n='30', title='跟着读三遍',
             lines=[(470, '1. You can only succeed', 42, 'green2', True),
                    (545, 'insofar as you are prepared.', 38, 'green2', True),
                    (670, '2. It’s game over.', 44, 'green2', True),
                    (865, '3. The results will tell you', 40, 'green2', True),
                    (938, 'what you really believe.', 40, 'green2', True)],
             speech=[('zh', '最后挑三句最常用的，跟着读一遍。'),
                     ('en', 'You can only succeed insofar as you are prepared.'),
                     ('en', 'It’s game over.'),
                     ('en', 'The results will tell you what you really believe.'),
                     ('zh', '不用追求完美，先把它说出口。')],
             tail=3.1),
        dict(n='31', title='收藏，下次要跟人说真话前过一遍',
             lines=[(480, '拾句英语', 100, 'green', False),
                    (650, '四分钟，学会把真话说出口', 42, 'fg', False),
                    (850, '接住   own it', 36, 'green2', False),
                    (925, '关系   go to the next level', 34, 'green2', False),
                    (1000, '临场   it’s game over', 36, 'green2', False),
                    (1200, '听懂一句，再把它说出来', 40, 'mute', False)],
             speech=[('zh', '这一期讲的是脆弱和友谊：敢说真话才走得下去，'
                            '而临场那一秒，只认你平时攒下的底子。'),
                     ('zh', '先收藏，下次要跟重要的人说难听的话之前，把这三句过一遍。'
                            '拾句英语，听懂一句，再把它说出来。')]),
    ],
)


# ---- 14 滑雪技术（原片 2701.60–2964.20，262.60 秒）----
# 与 13 章的边界：13 收在「the results will tell you what you really believe.」（44:11 前），
# 中间 44:11–45:01 是 Mazda 广告（已排除），本条从 45:01 接。
# 本段剔除纯技术术语（whip physics、proprioception、G-forces 等），只留可迁移结构。
SPECS['谷爱凌_滑雪技术'] = dict(
    src='__DATA_ROOT__/小红书发帖-拾句英语/谷爱凌/谷爱凌最新全英访谈.mp4',
    cards=[
        # ---- 第 0 章 钩子 + 完整听一遍（262 秒，拆三张）----
        dict(n='01', title='容错空间有多小',
             lines=[(770, '跟着 4 分钟访谈学表达', 46, 'green', False),
                    (920, '变量 · 恐惧 · 预演', 40, 'fg', False),
                    (1000, '20 个表达，就藏在 4 分 22 秒里', 34, 'mute', False)],
             speech=[('zh', '主持人听完她的解释，说了这么一句：'),
                     ('en', 'the room for error is tiny.'),
                     ('zh', '在这段 4 分 22 秒里，她讲了自由式滑雪为什么难：'
                            '空中的时间不到一秒，身体又是所有项目里最「散」的那一种，'
                            '外面还有风、有天气。'),
                     ('zh', '我们先完整听一遍，再一句一句拆。')]),
        dict(n='02', title='先听前 88 秒',
             lines=[(950, 'the room for error is tiny', 40, 'green2', True),
                    (1190, '先听前 88 秒', 42, 'fg', False),
                    (1330, '主持人这一段的追问很值得学', 36, 'mute', False)],
             speech=[('zh', '先听前 88 秒。主持人先自谦说自己是外行，'
                            '再一步步把「到底难在哪」问出来。')],
             source=(2701.60, 2789.30)),
        dict(n='03', title='再听 88 秒',
             lines=[(950, 'I can logic my way into things', 38, 'green2', True),
                    (1190, '再听 88 秒', 42, 'fg', False),
                    (1330, '这一段讲「把恐惧分类」', 38, 'mute', False)],
             speech=[('zh', '再听 88 秒。她讲了怎么把身体里的恐惧认出来、'
                            '再一个一个处理掉。')],
             source=(2789.30, 2877.00)),
        dict(n='04', title='最后 87 秒',
             lines=[(950, 'the faster you can reconcile that', 38, 'green2', True),
                    (1190, '最后 87 秒', 42, 'fg', False),
                    (1330, '听完这一遍，我们就开始拆', 38, 'mute', False)],
             speech=[('zh', '最后 87 秒。她讲了没人做过的新动作要怎么练——'
                            '以及为什么「第一次」必须靠信任。听完这一遍，我们就开始拆。')],
             source=(2877.00, 2964.20)),
        # ---- 第 1 章 主持人怎么把话打开 ----
        dict(n='05', title='Talk to me a bit more about …',
             lines=[(950, 'Talk to me a bit more', 42, 'green2', True),
                    (1030, 'about the technicalities', 42, 'green2', True),
                    (1190, '跟我多聊聊技术层面的东西', 40, 'fg', False),
                    (1330, 'Talk to me (a bit more) about …', 34, 'green', True)],
             speech=[('zh', '主持人最标志性的追问模板：'),
                     ('en', 'Talk to me a bit more about the technicalities of free skiing'),
                     ('zh', '，跟我再多聊聊自由式滑雪的技术细节。'
                            'a bit more 是关键的软化词——比 Tell me about 更像聊天，'
                            '也让对方容易接着往下说。')],
             source=(2701.90, 2703.90)),
        dict(n='06', title='be fortunate enough to do sth',
             lines=[(950, 'I’ve been fortunate', 42, 'green2', True),
                    (1030, 'enough to sit down with …', 38, 'green2', True),
                    (1190, '我有幸跟……坐下来聊过', 40, 'fg', False),
                    (1330, 'be fortunate enough to do sth', 34, 'green', True)],
             speech=[('zh', '讲「有幸做过某事」，用 '),
                     ('en', 'be fortunate enough to do sth'),
                     ('zh', '，比 I had a chance to 更客气。他说 I’ve been fortunate enough to '
                            'sit down with Novak and talk about tennis，我有幸跟德约坐下来聊网球；'
                            'sit down with sb 就是「跟某人坐下来谈」，比 meet 正式。')],
             source=(2704.20, 2708.20)),
        dict(n='07', title='I’ve never interviewed someone who … before',
             lines=[(950, 'I’ve never interviewed', 40, 'green2', True),
                    (1030, 'someone who’s a free skier', 38, 'green2', True),
                    (1110, 'before.', 46, 'green2', True),
                    (1190, '我从来没采访过自由式滑雪的人', 36, 'fg', False),
                    (1330, '现在完成时 + before', 34, 'green', True)],
             speech=[('zh', '讲「这是我头一回」，用现在完成时加 before：'),
                     ('en', 'I’ve never interviewed someone who’s a free skier before'),
                     ('zh', '，我以前从来没采访过练自由式滑雪的人。'
                            '这比 This is my first time interviewing 自然得多，'
                            '而且把「第一次」的分量留在了 never 上。')],
             source=(2718.80, 2721.30)),
        dict(n='08', title='换你来说',
             lines=[(470, 'I’d love to hear a bit more', 40, 'green2', True),
                    (560, 'about how you actually', 40, 'green2', True),
                    (650, 'do it.', 46, 'green2', True),
                    (870, '你可以试着这样说', 38, 'fg', False),
                    (1090, '把 do it 换成你想问的那件事', 34, 'mute', False)],
             speech=[('zh', '你也可以试着这样说。'),
                     ('en', 'I’d love to hear a bit more about how you actually do it.'),
                     ('zh', '，我想再多听听你到底是怎么做的。'
                            '把 do it 换成你想问的那件事。')]),
        # ---- 第 2 章 容错空间有多小 ----
        dict(n='09', title='the room for error is tiny',
             lines=[(950, 'the room for error', 42, 'green2', True),
                    (1030, 'is tiny.', 46, 'green2', True),
                    (1190, '容错空间非常小', 40, 'fg', False),
                    (1330, 'the room for error', 38, 'green', True)],
             speech=[('zh', '讲「容错空间」，用 '),
                     ('en', 'the room for error'),
                     ('zh', '。他看到那些角度和力学之后说：the room for error is tiny，'
                            '容错空间小得可怜。做风险提示、讲项目难度时，'
                            'there’s little room for error 是职场里的标准说法。')],
             source=(2725.90, 2728.70)),
        dict(n='10', title='as a complete novice to this world',
             lines=[(950, 'as a complete novice', 40, 'green2', True),
                    (1030, 'to this world', 40, 'green2', True),
                    (1190, '作为这个圈子的门外汉', 38, 'fg', False),
                    (1330, 'as a complete novice to X', 34, 'green', True)],
             speech=[('zh', '自谦式插入语：'),
                     ('en', 'as a complete novice to this world'),
                     ('zh', '，作为这个领域的纯外行。novice 是新手、门外汉；'
                            '他说 Talk to me about something that, as a complete novice to this world, '
                            'I would be unaware of——有什么是我这个外行根本不知道的？'
                            '这句话用来请人讲细节，比 I don’t know much 更体面。')],
             source=(2732.80, 2736.70)),
        dict(n='11', title='pull sth off',
             lines=[(950, 'the amount of analytics', 38, 'green2', True),
                    (1030, 'behind pulling', 40, 'green2', True),
                    (1110, 'something like that off.', 34, 'green2', True),
                    (1190, '做成这样一件事，背后有多少分析', 30, 'fg', False),
                    (1330, 'pull sth off', 38, 'green', True)],
             speech=[('zh', '夸人「把难事做成了」，用 '),
                     ('en', 'pull sth off'),
                     ('zh', '。他说 you almost undervalue the amount of analytics behind pulling '
                            'something like that off，你几乎低估了做成这样一件事背后的分析量。'
                            'pull off 是「成功搞定（很难的事）」，夸人、夸团队都好用。')],
             source=(2750.30, 2753.20)),
        dict(n='12', title='换你来说',
             lines=[(470, 'I still don’t know how they', 40, 'green2', True),
                    (560, 'pulled that off — the timing', 40, 'green2', True),
                    (650, 'alone is wild.', 42, 'green2', True),
                    (870, '你可以试着这样说', 38, 'fg', False),
                    (1090, '把 that 换成你见过的那件难事', 34, 'mute', False)],
             speech=[('zh', '你也可以试着这样说。'),
                     ('en', 'I still don’t know how they pulled that off — the timing alone '
                            'is wild.'),
                     ('zh', '，我到现在都想不通他们是怎么做成的——光那个时机就很野。')]),
        # ---- 第 3 章 恐惧要分类 ----
        dict(n='13', title='a sense of betrayal',
             lines=[(950, 'there is this almost', 40, 'green2', True),
                    (1030, 'sense of betrayal', 42, 'green2', True),
                    (1190, '会有一种被背叛的感觉', 38, 'fg', False),
                    (1330, 'a sense of betrayal / betray sb', 32, 'green', True)],
             speech=[('zh', '她形容最后一刻没做动作的那种感觉：'),
                     ('en', 'there is this almost sense of betrayal that happens in that moment'),
                     ('zh', '，那一刻会有一种几乎像被背叛的感觉——'
                            '她说的是 why is my body betraying me？我的身体怎么不听我的了。'
                            '「身体不听使唤」英语里就常说 one’s body betrays sb。')],
             source=(2779.60, 2782.70)),
        dict(n='14', title='identify the kinds of fear that you have',
             lines=[(950, 'identifying the kinds', 40, 'green2', True),
                    (1030, 'of fear that you have', 40, 'green2', True),
                    (1190, '把自己有哪几种恐惧认出来', 36, 'fg', False),
                    (1330, 'identify the kinds of … that you have', 32, 'green', True)],
             speech=[('zh', '她处理恐惧的第一步是分类：'),
                     ('en', 'so much of it is identifying the kinds of fear that you have'),
                     ('zh', '，很大一部分工作，就是把自己有哪几种恐惧认出来。'
                            'identify the kinds of + 名词 + that you have，'
                            '换成焦虑、动机、顾虑都能套——先把清单列出来，再一个个处理。')],
             source=(2785.90, 2789.30)),
        dict(n='15', title='logic my way into things',
             lines=[(950, 'I can logic my way', 42, 'green2', True),
                    (1030, 'into things', 42, 'green2', True),
                    (1190, '我能靠推理把自己说通', 40, 'fg', False),
                    (1330, '动词 + one’s way into sth', 34, 'green', True)],
             speech=[('zh', '很出彩的一个构式：动词加 one’s way into something。'
                            '她说 I can logic my way into things，'
                            '我能一步一步推理，把自己说进这件事里。'
                            '同一个构式还能说 talk my way into a meeting、work my way into a role。')],
             source=(2789.90, 2792.00)),
        dict(n='16', title='the difference between A and B',
             lines=[(950, 'discerning that often is', 38, 'green2', True),
                    (1030, 'the difference between', 40, 'green2', True),
                    (1110, 'injury and success.', 40, 'green2', True),
                    (1190, '分得清这些，往往就是受伤和成功的差别', 30, 'fg', False),
                    (1330, 'A is the difference between X and Y', 30, 'green', True)],
             speech=[('zh', '她把「分辨」说成生死的分界线：'),
                     ('en', 'discerning that often is the difference between injury and success'),
                     ('zh', '，能不能分清这些，往往就是受伤和成功的区别。'
                            '很实用的一句框架：A is the difference between X and Y。')],
             source=(2797.00, 2800.60)),
        dict(n='17', title='换你来说',
             lines=[(470, 'Naming the fear is often the', 40, 'green2', True),
                    (560, 'difference between freezing', 40, 'green2', True),
                    (650, 'and moving.', 44, 'green2', True),
                    (870, '你可以试着这样说', 38, 'fg', False),
                    (1090, '把 fear 换成你常卡住的那种情绪', 34, 'mute', False)],
             speech=[('zh', '你也可以试着这样说。'),
                     ('en', 'Naming the fear is often the difference between freezing and moving.'),
                     ('zh', '，把恐惧叫出名字，往往就是「僵住」和「动起来」的区别。')]),
        # ---- 第 4 章 层层加码的变量 ----
        dict(n='18', title='as far as … goes',
             lines=[(950, 'As far as mechanics go,', 40, 'green2', True),
                    (1030, 'this is kind of interesting', 38, 'green2', True),
                    (1190, '就力学而言，这里有点意思', 38, 'fg', False),
                    (1330, 'As far as … goes,', 38, 'green', True)],
             speech=[('zh', '限定讨论范围，用 '),
                     ('en', 'as far as … goes'),
                     ('zh', '。她说 As far as mechanics go, this is kind of interesting，'
                            '单说力学这一块，这个挺有意思。'
                            '开会时用它划定范围（as far as timing goes…），'
                            '比 about 精确，也不容易跑题。')],
             source=(2801.10, 2802.90)),
        dict(n='19', title='On top of that',
             lines=[(950, 'On top of that, it’s', 40, 'green2', True),
                    (1030, 'an outdoor sport', 42, 'green2', True),
                    (1190, '在这之上，它还是户外项目', 38, 'fg', False),
                    (1330, 'On top of that,', 38, 'green', True)],
             speech=[('zh', '层层加码地补理由，用 '),
                     ('en', 'On top of that'),
                     ('zh', '。她说 On top of that, it’s an outdoor sport, so wind impacts you more，'
                            '除此之外它还是户外项目，风对你的影响更大。'
                            '比 besides 更有「一条压一条」的推进感——讲风险、讲难点时特别好用。')],
             source=(2829.40, 2833.10)),
        dict(n='20', title='be hyper aware of / work against sb',
             lines=[(950, 'I had to be so hyper', 38, 'green2', True),
                    (1030, 'aware of these factors', 38, 'green2', True),
                    (1110, 'that were working against me', 34, 'green2', True),
                    (1190, '我得对那种一开始就对我不利的因素高度警觉', 30, 'fg', False),
                    (1330, 'be hyper aware of / work against sb', 28, 'green', True)],
             speech=[('zh', '两个搭配一起记：'),
                     ('en', 'I had to kind of be so hyper aware of these factors that were '
                            'initially working against me'),
                     ('zh', '，我得对那种一开始就对我环境不利的因素高度警觉。'
                            'hyper aware of 是「高度留意」；work against sb 是「对某人不利」。')],
             source=(2842.60, 2847.90)),
        dict(n='21', title='换你来说',
             lines=[(470, 'I’m hyper aware of anything', 40, 'green2', True),
                    (560, 'working against the deadline.', 38, 'green2', True),
                    (870, '你可以试着这样说', 38, 'fg', False),
                    (1090, '把 deadline 换成你的那道坎', 34, 'mute', False)],
             speech=[('zh', '你也可以试着这样说。'),
                     ('en', 'I’m hyper aware of anything working against the deadline.'),
                     ('zh', '，任何对进度不利的因素我都会格外注意。')]),
        # ---- 第 5 章 为什么长鞭子更有力 ----
        dict(n='22', title='the + 比较级 …, the + 比较级 …',
             lines=[(950, 'the longer the whip is,', 38, 'green2', True),
                    (1030, 'the more force is generated', 36, 'green2', True),
                    (1110, 'at the very tip.', 40, 'green2', True),
                    (1190, '鞭子越长，末端的力越大', 34, 'fg', False),
                    (1330, 'the + 比较级 …, the + 比较级 …', 32, 'green', True)],
             speech=[('zh', '她打了个比方：'),
                     ('en', 'the longer the whip is, the more force is generated at the very tip'),
                     ('zh', '，鞭子越长，末端生成的力越大。'
                            '这正好是 the + 比较级 …, the + 比较级 … 的范例；'
                            '「打个比方再解释」也是她讲技术时最常用的一招。')],
             source=(2851.00, 2856.00)),
        dict(n='23', title='get the timing right',
             lines=[(950, 'if I can get', 42, 'green2', True),
                    (1030, 'the timing right,', 42, 'green2', True),
                    (1110, 'technically I can generate more force.', 30, 'green2', True),
                    (1190, '只要时机对了，理论上我就能出更大的力', 30, 'fg', False),
                    (1330, 'get sth right', 38, 'green', True)],
             speech=[('zh', '讲「把某件事做准」，用 '),
                     ('en', 'get sth right'),
                     ('zh', '。她说 if I can get the timing right, technically I can generate '
                            'more force，只要时机拿准，理论上我就能出更大的力。'
                            'get the timing right / get the numbers right，'
                            '比 do it correctly 自然得多。')],
             source=(2856.90, 2861.30)),
        dict(n='24', title='visualize in four angles',
             lines=[(950, 'when I visualize,', 40, 'green2', True),
                    (1030, 'I visualize in four', 40, 'green2', True),
                    (1110, 'angles or dimensions.', 36, 'green2', True),
                    (1190, '我预演的时候，会从四个角度看', 34, 'fg', False),
                    (1330, 'visualize in + 角度/维度', 34, 'green', True)],
             speech=[('zh', '讲「在脑子里预演」，用 '),
                     ('en', 'visualize'),
                     ('zh', '。她说 When I visualize, I visualize in four angles or dimensions，'
                            '我预演的时候会从四个角度、四个维度去看：跟拍、看台、自己的视角，'
                            '再加慢动作。同一个动词重复一遍，是在强调这件事的分量。')],
             source=(2875.70, 2879.00)),
        dict(n='25', title='换你来说',
             lines=[(470, 'Before the call I visualize it', 40, 'green2', True),
                    (560, 'in three angles, then', 40, 'green2', True),
                    (650, 'I stop thinking.', 42, 'green2', True),
                    (870, '你可以试着这样说', 38, 'fg', False),
                    (1090, '把 three angles 换成你的预演方式', 32, 'mute', False)],
             speech=[('zh', '你也可以试着这样说。'),
                     ('en', 'Before the call I visualize it in three angles, then I stop thinking.'),
                     ('zh', '，上会之前我会从三个角度预演一遍，然后就停止思考。')]),
        # ---- 第 6 章 没人做过的事 ----
        dict(n='26', title='something kind of counterintuitive',
             lines=[(950, 'there’s something kind of', 40, 'green2', True),
                    (1030, 'counterintuitive about that.', 34, 'green2', True),
                    (1190, '这里有点反直觉', 40, 'fg', False),
                    (1330, 'something counterintuitive about sth', 30, 'green', True)],
             speech=[('zh', '引出「听起来不合理、但成立」的观点，用 '),
                     ('en', 'something kind of counterintuitive'),
                     ('zh', '。她说 there’s something kind of counterintuitive about that，'
                            '这里面有点反直觉的地方——越是看不见，越得靠信任。')],
             source=(2915.40, 2917.90)),
        dict(n='27', title='the faster you can reconcile that',
             lines=[(950, 'the faster you can', 42, 'green2', True),
                    (1030, 'reconcile that, that’s', 38, 'green2', True),
                    (1110, 'what makes a trick safe.', 34, 'green2', True),
                    (1190, '你消化得越快，动作就越安全', 34, 'fg', False),
                    (1330, 'reconcile sth', 38, 'green', True)],
             speech=[('zh', 'reconcile 是「调和、消化（矛盾的东西）」。'
                            '她说 '),
                     ('en', 'the faster you can reconcile that, that’s what makes a trick safe'),
                     ('zh', '，你越快消化掉这种反直觉，动作就越安全。'
                            '职场里也常说 reconcile 两套说法、两种立场：'
                            'reconcile the two views。')],
             source=(2918.00, 2921.00)),
        dict(n='28', title='be the first woman to ever do a trick',
             lines=[(950, 'sometimes I’m the first woman', 34, 'green2', True),
                    (1030, 'to ever do a trick.', 38, 'green2', True),
                    (1190, '有时候我是第一个做出某个动作的女性', 32, 'fg', False),
                    (1330, 'the first (sb) to ever do sth', 32, 'green', True)],
             speech=[('zh', '里程碑式表达：'),
                     ('en', 'sometimes I’m the first woman to ever do a trick'),
                     ('zh', '，有时候我是第一个做出某个动作的女性。'
                            'the first to ever do sth 比 the first one who did 更有分量，'
                            '写履历、写介绍时很好用。')],
             source=(2936.20, 2938.10)),
        dict(n='29', title='innovate on my own',
             lines=[(950, 'what I have to', 42, 'green2', True),
                    (1030, 'innovate almost', 42, 'green2', True),
                    (1110, 'on my own.', 44, 'green2', True),
                    (1190, '有些东西只能我自己摸索', 38, 'fg', False),
                    (1330, 'innovate on one’s own', 36, 'green', True)],
             speech=[('zh', '她讲怎么从男选手的视频里学：'),
                     ('en', 'what points I can kind of take and what I have to innovate almost '
                            'on my own'),
                     ('zh', '，哪些能直接拿来，哪些只能我自己摸索创新。'
                            'innovate on one’s own 是「独立摸索」，'
                            '和 take what I can 放在一起，正是学习的两条腿。')],
             source=(2949.40, 2952.40)),
        dict(n='30', title='换你来说',
             lines=[(470, 'There’s no playbook for this,', 40, 'green2', True),
                    (560, 'so I have to innovate', 40, 'green2', True),
                    (650, 'on my own.', 44, 'green2', True),
                    (870, '你可以试着这样说', 38, 'fg', False),
                    (1090, '把 playbook 换成你缺的那本手册', 34, 'mute', False)],
             speech=[('zh', '你也可以试着这样说。'),
                     ('en', 'There’s no playbook for this, so I have to innovate on my own.'),
                     ('zh', '，这件事没有现成手册，只能我自己摸索。')]),
        # ---- 第 7 章 收尾 ----
        dict(n='31', title='带着这些点，再听一遍',
             lines=[(950, '现在再完整听一遍', 50, 'fg', False),
                    (1040, '你应该能听出更多东西了', 52, 'green', False),
                    (1210, '4 分 22 秒，20 个地道表达', 44, 'mute', False)],
             speech=[('zh', '现在带着刚才拆过的这些点，再完整听一遍这 4 分 22 秒。'
                            '这一次，你会听清她怎么把恐惧分类，也会听清那句 '),
                     ('en', 'the room for error is tiny'),
                     ('zh', ' 是怎么来的。')],
             source=(2701.60, 2964.20)),
        dict(n='32', title='跟着读三遍',
             lines=[(470, '1. The room for error is tiny.', 42, 'green2', True),
                    (670, '2. On top of that, it’s an outdoor sport.', 38, 'green2', True),
                    (865, '3. The faster you can reconcile that,', 36, 'green2', True),
                    (938, 'the safer the trick is.', 40, 'green2', True)],
             speech=[('zh', '最后挑三句最常用的，跟着读一遍。'),
                     ('en', 'The room for error is tiny.'),
                     ('en', 'On top of that, it’s an outdoor sport.'),
                     ('en', 'The faster you can reconcile that, the safer the trick is.'),
                     ('zh', '不用追求完美，先把它说出口。')],
             tail=3.1),
        dict(n='33', title='收藏，下次要讲难度的时候过一遍',
             lines=[(480, '拾句英语', 100, 'green', False),
                    (650, '四分钟，学会讲清「有多难」', 42, 'fg', False),
                    (850, '容错   the room for error is tiny', 32, 'green2', False),
                    (925, '加码   On top of that, …', 34, 'green2', False),
                    (1000, '拆解   identify the kinds of fear', 32, 'green2', False),
                    (1200, '听懂一句，再把它说出来', 40, 'mute', False)],
             speech=[('zh', '这一期讲的是「这件事有多难」：容错空间小在哪，'
                            '变量怎么一层层加上去，以及恐惧要怎么分类处理。'),
                     ('zh', '先收藏，下次要跟人解释你手上的活为什么难，把这三句过一遍。'
                            '拾句英语，听懂一句，再把它说出来。')]),
    ],
)


# ---- 15 冬奥夺金（原片 2964.20–3285.20，321.00 秒）----
# 与 14 章的边界：14 收在「helps a lot.」（49:24），本条从 49:24 接。
# 这一章是「三个项目一起打」的赛程复盘 + 那块金牌当天到底怎么发生的。
SPECS['谷爱凌_冬奥夺金'] = dict(
    src='__DATA_ROOT__/小红书发帖-拾句英语/谷爱凌/谷爱凌最新全英访谈.mp4',
    cards=[
        # ---- 第 0 章 钩子 + 完整听一遍（321 秒，拆四张）----
        dict(n='01', title='她怎么把自己敲醒',
             lines=[(770, '跟着 5 分钟访谈学表达', 46, 'green', False),
                    (920, '赛程 · 低谷 · 找回状态', 40, 'fg', False),
                    (1000, '20 个表达，就藏在 5 分 21 秒里', 34, 'mute', False)],
             speech=[('zh', '主持人问了一个很妙的问题：'),
                     ('en', 'When is the last time you felt like genuine fear?'),
                     ('zh', '在这段 5 分 21 秒里，她复盘了那块金牌当天到底怎么发生的：'
                            '三个项目一起打、训练被取消、第一轮就摔到 last，'
                            '最后又是怎么把自己找回来的。'),
                     ('zh', '我们先完整听一遍，再一句一句拆。')]),
        dict(n='02', title='先听前 80 秒',
             lines=[(950, 'Walk me through the euphoria', 40, 'green2', True),
                    (1190, '先听前 80 秒', 42, 'fg', False),
                    (1330, '主持人这三种问法都值得抄下来', 34, 'mute', False)],
             speech=[('zh', '先听前 80 秒。主持人先用一个「你上次感到真正的恐惧是什么时候」'
                            '把话题打开，再请她一步步讲当时的感受。')],
             source=(2964.20, 3044.00)),
        dict(n='03', title='再听 80 秒',
             lines=[(950, 'the highest highs and the lowest lows', 34, 'green2', True),
                    (1190, '再听 80 秒', 42, 'fg', False),
                    (1330, '这一段讲「那两周是什么感觉」', 36, 'mute', False)],
             speech=[('zh', '再听 80 秒。她讲了那两周的身心负荷：'
                            '每天都在人生最高点和最低点之间来回。')],
             source=(3044.00, 3124.00)),
        dict(n='04', title='再听 80 秒',
             lines=[(950, 'holding on by a thread', 42, 'green2', True),
                    (1190, '再听 80 秒', 42, 'fg', False),
                    (1330, '这一段讲「赛程有多离谱」', 38, 'mute', False)],
             speech=[('zh', '再听 80 秒。赛程被取消、改到第二天，'
                            '她带着一身的疲惫和心事上场，第一轮又摔了。')],
             source=(3124.00, 3204.00)),
        dict(n='05', title='最后 81 秒',
             lines=[(950, 'it just clicks', 46, 'green2', True),
                    (1190, '最后 81 秒', 42, 'fg', False),
                    (1330, '听完这一遍，我们就开始拆', 38, 'mute', False)],
             speech=[('zh', '最后 81 秒。她讲了怎么把自己找回来——'
                            '对着墙角跑、假动作捶墙，然后某一刻突然就通了。'
                            '听完这一遍，我们就开始拆。')],
             source=(3204.00, 3285.20)),
        # ---- 第 1 章 主持人怎么把情绪问出来 ----
        dict(n='06', title='When is the last time you felt …?',
             lines=[(950, 'When is the last time', 42, 'green2', True),
                    (1030, 'you felt like genuine fear?', 38, 'green2', True),
                    (1190, '你上次感到真正的恐惧是什么时候？', 34, 'fg', False),
                    (1330, 'When is the last time you felt …?', 32, 'green', True)],
             speech=[('zh', '把话题从「事实」拉到「感受」，用这一句：'),
                     ('en', 'When is the last time you felt like genuine fear?'),
                     ('zh', '，你上一次感到真正的恐惧是什么时候？'
                            '访谈、团建、写作开头都能用——'
                            '它逼着对方去调一段具体的记忆，而不是给你一个概括。')],
             source=(2968.00, 2970.50)),
        dict(n='07', title='struggle to think of',
             lines=[(950, 'a lot of people would', 40, 'green2', True),
                    (1030, 'struggle to think of', 40, 'green2', True),
                    (1110, 'the last time.', 44, 'green2', True),
                    (1190, '很多人可能想不起上一次是什么时候', 32, 'fg', False),
                    (1330, 'struggle to do sth', 38, 'green', True)],
             speech=[('zh', '讲「很难做到／想不起来」，用 '),
                     ('en', 'struggle to do sth'),
                     ('zh', '，比 can’t 委婉，也更有画面。他说 I think a lot of people would '
                            'struggle to think of the last time，很多人恐怕想不起上一次是什么时候——'
                            '这句一垫，后面的反差才有劲。')],
             source=(2970.90, 2974.10)),
        dict(n='08', title='Walk me through …',
             lines=[(950, 'Walk me through', 44, 'green2', True),
                    (1030, 'the euphoria you felt.', 40, 'green2', True),
                    (1190, '带我一步步过一遍当时的感受', 36, 'fg', False),
                    (1330, 'Walk me through sth', 38, 'green', True)],
             speech=[('zh', '访谈、面试、复盘的标准模板：'),
                     ('en', 'Walk me through the euphoria you felt.'),
                     ('zh', '，带我一步步过一遍你当时的兴奋。'
                            'walk sb through 是「带着某人走一遍流程」，'
                            '比 Tell me about 更能要到细节，也更像在引导对方回忆。')],
             source=(2988.20, 2990.50)),
        dict(n='09', title='contextualize that moment',
             lines=[(950, 'it’s really important to', 40, 'green2', True),
                    (1030, 'contextualize that moment', 38, 'green2', True),
                    (1190, '把那个瞬间放到背景里讲清楚', 36, 'fg', False),
                    (1330, 'contextualize sth', 38, 'green', True)],
             speech=[('zh', '她先说了一句：'),
                     ('en', 'I think it’s really important to contextualize that moment actually'),
                     ('zh', '，我觉得得先把那个时刻放回背景里讲，才有意义。'
                            'contextualize 是「把……放到上下文里」，'
                            '汇报、写复盘时用它能显得很专业；接下来她就讲了自己要打三个项目。')],
             source=(2998.70, 3001.40)),
        dict(n='10', title='换你来说',
             lines=[(470, 'Walk me through how the week', 40, 'green2', True),
                    (560, 'actually went — I want the', 40, 'green2', True),
                    (650, 'details, not the summary.', 40, 'green2', True),
                    (870, '你可以试着这样说', 38, 'fg', False),
                    (1090, '把 the week 换成你想追问的那件事', 32, 'mute', False)],
             speech=[('zh', '你也可以试着这样说。'),
                     ('en', 'Walk me through how the week actually went — I want the details, '
                            'not the summary.'),
                     ('zh', '，把这一周到底怎么过的讲一遍——我要细节，不要总结。')]),
        # ---- 第 2 章 那两周是什么感觉 ----
        dict(n='11', title='the highest highs and the lowest lows',
             lines=[(950, 'the highest highs and', 40, 'green2', True),
                    (1030, 'the lowest lows', 42, 'green2', True),
                    (1190, '人生最高点和最低点', 40, 'fg', False),
                    (1330, 'the highest highs and the lowest lows', 30, 'green', True)],
             speech=[('zh', '形容情绪起伏，用一对最高级：'),
                     ('en', 'you’re literally having like the highest highs and the lowest lows '
                            'of your life every day for two weeks'),
                     ('zh', '，那两周里，你每天都在经历人生最高点和最低点。'
                            '比 up and down 强烈得多；literally 在这里是「真不是夸张」。')],
             source=(3025.10, 3029.50)),
        dict(n='12', title='manage so much load',
             lines=[(950, 'you’re managing', 42, 'green2', True),
                    (1030, 'so much load', 42, 'green2', True),
                    (1190, '你要扛的负荷太多了', 40, 'fg', False),
                    (1330, 'manage so much load', 38, 'green', True)],
             speech=[('zh', '讲压力和排期，用 load：'),
                     ('en', 'everything is kind of just different and foreign and you’re managing '
                            'so much load'),
                     ('zh', '，周围一切都是陌生的，而你要扛的负荷太多了。'
                            'load 是「负荷、工作量」，比 pressure 具体；'
                            '职场里 mental load（心智负担）也是这组词。')],
             source=(3033.80, 3037.70)),
        dict(n='13', title='miss out on sth',
             lines=[(950, 'I actually missed out', 40, 'green2', True),
                    (1030, 'on a training', 42, 'green2', True),
                    (1110, 'in half pipe.', 42, 'green2', True),
                    (1190, '我少上了一次训练', 38, 'fg', False),
                    (1330, 'miss out on sth', 38, 'green', True)],
             speech=[('zh', '讲「错过」，用 '),
                     ('en', 'miss out on sth'),
                     ('zh', '。她说 I actually missed out on a training in half pipe，'
                            '我少上了一次 U 型池的训练。'
                            '前面还有个结构：ended up medaling in Big Air，'
                            'end up + 动名词＝最后竟然……，讲意外结果特别好用。')],
             source=(3056.10, 3058.50)),
        dict(n='14', title='换你来说',
             lines=[(470, 'I ended up missing out on', 40, 'green2', True),
                    (560, 'the one session I needed', 40, 'green2', True),
                    (650, 'most.', 46, 'green2', True),
                    (870, '你可以试着这样说', 38, 'fg', False),
                    (1090, '把 session 换成你错过的那个机会', 32, 'mute', False)],
             speech=[('zh', '你也可以试着这样说。'),
                     ('en', 'I ended up missing out on the one session I needed most.'),
                     ('zh', '，最后偏偏错过了我最需要的那一次。')]),
        # ---- 第 3 章 离谱的赛程 ----
        dict(n='15', title='What’s even crazier is …',
             lines=[(950, 'What’s even crazier', 40, 'green2', True),
                    (1030, 'is they said, …', 40, 'green2', True),
                    (1190, '更离谱的是，他们说……', 38, 'fg', False),
                    (1330, 'What’s even crazier is …', 34, 'green', True)],
             speech=[('zh', '叙述层层加码，用 '),
                     ('en', 'What’s even crazier is …'),
                     ('zh', '，更离谱的是……。她说 What’s even crazier is they said, '
                            'if we can’t do it, we’re just gonna take qualifier results，'
                            '更离谱的是，他们说如果办不了，就直接拿资格赛成绩算。'
                            '比 moreover 生动，讲故事特别抓人。')],
             source=(3087.90, 3092.70)),
        dict(n='16', title='lose my mind',
             lines=[(950, 'I was just like', 42, 'green2', True),
                    (1030, 'losing my mind', 42, 'green2', True),
                    (1190, '我真的要疯了', 40, 'fg', False),
                    (1330, 'lose one’s mind', 38, 'green', True)],
             speech=[('zh', '口语里的夸张说法：'),
                     ('en', 'I was just like losing my mind because I was already so tired'),
                     ('zh', '，我当时真的要疯了，因为已经累得不行。'
                            'lose one’s mind 在这里是「快被逼疯了」，'
                            '不是字面上的「精神失常」——语气夸张，用的时候注意场合。')],
             source=(3101.10, 3104.20)),
        dict(n='17', title='frazzled',
             lines=[(950, 'I’m going into this', 42, 'green2', True),
                    (1030, 'contest very frazzled.', 40, 'green2', True),
                    (1190, '我是心力交瘁地走上赛场的', 36, 'fg', False),
                    (1330, 'frazzled', 40, 'green', True)],
             speech=[('zh', '一个比 tired 精准得多的形容词：'),
                     ('en', 'So I’m going into this contest very frazzled.'),
                     ('zh', '，我就是心力交瘁地走上这个赛场的。'
                            'frazzled 说的是「被折腾得心烦意乱、脑子发毛」的状态，'
                            '跟单纯的累不一样——熬了几个通宵的那种感觉。')],
             source=(3115.10, 3117.80)),
        dict(n='18', title='hold on by a thread',
             lines=[(950, 'I am just really', 42, 'green2', True),
                    (1030, 'holding on', 44, 'green2', True),
                    (1110, 'by a thread.', 44, 'green2', True),
                    (1190, '我只是勉强撑着', 40, 'fg', False),
                    (1330, 'hold on by a thread', 38, 'green', True)],
             speech=[('zh', '形容「勉强撑着、命悬一线」，用 '),
                     ('en', 'hold on by a thread'),
                     ('zh', '。她说 I am not in peak form. I am just really holding on by a thread，'
                            '我根本不在巅峰状态，就是勉强撑着。'
                            'thread 是一根线——全靠一根线挂着，形象度极高。')],
             source=(3118.40, 3121.90)),
        dict(n='19', title='换你来说',
             lines=[(470, 'By Friday I was holding on', 40, 'green2', True),
                    (560, 'by a thread — I hadn’t', 40, 'green2', True),
                    (650, 'slept properly all week.', 38, 'green2', True),
                    (870, '你可以试着这样说', 38, 'fg', False),
                    (1090, '把 Friday 换成你最崩的那天', 34, 'mute', False)],
             speech=[('zh', '你也可以试着这样说。'),
                     ('en', 'By Friday I was holding on by a thread — I hadn’t slept properly '
                            'all week.'),
                     ('zh', '，到周五我已经全靠一根线撑着了——整周都没好好睡。')]),
        # ---- 第 4 章 被敲醒 ----
        dict(n='20', title='jolt sb into sth',
             lines=[(950, 'to be like, okay, I’m here', 36, 'green2', True),
                    (1030, 'and like jolt me', 40, 'green2', True),
                    (1110, 'into reality', 42, 'green2', True),
                    (1190, '让我醒过来、意识到「我在这儿」', 32, 'fg', False),
                    (1330, 'jolt sb into sth', 38, 'green', True)],
             speech=[('zh', '她解释自己为什么会摔：'),
                     ('en', 'I needed something so harsh that my body to be like, you’re actually '
                            'here… and like jolt me into reality'),
                     ('zh', '，我需要一个足够狠的东西，把我的身体敲醒，让我意识到「你真的在这儿」。'
                            'jolt 是「猛击、电一下」；jolt sb into reality 就是「一下被敲回现实」，'
                            '换个说法还能说 jolt sb out of complacency。')],
             source=(3145.00, 3148.70)),
        dict(n='21', title='Needless to say, …',
             lines=[(950, 'Needless to say,', 44, 'green2', True),
                    (1030, 'I fall on my first run', 38, 'green2', True),
                    (1110, 'and now I’m in last.', 38, 'green2', True),
                    (1190, '不用说，第一轮我就摔了，直接垫底', 30, 'fg', False),
                    (1330, 'Needless to say, …', 38, 'green', True)],
             speech=[('zh', '叙述转折时最好的话语标记：'),
                     ('en', 'Needless to say, I fall on my first run and now I’m in last.'),
                     ('zh', '，不用说，第一轮我就摔了，现在排在最后一名。'
                            'needless to say 相当于「可想而知」，'
                            '把前因后果省掉，直接把结果甩出来。')],
             source=(3153.60, 3158.10)),
        dict(n='22', title='not bode well for sb',
             lines=[(950, 'This is not', 44, 'green2', True),
                    (1030, 'boding well for me.', 40, 'green2', True),
                    (1190, '这对我来说不是个好兆头', 40, 'fg', False),
                    (1330, 'not bode well for sb', 36, 'green', True)],
             speech=[('zh', '讲「不是好兆头」，用 '),
                     ('en', 'not bode well for sb'),
                     ('zh', '。她说 This is not boding well for me，这对我来说可不是好兆头。'
                            'bode 是「预示」——她的原话是现在进行时，'
                            '正式写作里更常用 it doesn’t bode well for the plan。')],
             source=(3174.10, 3175.40)),
        dict(n='23', title='换你来说',
             lines=[(470, 'Two cancellations in a row —', 40, 'green2', True),
                    (560, 'that doesn’t bode well', 40, 'green2', True),
                    (650, 'for the launch.', 42, 'green2', True),
                    (870, '你可以试着这样说', 38, 'fg', False),
                    (1090, '把 launch 换成你在盯的那件事', 34, 'mute', False)],
             speech=[('zh', '你也可以试着这样说。'),
                     ('en', 'Two cancellations in a row — that doesn’t bode well for the launch.'),
                     ('zh', '，连着两次取消，这对发布可不是好兆头。')]),
        # ---- 第 5 章 找不回那个状态 ----
        dict(n='24', title='get myself into this headspace',
             lines=[(950, 'doing absurd things to try', 38, 'green2', True),
                    (1030, 'and just get myself', 40, 'green2', True),
                    (1110, 'into this headspace', 38, 'green2', True),
                    (1190, '做一些很荒唐的事，把自己弄进那个状态', 30, 'fg', False),
                    (1330, 'get oneself into a headspace', 32, 'green', True)],
             speech=[('zh', '讲「进入某种心理状态」，用 '),
                     ('en', 'headspace'),
                     ('zh', '。她说 I’m just doing absurd things to try and just get myself into '
                            'this headspace，我在做一些荒唐的事，就想把自己弄进那个状态里。'
                            '她做的荒唐事是：一个人跑、对着墙角盯、假装捶墙。'
                            'headspace 比 mood 专业，心理咨询、运动心理都常用。')],
             source=(3229.00, 3231.40)),
        dict(n='25', title='it just clicks',
             lines=[(950, 'And then', 46, 'green2', True),
                    (1030, 'it just clicks,', 46, 'green2', True),
                    (1110, 'and I’m like, hold it and I do.', 34, 'green2', True),
                    (1190, '然后突然就通了', 40, 'fg', False),
                    (1330, 'it clicks', 40, 'green', True)],
             speech=[('zh', '讲「突然就通了」，用 '),
                     ('en', 'it just clicks'),
                     ('zh', '。她说 And then it just clicks, and I’m like, hold it for 30 seconds '
                            'and I do.，然后突然就通了，我心里说保持三十秒，我就真的保持了。'
                            '讲顿悟、讲默契、讲状态回来了，都能用这个词。')],
             source=(3236.20, 3239.00)),
        dict(n='26', title='换你来说',
             lines=[(470, 'I stopped forcing it,', 40, 'green2', True),
                    (560, 'and then it just clicked.', 38, 'green2', True),
                    (870, '你可以试着这样说', 38, 'fg', False),
                    (1090, '把 it 换成你突然想通的那件事', 34, 'mute', False)],
             speech=[('zh', '你也可以试着这样说。'),
                     ('en', 'I stopped forcing it, and then it just clicked.'),
                     ('zh', '，我不硬来了，然后突然就通了。')]),
        # ---- 第 6 章 我对我自己的较量 ----
        dict(n='27', title='it was totally me versus me',
             lines=[(950, 'It’s not about my skill,', 38, 'green2', True),
                    (1030, 'it was totally', 40, 'green2', True),
                    (1110, 'me versus me.', 42, 'green2', True),
                    (1190, '那不是技术的较量，完全是我对我自己', 32, 'fg', False),
                    (1330, 'it’s me versus me', 38, 'green', True)],
             speech=[('zh', '她给那场比赛定了个性质：'),
                     ('en', 'It’s not about my skill, it was totally me versus me.'),
                     ('zh', '，那跟技术没关系，完全是我对我自己的较量。'
                            'me versus me 这个说法写个人成长的文章很好用，'
                            '比 compete with myself 更有画面。')],
             source=(3251.50, 3254.30)),
        dict(n='28', title='betray myself',
             lines=[(950, 'it would have been', 42, 'green2', True),
                    (1030, 'me betraying myself.', 40, 'green2', True),
                    (1190, '那就是我在辜负自己', 40, 'fg', False),
                    (1330, 'betray oneself', 38, 'green', True)],
             speech=[('zh', '她说如果那天没做成，'),
                     ('en', 'it would have been me betraying myself'),
                     ('zh', '，那就是我自己辜负了自己。'
                            '前一章她讲过 body betraying me（身体不听使唤），'
                            '这里是 betray myself（辜负自己）——同一个动词，两种用法。')],
             source=(3258.50, 3259.90)),
        dict(n='29', title='come down to',
             lines=[(950, 'so much of it came', 42, 'green2', True),
                    (1030, 'down to trust', 44, 'green2', True),
                    (1110, 'and willfulness.', 42, 'green2', True),
                    (1190, '归根结底，看的是信任和意志', 36, 'fg', False),
                    (1330, 'come down to sth', 38, 'green', True)],
             speech=[('zh', '总结归因的黄金短语：'),
                     ('en', 'so much of it came down to trust and willfulness'),
                     ('zh', '，很大一部分，归根结底就是信任和意志。'
                            'come down to sth 是「最终取决于」——'
                            '复盘、汇报、写结语，一句话把重点收住。')],
             source=(3260.40, 3265.00)),
        dict(n='30', title='be totally spent',
             lines=[(950, 'it was because', 42, 'green2', True),
                    (1030, 'I was totally spent.', 42, 'green2', True),
                    (1190, '因为我已经被榨干了', 40, 'fg', False),
                    (1330, 'be totally spent', 38, 'green', True)],
             speech=[('zh', '她讲自己为什么哭：'),
                     ('en', 'it was because I was totally spent'),
                     ('zh', '，因为我已经被彻底榨干了。spent 是「被用尽了的」；'
                            '同类还有 drained（被抽干）、wiped out（累瘫），'
                            '三个词的程度一层比一层重。')],
             source=(3278.90, 3281.10)),
        dict(n='31', title='换你来说',
             lines=[(470, 'It came down to whether I', 40, 'green2', True),
                    (560, 'could show up fully spent —', 40, 'green2', True),
                    (650, 'that’s the whole game.', 40, 'green2', True),
                    (870, '你可以试着这样说', 38, 'fg', False),
                    (1090, '把 spent 换成你最真实的状态', 34, 'mute', False)],
             speech=[('zh', '你也可以试着这样说。'),
                     ('en', 'It came down to whether I could show up fully spent — that’s the '
                            'whole game.'),
                     ('zh', '，说到底就看我在被榨干的状态下还能不能上场——这才是全部。')]),
        # ---- 第 7 章 收尾 ----
        dict(n='32', title='带着这些点，再听一遍',
             lines=[(950, '现在再完整听一遍', 50, 'fg', False),
                    (1040, '你应该能听出更多东西了', 52, 'green', False),
                    (1210, '5 分 21 秒，20 个地道表达', 44, 'mute', False)],
             speech=[('zh', '现在带着刚才拆过的这些点，再完整听一遍这 5 分 21 秒。'
                            '这一次，你会听清她怎么复盘那场最难的比赛，'
                            '也会听清那句 '),
                     ('en', 'it was totally me versus me'),
                     ('zh', ' 是怎么落下来的。')],
             source=(2964.20, 3285.20)),
        dict(n='33', title='跟着读三遍',
             lines=[(470, '1. Walk me through it.', 44, 'green2', True),
                    (670, '2. I was holding on by a thread.', 40, 'green2', True),
                    (865, '3. It came down to trust.', 42, 'green2', True)],
             speech=[('zh', '最后挑三句最常用的，跟着读一遍。'),
                     ('en', 'Walk me through it.'),
                     ('en', 'I was holding on by a thread.'),
                     ('en', 'It came down to trust.'),
                     ('zh', '不用追求完美，先把它说出口。')],
             tail=3.1),
        dict(n='34', title='收藏，下次要复盘一场硬仗时过一遍',
             lines=[(480, '拾句英语', 100, 'green', False),
                    (650, '五分钟，学会复盘一场硬仗', 42, 'fg', False),
                    (850, '追问   Walk me through …', 36, 'green2', False),
                    (925, '状态   holding on by a thread', 34, 'green2', False),
                    (1000, '归因   it came down to …', 36, 'green2', False),
                    (1200, '听懂一句，再把它说出来', 40, 'mute', False)],
             speech=[('zh', '这一期讲的是怎么复盘一场硬仗：怎么把感受问出来，'
                            '怎么描述「撑不住了」，以及怎么把结论收在归因上。'),
                     ('zh', '先收藏，下次要复盘项目、复盘比赛的时候，把这三句过一遍。'
                            '拾句英语，听懂一句，再把它说出来。')]),
    ],
)


# ---- 16 奶奶去世（原片 3285.20–3603.70，318.50 秒）----
# 与 15 章的边界：15 收在「it was really difficult.」（54:45），本条从 54:45 接。
# ⚠️ 表述库里标「情感向」的 3 条（it's her mother / it was just devastating / I could not ask my mom）
#    按 SOP 不当语言课素材，只留在回放段落里；本条语言点 19 个。
SPECS['谷爱凌_奶奶去世'] = dict(
    src='__DATA_ROOT__/小红书发帖-拾句英语/谷爱凌/谷爱凌最新全英访谈.mp4',
    cards=[
        # ---- 第 0 章 钩子 + 完整听一遍（318 秒，拆四张）----
        dict(n='01', title='一块金牌，隔着一个告别',
             lines=[(770, '跟着 5 分钟访谈学表达', 46, 'green', False),
                    (920, '告别 · 撑住 · 纪念', 40, 'fg', False),
                    (1000, '19 个表达，就藏在 5 分 18 秒里', 34, 'mute', False)],
             speech=[('zh', '这一期讲的是这段访谈里最重的一段。她说：'),
                     ('en', 'it’s the highest high and the lowest low separated by a matter of minutes.'),
                     ('zh', '最高点和最低点之间，只隔了几分钟。'
                            '在讲怎么表达之前，先说清楚：这一期不是情绪消费，'
                            '是跟着她自己的讲述，学她怎么把一段很难的事讲清楚。'),
                     ('zh', '我们先完整听一遍，再一句一句拆。')]),
        dict(n='02', title='先听前 80 秒',
             lines=[(950, 'even when you’re so clear …', 38, 'green2', True),
                    (1190, '先听前 80 秒', 42, 'fg', False),
                    (1330, '主持人先替她把情绪接住了', 36, 'mute', False)],
             speech=[('zh', '先听前 80 秒。主持人先谢她把细节一步步讲出来，'
                            '再说到那场记者会——大家看着她眼泪掉下来的那一刻。')],
             source=(3285.20, 3365.00)),
        dict(n='03', title='再听 80 秒',
             lines=[(950, 'my ground was cracking', 40, 'green2', True),
                    (1030, 'out from underneath me', 38, 'green2', True),
                    (1190, '再听 80 秒', 42, 'fg', False),
                    (1330, '这一段讲「认知整个塌掉」', 38, 'mute', False)],
             speech=[('zh', '再听 80 秒。她讲了出发前那次告别、和妈妈事先的约定，'
                            '以及拿到金牌之后看到那封邮件的那一刻。')],
             source=(3365.00, 3445.00)),
        dict(n='04', title='再听 80 秒',
             lines=[(950, 'I had to just turn something', 36, 'green2', True),
                    (1030, 'off in my brain', 40, 'green2', True),
                    (1190, '再听 80 秒', 42, 'fg', False),
                    (1330, '这一段讲「她怎么撑过记者会」', 36, 'mute', False)],
             speech=[('zh', '再听 80 秒。她讲了那场记者会怎么开完的，'
                            '以及她怎么把情绪先放在一边。')],
             source=(3445.00, 3525.00)),
        dict(n='05', title='最后 78 秒',
             lines=[(950, 'a line I would not cross', 40, 'green2', True),
                    (1190, '最后 78 秒', 42, 'fg', False),
                    (1330, '听完这一遍，我们就开始拆', 38, 'mute', False)],
             speech=[('zh', '最后 78 秒。她讲了那条她不会越过的线，'
                            '也讲了她替家人办的那场葬礼。听完这一遍，我们就开始拆。')],
             source=(3525.00, 3603.70)),
        # ---- 第 1 章 主持人先替她把情绪接住 ----
        dict(n='06', title='walk sb through sth / play by play',
             lines=[(950, 'Thank you for walking us', 38, 'green2', True),
                    (1030, 'through play by play', 40, 'green2', True),
                    (1190, '谢谢你一步步带我们过了一遍', 36, 'fg', False),
                    (1330, 'walk sb through sth / play by play', 30, 'green', True)],
             speech=[('zh', '主持人先谢她：'),
                     ('en', 'Thank you for walking us through play by play'),
                     ('zh', '，谢谢你一步一步带我们过了一遍。'
                            'walk sb through sth 是「带某人走一遍流程」；'
                            'play by play 本来是体育解说里的「逐帧细节」，'
                            '日常说 play by play 就是「一点一点、原原本本」。')],
             source=(3286.30, 3288.10)),
        dict(n='07', title='even when …, there’s so much to it',
             lines=[(950, 'even when you’re so clear,', 38, 'green2', True),
                    (1030, 'even when you’re so focused', 36, 'green2', True),
                    (1110, 'and driven and trained', 36, 'green2', True),
                    (1190, '就算再清醒、再专注，也没那么简单', 30, 'fg', False),
                    (1330, 'even when …, there’s so much to it', 30, 'green', True)],
             speech=[('zh', '他说看着很容易，其实不是：'),
                     ('en', 'even when you’re so clear, even when you’re so focused and driven '
                            'and trained and prepared, there’s so much to it'),
                     ('zh', '，就算你再清醒、再专注、再训练有素、准备得再好，'
                            '里面还有太多东西。even when 开头的让步从句加一串形容词排比，'
                            '把「没那么简单」说得很有分量；there’s so much to it 就是'
                            '「这里面的门道太多了」。')],
             source=(3301.10, 3307.50)),
        dict(n='08', title='换你来说',
             lines=[(470, 'Even when the plan looks', 40, 'green2', True),
                    (560, 'simple, there’s so much to it.', 38, 'green2', True),
                    (870, '你可以试着这样说', 38, 'fg', False),
                    (1090, '把 simple 换成你手上那件事', 36, 'mute', False)],
             speech=[('zh', '你也可以试着这样说。'),
                     ('en', 'Even when the plan looks simple, there’s so much to it.'),
                     ('zh', '，就算计划看着很简单，里面的门道也多着呢。')]),
        # ---- 第 2 章 第一次公开讲这件事 ----
        dict(n='09', title='my first time doing sth',
             lines=[(950, 'This is like my first time', 38, 'green2', True),
                    (1030, 'really speaking about this', 38, 'green2', True),
                    (1110, 'publicly since.', 40, 'green2', True),
                    (1190, '这是我第一次公开讲这件事', 38, 'fg', False),
                    (1330, 'my first time doing sth（不是 to do）', 30, 'green', True)],
             speech=[('zh', '讲「第一次做某事」，注意是 doing 不是 to do：'),
                     ('en', 'This is like my first time really speaking about this publicly since.'),
                     ('zh', '，这算是我第一次公开讲这件事。'
                            'my first time doing sth 是固定说法；'
                            '写成 my first time to speak 是典型的中式英语，要改掉。')],
             source=(3332.60, 3335.90)),
        dict(n='10', title='metabolize（消化情绪）',
             lines=[(950, 'it’s just been so hard', 40, 'green2', True),
                    (1030, 'for me to metabolize', 40, 'green2', True),
                    (1110, 'after all this time.', 40, 'green2', True),
                    (1190, '过了这么久，我还是很难消化这件事', 34, 'fg', False),
                    (1330, 'metabolize sth', 38, 'green', True)],
             speech=[('zh', 'metabolize 本义是「代谢」，用来讲情绪就是「慢慢消化、接受」。'
                            '她说 '),
                     ('en', 'it’s just been so hard for me to metabolize after all this time'),
                     ('zh', '，过了这么久，我还是很难把这件事消化掉。'
                            '母语者讲悲伤、讲创伤时经常用这个隐喻——'
                            '它比 accept 更慢、更身体化。')],
             source=(3336.90, 3339.50)),
        dict(n='11', title='be separated by a matter of …',
             lines=[(950, 'the highest high and the lowest low', 34, 'green2', True),
                    (1030, 'separated by', 42, 'green2', True),
                    (1110, 'a matter of minutes.', 38, 'green2', True),
                    (1190, '最高点和最低点之间，只隔了几分钟', 32, 'fg', False),
                    (1330, 'a matter of + 时间/数量', 34, 'green', True)],
             speech=[('zh', 'a matter of + 时间或数量＝「仅仅、不过」。她说 '),
                     ('en', 'it’s the highest high and the lowest low separated by a matter of minutes'),
                     ('zh', '，最高点和最低点，中间只隔着几分钟。'
                            'a matter of seconds / a matter of degrees 都是这个结构——'
                            '强调「差得极少」。')],
             source=(3340.40, 3343.70)),
        dict(n='12', title='换你来说',
             lines=[(470, 'The best and the worst news', 40, 'green2', True),
                    (560, 'came separated by a matter', 40, 'green2', True),
                    (650, 'of hours.', 44, 'green2', True),
                    (870, '你可以试着这样说', 38, 'fg', False),
                    (1090, '把 hours 换成你的那两个时间点', 34, 'mute', False)],
             speech=[('zh', '你也可以试着这样说。'),
                     ('en', 'The best and the worst news came separated by a matter of hours.'),
                     ('zh', '，最好的消息和最坏的消息，中间只隔了几个小时。')]),
        # ---- 第 3 章 出发前的那次告别 ----
        dict(n='13', title='过去完成时 + there was a chance that …',
             lines=[(950, 'my grandma had been sick', 38, 'green2', True),
                    (1030, 'for a long time, and we knew', 36, 'green2', True),
                    (1110, 'there was a chance that …', 36, 'green2', True),
                    (1190, '奶奶病了很久，我们都知道有可能……', 30, 'fg', False),
                    (1330, 'had been / there was a chance that', 30, 'green', True)],
             speech=[('zh', '这一句里有三个点：过去完成时（had been sick）、'
                            '不确定的可能性（there was a chance that）、'
                            '以及 our last time doing sth。她说 '),
                     ('en', 'my grandma had been sick for a long time, and we knew that there was '
                            'a chance that it was our last time saying goodbye to her when I left '
                            'for the Olympics'),
                     ('zh', '，奶奶已经病了很久，我们心里都清楚，'
                            '我出发去奥运会前那次，可能就是最后一次跟她告别。')],
             source=(3344.20, 3352.20)),
        dict(n='14', title='be brave for sb / make sb promises',
             lines=[(950, 'I told her I’d be brave', 38, 'green2', True),
                    (1030, 'for her and made her a bunch', 36, 'green2', True),
                    (1110, 'of promises.', 42, 'green2', True),
                    (1190, '我跟她说我会为她坚强，还许了一堆承诺', 30, 'fg', False),
                    (1330, 'be brave for sb / make sb promises', 28, 'green', True)],
             speech=[('zh', '她讲那次告别：'),
                     ('en', 'I told her I’d be brave for her and made her a bunch of promises '
                            'essentially'),
                     ('zh', '，我跟她说，我会为了她坚强，基本上就是给她许了一堆承诺。'
                            'be brave for sb 是「为了某人而坚强」——'
                            '勇敢不是形容词，是给别人看的一个动作；'
                            'make sb a promise 是「向某人承诺」。')],
             source=(3355.30, 3358.70)),
        dict(n='15', title='we’d agreed that if … had happened …',
             lines=[(950, 'we’d agreed that if something', 36, 'green2', True),
                    (1030, 'had happened to my grandma', 34, 'green2', True),
                    (1110, 'during the Olympics, I didn’t', 32, 'green2', True),
                    (1190, '我们事先说好：如果奥运期间出了事，我不想知道', 28, 'fg', False),
                    (1330, 'we’d agreed that if … had happened …', 28, 'green', True)],
             speech=[('zh', '转述「事先的约定」，用过去完成时叠 if 从句：'),
                     ('en', 'my mom and I had actually spoken about it and we’d agreed that if '
                            'something had happened to my grandma during the Olympics, I didn’t '
                            'want to know during the contest'),
                     ('zh', '，我和妈妈事先聊过，说好如果奥运期间奶奶出了什么事，'
                            '比赛期间我不要知道——因为提前哀悼，只会毁掉我练了四年的这一刻。'
                            'we’d agreed that if + 过去完成时，是转述约定的标准句型。')],
             source=(3358.70, 3367.90)),
        dict(n='16', title='换你来说',
             lines=[(470, 'We’d agreed that if anything', 40, 'green2', True),
                    (560, 'had happened, we’d deal with', 40, 'green2', True),
                    (650, 'it after the launch.', 40, 'green2', True),
                    (870, '你可以试着这样说', 38, 'fg', False),
                    (1090, '把 launch 换成你的那件大事', 36, 'mute', False)],
             speech=[('zh', '你也可以试着这样说。'),
                     ('en', 'We’d agreed that if anything had happened, we’d deal with it after '
                            'the launch.'),
                     ('zh', '，我们事先说好，万一出了什么事，等上线之后再说。')]),
        # ---- 第 4 章 妈妈一声没吭 ----
        dict(n='17', title='not break a sweat',
             lines=[(950, 'did not break a sweat,', 40, 'green2', True),
                    (1030, 'or a tear,', 44, 'green2', True),
                    (1110, 'or anything.', 42, 'green2', True),
                    (1190, '一滴汗没出，一滴泪没掉，什么都没露', 32, 'fg', False),
                    (1330, 'not break a sweat', 38, 'green', True)],
             speech=[('zh', '讲「稳住、一点声色都不露」，用 '),
                     ('en', 'not break a sweat'),
                     ('zh', '。她说妈妈全知道，却 did not break a sweat, or a tear, or anything，'
                            '一滴汗没出、一滴泪没掉，什么都没露出来。'
                            'break a sweat 本来是运动里「出汗」，引申为「露馅、费劲」；'
                            '这里和 tear 并列，分量就出来了。')],
             source=(3384.10, 3388.50)),
        dict(n='18', title='wrap one’s head around sth',
             lines=[(950, 'I genuinely cannot', 40, 'green2', True),
                    (1030, 'wrap my head', 42, 'green2', True),
                    (1110, 'around that.', 44, 'green2', True),
                    (1190, '我真的想不通这件事', 40, 'fg', False),
                    (1330, 'wrap one’s head around sth', 34, 'green', True)],
             speech=[('zh', '表达「想不通、接受不了」的第一高频习语：'),
                     ('en', 'I genuinely cannot wrap my head around that'),
                     ('zh', '，我真的没法把这件事想明白。'
                            'wrap one’s head around 字面是「把脑袋绕过去」，'
                            '实际是「理解、消化」——工作里说 I can’t wrap my head around '
                            'the numbers，也是这个用法。')],
             source=(3395.90, 3397.80)),
        dict(n='19', title='换你来说',
             lines=[(470, 'I still can’t wrap my head', 40, 'green2', True),
                    (560, 'around how they shipped it', 40, 'green2', True),
                    (650, 'that fast.', 44, 'green2', True),
                    (870, '你可以试着这样说', 38, 'fg', False),
                    (1090, '把 it 换成你想不通的那件事', 36, 'mute', False)],
             speech=[('zh', '你也可以试着这样说。'),
                     ('en', 'I still can’t wrap my head around how they shipped it that fast.'),
                     ('zh', '，我到现在还是想不通他们怎么那么快就上线了。')]),
        # ---- 第 5 章 认知崩塌 ----
        dict(n='20', title='my ground was cracking out from underneath me',
             lines=[(950, 'my ground was cracking', 40, 'green2', True),
                    (1030, 'out from underneath me.', 36, 'green2', True),
                    (1190, '我的地基，从脚底下裂开了', 36, 'fg', False),
                    (1330, 'one’s ground cracks out from underneath sb', 28, 'green', True)],
             speech=[('zh', '她用「地基塌陷」来讲那一刻：'),
                     ('en', 'it was just like my ground was cracking out from underneath me'),
                     ('zh', '，就好像脚底下的地面正在裂开。'
                            'ground 是「立足之地、地基」；'
                            '同类比喻还有 the ground shifted under my feet、'
                            'everything fell away underneath me——'
                            '都是「原来的世界观不成立了」。')],
             source=(3410.30, 3414.10)),
        dict(n='21', title='you think X is what it is until …',
             lines=[(950, 'you think your reality', 40, 'green2', True),
                    (1030, 'is what it is until', 40, 'green2', True),
                    (1110, 'something just comes along', 36, 'green2', True),
                    (1190, '你以为现实就是这样，直到……', 36, 'fg', False),
                    (1330, 'you think X is what it is until …', 30, 'green', True)],
             speech=[('zh', '「认知被颠覆」的叙事框架：'),
                     ('en', 'you think your reality is what it is until something just comes along '
                            'and makes you feel like you were living in a little fishbowl'),
                     ('zh', '，你以为你的现实就是那样，直到某件事突然出现，'
                            '让你发现自己原来一直活在一个小鱼缸里。'
                            'X is what it is 是「就是这样、没什么可说的」；'
                            'fishbowl 比喻视野很窄的那一小块天地。')],
             source=(3414.30, 3421.60)),
        dict(n='22', title='换你来说',
             lines=[(470, 'You think the process is fine', 40, 'green2', True),
                    (560, 'until one outage shows you', 40, 'green2', True),
                    (650, 'the whole fishbowl.', 40, 'green2', True),
                    (870, '你可以试着这样说', 38, 'fg', False),
                    (1090, '把 outage 换成让你清醒的那件事', 34, 'mute', False)],
             speech=[('zh', '你也可以试着这样说。'),
                     ('en', 'You think the process is fine until one outage shows you the whole '
                            'fishbowl.'),
                     ('zh', '，你以为流程没问题，直到一次故障让你看清整个鱼缸。')]),
        # ---- 第 6 章 她怎么撑过那场记者会 ----
        dict(n='23', title='in case + 一般现在时',
             lines=[(950, 'if in case I win,', 42, 'green2', True),
                    (1030, 'I’m going to put it', 40, 'green2', True),
                    (1110, 'in my hair.', 42, 'green2', True),
                    (1190, '万一我赢了呢，我打算把它戴在头上', 32, 'fg', False),
                    (1330, 'in case + 一般现在时', 36, 'green', True)],
             speech=[('zh', '她讲那根金色发绳：'),
                     ('en', 'if in case I win, I’m going to put it in my hair'),
                     ('zh', '，我想着万一赢了呢，就把它戴在头上。'
                            'in case 是「以防万一」，后面接一般现在时，'
                            '不能接 will——这是 if 和 in case 最常被混的一处：'
                            'if 讲条件，in case 讲预防。')],
             source=(3459.30, 3462.30)),
        dict(n='24', title='compartmentalized',
             lines=[(950, 'That was all', 42, 'green2', True),
                    (1030, 'so compartmentalized.', 38, 'green2', True),
                    (1190, '那段时间，我把一切都分格放好了', 36, 'fg', False),
                    (1330, 'compartmentalized', 38, 'green', True)],
             speech=[('zh', '一个心理学和职场都常用的高级词：'),
                     ('en', 'That was all so compartmentalized'),
                     ('zh', '，那些事都被我分门别类放在各自的格子里了。'
                            'compartmentalize 是「把情绪或事务分格隔离」——'
                            '听起来很理性，但她后面说：撑完记者会，整个人还是崩了。')],
             source=(3479.40, 3481.80)),
        dict(n='25', title='pass away',
             lines=[(950, 'one of the most important people', 34, 'green2', True),
                    (1030, 'in my life', 42, 'green2', True),
                    (1110, 'just passed away.', 40, 'green2', True),
                    (1190, '我生命里最重要的人之一，刚刚走了', 34, 'fg', False),
                    (1330, 'pass away', 40, 'green', True)],
             speech=[('zh', '谈死亡的标准委婉说法：'),
                     ('en', 'one of the most important people in my life just passed away'),
                     ('zh', '，我生命里最重要的人之一，刚刚走了。'
                            'pass away 比 die 委婉，正式场合、书面都用它；'
                            '她那句前面还有一个 by the way——本来是话锋一转的口头禅，'
                            '放在这里，反而更让人心一沉。')],
             source=(3485.70, 3487.70)),
        dict(n='26', title='turn sth off in one’s brain / get through sth',
             lines=[(950, 'I had to just turn', 40, 'green2', True),
                    (1030, 'something off in my brain', 36, 'green2', True),
                    (1110, 'to get through that press conference.', 30, 'green2', True),
                    (1190, '我得把脑子里的某个开关关掉，才能撑过那场记者会', 28, 'fg', False),
                    (1330, 'turn sth off in one’s brain / get through sth', 26, 'green', True)],
             speech=[('zh', '两个搭配一起记：'),
                     ('en', 'I had to just turn something off in my brain to get through that '
                            'press conference'),
                     ('zh', '，我得把脑子里的某个东西关掉，才能把那场记者会撑下来。'
                            'turn sth off 是「关掉开关」，用来讲强行屏蔽情绪非常准；'
                            'get through sth 是「撑过、熬过」。')],
             source=(3497.50, 3501.60)),
        dict(n='27', title='换你来说',
             lines=[(470, 'I had to switch something off', 40, 'green2', True),
                    (560, 'to get through the review,', 40, 'green2', True),
                    (650, 'then I dealt with it.', 40, 'green2', True),
                    (870, '你可以试着这样说', 38, 'fg', False),
                    (1090, '把 review 换成你必须撑过去的那件事', 30, 'mute', False)],
             speech=[('zh', '你也可以试着这样说。'),
                     ('en', 'I had to switch something off to get through the review, then I dealt '
                            'with it.'),
                     ('zh', '，我得先关掉一部分自己才能撑过那次复盘，之后再慢慢处理。')]),
        # ---- 第 7 章 她替家人办的那场葬礼 ----
        dict(n='28', title='a line I would not cross',
             lines=[(950, 'that is just like', 40, 'green2', True),
                    (1030, 'a line I would not cross.', 36, 'green2', True),
                    (1190, '那是一条我不会越过的线', 38, 'fg', False),
                    (1330, 'a line sb would not cross', 34, 'green', True)],
             speech=[('zh', '讲底线，用 line：'),
                     ('en', 'that is just like a line I would not cross'),
                     ('zh', '，那就是一条我不会越过的线。'
                            'draw a line / cross a line 是「划底线、越线」；'
                            '这里把它改成定语从句 a line I would not cross，'
                            '句子更短，态度也更硬——有人拿她奶奶的事做文章，她回击了。')],
             source=(3524.30, 3525.90)),
        dict(n='29', title='平行短句排比',
             lines=[(950, 'I planned my grandma’s funeral.', 34, 'green2', True),
                    (1030, 'I found the choir for it.', 36, 'green2', True),
                    (1110, 'I selected the Bible verses.', 34, 'green2', True),
                    (1190, '我挑了花，我主持了仪式', 36, 'fg', False),
                    (1330, '短句排比：I did A. I did B. I did C.', 30, 'green', True)],
             speech=[('zh', '她列自己做过的事，用的全是短句：'),
                     ('en', 'I planned my grandma’s funeral. I found the choir for it. '
                            'I selected the Bible verses for it. I picked the flowers. '
                            'I did the ceremony.'),
                     ('zh', '，我筹划了奶奶的葬礼，找了唱诗班，选了经文，挑了花，主持了仪式。'
                            '六个短句连着摆，不解释、不修饰——分量全靠信息密度顶上来。'
                            '写作里想表达「我做了很多」，用排比短句比用形容词有力。')],
             source=(3529.30, 3537.10)),
        dict(n='30', title='换你来说',
             lines=[(470, 'I booked the room. I wrote', 40, 'green2', True),
                    (560, 'the agenda. I ran the whole', 40, 'green2', True),
                    (650, 'thing myself.', 44, 'green2', True),
                    (870, '你可以试着这样说', 38, 'fg', False),
                    (1090, '三个短句连着说，比重形容词有力', 32, 'mute', False)],
             speech=[('zh', '你也可以试着这样说。'),
                     ('en', 'I booked the room. I wrote the agenda. I ran the whole thing myself.'),
                     ('zh', '，我订了会议室，写了议程，整场都是我自己撑下来的。')]),
        # ---- 第 8 章 收尾 ----
        dict(n='31', title='the most human thing you could have done',
             lines=[(950, 'that was the most human thing', 32, 'green2', True),
                    (1030, 'you could have done.', 36, 'green2', True),
                    (1190, '那是你能做的最有人味的一件事', 36, 'fg', False),
                    (1330, 'the most + 形容词 + thing you could have done', 28, 'green', True)],
             speech=[('zh', '主持人最后这句话，把整段收住了：'),
                     ('en', 'you being honest about the loss of one of the most important women in '
                            'your life was the most human thing you could have done'),
                     ('zh', '，你愿意坦白讲出失去这样一位对你如此重要的女性，'
                            '是你能做的最有人味的一件事。'
                            'the most + 形容词 + thing you could have done，'
                            '是英语里高度褒奖人的句型——夸的不是成绩，是选择。')],
             source=(3576.90, 3582.70)),
        dict(n='32', title='带着这些点，再听一遍',
             lines=[(950, '现在再完整听一遍', 50, 'fg', False),
                    (1040, '你应该能听出更多东西了', 52, 'green', False),
                    (1210, '5 分 18 秒，19 个地道表达', 44, 'mute', False)],
             speech=[('zh', '现在带着刚才拆过的这些点，再完整听一遍这 5 分 18 秒。'
                            '这一次，你会听清她怎么用短句承受分量，'
                            '也会听清那句 '),
                     ('en', 'separated by a matter of minutes'),
                     ('zh', ' 是怎么落下来的。')],
             source=(3285.20, 3603.70)),
        dict(n='33', title='跟着读三遍',
             lines=[(470, '1. I can’t wrap my head around it.', 38, 'green2', True),
                    (670, '2. I had to turn something off', 38, 'green2', True),
                    (740, 'to get through it.', 40, 'green2', True),
                    (865, '3. It came separated by a matter of minutes.', 34, 'green2', True)],
             speech=[('zh', '最后挑三句最常用的，跟着读一遍。'),
                     ('en', 'I can’t wrap my head around it.'),
                     ('en', 'I had to turn something off to get through it.'),
                     ('en', 'It came separated by a matter of minutes.'),
                     ('zh', '不用追求完美，先把它说出口。')],
             tail=3.1),
        dict(n='34', title='收藏，下次要讲一段难的事时过一遍',
             lines=[(480, '拾句英语', 100, 'green', False),
                    (650, '五分钟，学会把难的事讲清楚', 40, 'fg', False),
                    (850, '承受   separated by a matter of minutes', 30, 'green2', False),
                    (925, '撑住   turn something off / get through', 30, 'green2', False),
                    (1000, '分量   I did A. I did B. I did C.', 32, 'green2', False),
                    (1200, '听懂一句，再把它说出来', 40, 'mute', False)],
             speech=[('zh', '这一期讲的是怎么把一段很难的事讲清楚：'
                            '用「只隔几分钟」讲落差，用「关掉一部分自己」讲撑住，'
                            '用排比短句讲分量。'),
                     ('zh', '先收藏，下次要讲一段不容易的事，把这三句过一遍。'
                            '拾句英语，听懂一句，再把它说出来。')]),
    ],
)


# ---- 17 Final Five（原片 3603.70–3714.00，110.30 秒）----
# 与 16 章的边界：16 收在「Thank you for walking us through」（1:00:03），本条从 1:00:03 接。
# 这是整段访谈的最后一节：五个快问快答（每题一句话上限），外加双方的收尾致谢。
SPECS['谷爱凌_FinalFive'] = dict(
    src='__DATA_ROOT__/小红书发帖-拾句英语/谷爱凌/谷爱凌最新全英访谈.mp4',
    cards=[
        # ---- 第 0 章 钩子 + 完整听一遍（110 秒，一张听完）----
        dict(n='01', title='每题一句话，五个快问快答',
             lines=[(770, '跟着 2 分钟访谈学表达', 46, 'green', False),
                    (920, '快问 · 定义 · 致谢', 40, 'fg', False),
                    (1000, '20 个表达，就藏在 1 分 50 秒里', 34, 'mute', False)],
             speech=[('zh', '这是整段访谈的最后一节，规则很简单：'),
                     ('en', 'these questions have to be answered in one sentence maximum.'),
                     ('zh', '每题最多用一句话回答。五个问题里，有「你收到过最好的建议」'
                            '「你想给全世界立一条什么法」，最后还有两个人的收尾致谢——'
                            '英语里怎么道谢、怎么祝福，这一节全在里面。'),
                     ('zh', '我们先完整听一遍，再一句一句拆。')]),
        dict(n='02', title='先完整听一遍这 1 分 50 秒',
             lines=[(950, 'Hit me.', 46, 'green2', True),
                    (1190, '整段只有 1 分 50 秒', 42, 'fg', False),
                    (1330, '快问快答，每句都值得抄', 38, 'mute', False)],
             speech=[('zh', '先完整听一遍。注意主持人的节奏：一个问题接一个问题，'
                            '她每题只答一句，最后两个人怎么互相收尾。')],
             source=(3603.70, 3714.00)),
        # ---- 第 1 章 「来吧，问吧」 ----
        dict(n='03', title='Hit me.',
             lines=[(950, 'these questions have to be', 38, 'green2', True),
                    (1030, 'answered in one sentence maximum.', 32, 'green2', True),
                    (1110, 'Hit me.', 50, 'green2', True),
                    (1190, '每题最多一句话——来吧', 40, 'fg', False),
                    (1330, 'Hit me.（问吧 / 说吧）', 36, 'green', True)],
             speech=[('zh', '主持人宣布规则：每题最多一句话，然后说了两个字：'),
                     ('en', 'Hit me.'),
                     ('zh', '字面是「打我」，实际是「来吧、问吧」——'
                            '口语里请对方尽管开口、尽管出招，就用它。'
                            '字面和含义完全脱钩，所以别按字面理解。')],
             source=(3605.10, 3606.90)),
        dict(n='04', title='最好的建议：先说「试着来」',
             lines=[(950, 'What is the best advice', 40, 'green2', True),
                    (1030, 'you’ve ever heard or received?', 36, 'green2', True),
                    (1190, '你收到过最好的建议是什么？', 38, 'fg', False),
                    (1330, 'What’s the best … you’ve ever …?', 34, 'green', True)],
             speech=[('zh', '访谈里的固定模板，日常聊天也常用：'),
                     ('en', 'What is the best advice you’ve ever heard or received?'),
                     ('zh', '，你听过或收到过最好的建议是什么？'
                            '最高级 + 现在完成时 + ever，问的是「迄今为止」的经验里最的那个；'
                            '把 best 换成 worst、funniest 就能问出一整轮问题。')],
             source=(3610.10, 3612.60)),
        dict(n='05', title='It will never be embarrassing to try.',
             lines=[(950, 'It will never be embarrassing', 36, 'green2', True),
                    (1030, 'to try.', 48, 'green2', True),
                    (1190, '尝试，永远不会让人难堪', 40, 'fg', False),
                    (1330, 'It will never be embarrassing to do sth', 30, 'green', True)],
             speech=[('zh', '她给出的答案是：'),
                     ('en', 'It will never be embarrassing to try.'),
                     ('zh', '，尝试永远不会让你难堪。'
                            'it 是形式主语，真正的主语是后面的 to try；'
                            'never 放在 be 和表语之间，把「永远」钉死——'
                            '这句话可以直接背下来，用来鼓励别人。')],
             source=(3612.90, 3614.50)),
        dict(n='06', title='动名词作主语',
             lines=[(950, 'Waking up at four', 42, 'green2', True),
                    (1030, 'in the morning', 42, 'green2', True),
                    (1110, 'makes you more productive.', 34, 'green2', True),
                    (1190, '凌晨四点起床，会让你更高效', 34, 'fg', False),
                    (1330, '动名词作主语 + make sb + 形容词', 28, 'green', True)],
             speech=[('zh', '她举了一条「最差的建议」：'),
                     ('en', 'Waking up at four in the morning makes you more productive.'),
                     ('zh', '，凌晨四点起床会让你更高效。'
                            'waking up 是动名词作主语——英语里讲「做某事会带来什么结果」，'
                            '最常见的开头就是把动词变成 -ing；'
                            'make sb + 形容词，是「让某人变得……」。')],
             source=(3618.80, 3620.80)),
        dict(n='07', title='换你来说',
             lines=[(470, 'The best advice I ever got', 40, 'green2', True),
                    (560, 'was simple: it will never', 40, 'green2', True),
                    (650, 'be embarrassing to try.', 40, 'green2', True),
                    (870, '你可以试着这样说', 38, 'fg', False),
                    (1090, '把 try 换成你一直不敢做的那件事', 32, 'mute', False)],
             speech=[('zh', '你也可以试着这样说。'),
                     ('en', 'The best advice I ever got was simple: it will never be embarrassing '
                            'to try.'),
                     ('zh', '，我收到过最好的建议很简单：尝试永远不会让人难堪。'
                            '把 try 换成你一直不敢做的那件事。')]),
        # ---- 第 2 章 别被盒子装进去 ----
        dict(n='08', title='Define your own category.',
             lines=[(950, 'Define your', 46, 'green2', True),
                    (1030, 'own category.', 46, 'green2', True),
                    (1190, '自己定义你的分类', 40, 'fg', False),
                    (1330, 'Define your own category.', 36, 'green', True)],
             speech=[('zh', '给年轻女性的建议，她只说了四个词：'),
                     ('en', 'Define your own category.'),
                     ('zh', '，自己定义你的分类。'
                            '别人给你准备好的那些类别，都可以不要；'
                            'category 是「分类、类别」——这句是祈使句，短、硬、适合当签名。')],
             source=(3626.00, 3627.70)),
        dict(n='09', title='boxes that feel more rigid / what being X means',
             lines=[(950, 'there’s a lot of boxes', 38, 'green2', True),
                    (1030, 'that feel more rigid', 38, 'green2', True),
                    (1110, 'as far as career, …', 36, 'green2', True),
                    (1190, '有很多框子，在职业、做母亲、做女孩这些事上显得更硬', 28, 'fg', False),
                    (1330, 'boxes that feel rigid / what being X means', 26, 'green', True)],
             speech=[('zh', '她解释为什么要自定义：'),
                     ('en', 'for women, there’s a lot of boxes that feel more rigid as far as career, '
                            'what being a mother means, what being a girl'),
                     ('zh', '，对女性来说，有很多框子——在职业、'
                            '「当妈妈意味着什么」「当女孩意味着什么」这些事上，它们显得更硬。'
                            'box 在这里是「被划定的框架」；'
                            'what being X means 是「身为 X 意味着什么」，谈身份时很好用。')],
             source=(3630.10, 3635.60)),
        dict(n='10', title='You can be N of one.',
             lines=[(950, 'You can be', 46, 'green2', True),
                    (1030, 'N of one.', 46, 'green2', True),
                    (1190, '你可以是「只有一个样本」的那种存在', 34, 'fg', False),
                    (1330, 'N of one', 40, 'green', True)],
             speech=[('zh', '这句很有意思，是统计学里的说法借来用的：'),
                     ('en', 'You can be N of one.'),
                     ('zh', '，你可以是「样本量为 1」的那个人。'
                            'N 在统计里指样本数：N of one 意思是「只有一个样本，'
                            '没有同类可以比较」——也就是独一无二、不跟任何人同类。'
                            '她讲的是：不用非得属于某个类别。')],
             source=(3641.40, 3643.50)),
        dict(n='11', title='换你来说',
             lines=[(470, 'I stopped fitting into the', 40, 'green2', True),
                    (560, 'boxes I was handed —', 40, 'green2', True),
                    (650, 'I defined my own.', 40, 'green2', True),
                    (870, '你可以试着这样说', 38, 'fg', False),
                    (1090, '把 boxes 换成别人给你划的那些框', 32, 'mute', False)],
             speech=[('zh', '你也可以试着这样说。'),
                     ('en', 'I stopped fitting into the boxes I was handed — I defined my own.'),
                     ('zh', '，我不再往别人递过来的框子里塞自己了——我自己定义。')]),
        # ---- 第 3 章 崩了的时候她做什么 ----
        dict(n='12', title='crash out',
             lines=[(950, 'when you have a crash out', 38, 'green2', True),
                    (1030, 'or a bad day, what does', 38, 'green2', True),
                    (1110, 'Eileen Gu do?', 38, 'green2', True),
                    (1190, '情绪崩掉、或者过得糟的时候，谷爱凌会干嘛？', 30, 'fg', False),
                    (1330, 'crash out', 40, 'green', True)],
             speech=[('zh', '主持人用了一个很新的俚语：'),
                     ('en', 'when you have a crash out or a bad day, what does Eileen Gu do?'),
                     ('zh', '，你情绪崩掉、或者过得很糟的时候，会干嘛？'
                            'crash out 是近几年流行的俚语：情绪失控、彻底摆烂的状态；'
                            '注意这里是名词用法 a crash out，动词用法是 I crashed out。')],
             source=(3644.20, 3648.10)),
        dict(n='13', title='the most efficient way that you can do sth',
             lines=[(950, 'it’s the most efficient way', 38, 'green2', True),
                    (1030, 'that you can release emotion', 34, 'green2', True),
                    (1110, 'and return to a logical state.', 32, 'green2', True),
                    (1190, '这是释放情绪、回到理性状态最高效的办法', 28, 'fg', False),
                    (1330, 'the most efficient way that you can do sth', 26, 'green', True)],
             speech=[('zh', '她的答案是哭：'),
                     ('en', 'I think it’s the most efficient way that you can release emotion and '
                            'return to a logical state.'),
                     ('zh', '，我觉得这是释放情绪、回到理性状态最高效的办法。'
                            'the most efficient way that you can do sth 是一套很好用的说法，'
                            '讲方法论、讲流程都能套；release emotion 是「把情绪放出去」，'
                            'return to a logical state 是「回到理性状态」。'
                            '她还补了一句：the sooner you can get the irrational out, the better.')],
             source=(3651.10, 3656.30)),
        dict(n='14', title='换你来说',
             lines=[(470, 'Running is the most efficient way', 38, 'green2', True),
                    (560, 'I can reset and get back', 38, 'green2', True),
                    (650, 'to a logical state.', 40, 'green2', True),
                    (870, '你可以试着这样说', 38, 'fg', False),
                    (1090, '把 Running 换成让你回血的那件事', 32, 'mute', False)],
             speech=[('zh', '你也可以试着这样说。'),
                     ('en', 'Running is the most efficient way I can reset and get back to a '
                            'logical state.'),
                     ('zh', '，跑步是我重置自己、回到理性状态最高效的办法。')]),
        # ---- 第 4 章 给全世界立一条法 ----
        dict(n='15', title='We asked this to every guest who’s ever been on the show.',
             lines=[(950, 'We asked this to every guest', 36, 'green2', True),
                    (1030, 'who’s ever been on the show.', 34, 'green2', True),
                    (1190, '这题我们问过每一位上过节目的嘉宾', 34, 'fg', False),
                    (1330, 'every guest who’s ever done sth', 30, 'green', True)],
             speech=[('zh', '主持人铺垫最后一题：'),
                     ('en', 'We asked this to every guest who’s ever been on the show.'),
                     ('zh', '，这题我们问过每一位上过节目的嘉宾。'
                            '现在完成时加 ever 作定语从句，强调「一个都没例外」——'
                            '这比 We asked everyone 重得多，也把这一题的仪式感立起来了。')],
             source=(3668.10, 3669.70)),
        dict(n='16', title='If you could …, what would …?',
             lines=[(950, 'If you could create one law', 36, 'green2', True),
                    (1030, 'that everyone in the world', 34, 'green2', True),
                    (1110, 'had to follow, what would it be?', 30, 'green2', True),
                    (1190, '如果你能立一条全世界都得守的法，你会立什么？', 28, 'fg', False),
                    (1330, 'If you could …, what would …?', 30, 'green', True)],
             speech=[('zh', '第二条件句用来问「假设性的大问题」：'),
                     ('en', 'If you could create one law that everyone in the world had to follow, '
                            'what would it be?'),
                     ('zh', '，如果你能立一条全世界都必须遵守的法律，会是什么？'
                            'If + 过去式，主句 what would …——问的是不存在的假设，'
                            '所以动词全用虚拟语气。课堂讨论、面试、破冰都能用这套。')],
             source=(3670.20, 3674.50)),
        dict(n='17', title='stick with it',
             lines=[(950, 'at age seven or eight,', 40, 'green2', True),
                    (1030, 'you have to pick a project', 36, 'green2', True),
                    (1110, 'and stick with it for a year.', 34, 'green2', True),
                    (1190, '七八岁的时候，你得挑一个项目，然后坚持一年', 28, 'fg', False),
                    (1330, 'stick with sth', 38, 'green', True)],
             speech=[('zh', '她的答案是：'),
                     ('en', 'at age seven or eight, you have to pick a project and stick with it '
                            'for a year'),
                     ('zh', '，七八岁的时候，你得挑一个项目，然后坚持一年。'
                            'at age + 数字是「在几岁时」；stick with sth 是「坚持做下去」，'
                            '比 insist 自然得多——pick 和 stick with 连在一起用，'
                            '正好是「选定」加「坚持」这条链。')],
             source=(3680.00, 3685.40)),
        dict(n='18', title='It’s not like …',
             lines=[(950, 'It’s not like every', 42, 'green2', True),
                    (1030, 'seven-year-old needs', 40, 'green2', True),
                    (1110, 'an internship.', 42, 'green2', True),
                    (1190, '不是说每个七岁小孩都得去实习', 34, 'fg', False),
                    (1330, 'It’s not like …', 38, 'green', True)],
             speech=[('zh', '讲完主张，她马上划清边界：'),
                     ('en', 'It’s not like every seven-year-old needs an internship.'),
                     ('zh', '，不是说每个七岁小孩都得去实习。'
                            'It’s not like … 用来澄清误会、防止别人把话听极端——'
                            '口语里极高频。说主张之后补一句它，观点就不容易被误读。')],
             source=(3685.40, 3690.00)),
        dict(n='19', title='self-guided, high-agency exploration',
             lines=[(950, 'some kind of self-guided,', 36, 'green2', True),
                    (1030, 'high-agency exploration', 36, 'green2', True),
                    (1110, 'that values curiosity.', 36, 'green2', True),
                    (1190, '一种自主、高能动性、看重好奇心的探索', 30, 'fg', False),
                    (1330, 'self-guided / high-agency / value curiosity', 26, 'green', True)],
             speech=[('zh', '她给这件事下了个定义：'),
                     ('en', 'some kind of self-guided, high-agency exploration that values curiosity'),
                     ('zh', '，一种自主的、高能动性的探索，而它看重的是好奇心。'
                            'self-guided 是「自己带自己」；high-agency 我们前面讲过，'
                            '是「自己主导、自己推进」；value 在这里是动词，'
                            '「重视」——value curiosity 就是「把好奇心当回事」。')],
             source=(3690.40, 3695.00)),
        dict(n='20', title='换你来说',
             lines=[(470, 'It’s not like you need a', 40, 'green2', True),
                    (560, 'mentor for this — some', 40, 'green2', True),
                    (650, 'self-guided exploration is enough.', 32, 'green2', True),
                    (870, '你可以试着这样说', 38, 'fg', False),
                    (1090, '先立主张，再用 It’s not like 划边界', 28, 'mute', False)],
             speech=[('zh', '你也可以试着这样说。'),
                     ('en', 'It’s not like you need a mentor for this — some self-guided '
                            'exploration is enough.'),
                     ('zh', '，不是说非得有个导师才行——自己摸索就够了。')]),
        # ---- 第 5 章 收尾怎么道谢 ----
        dict(n='21', title='your X, your Y, your Z 三连致谢',
             lines=[(950, 'I’m so grateful for your time,', 34, 'green2', True),
                    (1030, 'your presence, your energy.', 34, 'green2', True),
                    (1190, '谢谢你花时间，谢谢你在场，谢谢你的能量', 32, 'fg', False),
                    (1330, 'I’m so grateful for your X, your Y, your Z', 26, 'green', True)],
             speech=[('zh', '主持人收尾的致谢，用了三个名词排比：'),
                     ('en', 'I’m so grateful for your time, your presence, your energy.'),
                     ('zh', '，谢谢你花时间、谢谢你在场、谢谢你的能量。'
                            'your X, your Y, your Z 三连铺开，比单说 thank you 有分量得多，'
                            '也比感谢的话更有画面——名字、时间、到场，各说一遍。')],
             source=(3697.10, 3699.20)),
        dict(n='22', title='be rooting for sb / in sb’s corner',
             lines=[(950, 'rooting for you and', 40, 'green2', True),
                    (1030, 'in your corner.', 44, 'green2', True),
                    (1190, '我为你加油，我站你这边', 40, 'fg', False),
                    (1330, 'be rooting for sb / be in sb’s corner', 28, 'green', True)],
             speech=[('zh', '祝福别只会说 good luck：'),
                     ('en', 'I hope this is the start of a great friendship, and I wish you all '
                            'the best, and rooting for you and in your corner.'),
                     ('zh', '，希望这是我们一段好朋友关系的开始，祝你一切都好，'
                            '我为你加油，也站在你这边。'
                            'be rooting for sb 是「为你打气」；in sb’s corner 是「站你那边」；'
                            '他后面还有一句 Here whenever you need，你需要我时我随时都在。')],
             source=(3699.80, 3704.70)),
        dict(n='23', title='I really really am so grateful.',
             lines=[(950, 'I really really am', 44, 'green2', True),
                    (1030, 'so grateful for our conversation today.', 32, 'green2', True),
                    (1110, 'I feel invigorated.', 40, 'green2', True),
                    (1190, '我真的特别感谢今天的这场对话——我觉得自己被充满了电', 28, 'fg', False),
                    (1330, 'really really am / be invigorated', 28, 'green', True)],
             speech=[('zh', '她的回礼：'),
                     ('en', 'I really really am so grateful for our conversation today. '
                            'I feel invigorated.'),
                     ('zh', '，我真的、真的很感谢今天的这场对话，我觉得自己被充满了电。'
                            '注意 am 是显性说出来的——中文母语者常漏掉这个 be 动词，'
                            '但把它说出来，诚意是加分的；invigorated 是「被注入活力」，'
                            '比 excited、refreshed 高一个档次。')],
             source=(3708.80, 3714.00)),
        dict(n='24', title='换你来说',
             lines=[(470, 'Thank you for your time and', 40, 'green2', True),
                    (560, 'your honesty — I feel', 40, 'green2', True),
                    (650, 'invigorated.', 42, 'green2', True),
                    (870, '你可以试着这样说', 38, 'fg', False),
                    (1090, '把 your X 换成你真心想谢的那两样', 30, 'mute', False)],
             speech=[('zh', '你也可以试着这样说。'),
                     ('en', 'Thank you for your time and your honesty — I feel invigorated.'),
                     ('zh', '，谢谢你的时间和你的坦诚——我觉得自己被充满了电。')]),
        # ---- 第 6 章 收尾（系列终章）----
        dict(n='25', title='带着这些点，再听一遍',
             lines=[(950, '现在再完整听一遍', 50, 'fg', False),
                    (1040, '你应该能听出更多东西了', 52, 'green', False),
                    (1210, '1 分 50 秒，20 个地道表达', 44, 'mute', False)],
             speech=[('zh', '现在带着刚才拆过的这些点，再完整听一遍这 1 分 50 秒。'
                            '这一次，你会听清主持人怎么问、她怎么用一句话答，'
                            '也会听清那句 '),
                     ('en', 'It will never be embarrassing to try'),
                     ('zh', ' 是怎么落下来的。')],
             source=(3603.70, 3714.00)),
        dict(n='26', title='跟着读三遍',
             lines=[(470, '1. It will never be', 42, 'green2', True),
                    (545, 'embarrassing to try.', 42, 'green2', True),
                    (670, '2. Define your own category.', 40, 'green2', True),
                    (795, '3. I’m rooting for you.', 42, 'green2', True)],
             speech=[('zh', '最后挑三句最常用的，跟着读一遍。'),
                     ('en', 'It will never be embarrassing to try.'),
                     ('en', 'Define your own category.'),
                     ('en', 'I’m rooting for you.'),
                     ('zh', '不用追求完美，先把它说出口。')],
             tail=3.1),
        dict(n='27', title='收藏，这一条到这儿就收尾了',
             lines=[(480, '拾句英语', 100, 'green', False),
                    (650, '两分钟，收好五个快问快答', 40, 'fg', False),
                    (850, '鼓励   It will never be embarrassing to try.', 28, 'green2', False),
                    (925, '自定义   Define your own category.', 34, 'green2', False),
                    (1000, '收尾   I’m rooting for you and in your corner.', 28, 'green2', False),
                    (1100, '这段访谈到这里就讲完了，一共 17 期。', 32, 'mute', False),
                    (1180, '听懂一句，再把它说出来。', 40, 'mute', False)],
             speech=[('zh', '这一期是这段访谈的最后一节：五个快问快答，'
                            '外加两个人的收尾致谢，学到了怎么鼓励、怎么定义自己、'
                            '怎么把感谢和祝福说得有分量。'),
                     ('zh', '这段访谈我们一共做了 17 期，到这儿就讲完了。'
                            '先收藏，下次要鼓励别人、要收尾一场谈话的时候，把这三句过一遍。'
                            '拾句英语，听懂一句，再把它说出来。')]),
    ],
)


# ---- 1.2 倍速 demo（用写日记试）----
# 两个版本一起出，方便听差别：
#   ① demo          —— 旁白提速 1.2，访谈原声保持原速（推荐：原声是学习材料，而且英文旁白本来就特意
#                      放到 0.8 倍教发音，把原声加速会跟这个设计打架）
#   ② 原声同速      —— 连原声一起 1.2 倍（画面也 setpts，声画一起快）
# work 用单独的 demo 目录：先把主片 work/elevenlabs 里的 mp3 + sha256 拷过去，
# 这样既复用 TTS 缓存（不再花钱、不再调 API），又不动主片的中间产物。
DEMO_SPEED_SPEC = dict(
    SPECS['谷爱凌_写日记'],
    speed=1.2,
    work='谷爱凌_写日记_1.2倍速demo',
    out_dir='谷爱凌_写日记',
)
SPECS['谷爱凌_写日记_1.2倍速demo'] = dict(DEMO_SPEED_SPEC)
SPECS['谷爱凌_写日记_1.2倍速demo_原声同速'] = dict(DEMO_SPEED_SPEC, speed_src=1.2)


def render(name):
    global WORK, OUT, SRC, VOICE, VOICE_SETTINGS, SUB_CY, SUB_TOP, MODEL, EN_SLOW, SHOW_URL, SHOW_FOOT
    global SPEED, SPEED_SRC
    spec = SPECS[name]
    SHOW_FOOT = spec.get('foot', False)  # 页脚：新片一律不画，下半区让给正文
    SHOW_URL = spec.get('url', False)    # 页脚里要不要放官网链接（只有老片）
    SPEED = spec.get('speed', DEFAULT_SPEED)             # 整体倍速（旁白）
    SPEED_SRC = spec.get('speed_src', DEFAULT_SPEED_SRC)  # 原声倍速，默认原速
    apply_style(spec.get('style', DEFAULT_STYLE))   # 按选题套样式预设（新片默认 v2 深色）
    apply_fonts(spec.get('fonts', DEFAULT_FONTS))   # 字体预设同样按选题走
    VOICE = spec.get('voice', DEFAULT_VOICE)        # 音色也可按选题覆盖
    MODEL = spec.get('model', DEFAULT_MODEL)        # 模型同理（v3 不支持 speed 参数，SPEC 里别写）
    VOICE_SETTINGS = spec.get('voice_settings', DEFAULT_VOICE_SETTINGS)
    EN_SLOW = spec.get('en_slow', DEFAULT_EN_SLOW)  # 英文变速倍数，1.0 = 不变速
    SUB_CY = spec.get('sub_cy', SUB_CY_DEFAULT)     # 字幕高度也按选题定（各卡文字位置不同）
    SUB_TOP = SUB_CY - SUB_BAND // 2
    SRC = spec.get('src', DEFAULT_SRC)
    # 中间产物目录默认跟选题同名；派生版（加字幕、换音色试听…）可以用 'work' 指到主片目录，
    # 这样直接复用已合成的旁白——TTS 不保证同文本同结果，重合成会让「只多了字幕」的对照组失真。
    WORK = BASE/'work'/spec.get('work', name)
    WORK.mkdir(parents=True, exist_ok=True)
    OUT = WORK/'elevenlabs'
    OUT.mkdir(parents=True, exist_ok=True)
    dest = topic_dir(spec.get('out_dir', name))   # 一个选题一个文件夹；派生版可用 out_dir 落回主片目录
    dest.mkdir(parents=True, exist_ok=True)
    segments.clear()

    limit = spec.get('limit')       # 只要前 N 秒：做「试听版」用，渲到时长够了就停
    SUBS = spec.get('subs', False)  # 带字幕版：把讲解旁白打成单行字幕，压在画中画视频底部
    total = 0.0
    for c in spec['cards']:
        a, info = speech(c['n'], c['speech']) if c.get('speech') else (None, [])
        subs = build_subs(c['n'], info) if (SUBS and info) else []
        s = c.get('source')
        if s and a:
            # 「先讲解、再听原声」：同一张卡拆两段——先用定格帧 + 旁白讲，再播原声
            start, end = s
            pa = card(c['n']+'_a', c['title'], c['lines'], still=grab_still(start, c['n']))
            segment(c['n']+'_a', pa, a, tail=0.25, subs=subs)
            pb = card(c['n']+'_b', c['title'], c['lines'])
            segment(c['n']+'_b', pb, source=True, start=start, end=end)
        elif s:
            start, end = s
            p = card(c['n'], c['title'], c['lines'])
            segment(c['n'], p, source=True, start=start, end=end)
        else:
            p = card(c['n'], c['title'], c['lines'])
            segment(c['n'], p, a, tail=c.get('tail', 0.35), subs=subs)
        total = sum(d for _, d in segments)
        if limit and total >= limit:
            print(f'  达到 {limit}s 上限，停在卡 {c["n"]}（累计 {total:.1f}s）', flush=True)
            break

    lst = WORK/'concat.txt'
    lst.write_text(''.join(f"file '{p}'\n" for p, d in segments))
    out = dest/f'{name}.mp4'
    # 注意：这块盘（云盘/外置卷）上 -movflags +faststart 会写失败，故不加
    run(['ffmpeg', '-y', '-v', 'error', '-f', 'concat', '-safe', '0', '-i', str(lst), '-c', 'copy', str(out)])
    (dest/f'{name}_说明.json').write_text(json.dumps({
        'output': str(out),
        'duration': duration(out),
        'canvas': f'{W}x{H} (9:16)',
        'voice_id': VOICE,
        'model': MODEL,
        'voice_settings': VOICE_SETTINGS,   # 记下来，否则换过参数就复现不了
        'en_slow': EN_SLOW,                 # 英文变速倍数（1.0 = 不放慢）
        'speed': SPEED,                     # 整体倍速：旁白 atempo，段长等比缩短
        'speed_src': SPEED_SRC,             # 访谈原声倍速（1.0 = 原速，默认不动）
        'subtitles': (f'讲解旁白字幕（白字 + 1px 黑描边，字号 {SUB_FS}，单行，中心线 y={SUB_CY}，'
                      f'画面中下方；原声片段不打字幕）' if SUBS else '无'),
        'source': SRC,
        'style': f'{STYLE}（{BG} 底，左右留白 {SIDE}px，页脚{FOOT_LAYOUT}对齐）',
        'fonts': f'{FONTSET}（中文 {CN.split("/")[-1]} 第 {CN_IDX} 号字面；西文 {EN.split("/")[-1]}'
                 + (f'；页脚网址固定 {EN_UI.split("/")[-1]}）' if (SHOW_FOOT and SHOW_URL) else '）'),
        'palette': {'底': BG, '主文字': FG, '次要文字': MUTE, '主强调': GREEN, '次强调': GREEN2,
                    '品牌绿原色': BRAND, '分隔线': LINE,
                    '来源': '拾句英语官网首页（品牌绿 #2DCE7B）'},
        'segments': [{'file': p.name, 'duration': d} for p, d in segments],
        'source_clips': [{'card': c['n'], 'start': c['source'][0], 'end': c['source'][1]}
                         for c in spec['cards'] if c.get('source')],
        'notes': [
            '画布 1080×1920（9:16）；上方留白 190px、下方留白 417px，避开小红书顶部/底部 UI 遮挡区。',
            '原片切点用本地语音识别（whisper small）逐词定位，并对切出的片段二次识别复核。',
            '原片使用高清素材（1920×1080），画中画缩放到 810×456。',
            f'中英文旁白统一使用 Voice ID {VOICE}（{MODEL}）；'
            + (f'英文按 {EN_SLOW} 倍放慢，中文原速。' if EN_SLOW != 1.0 else '中英均原速，英文不放慢。'),
            (f'整体倍速 {SPEED}（旁白 atempo；访谈原声 {SPEED_SRC} 倍）。' if SPEED != 1.0 or SPEED_SRC != 1.0
             else '整体原速（未做倍速）。'),
            (f'页脚品牌条：logo + {BRAND_NAME} + '
             + (f'{BRAND_URL}（{FOOT_LAYOUT} 对齐）。' if SHOW_URL else f'{BRAND_TAIL}。')
             if SHOW_FOOT else
             '无页脚（2026-09 起整条不画：官网链接会被小红书判成站外引流限流，'
             '去掉底部分隔线与页脚后，正文下沿从 1380 延到 1470，1503 是平台 UI 安全线）。'),
            ('配色取自官网首页；v2 深色版用官网正文色 #191918 作底、品牌绿 #2DCE7B 作强调'
             '（对比度 8.1:1），因为小红书官方按钮是白色，浅底上会糊在一起。'
             if STYLE == 'v2' else
             '配色取自官网首页：米白底 + 墨黑字 + 品牌绿（v1 浅色版，2026-09 前使用）。'),
            f'左右留白 {SIDE}px：视频在小红书被缩放显示后，可保证文字不贴边。' if STYLE == 'v2' else '',
            '迁移例句为原创练习，非访谈原话。',
            '未发布。',
        ],
    }, ensure_ascii=False, indent=2))
    print('DONE', out, duration(out), flush=True)


if __name__ == '__main__':
    names = sys.argv[1:] or list(SPECS)
    for n in names:
        render(n)
