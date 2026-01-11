import argparse
import ctypes
import json
import sys
import threading
import time
from dataclasses import dataclass
from typing import Iterable, Optional, Sequence, Tuple


if sys.platform != "win32":
    raise SystemExit("This script only supports Windows.")

user32 = ctypes.WinDLL("user32", use_last_error=True)

WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
MK_LBUTTON = 0x0001


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


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


def send_key(hwnd: int, key: str) -> None:
    vk = _vk_code(key)
    user32.PostMessageW(hwnd, WM_KEYDOWN, vk, 0)
    time.sleep(0.03)
    user32.PostMessageW(hwnd, WM_KEYUP, vk, 0)


def _to_client(hwnd: int, x: int, y: int) -> POINT:
    point = POINT(x, y)
    user32.ScreenToClient(hwnd, ctypes.byref(point))
    return point


def _lparam_from_point(point: POINT) -> int:
    return (point.y << 16) | (point.x & 0xFFFF)


def send_click(hwnd: int, x: int, y: int) -> None:
    point = _to_client(hwnd, x, y)
    lparam = _lparam_from_point(point)
    user32.PostMessageW(hwnd, WM_LBUTTONDOWN, MK_LBUTTON, lparam)
    time.sleep(0.02)
    user32.PostMessageW(hwnd, WM_LBUTTONUP, 0, lparam)


def load_key_cycle(raw: Sequence[dict]) -> Sequence[KeyStep]:
    return [KeyStep(step["key"], float(step["delay_s"])) for step in raw]


def load_click_cycle(raw: Sequence[dict]) -> Sequence[ClickStep]:
    return [ClickStep(int(step["x"]), int(step["y"]), float(step["delay_s"])) for step in raw]


def run_key_loop(hwnd: int, steps: Sequence[KeyStep], stop_event: threading.Event) -> None:
    while not stop_event.is_set():
        for step in steps:
            if stop_event.is_set():
                break
            send_key(hwnd, step.key)
            stop_event.wait(step.delay_s)


def run_click_loop(hwnd: int, steps: Sequence[ClickStep], stop_event: threading.Event) -> None:
    while not stop_event.is_set():
        for step in steps:
            if stop_event.is_set():
                break
            send_click(hwnd, step.x, step.y)
            stop_event.wait(step.delay_s)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Send background key presses to a Roblox window.")
    parser.add_argument("--title", default="Roblox", help="Window title fragment to target.")
    parser.add_argument("--config", default="config.json", help="Path to config JSON file.")
    return parser.parse_args()


def load_config(path: str) -> Tuple[Sequence[KeyStep], Sequence[ClickStep]]:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            raw = json.load(handle)
    except FileNotFoundError as exc:
        hint = f"Config file not found: {path}. Create it or copy config.example.json to {path}."
        raise SystemExit(hint) from exc
    key_steps = load_key_cycle(raw.get("key_cycle", []))
    click_steps = load_click_cycle(raw.get("click_cycle", []))
    return key_steps, click_steps


def main() -> None:
    args = parse_args()
    key_steps, click_steps = load_config(args.config)
    if not key_steps and not click_steps:
        raise SystemExit("Config file must include key_cycle or click_cycle entries.")

    hwnd = find_window(args.title)
    if not hwnd:
        raise SystemExit(f"Could not find a window containing title fragment: {args.title}")

    stop_event = threading.Event()
    threads = []

    if key_steps:
        threads.append(threading.Thread(target=run_key_loop, args=(hwnd, key_steps, stop_event), daemon=True))
    if click_steps:
        threads.append(threading.Thread(target=run_click_loop, args=(hwnd, click_steps, stop_event), daemon=True))

    for thread in threads:
        thread.start()

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
