import argparse
import ctypes
import json
import sys
import threading
import time
import tkinter as tk
from dataclasses import dataclass
from tkinter import messagebox, scrolledtext
from typing import Iterable, Optional, Sequence, Tuple


if sys.platform != "win32":
    raise SystemExit("This script only supports Windows.")

user32 = ctypes.WinDLL("user32", use_last_error=True)

WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
MK_LBUTTON = 0x0001
INPUT_KEYBOARD = 1
INPUT_MOUSE = 0
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_SCANCODE = 0x0008
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_ABSOLUTE = 0x8000
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004

SM_CXSCREEN = 0
SM_CYSCREEN = 1


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.c_ushort),
        ("wScan", ctypes.c_ushort),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.c_long),
        ("dy", ctypes.c_long),
        ("mouseData", ctypes.c_ulong),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class INPUT(ctypes.Structure):
    class _INPUT_UNION(ctypes.Union):
        _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT)]

    _fields_ = [("type", ctypes.c_ulong), ("union", _INPUT_UNION)]


@dataclass(frozen=True)
class KeyStep:
    key: str
    delay_s: float


@dataclass(frozen=True)
class ClickStep:
    x: int
    y: int
    delay_s: float


def _check_result(result, func, arguments):
    if not result:
        err = ctypes.get_last_error()
        raise ctypes.WinError(err)
    return result


user32.EnumWindows.errcheck = _check_result
user32.ScreenToClient.errcheck = _check_result
user32.SendInput.errcheck = _check_result
user32.GetCursorPos.errcheck = _check_result


def _window_titles() -> Iterable[Tuple[int, str]]:
    titles = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def enum_proc(hwnd, lparam):
        length = user32.GetWindowTextLengthW(hwnd)
        if length:
            buffer = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buffer, length + 1)
            titles.append((hwnd, buffer.value))
        return True

    user32.EnumWindows(enum_proc, 0)
    return titles


def find_window(title_fragment: str) -> Optional[int]:
    fragment = title_fragment.lower()
    for hwnd, title in _window_titles():
        if fragment in title.lower():
            return hwnd
    return None


def _vk_code(key: str) -> int:
    if len(key) == 1:
        return ord(key.upper())
    aliases = {
        "shift": 0x10,
        "ctrl": 0x11,
        "alt": 0x12,
        "space": 0x20,
    }
    lowered = key.lower()
    if lowered in aliases:
        return aliases[lowered]
    raise ValueError(f"Unsupported key name: {key}")


def _activate_window(hwnd: int) -> None:
    user32.SetForegroundWindow(hwnd)
    user32.SetFocus(hwnd)


def _send_key_postmessage(hwnd: int, key: str) -> None:
    vk = _vk_code(key)
    user32.PostMessageW(hwnd, WM_KEYDOWN, vk, 0)
    time.sleep(0.03)
    user32.PostMessageW(hwnd, WM_KEYUP, vk, 0)


def _send_key_sendinput(key: str) -> None:
    vk = _vk_code(key)
    scancode = user32.MapVirtualKeyW(vk, 0)
    extra = ctypes.c_ulong(0)
    inputs = (INPUT * 2)()
    inputs[0].type = INPUT_KEYBOARD
    inputs[0].union.ki = KEYBDINPUT(0, scancode, KEYEVENTF_SCANCODE, 0, ctypes.pointer(extra))
    inputs[1].type = INPUT_KEYBOARD
    inputs[1].union.ki = KEYBDINPUT(0, scancode, KEYEVENTF_SCANCODE | KEYEVENTF_KEYUP, 0, ctypes.pointer(extra))
    user32.SendInput(2, ctypes.byref(inputs), ctypes.sizeof(INPUT))


def _to_client(hwnd: int, x: int, y: int) -> POINT:
    point = POINT(x, y)
    user32.ScreenToClient(hwnd, ctypes.byref(point))
    return point


def _lparam_from_point(point: POINT) -> int:
    return (point.y << 16) | (point.x & 0xFFFF)


def _send_click_postmessage(hwnd: int, x: int, y: int) -> None:
    point = _to_client(hwnd, x, y)
    lparam = _lparam_from_point(point)
    user32.PostMessageW(hwnd, WM_LBUTTONDOWN, MK_LBUTTON, lparam)
    time.sleep(0.02)
    user32.PostMessageW(hwnd, WM_LBUTTONUP, 0, lparam)


def _screen_to_absolute(x: int, y: int) -> Tuple[int, int]:
    width = user32.GetSystemMetrics(SM_CXSCREEN) - 1
    height = user32.GetSystemMetrics(SM_CYSCREEN) - 1
    abs_x = int(x * 65535 / width)
    abs_y = int(y * 65535 / height)
    return abs_x, abs_y


def _send_click_sendinput(x: int, y: int) -> None:
    abs_x, abs_y = _screen_to_absolute(x, y)
    extra = ctypes.c_ulong(0)
    inputs = (INPUT * 3)()
    inputs[0].type = INPUT_MOUSE
    inputs[0].union.mi = MOUSEINPUT(abs_x, abs_y, 0, MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE, 0, ctypes.pointer(extra))
    inputs[1].type = INPUT_MOUSE
    inputs[1].union.mi = MOUSEINPUT(abs_x, abs_y, 0, MOUSEEVENTF_LEFTDOWN | MOUSEEVENTF_ABSOLUTE, 0, ctypes.pointer(extra))
    inputs[2].type = INPUT_MOUSE
    inputs[2].union.mi = MOUSEINPUT(abs_x, abs_y, 0, MOUSEEVENTF_LEFTUP | MOUSEEVENTF_ABSOLUTE, 0, ctypes.pointer(extra))
    user32.SendInput(3, ctypes.byref(inputs), ctypes.sizeof(INPUT))


def load_key_cycle(raw: Sequence[dict]) -> Sequence[KeyStep]:
    return [KeyStep(step["key"], float(step["delay_s"])) for step in raw]


def load_click_cycle(raw: Sequence[dict]) -> Sequence[ClickStep]:
    return [ClickStep(int(step["x"]), int(step["y"]), float(step["delay_s"])) for step in raw]


@dataclass(frozen=True)
class InputConfig:
    key_steps: Sequence[KeyStep]
    click_steps: Sequence[ClickStep]


@dataclass(frozen=True)
class InputOptions:
    input_mode: str
    activate: bool


class InputController:
    def __init__(self, hwnd: int, options: InputOptions) -> None:
        self.hwnd = hwnd
        self.options = options

    def send_key(self, key: str) -> None:
        if self.options.activate:
            _activate_window(self.hwnd)
        if self.options.input_mode == "postmessage":
            _send_key_postmessage(self.hwnd, key)
        else:
            _send_key_sendinput(key)

    def send_click(self, x: int, y: int) -> None:
        if self.options.activate:
            _activate_window(self.hwnd)
        if self.options.input_mode == "postmessage":
            _send_click_postmessage(self.hwnd, x, y)
        else:
            _send_click_sendinput(x, y)


def run_key_loop(controller: InputController, steps: Sequence[KeyStep], stop_event: threading.Event) -> None:
    while not stop_event.is_set():
        for step in steps:
            if stop_event.is_set():
                break
            controller.send_key(step.key)
            stop_event.wait(step.delay_s)


def run_click_loop(controller: InputController, steps: Sequence[ClickStep], stop_event: threading.Event) -> None:
    while not stop_event.is_set():
        for step in steps:
            if stop_event.is_set():
                break
            controller.send_click(step.x, step.y)
            stop_event.wait(step.delay_s)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Send background key presses to a Roblox window.")
    parser.add_argument("--title", default="Roblox", help="Window title fragment to target.")
    parser.add_argument("--config", default="config.json", help="Path to config JSON file.")
    parser.add_argument(
        "--input-mode",
        choices=("postmessage", "sendinput"),
        default="sendinput",
        help="Input method to use.",
    )
    parser.add_argument(
        "--activate",
        action="store_true",
        help="Activate the Roblox window before sending input.",
    )
    parser.add_argument(
        "--gui",
        action="store_true",
        help="Launch a small overlay to edit config and control input.",
    )
    return parser.parse_args()


def _parse_config(raw: dict) -> InputConfig:
    key_steps = load_key_cycle(raw.get("key_cycle", []))
    click_steps = load_click_cycle(raw.get("click_cycle", []))
    return InputConfig(key_steps=key_steps, click_steps=click_steps)


def load_config(path: str) -> InputConfig:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            raw = json.load(handle)
    except FileNotFoundError as exc:
        hint = f"Config file not found: {path}. Create it or copy config.example.json to {path}."
        raise SystemExit(hint) from exc
    return _parse_config(raw)


def _start_threads(controller: InputController, config: InputConfig, stop_event: threading.Event) -> Sequence[threading.Thread]:
    threads = []
    if config.key_steps:
        threads.append(threading.Thread(target=run_key_loop, args=(controller, config.key_steps, stop_event), daemon=True))
    if config.click_steps:
        threads.append(threading.Thread(target=run_click_loop, args=(controller, config.click_steps, stop_event), daemon=True))
    for thread in threads:
        thread.start()
    return threads


class ConfigOverlay:
    def __init__(self, hwnd: int, args: argparse.Namespace) -> None:
        self.hwnd = hwnd
        self.args = args
        self.stop_event = threading.Event()
        self.threads: Sequence[threading.Thread] = []
        self.controller = InputController(
            hwnd,
            InputOptions(input_mode=args.input_mode, activate=args.activate),
        )

        self.root = tk.Tk()
        self.root.title("Roblox Auto Input Overlay")
        self.root.geometry("520x420")
        self.root.attributes("-topmost", True)

        path_frame = tk.Frame(self.root)
        path_frame.pack(fill=tk.X, padx=8, pady=4)
        tk.Label(path_frame, text="Config path:").pack(side=tk.LEFT)
        self.path_entry = tk.Entry(path_frame)
        self.path_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)
        self.path_entry.insert(0, args.config)
        tk.Button(path_frame, text="Load", command=self.load_config).pack(side=tk.LEFT, padx=2)
        tk.Button(path_frame, text="Save", command=self.save_config).pack(side=tk.LEFT, padx=2)

        self.text = scrolledtext.ScrolledText(self.root, height=16)
        self.text.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)

        button_frame = tk.Frame(self.root)
        button_frame.pack(fill=tk.X, padx=8, pady=4)
        tk.Button(button_frame, text="Start", command=self.start).pack(side=tk.LEFT, padx=2)
        tk.Button(button_frame, text="Stop", command=self.stop).pack(side=tk.LEFT, padx=2)

        options_frame = tk.Frame(self.root)
        options_frame.pack(fill=tk.X, padx=8, pady=4)
        self.activate_var = tk.BooleanVar(value=args.activate)
        tk.Checkbutton(options_frame, text="Activate window before input", variable=self.activate_var).pack(
            side=tk.LEFT
        )

        mode_frame = tk.Frame(self.root)
        mode_frame.pack(fill=tk.X, padx=8, pady=4)
        tk.Label(mode_frame, text="Input mode:").pack(side=tk.LEFT)
        self.mode_var = tk.StringVar(value=args.input_mode)
        tk.OptionMenu(mode_frame, self.mode_var, "sendinput", "postmessage").pack(side=tk.LEFT, padx=4)

        self.load_config()

    def load_config(self) -> None:
        path = self.path_entry.get().strip()
        try:
            with open(path, "r", encoding="utf-8") as handle:
                raw = json.load(handle)
        except FileNotFoundError:
            messagebox.showwarning("Config not found", f"Config file not found: {path}")
            return
        self.text.delete("1.0", tk.END)
        self.text.insert(tk.END, json.dumps(raw, indent=2))

    def save_config(self) -> None:
        path = self.path_entry.get().strip()
        try:
            raw = json.loads(self.text.get("1.0", tk.END))
        except json.JSONDecodeError as exc:
            messagebox.showerror("Invalid JSON", str(exc))
            return
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(raw, handle, indent=2)
        messagebox.showinfo("Saved", f"Saved config to {path}")

    def _read_config(self) -> Optional[InputConfig]:
        try:
            raw = json.loads(self.text.get("1.0", tk.END))
        except json.JSONDecodeError as exc:
            messagebox.showerror("Invalid JSON", str(exc))
            return None
        return _parse_config(raw)

    def start(self) -> None:
        config = self._read_config()
        if not config:
            return
        if not config.key_steps and not config.click_steps:
            messagebox.showwarning("Missing steps", "Config must include key_cycle or click_cycle entries.")
            return
        self.stop()
        self.controller = InputController(
            self.hwnd,
            InputOptions(input_mode=self.mode_var.get(), activate=self.activate_var.get()),
        )
        self.stop_event.clear()
        self.threads = _start_threads(self.controller, config, self.stop_event)

    def stop(self) -> None:
        if self.threads:
            self.stop_event.set()
            for thread in self.threads:
                thread.join(timeout=1)
        self.threads = []

    def run(self) -> None:
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.mainloop()

    def _on_close(self) -> None:
        self.stop()
        self.root.destroy()


def main() -> None:
    args = parse_args()
    hwnd = find_window(args.title)
    if not hwnd:
        raise SystemExit(f"Could not find a window containing title fragment: {args.title}")

    if args.gui:
        overlay = ConfigOverlay(hwnd, args)
        overlay.run()
        return

    config = load_config(args.config)
    if not config.key_steps and not config.click_steps:
        raise SystemExit("Config file must include key_cycle or click_cycle entries.")

    controller = InputController(hwnd, InputOptions(input_mode=args.input_mode, activate=args.activate))
    stop_event = threading.Event()
    threads = _start_threads(controller, config, stop_event)

    print("Running. Press Ctrl+C to stop.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        stop_event.set()
        for thread in threads:
            thread.join(timeout=1)


if __name__ == "__main__":
    main()
