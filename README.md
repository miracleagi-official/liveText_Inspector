# ASR BenchMarker

## setup

```bash
uv venv --python=3.11 .venv
uv init

```

## usage

정답을 맞추면 녹색으로 표시  
틀리면 빨간색으로 표시

```python
 # 색상 매핑
    TAG_COLORS = {
        AlignType.PENDING: "white",    # 아직 안 읽음
        AlignType.HIT: "#00FF00",      # 초록 (정답)
        AlignType.SUB: "#FF0000",      # 빨강 (오인식)
        AlignType.DEL: "#FFFF00",      # 노랑 (누락)
        AlignType.INS: "#FFA500",      # 오렌지 (추가)
    }
```

## build

```bash
pyinstaller --noconsole --onefile --icon="icon.ico" --add-data="icon.png;." --name "liveText_Inspector" main.py
```