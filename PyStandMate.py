import os
import time
import threading
import queue
import subprocess
import tkinter as tk
from tkinter import filedialog, messagebox
from pathlib import Path

from pynput import keyboard, mouse

import win32gui
import win32api
import win32con
import ctypes

# =========================
# SendInput 封装（增强版）
# =========================

SendInput = ctypes.windll.user32.SendInput

SCREEN_W = win32api.GetSystemMetrics(0)
SCREEN_H = win32api.GetSystemMetrics(1)

PUL = ctypes.POINTER(ctypes.c_ulong)

class INPUT(ctypes.Structure):
    class _I(ctypes.Union):
        _fields_ = [("mi", ctypes.c_ulong * 7), ("ki", ctypes.c_ulong * 7)]
    _anonymous_ = ("i",)
    _fields_ = [("type", ctypes.c_ulong), ("i", _I)]


def to_absolute(x, y):
    return int(x * 65535 / SCREEN_W), int(y * 65535 / SCREEN_H)


def send_mouse_abs(x, y, flags):
    ax, ay = to_absolute(x, y)
    ctypes.windll.user32.mouse_event(
        flags | win32con.MOUSEEVENTF_ABSOLUTE,
        ax, ay, 0, 0
    )


def send_key_scancode(vk, down=True):
    scan = win32api.MapVirtualKey(vk, 0)
    flags = win32con.KEYEVENTF_SCANCODE
    if not down:
        flags |= win32con.KEYEVENTF_KEYUP

    ctypes.windll.user32.keybd_event(0, scan, flags, 0)


# =========================
# 输入队列（核心）
# =========================

input_queue = queue.Queue()


def input_worker():
    while True:
        item = input_queue.get()

        if item["type"] == "mouse":
            send_mouse_abs(item["x"], item["y"], item["flag"])

        elif item["type"] == "key":
            send_key_scancode(item["vk"], item["down"])

        input_queue.task_done()


threading.Thread(target=input_worker, daemon=True).start()


# =========================
# VM 数据
# =========================

class VMItem:
    def __init__(self, path):
        self.path = path
        self.name = os.path.basename(path)
        self.hwnd = None


# =========================
# 窗口识别
# =========================

def find_windows(vm_list):
    def handler(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return

        title = win32gui.GetWindowText(hwnd)

        for vm in vm_list:
            if vm.name in title:
                vm.hwnd = hwnd

    win32gui.EnumWindows(handler, None)


# =========================
# 坐标映射
# =========================

def screen_to_client(hwnd, x, y):
    return win32gui.ScreenToClient(hwnd, (x, y))


def client_to_screen(hwnd, x, y):
    return win32gui.ClientToScreen(hwnd, (x, y))


# =========================
# 主程序
# =========================

class App:
    def __init__(self, root):
        self.root = root
        self.vm_list = []
        self.master = None
        self.syncing = False

        self.build_ui()

    def build_ui(self):
        top = tk.Frame(self.root)
        top.pack()

        tk.Button(top, text="扫描VMX", command=self.scan).pack(side=tk.LEFT)
        tk.Button(top, text="启动VM", command=self.start_vms).pack(side=tk.LEFT)
        tk.Button(top, text="设主控", command=self.set_master).pack(side=tk.LEFT)
        tk.Button(top, text="开始同步", command=self.start_sync).pack(side=tk.LEFT)

        self.listbox = tk.Listbox(self.root)
        self.listbox.pack(fill=tk.BOTH, expand=True)

    def scan(self):
        d = filedialog.askdirectory()
        for f in Path(d).rglob("*.vmx"):
            vm = VMItem(str(f))
            self.vm_list.append(vm)
            self.listbox.insert(tk.END, vm.name)

    def start_vms(self):
        for vm in self.vm_list:
            subprocess.Popen(["vmware.exe", vm.path])

        time.sleep(5)
        find_windows(self.vm_list)

    def set_master(self):
        idx = self.listbox.curselection()
        if not idx:
            return
        self.master = self.vm_list[idx[0]]
        messagebox.showinfo("OK", "主控设置成功")

    def start_sync(self):
        if not self.master:
            return

        self.syncing = True
        threading.Thread(target=self.sync_loop, daemon=True).start()

    def sync_loop(self):

        def on_move(x, y):
            if not self.syncing:
                return

            for vm in self.vm_list:
                if vm == self.master or not vm.hwnd:
                    continue

                cx, cy = screen_to_client(self.master.hwnd, x, y)
                tx, ty = client_to_screen(vm.hwnd, cx, cy)

                input_queue.put({
                    "type": "mouse",
                    "x": tx,
                    "y": ty,
                    "flag": win32con.MOUSEEVENTF_MOVE
                })

        def on_click(x, y, button, pressed):
            if not self.syncing:
                return

            flag = win32con.MOUSEEVENTF_LEFTDOWN if pressed else win32con.MOUSEEVENTF_LEFTUP

            for vm in self.vm_list:
                if vm == self.master or not vm.hwnd:
                    continue

                cx, cy = screen_to_client(self.master.hwnd, x, y)
                tx, ty = client_to_screen(vm.hwnd, cx, cy)

                input_queue.put({
                    "type": "mouse",
                    "x": tx,
                    "y": ty,
                    "flag": flag
                })

        def on_key_press(key):
            try:
                vk = key.vk if hasattr(key, 'vk') else key.value.vk
            except:
                return

            input_queue.put({"type": "key", "vk": vk, "down": True})

        def on_key_release(key):
            try:
                vk = key.vk if hasattr(key, 'vk') else key.value.vk
            except:
                return

            input_queue.put({"type": "key", "vk": vk, "down": False})

        mouse.Listener(on_move=on_move, on_click=on_click).start()
        keyboard.Listener(on_press=on_key_press, on_release=on_key_release).start()

        while self.syncing:
            time.sleep(0.005)


# =========================
# 启动
# =========================

if __name__ == "__main__":
    root = tk.Tk()
    root.title("DX增强同步器（用户态极限版）")
    App(root)
    root.mainloop()
  
