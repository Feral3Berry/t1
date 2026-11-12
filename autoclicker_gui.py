"""
Макро-автокликер: клики мыши, клавиши, сочетания, ввод текста, запись действий
(клавиатура, кнопки мыши, перемещения) с задержками, и маскировка окна под фото.

Запуск из Python:  python autoclicker_gui.py
Зависимости:       pip install pynput pillow
"""

import ctypes
import json
import os
import random
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from pynput import keyboard, mouse
from PIL import Image, ImageOps, ImageTk

# Чтобы координаты tkinter и pynput совпадали на экранах с масштабированием
if sys.platform == "win32":
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

WINDOW_TITLE = "Главная - проводник"
IS_WIN = sys.platform == "win32"
Key = keyboard.Key
HOTKEYS = [f"F{i}" for i in range(1, 13)]

# ---------------------------------------------------------------- действия
ACTIONS = {
    "Клик мыши": "click",
    "Двойной клик": "double_click",
    "Переместить мышь": "move",
    "Зажать кнопку мыши": "mouse_down",
    "Отпустить кнопку мыши": "mouse_up",
    "Прокрутка колеса": "scroll",
    "Нажать клавишу": "key",
    "Зажать клавишу": "key_down",
    "Отпустить клавишу": "key_up",
    "Сочетание клавиш": "combo",
    "Ввести текст": "text",
}
ACTION_BY_TYPE = {v: k for k, v in ACTIONS.items()}

DEFAULT_ARGS = {
    "click": "left", "double_click": "left", "move": "500,300",
    "mouse_down": "left", "mouse_up": "left", "scroll": "0,-3",
    "key": "enter", "key_down": "shift", "key_up": "shift",
    "combo": "ctrl+c", "text": "Привет",
}
HINTS = {
    "click": "Кнопка: left / right / middle (или левая / правая / средняя). "
             "Можно с координатами: left 500,300",
    "double_click": "Так же, как клик: left или left 500,300",
    "move": "Координаты на экране: x,y  (например 500,300)",
    "mouse_down": "left / right / middle",
    "mouse_up": "left / right / middle",
    "scroll": "dx,dy или просто dy. Отрицательное — вниз: 0,-3",
    "key": "Одна клавиша: a, 5, enter, space, tab, esc, f5, up, backspace…",
    "key_down": "Клавиша, которая будет зажата: shift, ctrl, alt, a…",
    "key_up": "Клавиша, которую нужно отпустить",
    "combo": "Клавиши через плюс: ctrl+c, ctrl+shift+esc, alt+tab, win+d",
    "text": "Любой текст, он будет набран посимвольно",
}

BTN = {}
for _names, _btn in ((("left", "l", "левая", "лкм"), mouse.Button.left),
                     (("right", "r", "правая", "пкм"), mouse.Button.right),
                     (("middle", "m", "средняя", "скм"), mouse.Button.middle)):
    for _n in _names:
        BTN[_n] = _btn
BTN_NAME = {mouse.Button.left: "left", mouse.Button.right: "right",
            mouse.Button.middle: "middle"}

KEY_ALIASES = {
    "ctrl": Key.ctrl, "control": Key.ctrl, "shift": Key.shift, "alt": Key.alt,
    "win": Key.cmd, "cmd": Key.cmd, "super": Key.cmd,
    "enter": Key.enter, "return": Key.enter, "esc": Key.esc, "escape": Key.esc,
    "space": Key.space, "tab": Key.tab, "backspace": Key.backspace,
    "del": Key.delete, "delete": Key.delete,
    "pageup": Key.page_up, "pagedown": Key.page_down,
}
KEY_NORMALIZE = {
    "ctrl_l": "ctrl", "ctrl_r": "ctrl", "shift_l": "shift", "shift_r": "shift",
    "alt_l": "alt", "alt_r": "alt", "alt_gr": "alt",
    "cmd_l": "win", "cmd_r": "win", "cmd": "win",
}


def parse_button(token):
    try:
        return BTN[token.strip().lower()]
    except KeyError:
        raise ValueError(f"Неизвестная кнопка мыши: «{token}». Нужно left, right или middle.")


def parse_ints(text, count, what):
    parts = text.replace(",", " ").split()
    try:
        nums = [int(float(p)) for p in parts]
    except ValueError:
        raise ValueError(f"{what}: ожидаются числа, например 500,300")
    if len(nums) != count:
        raise ValueError(f"{what}: нужно {count} числа(ел), например 500,300")
    return nums


def parse_click(arg):
    parts = arg.replace(",", " ").split()
    if not parts:
        return mouse.Button.left, None
    btn = parse_button(parts[0])
    if len(parts) == 1:
        return btn, None
    if len(parts) == 3:
        try:
            return btn, (int(float(parts[1])), int(float(parts[2])))
        except ValueError:
            pass
    raise ValueError("Клик: left или left 500,300")


def parse_scroll(arg):
    parts = arg.replace(",", " ").split()
    try:
        nums = [int(float(p)) for p in parts]
    except ValueError:
        raise ValueError("Прокрутка: числа, например 0,-3")
    if len(nums) == 1:
        return 0, nums[0]
    if len(nums) == 2:
        return nums[0], nums[1]
    raise ValueError("Прокрутка: dx,dy или просто dy")


def parse_key(text):
    s = text.strip()
    low = s.lower()
    if not s:
        raise ValueError("Не указана клавиша")
    if low in KEY_ALIASES:
        return KEY_ALIASES[low]
    if len(s) > 2 and s[0] == "<" and s[-1] == ">" and s[1:-1].isdigit():
        return keyboard.KeyCode.from_vk(int(s[1:-1]))
    if len(s) == 1:
        if IS_WIN and low.isascii() and low.isalnum():
            return keyboard.KeyCode.from_vk(ord(low.upper()))
        return s
    member = getattr(Key, low, None)
    if isinstance(member, Key):
        return member
    raise ValueError(f"Неизвестная клавиша: «{s}»")


def key_to_str(key):
    """Клавиша из слушателя -> строка, которую понимает parse_key."""
    if isinstance(key, Key):
        return KEY_NORMALIZE.get(key.name, key.name)
    vk = getattr(key, "vk", None)
    if IS_WIN and vk is not None and (0x30 <= vk <= 0x39 or 0x41 <= vk <= 0x5A):
        return chr(vk).lower()
    char = getattr(key, "char", None)
    if char and char.isprintable() and char != " ":
        return char
    if vk is not None:
        return f"<{vk}>"
    return "?"


def check_step(s):
    """Проверяет шаг без выполнения. Бросает ValueError при ошибке."""
    t, a = s["type"], s["arg"].strip()
    if t in ("click", "double_click"):
        parse_click(a)
    elif t == "move":
        parse_ints(a, 2, "Перемещение")
    elif t in ("mouse_down", "mouse_up"):
        parse_button(a)
    elif t == "scroll":
        parse_scroll(a)
    elif t in ("key", "key_down", "key_up"):
        parse_key(a)
    elif t == "combo":
        keys = [k for k in a.split("+")]
        if not keys or not all(k.strip() for k in keys):
            raise ValueError("Сочетание: клавиши через плюс, например ctrl+c")
        for k in keys:
            parse_key(k)
    elif t == "text":
        if not a:
            raise ValueError("Введите текст")
    else:
        raise ValueError(f"Неизвестное действие: {t}")


# ---------------------------------------------------------------- программа
class App:
    def __init__(self, root):
        self.root = root
        root.title(WINDOW_TITLE)
        root.geometry("940x660")
        root.minsize(780, 580)

        self.mouse = mouse.Controller()
        self.kb = keyboard.Controller()

        self.steps = []
        self.playing = False
        self.recording = False
        self.stop_evt = threading.Event()
        self.rec_lock = threading.Lock()
        self.rec_events = []
        self.rec_last_t = None
        self.rec_last_pos = None
        self.rec_last_move_t = 0.0
        self.rec_down = set()
        self.mouse_listener = None
        self.win_rect = (0, 0, 0, 0)

        self.disguised = False
        self.disguise_src = None
        self.cover_photo = None
        self.photo_path = ""
        self.resize_job = None

        self.hk = {"play": "f6", "rec": "f7", "disguise": "f8"}
        self.hk_held = set()

        self.build_ui()

        root.update_idletasks()
        self.update_rect()
        root.bind("<Configure>", self.on_configure)
        root.protocol("WM_DELETE_WINDOW", self.close)

        self.listener = keyboard.Listener(on_press=self.on_press, on_release=self.on_release)
        self.listener.daemon = True
        self.listener.start()

    # ------------------------------------------------------------ интерфейс
    def build_ui(self):
        self.main = ttk.Frame(self.root, padding=8)
        self.main.pack(fill="both", expand=True)
        self.cover = tk.Label(self.root, bd=0, bg="white")

        # --- настройки запуска
        run = ttk.LabelFrame(self.main, text="Запуск", padding=6)
        run.pack(fill="x")
        self.count_var = tk.StringVar(value="1")
        self.pause_var = tk.StringVar(value="0")
        self.speed_var = tk.StringVar(value="100")
        self.hold_var = tk.StringVar(value="50")
        self.jitter_var = tk.StringVar(value="0")
        fields = (("Повторов (0 = ∞):", self.count_var),
                  ("Пауза между повторами, мс:", self.pause_var),
                  ("Скорость, %:", self.speed_var),
                  ("Удержание клика, мс:", self.hold_var),
                  ("Разброс задержек, мс:", self.jitter_var))
        for i, (label, var) in enumerate(fields):
            ttk.Label(run, text=label).grid(row=0, column=i * 2, sticky="e", padx=(8, 2))
            ttk.Entry(run, textvariable=var, width=6).grid(row=0, column=i * 2 + 1)

        # --- горячие клавиши и маскировка
        hot = ttk.LabelFrame(self.main, text="Горячие клавиши и маскировка", padding=6)
        hot.pack(fill="x", pady=(6, 0))
        self.play_key = tk.StringVar(value="F6")
        self.rec_key = tk.StringVar(value="F7")
        self.disg_key = tk.StringVar(value="F8")
        for i, (label, var, name) in enumerate((
                ("Запуск/стоп:", self.play_key, "play"),
                ("Запись:", self.rec_key, "rec"),
                ("Маскировка:", self.disg_key, "disguise"))):
            ttk.Label(hot, text=label).grid(row=0, column=i * 2, sticky="e", padx=(8, 2))
            ttk.Combobox(hot, textvariable=var, values=HOTKEYS, width=5,
                         state="readonly").grid(row=0, column=i * 2 + 1)
            var.trace_add("write", lambda *_, n=name, v=var: self.hk.__setitem__(n, v.get().lower()))
        ttk.Button(hot, text="Выбрать фото…", command=self.choose_photo).grid(row=0, column=6, padx=(16, 4))
        self.photo_var = tk.StringVar(value="фото не выбрано")
        ttk.Label(hot, textvariable=self.photo_var, foreground="gray").grid(row=0, column=7, sticky="w")

        # --- список действий
        box = ttk.Frame(self.main)
        box.pack(fill="both", expand=True, pady=6)
        self.tree = ttk.Treeview(box, columns=("n", "act", "arg", "delay"),
                                 show="headings", height=12, selectmode="browse")
        for col, title, width, anchor in (("n", "№", 50, "center"), ("act", "Действие", 190, "w"),
                                          ("arg", "Параметр", 380, "w"), ("delay", "Задержка после, мс", 130, "center")):
            self.tree.heading(col, text=title)
            self.tree.column(col, width=width, anchor=anchor)
        sb = ttk.Scrollbar(box, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", self.on_select)

        # --- форма шага
        form = ttk.LabelFrame(self.main, text="Шаг", padding=6)
        form.pack(fill="x")
        self.action_var = tk.StringVar(value="Клик мыши")
        self.arg_var = tk.StringVar(value=DEFAULT_ARGS["click"])
        self.fdelay_var = tk.StringVar(value="100")
        cb = ttk.Combobox(form, textvariable=self.action_var, values=list(ACTIONS), width=22, state="readonly")
        cb.grid(row=0, column=0, padx=4)
        cb.bind("<<ComboboxSelected>>", self.on_action_change)
        ttk.Entry(form, textvariable=self.arg_var, width=34).grid(row=0, column=1, padx=4)
        ttk.Label(form, text="Задержка после, мс:").grid(row=0, column=2, padx=(10, 2))
        ttk.Entry(form, textvariable=self.fdelay_var, width=7).grid(row=0, column=3)
        self.hint_var = tk.StringVar(value=HINTS["click"])
        ttk.Label(form, textvariable=self.hint_var, foreground="gray", wraplength=860).grid(
            row=1, column=0, columnspan=6, sticky="w", padx=4, pady=(4, 0))
        btns = ttk.Frame(form)
        btns.grid(row=2, column=0, columnspan=6, sticky="w", pady=(6, 0))
        for text, cmd in (("Добавить", self.add_step), ("Заменить выбранный", self.replace_step),
                          ("Удалить", self.delete_step), ("Вверх", lambda: self.move_step(-1)),
                          ("Вниз", lambda: self.move_step(1)), ("Очистить всё", self.clear_steps)):
            ttk.Button(btns, text=text, command=cmd).pack(side="left", padx=3)

        # --- нижняя панель
        bottom = ttk.Frame(self.main)
        bottom.pack(fill="x", pady=(8, 0))
        self.play_btn = ttk.Button(bottom, text="▶ Запустить", command=self.on_play_button)
        self.play_btn.pack(side="left", padx=3)
        self.rec_btn = ttk.Button(bottom, text="⏺ Записать", command=self.toggle_record)
        self.rec_btn.pack(side="left", padx=3)
        ttk.Button(bottom, text="Сохранить…", command=self.save_preset).pack(side="left", padx=(20, 3))
        ttk.Button(bottom, text="Загрузить…", command=self.load_preset).pack(side="left", padx=3)
        self.status_var = tk.StringVar(value="Готово")
        ttk.Label(bottom, textvariable=self.status_var, font=("TkDefaultFont", 10, "bold")).pack(side="right", padx=6)

    def notify(self, text, error=False):
        self.status_var.set(text)
        if error and not self.disguised:
            messagebox.showerror("Ошибка", text)

    # ------------------------------------------------------- список шагов
    def refresh_tree(self, select=None):
        self.tree.delete(*self.tree.get_children())
        for i, s in enumerate(self.steps):
            self.tree.insert("", "end", iid=str(i),
                             values=(i + 1, ACTION_BY_TYPE.get(s["type"], s["type"]), s["arg"], s["delay"]))
        if select is not None and 0 <= select < len(self.steps):
            self.tree.selection_set(str(select))
            self.tree.see(str(select))

    def selected_index(self):
        sel = self.tree.selection()
        return int(sel[0]) if sel else None

    def on_select(self, _event=None):
        i = self.selected_index()
        if i is None:
            return
        s = self.steps[i]
        self.action_var.set(ACTION_BY_TYPE.get(s["type"], "Клик мыши"))
        self.arg_var.set(s["arg"])
        self.fdelay_var.set(str(s["delay"]))
        self.hint_var.set(HINTS.get(s["type"], ""))

    def on_action_change(self, _event=None):
        t = ACTIONS[self.action_var.get()]
        self.arg_var.set(DEFAULT_ARGS[t])
        self.hint_var.set(HINTS[t])

    def form_step(self):
        t = ACTIONS[self.action_var.get()]
        try:
            delay = int(float(self.fdelay_var.get().replace(",", ".")))
            if delay < 0:
                raise ValueError
        except ValueError:
            self.notify("Задержка должна быть числом ≥ 0", error=True)
            return None
        s = {"type": t, "arg": self.arg_var.get().strip(), "delay": delay}
        try:
            check_step(s)
        except ValueError as e:
            self.notify(str(e), error=True)
            return None
        return s

    def add_step(self):
        s = self.form_step()
        if s is None:
            return
        i = self.selected_index()
        pos = i + 1 if i is not None else len(self.steps)
        self.steps.insert(pos, s)
        self.refresh_tree(pos)

    def replace_step(self):
        i = self.selected_index()
        if i is None:
            self.notify("Сначала выберите шаг в списке", error=True)
            return
        s = self.form_step()
        if s is None:
            return
        self.steps[i] = s
        self.refresh_tree(i)

    def delete_step(self):
        i = self.selected_index()
        if i is None:
            return
        del self.steps[i]
        self.refresh_tree(min(i, len(self.steps) - 1))

    def move_step(self, d):
        i = self.selected_index()
        if i is None or not 0 <= i + d < len(self.steps):
            return
        self.steps[i], self.steps[i + d] = self.steps[i + d], self.steps[i]
        self.refresh_tree(i + d)

    def clear_steps(self):
        if self.steps and messagebox.askyesno("Очистить", "Удалить все шаги из списка?"):
            self.steps = []
            self.refresh_tree()

    # ---------------------------------------------------------- выполнение
    def num(self, var):
        return float(var.get().replace(",", "."))

    def read_settings(self):
        try:
            cfg = {"count": int(self.num(self.count_var)), "pause": self.num(self.pause_var),
                   "speed": self.num(self.speed_var), "hold": self.num(self.hold_var),
                   "jitter": self.num(self.jitter_var)}
        except ValueError:
            raise ValueError("Настройки запуска должны быть числами")
        if cfg["count"] < 0 or cfg["pause"] < 0 or cfg["speed"] <= 0 or cfg["hold"] < 0 or cfg["jitter"] < 0:
            raise ValueError("Скорость должна быть > 0, остальные значения ≥ 0")
        return cfg

    def on_play_button(self):
        if self.playing:
            self.stop_evt.set()
        elif not self.recording:
            self.status_var.set("Старт через 2 с — наведите курсор…")
            self.root.after(2000, self.start_play)

    def toggle_play(self):
        if self.playing:
            self.stop_evt.set()
        else:
            self.start_play()

    def start_play(self):
        if self.playing or self.recording:
            return
        if not self.steps:
            self.notify("Список действий пуст", error=True)
            return
        try:
            cfg = self.read_settings()
        except ValueError as e:
            self.notify(str(e), error=True)
            return
        self.playing = True
        self.stop_evt = threading.Event()
        self.play_btn.config(text="■ Остановить")
        self.status_var.set("Выполняется…")
        threading.Thread(target=self.play_loop, args=(list(self.steps), cfg, self.stop_evt),
                         daemon=True).start()

    def play_loop(self, steps, cfg, stop):
        hold = cfg["hold"] / 1000
        cycle = 0
        try:
            while not stop.is_set():
                for s in steps:
                    if stop.is_set():
                        break
                    self.exec_step(s, hold)
                    d = s["delay"] * 100 / cfg["speed"] + random.uniform(0, cfg["jitter"])
                    if stop.wait(max(d, 1) / 1000):
                        break
                cycle += 1
                if cfg["count"] and cycle >= cfg["count"]:
                    break
                if cfg["pause"] and stop.wait(cfg["pause"] / 1000):
                    break
                if stop.wait(0.001):
                    break
        except Exception as e:  # noqa: BLE001
            msg = f"Ошибка выполнения: {e}"
            self.root.after(0, lambda: self.notify(msg, error=True))
        finally:
            self.root.after(0, self.on_play_finished)

    def on_play_finished(self):
        self.playing = False
        self.play_btn.config(text="▶ Запустить")
        if self.status_var.get() == "Выполняется…":
            self.status_var.set("Остановлено")

    def exec_step(self, s, hold):
        t, a = s["type"], s["arg"].strip()
        m, k = self.mouse, self.kb
        if t in ("click", "double_click"):
            btn, xy = parse_click(a)
            if xy:
                m.position = xy
                time.sleep(0.01)
            for i in range(2 if t == "double_click" else 1):
                m.press(btn)
                time.sleep(hold)
                m.release(btn)
                if i == 0 and t == "double_click":
                    time.sleep(0.05)
        elif t == "move":
            x, y = parse_ints(a, 2, "Перемещение")
            m.position = (x, y)
        elif t == "mouse_down":
            m.press(parse_button(a))
        elif t == "mouse_up":
            m.release(parse_button(a))
        elif t == "scroll":
            dx, dy = parse_scroll(a)
            m.scroll(dx, dy)
        elif t == "key":
            key = parse_key(a)
            k.press(key)
            time.sleep(hold)
            k.release(key)
        elif t == "key_down":
            k.press(parse_key(a))
        elif t == "key_up":
            k.release(parse_key(a))
        elif t == "combo":
            keys = [parse_key(p) for p in a.split("+")]
            for key in keys:
                k.press(key)
                time.sleep(0.02)
            time.sleep(hold)
            for key in reversed(keys):
                k.release(key)
                time.sleep(0.02)
        elif t == "text":
            k.type(a)

    # --------------------------------------------------------------- запись
    def toggle_record(self):
        if self.recording:
            self.stop_record()
        elif not self.playing:
            self.start_record()

    def start_record(self):
        with self.rec_lock:
            self.rec_events = []
            self.rec_last_t = None
            self.rec_last_pos = None
            self.rec_last_move_t = 0.0
            self.rec_down = set()
        self.recording = True
        self.rec_btn.config(text="■ Остановить запись")
        pos = self.mouse.position
        if not self.inside_own(*pos):
            self.rec_move(*pos)
        self.mouse_listener = mouse.Listener(on_move=self.on_mouse_move, on_click=self.on_mouse_click,
                                             on_scroll=self.on_mouse_scroll)
        self.mouse_listener.daemon = True
        self.mouse_listener.start()
        self.tick_rec()

    def tick_rec(self):
        if self.recording:
            self.status_var.set(f"Запись… событий: {len(self.rec_events)} "
                                f"(стоп: {self.rec_key.get()})")
            self.root.after(300, self.tick_rec)

    def stop_record(self):
        self.recording = False
        if self.mouse_listener:
            self.mouse_listener.stop()
            self.mouse_listener = None
        with self.rec_lock:
            events, self.rec_events = self.rec_events, []
        self.steps.extend(events)
        self.refresh_tree(len(self.steps) - 1 if events else None)
        self.rec_btn.config(text="⏺ Записать")
        self.status_var.set(f"Записано действий: {len(events)} (добавлены в конец списка)")

    def rec_add(self, typ, arg):
        with self.rec_lock:
            now = time.perf_counter()
            if self.rec_events and self.rec_last_t is not None:
                self.rec_events[-1]["delay"] = int((now - self.rec_last_t) * 1000)
            self.rec_last_t = now
            self.rec_events.append({"type": typ, "arg": arg, "delay": 0})

    def rec_move(self, x, y):
        self.rec_last_pos = (x, y)
        self.rec_last_move_t = time.perf_counter()
        self.rec_add("move", f"{x},{y}")

    def inside_own(self, x, y):
        rx, ry, w, h = self.win_rect
        return rx <= x < rx + w and ry - 40 <= y < ry + h

    def on_mouse_move(self, x, y):
        if not self.recording or self.inside_own(x, y):
            return
        if (x, y) == self.rec_last_pos or time.perf_counter() - self.rec_last_move_t < 0.02:
            return
        self.rec_move(x, y)

    def on_mouse_click(self, x, y, button, pressed):
        if not self.recording or self.inside_own(x, y):
            return
        if (x, y) != self.rec_last_pos:
            self.rec_move(x, y)
        self.rec_add("mouse_down" if pressed else "mouse_up", BTN_NAME.get(button, "left"))

    def on_mouse_scroll(self, x, y, dx, dy):
        if not self.recording or self.inside_own(x, y):
            return
        if (x, y) != self.rec_last_pos:
            self.rec_move(x, y)
        self.rec_add("scroll", f"{dx},{dy}")

    # ----------------------------------------------------------- клавиатура
    def on_press(self, key):
        name = key.name if isinstance(key, Key) else None
        if name:
            for action, hk in self.hk.items():
                if name == hk:
                    if name not in self.hk_held:
                        self.hk_held.add(name)
                        fn = {"play": self.toggle_play, "rec": self.toggle_record,
                              "disguise": self.toggle_disguise}[action]
                        self.root.after(0, fn)
                    return
        if self.recording:
            ks = key_to_str(key)
            if ks not in self.rec_down:
                self.rec_down.add(ks)
                self.rec_add("key_down", ks)

    def on_release(self, key):
        name = key.name if isinstance(key, Key) else None
        if name and name in self.hk.values():
            self.hk_held.discard(name)
            return
        if self.recording:
            ks = key_to_str(key)
            if ks in self.rec_down:
                self.rec_down.discard(ks)
                self.rec_add("key_up", ks)

    # ------------------------------------------------------------ маскировка
    def choose_photo(self):
        path = filedialog.askopenfilename(
            title="Фото для маскировки",
            filetypes=[("Изображения", "*.png *.jpg *.jpeg *.bmp *.gif *.webp"), ("Все файлы", "*.*")])
        if path:
            self.load_photo(path)

    def load_photo(self, path):
        try:
            img = Image.open(path).convert("RGB")
        except Exception as e:  # noqa: BLE001
            self.notify(f"Не удалось открыть фото: {e}", error=True)
            return
        self.disguise_src = img
        self.photo_path = path
        self.photo_var.set(os.path.basename(path))
        if self.disguised:
            self.render_cover()

    def toggle_disguise(self):
        if self.disguised:
            self.cover.pack_forget()
            self.main.pack(fill="both", expand=True)
            self.disguised = False
            return
        if self.disguise_src is None:
            self.notify("Сначала выберите фото для маскировки", error=True)
            return
        self.main.pack_forget()
        self.cover.pack(fill="both", expand=True)
        self.disguised = True
        self.root.update_idletasks()
        self.render_cover()

    def render_cover(self):
        w, h = self.root.winfo_width(), self.root.winfo_height()
        if w < 2 or h < 2 or self.disguise_src is None:
            return
        img = ImageOps.fit(self.disguise_src, (w, h), Image.LANCZOS)
        self.cover_photo = ImageTk.PhotoImage(img)
        self.cover.config(image=self.cover_photo)

    def update_rect(self):
        self.win_rect = (self.root.winfo_rootx(), self.root.winfo_rooty(),
                         self.root.winfo_width(), self.root.winfo_height())

    def on_configure(self, event):
        if event.widget is not self.root:
            return
        self.update_rect()
        if self.disguised:
            if self.resize_job:
                self.root.after_cancel(self.resize_job)
            self.resize_job = self.root.after(80, self.render_cover)

    # ------------------------------------------------------------ пресеты
    def save_preset(self):
        path = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON", "*.json")])
        if not path:
            return
        data = {
            "steps": self.steps,
            "settings": {
                "count": self.count_var.get(), "pause": self.pause_var.get(),
                "speed": self.speed_var.get(), "hold": self.hold_var.get(),
                "jitter": self.jitter_var.get(), "play_key": self.play_key.get(),
                "rec_key": self.rec_key.get(), "disguise_key": self.disg_key.get(),
                "photo": self.photo_path,
            },
        }
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=1)
            self.status_var.set("Сохранено")
        except OSError as e:
            self.notify(f"Не удалось сохранить: {e}", error=True)

    def load_preset(self):
        path = filedialog.askopenfilename(filetypes=[("JSON", "*.json"), ("Все файлы", "*.*")])
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            steps = []
            for s in data["steps"]:
                step = {"type": s["type"], "arg": str(s["arg"]), "delay": int(s["delay"])}
                check_step(step)
                steps.append(step)
        except Exception as e:  # noqa: BLE001
            self.notify(f"Не удалось загрузить файл: {e}", error=True)
            return
        self.steps = steps
        st = data.get("settings", {})
        for var, key in ((self.count_var, "count"), (self.pause_var, "pause"), (self.speed_var, "speed"),
                         (self.hold_var, "hold"), (self.jitter_var, "jitter")):
            if key in st:
                var.set(str(st[key]))
        for var, key in ((self.play_key, "play_key"), (self.rec_key, "rec_key"), (self.disg_key, "disguise_key")):
            if st.get(key) in HOTKEYS:
                var.set(st[key])
        if st.get("photo") and os.path.exists(st["photo"]):
            self.load_photo(st["photo"])
        self.refresh_tree()
        self.status_var.set(f"Загружено шагов: {len(steps)}")

    # ---------------------------------------------------------------- выход
    def close(self):
        self.stop_evt.set()
        self.recording = False
        if self.mouse_listener:
            self.mouse_listener.stop()
        self.listener.stop()
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    App(root)
    root.mainloop()
