"""拾句英语 · 音色调试台

专用来调旁白音色与语调参数，不碰视频渲染。一轮 = 一批「同一套文本、不同音色/参数」的短音频，
外加一条带序号提示音的连播文件（方便一口气 A/B），最后把结果记进 ../台账.md。

用法（工作目录必须是 音色调试/）：
    /opt/homebrew/bin/python3 _tools/voice_lab.py R01      # 跑第 R01 轮
    /opt/homebrew/bin/python3 _tools/voice_lab.py          # 列出所有轮次

设计约定：
  · 合成链路直接复用成片渲染器的实现（同一个 key、同一个缓存签名、同一个请求体），
    这样在这里选出来的参数，写回 build.py 后听感完全一致。
  · 只出音频样本，不出视频；选定了再回填 build.py 的 DEFAULT_VOICE_SETTINGS。
  · 指标由 prosody.py 量，只做相对比较，最终结论靠耳朵。
"""
import json
import shutil
import subprocess as sp
import sys
import time
from pathlib import Path

import numpy as np

BASE = Path(__file__).resolve().parent.parent      # 音色调试/
sys.path.insert(0, str(BASE / '_tools'))
sys.path.insert(0, '__DATA_ROOT__/小红书发帖-拾句英语/精细讲解视频/_tools')

import build as B          # noqa: E402  复用它的 load_key / request / tts
import prosody             # noqa: E402

SR = 44100

# ---- 试听文本 ----
# 真实旁白取自成片（用户反馈中文语调不对的那些），通用句型用来覆盖不同语气。
TEXTS = {
    'T1': ('真实旁白·中文长句（含问句和破折号）',
           '简历之外，你希望别人知道你什么？这段 2 分 5 秒的访谈里，谷爱凌回答了一个最难的问题'
           '——怎么让人看见「运动员」标签之外的自己。'),
    'T2': ('真实旁白·中英混排（最容易露馅）',
           '我是我们高中历史上第一个提前毕业的人。结构是 the first 加人 加 in 加范围 加 to do，'
           '这里的 to do 是不定式做定语，不能写成 doing。'),
    'T3': ('通用·陈述加举例',
           '这句话在口语里出现的频率很高，比如约人吃饭、约人开会都能用得上。'),
    'T4': ('通用·疑问加转折',
           '那怎么办呢？其实很简单，先把它说出口，剩下的再慢慢改。'),
    'T5': ('通用·列举',
           '第一，看它在句子里的位置；第二，看它后面接什么介词；第三，看它用在正式场合还是随口说说。'),
    'T6': ('通用·强调与长句',
           '真正的关键，不是你背了多少个单词，而是你能不能在需要的那一刻，把它稳稳地说出来。'),
}

V = '__VOICE_ID__'      # 主片音色，这轮只扫参数和模型


def arm(tag, model='eleven_multilingual_v2', stability=0.45, style=0.0, boost=True, **extra):
    s = {'stability': stability, 'similarity_boost': 0.75, 'style': style,
         'use_speaker_boost': boost}
    s.update(extra)
    return dict(tag=tag, model=model, voice=V, settings=s)


ROUNDS = {
    # R01：中文语调到底卡在哪——是 style 不够，还是 stability 太稳，还是模型本身不适合中文
    'R01': dict(
        texts=['T1', 'T2'],
        arms=[
            arm('01_base-mv2-s0.0', style=0.0, speed=1.0),
            arm('02_mv2-s0.4', style=0.4, speed=1.0),
            arm('03_mv2-s0.4-st0.30', stability=0.30, style=0.4, speed=1.0),
            arm('04_mv2-s0.6-st0.30', stability=0.30, style=0.6, speed=1.0),
            arm('05_mv2-s0.4-无boost', style=0.4, boost=False, speed=1.0),
            arm('06_turbo2.5-s0.4', model='eleven_turbo_v2_5', style=0.4, speed=1.0),
            arm('07_v3-s0.4', model='eleven_v3', style=0.4),
        ],
    ),
}


def synth(text, a, out):
    """按某组参数合成一条。失败（模型没权限、参数不支持、偶发网络错）就返回错误文本，不中断整轮。"""
    B.VOICE, B.MODEL, B.VOICE_SETTINGS = a['voice'], a['model'], a['settings']
    for attempt in range(3):
        try:
            B.tts(text, out)
            return None
        except SystemExit as e:
            err = str(e)
            if 'SSLError' in err or 'Timeout' in err or 'TimeoutError' in err:
                time.sleep(2 + 2 * attempt)      # 偶发网络错，隔几秒再来一次
                continue
            return err
    return err


def decode(p, sr=SR, ch=2):
    raw = sp.check_output(['ffmpeg', '-v', 'error', '-i', str(p), '-ar', str(sr),
                           '-ac', str(ch), '-f', 'f32le', '-'])
    return np.frombuffer(raw, dtype='<f4').reshape(-1, ch)


def write_audio(a, out, sr=SR):
    sp.run(['ffmpeg', '-y', '-v', 'error', '-f', 'f32le', '-ar', str(sr), '-ac', str(a.shape[1]),
            '-i', '-', '-c:a', 'libmp3lame', '-b:a', '160k', str(out)],
           input=a.astype('<f4').tobytes(), check=True)


def silence(sec, ch=2, sr=SR):
    return np.zeros((int(sr * sec), ch), np.float32)


def beeps(n, ch=2, sr=SR, f=900, dur=0.12, gap=0.07):
    """n 声短提示音，用来标记连播文件里第几段是哪个方案。"""
    t = np.arange(int(sr * dur)) / sr
    tone = (0.32 * np.sin(2 * np.pi * f * t) * np.hanning(len(t))).astype(np.float32)
    unit = np.tile(tone[:, None], (1, ch))
    out = []
    for _ in range(n):
        out += [unit, silence(gap, ch, sr)]
    return np.concatenate(out) if out else silence(0, ch, sr)


def compare(rows, out):
    """把同一条文本的各方案串成一条：N 声提示音 + 音频，方便一口气听。"""
    parts = []
    for i, r in enumerate(rows):
        parts += [beeps(i + 1), silence(0.25), decode(r['path']), silence(0.7)]
    write_audio(np.concatenate(parts), out)


def markdown(rid, spec, texts, rows):
    L = [f'## {rid} · 参数扫描（音色 `{V}`）', '',
         '**这轮想回答**：句子层面的中文语调不对，到底是 style 不够、stability 太稳，还是模型不适合中文。', '',
         '**怎么听**：先听 `对比_<文本>_按序号带提示音.mp3`——1 声＝01 号方案，2 声＝02 号，依次类推；'
         '再挑有感觉的单条反复听。', '',
         '| # | 方案 | 模型 | stability | style | boost | 其他 |', '|---|---|---|---|---|---|---|']
    for a in spec['arms']:
        s = a['settings']
        other = ', '.join(f'{k}={v}' for k, v in s.items()
                          if k not in ('stability', 'style', 'use_speaker_boost',
                                       'similarity_boost', 'speed') or (k == 'speed' and v != 1.0))
        L.append(f"| {a['tag'].split('_')[0]} | {a['tag'].split('_',1)[1]} | {a['model']} | "
                 f"{s['stability']} | {s['style']} | {'on' if s['use_speaker_boost'] else 'off'} | {other or '—'} |")
    L += ['', '### 试听文本', '']
    for t in texts:
        L += [f"**{t}** · {TEXTS[t][0]}", '', f"> {TEXTS[t][1]}", '']
    L += ['### 指标（语调跨度 / 抖动 都是半音，越大越起伏；抖动大＝忽高忽低）', '',
          '| 文本 | 方案 | 时长(s) | 语速(字/s) | 基频中位(Hz) | 语调跨度 | 抖动 | 停顿/秒 | 你的结论 |',
          '|---|---|---|---|---|---|---|---|---|']
    for r in rows:
        if r.get('err'):
            L.append(f"| {r['text']} | {r['tag']} | — | — | — | — | — | — | 合成失败 |")
            continue
        m = r['m']
        L.append(f"| {r['text']} | {r['tag']} | {m['dur']} | {m['speech_rate']} | {m['f0']} | "
                 f"{m['range_st']} | {m['jitter_st']} | {m['pauses']} | |")
    L += ['', '**自动观察**：']
    for t in texts:
        rs = [r for r in rows if r['text'] == t and r.get('m') and r['m']['range_st'] is not None]
        if len(rs) < 2:
            continue
        hi = max(rs, key=lambda r: r['m']['range_st'])
        lo = min(rs, key=lambda r: r['m']['range_st'])
        ji = max(rs, key=lambda r: r['m']['jitter_st'])
        L.append(f"- {t}：语调跨度最大 `{hi['tag']}`（{hi['m']['range_st']}），最小 `{lo['tag']}`"
                 f"（{lo['m']['range_st']}）；抖动最大 `{ji['tag']}`（{ji['m']['jitter_st']}）")
    errs = [r for r in rows if r.get('err')]
    if errs:
        L += ['', '**失败项**：', '']
        for r in errs:
            L.append(f"- `{r['tag']}`（{r['text']}）：{r['err']}")
    L += ['', '**结论**：（听完在这里写：哪一组最自然、差在哪）', '', '---', '']
    return '\n'.join(L)


def write_ledger(rid, section):
    f = BASE / '台账.md'
    header = ('# 拾句英语 · 音色调试台账\n\n'
              '每轮一批短音频放在 `samples/<轮次>/`，这里是参数、指标和结论。\n'
              '重跑同一轮会覆盖该轮小节（样本按 音色+文本+参数 的 sha256 缓存，不会重复扣费）。\n\n---\n\n')
    old = f.read_text() if f.exists() else header
    head = f'## {rid} ·'
    i = old.find(head)
    if i < 0:
        new = old + section
    else:
        j = old.find('\n## ', i + len(head))
        new = old[:i] + section + (old[j + 1:] if j >= 0 else '')
    f.write_text(new)


def run(rid):
    spec = ROUNDS[rid]
    dest = BASE / 'samples' / rid
    cache = dest / '.cache'      # 合成落在隐藏目录：缓存签名（.sha256）就不会混在试听文件里
    cache.mkdir(parents=True, exist_ok=True)
    rows = []
    for t in spec['texts']:
        title, text = TEXTS[t]
        trows = []
        for a in spec['arms']:
            name = f"{t}_{a['tag']}.mp3"
            p = dest / name
            err = synth(text, a, cache / name)
            if err:
                print(f'  ✗ {t} {a["tag"]}：{err}', flush=True)
                rows.append(dict(text=t, tag=a['tag'], path=None, err=err))
                continue
            shutil.copy(cache / name, p)
            m = prosody.probe(p, text)
            print(f'  ✓ {t} {a["tag"]}  {m["dur"]}s  跨度{m["range_st"]}  抖动{m["jitter_st"]}',
                  flush=True)
            r = dict(text=t, tag=a['tag'], path=p, m=m)
            rows.append(r)
            trows.append(r)
        if len(trows) >= 2:
            out = dest / f'对比_{t}_按序号带提示音.mp3'
            compare(trows, out)
            print(f'  → {out.name}', flush=True)
    write_ledger(rid, markdown(rid, spec, spec['texts'], rows))
    print(f'DONE {rid}  {len([r for r in rows if not r.get("err")])} 条样本  {dest}', flush=True)


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] in ROUNDS:
        run(sys.argv[1])
    else:
        for k, v in ROUNDS.items():
            print(k, v['texts'], [a['tag'] for a in v['arms']])
