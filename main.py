"""
main.py - STT Live Monitor 메인 애플리케이션
"""
import tkinter as tk
from tkinter import ttk, messagebox
import threading
import socket
import struct
import json
import os
from typing import List, Optional
from dotenv import load_dotenv

from ui.main_window import MainWindow
from alignment import compute_alignment, AlignType
from subtitle_client import SubtitleClient

from etc import get_base_dir, resource_path

# 환경 변수 로드
load_dotenv()


class STTMonitorApp:
    """STT 모니터 애플리케이션 컨트롤러"""
    
    def __init__(self, root: tk.Tk):
        
        # 1. .env 파일 경로 설정 (실행파일과 같은 위치)
        env_path = os.path.join(get_base_dir(), ".env")
        
        # 2. 로드 시도 및 결과 확인
        is_loaded = load_dotenv(env_path)
        
        # 모니터 서버 설정
        self.HOST = os.getenv("HOST", "127.0.0.1")
        self.PORT = int(os.getenv("PORT", "26072"))
        self.RESP_CHECKCODE = int(os.getenv("RESP_CHECKCODE", "20250918"), 0)
        self.RAW_OUT_PATH = os.getenv("RAW_OUT_PATH", "./raw_out")
        
        # 자막 서버 설정
        self.SUBTITLE_HOST = os.getenv("SUBTITLE_HOST", "127.0.0.1")
        self.SUBTITLE_PORT = int(os.getenv("SUBTITLE_PORT", "26071"))
        self.SUBTITLE_CHECKCODE = int(os.getenv("RESP_CHECKCODE", "20250918"), 0)
        self.OUTPUT_SUBTITLE_INSERTER_ENABLE = os.getenv("OUTPUT_SUBTITLE_INSERTER_ENABLE", "false").lower() == "true"
        
        # 유사도 임계값 (환경변수로 조정 가능)
        self.SIMILARITY_THRESHOLD = float(os.getenv("SIMILARITY_THRESHOLD", "0.6"))
        
        if not os.path.exists(self.RAW_OUT_PATH):
            os.makedirs(self.RAW_OUT_PATH)
        
        # 상태 관리
        self.reference_text = ""
        self.hypothesis_tokens: List[str] = []
        self._tokens_lock = threading.Lock()
        
        self.is_running = False
        self.is_completed = False  # 자막 비교 완료 플래그
        self.server_sock = None
        
        # 자막 클라이언트 초기화
        self.subtitle_client: Optional[SubtitleClient] = None
        self.subtitle_connected = False
        
        # UI 초기화
        self.ui = MainWindow(root, appVersion="1.0.0")
        self._bind_ui_callbacks()
        
        if is_loaded:
            msg = (f".env 설정을 불러왔습니다.\n\n"
                   f"Path: {env_path}\n"
                   f"모니터 서버: {self.HOST}:{self.PORT}\n"
                   f"자막 서버: {self.SUBTITLE_HOST}:{self.SUBTITLE_PORT}\n"
                   f"SIMILARITY: {self.SIMILARITY_THRESHOLD}")
            messagebox.showinfo("설정 로드 성공", msg)
        else:
            msg = (f".env 파일을 찾을 수 없어 기본값으로 시작합니다.\n\n"
                   f"시도한 경로: {env_path}\n"
                   f"모니터 PORT: {self.PORT}\n"
                   f"자막 PORT: {self.SUBTITLE_PORT}")
            messagebox.showwarning("설정 로드 실패", msg)
            
        self.subtitle_client = None
        if self.OUTPUT_SUBTITLE_INSERTER_ENABLE:        
            # 자막 서버 연결 시도
            self._connect_subtitle_server()
        else :
            self.ui.set_subtitle_status("자막 서버 출력 비활성화", "gray")            
        
        
        # 자동으로 모니터 서버 시작
        self._auto_start_server()
        
    def _connect_subtitle_server(self):
        """자막 서버에 연결 시도"""
        self.subtitle_client = SubtitleClient(
            host=self.SUBTITLE_HOST,
            port=self.SUBTITLE_PORT,
            checkcode=self.SUBTITLE_CHECKCODE,
            status_cb=lambda msg: print(msg)
        )
        
        self.subtitle_connected = self.subtitle_client.connect()
        
        if self.subtitle_connected:
            self.ui.set_subtitle_status(f"자막 서버 연결됨 ({self.SUBTITLE_HOST}:{self.SUBTITLE_PORT})", "green")
        else:
            self.ui.set_subtitle_status(f"자막 서버 연결 실패 ({self.SUBTITLE_HOST}:{self.SUBTITLE_PORT})", "red")
        
    def _bind_ui_callbacks(self):
        """UI 콜백 바인딩"""
        self.ui.set_on_load_reference(self._load_reference)
        self.ui.set_on_reset(self._reset_state)
        self.ui.set_on_closing(self._on_closing)
        self.ui.set_on_reconnect_subtitle(self._reconnect_subtitle_server)
        
    def _reconnect_subtitle_server(self):
        """자막 서버 재연결"""
        if self.subtitle_client:
            self.subtitle_client.disconnect()
        self._connect_subtitle_server()
        
    def _load_reference(self):
        """대본 파일 로드 (화면에 표시하지 않음)"""
        file_path = self.ui.ask_open_file()
        if not file_path:
            return
            
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                raw_text = f.read().strip()
                self.reference_text = " ".join(raw_text.split())
            
            # 대본 로드 시 화면에 표시하지 않음 (비교 시작 시에만 표시)
            self.ui.clear_display()
            self.ui.set_status(f"대본 로드 완료 ({len(self.reference_text)}자) - 대기 중", "blue")
            
            # 상태 초기화
            with self._tokens_lock:
                self.hypothesis_tokens = []
            self.is_completed = False  # 완료 플래그 초기화
            self.ui.reset_metrics()
            
        except Exception as e:
            self.ui.show_error("Error", f"파일 로드 실패: {e}")
            
    def _reset_state(self):
        """상태 초기화"""
        with self._tokens_lock:
            self.hypothesis_tokens = []
        
        self.is_completed = False  # 완료 플래그 초기화
        self.ui.reset_metrics()
        self.ui.clear_display()
        
        if self.reference_text:
            self.ui.set_status(f"대본 로드됨 ({len(self.reference_text)}자) - 초기화됨", "blue")
        else:
            self.ui.set_status(f"모니터링 중... ({self.HOST}:{self.PORT})", "green")
            
    def _auto_start_server(self):
        """앱 시작 시 자동으로 서버 시작"""
        if self.is_running:
            return
            
        self.is_running = True
        
        if self.reference_text:
            self.ui.set_status(f"모니터링 중... ({self.HOST}:{self.PORT})", "green")
        else:
            self.ui.set_status(f"모니터링 중 (대본 없음) - {self.HOST}:{self.PORT}", "green")
        
        # 서버 스레드 시작
        threading.Thread(target=self._server_loop, daemon=True).start()
        
        # 주기적 업데이트 스케줄 (500ms마다)
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
                        print(f"[Received] {token}")
                        if token:
                            with self._tokens_lock:
                                self.hypothesis_tokens.append(token)
                            
                            # 자막 서버로 전송
                            if self.subtitle_client and self.subtitle_connected:
                                self._forward_to_subtitle_server(text_data)
                            # else:
                            #     print("[Subtitle] 자막 서버에 연결되지 않음, 전송 생략")
                            
                    except json.JSONDecodeError:
                        pass
                        
                    # 응답 전송
                    resp_header = struct.pack("<ii", self.RESP_CHECKCODE, req_code)
                    conn.sendall(resp_header + struct.pack("B", 0))
                    
            except Exception as e:
                print(f"[Client Error] {e}")
    
    def _forward_to_subtitle_server(self, text_data: str):
        """자막 서버로 데이터 전송"""
        if not self.subtitle_client:
            return
            
        if not self.subtitle_connected:
            # 재연결 시도
            self.subtitle_connected = self.subtitle_client.connect()
            if self.subtitle_connected:
                # UI 업데이트는 메인 스레드에서
                self.ui.root.after(0, lambda: self.ui.set_subtitle_status(
                    f"자막 서버 재연결됨 ({self.SUBTITLE_HOST}:{self.SUBTITLE_PORT})", "green"))
            else:
                return
        
        # 전송 시도
        success = self.subtitle_client.send_subtitle(text_data)
        if not success:
            self.subtitle_connected = False
            # UI 업데이트는 메인 스레드에서
            self.ui.root.after(0, lambda: self.ui.set_subtitle_status(
                f"자막 서버 연결 끊김", "red"))
                
    def _schedule_update(self):
        """500ms마다 UI 및 메트릭 갱신"""
        if self.is_running:
            self._update_display()
            self.ui.schedule(500, self._schedule_update)
            
    def _update_display(self):
        """정렬 수행 및 UI 업데이트"""
        # 이미 완료된 경우 더 이상 비교하지 않음
        if self.is_completed:
            return
            
        with self._tokens_lock:
            if not self.hypothesis_tokens:
                return
            hyp_text = " ".join(self.hypothesis_tokens)
        
        # 대본이 없으면 단순 출력 모드
        if not self.reference_text:
            self.ui.render_text(hyp_text, "hit")  # 초록색으로 출력
            return
            
        # 정렬 및 메트릭 계산 (관대한 비교 모드)
        aligned_tokens, metrics = compute_alignment(
            self.reference_text, 
            hyp_text,
            similarity_threshold=self.SIMILARITY_THRESHOLD
        )
        
        # 자막 완료 여부 체크 (PENDING이 없으면 완료)
        has_pending = any(t.align_type == AlignType.PENDING for t in aligned_tokens)
        
        if not has_pending:
            self.is_completed = True
            self.ui.set_status("✓ 자막 비교 완료!", "green")
        
        # UI 업데이트
        self.ui.render_aligned_tokens(aligned_tokens)
        self.ui.update_metrics(metrics)
        
    def _on_closing(self):
        """종료 처리"""
        self.is_running = False
        if self.server_sock:
            self.server_sock.close()
        if self.subtitle_client:
            self.subtitle_client.disconnect()


def main():
    root = tk.Tk()
    app = STTMonitorApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()