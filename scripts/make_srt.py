"""拾句英语 · 从成片反推字幕（SRT）

**文本**用脚本里的旁白原文——那是权威版本，不受 ASR 错字影响。
**时间轴**用本地 ASR（faster-whisper）的词级时间戳，按「脚本字符 ⇄ ASR 字符」的对齐结果反推。

为什么不对着旁白缓存算：缓存会被清（清过一次），清掉之后就推不出每段旁白的内部时间；
而 ASR 读的是成片本身，任何时候都能重建，换音色 / 改文案 / 重渲都不会失配。
唯一错位风险是 ASR 把某句听错——靠 difflib 的匹配块做锚点，再把没锚上的字符线性插值补回来。
某一卡锚点实在太少（含整句英文跟读的卡最常见），就把这一段剪出来单独再转一遍
（`transcribe_seg`）：段内上下文短，准确率高得多。

用法（工作目录：精细讲解视频/）：
    python3 _tools/make_srt.py <选题> [<选题> ...]

产物：`<选题>/<选题>.srt`。原声片段（只播访谈、没有旁白的那几段）不打字幕，
要的话可以从修正版 SRT 按切点平移过来。
"""
import difflib
import json
import re
import subprocess as sp
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
import build as B          # noqa: E402

MODEL_SIZE = 'small'       # 只用来对时间，不需要它把字听对
ASR_SR = 16000
# whisper 的中文输出经常是繁体、还会把专有名词听错，这些都会让「逐字对齐」掉锚点：
# 用 initial_prompt 把它往简体+领域词上引，再用一张常用繁→简表兜底。
ASR_PROMPT = '以下是简体中文普通话，中间夹杂英文单词。拾句英语，谷爱凌，访谈，口语表达。'
TRAD2SIMP = str.maketrans({
    '聽': '听', '說': '说', '後': '后', '會': '会', '麼': '么', '個': '个', '沒': '没',
    '裡': '里', '這': '这', '來': '来', '對': '对', '時': '时', '學': '学', '誰': '谁',
    '點': '点', '現': '现', '應': '应', '們': '们', '過': '过', '還': '还', '開': '开',
    '關': '关', '問': '问', '題': '题', '語': '语', '詞': '词', '練': '练', '習': '习',
    '錯': '错', '樣': '样', '種': '种', '發': '发', '覺': '觉', '讓': '让', '帶': '带',
    '給': '给', '經': '经', '實': '实', '際': '际', '臉': '脸', '樂': '乐', '幾': '几',
    '節': '节', '總': '总', '結': '结', '簡': '简', '單': '单', '難': '难', '係': '系',
    '夠': '够', '幹': '干', '嗎': '吗', '誒': '诶', '喲': '哟', '產': '产', '場': '场',
    '準': '准', '錄': '录', '譯': '译', '讀': '读', '寫': '写', '記': '记', '單': '单',
})


def norm(s):
    """对齐用的归一化：繁体转简体，只留汉字/字母/数字，英文小写，去掉标点与空格。"""
    return ''.join(ch.lower() for ch in s.translate(TRAD2SIMP) if ch.isalnum())


def units(s):
    """长度口径：一个汉字算 1，一个西文字符算 0.5。"""
    return sum(1 if '\u4e00' <= ch <= '\u9fff' else 0.5 for ch in s)


def cut_cues(text, target=14.0, hard=22.0):
    """把一段旁白切成字幕条：优先在句末断，其次在逗号/顿号，最后才硬断。
    target/hard 都是「显示宽度」口径（一个汉字 1、一个西文字符 0.5）。"""
    soft, strong = '，、；：,;:', '。！？…!?'
    cues, cur, w = [], '', 0.0
    for ch in text:
        cur += ch
        w += 1 if '\u4e00' <= ch <= '\u9fff' else 0.5
        if ch in strong and w >= target * 0.6:
            cues.append(cur); cur, w = '', 0.0
        elif ch in soft and w >= target:
            cues.append(cur); cur, w = '', 0.0
        elif w >= hard:
            i = max(cur.rfind(' '), cur.rfind('，'), cur.rfind(','))
            if i > len(cur) * 0.4:
                cues.append(cur[:i+1]); cur = cur[i+1:]
            else:
                cues.append(cur); cur = ''
            w = units(cur)
    if cur.strip():
        cues.append(cur)
    cues = [c.strip() for c in cues if c.strip()]
    # 硬断是按「显示宽度」切的，可能正好切在句末标点之前——
    # 那样下一条会以「。」开头、上一条反而没句号。把标点归回上一条。
    # 用 while 而不是 if：连着两三个标点（比如「……。」）要一次搬干净。
    for i in range(1, len(cues)):
        while cues[i][:1] and cues[i][0] in strong:
            cues[i-1] += cues[i][0]
            cues[i] = cues[i][1:]
    return [c for c in cues if c]


def tokenize(s):
    """切成对齐用的 token：中文按字，西文按词。返回 [(token, 原串起, 原串止)]。"""
    out, i, n = [], 0, len(s)
    while i < n:
        ch = s[i]
        if ch.isascii() and ch.isalnum():
            j = i
            while j < n and s[j].isascii() and s[j].isalnum():
                j += 1
            out.append((s[i:j].lower(), i, j))
            i = j
        elif ch.isalnum():
            out.append((ch.translate(TRAD2SIMP), i, i + 1))
            i += 1
        else:
            i += 1
    return out


def char_times(text, words):
    """脚本每个「字母数字字符」的 (起, 止) 时刻（按出现顺序展平）。

    字幕**起点取首字的「起」、结束取末字的「止」**——早先一律取「止」，
    结果每条都晚半个字（中文 0.2–0.35 秒）才出现。

    对齐按 token 走，不按字符：ASR 漏掉一整段英文时，损失的是 1 个 token 而不是二十个字符，
    锚点比例才不会被拖垮；没锚上的 token 在左右锚点之间线性插值。
    """
    st = tokenize(text)
    at, atime = [], []
    for w, s_, e_ in words:
        toks = tokenize(w)
        if not toks:
            continue
        step = (e_ - s_) / len(toks)
        for k, (tok, _, _) in enumerate(toks):
            at.append(tok)
            atime.append((s_ + k * step, s_ + (k + 1) * step))
    if not at or not st:
        return None
    sm = difflib.SequenceMatcher(None, [t for t, _, _ in st], at, autojunk=False)
    j = {}
    for a, b, size in sm.get_matching_blocks():
        for k in range(size):
            j[a + k] = b + k
    if len(j) < len(st) * 0.6:              # 锚点太少说明这段 ASR 没听出来，交给调用方兜底
        return None
    keys = sorted(j)
    span = [None] * len(st)
    for k in range(len(st)):
        if k in j:
            span[k] = atime[j[k]]
        else:
            lo = max([x for x in keys if x < k], default=None)
            hi = min([x for x in keys if x > k], default=None)
            if lo is None:
                span[k] = atime[j[hi]]
            elif hi is None:
                span[k] = atime[j[lo]]
            else:
                r = (k - lo) / (hi - lo)
                span[k] = (atime[j[lo]][1], atime[j[hi]][0])
                span[k] = (span[k][0] + (span[k][1] - span[k][0]) * r,) * 2
    for k in range(1, len(span)):           # 保证单调，字幕不会倒着跳
        span[k] = (max(span[k][0], span[k-1][0]), max(span[k][1], span[k-1][1]))
    ct = []
    for (tok, _, _), (s_, e_) in zip(st, span):
        L = len(tok)
        ct += [(s_ + (e_ - s_) * c / L, s_ + (e_ - s_) * (c + 1) / L) for c in range(L)]
    return ct


_MODEL = None


def transcribe(wav, lang=None):
    global _MODEL
    if _MODEL is None:                  # 段内补转会再调它几次，模型只加载一次
        from faster_whisper import WhisperModel
        _MODEL = WhisperModel(MODEL_SIZE, device='cpu', compute_type='int8')
    segs, _ = _MODEL.transcribe(str(wav), word_timestamps=True, vad_filter=True,
                                condition_on_previous_text=False,
                                language=lang,
                                # 指定英文时不要塞中文提示词，否则反而把英文带偏
                                initial_prompt=None if lang == 'en' else ASR_PROMPT)
    words = []
    for s in segs:
        for w in (s.words or []):
            words.append((w.word, w.start, w.end))
    return words


def cut_seg(wav, t0, dur):
    """把某一段剪出来单独转写用，返回临时文件路径。

    整片转写时上下文很长，含**整句英文跟读**的卡（英文由中文音色念出）经常被听岔或吞掉，
    token 锚点率就掉到 60% 以下。剪成 20–30 秒再转，上下文短、准确率高得多。
    """
    clip = Path('/tmp')/f'{wav.stem}_seg.wav'
    sp.run(['ffmpeg', '-y', '-v', 'error', '-ss', f'{t0:.3f}', '-t', f'{dur:.3f}',
            '-i', str(wav), '-ac', '1', '-ar', str(ASR_SR), str(clip)], check=True)
    return clip


def ts(t):
    h, rem = divmod(max(t, 0), 3600)
    m, s = divmod(rem, 60)
    return f'{int(h):02d}:{int(m):02d}:{s:06.3f}'.replace('.', ',')


def make(name):
    spec = B.SPECS[name]
    dest = B.topic_dir(name)           # 系列顶层带 01_/02_ 序号前缀，靠 topic_dir 找
    info = json.loads((dest/f'{name}_说明.json').read_text())
    # 成片 → 音频（一次全片转写，别按段反复加载模型）
    wav = Path('/tmp')/f'{name}_asr.wav'
    sp.run(['ffmpeg', '-y', '-v', 'error', '-i', str(dest/f'{name}.mp4'),
            '-ac', '1', '-ar', str(ASR_SR), str(wav)], check=True)
    words = transcribe(wav)
    print(f'  ASR 得到 {len(words)} 个词', flush=True)

    cards = {c['n']: c for c in spec['cards']}
    rows, t0 = [], 0.0
    for s in info['segments']:
        key, seg = s['file'][:-4], s['duration']
        card = cards.get(key) or (cards.get(key[:-2]) if key[-2:] in ('_a', '_b') else None)
        narr = None
        if card and card.get('speech'):
            if key.endswith('_a'):
                tail = 0.25
            elif not key.endswith('_b'):
                tail = card.get('tail', 0.35)
            else:
                tail = None                     # 原声段，没旁白
            if tail is not None:
                narr = (t0, t0 + seg - tail, ''.join(t for _, t in card['speech']))
        if narr:
            a, b, text = narr
            sub = [(w, s_, e_) for w, s_, e_ in words if e_ > a and s_ < b]
            ct = char_times(text, sub)          # 词级时间戳是全片绝对时间，ct 也是绝对时间
            if ct is None:
                # 整片 ASR 没听准这一卡：把它单独剪出来再转一遍（准得多），还不行才摊时长
                print(f'  ~ 卡 {key} 整片对齐失败，改段内单独转写', flush=True)
                clip = cut_seg(wav, t0, seg)
                # 中英混讲的卡，两种语言各有各的听岔处（整句英文跟读尤其明显）：
                # 先按自动检测，再各按 en / zh 强指一次——实测同一条视频里两张卡分别靠 en、zh 才对上
                for lang in (None, 'en', 'zh'):
                    ct = char_times(text, [(w, s_ + t0, e_ + t0)
                                           for w, s_, e_ in transcribe(clip, lang)])
                    if ct is not None:
                        print(f'  ~ 卡 {key} 段内转写对齐成功（{lang or "自动"}）', flush=True)
                        break
            cues = cut_cues(text)
            if ct is None:
                # 这一卡 ASR 没听出来：按字数把整段时长摊掉，至少别整卡没字幕
                print(f'  ~ 卡 {key} 对齐锚点不足，改按字数分摊', flush=True)
                total = sum(units(c) for c in cues) or 1
                t_ = a
                for cue in cues:
                    d = (b - a) * units(cue) / total
                    rows.append((t_, t_ + d, cue, b))      # 第 4 位记下本卡旁白窗口的终点，收尾时判断空档用
                    t_ += d
            else:
                idx = 0                          # cut_cues 会保留全部字符，按顺序累加即得归一化下标
                first = None
                for cue in cues:
                    k = norm(cue)
                    if not k:
                        continue
                    s_i = min(idx, len(ct) - 1)
                    e_i = min(idx + len(k) - 1, len(ct) - 1)
                    idx += len(k)
                    # 起点取首字的「起」、结束取末字的「止」+ 一点余量；
                    # 夹在本卡旁白窗口 [a, b] 内：ASR 有时会把锚点落到下一段（原声段）里，
                    # 不夹的话字幕就会盖到只播访谈的那几秒上。
                    s_, e_ = max(ct[s_i][0], a), min(ct[e_i][1] + 0.28, b)
                    if first is None:
                        first = len(rows)
                    rows.append((s_, e_, cue, b))
                # 卡片的第一条：ASR 开头那句是「从上一段的余音里起的」，词级起点常晚 0.5–1 秒，
                # 而旁白本来就是从卡片开头念的——明显偏晚就拉回卡片开头，别让第一句字幕姗姗来迟。
                if first is not None and rows[first][0] > a + 0.6:
                    print(f'  ~ 卡 {key} 首条字幕偏晚 {rows[first][0] - a:.2f}s，拉回卡片开头', flush=True)
                    rows[first] = (a, rows[first][1], rows[first][2], rows[first][3])
        t0 += seg

    # 收尾：去掉重叠、每条的结束不晚于下一条的开始
    out = []
    for i, (s_, e_, txt, card_end) in enumerate(rows):
        if i + 1 < len(rows) and e_ > rows[i+1][0]:
            e_ = rows[i+1][0] - 0.02
        if e_ > s_:
            out.append((s_, e_, txt, card_end))
    # 同一条卡里留了长空档（>1.2 秒）就把上一条顺延到下一条前 0.1 秒：
    # 空档基本都出现在「英文原句（旁白按 0.8 倍速念）→ 中文译文」之间——
    # ASR 对英文原句往往只锚到开头一小段，整句英文字幕被压成几秒，念到一半字幕就没了。
    # 只在同一张卡内顺延（下一条仍落在本卡窗口里），免得字幕跨到下一张开头。
    for i in range(len(out) - 1):
        s_, e_, txt, card_end = out[i]
        if out[i+1][0] - e_ > 1.2 and out[i+1][0] <= card_end + 0.5:
            out[i] = (s_, out[i+1][0] - 0.1, txt, card_end)
    # 卡片末尾那条常被旁白窗口（段尾要留 0.25–3.1 秒）挤成零点几秒——
    # 一闪而过根本看不见，并进上一条，读得完。
    merged = []
    for s_, e_, txt, _ in out:
        if e_ - s_ < 0.5 and merged:
            ps, pe, pt = merged[-1]
            merged[-1] = (ps, max(pe, e_), pt + txt)
        else:
            merged.append((s_, e_, txt))
    p = dest/f'{name}.srt'
    p.write_text(''.join(f'{i+1}\n{ts(s)} --> {ts(e)}\n{t}\n\n'
                         for i, (s, e, t) in enumerate(merged)))
    print(f'DONE {p}  {len(merged)} 条字幕', flush=True)
    return p


if __name__ == '__main__':
    names = sys.argv[1:] or [k for k in B.SPECS if (B.topic_dir(k)/f'{k}.mp4').exists()]
    for n in names:
        make(n)
