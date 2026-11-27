"""autoblog 데스크톱 앱 (CustomTkinter).

탭: 편집(주제별 글·미디어) / 대기열(queue.csv) / 실행(main.py 실행·로그).
실행: python gui.py  (또는 gui.bat)
"""
import os
import queue
import re
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import customtkinter as ctk
import yaml
from PIL import Image

import ai_writer
import queue_store
import topics
from common import IMAGE_EXT, VIDEO_EXT
from tools import enqueue

ROOT = topics.ROOT
NEED_TOPIC = "먼저 왼쪽 목록에서 주제를 선택하거나, '＋ 새 주제'로 주제를 만드세요."
_ROOT = [None]  # 메인 창. 대화상자를 항상 메인 창 위에 띄우기 위해 parent 로 넘긴다


def yesno(title, msg, **kw):
    kw.setdefault("parent", _ROOT[0])
    return messagebox.askyesno(title, msg, **kw)


def showerror(title, msg, **kw):
    kw.setdefault("parent", _ROOT[0])
    return messagebox.showerror(title, msg, **kw)


def showinfo(title, msg, **kw):
    kw.setdefault("parent", _ROOT[0])
    return messagebox.showinfo(title, msg, **kw)


ctk.set_appearance_mode("light")
ctk.set_default_color_theme("blue")
FONT = ("맑은 고딕", 13)
CAPTION_MAX, HASHTAG_MAX = 2200, 30
STATUS_COLOR = {"pending": "#1f6aa5", "done": "#2e8b57", "draft": "#2e8b57", "dry": "#888888", "failed": "#c0392b"}


def load_accounts() -> list[str]:
    try:
        cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
        return [a["name"] for a in cfg.get("accounts", [])]
    except Exception:
        return []


# ---------------------------------------------------------------- 편집
class MediaPanel(ctk.CTkFrame):
    """media/ 의 이미지·영상 목록: 추가, 삭제, 순서 변경 (순서는 인스타 게시 순서)."""

    def __init__(self, master, on_change):
        super().__init__(master, fg_color="transparent")
        self.topic = None
        self.on_change = on_change
        self._imgs = []  # CTkImage 참조 유지
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.pack(fill="x", pady=(0, 6))
        ctk.CTkButton(bar, text="파일 추가…", width=100, font=FONT, command=self.add).pack(side="left")
        ctk.CTkLabel(bar, text="  순서 = 인스타 게시 순서 (네이버 본문은 [[image:...]] 위치로 결정)", font=FONT,
                     text_color="#666").pack(side="left")
        self.list = ctk.CTkScrollableFrame(self)
        self.list.pack(fill="both", expand=True)

    def load(self, topic):
        self.topic = topic
        self.refresh()

    def refresh(self):
        for w in self.list.winfo_children():
            w.destroy()
        self._imgs.clear()
        if not self.topic:
            return
        files = topics.media_files(self.topic)
        if not files:
            ctk.CTkLabel(self.list, text="아직 미디어가 없습니다. '파일 추가…' 로 이미지·영상을 넣으세요.",
                         font=FONT, text_color="#888").pack(pady=30)
        for i, f in enumerate(files):
            row = ctk.CTkFrame(self.list)
            row.pack(fill="x", pady=3, padx=2)
            thumb = self._thumb(f)
            lbl = ctk.CTkLabel(row, text="" if thumb else "🎬", image=thumb, width=88, height=88, font=("", 28))
            lbl.pack(side="left", padx=6, pady=4)
            kind = "영상" if f.suffix.lower() in VIDEO_EXT else "이미지"
            info = f"{i + 1}. {f.name}\n{kind} · {f.stat().st_size / 1024:.0f} KB"
            ctk.CTkLabel(row, text=info, font=FONT, justify="left", anchor="w").pack(side="left", padx=8, fill="x", expand=True)
            ctk.CTkButton(row, text="▲", width=34, command=lambda n=f.name: self.move(n, -1)).pack(side="left", padx=2)
            ctk.CTkButton(row, text="▼", width=34, command=lambda n=f.name: self.move(n, 1)).pack(side="left", padx=2)
            ctk.CTkButton(row, text="삭제", width=54, fg_color="#c0392b", hover_color="#992d22",
                          command=lambda n=f.name: self.delete(n)).pack(side="left", padx=(2, 8))

    def _thumb(self, path):
        if path.suffix.lower() not in IMAGE_EXT:
            return None
        try:
            im = Image.open(path)
            im.thumbnail((88, 88))
            ci = ctk.CTkImage(light_image=im, size=im.size)
            self._imgs.append(ci)
            return ci
        except Exception:
            return None

    def add(self):
        if not self.topic:
            showinfo("주제 선택", NEED_TOPIC)
            return
        paths = filedialog.askopenfilenames(
            title="이미지·영상 선택",
            filetypes=[("이미지/영상", "*.jpg *.jpeg *.png *.webp *.mp4 *.mov"), ("모든 파일", "*.*")])
        if not paths:
            return
        try:
            topics.add_media(self.topic, paths)
        except ValueError as e:
            showerror("추가 실패", str(e))
        self.refresh()
        self.on_change()

    def move(self, name, delta):
        topics.move_media(self.topic, name, delta)
        self.refresh()
        self.on_change()

    def delete(self, name):
        if yesno("삭제", f"{name} 파일을 삭제할까요?\n(복구할 수 없습니다)"):
            topics.delete_media(self.topic, name)
            self.refresh()
            self.on_change()


class AIPanel(ctk.CTkFrame):
    """주제·프롬프트·말투·분량·사진을 주면 Claude 가 제목/네이버 본문/인스타 캡션을 써서 입력칸에 채운다."""

    def __init__(self, master, editor):
        super().__init__(master, fg_color="transparent")
        self.ed = editor
        self.q = queue.Queue()
        self.busy = False
        self.backup = None
        self.topic = None

        ctk.CTkLabel(self, text="주제 / 프롬프트  (무엇에 대한 글인지, 꼭 넣을 내용·경험·정보를 구체적으로)", font=FONT).pack(anchor="w")
        self.prompt = ctk.CTkTextbox(self, height=100, font=FONT, wrap="word")
        self.prompt.pack(fill="x", pady=(2, 8))

        r1 = ctk.CTkFrame(self, fg_color="transparent")
        r1.pack(fill="x", pady=2)
        ctk.CTkLabel(r1, text="말투", font=FONT, width=60, anchor="w").pack(side="left")
        self.tone = ctk.CTkOptionMenu(r1, values=[t["name"] for t in ai_writer.load_tones()], width=180, font=FONT)
        self.tone.pack(side="left")
        ctk.CTkButton(r1, text="프리셋 편집", width=90, font=FONT, command=self.edit_presets).pack(side="left", padx=8)
        ctk.CTkLabel(r1, text="작성 방식", font=FONT).pack(side="left", padx=(14, 6))
        self.mode_labels = {m["label"]: k for k, m in ai_writer.MODES.items()}
        self.mode = ctk.CTkOptionMenu(r1, values=list(self.mode_labels), width=190, font=FONT)
        self.mode.set(ai_writer.MODES[ai_writer.DEFAULT_MODE]["label"])
        self.mode.pack(side="left")

        r2 = ctk.CTkFrame(self, fg_color="transparent")
        r2.pack(fill="x", pady=2)
        ctk.CTkLabel(r2, text="분량", font=FONT, width=60, anchor="w").pack(side="left")
        self.naver_len = ctk.CTkEntry(r2, width=70, font=FONT)
        self.naver_len.pack(side="left")
        ctk.CTkLabel(r2, text="자 (네이버)   ", font=FONT).pack(side="left")
        self.ig_len = ctk.CTkEntry(r2, width=70, font=FONT)
        self.ig_len.pack(side="left")
        ctk.CTkLabel(r2, text="자 (인스타 캡션)   ", font=FONT).pack(side="left")
        self.th_len = ctk.CTkEntry(r2, width=70, font=FONT)
        self.th_len.pack(side="left")
        ctk.CTkLabel(r2, text="자 (스레드, 500 이하)", font=FONT).pack(side="left")

        r3 = ctk.CTkFrame(self, fg_color="transparent")
        r3.pack(fill="x", pady=2)
        ctk.CTkLabel(r3, text="키워드", font=FONT, width=60, anchor="w").pack(side="left")
        self.keywords = ctk.CTkEntry(r3, font=FONT, placeholder_text="쉼표로 구분 (선택)")
        self.keywords.pack(side="left", fill="x", expand=True)
        self.naver_len.insert(0, "1500")  # 주제 선택 전에도 빈 칸이 되지 않게 기본값
        self.ig_len.insert(0, "300")
        self.th_len.insert(0, "300")

        r4 = ctk.CTkFrame(self, fg_color="transparent")
        r4.pack(fill="x", pady=(6, 2))
        self.v_naver, self.v_ig, self.v_img = tk.BooleanVar(value=True), tk.BooleanVar(value=True), tk.BooleanVar(value=True)
        self.v_th = tk.BooleanVar(value=False)  # 스레드는 공개 게시라서 기본은 꺼 둔다
        ctk.CTkLabel(r4, text="작성", font=FONT, width=60, anchor="w").pack(side="left")
        ctk.CTkCheckBox(r4, text="네이버", variable=self.v_naver, font=FONT, width=70).pack(side="left", padx=(0, 10))
        ctk.CTkCheckBox(r4, text="인스타", variable=self.v_ig, font=FONT, width=70).pack(side="left", padx=(0, 10))
        ctk.CTkCheckBox(r4, text="스레드", variable=self.v_th, font=FONT, width=70).pack(side="left", padx=(0, 20))
        self.img_cb = ctk.CTkCheckBox(r4, text="사진 참고", variable=self.v_img, font=FONT, width=90)
        self.img_cb.pack(side="left")
        self.img_lbl = ctk.CTkLabel(r4, text="", font=FONT, text_color="#c0392b")
        self.img_lbl.pack(side="left", padx=6)

        r5 = ctk.CTkFrame(self, fg_color="transparent")
        r5.pack(fill="x", pady=(10, 4))
        self.gen_btn = ctk.CTkButton(r5, text="✨ 생성", width=110, font=FONT, fg_color="#2e8b57", hover_color="#236b43",
                                     command=self.start)
        self.gen_btn.pack(side="left")
        self.undo_btn = ctk.CTkButton(r5, text="되돌리기", width=90, font=FONT, state="disabled", command=self.undo)
        self.undo_btn.pack(side="left", padx=8)
        self.prog = ctk.CTkProgressBar(r5, mode="indeterminate", width=140)
        self.state_lbl = ctk.CTkLabel(r5, text="", font=FONT, text_color="#555")
        self.state_lbl.pack(side="left", padx=8)

        # 결과 보기: 생성되면 여기에 바로 표시되고, 같은 내용이 '네이버'/'인스타그램' 탭 입력칸에도 채워진다
        self.res = ctk.CTkTabview(self, height=240)
        self.res.pack(fill="both", expand=True, pady=(6, 0))
        for t in ("네이버 결과", "인스타 결과", "스레드 결과", "로그"):
            self.res.add(t)
        for key, tab, target in (("prev_naver", "네이버 결과", "네이버"), ("prev_ig", "인스타 결과", "인스타그램"),
                                 ("prev_th", "스레드 결과", "스레드")):
            bar = ctk.CTkFrame(self.res.tab(tab), fg_color="transparent")
            bar.pack(fill="x", pady=(0, 4))
            ctk.CTkButton(bar, text=f"'{target}' 탭에서 수정하기", width=150, font=FONT,
                          command=lambda t=target: self.ed.tabs.set(t)).pack(side="left")
            ctk.CTkLabel(bar, text="  (이 화면은 미리보기입니다. 수정은 해당 탭에서)", font=FONT,
                         text_color="#666").pack(side="left")
            box = ctk.CTkTextbox(self.res.tab(tab), font=FONT, wrap="word")
            box.pack(fill="both", expand=True)
            box.insert("1.0", "아직 생성된 결과가 없습니다. 위에서 [✨ 생성]을 누르세요.")
            setattr(self, key, box)
        self.out = ctk.CTkTextbox(self.res.tab("로그"), font=FONT, wrap="word")
        self.out.pack(fill="both", expand=True)
        self._out("생성 결과는 '네이버/인스타/스레드 결과' 탭에 표시되고, 각 플랫폼 탭 입력칸에도 채워집니다.\n"
                  "읽고 고친 뒤 [저장] → [대기열에 등록] 하세요.\n"
                  "※ 사실(가격·상호·효능 등)은 AI가 확인할 수 없으니 반드시 직접 검토하세요.\n")

    # ---- 상태 ----
    def get_state(self) -> dict:
        return {"prompt": self.prompt.get("1.0", "end-1c"), "tone": self.tone.get(), "mode": self.mode_labels[self.mode.get()],
                "naver_len": self.naver_len.get(), "ig_len": self.ig_len.get(), "th_len": self.th_len.get(),
                "keywords": self.keywords.get()}

    def set_state(self, s: dict, topic):
        self.topic = topic
        self.prompt.delete("1.0", "end")
        self.prompt.insert("1.0", s.get("prompt", ""))
        tones = [t["name"] for t in ai_writer.load_tones()]
        self.tone.configure(values=tones)
        self.tone.set(s.get("tone") if s.get("tone") in tones else tones[0])
        self.mode.set(ai_writer.MODES.get(s.get("mode"), ai_writer.MODES[ai_writer.DEFAULT_MODE])["label"])
        for e, v, d in ((self.naver_len, s.get("naver_len"), "1500"), (self.ig_len, s.get("ig_len"), "300"),
                        (self.th_len, s.get("th_len"), "300")):
            e.delete(0, "end")
            e.insert(0, v or d)
        self.keywords.delete(0, "end")
        self.keywords.insert(0, s.get("keywords", ""))
        self.refresh_image_info(reset_check=True)

    def refresh_image_info(self, reset_check=False):
        """'사진 참고 (N장)' 표시를 현재 media/ 내용에 맞춘다. 사진을 추가/삭제할 때도 호출된다."""
        topic = self.topic
        n = sum(1 for f in topics.media_files(topic) if f.suffix.lower() in IMAGE_EXT) if topic else 0
        sent = min(n, ai_writer.load_ai_config()["max_images"])
        self.img_cb.configure(text=f"사진 참고 ({n}장)")
        extra = f" · 앞의 {sent}장만 전송" if n > sent else ""
        self.img_lbl.configure(text=f"※ 사진이 Anthropic API 로 전송됩니다{extra}" if n else "")
        if reset_check:
            self.v_img.set(n > 0)
        elif n == 0:
            self.v_img.set(False)

    def _out(self, text):
        self.out.insert("end", text)
        self.out.see("end")

    @staticmethod
    def _set_preview(box, text):
        box.delete("1.0", "end")
        box.insert("1.0", text)

    # ---- 생성 ----
    def start(self):
        if self.busy:
            return
        if not self.ed.topic:
            self.state_lbl.configure(text="⚠ 주제가 선택되지 않았습니다", text_color="#c0392b")
            showinfo("주제 선택", NEED_TOPIC)
            return
        plats = [p for p, v in (("naver", self.v_naver), ("instagram", self.v_ig), ("threads", self.v_th)) if v.get()]
        try:
            n_len, i_len = int(self.naver_len.get() or 1500), int(self.ig_len.get() or 300)
            t_len = int(self.th_len.get() or 300)
        except ValueError:
            showerror("분량", "분량은 숫자로 입력하세요.")
            return
        if t_len > ai_writer.THREADS_MAX:
            self.th_len.delete(0, "end")
            self.th_len.insert(0, str(ai_writer.THREADS_MAX))
            t_len = ai_writer.THREADS_MAX  # 스레드는 500자까지만 가능
        # 확인창 없이 바로 덮어쓴다 (모달 대화상자가 뒤에 숨으면 앱이 멈춘 것처럼 보임). [되돌리기]로 복구 가능.
        tone = next((t for t in ai_writer.load_tones() if t["name"] == self.tone.get()), ai_writer.load_tones()[0])
        args = dict(topic=self.ed.topic, prompt=self.prompt.get("1.0", "end-1c"), tone=tone, platforms=plats,
                    naver_chars=n_len, ig_chars=i_len, threads_chars=t_len, keywords=self.keywords.get(),
                    use_images=self.v_img.get(), mode=self.mode_labels[self.mode.get()])
        self.backup = (self.ed.title_var.get(), self.ed.naver.get("1.0", "end-1c"), self.ed.ig.get("1.0", "end-1c"),
                       self.ed.threads.get("1.0", "end-1c"))
        self.busy = True
        self.gen_btn.configure(state="disabled", text="생성 중…")
        self.prog.pack(side="left", padx=(10, 0), before=self.state_lbl)
        self.prog.start()
        self.state_lbl.configure(text="Claude 가 작성하는 중입니다 (30초~1분 이상 걸릴 수 있음)", text_color="#555")
        self.res.set("로그")
        self._out("\n[시작] 생성 요청을 보냈습니다…\n")
        threading.Thread(target=self._worker, args=(args,), daemon=True).start()
        self.after(200, self._poll)

    def _worker(self, args):
        try:
            self.q.put(("ok", ai_writer.generate(**args), args["platforms"]))
        except ai_writer.AIError as e:
            self.q.put(("err", str(e), None))
        except Exception as e:  # 예기치 못한 오류도 화면에 표시
            self.q.put(("err", f"{type(e).__name__}: {e}", None))

    def _poll(self):
        try:
            kind, payload, plats = self.q.get_nowait()
        except queue.Empty:
            self.after(200, self._poll)
            return
        self.busy = False
        self.gen_btn.configure(state="normal", text="✨ 생성")
        self.prog.stop()
        self.prog.pack_forget()
        self.state_lbl.configure(text="")
        if kind == "err":
            self.state_lbl.configure(text="❌ 생성 실패 — '로그' 탭을 확인하세요", text_color="#c0392b")
            self._out(f"\n[실패] {payload}\n")
            if "API 키" in payload and yesno("API 키", payload + "\n\nconfig.yaml 을 열까요?"):
                os.startfile(ROOT / "config.yaml")
            else:
                showerror("생성 실패", payload)
            return
        self.apply(payload, plats)

    def apply(self, r, plats):
        ed = self.ed
        if "naver" in plats:
            if r["title"]:
                ed.title_var.set(r["title"])
            ed.naver.delete("1.0", "end")
            ed.naver.insert("1.0", r["naver_body"])
        if "instagram" in plats:
            ed.ig.delete("1.0", "end")
            ed.ig.insert("1.0", r["instagram_caption"])
        if "threads" in plats:
            ed.threads.delete("1.0", "end")
            ed.threads.insert("1.0", r["threads_post"])
        ed.update_counts()
        self.undo_btn.configure(state="normal")
        # 미리보기 (이 탭 안에서 바로 확인)
        self._set_preview(self.prev_naver, f"제목: {r['title']}\n\n{r['naver_body']}" if "naver" in plats
                          else "이번에는 네이버를 작성하지 않았습니다.")
        self._set_preview(self.prev_ig, r["instagram_caption"] if "instagram" in plats
                          else "이번에는 인스타그램을 작성하지 않았습니다.")
        self._set_preview(self.prev_th, r["threads_post"] if "threads" in plats
                          else "이번에는 스레드를 작성하지 않았습니다.")
        first = next(tab for key, tab in (("naver", "네이버 결과"), ("instagram", "인스타 결과"), ("threads", "스레드 결과"))
                     if key in plats)
        self.res.set(first)
        guess = len(r.get("unverified") or [])
        done = "✅ 생성 완료 — 아래 결과 탭에서 확인"
        if guess:
            done += f"  ⚠ 추정 문장 {guess}개 (로그 탭에서 확인)"
        self.state_lbl.configure(text=done, text_color="#2e8b57" if not guess else "#b9770e")
        u = r["usage"]
        self._out(f"\n[완료] 모델 {r['model']} · 입력 {u['input']:,} / 출력 {u['output']:,} 토큰\n")
        for w in r["warnings"]:
            self._out(f"  ⚠ {w}\n")
        if r["notes"]:
            self._out(f"  AI 메모: {r['notes']}\n")
        self.ed.app.status("AI 글이 생성되었습니다. 검토·수정 후 저장하세요")

    def undo(self):
        if not self.backup:
            return
        t, n, i, th = self.backup
        self.ed.title_var.set(t)
        for box, text in ((self.ed.naver, n), (self.ed.ig, i), (self.ed.threads, th)):
            box.delete("1.0", "end")
            box.insert("1.0", text)
        self.ed.update_counts()
        self.backup = None
        self.undo_btn.configure(state="disabled")
        self._out("\n[되돌림] 생성 이전 내용으로 복구했습니다.\n")

    # ---- 말투 프리셋 편집 ----
    def edit_presets(self):
        dlg = ctk.CTkToplevel(self)
        dlg.title("말투 프리셋")
        dlg.geometry("460x380")
        dlg.transient(self.winfo_toplevel())
        dlg.after(100, dlg.grab_set)
        tones = ai_writer.load_tones()
        NEW = "(새 프리셋)"
        sel = ctk.CTkOptionMenu(dlg, values=[t["name"] for t in tones] + [NEW], font=FONT)
        sel.pack(fill="x", padx=16, pady=(14, 6))
        ctk.CTkLabel(dlg, text="이름", font=FONT).pack(anchor="w", padx=16)
        name = ctk.CTkEntry(dlg, font=FONT)
        name.pack(fill="x", padx=16, pady=(0, 6))
        ctk.CTkLabel(dlg, text="말투 지시문 (AI 에게 그대로 전달됨)", font=FONT).pack(anchor="w", padx=16)
        ins = ctk.CTkTextbox(dlg, height=130, font=FONT, wrap="word")
        ins.pack(fill="x", padx=16, pady=(0, 8))

        def load(choice=None):
            t = next((x for x in tones if x["name"] == sel.get()), None)
            name.delete(0, "end")
            ins.delete("1.0", "end")
            if t:
                name.insert(0, t["name"])
                ins.insert("1.0", t["instruction"])

        def refresh(select):
            names = [t["name"] for t in tones]
            sel.configure(values=names + [NEW])
            sel.set(select if select in names else NEW)
            self.tone.configure(values=names or ["-"])
            if self.tone.get() not in names and names:
                self.tone.set(names[0])
            load()

        def save():
            n, i = name.get().strip(), ins.get("1.0", "end-1c").strip()
            if not n or not i:
                showerror("프리셋", "이름과 지시문을 모두 입력하세요.", parent=dlg)
                return
            old = sel.get()
            for t in tones:
                if t["name"] == old:
                    t["name"], t["instruction"] = n, i
                    break
            else:
                if any(t["name"] == n for t in tones):
                    showerror("프리셋", "같은 이름이 이미 있습니다.", parent=dlg)
                    return
                tones.append({"name": n, "instruction": i})
            ai_writer.save_tones(tones)
            refresh(n)

        def delete():
            if len(tones) <= 1 or sel.get() == NEW:
                return
            tones[:] = [t for t in tones if t["name"] != sel.get()]
            ai_writer.save_tones(tones)
            refresh(tones[0]["name"])

        sel.configure(command=load)
        bar = ctk.CTkFrame(dlg, fg_color="transparent")
        bar.pack(pady=6)
        ctk.CTkButton(bar, text="저장", width=80, font=FONT, command=save).pack(side="left", padx=6)
        ctk.CTkButton(bar, text="삭제", width=80, font=FONT, fg_color="#c0392b", hover_color="#992d22",
                      command=delete).pack(side="left", padx=6)
        ctk.CTkButton(bar, text="닫기", width=80, font=FONT, command=dlg.destroy).pack(side="left", padx=6)
        refresh(self.tone.get())


class Editor(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.topic = None
        head = ctk.CTkFrame(self, fg_color="transparent")
        head.pack(fill="x", pady=(0, 8))
        self.name_lbl = ctk.CTkLabel(head, text="← 왼쪽에서 주제를 선택하세요", font=("맑은 고딕", 18, "bold"),
                                     text_color="#c0392b")
        self.name_lbl.pack(side="left")
        ctk.CTkButton(head, text="주제 삭제", width=80, fg_color="#c0392b", hover_color="#992d22",
                      font=FONT, command=self.delete_topic).pack(side="right", padx=(6, 0))
        ctk.CTkButton(head, text="대기열에 등록", width=110, font=FONT, fg_color="#2e8b57", hover_color="#236b43",
                      command=self.enqueue_dialog).pack(side="right", padx=6)
        ctk.CTkButton(head, text="저장", width=70, font=FONT, command=self.save).pack(side="right", padx=6)

        trow = ctk.CTkFrame(self, fg_color="transparent")
        trow.pack(fill="x", pady=(0, 8))
        ctk.CTkLabel(trow, text="글 제목 (네이버)", font=FONT).pack(side="left")
        self.title_var = tk.StringVar()
        ctk.CTkEntry(trow, textvariable=self.title_var, font=FONT).pack(side="left", fill="x", expand=True, padx=8)

        self.tabs = ctk.CTkTabview(self)
        self.tabs.pack(fill="both", expand=True)
        for t in ("메모", "AI 작성", "네이버", "인스타그램", "스레드", "미디어"):
            self.tabs.add(t)

        self.memo = ctk.CTkTextbox(self.tabs.tab("메모"), font=FONT, wrap="word")
        self.memo.pack(fill="both", expand=True)
        self.ai = AIPanel(self.tabs.tab("AI 작성"), self)
        self.ai.pack(fill="both", expand=True)

        # 네이버
        nb = ctk.CTkFrame(self.tabs.tab("네이버"), fg_color="transparent")
        nb.pack(fill="x", pady=(0, 6))
        self.img_choice = ctk.CTkOptionMenu(nb, values=["(이미지 없음)"], width=220, font=FONT)
        self.img_choice.pack(side="left")
        ctk.CTkButton(nb, text="커서 위치에 이미지 삽입", font=FONT, command=self.insert_image).pack(side="left", padx=8)
        self.naver_count = ctk.CTkLabel(nb, text="", font=FONT)
        self.naver_count.pack(side="right")
        self.naver = ctk.CTkTextbox(self.tabs.tab("네이버"), font=FONT, wrap="word")
        self.naver.pack(fill="both", expand=True)
        self.naver.bind("<KeyRelease>", lambda e: self.update_counts())

        # 인스타
        ib = ctk.CTkFrame(self.tabs.tab("인스타그램"), fg_color="transparent")
        ib.pack(fill="x", pady=(0, 6))
        ctk.CTkLabel(ib, text="게시 형식", font=FONT).pack(side="left")
        self.ig_mode = ctk.CTkSegmentedButton(ib, values=["이미지 게시물", "릴스(영상)"], font=FONT)
        self.ig_mode.pack(side="left", padx=8)
        self.ig_count = ctk.CTkLabel(ib, text="", font=FONT)
        self.ig_count.pack(side="right")
        self.ig = ctk.CTkTextbox(self.tabs.tab("인스타그램"), font=FONT, wrap="word")
        self.ig.pack(fill="both", expand=True)
        self.ig.bind("<KeyRelease>", lambda e: self.update_counts())

        # 스레드
        tb = ctk.CTkFrame(self.tabs.tab("스레드"), fg_color="transparent")
        tb.pack(fill="x", pady=(0, 6))
        ctk.CTkLabel(tb, text="※ 공개 범위: 공개 · 500자 이하 · 해시태그 1개 이하 권장 · 사진/영상은 선택 (미디어 탭)",
                     font=FONT, text_color="#666").pack(side="left")
        self.th_count = ctk.CTkLabel(tb, text="", font=FONT)
        self.th_count.pack(side="right")
        self.threads = ctk.CTkTextbox(self.tabs.tab("스레드"), font=FONT, wrap="word")
        self.threads.pack(fill="both", expand=True)
        self.threads.bind("<KeyRelease>", lambda e: self.update_counts())

        self.media = MediaPanel(self.tabs.tab("미디어"), on_change=self.media_changed)
        self.media.pack(fill="both", expand=True)

    # ---- 주제 로드/저장 ----
    def load(self, topic):
        self.topic = topic
        self.name_lbl.configure(text=topic, text_color=("#1a1a1a", "#e0e0e0"))
        meta = topics.read_meta(topic)
        self.title_var.set(meta.get("title", ""))
        for box, text in ((self.memo, topics.read_memo(topic)),
                          (self.naver, topics.read_text(topic, "naver")),
                          (self.ig, topics.read_text(topic, "instagram")),
                          (self.threads, topics.read_text(topic, "threads"))):
            box.delete("1.0", "end")
            box.insert("1.0", text)
        self.ig_mode.set("릴스(영상)" if meta.get("ig_reel") else "이미지 게시물")
        self.media.load(topic)
        self.media_changed()
        self.update_counts()
        self.ai.set_state(meta.get("ai", {}), topic)
        self._snap = self._state()

    def _state(self):
        """화면에 입력된 내용 전체. 마지막 저장 이후 바뀌었는지 비교하는 데 쓴다."""
        return (self.memo.get("1.0", "end-1c"), self.naver.get("1.0", "end-1c"), self.ig.get("1.0", "end-1c"),
                self.threads.get("1.0", "end-1c"), self.title_var.get(), self.ig_mode.get(),
                tuple(sorted(self.ai.get_state().items())))

    def autosave(self) -> bool:
        """바뀐 내용이 있을 때만 저장한다. (다른 도구로 파일을 고친 경우 화면이 안 바뀌었으면 덮어쓰지 않는다)"""
        if not self.topic or not topics.topic_dir(self.topic).is_dir():
            return False
        if self._state() == getattr(self, "_snap", None):
            return False
        self.save(quiet=True)
        return True

    def save(self, quiet=False):
        if not self.topic or not topics.topic_dir(self.topic).is_dir():
            if not quiet:
                showinfo("주제 선택", NEED_TOPIC)
            return
        t = self.topic
        topics.write_memo(t, self.memo.get("1.0", "end-1c"))
        topics.write_text(t, "naver", self.naver.get("1.0", "end-1c"))
        topics.write_text(t, "instagram", self.ig.get("1.0", "end-1c"))
        topics.write_text(t, "threads", self.threads.get("1.0", "end-1c"))
        meta = topics.read_meta(t)
        meta["title"] = self.title_var.get().strip()
        meta["ig_reel"] = self.ig_mode.get() == "릴스(영상)"
        meta["ai"] = self.ai.get_state()
        topics.write_meta(t, meta)
        self._snap = self._state()
        self.app.refresh_topics()
        if not quiet:
            self.app.status("저장했습니다")

    def media_changed(self):
        self.ai.refresh_image_info()
        names = [f.name for f in topics.media_files(self.topic)] if self.topic else []
        imgs = [n for n in names if os.path.splitext(n)[1].lower() in IMAGE_EXT]
        self.img_choice.configure(values=imgs or ["(이미지 없음)"])
        self.img_choice.set(imgs[0] if imgs else "(이미지 없음)")

    def insert_image(self):
        name = self.img_choice.get()
        if name == "(이미지 없음)":
            showinfo("이미지 없음", "먼저 '미디어' 탭에서 이미지를 추가하세요.")
            return
        box = self.naver._textbox
        idx = box.index("insert")
        line_start = box.get(f"{idx} linestart", f"{idx} lineend").strip()
        prefix = "\n" if line_start else ""  # 줄 중간이면 줄바꿈해서 마커를 한 줄로 만든다
        box.insert("insert", f"{prefix}[[image:../media/{name}]]\n")
        self.update_counts()

    def update_counts(self):
        n = self.naver.get("1.0", "end-1c")
        imgs = len(re.findall(r"\[\[image:", n))
        self.naver_count.configure(text=f"{len(n)}자 · 이미지 {imgs}곳")
        c = self.ig.get("1.0", "end-1c")
        tags = len(re.findall(r"#\w+", c))
        bad = len(c) > CAPTION_MAX or tags > HASHTAG_MAX
        self.ig_count.configure(text=f"{len(c)}/{CAPTION_MAX}자 · 해시태그 {tags}/{HASHTAG_MAX}",
                                text_color="#c0392b" if bad else "#333")
        th = self.threads.get("1.0", "end-1c")
        th_tags = len(re.findall(r"#\w+", th))
        color = "#c0392b" if len(th) > ai_writer.THREADS_MAX else ("#b9770e" if th_tags > ai_writer.THREADS_HASHTAG_MAX else "#333")
        self.th_count.configure(text=f"{len(th)}/{ai_writer.THREADS_MAX}자 · 해시태그 {th_tags}/{ai_writer.THREADS_HASHTAG_MAX}",
                                text_color=color)

    def delete_topic(self):
        if not self.topic:
            showinfo("주제 선택", NEED_TOPIC)
            return
        if yesno("주제 삭제", f"'{self.topic}' 주제와 안의 글·이미지를 모두 삭제할까요?\n(복구할 수 없습니다)"):
            topics.delete_topic(self.topic)
            self.topic = None
            self.name_lbl.configure(text="← 왼쪽에서 주제를 선택하세요", text_color="#c0392b")
            self.app.refresh_topics()
            self.app.status("주제를 삭제했습니다")

    # ---- 대기열 등록 ----
    def enqueue_dialog(self):
        if not self.topic:
            showinfo("주제 선택", NEED_TOPIC)
            return
        self.save(quiet=True)
        accounts = load_accounts()
        if not accounts:
            showerror("계정 없음", "config.yaml 에 accounts 가 없습니다.\n설정 후 다시 시도하세요.")
            return
        dlg = ctk.CTkToplevel(self)
        dlg.title("대기열에 등록")
        dlg.geometry("340x350")
        dlg.transient(self.winfo_toplevel())
        dlg.after(100, dlg.grab_set)
        ctk.CTkLabel(dlg, text="계정", font=FONT).pack(anchor="w", padx=20, pady=(16, 2))
        acc = ctk.CTkOptionMenu(dlg, values=accounts, font=FONT)
        acc.pack(fill="x", padx=20)
        ctk.CTkLabel(dlg, text="플랫폼  (글이 작성된 플랫폼만 선택되어 있습니다)", font=FONT).pack(anchor="w", padx=20, pady=(12, 2))
        # 작성되지 않은 플랫폼은 기본으로 해제해 둔다 (등록 시 '작성되지 않은 글' 오류 방지)
        v_n, v_i, v_t = (tk.BooleanVar(value=topics.is_written(self.topic, p)) for p in ("naver", "instagram", "threads"))
        ctk.CTkCheckBox(dlg, text="네이버 블로그 (임시저장)", variable=v_n, font=FONT).pack(anchor="w", padx=24, pady=2)
        reel = self.ig_mode.get() == "릴스(영상)"
        ctk.CTkCheckBox(dlg, text="인스타그램 " + ("(릴스)" if reel else "(이미지 게시물)"),
                        variable=v_i, font=FONT).pack(anchor="w", padx=24, pady=2)
        ctk.CTkCheckBox(dlg, text="스레드 (공개로 바로 게시)", variable=v_t, font=FONT).pack(anchor="w", padx=24, pady=2)

        def ok():
            plats = [p for p, v in (("naver", v_n), ("instagram", v_i), ("threads", v_t)) if v.get()]
            try:
                msgs = enqueue.add_to_queue(self.topic, acc.get(), plats, self.title_var.get().strip(), reel)
            except ValueError as e:
                showerror("등록 실패", str(e), parent=dlg)
                return
            dlg.destroy()
            self.app.queue_tab.refresh()
            self.app.status(" / ".join(msgs))
            showinfo("대기열 등록", "\n".join(msgs))

        ctk.CTkButton(dlg, text="등록", font=FONT, fg_color="#2e8b57", hover_color="#236b43",
                      command=ok).pack(pady=20)


# ---------------------------------------------------------------- 대기열
class QueueTab(ctk.CTkFrame):
    COLS = [("account", "계정", 70), ("platform", "플랫폼", 80), ("title", "제목", 200),
            ("body_file", "글 파일", 280), ("media", "미디어", 80), ("status", "상태", 80)]

    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.pack(fill="x", pady=(0, 6))
        for text, cmd, kw in (("새로고침", self.refresh, {}), ("▲", lambda: self.move(-1), {"width": 40}),
                              ("▼", lambda: self.move(1), {"width": 40}),
                              ("대기(pending)로 되돌리기", self.reset_status, {}),
                              ("선택 삭제", self.delete, {"fg_color": "#c0392b", "hover_color": "#992d22"})):
            ctk.CTkButton(bar, text=text, command=cmd, font=FONT, **kw).pack(side="left", padx=(0, 6))
        ctk.CTkLabel(bar, text="위에서 아래 순서로 게시됩니다", font=FONT, text_color="#666").pack(side="right")
        wrap = ctk.CTkFrame(self)
        wrap.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(wrap, columns=[c[0] for c in self.COLS], show="headings", selectmode="extended")
        for key, label, w in self.COLS:
            self.tree.heading(key, text=label)
            self.tree.column(key, width=w, anchor="w")
        for st, color in STATUS_COLOR.items():
            self.tree.tag_configure(st, foreground=color)
        sb = ttk.Scrollbar(wrap, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.rows, self.fields = [], list(queue_store.FIELDS)
        self.refresh()

    def refresh(self):
        self.rows, self.fields = queue_store.load()
        self.tree.delete(*self.tree.get_children())
        for i, r in enumerate(self.rows):
            media = f"{len(r['media'].split('|'))}개" if r.get("media") else ""
            vals = (r.get("account", ""), r.get("platform", ""), r.get("title", ""),
                    r.get("body_file", ""), media, r.get("status", ""))
            self.tree.insert("", "end", iid=str(i), values=vals, tags=(r.get("status", ""),))

    def _selected(self) -> list[int]:
        return sorted(int(i) for i in self.tree.selection())

    def _commit(self, select=None):
        queue_store.save(self.rows, self.fields)
        self.refresh()
        if select:
            self.tree.selection_set([str(i) for i in select])

    def reset_status(self):
        sel = self._selected()
        for i in sel:
            self.rows[i]["status"] = "pending"
        if sel:
            self._commit(sel)

    def delete(self):
        sel = self._selected()
        if sel and yesno("삭제", f"선택한 {len(sel)}건을 대기열에서 삭제할까요?"):
            self.rows = [r for i, r in enumerate(self.rows) if i not in sel]
            self._commit()

    def move(self, delta):
        sel = self._selected()
        if not sel:
            return
        order = sel if delta < 0 else sel[::-1]
        out = list(sel)
        for i in order:
            j = i + delta
            if 0 <= j < len(self.rows) and j not in out:
                self.rows[i], self.rows[j] = self.rows[j], self.rows[i]
                out[out.index(i)] = j
        self._commit(out)


# ---------------------------------------------------------------- 실행
class RunTab(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.proc = None
        self.q = queue.Queue()
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.pack(fill="x", pady=(0, 8))
        self.dry = tk.BooleanVar(value=True)
        self.force = tk.BooleanVar(value=False)
        ctk.CTkCheckBox(bar, text="dry-run (게시 직전까지만)", variable=self.dry, font=FONT).pack(side="left")
        ctk.CTkCheckBox(bar, text="한도·시간대 무시(--force)", variable=self.force, font=FONT).pack(side="left", padx=14)
        self.only_map = {"네이버": "naver", "인스타그램": "instagram", "스레드": "threads"}
        self.only = ctk.CTkOptionMenu(bar, values=["전체", *self.only_map], width=110, font=FONT)
        self.only.pack(side="left")
        self.stop_btn = ctk.CTkButton(bar, text="중지", width=70, font=FONT, state="disabled",
                                      fg_color="#c0392b", hover_color="#992d22", command=self.stop)
        self.stop_btn.pack(side="right")
        self.run_btn = ctk.CTkButton(bar, text="실행", width=80, font=FONT, command=self.start)
        self.run_btn.pack(side="right", padx=8)
        self.log = ctk.CTkTextbox(self, font=("Consolas", 12), wrap="word")
        self.log.pack(fill="both", expand=True)
        self.log.insert("end", "대기열(pending)을 위에서부터 순서대로 처리합니다.\n"
                               "처음에는 dry-run 으로 확인하세요. 실제 실행은 인스타·스레드가 바로 게시됩니다 (네이버는 임시저장).\n\n")

    def _log(self, text):
        self.log.insert("end", text)
        self.log.see("end")

    def start(self):
        if self.proc:
            return
        self.app.editor.save(quiet=True)  # main.py 는 디스크의 파일을 읽으므로, 화면의 최신 글을 먼저 저장한다
        dry = self.dry.get()
        if not dry and not yesno(
                "실제 실행","dry-run 이 아닙니다.\n대기열의 글이 실제로 게시됩니다 (인스타·스레드는 바로 공개 게시).\n\n계속할까요?"):
            return
        cmd = [sys.executable, "-u", "main.py"]
        if dry:
            cmd.append("--dry-run")
        if self.force.get():
            cmd.append("--force")
        sel = self.only.get()
        if sel != "전체":
            cmd += ["--only", self.only_map[sel]]
        self._log(f"\n$ {' '.join(cmd[1:])}\n")
        env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"}
        self.proc = subprocess.Popen(cmd, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env,
                                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.run_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        threading.Thread(target=self._reader, args=(self.proc,), daemon=True).start()
        self.after(150, self._poll)

    def _reader(self, proc):
        for raw in iter(proc.stdout.readline, b""):
            self.q.put(raw.decode("utf-8", errors="replace"))
        proc.wait()
        self.q.put(None)

    def _poll(self):
        done = False
        while True:
            try:
                item = self.q.get_nowait()
            except queue.Empty:
                break
            if item is None:
                done = True
            else:
                self._log(item)
        if done:
            code = self.proc.returncode if self.proc else None
            self._log(f"\n[종료] 종료코드 {code}\n")
            self.proc = None
            self.run_btn.configure(state="normal")
            self.stop_btn.configure(state="disabled")
            self.app.queue_tab.refresh()
        else:
            self.after(150, self._poll)

    def stop(self):
        if self.proc:
            # 브라우저 자식 프로세스까지 함께 종료
            subprocess.run(["taskkill", "/PID", str(self.proc.pid), "/T", "/F"], capture_output=True,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            self._log("\n[중지 요청]\n")

    def busy(self):
        return self.proc is not None


# ---------------------------------------------------------------- 앱
class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title(f"autoblog  -  {ROOT}")  # 설치 폴더가 보이게 한다 (ZIP 푼 폴더 등 엉뚱한 폴더에서 실행했는지 구분)
        self.geometry("1180x760")
        self.minsize(980, 620)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        side = ctk.CTkFrame(self, width=240, corner_radius=0)
        side.grid(row=0, column=0, sticky="nsw")
        side.grid_propagate(False)
        ctk.CTkLabel(side, text="주제", font=("맑은 고딕", 16, "bold")).pack(anchor="w", padx=14, pady=(14, 6))
        ctk.CTkButton(side, text="＋ 새 주제", font=FONT, command=self.new_topic).pack(fill="x", padx=12)
        self.topic_list = ctk.CTkScrollableFrame(side, fg_color="transparent")
        self.topic_list.pack(fill="both", expand=True, padx=4, pady=8)
        ctk.CTkButton(side, text="🔑 로그인 (네이버·인스타·스레드)", font=FONT, fg_color="#555", hover_color="#333",
                      command=self.login_dialog).pack(fill="x", padx=12, pady=(0, 12), side="bottom")

        main = ctk.CTkFrame(self, fg_color="transparent")
        main.grid(row=0, column=1, sticky="nsew", padx=14, pady=12)
        self.tabs = ctk.CTkTabview(main)
        self.tabs.pack(fill="both", expand=True)
        for t in ("편집", "대기열", "실행"):
            self.tabs.add(t)
        self.editor = Editor(self.tabs.tab("편집"), self)
        self.editor.pack(fill="both", expand=True)
        self.queue_tab = QueueTab(self.tabs.tab("대기열"), self)
        self.queue_tab.pack(fill="both", expand=True)
        self.run_tab = RunTab(self.tabs.tab("실행"), self)
        self.run_tab.pack(fill="both", expand=True)

        self.status_lbl = ctk.CTkLabel(main, text="", font=FONT, anchor="w", text_color="#555")
        self.status_lbl.pack(fill="x", pady=(6, 0))

        self.current = None
        _ROOT[0] = self
        self.refresh_topics()
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.after(30000, self._autosave_tick)
        names = topics.list_topics()
        if names:  # 시작하자마자 첫 주제를 선택해 둔다 (아무것도 선택 안 된 상태로 버튼을 누르는 실수 방지)
            self.after(100, lambda: self.select_topic(names[0]))

    # ---- 로그인 (터미널 없이) ----
    def login_dialog(self):
        """계정·플랫폼을 고르고 브라우저를 열어 로그인한다. [로그인 완료] 를 누르면 실제로 로그인됐는지 확인한다."""
        accounts = load_accounts()
        if not accounts:
            showerror("계정 없음", "config.yaml 에 accounts 가 없습니다.\n먼저 config.yaml 에 계정(name, blog_id)을 입력하세요.")
            return
        plats = {"네이버": "naver", "인스타그램": "instagram", "스레드": "threads"}
        names = {v: k for k, v in plats.items()}
        dlg = ctk.CTkToplevel(self)
        dlg.title("로그인")
        dlg.geometry("500x470")
        dlg.transient(self)
        dlg.after(100, dlg.grab_set)
        ctk.CTkLabel(dlg, font=FONT, justify="left", wraplength=450, text=(
            "이 PC의 계정별 브라우저에 로그인합니다. 한 번만 하면 유지됩니다.\n\n"
            "1. 계정과 플랫폼을 고르고 [브라우저 열기]\n"
            "2. 열린 브라우저에서 로그인 ('로그인 상태 유지' 체크,\n"
            "    보안 확인이 나오면 끝까지 완료. 스레드는 '인스타 계정으로 계속')\n"
            "3. 로그인된 화면이 보이면 이 창의 [로그인 완료]를 누르세요")).pack(anchor="w", padx=22, pady=(18, 10))
        row = ctk.CTkFrame(dlg, fg_color="transparent")
        row.pack(fill="x", padx=22)
        acc = ctk.CTkOptionMenu(row, values=accounts, width=150, font=FONT)
        acc.pack(side="left")
        plat = ctk.CTkOptionMenu(row, values=list(plats), width=150, font=FONT)
        plat.pack(side="left", padx=10)
        status = ctk.CTkLabel(dlg, text="", font=FONT, wraplength=450, justify="left")
        status.pack(anchor="w", padx=22, pady=14)
        open_btn = ctk.CTkButton(dlg, text="1. 브라우저 열기", font=FONT, height=38)
        open_btn.pack(fill="x", padx=22, pady=4)
        done_btn = ctk.CTkButton(dlg, text="2. 로그인 완료", font=FONT, height=38, state="disabled",
                                 fg_color="#2e8b57", hover_color="#236b43")
        done_btn.pack(fill="x", padx=22, pady=4)
        summary = ctk.CTkLabel(dlg, text="", font=FONT, justify="left", wraplength=450, text_color="#555")
        summary.pack(anchor="w", padx=22, pady=10)

        st = {"proc": None, "results": {}}
        q = queue.Queue()
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"}

        def show_summary():
            summary.configure(text="\n".join(f"{'✅' if ok else '❌'} {names[p]}  ({a})" for (a, p), ok in st["results"].items()))

        def do_open():
            if st["proc"]:
                return
            a, p = acc.get(), plats[plat.get()]
            st["cur"] = (a, p)
            st["proc"] = subprocess.Popen([sys.executable, "-u", "main.py", "--login-only", a, "--platform", p], cwd=ROOT,
                                          stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                          env=env, creationflags=flags)
            threading.Thread(target=lambda pr=st["proc"]: [None for _ in pr.stdout], daemon=True).start()  # 출력 버퍼 비우기
            open_btn.configure(state="disabled")
            done_btn.configure(state="normal")
            status.configure(text=f"브라우저가 열립니다 (잠시 걸릴 수 있음). {plat.get()}에 '{a}' 계정으로 로그인한 뒤 [로그인 완료]를 누르세요.",
                             text_color="#555")

        def finish():  # 작업 스레드: 로그인 창 종료 → 실제 로그인 여부 확인
            a, p = st["cur"]
            pr = st["proc"]
            try:
                pr.stdin.write(b"\n")
                pr.stdin.flush()
                pr.stdin.close()
            except OSError:
                pass
            try:
                pr.wait(timeout=30)
            except subprocess.TimeoutExpired:
                pr.kill()
            try:
                r = subprocess.run([sys.executable, "-u", "main.py", "--check-login", a, "--platform", p], cwd=ROOT,
                                   capture_output=True, env=env, creationflags=flags, timeout=180)
                ok = r.returncode == 0 and b"LOGGED_IN" in r.stdout and b"NOT_LOGGED_IN" not in r.stdout
                info = "\n".join(l for l in r.stdout.decode("utf-8", errors="replace").splitlines() if l.startswith("[블로그]"))
            except Exception:
                ok, info = False, ""
            q.put(((a, p), ok, info))

        def do_done():
            done_btn.configure(state="disabled")
            status.configure(text="로그인을 확인하는 중입니다 (브라우저가 잠깐 열렸다 닫힙니다)…", text_color="#555")
            threading.Thread(target=finish, daemon=True).start()
            dlg.after(300, poll)

        def poll():
            try:
                key, ok, info = q.get_nowait()
            except queue.Empty:
                dlg.after(300, poll)
                return
            st["proc"] = None
            st["results"][key] = ok
            open_btn.configure(state="normal")
            a, p = key
            status.configure(text=((f"✅ {names[p]} 로그인이 확인되었습니다." + (f"\n{info}" if info else "")) if ok else
                                   f"❌ {names[p]} 로그인이 감지되지 않았습니다. [브라우저 열기]부터 다시 해 보세요."),
                             text_color=("#b9770e" if "주의" in info else "#2e8b57") if ok else "#c0392b")
            show_summary()

        def on_close():
            pr = st["proc"]
            if pr and pr.poll() is None:
                if not yesno("로그인", "로그인 창이 열려 있습니다. 닫으면 취소됩니다.\n닫을까요?", parent=dlg):
                    return
                pr.kill()
            dlg.destroy()

        open_btn.configure(command=do_open)
        done_btn.configure(command=do_done)
        dlg.protocol("WM_DELETE_WINDOW", on_close)

    def _autosave_tick(self):
        """30초마다 변경된 글을 자동 저장한다 (저장 버튼을 잊어도 글이 사라지지 않게)."""
        try:
            if self.editor.autosave():
                import datetime
                self.status(f"자동 저장됨 ({datetime.datetime.now():%H:%M:%S})")
        except Exception:
            pass  # 자동 저장 실패가 앱 동작을 막지 않게 한다 (수동 저장/종료 시 저장은 그대로 동작)
        self.after(30000, self._autosave_tick)

    def report_callback_exception(self, exc, val, tb):
        """버튼 콜백에서 난 예외. pythonw(콘솔 없음)에서는 보이지 않으므로 파일에 남기고 알린다."""
        import datetime
        import traceback
        text = "".join(traceback.format_exception(exc, val, tb))
        try:
            (ROOT / "logs").mkdir(exist_ok=True)
            with (ROOT / "logs" / "gui_error.log").open("a", encoding="utf-8") as f:
                f.write(f"\n=== {datetime.datetime.now():%Y-%m-%d %H:%M:%S} ===\n{text}")
        except OSError:
            pass
        self.status(f"오류가 발생했습니다: {val}  (logs/gui_error.log 참고)")
        try:
            showerror("오류", f"{type(val).__name__}: {val}\n\n자세한 내용: logs/gui_error.log")
        except Exception:
            pass

    def status(self, text):
        self.status_lbl.configure(text=text)

    def refresh_topics(self):
        for w in self.topic_list.winfo_children():
            w.destroy()
        names = topics.list_topics()
        if not names:
            ctk.CTkLabel(self.topic_list, text="주제가 없습니다.\n'＋ 새 주제' 를 누르세요.", font=FONT,
                         text_color="#888").pack(pady=20)
        for n in names:
            nv = "●" if topics.is_written(n, "naver") else "○"
            ig = "●" if topics.is_written(n, "instagram") else "○"
            th = "●" if topics.is_written(n, "threads") else "○"
            sel = n == self.current
            ctk.CTkButton(self.topic_list, text=f"{n}\n네이버 {nv}  인스타 {ig}  스레드 {th}", font=FONT, anchor="w",
                          fg_color="#1f6aa5" if sel else "transparent", text_color="white" if sel else "#222",
                          hover_color="#d0d9e3", command=lambda x=n: self.select_topic(x)).pack(fill="x", pady=2)

    def select_topic(self, name):
        if self.current and self.current != name:
            self.editor.save(quiet=True)
        self.current = name
        self.editor.load(name)
        self.refresh_topics()
        self.tabs.set("편집")

    def new_topic(self):
        dlg = ctk.CTkInputDialog(text="새 주제 이름 (폴더 이름이 됩니다)", title="새 주제")
        name = dlg.get_input()
        if name is None:
            return
        try:
            topics.create_topic(name.strip())
        except ValueError as e:
            showerror("새 주제", str(e))
            return
        self.select_topic(name.strip())

    def on_close(self):
        if self.run_tab.busy() and not yesno("종료", "실행 중입니다. 종료하면 작업이 중단됩니다.\n종료할까요?"):
            return
        if self.run_tab.busy():
            self.run_tab.stop()
        try:
            self.editor.save(quiet=True)
        except Exception:
            pass
        self.destroy()


if __name__ == "__main__":
    os.chdir(ROOT)
    App().mainloop()
