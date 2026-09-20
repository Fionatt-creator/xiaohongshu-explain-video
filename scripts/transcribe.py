"""长视频/音频转写（faster-whisper）

用法（在素材所在目录执行，输出会写在素材旁边）：
    cd <素材目录>
    /opt/homebrew/bin/python3 <此脚本路径> <媒体文件> [模型档位]

模型档位实测（Apple Silicon CPU / int8）：
    small    约 4.2x 实时 → 1 小时约 15 分钟（默认，先用它跑通）
    medium   约 1.7x 实时 → 1 小时约 37 分钟（要更准时用）

产物：<同名>.srt（给人看/做封面字幕）、<同名>.json（带词级时间戳，给切点用）
"""
import sys, json, time, subprocess as sp
from pathlib import Path
from faster_whisper import WhisperModel


def hms(t, comma=True):
    h = int(t//3600); m = int(t % 3600//60); s = int(t % 60); ms = int(round((t-int(t))*1000))
    return f'{h:02d}:{m:02d}:{s:02d}{"," if comma else "."}{ms:03d}'


def main():
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    src = Path(sys.argv[1]).resolve()
    size = sys.argv[2] if len(sys.argv) > 2 else 'small'

    wav = Path('/tmp')/f'{src.stem}.16k.wav'
    if not wav.exists():
        print('抽取音频…', flush=True)
        sp.run(['ffmpeg', '-y', '-v', 'error', '-i', str(src), '-vn', '-ac', '1', '-ar', '16000', str(wav)], check=True)

    print(f'加载模型 {size} …', flush=True)
    model = WhisperModel(size, device='cpu', compute_type='int8')
    t0 = time.time()
    segments, info = model.transcribe(str(wav), language='en', word_timestamps=True,
                                      vad_filter=True, condition_on_previous_text=False)

    rows, srt = [], []
    for i, s in enumerate(segments, 1):
        txt = s.text.strip()
        if not txt:
            continue
        rows.append({'start': round(s.start, 3), 'end': round(s.end, 3), 'text': txt,
                     'words': [{'start': round(w.start, 3), 'end': round(w.end, 3), 'word': w.word}
                               for w in (s.words or [])]})
        srt.append(f'{len(rows)}\n{hms(s.start)} --> {hms(s.end)}\n{txt}\n')
        if len(rows) % 100 == 0:
            el = time.time()-t0
            print(f'  {len(rows)} 段，已用时 {el/60:.1f} 分钟', flush=True)

    base = src.with_suffix('')
    # 先写 /tmp（长任务的后台沙箱不允许写外置盘），跑完再单独复制到素材目录
    tmp_srt = Path('/tmp')/f'{base.name}.{size}.srt'
    tmp_json = Path('/tmp')/f'{base.name}.{size}.json'
    tmp_srt.write_text('\n'.join(srt), encoding='utf-8')
    tmp_json.write_text(json.dumps({'model': size, 'duration': info.duration,
                                    'segments': rows}, ensure_ascii=False), encoding='utf-8')
    print(f'DONE 共 {len(rows)} 段，耗时 {(time.time()-t0)/60:.1f} 分钟', flush=True)
    print(f'  {tmp_srt}', flush=True)
    print(f'  {tmp_json}', flush=True)
    print(f'把这两个文件复制到素材目录即可：{base.parent}', flush=True)


if __name__ == '__main__':
    main()
