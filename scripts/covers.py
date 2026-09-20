"""拾句英语 · 精细讲解视频封面

- 人像版：1080×1440（3:4），上半为谷爱凌访谈画面，下半为品牌文字区（主用）
- 纯文字版：同样版式，不带人像（留作备用）
- 候选帧：把最清晰的几帧排成对照图，方便换帧

配色、logo、字体全部复用 build.py，与视频画面保持同一套品牌语言。
"""
import sys, subprocess as sp
from pathlib import Path
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build as B

W, H = 1080, 1440
SIDE, RIGHT = 72, 1008
PHOTO_H = 760          # 上半人像区高度
CHIP = (SIDE, 800, SIDE+200, 860)
HEAD_Y = 950
HEAD_LH = 120
HEAD_SIZE = 108
SUB_Y = 1220
SUB_SIZE = 46
PANEL = (SIDE, 880, RIGHT, 1290)   # 纯文字版用
BRAND_CY = 1330                    # 已废弃：封面页脚自 2026-09 起不画
B.LOGO_H = 52

# 人脸位置来自 Haar 检测。选帧依据见 流程.md 第 7 步：
# 播客素材两个人同框，靠「转写里这段谁在说话 + 镜头给说话人」定位人物：
# 0–20s 是 Jay 在说，20.3–41s 是谷爱凌在说；两段的人脸描述子组内距离 30–35、组间 66.9，
# 证实是两个人，故取 20.3–41s 这组。cx/cy 是原片像素坐标。
FRAMES = {
    '勇敢开口': dict(t=88.0, cx=1146, cy=471),
    '继续成长': dict(t=122.0, cx=1138, cy=489),
    '你也能': dict(t=160.0, cx=1171, cy=429),
    '开场寒暄': dict(t=29.0, cx=509, cy=145,
                  src='__DATA_ROOT__/小红书发帖-拾句英语/谷爱凌/谷爱凌最新全英访谈.mp4'),
    '身份之争': dict(t=170.0, cx=531, cy=185,
                  src='__DATA_ROOT__/小红书发帖-拾句英语/谷爱凌/谷爱凌最新全英访谈.mp4'),
    # 童年什么都试（190.97–313.19s）：这一段她一直在讲话，t=260 那帧人脸在 (548,186)、
    # 双眼可检、清晰度 30，与已知谷爱凌帧（t=170）的描述子距离 915 最近（Jay 在 t=245/300
    # 那两帧是 2733/2889，一眼能分开）。
    # 写日记（313.63–455.09s）：t=395 那帧人脸在 (534,178)、双眼可检、清晰度 36，
    # 与已知谷爱凌帧（t=170）的描述子距离 750 最近；t=440/450 是主持人（距离 2852/2942）。
    # 女性气质（490.25–685.79s）：t=580 那帧人脸在 (555,200)、双眼、清晰度 28，
    # 与已知谷爱凌帧（t=170）的描述子距离 879 最近；t=500/520/600 距离 2846–2884 是主持人。
    # 训练日常（686.15–875.27s）：t=780 那帧人脸在 (532,186)、双眼、清晰度 29，
    # 与已知谷爱凌帧（t=170）的描述子距离 951 最近；画面右侧 (953,437) 无眼的一律是主持人。
    '训练日常': dict(t=780.0, cx=532, cy=186,
                src='__DATA_ROOT__/小红书发帖-拾句英语/谷爱凌/谷爱凌最新全英访谈.mp4'),
    # 妈妈和奶奶（875.71–998.42s）：这一段她一直在讲话，t=946 那帧人脸在 (531,183)、
    # 双眼可检、清晰度 27.7，与已知谷爱凌帧（t=170）的描述子距离 2035 最小；
    # 同期她自己的镜头都在 (527–540,183–203) 一线（距离 2035–3556），
    # 主持人镜头在 (750,170) 附近（距离 7471），右下角小窗那张脸（951,437）是无眼低清帧（6500）。
    '妈妈和奶奶': dict(t=946.0, cx=531, cy=183,
                  src='__DATA_ROOT__/小红书发帖-拾句英语/谷爱凌/谷爱凌最新全英访谈.mp4'),
    # 努力vs方向（998.42–1249.60s）：这一段她讲得多、主持人问得少，她自己的镜头一直在 (522–548,170–201) 一线。
    # t=1132 那帧人脸在 (522,183)、双眼可检、清晰度 24，与已知谷爱凌帧（t=170）距离 2190 第二小
    # （最小是 t=1116，但那双眼睛检出 3 处，疑有误检）；主持人镜头同期在 7000 上下。
    '努力vs方向': dict(t=1132.0, cx=522, cy=183,
                   src='__DATA_ROOT__/小红书发帖-拾句英语/谷爱凌/谷爱凌最新全英访谈.mp4'),
    # 怎么选方向（1249.60–1588.00s）：她讲得最多的一段，t=1524 那帧人脸在 (534,179)、双眼可检、
    # 清晰度 26.6，与已知谷爱凌帧（t=170）距离 2089 最小（次小 2359 在 t=1460）。
    # 1500s 之后是「价值观 / 抛硬币」那几句，表情比较放松，适合做封面。
    '怎么选方向': dict(t=1524.0, cx=534, cy=179,
                   src='__DATA_ROOT__/小红书发帖-拾句英语/谷爱凌/谷爱凌最新全英访谈.mp4'),
    # 学习是超能力（1588.00–1880.00s）：t=1682 那帧人脸在 (538,183)、双眼可检、清晰度 30.1，
    # 与已知谷爱凌帧（t=170）距离 1930 最小（次小 2080 在 t=1702）——距离和清晰度同时最好的一帧。
    '学习是超能力': dict(t=1682.0, cx=538, cy=183,
                   src='__DATA_ROOT__/小红书发帖-拾句英语/谷爱凌/谷爱凌最新全英访谈.mp4'),
    # 比赛心态（1880.00–2146.00s）：t=1938 那帧人脸在 (534,190)、双眼可检、清晰度 27.3，
    # 与已知谷爱凌帧（t=170）距离 1988 最小（次小 2150 在 t=2018）。
    '比赛心态': dict(t=1938.0, cx=534, cy=190,
                 src='__DATA_ROOT__/小红书发帖-拾句英语/谷爱凌/谷爱凌最新全英访谈.mp4'),
    # 严于律己不自我攻击（2146.00–2419.00s）：t=2376 那帧人脸在 (538,180)、双眼可检、清晰度 30.4，
    # 与已知谷爱凌帧（t=170）距离 2328 最小（次小 2390 在 t=2372）。
    '严于律己不自我攻击': dict(t=2376.0, cx=538, cy=180,
                       src='__DATA_ROOT__/小红书发帖-拾句英语/谷爱凌/谷爱凌最新全英访谈.mp4'),
    # 滑雪技术（2701.60–2964.20s）：t=2783 那帧人脸在 (524,188)、双眼可检、清晰度 31.7，
    # 与已知谷爱凌帧（t=170）距离 2280 最小（次小 2352 在 t=2907）。
    '滑雪技术': dict(t=2783.0, cx=524, cy=188,
                 src='__DATA_ROOT__/小红书发帖-拾句英语/谷爱凌/谷爱凌最新全英访谈.mp4'),
    # 冬奥夺金（2964.20–3285.20s）：t=3114 那帧人脸在 (532,192)、双眼可检、清晰度 29.4，
    # 与已知谷爱凌帧（t=170）距离 2275（最小是 3082 的 2111，但清晰度只有 25）。
    '冬奥夺金': dict(t=3114.0, cx=532, cy=192,
                 src='__DATA_ROOT__/小红书发帖-拾句英语/谷爱凌/谷爱凌最新全英访谈.mp4'),
    # 奶奶去世（3285.20–3603.70s）：t=3563 那帧人脸在 (527,194)、双眼可检、清晰度 35.7（本段最锐），
    # 距离 2385（最小是 3379 的 2222，但那帧在「崩掉」那一段，表情不适合做封面）。
    '奶奶去世': dict(t=3563.0, cx=527, cy=194,
                 src='__DATA_ROOT__/小红书发帖-拾句英语/谷爱凌/谷爱凌最新全英访谈.mp4'),
    # Final Five（3603.70–3714.00s）：t=3643 那帧人脸在 (536,189)、双眼可检、清晰度 32.3，
    # 与已知谷爱凌帧（t=170）距离 2308 最小（次小 2532 在 t=3663）。这一段她答得快、表情轻松。
    'FinalFive': dict(t=3643.0, cx=536, cy=189,
                      src='__DATA_ROOT__/小红书发帖-拾句英语/谷爱凌/谷爱凌最新全英访谈.mp4'),
    # 脆弱与友谊（2419.00–2651.40s）：t=2589 那帧人脸在 (530,178)、双眼可检、清晰度 32.9，
    # 与已知谷爱凌帧（t=170）距离 1816 是这一段里最小的（次小 2287 在 t=2645）。
    '脆弱与友谊': dict(t=2589.0, cx=530, cy=178,
                  src='__DATA_ROOT__/小红书发帖-拾句英语/谷爱凌/谷爱凌最新全英访谈.mp4'),
    '女性气质': dict(t=580.0, cx=555, cy=200,
                src='__DATA_ROOT__/小红书发帖-拾句英语/谷爱凌/谷爱凌最新全英访谈.mp4'),
    '写日记': dict(t=395.0, cx=534, cy=178,
                src='__DATA_ROOT__/小红书发帖-拾句英语/谷爱凌/谷爱凌最新全英访谈.mp4'),
    '童年什么都试': dict(t=260.0, cx=548, cy=186,
                    src='__DATA_ROOT__/小红书发帖-拾句英语/谷爱凌/谷爱凌最新全英访谈.mp4'),
}

COVERS = {
    # 2026-09 起的新片：v2 深色 + 宋体，封面文案与视频钩子同源
    '谷爱凌_脆弱与友谊': dict(kind='脆弱与友谊',
                      head=['敢说真话，', '才算真的熟'],
                      sub='跟着 3 分钟访谈学表达',
                      items=[('You are not your craft', '把人和作品分开'),
                             ('insofar as you are prepared', '你只能在准备好的范围内成功')]),
    '谷爱凌_FinalFive': dict(kind='FinalFive',
                       head=['五个问题，', '每题一句话'],
                       sub='访谈最终章 · 跟着 2 分钟学表达',
                       items=[('It will never be embarrassing to try.', '鼓励别人最好用的一句'),
                              ('I’m rooting for you.', '收尾时怎么说祝福')]),
    '谷爱凌_奶奶去世': dict(kind='奶奶去世',
                     head=['金牌和告别，', '只隔几分钟'],
                     sub='跟着 5 分钟访谈学表达',
                     items=[('a matter of minutes', '怎么讲「只差一点点」'),
                            ('wrap my head around it', '想不通的时候怎么说')]),
    '谷爱凌_冬奥夺金': dict(kind='冬奥夺金',
                     head=['那两周，', '每天都在两端'],
                     sub='跟着 5 分钟访谈学表达',
                     items=[('holding on by a thread', '撑不住的时候怎么说'),
                            ('it came down to trust', '把一场硬仗收在归因上')]),
    '谷爱凌_滑雪技术': dict(kind='滑雪技术',
                     head=['容错空间，', '只有那么大'],
                     sub='跟着 4 分钟访谈学表达',
                     items=[('the room for error is tiny', '为什么这件事这么难'),
                            ('On top of that, …', '变量一层层往上加')]),
    '谷爱凌_严于律己不自我攻击': dict(kind='严于律己不自我攻击',
                         head=['对自己狠，', '不等于骂自己'],
                         sub='跟着 4 分钟访谈学表达',
                         items=[('You are not your craft', '你和你的作品不是一回事'),
                                ('take the note, drop the sting', '把意见收下，把刺放下')]),
    '谷爱凌_比赛心态': dict(kind='比赛心态',
                     head=['训练像没赢过，', '比赛像没输过'],
                     sub='跟着 4 分钟访谈学表达',
                     items=[('I train like I’ve never won', '训练时把自己当新人'),
                            ('alter ego, go time', '上场前按一下开关')]),
    '谷爱凌_学习是超能力': dict(kind='学习是超能力',
                       head=['她 12 岁，', '读了育儿手册'],
                       sub='跟着 5 分钟访谈学表达',
                       items=[('I don’t know, but I’ll learn.', '不懂就说不懂，然后去学'),
                              ('It’s not about becoming an expert.', '不是要变成专家')]),
    '谷爱凌_怎么选方向': dict(kind='怎么选方向',
                      head=['离开学校以后，', '标准去哪了？'],
                      sub='跟着 5 分钟访谈学表达',
                      items=[('you won’t gather momentum', '方向错了，越用力越沉'),
                             ('aligned with my values', '用价值观当筛子')]),
    '谷爱凌_努力vs方向': dict(kind='努力vs方向',
                      head=['努力和方向，', '哪个更重要？'],
                      sub='跟着 4 分钟访谈学表达',
                      items=[('the faster you run, the faster it moves', '为什么越努力越焦虑'),
                             ('overpraised / underrated', '一句话把判断说清')]),
    '谷爱凌_妈妈和奶奶': dict(kind='妈妈和奶奶',
                      head=['讲一个人，', '怎么讲得不空？'],
                      sub='跟着 2 分钟访谈学表达',
                      items=[('If I were to distill it, I would say …', '一句话把她说清楚'),
                             ('Not once has she ever …', '把否定说得很重')]),
    '谷爱凌_训练日常': dict(kind='训练日常',
                     head=['被夸的时候，', '还能怎么说？'],
                     sub='跟着 3 分钟访谈学表达',
                     items=[('give sb too much credit', '被夸过头了，怎么接'),
                            ('and still is to this day', '给一句话加上分量')]),
    '谷爱凌_女性气质': dict(kind='女性气质',
                     head=['你是团队里，', '唯一的那一个？'],
                     sub='跟着 3 分钟访谈学表达',
                     items=[('fall in and out of love with sth', '对一件事忽冷忽热'),
                            ('How do I … without feeling …?', '既要用上自己的力量，又不表演')]),
    '谷爱凌_写日记': dict(kind='写日记',
                     head=['一件小事，', '讲成「我是谁」'],
                     sub='跟着 2 分钟访谈学表达',
                     items=[('take sb back to + 记忆', '把人带回某段记忆'),
                            ('if + had done, would have done', '对过去的假设（没发生的事）')]),
    '谷爱凌_童年什么都试': dict(kind='童年什么都试',
                          head=['一聊自己，', '只会这几句？'],
                          sub='跟着 2 分钟访谈学表达',
                          items=[('do an incredible job of…', '做某事做得特别出色'),
                                 ('be much more known as A than B', '别人更把我看成 A，而不是 B')]),
    '谷爱凌_身份之争': dict(kind='身份之争',
                       head=['简历之外，', '才是你'],
                       sub='跟着 2 分钟访谈学表达',
                       items=[('at my core', '骨子里／说到底'),
                              ('what would have been', '本该是……（实际不是）')]),
    # 重制版：版式与文案沿用上面那条，配色/字体跟随选题（v2 深色 + 宋体）；02 用的是这一张
    '谷爱凌_身份之争_重制版': dict(kind='身份之争',
                            head=['简历之外，', '才是你'],
                            sub='跟着 2 分钟访谈学表达',
                            items=[('at my core', '骨子里／说到底'),
                                   ('what would have been', '本该是……（实际不是）')]),
    '谷爱凌_开场寒暄': dict(kind='开场寒暄',
                       head=['打招呼，', '只会这一句？'],
                       sub='跟着 69 秒访谈学寒暄',
                       items=[('Thank you for having me.', '谢谢邀请我来。'),
                              ('The feeling is mutual.', '我也一样／我也这么觉得。')]),
    # 完整版：版式与文案沿用上面那条，配色/字体跟随选题（v2 深色 + 宋体）
    '谷爱凌_开场寒暄_完整版': dict(kind='开场寒暄',
                            head=['打招呼，', '只会这一句？'],
                            sub='跟着 69 秒访谈学寒暄',
                            items=[('Thank you for having me.', '谢谢邀请我来。'),
                                   ('The feeling is mutual.', '我也一样／我也这么觉得。')]),
    '谷爱凌_勇敢开口': dict(kind='勇敢开口',
                       head=['怕说错，', '不敢开口？'],
                       sub='跟谷爱凌学两句英语',
                       items=[('have an opportunity to…', '有机会做某事'),
                              ('The worst that can happen is…', '最坏的情况是……')]),
    '谷爱凌_继续成长': dict(kind='继续成长',
                       head=['总觉得英语', '还不够好？'],
                       sub='跟谷爱凌学两句英语',
                       items=[('not … anymore', '不再……（以前是，现在不是了）'),
                              ('have room to grow', '还有成长空间')]),
    '谷爱凌_你也能': dict(kind='你也能',
                      head=['别人行，', '我不行？'],
                      sub='跟谷爱凌学两句英语',
                      items=[('I can too.', '我也能／我也行'),
                             ('more than + 形容词', '远不止……')]),
}


def grab(t, src=None):
    """从原片取一帧全分辨率 PNG。src 不给就用当前素材（不同选题可能用不同原片）。"""
    src = src or B.SRC
    out = Path('/tmp')/f'hd_{Path(src).stem[:12]}_{t}.png'
    sp.run(['ffmpeg', '-y', '-v', 'error', '-ss', str(t), '-i', src, '-frames:v', '1', str(out)], check=True)
    return Image.open(out).convert('RGB')


def photo_crop(im, cx, cy):
    """按人脸中心裁出 1080×PHOTO_H 的竖版人像区。
    素材比人像区还矮时（如播客的 1280×720）先等比放大，否则裁切会超出画布露出黑边。"""
    if im.height < PHOTO_H:
        k = PHOTO_H/im.height
        im = im.resize((round(im.width*k), PHOTO_H), Image.LANCZOS)
        cx, cy = round(cx*k), round(cy*k)
    x0 = max(0, min(im.width-W, cx-W//2))
    y0 = max(0, min(im.height-PHOTO_H, cy-int(PHOTO_H*0.45)))
    return im.crop((x0, y0, x0+W, y0+PHOTO_H))


def text_block(im, d, spec):
    d.rounded_rectangle(CHIP, radius=18, fill=B.BRAND)
    B.text_mid(d, SIDE+20, (CHIP[1]+CHIP[3])//2, '拾句英语', 36, B.ON_BRAND)
    B.text_r(d, RIGHT, 816, '听 · 懂 · 说', 32, B.MUTE)
    for i, line in enumerate(spec['head']):
        B.text(d, (SIDE, HEAD_Y+i*HEAD_LH), line, HEAD_SIZE, B.FG if i == 0 else B.GREEN)
    B.text(d, (SIDE, SUB_Y), spec['sub'], SUB_SIZE, B.MUTE)
    # 2026-09 起封面底部也不再放品牌落款（跟视频一致）：文字区少了那一条，
    # 顺势把两行大字与副标下移 50px，在「品牌绿分隔条 768 → 画布底 1440」之间重新居中。
    # 页脚原先是：logo + 拾句英语 + 官网链接/ slogan。


def cover_photo(name, spec):
    f = FRAMES[spec['kind']]
    im = Image.new('RGB', (W, H), B.BG)
    im.paste(photo_crop(grab(f['t'], f.get('src')), f['cx'], f['cy']), (0, 0))
    d = ImageDraw.Draw(im)
    d.rectangle((0, PHOTO_H, W, PHOTO_H+8), fill=B.BRAND)   # 人像与文字区之间的品牌绿分隔条
    text_block(im, d, spec)
    outdir = B.topic_dir(name)                 # 跟成片放同一个选题文件夹（含 01_/02_ 序号前缀）
    outdir.mkdir(parents=True, exist_ok=True)
    p = outdir/f'{name}_封面.png'
    im.save(p)
    return p


def cover_text(name, spec):
    im = Image.new('RGB', (W, H), B.BG)
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((SIDE, 72, SIDE+200, 132), radius=18, fill=B.BRAND)
    B.text_mid(d, SIDE+20, 102, '拾句英语', 36, B.ON_BRAND)
    B.text_r(d, RIGHT, 88, '听 · 懂 · 说', 32, B.MUTE)
    for i, line in enumerate(spec['head']):
        B.text(d, (SIDE, 230+i*160), line, 132, B.FG if i == 0 else B.GREEN)
    B.text(d, (SIDE, 590), spec['sub'], 56, B.MUTE)
    d.rounded_rectangle(PANEL, radius=28, fill=B.SURFACE, outline=B.LINE, width=3)
    y = PANEL[1]+58
    for item, cn in spec['items']:
        B.text(d, (SIDE+46, y), item, 50, B.FG, en=item.isascii())
        B.text(d, (SIDE+46, y+64), cn, 36, B.GREEN)
        y += 160
    # 2026-09 起也去掉页脚落款（原来在 1265：logo + 拾句英语 + 官网链接/slogan）
    p = Path(__file__).resolve().parent/f'封面_纯文字版_{name}.png'
    im.save(p)
    return p


def contact_sheet(spots):
    """把候选帧按人脸裁成方形排成对照图，标上时间点。"""
    cell, cols = 340, 3
    rows = (len(spots)+cols-1)//cols
    sheet = Image.new('RGB', (cols*cell, rows*(cell+40)), B.BG)
    d = ImageDraw.Draw(sheet)
    for i, (t, cx, cy) in enumerate(spots):
        side = 470
        box = (cx-side//2, cy-int(side*0.5), cx+side//2, cy+int(side*0.5))
        im = grab(t).crop(box).resize((cell, cell), Image.LANCZOS)
        x, y = (i % cols)*cell, (i//cols)*(cell+40)
        sheet.paste(im, (x, y))
        B.text(d, (x+10, y+cell+6), f't={t:.0f}s', 26, B.FG)
    p = Path(__file__).resolve().parent/'候选帧.png'
    sheet.save(p)
    return p


if __name__ == '__main__':
    names = sys.argv[1:] or list(COVERS)
    for name in names:
        # 封面配色/logo 跟随该选题视频的样式与字体：旧片 v1 浅色+黑体、新片 v2 深色+宋体
        B.apply_style(B.SPECS[name].get('style', B.DEFAULT_STYLE))
        B.apply_fonts(B.SPECS[name].get('fonts', B.DEFAULT_FONTS))
        print(cover_photo(name, COVERS[name]), flush=True)
        print(cover_text(name, COVERS[name]), flush=True)
    if not sys.argv[1:]:   # 只在全量重跑时刷新纪录片那批的候选帧对照图
        print(contact_sheet([(88, 1146, 471), (87, 1180, 400), (122, 1138, 489),
                             (52, 1179, 436), (160, 1171, 429), (183, 1154, 458)]), flush=True)
