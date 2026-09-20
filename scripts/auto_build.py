"""拾句英语 · 队列自动出片（定时任务用）

到点把「已经备好 SPEC 的选题」从渲染一路做到配套齐全：
    版面自检 → 规格扫描 → 渲染 → 成片校验 → 封面 → 精讲笔记 PDF → 讲解字幕 SRT → 目录加序号

**创意活它做不了**（选题拆解、写脚本、定切点、写文案仍由人/agent 先备好），它只负责机械步骤。
队列写在 `_tools/队列.json`，一个选题一条；成片已存在的自动跳过，所以重复跑是安全的。

用法：
    cd <精细讲解视频目录>
    /opt/homebrew/bin/python3 _tools/auto_build.py            # 按队列跑一遍
    /opt/homebrew/bin/python3 _tools/auto_build.py --dry-run  # 只体检不渲染
    /opt/homebrew/bin/python3 _tools/auto_build.py --only 09  # 只跑某一条
    /opt/homebrew/bin/python3 _tools/auto_build.py --wait 240 # 守着队列：没备好的等，备好了自动渲（定时任务用）

`--wait N`：每 2 分钟重读一次队列，最多守 N 分钟。定时任务 18:10 起就是用这个模式——
创意部分（SPEC / 封面文案 / 表达详解）还没备好的条目先等着，一备好就自动接着做，
全部做完或超时就退出。这样不必掐着「脚本写完」的时间点。

日志：`_tools/logs/auto_build_<时间戳>.log`
"""
import json
import re
import subprocess as sp
import sys
import time
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent
SERIES = BASE.parent
sys.path.insert(0, str(BASE))
import build as B                     # noqa: E402
import covers as C                    # noqa: E402

PROJ = Path('__WORKSPACE__/projects/eileen-gu-on-purpose')
QUEUE = BASE/'队列.json'
LOGDIR = BASE/'logs'
REF = '谷爱凌_训练日常'                # 规格基准片（新规格代表作）
DRY = '--dry-run' in sys.argv
ONLY = sys.argv[sys.argv.index('--only') + 1] if '--only' in sys.argv else None
WAIT = int(sys.argv[sys.argv.index('--wait') + 1]) if '--wait' in sys.argv else 0

LOG = []


def log(msg):
    line = f'[{datetime.now():%H:%M:%S}] {msg}'
    print(line, flush=True)
    LOG.append(line)


def sh(cmd, **kw):
    return sp.run(cmd, capture_output=True, text=True, **kw)


# ---------- 各步 ----------

def check_spec(name):
    """规格扫描：与基准片逐项比对（这是「出片前扫规格」那一步的脚本化）。"""
    if name not in B.SPECS:
        return False, f'SPECS 里没有 {name}'
    s, r = B.SPECS[name], B.SPECS[REF]
    got = dict(fonts=s.get('fonts', B.DEFAULT_FONTS), model=s.get('model', B.DEFAULT_MODEL),
               style=s.get('voice_settings', B.DEFAULT_VOICE_SETTINGS).get('style'),
               speed=s.get('speed', B.DEFAULT_SPEED), foot=s.get('foot', False))
    exp = dict(fonts=r.get('fonts', B.DEFAULT_FONTS), model=r.get('model', B.DEFAULT_MODEL),
               style=r.get('voice_settings', B.DEFAULT_VOICE_SETTINGS).get('style'),
               speed=r.get('speed', B.DEFAULT_SPEED), foot=r.get('foot', False))
    if got != exp:
        return False, f'规格与基准片不一致：{got} ≠ {exp}'
    return True, f"规格 OK（{got['fonts']} / {got['model']} / style {got['style']} / {got['speed']}x / 无页脚）"


def check_layout(name):
    """版面自检：出界 / 压行 / 越下沿 / 压画中画。"""
    from PIL import ImageFont
    B.apply_style(B.SPECS[name].get('style', B.DEFAULT_STYLE))
    pip, bot = (135, 470, 945, 926), 1470
    bad = []
    for c in B.SPECS[name]['cards']:
        rows = []
        for y, s, size, col, en in c['lines']:
            f = ImageFont.truetype(B.EN if en else B.CN, size)
            b = f.getbbox(s)
            rows.append((y, y + b[1], y + b[3], b[2] - b[0], s))
        for _, _, _, w, s in rows:
            if B.SIDE + w > B.RIGHT:
                bad.append(f"{c['n']} 出界「{s[:14]}」")
        rs = sorted(rows)
        for i in range(1, len(rs)):
            if rs[i][1] < rs[i-1][2]:
                bad.append(f"{c['n']} 压行")
        for _, _, bt, _, _ in rows:
            if bt > bot:
                bad.append(f"{c['n']} 越下沿")
        if c.get('source'):
            for _, t, bt, _, s in rows:
                if t < pip[3] and bt > pip[1]:
                    bad.append(f"{c['n']} 压画中画「{s[:12]}」")
    return (not bad), ('版面自检 0 问题' if not bad else '；'.join(bad[:4]))


def render(name):
    r = sh(['/opt/homebrew/bin/python3', str(BASE/'build.py'), name], cwd=str(SERIES))
    tail = (r.stdout or '').strip().split('\n')[-1:] or ['']
    return r.returncode == 0, tail[0][:120]


def verify(name, d):
    """五项：尺寸 / 原声完整 / 停顿 / 留白 / 配色。原声抽查按 SOP 带 0.4 秒余量。"""
    film = d/f'{name}.mp4'
    info = json.loads((d/f'{name}_说明.json').read_text())
    notes, ok = [], True
    r = sh(['ffprobe', '-v', 'error', '-select_streams', 'v:0',
            '-show_entries', 'stream=width,height', '-show_entries', 'format=duration',
            '-of', 'default=noprint_wrappers=1', str(film)])
    notes.append('　尺寸 ' + r.stdout.strip().replace('\n', ' '))
    if 'width=1080' not in r.stdout or 'height=1920' not in r.stdout:
        ok = False
        notes.append('　✗ 尺寸不对')
    # 停顿
    r = sh(['ffmpeg', '-hide_banner', '-i', str(film), '-af', 'silencedetect=noise=-45dB:d=2.5',
            '-f', 'null', '-'])
    pauses = [l.split('silence_duration: ')[-1] for l in r.stderr.splitlines() if 'silence_duration' in l]
    notes.append(f"　长留白 {len(pauses)} 处 {[round(float(x),1) for x in pauses][:3]}")
    if not pauses:
        ok = False
        notes.append('　✗ 没有 3 秒左右的跟读停顿')
    # 原声抽查：最长的一段 + 首尾各一段短的，带 0.4 秒余量
    t, clips, orig = 0.0, [], []
    for s in info['segments']:
        clips.append((s['file'][:-4], t, t + s['duration']))
        if s['file'][:-4].endswith('_b'):
            orig.append((s['file'][:-4], t, t + s['duration']))
        t += s['duration']
    picks = sorted(orig, key=lambda x: -(x[2] - x[1]))[:1] + orig[:1] + orig[-1:]
    try:
        from faster_whisper import WhisperModel
        m = WhisperModel('small', device='cpu', compute_type='int8')
        for key, a, b in picks:
            f = f'/tmp/ab_{key}.wav'
            sh(['ffmpeg', '-y', '-v', 'error', '-ss', str(max(a - 0.4, 0)), '-to', str(b + 0.4),
                '-i', str(film), '-ac', '1', '-ar', '16000', f])
            segs, _ = m.transcribe(f, word_timestamps=False, language='en',
                                   condition_on_previous_text=False)
            txt = ' '.join(s.text.strip() for s in segs)
            notes.append(f'　原声 {key}：{txt[:70]}')
    except Exception as e:                                   # ASR 不可用不该让整条失败
        notes.append(f'　（原声抽查跳过：{e}）')
    return ok, notes


def make_cover(item):
    name = item['name']
    if name not in C.COVERS:
        return False, '没有写封面文案（covers.py 的 COVERS）'
    if C.COVERS[name]['kind'] not in C.FRAMES:
        return False, '没有选封面帧（covers.py 的 FRAMES）'
    proj = Path.cwd()
    r = sh(['/opt/homebrew/bin/python3', str(BASE/'covers.py'), name], cwd=str(SERIES))
    return r.returncode == 0, (r.stdout or r.stderr).strip().split('\n')[-1][:100] or 'ok'


def make_pdf(item, outdir):
    md = PROJ/item['md']
    if not md.exists():
        return False, f'缺 {item["md"]}（表达详解还没写）'
    cmd = ['/opt/homebrew/bin/python3', str(BASE/'handout.py'), str(md), str(BASE/'handout'),
           item['title'], item['sub']]
    prac = PROJ/item.get('practice', '')
    if prac and Path(prac).exists():
        cmd.append(str(prac))
    r = sh(cmd, cwd=str(PROJ))
    if r.returncode != 0:
        return False, (r.stderr or '').strip()[-120:]
    src = BASE/f'handout/{re.sub(r"[^\w\u4e00-\u9fa5]+", "_", item["title"])}.pdf'
    dst = outdir/f'{item["name"]}_精讲笔记.pdf'
    if src.exists():
        dst.write_bytes(src.read_bytes())
        return True, f'{dst.name}（{dst.stat().st_size/1024:.0f} KB）'
    return False, f'PDF 没生成（{src.name}）'


def make_srt(name):
    r = sh(['/opt/homebrew/bin/python3', str(BASE/'make_srt.py'), name], cwd=str(SERIES))
    ok = r.returncode == 0
    tail = (r.stdout or '').strip().split('\n')[-1:]
    return ok, (tail[0][:120] if tail else '（无输出）')


def rename_dir(prefix, name):
    plain, prefixed = SERIES/name, SERIES/f'{prefix}_{name}'
    if prefixed.exists() or not plain.exists():
        return prefixed if prefixed.exists() else plain
    plain.rename(prefixed)
    return prefixed


# ---------- 主流程 ----------

def wrapup(item, d):
    """成片已在，把缺的配套补齐；缺创意部分（表达详解）就返回 wait，等下一次循环。"""
    name, pend = item['name'], False
    if not (d/f'{name}.srt').exists():
        ok, msg = make_srt(name)
        log(f'  {"✓" if ok else "✗"} 字幕：{msg}')
    if not (d/f'{name}_封面.png').exists():
        ok, msg = make_cover(item)
        log(f'  {"✓" if ok else "✗"} 封面：{msg}')
        pend |= not ok
    if not (d/f'{name}_精讲笔记.pdf').exists():
        ok, msg = make_pdf(item, d)
        log(f'  {"✓" if ok else "⏳"} 精讲笔记：{msg}')
        pend |= (not ok)
    if pend:
        return 'wait'
    log(f'  ✅ 配套齐全：{d}')
    return 'done'


def run_item(item):
    prefix, name = item['prefix'], item['name']
    log('=' * 62)
    log(f'▶ {prefix}｜{name}')
    if name not in B.SPECS:
        log('  ⏳ 等：SPEC 还没登记（创意部分未备好）')
        return 'wait'
    d = B.topic_dir(name)
    if (d/f'{name}.mp4').exists():
        log(f'  · 成片已存在（{(d/f"{name}.mp4").stat().st_size/1e6:.0f} MB），只补配套')
        return wrapup(item, d)
    ok, msg = check_spec(name)
    log(f'  {"✓" if ok else "✗"} 规格：{msg}')
    if not ok:
        return 'failed'
    ok, msg = check_layout(name)
    log(f'  {"✓" if ok else "✗"} 版面：{msg}')
    if not ok:
        return 'failed'
    if DRY:
        log('  （dry-run：到此为止，不渲染）')
        return 'dry'
    ok, msg = render(name)
    log(f'  {"✓" if ok else "✗"} 渲染：{msg}')
    if not ok:
        return 'failed'
    d = rename_dir(prefix, name)
    ok, notes = verify(name, d)
    for n in notes:
        log(n)
    log(f'  {"✓" if ok else "✗"} 成片校验：{"五项通过" if ok else "有项不通过"}')
    return wrapup(item, d)


def main():
    if not QUEUE.exists():
        print(f'没有队列文件：{QUEUE}')
        return 1
    LOGDIR.mkdir(exist_ok=True)
    deadline = time.time() + WAIT * 60
    round_no, res = 0, {}
    while True:
        round_no += 1
        queue = json.loads(QUEUE.read_text())
        if ONLY:
            queue = [q for q in queue if q['prefix'] == ONLY]
        log(f'—— 第 {round_no} 轮｜队列 {len(queue)} 条：'
            + '、'.join(q['prefix'] for q in queue) + ('（dry-run）' if DRY else ''))
        res = {}
        for item in queue:
            try:
                res[item['prefix']] = run_item(item)
            except Exception as e:                            # 单条失败不拖垮后面
                log(f'  ✗ 异常：{type(e).__name__}: {e}')
                res[item['prefix']] = 'failed'
        log('小结：' + '；'.join(f'{k}={v}' for k, v in res.items()))
        waiting = [k for k, v in res.items() if v == 'wait']
        if DRY or not WAIT or not waiting:
            break
        if time.time() > deadline:
            log(f'⏹ 守候超时（{WAIT} 分钟），还没备好的：{"、".join(waiting)}')
            break
        log(f'⏳ 还有 {"、".join(waiting)} 没备好，2 分钟后再看一次…')
        time.sleep(120)
    p = LOGDIR/f'auto_build_{datetime.now():%Y%m%d_%H%M}.log'
    p.write_text('\n'.join(LOG) + '\n')
    log(f'日志：{p}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
