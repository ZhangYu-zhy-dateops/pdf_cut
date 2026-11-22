import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import queue, threading, os, time, shutil
import pdf_cut
from PIL import Image, ImageTk
from screenshot_tool import SliceScreenshotWindow

# ===================== 基础配置 =====================
OUT_IMG_DIR = "out_img"
OUT_PDF_DIR = "out_slice_pdf"
BATCH_ARCHIVE_DIR = "archive_batch"
TEMPLATE_BACKUP_DIR = "template_backup"
TEMPLATE_FILE = "template.png"

os.makedirs(OUT_IMG_DIR, exist_ok=True)
os.makedirs(OUT_PDF_DIR, exist_ok=True)
os.makedirs(BATCH_ARCHIVE_DIR, exist_ok=True)
os.makedirs(TEMPLATE_BACKUP_DIR, exist_ok=True)


class SlicePdfGui:
    WIN_MODAL_W = 800
    WIN_MODAL_H = 600
    FONT_NORMAL = ("SimHei", 11)
    FONT_LOG = ("SimHei", 10)

    def __init__(self, root):
        self.root = root
        self.root.title("PDF图块截取分割工具")
        self.root.geometry("800x500")

        self.msg_queue = queue.Queue()
        self.running = False
        self.stop_flag = threading.Event()
        self.has_pdf = False

        self.var_pdf = tk.StringVar()
        self.var_scale = tk.DoubleVar(value=1.0)
        self.var_export_png = tk.BooleanVar(value=True)
        self.var_export_pdf = tk.BooleanVar(value=False)
        self.status_var = tk.StringVar(value="欢迎使用！请先选择PDF文件")

        self._init_style()
        self._build_menu()
        self._build_ui()
        self.poll_log()
        self._update_guide_status()

    def _open_path(self, path):
        if path and os.path.exists(path):
            self.root.attributes("-topmost", True)
            os.startfile(path)
            self.root.after(2000,lambda : self.root.attributes("-topmost", False))

    def _init_style(self):
        s = ttk.Style()
        s.configure("Action.TButton", font=self.FONT_NORMAL, padding=6)
        s.configure("Sub.TButton", font=self.FONT_NORMAL, padding=4)
        s.configure("Normal.TCheckbutton", font=self.FONT_NORMAL)

    def show_modal(self, title, text=None, img_path=None, confirm=False):
        """
        统一弹窗函数
        :param title: 标题
        :param text: 文本内容（文本弹窗）
        :param img_path: 图片路径（图片弹窗）
        :param confirm: True=显示确认/取消按钮，返回bool；False=纯预览无按钮，返回None
        """
        ret_var = tk.BooleanVar(value=False)
        win = tk.Toplevel(self.root)
        win.title(title)
        win.transient(self.root)
        win.grab_set()
        win.resizable(False, False)
        x = (win.winfo_screenwidth() - self.WIN_MODAL_W) // 2
        y = (win.winfo_screenheight() - self.WIN_MODAL_H) // 2
        win.geometry(f"{self.WIN_MODAL_W}x{self.WIN_MODAL_H}+{x}+{y}")

        main_frm = ttk.Frame(win)
        main_frm.pack(fill=tk.BOTH, expand=True)

        content_ok = True
        if img_path is not None:
            try:
                im = Image.open(img_path)
                # 预留底部按钮空间
                h_space = 90 if confirm else 40
                scale = min((self.WIN_MODAL_W - 40) / im.width, (self.WIN_MODAL_H - h_space) / im.height)
                im = im.resize((int(im.width * scale), int(im.height * scale)), Image.LANCZOS)
                img_tk = ImageTk.PhotoImage(im)
                lb_img = ttk.Label(main_frm, image=img_tk)
                lb_img.image = img_tk
                lb_img.pack(expand=True)
            except Exception as e:
                messagebox.showerror("错误", f"图片读取失败：{str(e)}", parent=win)
                win.destroy()
                return False if confirm else None
        elif text is not None:
            txt = tk.Text(main_frm, font=self.FONT_NORMAL, padx=15, pady=15)
            txt.insert(tk.END, text)
            txt.config(state=tk.DISABLED)
            txt.pack(fill=tk.BOTH, expand=True)
        else:
            content_ok = False

        if confirm and content_ok:
            btn_frm = ttk.Frame(main_frm)
            btn_frm.pack(pady=10)
            def on_ok():
                ret_var.set(True)
                win.destroy()
            def on_cancel():
                ret_var.set(False)
                win.destroy()
            ttk.Button(btn_frm, text="✅ 确认导入", command=on_ok).grid(row=0, column=0, padx=15)
            ttk.Button(btn_frm, text="❌ 取消", command=on_cancel).grid(row=0, column=1, padx=15)

        self.root.wait_window(win)
        return ret_var.get() if confirm else None

    def _build_menu(self):
        menubar = tk.Menu(self.root, tearoff=0)
        menu_open = tk.Menu(menubar, tearoff=0)
        menu_open.add_command(label="导出图片目录", command=lambda: self._open_path(OUT_IMG_DIR))
        menu_open.add_command(label="导出PDF目录", command=lambda: self._open_path(OUT_PDF_DIR))
        menu_open.add_command(label="归档批次目录", command=lambda: self._open_path(BATCH_ARCHIVE_DIR))
        menu_open.add_command(label="模板备份目录", command=lambda: self._open_path(TEMPLATE_BACKUP_DIR))
        menubar.add_cascade(label="📂 打开输出目录", menu=menu_open)
        menubar.add_command(label="📖 使用说明", command=self.show_help_popup)
        self.root.config(menu=menubar)

    def show_help_popup(self):
        help_text = """📌 操作步骤
1. 选择PDF文件：点【选择PDF】，选中需要识别裁切的PDF
2. 制作匹配模板（二选一）
    • 截图制作：手动打开PDF，调整画面到目标图块，框选保存为模板
    • 文件导入：直接挑选做好的模板图片导入，预览后确认导入
3. 输出选项
    • 导出图片：输出图片，可设置缩放系数 0.1 ~ 2.0
    • 导出PDF：输出单页独立PDF
4. 准备完成后，点击【开始处理】自动识别、裁切、归档
💡 温馨提示
    • 模板更新前，关闭看图软件，不要占用 template.png
    • 开始识别前，关闭源PDF，避免文件占用报错
    • 识别完成的文件会自动归档，按时间戳分文件夹保存
    • 识别过程中可以随时点【停止】终止任务，停止不会归档本次结果
    • 模板会自动备份，误操作可以去模板备份目录找回旧模板
    • 缩放只有勾选【导出图片】才生效，导出PDF保持原始尺寸
"""
        self.show_modal("📖 使用说明", text=help_text, confirm=False)

    def view_current_template(self):
        if not os.path.exists(TEMPLATE_FILE):
            messagebox.showwarning("提示", "暂无模板，请先导入或者截图生成模板")
            return
        self.show_modal("模板预览", img_path=TEMPLATE_FILE, confirm=False)

    def _backup_old_template(self):
        if os.path.exists(TEMPLATE_FILE):
            bak_name = f"template_{time.strftime('%Y%m%d_%H%M%S')}.png"
            bak_path = os.path.join(TEMPLATE_BACKUP_DIR, bak_name)
            shutil.copy2(TEMPLATE_FILE, bak_path)
            self.msg_queue.put(f">>> 旧模板已备份：{bak_name}")

    def select_pdf(self):
        fp = filedialog.askopenfilename(filetypes=[("PDF文件", "*.pdf")])
        if not fp:
            return
        self.var_pdf.set(fp)
        self.has_pdf = True
        self.msg_queue.put(f">>> 已选中PDF：{fp}")
        self._update_guide_status()

    def select_template_file(self):
        fp = filedialog.askopenfilename(filetypes=[("图片文件", "*.png;*.jpg;*.jpeg;*.bmp")])
        if not fp:
            return
        # 这里开启confirm=True，带确认按钮
        ok = self.show_modal("待导入模板预览", img_path=fp, confirm=True)
        if not ok:
            self.msg_queue.put(">>> 取消导入模板")
            return
        try:
            self._backup_old_template()
            shutil.copy2(fp, TEMPLATE_FILE)
            self.msg_queue.put(f">>> ✅ 模板更新成功")
        except PermissionError:
            self.msg_queue.put(">>> ⚠️ 模板文件被占用，请关闭看图软件重试")
        except Exception as e:
            self.msg_queue.put(f">>> ❌ 模板写入异常：{str(e)}")
        self._update_guide_status()

    def capture_template_by_rect(self):
        if not messagebox.askokcancel("操作提示", "请手动打开PDF，调整画面到目标图块。\n点【确定】开始框选截图；点【取消】退出。"):
            self.msg_queue.put(">>> 已取消截图")
            return
        shot_win = SliceScreenshotWindow(self.root, min_w=80, min_h=80)
        self.root.wait_window(shot_win.win)
        self.root.lift()
        if shot_win.result_img:
            try:
                self._backup_old_template()
                shot_win.result_img.save(TEMPLATE_FILE)
                self.msg_queue.put(">>> ✅ 截图模板保存成功")
            except PermissionError:
                self.msg_queue.put(">>> ⚠️ 模板文件被占用，请关闭看图软件重试")
            except Exception as e:
                self.msg_queue.put(f">>> ❌ 截图保存模板失败：{str(e)}")
        else:
            self.msg_queue.put(">>> 截图框选取消，未生成模板")
        self._update_guide_status()

    def _update_guide_status(self):
        pdf_ok = self.has_pdf
        tpl_ok = os.path.exists(TEMPLATE_FILE)
        self.btn_start.config(state=tk.NORMAL if pdf_ok else tk.DISABLED)
        self.btn_open_pdf.config(state=tk.NORMAL if pdf_ok else tk.DISABLED)
        self.btn_cap_temp.config(state=tk.NORMAL if pdf_ok else tk.DISABLED)
        self.btn_sel_temp.config(state=tk.NORMAL if pdf_ok else tk.DISABLED)
        if pdf_ok and tpl_ok:
            self.status_var.set("准备就绪，点击开始处理")
        elif pdf_ok:
            self.status_var.set("PDF已选，请添加模板文件")
        else:
            self.status_var.set("请先选择PDF文件")
        self.entry_scale.config(state=tk.NORMAL if self.var_export_png.get() else tk.DISABLED)

    def _clear_work_dir(self):
        for folder in (OUT_IMG_DIR, OUT_PDF_DIR):
            for f in os.listdir(folder):
                fp = os.path.join(folder, f)
                try:
                    if os.path.isfile(fp):
                        os.remove(fp)
                except Exception:
                    pass

    def _archive_current_batch(self):
        batch_id = time.strftime("batch_%Y%m%d_%H%M%S")
        batch_img_arch = os.path.join(BATCH_ARCHIVE_DIR, batch_id, OUT_IMG_DIR)
        batch_pdf_arch = os.path.join(BATCH_ARCHIVE_DIR, batch_id, OUT_PDF_DIR)
        os.makedirs(batch_img_arch, exist_ok=True)
        os.makedirs(batch_pdf_arch, exist_ok=True)
        for fname in os.listdir(OUT_IMG_DIR):
            shutil.copy2(os.path.join(OUT_IMG_DIR, fname), os.path.join(batch_img_arch, fname))
        for fname in os.listdir(OUT_PDF_DIR):
            shutil.copy2(os.path.join(OUT_PDF_DIR, fname), os.path.join(batch_pdf_arch, fname))
        self.msg_queue.put(f">>> ✅ 已归档至：{batch_id}")

    def _worker_task(self):
        self.running = True
        self.stop_flag.clear()
        try:
            scale = self.var_scale.get()
            if not 0.1 <= scale <= 2.0:
                raise Exception("缩放系数必须在0.1~2.0之间")
            if not os.path.exists(TEMPLATE_FILE):
                raise Exception("模板 template.png 不存在，请先制作模板")
            self.msg_queue.put(">>> 清空输出目录，准备开始识别")
            self._clear_work_dir()
            pdf_cut.detect_export_slice(
                pdf_path=self.var_pdf.get(),
                template_path=TEMPLATE_FILE,
                out_img_dir=OUT_IMG_DIR,
                out_pdf_dir=OUT_PDF_DIR,
                export_png=self.var_export_png.get(),
                export_pdf=self.var_export_pdf.get(),
                export_scale=scale,
                log_callback=lambda s: self.msg_queue.put(s),
                stop_event=self.stop_flag
            )
            self._archive_current_batch()
            self.msg_queue.put("\n>>> ✅ 本轮识别全部完成！")
        except Exception as e:
            err_str = str(e)
            if "用户主动停止" in err_str:
                self.msg_queue.put("\n>>> ⏹ 任务已手动停止，不归档")
            else:
                self.msg_queue.put(f"\n>>> ❌ 任务异常：{err_str}")
        finally:
            self.running = False
            self.root.after(0, self._update_guide_status)

    def start_run(self):
        if not messagebox.askokcancel("操作提示", "请确认关闭PDF、模板文件，避免占用报错。\n确定开始？"):
            self.msg_queue.put(">>> 取消本次任务")
            return
        if self.running:
            messagebox.showwarning("提示", "任务正在运行中")
            return
        self.btn_start.config(state=tk.DISABLED)
        self.btn_stop.config(state=tk.NORMAL)
        self.status_var.set("正在处理中，请勿关闭窗口")
        threading.Thread(target=self._worker_task, daemon=True).start()

    def stop_run(self):
        if self.running:
            self.stop_flag.set()
            self.msg_queue.put(">>> ⚠️ 发送停止信号...")

    def poll_log(self):
        while not self.msg_queue.empty():
            self.text_log.insert(tk.END, self.msg_queue.get() + "\n")
            self.text_log.see(tk.END)
        self.root.after(50, self.poll_log)

    def _build_ui(self):
        main_container = ttk.Frame(self.root, padding=5)
        main_container.grid(row=0, column=0, sticky="nsew")
        self.root.grid_rowconfigure(0, weight=1)
        self.root.grid_columnconfigure(0, weight=1)
        main_container.grid_rowconfigure(1, weight=1)
        main_container.grid_columnconfigure(0, weight=1)

        frame_top = ttk.Frame(main_container)
        frame_top.grid(row=0, column=0, sticky="ew", pady=5)

        ttk.Label(frame_top, text="1.选择PDF:", font=self.FONT_NORMAL).grid(row=0, column=0, padx=3, pady=4, sticky="w")
        self.btn_select_pdf = ttk.Button(frame_top, text="选择PDF", command=self.select_pdf, style="Action.TButton")
        self.btn_select_pdf.grid(row=0, column=1, padx=3, pady=4)
        self.btn_open_pdf = ttk.Button(frame_top, text="打开", command=lambda: self._open_path(self.var_pdf.get()), state=tk.DISABLED, style="Sub.TButton")
        self.btn_open_pdf.grid(row=0, column=2, padx=3, pady=4)

        ttk.Label(frame_top, text="2.制作模板:", font=self.FONT_NORMAL).grid(row=1, column=0, padx=3, pady=4, sticky="w")
        self.btn_cap_temp = ttk.Button(frame_top, text="截图制作", command=self.capture_template_by_rect, state=tk.DISABLED, style="Action.TButton")
        self.btn_cap_temp.grid(row=1, column=1, padx=3, pady=4)
        self.btn_sel_temp = ttk.Button(frame_top, text="文件导入", command=self.select_template_file, state=tk.DISABLED, style="Action.TButton")
        self.btn_sel_temp.grid(row=1, column=2, padx=3, pady=4)
        self.btn_view_temp = ttk.Button(frame_top, text="预览模板", command=self.view_current_template, style="Sub.TButton")
        self.btn_view_temp.grid(row=1, column=3, padx=3, pady=4)

        ttk.Label(frame_top, text="3.输出选项:", font=self.FONT_NORMAL).grid(row=2, column=0, padx=3, pady=4, sticky="w")
        ttk.Checkbutton(frame_top, text="导出图片", variable=self.var_export_png, command=self._update_guide_status, style="Normal.TCheckbutton").grid(row=2, column=1, padx=3, pady=4)
        ttk.Label(frame_top, text="图片缩放:", font=self.FONT_NORMAL).grid(row=2, column=2, padx=3, pady=4, sticky="e")
        self.entry_scale = ttk.Entry(frame_top, textvariable=self.var_scale, width=5)
        self.entry_scale.grid(row=2, column=3, padx=3, pady=4, sticky="w")
        ttk.Checkbutton(frame_top, text="导出PDF", variable=self.var_export_pdf, style="Normal.TCheckbutton").grid(row=2, column=4, padx=3, pady=4)

        self.btn_start = ttk.Button(frame_top, text="▶ 开始处理", command=self.start_run, state=tk.DISABLED, style="Action.TButton")
        self.btn_start.grid(row=3, column=1, padx=3, pady=4)
        self.btn_stop = ttk.Button(frame_top, text="■ 停止", command=self.stop_run, state=tk.DISABLED, style="Sub.TButton")
        self.btn_stop.grid(row=3, column=2, padx=3, pady=4)

        log_frame = ttk.LabelFrame(main_container, text="运行信息")
        log_frame.grid(row=1, column=0, sticky="nsew", pady=5)
        log_frame.grid_rowconfigure(0, weight=1)
        log_frame.grid_columnconfigure(0, weight=1)
        self.text_log = tk.Text(log_frame, font=self.FONT_LOG)
        self.text_log.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)

        status_label = ttk.Label(main_container, textvariable=self.status_var, relief=tk.SUNKEN, anchor="w", font=self.FONT_NORMAL)
        status_label.grid(row=2, column=0, sticky="ew", pady=(3,0))


if __name__ == '__main__':
    root = tk.Tk()
    app = SlicePdfGui(root)
    root.mainloop()
