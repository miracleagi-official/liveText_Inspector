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

## test_recv.py (테스트용 수신 서버)

`main.py`(`STTMonitorApp`)와 별도로, 콘솔에서 원문 payload를 그대로 확인하는 테스트 스크립트다.

- `HOST` / `PORT` : subtitle 프로토콜 수신 (`<checkcode><req><size><payload>`)
- `EVENT_SERVER_HOST` / `EVENT_SERVER_PORT` : liveSpeaker 이벤트(JSON line) 수신
- JSON 파싱 없이 수신 문자열을 그대로 출력

실행:

```bash
python test_recv.py
```

주의:

- `liveSpeaker` 오디오 프록시(`AUDIO_PROXY_PORT`)와 `liveText_Inspector`의 `PORT`를 같은 값으로 두면 포트 충돌이 발생한다.
- 예: `liveSpeaker`가 `26071`을 쓰는 경우, Inspector 수신 포트는 `26072` 등 다른 포트 사용 권장.
