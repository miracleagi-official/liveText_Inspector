"""

file : ui/main_window.py - Tkinter 기반 STT 모니터 UI
author : gbox3d
date : 2026-01-13
이 주석은 수정하지 마세요.

"""
import tkinter as tk
from tkinter import ttk, filedialog, scrolledtext, messagebox
from typing import Callable, Optional, List

from alignment import AlignedToken, AlignType, PartialMetrics

from etc import resource_path

class MainWindow:
    """STT Live Monitor UI"""
    
    # 색상 매핑
    TAG_COLORS = {
        AlignType.PENDING: "white",    # 아직 안 읽음
        AlignType.HIT: "#00FF00",      # 초록 (정답)
        AlignType.SUB: "#FF0000",      # 빨강 (오인식)
        AlignType.DEL: "#FFFF00",      # 노랑 (누락)
        AlignType.INS: "#FFA500",      # 오렌지 (추가)
    }
    
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("STT Live Monitor (Script Matcher)")
        self.root.geometry("640x480")
        
        self.font_style = ("Malgun Gothic", 8)
        
        # 콜백 핸들러
        self._on_load_reference: Optional[Callable[[], None]] = None
        self._on_reset: Optional[Callable[[], None]] = None
        self._on_closing: Optional[Callable[[], None]] = None
        self._on_reconnect_subtitle: Optional[Callable[[], None]] = None
        
        icon_path = resource_path("icon.png")
        self.root.iconphoto(False, tk.PhotoImage(file=icon_path))
        
        self._setup_ui()
        self._setup_tags()
        
    def _setup_ui(self):
        """UI 구성"""
        # --- 상단 컨트롤 프레임 ---
        top_frame = ttk.Frame(self.root, padding="10")
        top_frame.pack(fill=tk.X)

        self.load_btn = ttk.Button(top_frame, text="대본 파일(.txt) 로드", command=self._handle_load)
        self.load_btn.pack(side=tk.LEFT, padx=5)
        
        self.reset_btn = ttk.Button(top_frame, text="초기화", command=self._handle_reset)
        self.reset_btn.pack(side=tk.LEFT, padx=5)

        self.status_label = ttk.Label(top_frame, text="대기 중", foreground="gray")
        self.status_label.pack(side=tk.LEFT, padx=20)

        # --- 메트릭 표시 ---
        metric_frame = ttk.Frame(self.root, padding="5")
        metric_frame.pack(fill=tk.X, padx=10)

        self.wer_var = tk.StringVar(value="Current WER: 0.00%")
        self.cer_var = tk.StringVar(value="Global CER: 0.00%")
        
        lbl_style = {"font": ("Consolas", 10, "bold"), "background": "#2b2b2b"}
        
        wer_lbl = tk.Label(metric_frame, textvariable=self.wer_var, fg="#ff6b6b", **lbl_style)
        wer_lbl.pack(side=tk.LEFT, padx=10, fill=tk.Y)
        
        cer_lbl = tk.Label(metric_frame, textvariable=self.cer_var, fg="#51cf66", **lbl_style)
        cer_lbl.pack(side=tk.LEFT, padx=10, fill=tk.Y)
        
        # --- 자막 서버 상태 표시 ---
        subtitle_frame = ttk.Frame(self.root, padding="5")
        subtitle_frame.pack(fill=tk.X, padx=10)
        
        self.subtitle_status_label = ttk.Label(subtitle_frame, text="자막 서버: 연결 대기", foreground="gray")
        self.subtitle_status_label.pack(side=tk.LEFT, padx=5)
        
        self.reconnect_btn = ttk.Button(subtitle_frame, text="재연결", command=self._handle_reconnect_subtitle)
        self.reconnect_btn.pack(side=tk.LEFT, padx=5)

        # --- 범례 (Legend) 표시 ---
        legend_frame = ttk.LabelFrame(self.root, text="범례", padding="10")
        legend_frame.pack(fill=tk.X, padx=10, pady=5)
        
        legend_items = [
            (AlignType.PENDING, "white", "⬚ 아직 안 읽음"),
            (AlignType.HIT, "#00FF00", "● 정답 "),
            (AlignType.SUB, "#FF0000", "● 오인식 "),
            (AlignType.DEL, "#FFFF00", "● 누락 "),
            (AlignType.INS, "#FFA500", "● 추가 "),
        ]
        
        for align_type, color, desc in legend_items:
            lbl = tk.Label(
                legend_frame, 
                text=desc, 
                fg=color, 
                bg="#2b2b2b",
                font=("Malgun Gothic", 7, "bold"),
                padx=10
            )
            lbl.pack(side=tk.LEFT, padx=5)

        # --- 메인 스크립트 뷰 (하단 절반) ---
        self.script_display = scrolledtext.ScrolledText(
            self.root, 
            wrap=tk.WORD, 
            font=self.font_style, 
            bg="black", 
            fg="white",
            state=tk.DISABLED,
            cursor="arrow",
            height=10  # 높이 제한 (약 절반)
        )
        self.script_display.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        self.root.protocol("WM_DELETE_WINDOW", self._handle_closing)
        
    def _setup_tags(self):
        """텍스트 태그 설정"""
        for align_type, color in self.TAG_COLORS.items():
            self.script_display.tag_config(align_type.value, foreground=color)
    
    # --- 콜백 설정 ---
    def set_on_load_reference(self, callback: Callable[[], None]):
        self._on_load_reference = callback
        
    def set_on_reset(self, callback: Callable[[], None]):
        self._on_reset = callback
        
    def set_on_closing(self, callback: Callable[[], None]):
        self._on_closing = callback
        
    def set_on_reconnect_subtitle(self, callback: Callable[[], None]):
        self._on_reconnect_subtitle = callback
    
    # --- 이벤트 핸들러 ---
    def _handle_load(self):
        if self._on_load_reference:
            self._on_load_reference()
            
    def _handle_reset(self):
        if self._on_reset:
            self._on_reset()
            
    def _handle_reconnect_subtitle(self):
        if self._on_reconnect_subtitle:
            self._on_reconnect_subtitle()
            
    def _handle_closing(self):
        if self._on_closing:
            self._on_closing()
        self.root.destroy()
    
    # --- 파일 다이얼로그 ---
    def ask_open_file(self) -> Optional[str]:
        """파일 열기 다이얼로그"""
        return filedialog.askopenfilename(filetypes=[("Text files", "*.txt")])
    
    # --- UI 업데이트 메서드 ---
    def show_warning(self, title: str, message: str):
        messagebox.showwarning(title, message)
        
    def show_error(self, title: str, message: str):
        messagebox.showerror(title, message)
        
    def set_status(self, text: str, color: str = "gray"):
        self.status_label.config(text=text, foreground=color)
        
    def set_subtitle_status(self, text: str, color: str = "gray"):
        """자막 서버 연결 상태 표시"""
        self.subtitle_status_label.config(text=text, foreground=color)
        
    def update_metrics(self, metrics: PartialMetrics):
        """메트릭 UI 업데이트"""
        self.wer_var.set(f"Current WER: {metrics.wer * 100:.2f}%")
        self.cer_var.set(f"Global CER: {metrics.cer * 100:.2f}%")
        
    def reset_metrics(self):
        """메트릭 초기화"""
        self.wer_var.set("Current WER: 0.00%")
        self.cer_var.set("Global CER: 0.00%")
        
    def render_text(self, text: str, tag: str = "pending"):
        """단순 텍스트 렌더링 (초기 상태)"""
        self.script_display.config(state=tk.NORMAL)
        self.script_display.delete("1.0", tk.END)
        self.script_display.insert(tk.END, text, tag)
        self.script_display.config(state=tk.DISABLED)
        
    def clear_display(self):
        """화면 클리어"""
        self.script_display.config(state=tk.NORMAL)
        self.script_display.delete("1.0", tk.END)
        self.script_display.config(state=tk.DISABLED)
        
    def render_aligned_tokens(self, tokens: List[AlignedToken]):
        """정렬된 토큰 렌더링 (PENDING 제외, 매칭된 것만 표시)"""
        self.script_display.config(state=tk.NORMAL)
        self.script_display.delete("1.0", tk.END)
        
        for token in tokens:
            # PENDING(아직 안 들어온 부분)은 표시하지 않음
            if token.align_type == AlignType.PENDING:
                continue
                
            if token.align_type == AlignType.INS:
                # 삽입된 토큰은 대괄호로 표시
                display_text = f"[{token.text}] "
            else:
                display_text = f"{token.text} "
            
            self.script_display.insert(tk.END, display_text, token.align_type.value)
        
        # 스크롤을 먼저 하고 DISABLED 설정
        self.script_display.see(tk.END)
        self.script_display.config(state=tk.DISABLED)
        # DISABLED 상태에서도 동작하는 스크롤
        self.script_display.yview_moveto(1.0)
        
    def schedule(self, delay_ms: int, callback: Callable):
        """주기적 작업 스케줄링"""
        return self.root.after(delay_ms, callback)