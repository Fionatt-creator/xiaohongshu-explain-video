---
name: "xiaohongshu-explain-video"
description: "「小红书精讲视频」：把访谈/播客素材做成 9:16 英语精讲视频（卡片+旁白+封面+发帖文案+精讲 PDF），内含锁定的配色/字体/音色参数与踩过的坑。当用户要做、重做、批量做小红书英语精讲视频，或要出试听版/加字幕/调音色参数时调用。"
---

# 小红书精讲视频（拾句英语）

一条素材 → 拆成若干条「2–3 个重点句式」的讲解视频，配封面、发帖文案、精讲笔记 PDF、讲解字幕 SRT。
**四样配套每一条都要出**（SRT 自 2026-09 起列入常规交付，别等有人来要）。
本文件是**规格与参数的唯一出处**；十步流程的操作细节与命令见
`精细讲解视频/_tools/流程.md`（同目录，随项目演进）。

## 触发场景

- 给一个访谈/播客视频（或一段素材库里的章节），要做成小红书英语精讲视频
- 把已发布的旧片「重做一遍」（换配色/字体/音色）
- 出「前 N 分钟」试听版、做某个音色参数的对比版
- 调旁白音色与语调参数（配 `音色调试/` 那套台子，见文末）

## 零、公开版配置（下载后先改这几处）

本仓库是「通用化」版本，已把私有信息替换成占位符，**用之前先全局搜索替换下面四类**：

| 占位符 | 含义 | 换成什么 |
|---|---|---|
| `__DATA_ROOT__` | 你的素材/数据盘根目录 | 形如 `__DATA_ROOT__/小红书发帖-拾句英语/…` 的路径 → 你的实际目录 |
| `__WORKSPACE__` | 你的代码工作区 | 内容库所在的本地目录（原 `projects/xxx` 这类） |
| `__HOME__` | 你的用户目录 | `/Users/<你的用户名>` |
| `__VOICE_ID__` | ElevenLabs 音色 ID | 你在 ElevenLabs 上训练/选用的那串音色 ID |

**密钥绝不入库**：ElevenLabs key 放在运行目录的 `.env.elevenlabs`（或环境变量 `ELEVENLABS_API_KEY`），
脚本只从那里读。品牌常量（`拾句英语`、官网 URL、logo 路径）在各脚本顶部的 `BRAND_*` / `LOGO` / `URL` 里，改成你自己的品牌即可。

**依赖**：`pip install requests pillow faster-whisper numpy`；系统还要装 `ffmpeg`、Google Chrome（PDF 无头打印用）。


## 工作目录

| 位置 | 内容 |
|---|---|
| `__DATA_ROOT__/小红书发帖-拾句英语/精细讲解视频/` | 成片与工具（`_tools/`），一个选题一个文件夹 |
| 同上 `_tools/` | `build.py` 渲染器、`covers.py` 封面、`handout.py` PDF、`make_srt.py` 从成片反推字幕、`transcribe.py`/`fix_srt.py`/`split_srt.py` 素材处理、`流程.md` |
| 同上 `音色调试/`（平级） | `_tools/voice_lab.py` 参数台、`_tools/prosody.py` 语调指标、`台账.md` |
| `__WORKSPACE__/projects/eileen-gu-on-purpose/` | 内容库：`分段-重点表述.md`、`表达详解/`、`segments/*.srt` |

**沙箱限制**：命令的工作目录必须在目标盘内；长任务先写 `/tmp` 再拷回。

---

## 一、锁定的规格（新片一律照这套）

### 1. 画布与锚点（1080×1920）

| 项 | 值 |
|---|---|
| 画布 | 1080×1920（9:16），30fps |
| 上 / 下留白 | 190px / 417px（避开小红书顶部与底部 UI） |
| 左右留白 | **120px** → 内容区 x 120–960，**可用宽度 840px** |
| 品牌块 | 圆角 chip `(SIDE,190)-(SIDE+200,250)`，右上是「听 · 懂 · 说」 |
| 标题 | y=318（超过可用宽度自动缩号 62→34） |
| 分隔线 | **只有顶部 y=424**（底部 y=1408 自 2026-09 起取消） |
| 画中画 | 810×456 @ y=470（片源 16:9），x 由样式的 `pip_x` 给（135） |
| 页脚 | **无**（2026-09 起整条不画；2026-09 前的老片是 logo + 拾句英语 + 官网链接，用 `'foot': True` 锁住） |
| `lines` 纵向 | 无原声的卡 470–1470；**有原声的卡 950 起，行位 950/1030/1110/1190/1270/1350/1410，最多 7 行** |

> **下半区全部让给正文**（2026-09 起）：原先正文下沿只到 1380、下面留 28px 再一条分隔线、页脚在 1470。
> 去掉页脚与底部分隔线后，正文可以一直排到 **1470**（1503 是小红书 UI 安全线，不能越过）。
> 有原声的卡因此从 5 行变成 7 行。
> 排最后一行时注意：**行位的 y 是文字框顶，墨迹还会往下延伸约 1.25×字号**——
> 44px 的行排在 1410，墨迹到 1470；排在 1425 就溢到 1480 了。所以第 7 行固定用 1410，字号 ≤48px。
>
> **页脚里不放站外链接**：2026-09 前的老片页脚带 `https://shijuenglish.cn/`，实测被小红书判成引流而限流；
> 新片连页脚一起不要。`build.py` 默认 `SHOW_FOOT = False`，老片在 SPEC 里写 `'foot': True`（页脚里要不要网址再看 `'url'`）。

### 2. 配色（样式预设）

| 角色 | v2（**新片默认**） | v1（2026-09 前的旧片） |
|---|---|---|
| 底 | `#191918` | `#F7F7F5` |
| 主文字 | `#F7F7F5` | `#191918` |
| 次要文字 | `#9A9B98` | `#7D7E7B` |
| 主强调 | `#2DCE7B` | `#0A7A47` |
| 次强调 | `#6FE3A8` | `#12A45E` |
| 品牌绿原色 | `#2DCE7B` | `#2DCE7B` |
| 分隔线 | `#33342F` | `#E1E1DC` |
| 左右留白 | 120px | 72px |
| 页脚 | 左聚 | 两端分开 |
| logo | 只留白色图形（mark） | 连徽章本体（badge） |

**为什么改 v2**：小红书官方按钮是白色，浅底上会和画面糊在一起；
且视频被缩放后 72px 留白只剩约 5.6% 屏宽，显得贴边。品牌绿在深底上对比度 8.1:1，浅底只有 1.9:1。

SPEC 里**只写颜色角色**（`'fg'` / `'green'` / `'green2'` / `'mute'` / `'brand'`），由 `C()` 在渲染时解析成当前样式的实际色值——否则同一份 SPEC 套不上另一种样式。

### 3. 字体（字体预设）

| 预设 | 中文 | 西文 | 用途 |
|---|---|---|---|
| `song`（**新片默认**） | `/System/Library/Fonts/Supplemental/Songti.ttc` 第 **1** 号字面（Songti SC Bold） | `/System/Library/Fonts/Supplemental/Arial Italic.ttf` | 宋体 + Arial 斜体 |
| `heiti`（旧片） | `STHeiti Medium.ttc` 第 0 号 | `HelveticaNeue.ttc` 第 0 号 | 黑体 + Helvetica Neue |

- **页脚网址固定用 Helvetica Neue**（`EN_UI`），不跟着正文字体变——Arial 斜体的网址看着不像网址。
  （新片已没有页脚，这条只对 `'foot': True` 且 `'url': True` 的老片生效。）
- 宋体取 **Bold** 而不是 Regular/Light：实测同一张卡换宋体后浅色笔画只剩黑体的 **82%**，深底上 Regular 会发虚。要换：Songti.ttc 里 `0=Black 1=Bold 3=Light 6=Regular`，改一个数字。
- 换字体/配色**必须**跑下面的第 4 步版面自检——宋体与黑体的字面高度不同，容易压行。

### 4. 旁白（音色与模型）

```python
DEFAULT_VOICE = '__VOICE_ID__'
V3_EXPRESSIVE = {'stability': 0.45, 'similarity_boost': 0.75, 'style': 0.4,
                 'use_speaker_boost': True}          # 新片默认（eleven_v3）
```

- **模型**：新片 `eleven_v3`（中文语调明显更自然）；旧片 `eleven_multilingual_v2`。
  对应常量：`DEFAULT_MODEL = 'eleven_v3'`、`DEFAULT_VOICE_SETTINGS`（= `V3_EXPRESSIVE`，style 0.4、**不带 speed**）；
  老片的 `LEGACY_MODEL` / `LEGACY_VOICE_SETTINGS`（style 0 + 带 speed）只在老片 SPEC 里显式引用。
  字体同理：`DEFAULT_FONTS = 'song'`，老片显式写 `'fonts': 'heiti'`。
- **v3 不支持 `speed` 参数**，SPEC 的 `voice_settings` 里不要写 speed。
- 中文原速，英文按 `EN_SLOW = 0.8` 用 `atempo` 放慢（音高不变），段间 `PART_GAP = 0.22s` 停顿。
- **整体倍速**：新片默认 `DEFAULT_SPEED = 1.2`（旁白 atempo 1.2、段长等比缩短）——
  15:25 的片子压到 13:53，节奏更紧。**访谈原声默认不动**（`DEFAULT_SPEED_SRC = 1.0`）：
  原声就是学习材料，而且英文旁白特意放到 0.8 倍教发音，把原声加速会跟这个设计打架
  （要一起快就写 `'speed_src': 1.2`，画面会同步 `setpts`）。
  分段之间那 0.22 秒的间隔与跟读停顿**不跟着缩**，那是留给学员喘气和跟读的气口。
  已出片在 SPEC 写 `'speed': 1.0` 锁原速，免得重渲时被新默认改掉。
- 合成前**先把相邻同语种片段合并**：中文被切成半句送 TTS 会得到半句的语调，听起来很怪。
- ElevenLabs 在 SPEC 里可覆盖的三项：`voice` / `model` / `voice_settings`；另有 `en_slow`（1.0 = 英文不变速）、`subs`、`sub_cy`、`work`。

### 5. 新片 SPEC 的标准写法

**新片的 style / fonts / voice / model / voice_settings / speed / foot 全是默认值，SPEC 里一个字都不用写**：
v2 深色 · 宋体 · `eleven_v3` · `V3_EXPRESSIVE` · 1.2 倍速 · 无页脚。所以一条新片的 SPEC 就两行：

```python
SPECS['谷爱凌_<选题>'] = dict(
    src='/Volumes/…/<素材>.mp4',
    cards=[...],                      # 每张卡：n / title / lines / speech / [source] / [tail]
)
```

只有两种情况要显式写：

| 情况 | 写什么 |
|---|---|
| **老片（2026-09 前）要能原样复现** | `'style': 'v1'`、`'fonts': 'heiti'`、`'model': LEGACY_MODEL`、`'voice_settings': LEGACY_VOICE_SETTINGS`、`'speed': 1.0`、`'foot': True`、`'url': True` |
| **派生版**（倍速 / 试听 / 加字幕 / 挑卡） | `'speed'`、`'speed_src'`、`'limit'`、`'cards'`、`'work'`、`'out_dir'` |

> ⚠️ **踩过的坑**：默认值曾经还是「旧规格」（`heiti` + `eleven_multilingual_v2` + style 0），
> 而新片 SPEC 只写 `src` + `cards` —— 于是那条片子悄悄用了**黑体和上一代音色**，跟前后几条完全不是一把声音，
> 是用户听出来的。现在默认值已经改成新规格（见 `一、2/4`），但**出片前仍要扫一眼规格表**（`流程.md` 第 3 步），
> 确认每一条解析出来的 fonts / model / speed 都是想要的。

---

## 二、内容规则（比参数更容易翻车的地方）

1. **一张卡只讲一个点**，一条视频 2–3 个句型，配情绪钩子（不是语法名）。
2. **文案宽度先量再写**：v2 的可用宽度是 **840px**。同一份脚本从 v1（936px）搬到 v2 会大面积超宽——
   实测《开场寒暄》41 张卡里有 7 处超宽，最多超 72px。**改法按优先级**：缩句 → 拆成两行 → 最后才缩字号。
3. **切点只包含该段对话**：原声区间里不要混入节目组的固定插入、垫场音乐、上下段过渡。
   例：《开场寒暄》原片 0–69s 里，客方回应只到 **41.5s**，**42.3–55s** 是节目组插入（「Hey, it's Jay…」对听众说的），**55–69s** 是垫场；
   「完整听一遍」类卡片收到 **26→42s**，收尾重听卡收到 **0→55s**（保留插入、去掉垫场）。
   这类插入应当作**后面章节的教学素材**出现（讲关心话那几张卡），不是灌进听力卡里。
4. **原声卡位**：`source=(起, 止)`；`source` + `speech` 同时存在时，同一张卡拆成两段——
   先讲解（定格帧占住画中画位置）+ 再播原声。`tail` 用来留跟读停顿（3 秒左右）。
   ⚠️ **有 `source` 的卡片，正文必须落在画中画下方（y ≥ 950）**。画中画占 `(135,470)–(945,926)`，
   两段都会画上去，落在这条带里的卡面文字会被整块盖住——实测新片按 490/580/800/890 排了 12 张卡，
   共 47 行被压住。上半区（470–926）只给**没有原声**的讲解卡用。
   线下空间是 y 950–1380，按 950 / 1030 / 1110 / 1190 / 1330 排，最多 5 行（句式提示放 1330）。
5. **试听版（前 N 分钟）**：`limit=N`（渲到累计 ≥N 秒停）。
   ⚠️ **v3 比 v2 慢 25–40%**，沿用旧的 60/120s 上限会把后面几张卡挤掉、前后版本内容对不上——
   要么调大 limit，要么 `limit=None` 后自己挑卡（`cards=[c for c in ... if c['n'] in (...)]`）。
6. **派生版（换音色/加字幕/改切点）必须 `work='<主片目录名>'`**，复用主片已合成的旁白音轨：
   TTS 不保证同文本同结果，重新合成会让「只改了一处」的对比组失真。
7. **精讲笔记 PDF 只排视频讲过的表达**（2026-09 起）：PDF 是视频的纸质版，条目要与视频一一对应，
   不能比视频多出一大截。视频讲了 12 组就排 12 组。
   《表达详解》如果是穷尽式（一段挖 40–60 条，那是给选题库和产品练习用的），**不要整份喂给 `handout.py`**，
   只取视频选中的那几条；给一条视频写详解时，也可以直接按视频的讲解范围写。
   判断标准：学员把 PDF 从头看到尾，应该刚好复习完视频里出现过的每一个表达。
8. **视频和封面里不放任何站外链接，新片连页脚一起不要**（2026-09 起，实测踩坑）：
   小红书把视频/图片里的外链判成站外引流，会直接限流。去掉页脚后正文下沿从 1380 延到 1470，
   有原声的卡从 5 行放到 7 行。官网链接留给精讲笔记 PDF 和主页简介，视频与封面里一个字都别出现。
9. **旁白和卡面写「这句有什么用」，不写「这句多值钱」**（2026-09 起）：
   AI 写讲稿爱用「最值钱的 / 金句 / 全是宝 / 干货 / 封神 / 天花板」这类词**代替说明**——
   听着热闹，学员却拿不到信息，而且一眼看出不是人写的。
   一律换成「什么场合、对谁、起什么作用」。**自查：把这句评价删掉，句子还成立吗？**
   删掉之后信息量为零，就是空话，必须换成具体说明。

   | 别写（AI 味） | 改成（说清用途） |
   |---|---|
   | 本片最值钱的一句 | 谈自我认知最完整的一句，面试和自我介绍都能用 |
   | 整段里最值钱的部分 | 整段最该先学的一组：怎么接夸奖 |
   | 从 52 个表达里挑最值钱的一组 | 从 52 个表达里挑出三句最常用的 |
   | 这一句是语法点里最值钱的一条 | 这一句是本片唯一的语法点：对过去的假设 |
   | 这一条是本片最值钱的隐喻 | lens 是镜头，也是看问题的角度——谈学习路径时能用 |
   | 主持人追问的这一句，全是宝 | 他这两问，一个问兴趣、一个问方向，都能直接搬 |
   | 本片金句：骨子里，我是…… | 她讲「自己是什么样的人」说得最完整的一句 |
   | 这是英语里很高级的一种夸法 | 他在说现象、不下结论——被夸的人不用谦虚，也不用接话 |
   | 一个高级词，加一个高级结构 | 一个书面词 hubris，加一个 the + 名词 + to do 结构 |

   同类禁用词：干货、保姆级、划重点、必看、yyds、狠狠、直接封神、颠覆认知、一文讲透、天花板、宝藏。
   这些词写标题党文案可以（第 8 步的小红书文案另说），**出现在旁白和卡面里就是废话**。
   「最……之一」这类泛化的最高级也要少用，能用「本片唯一的语法点」就别用「语法点里最值钱的一条」。

10. **练习句用邀请式引入，不写免责声明**（2026-09 起）：
    「换你来说」这类卡片的旁白**不要说「这是我们的原创练习句」「这句不是她说的」**——
    听着像在打免责声明，一手把观众从学习状态里拽出来（而且那句话本身没给任何信息）。
    改成把句子直接递过去：**「你也可以试着这样说……」「换成你自己的情况，可以这样说……」**。
    句子后接一句「把 ___ 换成你自己的事」比声明归属有用得多。
    小红书文案同理：不写「视频里的练习句是我们自己写的，不是她说的」，
    需要区分时自然带一句就行，例如「她原话是这几句；练习句照着这个结构换成你自己的版本」。

---

## 三、操作清单

```bash
cd "__DATA_ROOT__/小红书发帖-拾句英语/精细讲解视频"

# 1) 长素材先建库（>30 分钟才需要）
python3 _tools/transcribe.py <素材>            # 转写 → SRT + 词级 JSON
python3 _tools/fix_srt.py                      # 按修正表改错词
python3 _tools/split_srt.py                    # 按话题边界切段

# 2) 版面自检（换了配色/字体/文案必跑，先别花 TTS 钱）
python3 - <<'PY'
import sys; sys.path.insert(0,'_tools')
sys.argv=['x']; import build as B
name='<选题>'
B.apply_style(B.SPECS[name].get('style', B.DEFAULT_STYLE))
B.apply_fonts(B.SPECS[name].get('fonts', B.DEFAULT_FONTS))
avail = B.RIGHT-B.SIDE; bad=0; PIP=(470,926)   # 画中画纵向范围
BOTTOM = 1380 if B.SPECS[name].get('foot') else 1470   # 新片无页脚，正文下沿可到 1470
for c in B.SPECS[name]['cards']:
    ts=62
    while ts>34 and B.font(ts).getlength(c['title'])>avail: ts-=2
    rows=[]
    for y,s,size,col,en in c['lines']:
        w=B.font(size,en).getlength(s)
        if w>avail: print('超宽', c['n'], round(w-avail), s); bad+=1
        b=B.font(size,en).getbbox(s)
        if c.get('source') and y+b[3]>PIP[0] and y+b[1]<PIP[1]:
            print('压画中画', c['n'], y, s); bad+=1      # 有原声的卡，文字必须落在 y≥950
        if y+b[3]>BOTTOM:                                # 墨迹比行位再往下约 1.25×字号
            print('越过下沿', c['n'], y, '墨迹到', y+b[3], f'上限{BOTTOM}', s); bad+=1
        rows.append((y+b[1], y+b[3], s))
    rows.sort()
    for a,b in zip(rows,rows[1:]):
        if b[0]<a[1]: print('压行', c['n'], a[2], '|', b[2]); bad+=1
print('可用宽度', avail, '正文下沿', BOTTOM, '问题数', bad)
PY

# 3) 出片前扫规格表（★ 必做，30 秒；详见 流程.md 第 3 步 ⑤）
#    新片只写 src + cards 是对的；这一步看的是「有没有意外偏离默认规格」
python3 - <<'PY'
import sys; sys.path.insert(0,'_tools'); sys.argv=['x']
import build as B
for k, s in B.SPECS.items():
    vs = s.get('voice_settings', B.DEFAULT_VOICE_SETTINGS)
    has = (B.topic_dir(k)/f'{k}.mp4').exists()
    print(f"{'有片' if has else '无片':<3} {k:28s} {s.get('fonts',B.DEFAULT_FONTS):>5} "
          f"{s.get('model',B.DEFAULT_MODEL):>22} style={vs.get('style')} "
          f"speed={s.get('speed',B.DEFAULT_SPEED)} foot={s.get('foot',False)}")
PY
# 判断：你要渲的那条（显示「无片」）要和最近一条「有片」逐项一致；
#      老片反过来应全是旧规格（它们也是「无片」，因为 mp4 归档到了 废弃/）

# 4) 出片（TTS + 卡片 + 合成 + concat + 写说明.json）
python3 _tools/build.py <选题>

# 5) 校验成片：规格 / 原声完整（逐段转写复核）/ 跟读停顿 / 留白配色
ffprobe -v error -select_streams v:0 -show_entries stream=width,height -of default=nw=1 <成片>
ffmpeg -y -v error -ss <段起> -t <段长> -i <成片> -vn -ac 1 -ar 16000 /tmp/a.wav
/opt/homebrew/bin/whisper /tmp/a.wav --model small --language en --output_format txt --output_dir /tmp --fp16 False

# 6) 封面 + 文案 + PDF + 字幕（四样都要出）
python3 _tools/covers.py <选题>
python3 _tools/handout.py <表达详解>.md        # → A4 PDF，进 Chrome 无头打印
python3 _tools/make_srt.py <选题>              # → <选题>/<选题>.srt（从成片反推）—— 每条都要跑
```

封面/文案/PDF/字幕的具体规范见 `_tools/流程.md` 第 7–10 步。

**出字幕**（`make_srt.py`，**每条视频的常规交付**，不是可选）：文本取脚本里的旁白原文（权威，不受 ASR 错字影响），
时间轴用本地 faster-whisper 的词级时间戳对齐——**按 token 对齐**（中文按字、西文按词），
因为 ASR 常常整段漏掉英文短语，按字符对齐会掉锚点。旁白缓存被清掉之后这也是唯一能对上成片时间轴的办法。
原声片段（只播访谈、没有旁白）不打字幕；要的话从修正版 SRT 按切点平移过来。
两处已知短板：ASR 听不出来的卡会退化成按字数分摊（日志里打 `~`），列表式的慢速朗读会出现 7–11 秒的长条。

---

## 四、已知坑

- **旧片必须锁样式与字体**：`'style': 'v1'`、`'fonts': 'heiti'`。改动了 `apply_style`/`apply_fonts`
  之后，用「渲染卡面 PNG 与原 work 目录里的同名 PNG 逐像素比对」做回归（要求 100% 一致）。
- **`.ttc` 需要字面序号**：`ImageFont.truetype(path, size, index=N)`。
- **字幕模块已实现但暂不启用**（`subs=True` 可开）：白字 + 1px 黑描边、字号 40、单行、
  位置压在画面**中下方**（`sub_cy` 必须用「整条空带」检测脚本量出来，不能拍脑袋）。
  字幕走**窄带透明 PNG 逐条叠**，不走 libass；叠加顺序必须是 **卡面 → 画中画 → 字幕**。
- **外置盘限制**：concat 的输出不能加 `-movflags +faststart`；Python 的 `unlink` 会报 Cross-device link
  （删文件用编辑器/`rm`）；长后台任务先写 `/tmp`。
- **`_说明.json` 里的 `source_clips` 记的是整份脚本的切点**，不是这次实际渲进去的那几张。
- 一条 16 分钟的片子约 150 次 TTS 调用、渲染 5–10 分钟；换 v3 后成片会再长 25–40%。

## 五、音色调试台（改参数时用）

```bash
cd "__DATA_ROOT__/小红书发帖-拾句英语/音色调试"
python3 _tools/voice_lab.py R01        # 跑一轮：同文本 × 多组音色参数 → 短音频 + 连播对比 + 台账
python3 _tools/voice_lab.py            # 列出所有轮次
```

- 样本落在 `samples/<轮次>/`，同一条文本的多个方案串成 `对比_<文本>_按序号带提示音.mp3`
  （**1 声＝01 号方案，2 声＝02 号**，依次类推）。
- 指标由 `_tools/prosody.py` 量：时长 / 语速 / 基调中位 / **语调跨度** / **抖动** / 停顿。
  **指标只做相对比较**，自相关估音高对中文短音节本来就粗，最终结论靠耳朵。
- 台子里的合成直接复用渲染器的实现（同一个 key、同一套缓存签名），所以在这里选出的参数
  写回 `build.py` 后听感完全一致。
- 选定后回填 `build.py`：`V3_EXPRESSIVE`（或 `DEFAULT_VOICE_SETTINGS`）。

## 六、外部依赖

- ElevenLabs key 放在 `精细讲解视频/.env.elevenlabs`（**只有这把有 TTS 权限**；
  `OpenMontage/.env` 里那把没有）。
- 中文母语 TTS（豆包/火山）**尚未接通**：需要 `DOUBAO_SPEECH_API_KEY` 与一个 Speech 2.0 音色 id，
  写入 `OpenMontage/.env`；调用参考 `OpenMontage/tools/audio/doubao_tts.py` 与
  `.agents/skills/doubao-tts/SKILL.md`。
