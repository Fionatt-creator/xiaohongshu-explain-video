"""旁白「语调 / 节奏」指标测量（纯 numpy，不依赖 librosa / scipy，本机没装）。

为什么要有它：「中文语调不对」是主观判断，但变化方向可以用几个客观量盯着——
  · 语调跨度：一句话里音高从低到高差多少半音。太小＝平，像机器念。
  · 语调抖动：相邻帧音高变化的中位数（半音）。太大＝忽高忽低，听着别扭。
  · 停顿 / 语速：断句是不是碎、赶不赶。
这些数字不判好坏，只用来比较「同一句话、不同音色参数」的相对差异，最终结论仍然靠耳朵。
"""
import re
import subprocess as sp

import numpy as np

SR = 16000          # 分析用采样率，16k 足够覆盖 70–350Hz 的基频
FMIN, FMAX = 70, 350
FRAME, HOP = 0.04, 0.01


def load(path, sr=SR):
    """用 ffmpeg 解码成单声道 float32，省掉 soundfile 依赖。"""
    raw = sp.check_output(['ffmpeg', '-v', 'error', '-i', str(path), '-ac', '1',
                           '-ar', str(sr), '-f', 's16le', '-'])
    return np.frombuffer(raw, dtype='<i2').astype(np.float32) / 32768.0


def f0_track(x, sr=SR, fmin=FMIN, fmax=FMAX, frame=FRAME, hop=HOP):
    """自相关估基频。返回 (每帧基频 Hz, 帧移秒)，0 表示该帧无声或不成音。"""
    n, h = int(frame * sr), int(hop * sr)
    lo, hi = max(2, int(sr / fmax)), min(int(sr / fmin), n - 1)
    win = np.hanning(n)
    out = []
    for i in range(0, max(len(x) - n, 1), h):
        seg = x[i:i + n]
        if len(seg) < n:
            break
        seg = (seg - seg.mean()) * win
        if np.sqrt((seg ** 2).mean()) < 5e-4:      # 静音
            out.append(0.0)
            continue
        spec = np.fft.rfft(seg, 2 * n)
        ac = np.fft.irfft(spec * np.conj(spec))[:hi + 2]
        if ac[0] <= 0:
            out.append(0.0)
            continue
        ac = ac / ac[0]
        k = int(np.argmax(ac[lo:hi + 1]))
        if ac[lo + k] < 0.35:                     # 峰值不够突出＝没有清晰基频
            out.append(0.0)
            continue
        a, b, c = ac[lo + k - 1], ac[lo + k], ac[lo + k + 1]
        d = 0.5 * (a - c) / (a - 2 * b + c) if (a - 2 * b + c) else 0.0
        out.append(sr / (lo + k + d))
    return np.array(out), h / sr


def units(text):
    """字数口径：一个汉字算 1，一个英文单词算 1，标点不算。"""
    return sum(1 for ch in text if '\u4e00' <= ch <= '\u9fff') + len(re.findall(r'[A-Za-z]+', text))


def smooth(f0, k=5):
    """在各自的有声段内做中值滤波：自相关偶尔会把某帧估成八度音，单帧尖刺会把跨度撑大。"""
    out = f0.copy()
    h = k // 2
    for i in range(len(f0)):
        a = f0[max(0, i - h):i + h + 1]
        a = a[a > 0]
        if len(a):
            out[i] = np.median(a)
    return out


def probe(path, text=None):
    """量一条音频。返回的字段直接进台账。"""
    x = load(path)
    dur = len(x) / SR
    f0, hop = f0_track(x)
    # 第二遍把搜索范围收到「中位基频附近」，专治自相关的八度错误：
    # 第一遍偶尔会把某一帧判成低八度/高八度，光靠中值滤波压不住，会把语调跨度撑到二十几半音。
    rough = f0[f0 > 0]
    if len(rough) >= 20:
        med = float(np.median(rough))
        f0, hop = f0_track(x, fmin=med / 1.8, fmax=med * 1.8)
    # 有声/无声的判定用原始轨迹，音高数值用滤波后的
    voiced = smooth(f0)[f0 > 0]
    m = {}
    m['dur'] = round(dur, 2)
    m['voiced'] = round(float((f0 > 0).mean()), 3)                   # 有声帧占比
    if len(voiced) >= 5:
        st = 12 * np.log2(voiced / np.median(voiced))                # 以各自的基频中位为基准
        m['f0'] = round(float(np.median(voiced)))
        m['range_st'] = round(float(np.percentile(st, 95) - np.percentile(st, 5)), 2)   # 语调跨度
        m['jitter_st'] = round(float(np.median(np.abs(np.diff(st)))), 3)                # 语调抖动
    else:
        m['f0'] = m['range_st'] = m['jitter_st'] = None
    # 停顿：无声段 ≥0.15s 算一次
    quiet = f0 <= 0
    runs, cur = 0, 0
    for q in quiet:
        cur = cur + 1 if q else 0
        if cur == int(0.15 / hop):
            runs += 1
    m['pauses'] = round(runs / dur, 2) if dur else None
    m['speech_rate'] = round(units(text) / dur, 2) if (text and dur) else None
    return m


if __name__ == '__main__':
    import sys
    for p in sys.argv[1:]:
        print(p, probe(p))
