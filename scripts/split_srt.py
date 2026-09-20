"""按话题边界把整份 SRT 切成若干段，每段输出 .srt + .txt

用法：
    python3 split_srt.py <输入.srt> <边界.txt> <输出目录>

边界文件每行一段，格式：`mm:ss 标题` 或 `hh:mm:ss 标题`
（标题会作为文件名后缀；最后一段自动延伸到文件结尾）
"""
import sys, re
from pathlib import Path


def to_sec(s):
    p = [int(x) for x in s.split(':')]
    return p[0]*3600 + p[1]*60 + p[2] if len(p) == 3 else p[0]*60 + p[1]


def parse_srt(txt):
    out = []
    for blk in re.split(r'\n\s*\n', txt.strip()):
        lines = blk.split('\n')
        if len(lines) < 3:
            continue
        m = re.match(r'(\d+):(\d+):(\d+),(\d+)\s*-->\s*(\d+):(\d+):(\d+),(\d+)', lines[1])
        if not m:
            continue
        st = int(m[1])*3600 + int(m[2])*60 + int(m[3]) + int(m[4])/1000
        out.append((st, lines[0], lines[1], ' '.join(lines[2:])))
    return out


def main():
    srt, bnd, outdir = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
    outdir.mkdir(parents=True, exist_ok=True)
    segs = parse_srt(srt.read_text(encoding='utf-8'))

    marks = []
    for ln in bnd.read_text(encoding='utf-8').splitlines():
        ln = ln.strip()
        if not ln or ln.startswith('#'):
            continue
        t, title = ln.split(None, 1)
        marks.append((to_sec(t), title.strip()))
    marks.sort()

    for i, (st, title) in enumerate(marks, 1):
        en = marks[i][0] if i < len(marks) else float('inf')
        part = [s for s in segs if st-1e-6 <= s[0] < en]
        if not part:
            print(f'!! {title} 没切到内容', flush=True)
            continue
        name = f'{i:02d}-{title}'
        (outdir/f'{name}.srt').write_text(
            '\n'.join(f'{n}\n{tl}\n{tx}\n' for _, n, tl, tx in part), encoding='utf-8')
        (outdir/f'{name}.txt').write_text('\n'.join(tx for _, _, _, tx in part), encoding='utf-8')
        dur = (part[-1][0] - st)/60
        print(f'{name:<34} {len(part):>4} 条  {tl0(part)}  ≈{dur:.1f} 分钟', flush=True)
    print(f'DONE 共 {len(marks)} 段 → {outdir}', flush=True)


def tl0(part):
    return part[0][2].split(' --> ')[0][:8]


if __name__ == '__main__':
    main()
