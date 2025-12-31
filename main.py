"""
main.py - STT Live Monitor 메인 애플리케이션
"""
import tkinter as tk
import threading
import socket
import struct
import json
import os
from typing import List
from dotenv import load_dotenv

from ui import MainWindow
from alignment import compute_alignment, AlignType

# 환경 변수 로드
load_dotenv()


class STTMonitorApp:
    """STT 모니터 애플리케이션 컨트롤러"""
    
    def __init__(self, root: tk.Tk):
        # 설정 로드
        self.HOST = os.getenv("HOST", "127.0.0.1")
        self.PORT = int(os.getenv("PORT", "26071"))
        self.RESP_CHECKCODE = int(os.getenv("RESP_CHECKCODE", "20250918"), 0)
        self.RAW_OUT_PATH = os.getenv("RAW_OUT_PATH", "./raw_out")
        
        if not os.path.exists(self.RAW_OUT_PATH):
            os.makedirs(self.RAW_OUT_PATH)
        
        # 상태 관리
        self.reference_text = ""
        self.hypothesis_tokens: List[str] = []
        self._tokens_lock = threading.Lock()
        
        self.is_running = False
        self.server_sock = None
        
        # UI 초기화
        self.ui = MainWindow(root)
        self._bind_ui_callbacks()
        
    def _bind_ui_callbacks(self):
        """UI 콜백 바인딩"""
        self.ui.set_on_load_reference(self._load_reference)
        self.ui.set_on_start_server(self._start_server)
        self.ui.set_on_reset(self._reset_state)
        self.ui.set_on_closing(self._on_closing)
        
    def _load_reference(self):
        """대본 파일 로드"""
        file_path = self.ui.ask_open_file()
        if not file_path:
            return
            
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                raw_text = f.read().strip()
                self.reference_text = " ".join(raw_text.split())
                
            self.ui.render_text(self.reference_text, AlignType.PENDING.value)
            self.ui.set_status(f"대본 로드 완료 ({len(self.reference_text)}자)", "blue")
        except Exception as e:
            self.ui.show_error("Error", f"파일 로드 실패: {e}")
            
    def _reset_state(self):
        """상태 초기화"""
        with self._tokens_lock:
            self.hypothesis_tokens = []
            
        self.ui.reset_metrics()
        if self.reference_text:
            self.ui.render_text(self.reference_text, AlignType.PENDING.value)
            
    def _start_server(self):
        """모니터링 서버 시작"""
        if not self.reference_text:
            self.ui.show_warning("경고", "대본 파일을 먼저 로드해주세요.")
            return
            
        if self.is_running:
            return
            
        self.is_running = True
        self.ui.set_monitoring_mode(True)
        self.ui.set_status(f"모니터링 중... ({self.HOST}:{self.PORT})", "red")
        
        # 서버 스레드 시작
        threading.Thread(target=self._server_loop, daemon=True).start()
        
        # 주기적 업데이트 스케줄
        self._schedule_update()
        
    def _server_loop(self):
        """서버 메인 루프"""
        try:
            self.server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.server_sock.bind((self.HOST, self.PORT))
            self.server_sock.listen(5)
            self.server_sock.settimeout(1.0)
            
            while self.is_running:
                try:
                    conn, addr = self.server_sock.accept()
                    threading.Thread(
                        target=self._handle_client, 
                        args=(conn,), 
                        daemon=True
                    ).start()
                except socket.timeout:
                    continue
        except Exception as e:
            print(f"[Server Error] {e}")
        finally:
            if self.server_sock:
                self.server_sock.close()
                
    def _handle_client(self, conn: socket.socket):
        """클라이언트 연결 처리"""
        with conn:
            try:
                while self.is_running:
                    # 헤더 수신 (checkcode, req_code)
                    header = conn.recv(8)
                    if not header or len(header) < 8:
                        break
                        
                    checkcode, req_code = struct.unpack("<ii", header)
                    
                    # 데이터 크기 수신
                    size_bytes = conn.recv(4)
                    if not size_bytes:
                        break
                    (data_size,) = struct.unpack("<i", size_bytes)
                    
                    # 페이로드 수신
                    payload = b""
                    while len(payload) < data_size:
                        chunk = conn.recv(data_size - len(payload))
                        if not chunk:
                            break
                        payload += chunk
                        
                    text_data = payload.decode("utf-8", errors="replace")
                    
                    # JSON 파싱 및 토큰 추가
                    try:
                        obj = json.loads(text_data)
                        token = obj.get("text", "").strip()
                        if token:
                            with self._tokens_lock:
                                self.hypothesis_tokens.append(token)
                    except json.JSONDecodeError:
                        pass
                        
                    # 응답 전송
                    resp_header = struct.pack("<ii", self.RESP_CHECKCODE, req_code)
                    conn.sendall(resp_header + struct.pack("B", 0))
                    
            except Exception as e:
                print(f"[Client Error] {e}")
                
    def _schedule_update(self):
        """10초마다 UI 및 메트릭 갱신"""
        if self.is_running:
            self._update_display()
            self.ui.schedule(10000, self._schedule_update)
            
    def _update_display(self):
        """정렬 수행 및 UI 업데이트"""
        if not self.reference_text:
            return
            
        with self._tokens_lock:
            if not self.hypothesis_tokens:
                return
            hyp_text = " ".join(self.hypothesis_tokens)
            
        # 정렬 및 메트릭 계산
        aligned_tokens, metrics = compute_alignment(self.reference_text, hyp_text)
        
        # UI 업데이트
        self.ui.render_aligned_tokens(aligned_tokens)
        self.ui.update_metrics(metrics)
        
    def _on_closing(self):
        """종료 처리"""
        self.is_running = False
        if self.server_sock:
            self.server_sock.close()


def main():
    root = tk.Tk()
    app = STTMonitorApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
