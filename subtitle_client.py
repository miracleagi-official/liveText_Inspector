# filename: subtitle_client.py
"""
자막 출력 서버 클라이언트 (Persistent TCP Version, Little Endian)

프로토콜 요약
[요청]
  header (8B) : [checkcode(int32 LE), request_code(int32 LE)]
  body   (4+N): [data_size(int32 LE), text_data(N bytes, UTF-8)]

[응답]
  header (8B) : [resp_checkcode(int32 LE), request_code(int32 LE)]
  body   (1B) : [status(uint8)]  # 0 = OK
"""

import socket
import struct
from typing import Optional, Callable
import json

# 요청/응답 코드
REQUEST_SUBTITLE = 0x01          # 자막 전송 요청 코드 (req/resp 공통)
RESP_CHECKCODE   = 0x01350126    # 서버 응답용 체크코드 (int32 값)
STATUS_OK        = 0             # 응답 status == 0 이면 성공

StatusCallback = Callable[[str], None]


class SubtitleClient:
    """
    자막 출력 서버와 '상시 연결'을 유지하면서
    STT 결과가 나올 때마다 send_subtitle()로 자막을 푸시하는 클라이언트.

    - AudioProcessor 쪽에서 하는 일:
        - 시작 시:   subtitle_client.connect()
        - STT 결과:  subtitle_client.send_subtitle(json_text)
        - 종료 시:   subtitle_client.disconnect()
    """

    def __init__(
        self,
        host: str,
        port: int,
        checkcode: int,
        status_cb: Optional[StatusCallback] = None,
    ):
        self.host = host
        self.port = port
        self.checkcode = checkcode
        self._status_cb = status_cb or (lambda msg: None)

        self._sock: Optional[socket.socket] = None

    # ----------------------------------------------------------
    # 내부 유틸
    # ----------------------------------------------------------
    def _log(self, msg: str) -> None:
        self._status_cb(f"[SUBTITLE] {msg}")

    def _recv_exact(self, n: int) -> bytes:
        """
        내부 소켓에서 n 바이트를 정확히 읽어온다.
        (끊기면 예외 발생)
        """
        if not self._sock:
            raise ConnectionError("socket is not connected")

        buf = b""
        while len(buf) < n:
            chunk = self._sock.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("socket closed while receiving")
            buf += chunk
        return buf

    def _ensure_connection(self, timeout: float = 5.0) -> bool:
        """
        이미 연결되어 있으면 True,
        아니면 새로 연결을 시도하고 성공 시 True, 실패 시 False.
        """
        if self._sock is not None:
            return True

        try:
            sock = socket.create_connection((self.host, self.port), timeout=timeout)
            # 읽기 타임아웃도 설정 (응답 대기 시 블록 방지)
            sock.settimeout(timeout)
            self._sock = sock
            self._log(f"connected to {self.host}:{self.port}")
            return True
        except Exception as e:
            self._log(f"connect fail: {e}")
            self._sock = None
            return False

    # ----------------------------------------------------------
    # 공개 API
    # ----------------------------------------------------------
    def connect(self) -> bool:
        """
        AudioProcessor.start()에서 호출할 연결 함수.
        여러 번 호출해도 문제없도록 idempotent 하게 동작.
        """
        return self._ensure_connection()

    def disconnect(self) -> None:
        """
        AudioProcessor.stop()에서 호출할 종료 함수.
        소켓을 닫고 상태를 초기화.
        """
        if self._sock is not None:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None
            self._log("disconnected")

    @property
    def is_connected(self) -> bool:
        """현재 내부적으로 소켓이 살아 있는지 여부"""
        return self._sock is not None

    # ----------------------------------------------------------
    def send_subtitle(self, text: str, encoding: str = "utf-8") -> bool:
        """
        자막 문자열을 서버로 전송.
        - text: 일반 문자열이든, JSON 문자열이든 그대로 UTF-8 인코딩해서 전송
        - return: True면 정상 전송 + status == 0, False면 에러
        """
        text = (text or "").strip()
        if not text:
            # 빈 문자열은 보내지 않음
            return False

        # 연결 보장
        if not self._ensure_connection():
            return False

        try:
            # 1) 패킷 구성 (Little Endian)
            text_bytes = text.encode(encoding)
            size = len(text_bytes)

            header = struct.pack("<ii", self.checkcode, REQUEST_SUBTITLE)
            body = struct.pack("<i", size) + text_bytes
            packet = header + body

            # 2) 전송
            self._sock.sendall(packet)

            # 3) 응답 수신
            #    - header(8B): [resp_checkcode, request_code]
            resp_header = self._recv_exact(8)
            resp_check, resp_code = struct.unpack("<ii", resp_header)

            if resp_check != RESP_CHECKCODE:
                self._log(
                    f"invalid resp_checkcode: {resp_check:#x} "
                    f"(expected {RESP_CHECKCODE:#x})"
                )
                return False

            if resp_code != REQUEST_SUBTITLE:
                self._log(
                    f"mismatched resp_code: {resp_code} "
                    f"(expected {REQUEST_SUBTITLE})"
                )
                return False

            #    - body(1B): [status]
            status_bytes = self._recv_exact(1)
            status = status_bytes[0]

            if status != STATUS_OK:
                self._log(f"server returned error status={status}")
                return False

            self._log(f"subtitle sent OK (len={size})")
            return True

        except Exception as e:
            # 소켓 에러 → 다음 호출에서 재연결하도록 소켓 정리
            self._log(f"send_subtitle error: {e} → will reconnect next time")
            self.disconnect()
            return False

    def send_subtitle_json(self, payload: dict) -> bool:
        """
        dict → JSON 직렬화 → send_subtitle() 호출
        """
        try:
            txt = json.dumps(payload, ensure_ascii=False)
        except Exception as e:
            self._log(f"json encoding error: {e}")
            return False
        
        return self.send_subtitle(txt)