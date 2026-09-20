# 小红书精讲视频 · 拾句英语

把访谈 / 播客素材做成 **9:16 英语精讲视频** 的完整流水线，一条素材进去，一次产出全套配套：

**成片 · 封面 · 发帖文案 · 精讲笔记 PDF · 讲解字幕 SRT**

> 这是一个可安装的 **TRAE skill**：仓库根目录就是 skill 目录（`SKILL.md` 是入口），
> 用 TRAE 的「安装 skill」从本仓库 URL 安装即可，装完即本机的「小红书精讲视频」技能。

## 产出清单

| 产出 | 说明 |
|---|---|
| 成片 | 1080×1920（9:16），逐句详尽讲解重点表达，不设数量上限 |
| 封面 | 3:4，人脸聚类自动找帧，配色/字体与成片同源 |
| 发帖文案 | 标题 + 正文 + 标签，控字数、去 markdown 符号 |
| 精讲笔记 PDF | 视频讲过的表达排成 A4 学习资料（Chrome 无头打印） |
| 讲解字幕 SRT | 从成片反推时间轴（旁白原文 + 本地 ASR 词级对齐） |

## 目录结构

```
xiaohongshu-explain-video/
├── SKILL.md          技能入口：规格参数 + 内容规则 + 操作清单 + 已知坑
├── references/
│   └── 流程.md       十步操作 SOP（从素材到交付）
└── scripts/          工具脚本
    ├── build.py           渲染器（SPEC 登记 + TTS + 卡片 + 合成）
    ├── covers.py          封面生成
    ├── handout.py         精讲笔记 A4 PDF
    ├── make_srt.py        从成片反推字幕 SRT
    ├── transcribe.py      长素材转写（faster-whisper）
    ├── fix_srt.py         按修正表改错词
    ├── split_srt.py       按话题边界切段
    ├── auto_build.py      队列自动出片
    ├── voice_lab.py       音色参数调试台
    └── prosody.py         语调/节奏指标（纯 numpy）
```

## 快速开始

**1. 安装**：用 TRAE 的「安装 skill」，指向本仓库（或本仓库的 zip 下载地址）。

**2. 配置**：仓库是「通用化」版本，私有信息已替换成占位符，用前全局搜索替换：

| 占位符 | 换成 |
|---|---|
| `__DATA_ROOT__` | 你的素材 / 数据盘根目录 |
| `__WORKSPACE__` | 你的代码工作区 |
| `__HOME__` | 你的用户目录 |
| `__VOICE_ID__` | 你的 ElevenLabs 音色 ID |

品牌常量（`拾句英语`、官网 URL、logo 路径）在各脚本顶部的 `BRAND_*` / `LOGO` / `URL` 里，改成你自己的品牌即可。

**3. 密钥**：ElevenLabs key 放在运行目录的 `.env.elevenlabs`（或环境变量 `ELEVENLABS_API_KEY`），
脚本只从那里读，**密钥绝不入库**。

**4. 依赖**：

```bash
pip install requests pillow faster-whisper numpy
```

系统还需要 `ffmpeg` 和 Google Chrome（PDF 无头打印用）。

## 锁定规格（速览）

- 画布 1080×1920（9:16），上留白 190px / 下 417px / 左右 120px，可用宽 840px
- 新片默认：v2 深色 · 宋体 + Arial 斜体 · `eleven_v3`（style 0.4）· 旁白 1.2×（英文再放慢到 0.8×）
- 视频 / 封面不放站外链接（避免平台限流）

完整规格与踩坑记录见 `SKILL.md` 与 `references/流程.md`。
