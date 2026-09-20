"""把「表达详解」Markdown 转成可打印的 A4 PDF 学习资料。

用法：
    /opt/homebrew/bin/python3 handout.py <表达详解.md> <输出目录> [标题] [副标题] [跟读练习文件]

数据源是表达详解 md（单一真相），本脚本只负责排版：
    解析 `**N. \\`表达\\`** ｜ 时间` 条目 + 原句/意思/用法/迁移 → 生成 HTML → Chrome 无头打印 PDF

若 md 同目录下有同名 `<md>.原声对照.txt`（每行 `mm:ss｜说话人｜英文｜中文`），
就在文末多排一节「原声对照 · 整章逐句」——整段原话的英中对照；没有这个文件就一个字不加，
所以老选题的 PDF 重跑后与原来完全一致。
"""
import sys, re, base64, html, subprocess as sp
from pathlib import Path
from io import BytesIO

CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
LOGO = '__DATA_ROOT__/BrandLogo.png'
BRAND = '拾句英语'
URL = 'https://shijuenglish.cn/'


def md_inline(s):
    """把少量 markdown 行内标记转成 HTML。"""
    s = html.escape(s)
    s = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', s)
    s = re.sub(r'`(.+?)`', r'<code>\1</code>', s)
    s = re.sub(r'~~(.+?)~~', r'<del>\1</del>', s)
    return s


def parse(md_text):
    """返回 [(章节标题, [条目, ...]), ...]；条目 = {n, expr, time, 原句, 意思, 用法, 迁移}"""
    sections, cur = [], None
    entry = None
    for raw in md_text.split('\n'):
        line = raw.rstrip()
        if line.startswith('## '):
            title = line[3:].strip()
            if '做视频' in title:            # 选题规划，不进学习资料
                cur, entry = None, None
                continue
            cur = (title, [])
            sections.append(cur)
            entry = None
            continue
        if not cur or not line.strip():
            continue
        m = re.match(r'^\*\*(\d+)\.\s*(.+?)\*\*\s*｜\s*(.+?)$', line)
        if m:
            entry = {'n': m.group(1), 'expr': m.group(2).strip(),
                     'time': m.group(3).strip(), '原句': '', '意思': '', '用法': '', '迁移': ''}
            cur[1].append(entry)
            continue
        if entry is None:
            continue
        key = next((k for k in ('原句', '意思', '用法', '迁移') if line.startswith(k + '：')), None)
        if key:
            entry[key] = line[len(key) + 1:].strip()
        else:
            for k in ('迁移', '用法', '意思', '原句'):   # 续行并到最近一个字段
                if entry[k]:
                    entry[k] += ' ' + line.strip()
                    break
    return sections


def parse_transcript(path):
    """原声对照：每行 `mm:ss｜说话人｜英文｜中文`；`#` 开头与空行跳过。"""
    rows = []
    for raw in path.read_text(encoding='utf-8').split('\n'):
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        f = [x.strip() for x in line.split('｜')]
        if len(f) < 4:
            continue
        rows.append(dict(time=f[0], who=f[1], en=f[2], zh='｜'.join(f[3:])))
    return rows


def find_transcript(md_path):
    p = md_path.with_name(md_path.stem + '.原声对照.txt')
    return p if p.exists() else None


def logo_b64():
    try:
        from PIL import Image
        im = Image.open(LOGO).convert('RGB').resize((160, 160), Image.LANCZOS)
        b = BytesIO(); im.save(b, 'PNG')
        return 'data:image/png;base64,' + base64.b64encode(b.getvalue()).decode()
    except Exception:
        return ''


CSS = """
@page { size: A4; margin: 16mm 14mm 14mm; }
* { box-sizing: border-box; }
body { margin:0; font-family:'PingFang SC','STHeiti','Hiragino Sans GB',sans-serif;
       color:#191918; background:#fff; font-size:10.5pt; line-height:1.55; }
code { font-family:'SF Mono','Menlo',monospace; font-size:0.94em; background:#F1F5F2;
       color:#0A7A47; padding:0.5px 4px; border-radius:3px; }
.hdr { display:flex; align-items:center; gap:10px; padding-bottom:8px; border-bottom:2.5px solid #2DCE7B; }
.hdr img { width:34px; height:34px; border-radius:8px; }
.hdr .b { font-size:11pt; font-weight:600; letter-spacing:.5px; }
.hdr .r { margin-left:auto; font-size:9pt; color:#7D7E7B; }
h1 { font-size:19pt; margin:14px 0 4px; letter-spacing:.5px; }
.sub { color:#7D7E7B; font-size:10pt; margin-bottom:2px; }
.meta { color:#7D7E7B; font-size:9pt; margin-bottom:14px; }
.lead { background:#F4F8F5; border-left:3px solid #2DCE7B; padding:8px 11px;
        font-size:9.5pt; color:#3c4a41; margin-bottom:16px; }
h2 { font-size:12.5pt; margin:20px 0 8px; padding-left:9px; border-left:4px solid #0A7A47;
     page-break-after:avoid; }
h2 .cnt { font-size:9pt; color:#7D7E7B; font-weight:400; margin-left:6px; }
.e { margin:0 0 9px; padding-left:11px; border-left:2px solid #E1E1DC; page-break-inside:avoid; }
.e .t { font-weight:600; font-size:10.5pt; }
.e .t .n { color:#7D7E7B; font-weight:400; margin-right:4px; }
.e .t .time { float:right; color:#0A7A47; font-size:8.5pt; font-weight:400; }
.e .en { color:#0A7A47; font-size:10pt; margin-top:1px; }
.e .cn { color:#4a4a48; font-size:9.5pt; }
.e .use { color:#5d5d5b; font-size:9.5pt; margin-top:2px; }
.e .mig { font-size:9.5pt; margin-top:2px; color:#3c4a41; }
.e .mig::before { content:'迁移 · '; color:#12A45E; font-weight:600; }
.tip { margin:0 0 7px; padding-left:11px; border-left:2px solid #E1E1DC; font-size:9.5pt;
       color:#3c4a41; page-break-inside:avoid; }
.tr { margin:0 0 7px; padding-left:11px; border-left:2px solid #E1E1DC; page-break-inside:avoid; }
.tr .h { font-size:8.5pt; color:#7D7E7B; }
.tr .h .who { color:#0A7A47; font-weight:600; margin-left:7px; }
.tr .en { color:#0A7A47; font-size:10pt; margin-top:1px; }
.tr .cn { color:#4a4a48; font-size:9.5pt; }
.prac { background:#F4F8F5; border-radius:6px; padding:10px 13px; margin-top:8px;
        font-size:10pt; page-break-inside:avoid; }
.prac div { margin:3px 0; }
.ftr { margin-top:18px; padding-top:8px; border-top:1px solid #E1E1DC;
       color:#7D7E7B; font-size:8.5pt; display:flex; }
.ftr span:last-child { margin-left:auto; }
"""


def build_html(sections, title, sub, meta, lead, practice, practice_note='', transcript=None):
    parts = []
    for stitle, entries in sections:
        if not entries:
            continue
        parts.append(f'<h2>{md_inline(stitle)}<span class="cnt">{len(entries)} 条</span></h2>')
        for e in entries:
            en = md_inline(e['expr'])
            rows = []
            if e['原句']:
                rows.append(f'<div class="en">{md_inline(e["原句"])}</div>')
            if e['意思']:
                rows.append(f'<div class="cn">{md_inline(e["意思"])}</div>')
            if e['用法']:
                rows.append(f'<div class="use">{md_inline(e["用法"])}</div>')
            if e['迁移']:
                rows.append(f'<div class="mig">{md_inline(e["迁移"])}</div>')
            parts.append(
                f'<div class="e"><div class="t"><span class="n">{e["n"]}.</span>{en}'
                f'<span class="time">{md_inline(e["time"])}</span></div>{"".join(rows)}</div>')
    prac = ''
    if practice:
        items = ''.join(f'<div>{md_inline(x)}</div>' for x in practice)
        note = f'<span class="cnt">{html.escape(practice_note)}</span>' if practice_note else ''
        prac = f'<h2>跟读练习{note}</h2><div class="prac">{items}</div>'
    tr = ''
    if transcript:
        rows = ''.join(
            f'<div class="tr"><div class="h">{md_inline(r["time"])}'
            f'<span class="who">{md_inline(r["who"])}</span></div>'
            f'<div class="en">{md_inline(r["en"])}</div>'
            f'<div class="cn">{md_inline(r["zh"])}</div></div>' for r in transcript)
        tr = (f'<h2>原声对照<span class="cnt">整章逐句 · {len(transcript)} 句 · 英中</span></h2>'
              f'<div class="tip">这一段访谈的原话全在这里，按时间顺序排：上英文、下中文。'
              f'想跟读时先看英文回忆她的语气，再对一眼中文，检查有没有听漏。</div>{rows}')
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<title>{html.escape(title)}</title><style>{CSS}</style></head><body>
<div class="hdr"><img src="{logo_b64()}" alt=""><span class="b">{BRAND}</span>
<span class="r">听懂一句，再把它说出来</span></div>
<h1>{html.escape(title)}</h1><div class="sub">{html.escape(sub)}</div>
<div class="meta">{html.escape(meta)}</div>
<div class="lead">{md_inline(lead)}</div>
{''.join(parts)}{prac}{tr}
<div class="ftr"><span>{BRAND}</span><span>{URL}</span></div>
</body></html>"""


def main():
    md_path = Path(sys.argv[1]).resolve()
    outdir = Path(sys.argv[2]).resolve(); outdir.mkdir(parents=True, exist_ok=True)
    title = sys.argv[3] if len(sys.argv) > 3 else '精讲笔记'
    sub = sys.argv[4] if len(sys.argv) > 4 else ''
    practice = []
    if len(sys.argv) > 5:
        practice = [l.strip() for l in Path(sys.argv[5]).read_text(encoding='utf-8').split('\n') if l.strip()]
    practice_note = sys.argv[6] if len(sys.argv) > 6 else ''

    sections = parse(md_path.read_text(encoding='utf-8'))
    total = sum(len(e) for _, e in sections)
    tr_path = find_transcript(md_path)
    transcript = parse_transcript(tr_path) if tr_path else []
    meta = f'共 {total} 条表达 · 按「原句 → 意思 → 用法 → 迁移例句」编排'
    lead = ('这张笔记把视频里讲过的表达全部收齐，按「原句 → 意思 → 用法 → 迁移例句」四栏编排。'
            '建议用法：先看原句回忆视频里的语气，再读用法，最后把迁移例句读出声。'
            '带 · 的迁移句是可以直接搬到你自己场景里的句子。')

    html_path = outdir/(md_path.stem + '.html')
    html_path.write_text(build_html(sections, title, sub, meta, lead, practice, practice_note, transcript),
                         encoding='utf-8')
    pdf_path = outdir/(re.sub(r'[^\w\u4e00-\u9fa5]+', '_', title) + '.pdf')
    sp.run([CHROME, '--headless', '--disable-gpu', '--no-pdf-header-footer',
            f'--print-to-pdf={pdf_path}', html_path.as_uri()], check=True,
           stdout=sp.DEVNULL, stderr=sp.DEVNULL)
    print(f'HTML: {html_path}')
    print(f'PDF : {pdf_path}  ({pdf_path.stat().st_size/1024:.0f} KB)')
    print(f'条目 {total} 条，章节 {len([1 for _, e in sections if e])} 个')
    if transcript:
        print(f'原声对照：{tr_path.name}，{len(transcript)} 句')


if __name__ == '__main__':
    main()
