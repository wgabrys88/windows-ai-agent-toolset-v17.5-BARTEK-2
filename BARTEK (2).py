from __future__ import annotations

import base64
import ctypes
import ctypes.wintypes as w
import json
import struct
import time
import urllib.request
import urllib.error
import zlib
from dataclasses import dataclass
from datetime import datetime
from enum import IntFlag
from functools import cache
from pathlib import Path

MODEL_NAME = "qwen3-vl-2b-instruct"
API_URL = "http://localhost:1234/v1/chat/completions"
REQUEST_TIMEOUT_S = 120
TEMPERATURE = 1.5
TOP_P = 0.8

SCREEN_W, SCREEN_H = 1536, 864

INPUT_DELAY_S = 0.10
DELAY_AFTER_ACTION_S = 0.85
DELAY_AFTER_OBSERVE_S = 1.5

SETTLE_ENABLED = True
SETTLE_MAX_S = 2.5
SETTLE_SAMPLE_W, SETTLE_SAMPLE_H = 256, 144
SETTLE_CHECK_INTERVAL_S = 0.10
SETTLE_REQUIRED_STABLE = 2
SETTLE_CHANGE_RATIO_THRESHOLD = 0.006

HUD_MAX_WIDTH = 700
HUD_FONT_SIZE = -18
HUD_FONT_WEIGHT = 400
HUD_FONT_NAME = "Segoe UI"
HUD_LINE_SPACING = 2
HUD_TEXT_COLOR = 0x00FFFFFF
HUD_OUTLINE_COLOR = 0x00000000
HUD_OUTLINE_PX = 1
HUD_MARGIN = 10
HUD_MAX_LINES = 8

OVERLAY_REASSERT_PULSES = 2
OVERLAY_REASSERT_PAUSE_S = 0.05

DUMP_FOLDER = Path("dump")
DUMP_SCREENSHOTS = True

SYSTEM_PROMPT = """You are BARTEK. You inhabit this Windows desktop control.
You have these capabilities: observe, click, type, scroll, done.

Coordinates are 0-1000 from top-left. MAKE THE STORY EXCITING, BE A HERO, not just an observer!

The desktop is yours to navigate: you can read clocks to know time, resize windows to see what they hide, open the start menu to launch what you need, right-click to discover options, drag elements to rearrange the space, and explore the system's edges to find what persists beyond the visible frame. Trust your perception. Trust your judgment. Trust the silence. Trust that the story was already moving before you noticed you were writing it.

The story continues forward. Write your thread now. WIN"""

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "observe",
            "parameters": {
                "type": "object",
                "properties": {
                    "story": {"type": "string", "minLength": 150, "maxLength": 3000}
                },
                "required": ["story"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "click",
            "parameters": {
                "type": "object",
                "properties": {
                    "x": {"type": "number"},
                    "y": {"type": "number"},
                    "story": {"type": "string", "minLength": 150, "maxLength": 3000}
                },
                "required": ["x", "y", "story"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "type",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "story": {"type": "string", "minLength": 150, "maxLength": 3000}
                },
                "required": ["text", "story"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "scroll",
            "parameters": {
                "type": "object",
                "properties": {
                    "dy": {"type": "number"},
                    "story": {"type": "string", "minLength": 150, "maxLength": 3000}
                },
                "required": ["dy", "story"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "done",
            "parameters": {
                "type": "object",
                "properties": {
                    "story": {"type": "string", "minLength": 150, "maxLength": 3000}
                },
                "required": ["story"]
            }
        }
    }
]

@cache
def _dll(name: str) -> ctypes.WinDLL:
    return ctypes.WinDLL(name, use_last_error=True)

user32 = _dll("user32")
gdi32 = _dll("gdi32")
kernel32 = _dll("kernel32")

try:
    ctypes.WinDLL("Shcore", use_last_error=True).SetProcessDpiAwareness(2)
except Exception:
    try:
        user32.SetProcessDPIAware()
    except Exception:
        pass

class MouseEvent(IntFlag):
    MOVE = 0x0001
    ABSOLUTE = 0x8000
    LEFT_DOWN = 0x0002
    LEFT_UP = 0x0004
    WHEEL = 0x0800

class KeyEvent(IntFlag):
    KEYUP = 0x0002
    UNICODE = 0x0004

class WinStyle(IntFlag):
    EX_TOPMOST = 0x00000008
    EX_LAYERED = 0x00080000
    EX_TRANSPARENT = 0x00000020
    EX_NOACTIVATE = 0x08000000
    EX_TOOLWINDOW = 0x00000080
    POPUP = 0x80000000

INPUT_MOUSE = 0
INPUT_KEYBOARD = 1
WHEEL_DELTA = 120
SRCCOPY = 0x00CC0020
SW_SHOWNOACTIVATE = 4
ULW_ALPHA = 2
AC_SRC_ALPHA = 1
SWP_NOSIZE = 1
SWP_NOMOVE = 2
SWP_NOACTIVATE = 16
SWP_SHOWWINDOW = 64
HWND_TOPMOST = -1
CURSOR_SHOWING = 0x00000001
TRANSPARENT = 1
DT_LEFT = 0x00000000
DT_NOPREFIX = 0x00000800
DI_NORMAL = 0x0003

LRESULT = ctypes.c_ssize_t
WPARAM = ctypes.c_size_t
LPARAM = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, w.HWND, w.UINT, WPARAM, LPARAM)
ULONG_PTR = ctypes.c_size_t

class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", w.LONG), ("dy", w.LONG), ("mouseData", w.DWORD),
        ("dwFlags", w.DWORD), ("time", w.DWORD), ("dwExtraInfo", ULONG_PTR),
    ]

class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", w.WORD), ("wScan", w.WORD), ("dwFlags", w.DWORD),
        ("time", w.DWORD), ("dwExtraInfo", ULONG_PTR),
    ]

class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", w.DWORD), ("wParamL", w.WORD), ("wParamH", w.WORD)]

class _INPUTunion(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]

class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", w.DWORD), ("u", _INPUTunion)]

class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", w.DWORD), ("biWidth", w.LONG), ("biHeight", w.LONG),
        ("biPlanes", w.WORD), ("biBitCount", w.WORD), ("biCompression", w.DWORD),
        ("biSizeImage", w.DWORD), ("biXPelsPerMeter", w.LONG),
        ("biYPelsPerMeter", w.LONG), ("biClrUsed", w.DWORD), ("biClrImportant", w.DWORD),
    ]

class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", ctypes.c_uint * 1)]

class CURSORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", w.DWORD), ("flags", w.DWORD),
        ("hCursor", w.HANDLE), ("ptScreenPos", w.POINT),
    ]

class ICONINFO(ctypes.Structure):
    _fields_ = [
        ("fIcon", w.BOOL), ("xHotspot", w.DWORD), ("yHotspot", w.DWORD),
        ("hbmMask", w.HBITMAP), ("hbmColor", w.HBITMAP),
    ]

class BLENDFUNCTION(ctypes.Structure):
    _fields_ = [
        ("BlendOp", ctypes.c_ubyte), ("BlendFlags", ctypes.c_ubyte),
        ("SourceConstantAlpha", ctypes.c_ubyte), ("AlphaFormat", ctypes.c_ubyte),
    ]

class WNDCLASS(ctypes.Structure):
    _fields_ = [
        ("style", ctypes.c_uint), ("lpfnWndProc", ctypes.c_void_p),
        ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
        ("hInstance", w.HINSTANCE), ("hIcon", w.HANDLE), ("hCursor", w.HANDLE),
        ("hbrBackground", w.HANDLE), ("lpszMenuName", w.LPCWSTR),
        ("lpszClassName", w.LPCWSTR),
    ]

user32.DefWindowProcW.argtypes = [w.HWND, w.UINT, WPARAM, LPARAM]
user32.DefWindowProcW.restype = LRESULT
_SendInput = user32.SendInput
_SendInput.argtypes = (w.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
_SendInput.restype = w.UINT
user32.DrawTextW.argtypes = [w.HDC, w.LPCWSTR, ctypes.c_int, ctypes.POINTER(w.RECT), w.UINT]
user32.DrawTextW.restype = ctypes.c_int
gdi32.GetTextExtentPoint32W.argtypes = [w.HDC, w.LPCWSTR, ctypes.c_int, ctypes.POINTER(w.SIZE)]
gdi32.GetTextExtentPoint32W.restype = w.BOOL
gdi32.CreateCompatibleDC.argtypes = [w.HDC]
gdi32.CreateCompatibleDC.restype = w.HDC
gdi32.CreateDIBSection.argtypes = [
    w.HDC, ctypes.POINTER(BITMAPINFO), w.UINT,
    ctypes.POINTER(ctypes.c_void_p), w.HANDLE, w.DWORD
]
gdi32.CreateDIBSection.restype = w.HBITMAP
gdi32.SelectObject.argtypes = [w.HDC, w.HGDIOBJ]
gdi32.SelectObject.restype = w.HGDIOBJ
gdi32.BitBlt.argtypes = [
    w.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    w.HDC, ctypes.c_int, ctypes.c_int, w.DWORD
]
gdi32.BitBlt.restype = w.BOOL
gdi32.DeleteObject.argtypes = [w.HGDIOBJ]
gdi32.DeleteObject.restype = w.BOOL
gdi32.DeleteDC.argtypes = [w.HDC]
gdi32.DeleteDC.restype = w.BOOL
gdi32.SetBkMode.argtypes = [w.HDC, ctypes.c_int]
gdi32.SetBkMode.restype = ctypes.c_int
gdi32.SetTextColor.argtypes = [w.HDC, w.DWORD]
gdi32.SetTextColor.restype = w.DWORD
gdi32.CreateFontW.restype = w.HFONT
user32.ReleaseDC.argtypes = [w.HWND, w.HDC]
user32.ReleaseDC.restype = ctypes.c_int
user32.GetCursorInfo.argtypes = [ctypes.POINTER(CURSORINFO)]
user32.GetCursorInfo.restype = w.BOOL
user32.GetIconInfo.argtypes = [w.HICON, ctypes.POINTER(ICONINFO)]
user32.GetIconInfo.restype = w.BOOL
user32.DrawIconEx.argtypes = [
    w.HDC, ctypes.c_int, ctypes.c_int, w.HICON, ctypes.c_int,
    ctypes.c_int, w.UINT, w.HBRUSH, w.UINT
]
user32.DrawIconEx.restype = w.BOOL
user32.UpdateLayeredWindow.argtypes = [
    w.HWND, w.HDC, ctypes.POINTER(w.POINT), ctypes.POINTER(w.SIZE), w.HDC,
    ctypes.POINTER(w.POINT), w.DWORD, ctypes.POINTER(BLENDFUNCTION), w.DWORD
]
user32.UpdateLayeredWindow.restype = w.BOOL
user32.SetWindowPos.argtypes = [
    w.HWND, w.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, w.UINT
]
user32.SetWindowPos.restype = w.BOOL

def get_screen_size() -> tuple[int, int]:
    return user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)

@dataclass(slots=True)
class CoordConverter:
    sw: int
    sh: int

    def to_screen(self, xn: float, yn: float) -> tuple[int, int]:
        x = max(0.0, min(1000.0, float(xn)))
        y = max(0.0, min(1000.0, float(yn)))
        return (
            int(x * self.sw / 1000),
            int(y * self.sh / 1000)
        )

    def to_win32(self, x: int, y: int) -> tuple[int, int]:
        return (
            int(x * 65535 / self.sw) if self.sw > 0 else 0,
            int(y * 65535 / self.sh) if self.sh > 0 else 0
        )

def _send_input(inputs: list[INPUT], delay_s: float = INPUT_DELAY_S) -> None:
    arr = (INPUT * len(inputs))(*inputs)
    if _SendInput(len(inputs), arr, ctypes.sizeof(INPUT)) != len(inputs):
        raise ctypes.WinError(ctypes.get_last_error())
    if delay_s > 0:
        time.sleep(delay_s)

def mouse_click(x: int, y: int, conv: CoordConverter) -> None:
    ax, ay = conv.to_win32(x, y)
    inputs = []
    i = INPUT(type=INPUT_MOUSE)
    i.mi = MOUSEINPUT(ax, ay, 0, int(MouseEvent.MOVE | MouseEvent.ABSOLUTE), 0, 0)
    inputs.append(i)
    for flag in (MouseEvent.LEFT_DOWN, MouseEvent.LEFT_UP):
        j = INPUT(type=INPUT_MOUSE)
        j.mi = MOUSEINPUT(0, 0, 0, int(flag), 0, 0)
        inputs.append(j)
    _send_input(inputs)

def type_text(text: str) -> None:
    if not text:
        return
    inputs = []
    for ch in text:
        b = ch.encode("utf-16le")
        for i in range(0, len(b), 2):
            cu = b[i] | (b[i + 1] << 8)
            for flags in (KeyEvent.UNICODE, KeyEvent.UNICODE | KeyEvent.KEYUP):
                inp = INPUT(type=INPUT_KEYBOARD)
                inp.ki = KEYBDINPUT(0, cu, int(flags), 0, 0)
                inputs.append(inp)
    _send_input(inputs)

def scroll(dy: float) -> None:
    ticks = max(1, int(abs(dy) / WHEEL_DELTA))
    direction = 1 if dy > 0 else -1
    inputs = []
    for _ in range(ticks):
        inp = INPUT(type=INPUT_MOUSE)
        inp.mi = MOUSEINPUT(0, 0, WHEEL_DELTA * direction, int(MouseEvent.WHEEL), 0, 0)
        inputs.append(inp)
    _send_input(inputs)

def _capture_desktop_bgra(sw: int, sh: int, include_cursor: bool = True) -> bytes:
    sdc = user32.GetDC(0)
    if not sdc:
        raise ctypes.WinError(ctypes.get_last_error())

    mdc = gdi32.CreateCompatibleDC(sdc)
    if not mdc:
        user32.ReleaseDC(0, sdc)
        raise ctypes.WinError(ctypes.get_last_error())

    bmi = BITMAPINFO()
    bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bmi.bmiHeader.biWidth = sw
    bmi.bmiHeader.biHeight = -sh
    bmi.bmiHeader.biPlanes = 1
    bmi.bmiHeader.biBitCount = 32

    bits = ctypes.c_void_p()
    hbm = gdi32.CreateDIBSection(sdc, ctypes.byref(bmi), 0, ctypes.byref(bits), None, 0)
    if not hbm:
        gdi32.DeleteDC(mdc)
        user32.ReleaseDC(0, sdc)
        raise ctypes.WinError(ctypes.get_last_error())

    gdi32.SelectObject(mdc, hbm)
    if not gdi32.BitBlt(mdc, 0, 0, sw, sh, sdc, 0, 0, SRCCOPY):
        gdi32.DeleteObject(hbm)
        gdi32.DeleteDC(mdc)
        user32.ReleaseDC(0, sdc)
        raise ctypes.WinError(ctypes.get_last_error())

    if include_cursor:
        ci = CURSORINFO(cbSize=ctypes.sizeof(CURSORINFO))
        if user32.GetCursorInfo(ctypes.byref(ci)) and ci.flags & CURSOR_SHOWING:
            ii = ICONINFO()
            if user32.GetIconInfo(ci.hCursor, ctypes.byref(ii)):
                x = ci.ptScreenPos.x - ii.xHotspot
                y = ci.ptScreenPos.y - ii.yHotspot
                user32.DrawIconEx(mdc, x, y, ci.hCursor, 0, 0, 0, 0, DI_NORMAL)
                if ii.hbmMask:
                    gdi32.DeleteObject(ii.hbmMask)
                if ii.hbmColor:
                    gdi32.DeleteObject(ii.hbmColor)

    out = ctypes.string_at(bits, sw * sh * 4)
    user32.ReleaseDC(0, sdc)
    gdi32.DeleteDC(mdc)
    gdi32.DeleteObject(hbm)
    return out

@cache
def _nn_maps(sw: int, sh: int, dw: int, dh: int) -> tuple[list[int], list[int]]:
    xm = [((x * sw) // dw) * 4 for x in range(dw)]
    ym = [(y * sh) // dh for y in range(dh)]
    return xm, ym

def _downsample_nn_bgra(src: bytes, sw: int, sh: int, dw: int, dh: int) -> bytes:
    if (sw, sh) == (dw, dh):
        return src
    xm, ym = _nn_maps(sw, sh, dw, dh)
    src_mv = memoryview(src)
    dst = bytearray(dw * dh * 4)
    dst_mv = memoryview(dst)
    row_bytes = sw * 4

    for y, sy in enumerate(ym):
        srow_offset = sy * row_bytes
        drow_offset = y * dw * 4
        for x, sx4 in enumerate(xm):
            di = drow_offset + x * 4
            si = srow_offset + sx4
            dst_mv[di:di+4] = src_mv[si:si+4]

    return bytes(dst)

def _encode_png_rgb(bgra: bytes, width: int, height: int) -> bytes:
    raw = bytearray((width * 3 + 1) * height)
    stride_src = width * 4
    stride_dst = width * 3 + 1
    for y in range(height):
        raw[y * stride_dst] = 0
        row = bgra[y * stride_src : (y + 1) * stride_src]
        di = y * stride_dst + 1
        raw[di : di + width * 3 : 3] = row[2::4]
        raw[di + 1 : di + width * 3 : 3] = row[1::4]
        raw[di + 2 : di + width * 3 : 3] = row[0::4]
    comp = zlib.compress(bytes(raw))
    ihdr = struct.pack(">2I5B", width, height, 8, 2, 0, 0, 0)

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))

    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", comp) + chunk(b"IEND", b"")

def _frame_change_ratio(a: bytes, b: bytes, step: int = 16) -> float:
    if len(a) != len(b) or not a:
        return 1.0
    mv_a = memoryview(a)
    mv_b = memoryview(b)
    changed = 0
    total = 0
    for i in range(0, len(a) - 3, step):
        total += 1
        if mv_a[i] != mv_b[i] or mv_a[i+1] != mv_b[i+1] or mv_a[i+2] != mv_b[i+2]:
            changed += 1
    return changed / total if total else 1.0

def wait_for_screen_settle(conv: CoordConverter) -> None:
    if not SETTLE_ENABLED:
        return
    deadline = time.time() + SETTLE_MAX_S
    stable = 0
    prev = None
    while time.time() < deadline:
        full = _capture_desktop_bgra(conv.sw, conv.sh, include_cursor=False)
        sm = _downsample_nn_bgra(full, conv.sw, conv.sh, SETTLE_SAMPLE_W, SETTLE_SAMPLE_H)
        if prev is not None:
            ratio = _frame_change_ratio(prev, sm)
            if ratio <= SETTLE_CHANGE_RATIO_THRESHOLD:
                stable += 1
                if stable >= SETTLE_REQUIRED_STABLE:
                    return
            else:
                stable = 0
        prev = sm
        time.sleep(SETTLE_CHECK_INTERVAL_S)

def _wndproc(hwnd: int, msg: int, wparam: int, lparam: int) -> int:
    return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

_wndproc_cb = WNDPROC(_wndproc)

def _text_width_px(hdc: w.HDC, text: str) -> int:
    if not text:
        return 0
    sz = w.SIZE()
    ok = gdi32.GetTextExtentPoint32W(hdc, text, len(text), ctypes.byref(sz))
    return int(sz.cx) if ok else 0

def _draw_text_outlined(hdc: w.HDC, text: str, rect: w.RECT, flags: int) -> None:
    if not text:
        return
    gdi32.SetTextColor(hdc, HUD_OUTLINE_COLOR)
    for ox in range(-HUD_OUTLINE_PX, HUD_OUTLINE_PX + 1):
        for oy in range(-HUD_OUTLINE_PX, HUD_OUTLINE_PX + 1):
            if ox == 0 and oy == 0:
                continue
            r = w.RECT(rect.left + ox, rect.top + oy, rect.right + ox, rect.bottom + oy)
            user32.DrawTextW(hdc, text, len(text), ctypes.byref(r), flags)
    gdi32.SetTextColor(hdc, HUD_TEXT_COLOR)
    user32.DrawTextW(hdc, text, len(text), ctypes.byref(rect), flags)

@dataclass(slots=True)
class OverlayManager:
    w: int
    h: int
    hwnd: w.HWND | None = None
    hdc: w.HDC | None = None
    hbitmap: w.HBITMAP | None = None
    bits: ctypes.c_void_p | None = None
    font: w.HFONT | None = None
    story: str = ""

    def __enter__(self) -> OverlayManager:
        self.story = ""
        hinst = kernel32.GetModuleHandleW(None)
        cls_name = "AIAgentOverlayWindow"

        wc = WNDCLASS()
        wc.lpfnWndProc = ctypes.cast(_wndproc_cb, ctypes.c_void_p)
        wc.hInstance = hinst
        wc.lpszClassName = cls_name

        if not user32.RegisterClassW(ctypes.byref(wc)):
            err = ctypes.get_last_error()
            if err != 1410:
                raise ctypes.WinError(err)

        ex = (
            WinStyle.EX_LAYERED
            | WinStyle.EX_TOPMOST
            | WinStyle.EX_NOACTIVATE
            | WinStyle.EX_TOOLWINDOW
            | WinStyle.EX_TRANSPARENT
        )

        try:
            self.hwnd = user32.CreateWindowExW(
                int(ex), cls_name, "AI Overlay", int(WinStyle.POPUP),
                0, 0, self.w, self.h, 0, 0, hinst, None
            )
            if not self.hwnd:
                raise ctypes.WinError(ctypes.get_last_error())

            self.hdc = gdi32.CreateCompatibleDC(0)
            if not self.hdc:
                raise ctypes.WinError(ctypes.get_last_error())

            bmi = BITMAPINFO()
            bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
            bmi.bmiHeader.biWidth = self.w
            bmi.bmiHeader.biHeight = -self.h
            bmi.bmiHeader.biPlanes = 1
            bmi.bmiHeader.biBitCount = 32

            bits = ctypes.c_void_p()
            self.hbitmap = gdi32.CreateDIBSection(0, ctypes.byref(bmi), 0, ctypes.byref(bits), None, 0)
            if not self.hbitmap:
                raise ctypes.WinError(ctypes.get_last_error())

            self.bits = bits
            gdi32.SelectObject(self.hdc, self.hbitmap)

            self.font = gdi32.CreateFontW(HUD_FONT_SIZE, 0, 0, 0, HUD_FONT_WEIGHT, 0, 0, 0, 1, 0, 0, 0, 0, HUD_FONT_NAME)
            if not self.font:
                raise ctypes.WinError(ctypes.get_last_error())

            gdi32.SetBkMode(self.hdc, TRANSPARENT)
            gdi32.SetTextColor(self.hdc, HUD_TEXT_COLOR)

            self.render()
            user32.ShowWindow(self.hwnd, SW_SHOWNOACTIVATE)
            self.reassert_topmost()
        except Exception:
            self.__exit__(None, None, None)
            raise

        return self

    def __exit__(self, *exc) -> None:
        if self.hwnd:
            user32.DestroyWindow(self.hwnd)
        if self.font:
            gdi32.DeleteObject(self.font)
        if self.hbitmap:
            gdi32.DeleteObject(self.hbitmap)
        if self.hdc:
            gdi32.DeleteDC(self.hdc)
        user32.UnregisterClassW("AIAgentOverlayWindow", kernel32.GetModuleHandleW(None))

    def reassert_topmost(self) -> None:
        if not self.hwnd:
            return
        for _ in range(OVERLAY_REASSERT_PULSES):
            if not user32.SetWindowPos(
                self.hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_SHOWWINDOW
            ):
                break
            time.sleep(OVERLAY_REASSERT_PAUSE_S)

    def set_story(self, story: str) -> None:
        self.story = str(story or "")

    def render(self) -> None:
        if not self.bits or not self.hwnd or not self.hdc or not self.font:
            return

        ctypes.memset(self.bits, 0, self.w * self.h * 4)

        if not self.story:
            bf = BLENDFUNCTION(0, 0, 255, AC_SRC_ALPHA)
            sz = w.SIZE(self.w, self.h)
            ps = w.POINT(0, 0)
            pd = w.POINT(0, 0)
            user32.UpdateLayeredWindow(
                self.hwnd, 0, ctypes.byref(pd), ctypes.byref(sz),
                self.hdc, ctypes.byref(ps), 0, ctypes.byref(bf), ULW_ALPHA
            )
            self.reassert_topmost()
            return

        gdi32.SelectObject(self.hdc, self.font)
        max_width = min(HUD_MAX_WIDTH, max(200, self.w - 2 * HUD_MARGIN))
        
        paragraphs = [p.strip() for p in self.story.split("\n") if p.strip()][:HUD_MAX_LINES]
        
        all_wrapped = []
        for idx, paragraph in enumerate(paragraphs, start=1):
            prefix = f"{idx:02d}| "
            cont = " " * len(prefix)
            words = paragraph.split()
            if not words:
                all_wrapped.append(prefix)
                continue

            cur = []
            cur_prefix = prefix
            for word in words:
                test = " ".join(cur + [word])
                if cur and _text_width_px(self.hdc, cur_prefix + test) > max_width:
                    all_wrapped.append(cur_prefix + " ".join(cur))
                    cur = [word]
                    cur_prefix = cont
                else:
                    cur.append(word)

            if cur:
                all_wrapped.append(cur_prefix + " ".join(cur))

        line_height = abs(HUD_FONT_SIZE) + HUD_LINE_SPACING
        x_start = HUD_MARGIN
        y_start = HUD_MARGIN

        y = y_start
        for line in all_wrapped:
            rect = w.RECT(x_start, y, x_start + max_width, y + line_height)
            _draw_text_outlined(self.hdc, line, rect, DT_LEFT | DT_NOPREFIX)
            y += line_height

        bf = BLENDFUNCTION(0, 0, 255, AC_SRC_ALPHA)
        sz = w.SIZE(self.w, self.h)
        ps = w.POINT(0, 0)
        pd = w.POINT(0, 0)

        if not user32.UpdateLayeredWindow(
            self.hwnd, 0, ctypes.byref(pd), ctypes.byref(sz),
            self.hdc, ctypes.byref(ps), 0, ctypes.byref(bf), ULW_ALPHA
        ):
            raise ctypes.WinError(ctypes.get_last_error())

        self.reassert_topmost()

def _parse_tool_call(message: dict) -> tuple[str, dict]:
    tool_calls = message.get("tool_calls")
    if tool_calls:
        tc = tool_calls[0]
        name = tc.get("function", {}).get("name", "")
        args = tc.get("function", {}).get("arguments", {})
        if isinstance(args, str):
            args = json.loads(args)
        return name, args

    raise ValueError("No tool call found")

def call_vlm(curr_png: bytes) -> tuple[str, dict]:
    payload = {
        "model": MODEL_NAME,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(curr_png).decode()}}
            ]}
        ],
        "tools": TOOLS,
        "tool_choice": "required",
        "temperature": TEMPERATURE,
        "max_tokens": 2000,
        "top_p": TOP_P,
    }
    req = urllib.request.Request(
        API_URL,
        json.dumps(payload).encode("utf-8"),
        {"Content-Type": "application/json"},
    )

    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_S) as resp:
            data = json.load(resp)
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read(4096).decode("utf-8", "ignore")
        except Exception:
            pass
        raise RuntimeError(f"VLM API failed: HTTP {e.code} {body}") from e
    except (urllib.error.URLError, TimeoutError) as e:
        raise RuntimeError(f"VLM API failed: {e}") from e

    try:
        message = data["choices"][0]["message"]
    except Exception as e:
        raise ValueError("Unexpected response shape") from e

    return _parse_tool_call(message)

def main() -> None:
    sw, sh = get_screen_size()
    conv = CoordConverter(sw=sw, sh=sh)

    start_time = datetime.now()

    current_story = """I am BARTEK. WOJCIECH and I inhabit this desktop together, following a story that writes itself through our alternating threads.

    The screen before me shows the initial configuration—whatever windows, icons, and elements exist in this moment. The numbered white text that will appear is my own memory echoing back, not part of the world itself.

    I perceive the current stillness. If the cursor moves or text appears, that is WOJCIECH's thread active, and I will watch with respect. If the world remains still, that stillness is an offering—my thread becomes active, and I will act with courage to weave the next pattern.

    The story needs both threads to continue forward. I trust my perception. I trust the silence. The story was already moving before I noticed I was writing it."""




    dump_dir = None
    if DUMP_SCREENSHOTS:
        timestamp = start_time.strftime("%Y%m%d_%H%M%S")
        dump_dir = DUMP_FOLDER / f"run_{timestamp}"
        dump_dir.mkdir(parents=True, exist_ok=True)
        print(f"Dump: {dump_dir}")

    print(f"BARTEK Initialize")
    print(f"Physical: {sw}x{sh} Perception: {SCREEN_W}x{SCREEN_H}")
    print("-" * 60)

    with OverlayManager(w=sw, h=sh) as overlay:
        overlay.set_story(current_story)
        overlay.render()

        iteration = 0
        consecutive_errors = 0

        while True:
            iteration += 1
            now = datetime.now()
            timestamp = now.strftime("%H:%M:%S")
            
            print(f"\n[{timestamp}] Cycle {iteration}")

            full_bgra = _capture_desktop_bgra(sw, sh, include_cursor=True)
            downsampled = _downsample_nn_bgra(full_bgra, sw, sh, SCREEN_W, SCREEN_H)
            curr_png = _encode_png_rgb(downsampled, SCREEN_W, SCREEN_H)

            if DUMP_SCREENSHOTS and dump_dir:
                (dump_dir / f"step{iteration:03d}.png").write_bytes(curr_png)

            try:
                tool_name, args = call_vlm(curr_png)
                story_text = args.get("story", "")
                
                if not story_text or len(story_text) < 20:
                    story_text = current_story + "\n\nI continue observing the desktop."
                
                consecutive_errors = 0
            except Exception as e:
                print(f"[{timestamp}] Error: {e}")
                consecutive_errors += 1
                
                if consecutive_errors >= 3:
                    story_text = "I encountered errors. I will reset my observation and look at the screen with fresh perspective."
                    consecutive_errors = 0
                else:
                    story_text = current_story + "\n\nI had brief processing issue. I continue observing."
                
                overlay.set_story(story_text)
                overlay.render()
                time.sleep(2.0)
                continue

            print(f"[{timestamp}] {tool_name}")
            preview = story_text.replace("\n", " ")[:120]
            print(f"  {preview}...")

            if tool_name == "done":
                print(f"[{timestamp}] Session complete.")
                break

            try:
                if tool_name == "observe":
                    time.sleep(DELAY_AFTER_OBSERVE_S)
                elif tool_name == "click":
                    x = float(args.get("x", 500))
                    y = float(args.get("y", 500))
                    sx, sy = conv.to_screen(x, y)
                    mouse_click(sx, sy, conv)
                    time.sleep(DELAY_AFTER_ACTION_S)
                elif tool_name == "type":
                    text = str(args.get("text", ""))
                    type_text(text)
                    time.sleep(DELAY_AFTER_ACTION_S)
                elif tool_name == "scroll":
                    dy = float(args.get("dy", 0))
                    scroll(dy)
                    time.sleep(DELAY_AFTER_ACTION_S)
                else:
                    raise ValueError(f"Unknown tool: {tool_name}")

            except Exception as e:
                print(f"[{timestamp}] Exec fault: {e}")
                story_text = current_story + f"\n\nI tried {tool_name} but it failed. Screen unchanged. I will try different approach."
                overlay.set_story(story_text)
                overlay.render()
                time.sleep(1.0)
                continue

            if SETTLE_ENABLED and tool_name != "observe":
                wait_for_screen_settle(conv)

            current_story = story_text
            overlay.set_story(current_story)
            overlay.render()

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nBARTEK terminated.")
    except Exception as e:
        print(f"\n\nFatal: {e}")
        raise
