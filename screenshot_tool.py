import tkinter as tk
from tkinter import ttk
import numpy as np
from PIL import Image, ImageTk, ImageGrab
import time

# 必须最开始就调用，这是全局系统设置
import sys
if sys.platform == "win32":
    import ctypes
    try:
        # Win8.1+ Win10：逐显示器DPI感知，高分屏截图最准
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except (AttributeError, OSError):
        # Win7/Vista兜底：系统级DPI感知，解决单屏缩放错位
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            # 实在调用失败就直接跳过，不影响原有截图功能
            pass


class SliceScreenshotWindow:
    """
    通用矩形框选截图工具（PDF分割导出、模板拾取通用）
    功能清单：
        - 先抓取屏幕原图，再弹出暗化遮罩，UI不会被截进图内
        - 背景变暗，框选区域原图高亮；绿色选框
        - 确认/取消悬浮按钮自带-topmost置顶，自动避让屏幕边界
        - 点击确认后弹出居中模态二次确认窗口
        - ESC 退出截图；鼠标移入画布后ESC生效
        - 最小尺寸过滤过小框选
        - 输出原始像素裁剪图，不缩放、不插值，适配PDF分割、模板采集
    """
    def __init__(self, root_main, min_w=80, min_h=80):
        self.root_main = root_main
        self.min_w = min_w
        self.min_h = min_h

        self.result_img = None          # 最终裁剪图，外部读取这个
        self.popup_locked = False       # 框选完成锁定，防止重复点击
        self.crop_img_cache = None      # 缓存框选图片，供二次确认
        self.btn_win = None             # 悬浮按钮窗口

        # 1. 主窗口后置让出焦点，抓取全屏原图
        self.root_main.lower()
        self.root_main.update_idletasks()
        time.sleep(0.15)
        self.full_img = ImageGrab.grab()
        self.screen_w, self.screen_h = self.full_img.size

        # 2. 生成暗化背景图（未选中区域变暗）
        dark_array = (np.array(self.full_img, dtype=np.float32) * 0.45).clip(0, 255).astype(np.uint8)
        self.dark_img = Image.fromarray(dark_array)

        # 3. 创建全屏截图窗口，移除focus_force避免压掉悬浮置顶按钮
        self.win = tk.Toplevel(root_main)
        self.win.title("矩形框选截图")
        self.win.attributes("-fullscreen", True)
        self.win.configure(bg="black")
        self.win.bind("<Escape>", self.on_cancel)

        self.canvas = tk.Canvas(self.win, bg="black", highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.canvas.bind("<Escape>", self.on_cancel)
        self.canvas.bind("<Enter>", lambda e: self.canvas.focus_set()) # 鼠标移入画布获得焦点，ESC可用

        self.tk_dark = ImageTk.PhotoImage(self.dark_img)
        self.canvas.create_image(0, 0, anchor=tk.NW, image=self.tk_dark)
        self.canvas.create_text(
            self.screen_w // 2, 40,
            text="拖动鼠标框选矩形区域 | ESC 退出截图",
            fill="#ffffff", font=("SimHei", 16)
        )

        # 画布元素id，用于后续清理
        self.start_x = self.start_y = None
        self.bright_patch_id = None
        self.rect_id = None
        self.size_text_id = None

        # 保存高亮patch引用，防止被GC回收（关键！）
        self.tk_bright_patch = None
        self.tk_preview = None

        # 绑定鼠标事件
        self.canvas.bind("<ButtonPress-1>", self.on_down)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_up)

    def on_down(self, event):
        """鼠标按下：记录起点，清空上一次框选UI"""
        if self.popup_locked:
            return
        self.start_x, self.start_y = event.x, event.y
        self._clear_canvas_widgets()

    def on_drag(self, event):
        """鼠标拖动：实时绘制选框、高亮预览区域"""
        if self.popup_locked:
            return
        self._clear_canvas_widgets()

        x1 = min(self.start_x, event.x)
        y1 = min(self.start_y, event.y)
        x2 = max(self.start_x, event.x)
        y2 = max(self.start_y, event.y)
        w, h = x2 - x1, y2 - y1
        if w <= 10 or h <= 10:
            return

        patch = self.full_img.crop((x1, y1, x2, y2))
        self.tk_bright_patch = ImageTk.PhotoImage(patch)
        self.bright_patch_id = self.canvas.create_image(x1, y1, anchor=tk.NW, image=self.tk_bright_patch)
        self.rect_id = self.canvas.create_rectangle(x1, y1, x2, y2, outline="#00ff00", width=3)

    def on_up(self, event):
        """鼠标松开：弹出置顶悬浮确认按钮"""
        if self.popup_locked:
            return
        self.popup_locked = True

        x1 = min(self.start_x, event.x)
        y1 = min(self.start_y, event.y)
        x2 = max(self.start_x, event.x)
        y2 = max(self.start_y, event.y)
        w, h = x2 - x1, y2 - y1

        if w < self.min_w or h < self.min_h:
            self.popup_locked = False
            return

        self.crop_img_cache = self.full_img.crop((x1, y1, x2, y2))
        margin = 8

        self.btn_win = tk.Toplevel(self.win)
        self.btn_win.overrideredirect(True)
        self.btn_win.attributes("-topmost", True) # 悬浮工具栏置顶
        frm = tk.Frame(self.btn_win)
        frm.pack()
        tk.Button(frm, text="✓确认", bg="#008822", fg="white", width=8, command=self.show_confirm_dialog).grid(row=0, column=0, padx=(0,10))
        tk.Button(frm, text="✕取消", bg="#992222", fg="white", width=8, command=self.do_cancel).grid(row=0, column=1)
        self.btn_win.update_idletasks()
        real_w, real_h = self.btn_win.winfo_width(), self.btn_win.winfo_height()

        # 锚点：选框右下角
        btn_x, btn_y = x2 + margin, y2 - real_h
        # 外侧放不下 → 放到框内右下角
        if not (margin <= btn_x and btn_x+real_w <= self.screen_w-margin and margin <= btn_y and btn_y+real_h <= self.screen_h-margin):
            btn_x = x2 - real_w - margin
            btn_y = y2 - real_h - margin

        # 兜底，强制在框内，防止按钮比框还大
        btn_x = max(x1, btn_x)
        btn_y = max(y1, btn_y)
        # 全局屏幕边界兜底
        btn_x = max(margin, btn_x)
        btn_y = max(margin, btn_y)

        self.btn_win.geometry(f"{real_w}x{real_h}+{btn_x}+{btn_y}")

    def show_confirm_dialog(self):
        """弹出居中模态二次确认窗口"""
        dlg = tk.Toplevel(self.win)
        dlg.title("确认截图区域")
        screen_w = dlg.winfo_screenwidth()
        screen_h = dlg.winfo_screenheight()
        dlg_w = 320
        dlg_h = 100
        pos_x = (screen_w - dlg_w) // 2
        pos_y = (screen_h - dlg_h) // 2
        dlg.geometry(f"{dlg_w}x{dlg_h}+{pos_x}+{pos_y}")

        dlg.resizable(False, False)
        dlg.attributes("-topmost", True)
        dlg.transient(self.win)
        dlg.grab_set()

        tk.Label(dlg, text="是否保存该截图到文件？", font=("SimHei", 11)).pack(pady=(8, 4))

        frame_btn = tk.Frame(dlg)
        frame_btn.pack(pady=8)

        def ok_callback():
            self.result_img = self.crop_img_cache
            dlg.destroy()
            self.win.destroy()

        def no_callback():
            dlg.destroy()
            self._clear_canvas_widgets()
            self.popup_locked = False

        ttk.Button(frame_btn, text="确定", command=ok_callback, width=10).grid(row=0, column=0, padx=8)
        ttk.Button(frame_btn, text="取消", command=no_callback, width=10).grid(row=0, column=1, padx=8)

    def do_cancel(self):
        """点击悬浮取消：清空框选，解锁，可以重新框选"""
        self._clear_canvas_widgets()
        self.popup_locked = False
        self.crop_img_cache = None

    def _clear_canvas_widgets(self):
        """清理画布上所有框选元素，同时销毁悬浮按钮窗口"""
        items = [self.bright_patch_id, self.rect_id, self.size_text_id]
        for item in items:
            if item:
                self.canvas.delete(item)
        self.bright_patch_id = self.rect_id = self.size_text_id = None

        if self.btn_win is not None and self.btn_win.winfo_exists():
            self.btn_win.destroy()
            self.btn_win = None

    def on_cancel(self, event=None):
        """ESC退出：直接放弃截图，关闭整个截图窗口"""
        self.result_img = None
        if self.win.winfo_exists():
            self.win.destroy()


if __name__ == "__main__":
    # 独立运行测试入口
    root = tk.Tk()
    root.withdraw()
    shot = SliceScreenshotWindow(root)
    root.wait_window(shot.win)
    if shot.result_img is not None:
        shot.result_img.save("template.png")
        print("截图保存成功: template.png")
    else:
        print("截图取消")
