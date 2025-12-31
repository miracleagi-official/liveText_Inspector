"""
subtitle_server.py - STT 자막 수신 테스트 서버
"""
import socket
import struct
import threading
import json
import re
import os
from dotenv import load_dotenv

load_dotenv()

HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "26071"))
RESP_CHECKCODE = int(os.getenv("RESP_CHECKCODE", "20250918"), 0)
RAW_OUT_PATH = os.getenv("RAW_OUT_PATH", "./raw_subtitle.txt")

running = True
_raw_lock = threading.Lock()


def append_raw_text(token: str):
    """토큰을 파일에 저장 (문장 부호 뒤에 줄바꿈)"""
    if not token or not token.strip():
        return

    token = token.strip()
    
    # 문장 종료 부호로 분리
    parts = re.split(r'([?!.])', token)
    out_chunks = []
    
    for i in range(0, len(parts), 2):
        chunk = parts[i]
        punct = parts[i + 1] if i + 1 < len(parts) else ""
        if not chunk and not punct:
            continue
        out_chunks.append(chunk + punct)
        out_chunks.append("\n" if punct else " ")

    out = "".join(out_chunks)

    with _raw_lock:
        with open(RAW_OUT_PATH, "a", encoding="utf-8") as f:
            f.write(out)


def handle_client(conn: socket.socket, addr):
    """클라이언트 연결 처리"""
    print(f"[CLIENT] connected from {addr}")
    
    try:
        while True:
            # 헤더 수신
            header = conn.recv(8)
            if not header or len(header) < 8:
                break

            checkcode, req_code = struct.unpack("<ii", header)

            # 데이터 크기 수신
            size_bytes = conn.recv(4)
            if len(size_bytes) < 4:
                break

            (data_size,) = struct.unpack("<i", size_bytes)
            
            # 페이로드 수신
            remaining = data_size
            chunks = []
            while remaining > 0:
                chunk = conn.recv(remaining)
                if not chunk:
                    raise ConnectionError("client closed mid-transfer")
                chunks.append(chunk)
                remaining -= len(chunk)

            payload = b"".join(chunks)
            text = payload.decode("utf-8", errors="replace")

            print("--------------------------------------------------")
            print(f"[TEXT] {text}")
            
            # JSON 파싱 및 저장
            try:
                obj = json.loads(text)
                token = obj.get("text", "")
                append_raw_text(token)
            except json.JSONDecodeError as e:
                print(f"[WARN] failed to parse JSON: {e}")

            # 응답 전송
            resp_header = struct.pack("<ii", RESP_CHECKCODE, req_code)
            conn.sendall(resp_header + struct.pack("B", 0))

    except Exception as e:
        print(f"[CLIENT ERROR] {addr}: {e}")
    finally:
        conn.close()
        print(f"[CLIENT] disconnected: {addr}")


def main():
    global running

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server_sock:
        server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_sock.bind((HOST, PORT))
        server_sock.listen()
        server_sock.settimeout(1.0)

        print(f"[SERVER] running on {HOST}:{PORT}")
        print("[CTRL+C] to stop server")

        try:
            while running:
                try:
                    conn, addr = server_sock.accept()
                    t = threading.Thread(target=handle_client, args=(conn, addr), daemon=True)
                    t.start()
                except socket.timeout:
                    pass

        except KeyboardInterrupt:
            print("\n[SERVER] Shutdown requested...")
        finally:
            running = False
            print("[SERVER] Closed.")


if __name__ == "__main__":
    main()
