"""按时间点就地修正 SRT 里的错词（转写误识别）

用法：
    python3 fix_srt.py <输入.srt> <修正表.txt> <输出.srt>

修正表每行一条，用竖线分隔：`时间 | 要找的片段 | 改成`
时间支持 `mm:ss` 或 `hh:mm:ss`；以 # 开头的行为注释（用于记录存疑、暂不改的项）。
先在该时间点附近 ±4 秒内找，找不到再全文找；找不到会列出来提醒你核对。
"""
import sys, re
from pathlib import Path


def to_sec(s):
    p = [int(x) for x in s.split(':')]
    return p[0]*3600 + p[1]*60 + p[2] if len(p) == 3 else p[0]*60 + p[1]


def parse_srt(txt):
    segs = []
    for b in re.split(r'\n\s*\n', txt.strip()):
        lines = b.split('\n')
        if len(lines) < 3:
            continue
        m = re.match(r'(\d+):(\d+):(\d+),(\d+)', lines[1])
        if not m:
            continue
        segs.append({'n': lines[0], 'tl': lines[1], 'text': ' '.join(lines[2:]),
                     'st': int(m[1])*3600 + int(m[2])*60 + int(m[3]) + int(m[4])/1000})
    return segs


def main():
    segs = parse_srt(Path(sys.argv[1]).read_text(encoding='utf-8'))
    applied, missed = 0, []
    for ln in Path(sys.argv[2]).read_text(encoding='utf-8').splitlines():
        ln = ln.strip()
        if not ln or ln.startswith('#'):
            continue
        t, old, new = [x.strip() for x in ln.split('|')]
        t = to_sec(t)
        cand = [s for s in segs if s['st'] >= t-4 and s['st'] <= t+4 and old in s['text']] \
            or [s for s in segs if old in s['text']]
        if not cand:
            missed.append((t, old))
            continue
        s = min(cand, key=lambda s: abs(s['st']-t))
        s['text'] = s['text'].replace(old, new)
        applied += 1
        print(f"  OK  {int(t//60):02d}:{int(t%60):02d}  {old}  →  {new}")

    out = '\n'.join(f"{s['n']}\n{s['tl']}\n{s['text']}\n" for s in segs)
    Path(sys.argv[3]).write_text(out, encoding='utf-8')
    print(f'\n已应用 {applied} 处，输出 {sys.argv[3]}')
    if missed:
        print(f'未匹配 {len(missed)} 处（请人工核对）：')
        for t, old in missed:
            print(f"  !!  {int(t//60):02d}:{int(t%60):02d}  {old}")


if __name__ == '__main__':
    main()
