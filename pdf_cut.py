# pdf_cut.py
# 功能：PDF矩形区域自动识别分割导出
# 识别方案：轮廓粗筛 → 宽高比校验 → HSV直方图颜色相似度 + NCC结构相似度双重校验
# 支持渐变底色标牌/矩形图块；输出PNG图片 / 单页矢量PDF
# 配套gui.py：GUI界面，日志回调；可截图生成模板、导入外部图片模板
import pymupdf          # PDF解析、页面矢量渲染
import cv2              # OpenCV：轮廓查找、模板匹配、图像相似度计算
import numpy as np      # 矩阵运算，OpenCV依赖
import os               # 路径、文件夹创建
import gc               # 手动垃圾回收，防止大批量PDF处理内存持续上涨
from PIL import Image   # PIL：用于把裁切后的图像保存为单页PDF
import threading        # 线程


def get_screen_height(fallback=800):
    """
    获取屏幕可用高度
    用途：auto_target_height=True时，自动适配屏幕高度作为导出图片高度上限
    说明：tkinter临时导入，服务器/无桌面环境自动回落fallback=800
    """
    try:
        import tkinter as tk
        root = tk.Tk()
        root.withdraw()  # 隐藏窗口
        screen_h = root.winfo_screenheight()
        root.destroy()
        usable_h = screen_h - 100
        return usable_h
    except Exception:
        return fallback


def calc_hist_cosine_similarity(img_bgr, hist_template, bins=32):
    """
    HSV三维直方图余弦相似度【颜色匹配】
    ✅ 适合渐变底色矩形图块：只统计颜色分布占比，不关心图案位置
    参数：
    img_bgr: 待比对区域图像，BGR格式（OpenCV默认）
    hist_template: 提前预计算好的模板直方图（只算一次，提速）
    bins: 直方图分箱，数值越大颜色判定越严格
    返回：
    sim: 0~1，越接近1代表颜色分布越接近
    """
    def get_hist(bgr):
        # BGR转HSV，HSV对光照明暗变化鲁棒性更好
        hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
        # H:0~180，S/V:0~256，三维直方图统计颜色数量
        hist = cv2.calcHist([hsv], [0, 1, 2], None, [bins, bins, bins], [0, 180, 0, 256, 0, 256])
        hist = hist.flatten()
        # 归一化，消除图片尺寸大小带来的影响；+极小值防止除0报错
        hist = hist / (np.sum(hist) + 1e-8)
        return hist

    h1 = get_hist(img_bgr)
    # 余弦相似度公式：向量点积 / (向量模长乘积)
    sim = np.dot(h1, hist_template) / (np.linalg.norm(h1) * np.linalg.norm(hist_template) + 1e-8)
    return float(sim)


def calc_ncc_similarity(img_bgr, tpl_gray_pre, crop_border=4):
    """
    NCC归一化互相关相似度【结构匹配】
    ✅ 用来过滤：颜色很像，但内容/排版不一样的色块（纯文字块、杂色块）
    参数：
    img_bgr: 待比对区域BGR图
    tpl_gray_pre: 预先裁掉边缘白边的模板灰度图（预计算）
    crop_border: 比对前向内裁切像素，消除模板外围白边干扰匹配
    返回：
    score: 0~1，越接近1代表布局结构越接近
    补充：cv2.TM_CCOEFF_NORMED原生输出范围 -1 ~ 1，映射到0~1统一阈值判断
    """
    def inner_crop(img, b):
        h, w = img.shape[:2]
        # 图像太小不再裁切，避免数组越界
        if h <= 2 * b or w <= 2 * b:
            return img
        return img[b:-b, b:-b]

    img_gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    img_gray = inner_crop(img_gray, crop_border)

    # 模板匹配，归一化互相关
    res = cv2.matchTemplate(img_gray, tpl_gray_pre, cv2.TM_CCOEFF_NORMED)
    score = float(res[0][0])
    # [-1,1] → [0,1]
    score = (score + 1.0) / 2.0
    return score


def detect_export_slice(
    pdf_path: str,                # 待处理PDF路径
    template_path: str,           # 识别模板图片路径（矩形样图）
    out_img_dir: str,             # PNG图片输出目录
    out_pdf_dir: str = None,      # 单页矩形矢量PDF输出目录
    target_pixel_height: int = 800,    # 导出图片高度上限（px）
    auto_target_height: bool = False,  # 是否自动读取屏幕高度覆盖target_pixel_height
    detect_scale: float = 0.15,   # 识别阶段渲染缩放系数：越大识别越清晰、速度越慢
    border_margin_pt: float = 6.0,      # 识别框向外留白边距，单位pt（PDF原生单位）
    export_png: bool = True,      # 是否输出PNG图片
    export_pdf: bool = False,     # 是否输出单张矢量PDF
    fill_canvas: bool = False,    # 是否给图片增加一圈白底画布
    debug_draw: bool = False,     # 调试开关：开启会保存带候选框的页面图
    debug_max_height: int = 1200, # 调试图最大高度，防止超大页面内存爆炸
    debug_dir: str = None,        # 调试图片存放目录
    safe_render_zoom: float = 2.0,# 渲染倍率上限保护，防止渲染超大图OOM卡死
    area_min: int = 800,          # 轮廓最小面积：过滤细碎噪点
    area_max: int = 80000,        # 轮廓最大面积：过滤整页大色块
    ar_min: float = 0.4,          # 宽高比下限 w/h
    ar_max: float = 2.2,          # 宽高比上限 w/h
    hist_threshold: float = 0.60, # 颜色相似度阈值，低于直接丢弃
    ncc_threshold: float = 0.50,  # 结构相似度阈值，低于直接丢弃
    enable_template_ratio_check: bool = True, # 是否开启【模板基准宽高比校验】
    ratio_tol_low: float = 0.88,  # 比例容错下限
    ratio_tol_high: float = 1.12, # 比例容错上限
    ncc_crop_border: int = 4,     # NCC比对时，模板向内裁切像素
    use_adaptive_bin: bool = False, # 二值模式：False固定阈值；True自适应阈值（明暗不均页面）
    fixed_thresh_val: int = 240,  # 固定二值阈值，白底PDF优先使用
    adaptive_block_size: int = 31,# 自适应二值区块大小，必须奇数
    adaptive_c: int = 8,          # 自适应二值亮度偏移
    export_scale: float = 1.0,    # PNG二次缩放系数，仅影响图片，不影响矢量PDF
    log_callback = None,          # 日志回调函数，对接GUI；None时只print控制台输出
    stop_event: threading.Event = None  # ========== 新增停止信号参数 ==========
):
    """
    PDF矩形图块批量识别&裁切主函数
    流程总览：
    1. 加载模板，一次性预计算模板直方图、裁切后灰度图（提速核心，不用每个候选重复算）
    2. 循环PDF每一页，低分辨率渲染页面用于轮廓查找
    3. 二值化 → 查找外层轮廓 → 粗筛（面积、宽高比）
    4. 【可选】按模板宽高比二次筛选候选框
    5. 候选框裁剪、缩放至模板大小 → 颜色打分 → 结构打分，双重校验
    6. 通过校验：换算回PDF原始坐标，向外扩留白，高清渲染矩形区域
    7. 按配置：白底画布、二次缩放、保存PNG / 保存矢量PDF
    """
    # 日志封装：同时支持控制台打印 + GUI回调推送
    def log(msg):
        print(msg)
        if log_callback is not None:
            log_callback(msg)

    # ========== 新增：停止检查函数 ==========
    def check_stop():
        if stop_event is not None and stop_event.is_set():
            raise Exception("用户主动停止")

    # ---------- 导出缩放系数钳位保护，限制区间 0.1 ~ 2.0 ----------
    scale_min = 0.1
    scale_max = 2.0
    raw_export_scale = export_scale
    export_scale = max(scale_min, min(export_scale, scale_max))

    # ---------- 自动读取屏幕高度 ----------
    if auto_target_height:
        target_pixel_height = get_screen_height(fallback=800)

    # ---------- 初始化输出文件夹 ----------
    if export_png:
        os.makedirs(out_img_dir, exist_ok=True)
    if export_pdf and out_pdf_dir is not None:
        os.makedirs(out_pdf_dir, exist_ok=True)
    if debug_draw and debug_dir is not None:
        os.makedirs(debug_dir, exist_ok=True)

    # ---------- 加载模板图片（OpenCV读取默认BGR） ----------
    tpl_img = cv2.imread(template_path)
    if tpl_img is None:
        raise FileNotFoundError(f"模板不存在：{template_path}，使用彩色截图，不要转黑白")
    tpl_h, tpl_w = tpl_img.shape[:2]
    tpl_ratio = tpl_h / tpl_w   # 模板基准 h/w
    log(f">>> 模板标准比例 h/w = {tpl_ratio:.3f}，比例允许范围：{ratio_tol_low:.2f} ~ {ratio_tol_high:.2f}")

    # ---------- 模板预计算（只执行一次！性能关键点） ----------
    def get_hist_for_template(bgr, bins=32):
        hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
        hist = cv2.calcHist([hsv], [0, 1, 2], None, [bins, bins, bins], [0, 180, 0, 256, 0, 256])
        hist = hist.flatten()
        hist = hist / (np.sum(hist) + 1e-8)
        return hist
    hist_template = get_hist_for_template(tpl_img)

    def inner_crop_tpl(img, b):
        h, w = img.shape[:2]
        if h <= 2 * b or w <= 2 * b:
            return img
        return img[b:-b, b:-b]
    tpl_gray_raw = cv2.cvtColor(tpl_img, cv2.COLOR_BGR2GRAY)
    tpl_gray_pre = inner_crop_tpl(tpl_gray_raw, ncc_crop_border)

    # --------------------------------------------------------
    # ---------- 打开PDF文档 with上下文管理器，自动close，杜绝文件锁残留 ----------
    with pymupdf.open(pdf_path) as doc:
        total_pages = len(doc)
        idx = 0   # 全局成功图块计数器
        # 逐页循环处理
        for page_idx in range(total_pages):
            check_stop()   # 每页开始前检查停止
            page_progress = page_idx / total_pages * 100
            log(f"\n===== 正在处理第 {page_idx+1}/{total_pages} 页，页面进度：{page_progress:.1f}% =====")
            page = doc[page_idx]

            # 渲染低分辨率图，专门用来轮廓识别（速度优先）
            mat_detect = pymupdf.Matrix(detect_scale, detect_scale)
            pix_detect = page.get_pixmap(matrix=mat_detect, colorspace=pymupdf.csRGB)
            img_detect_rgb = np.frombuffer(pix_detect.samples, dtype=np.uint8).reshape(pix_detect.h, pix_detect.w, 3)
            img_detect_bgr = cv2.cvtColor(img_detect_rgb, cv2.COLOR_RGB2BGR)
            # 灰度图，用于二值化找轮廓
            gray = cv2.cvtColor(img_detect_rgb, cv2.COLOR_RGB2GRAY)

            # 二值化分支：固定阈值 / 自适应阈值二选一
            if use_adaptive_bin:
                # 自适应二值：适合页面明暗不均匀；缺点容易丢失细线条边框
                bin_img = cv2.adaptiveThreshold(
                    gray,
                    255,
                    cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                    cv2.THRESH_BINARY_INV,
                    adaptive_block_size,
                    adaptive_c
                )
            else:
                # 固定全局阈值：白底均匀PDF更稳定，优先使用
                _, bin_img = cv2.threshold(gray, fixed_thresh_val, 255, cv2.THRESH_BINARY_INV)

            # 腐蚀操作：收缩白色区域，消除细小噪点；风险：极细边框会被吃掉
            kernel = np.ones((2, 2), np.uint8)
            bin_img = cv2.erode(bin_img, kernel, iterations=1)

            # 查找最外层轮廓，只取外框，忽略嵌套内部轮廓
            contours, hierarchy = cv2.findContours(bin_img, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            if not contours:
                log(">>> 本页没有找到任何轮廓框")
                continue

            # 第一轮粗筛：面积 + 宽高比，过滤碎块、超大块
            candidate_contours = []
            for c in contours:
                area = cv2.contourArea(c)
                x, y, w, h = cv2.boundingRect(c)
                ar = w / h
                if area_min < area < area_max and ar_min < ar < ar_max:
                    candidate_contours.append(c)

            if not candidate_contours:
                log(">>> 粗筛之后，没有符合大小、比例的候选框")
                continue

            # ---------- DEBUG模式：绘制候选框并保存图片 ----------
            if debug_draw:
                scale_dbg = min(1.0, debug_max_height / pix_detect.h)
                dbg_rgb = cv2.resize(img_detect_rgb, None, fx=scale_dbg, fy=scale_dbg, interpolation=cv2.INTER_AREA)
                for c in candidate_contours:
                    x, y, w, h = cv2.boundingRect(c)
                    cv2.rectangle(
                        dbg_rgb,
                        (int(x * scale_dbg), int(y * scale_dbg)),
                        (int((x + w) * scale_dbg), int((y + h) * scale_dbg)),
                        (255, 0, 0), 2
                    )
                dbg_bgr = cv2.cvtColor(dbg_rgb, cv2.COLOR_RGB2BGR)
                cv2.imwrite(f"{debug_dir}/debug_p{page_idx}.png", dbg_bgr)
            # ------------------------------------------------------

            # 第二轮筛选：和模板基准宽高比比对
            filtered_by_ratio = candidate_contours
            if enable_template_ratio_check:
                filtered_by_ratio = []
                for idx_c, c in enumerate(candidate_contours):
                    xc, yc, wc, hc = cv2.boundingRect(c)
                    curr_ratio = hc / wc
                    ratio_rel = curr_ratio / tpl_ratio
                    if ratio_tol_low < ratio_rel < ratio_tol_high:
                        filtered_by_ratio.append((idx_c, c))

            log(f">>> 本页通过比例校验、准备比对相似度的候选数量：{len(filtered_by_ratio)} 个")

            # 遍历每一个比例合格候选框，颜色+结构双重打分
            for idx_c, cnt in filtered_by_ratio:
                check_stop()
                xc, yc, wc, hc = cv2.boundingRect(cnt)
                # 在识别缩略图上裁切候选区域
                crop = img_detect_bgr[yc:yc+hc, xc:xc+wc]
                # 缩放至和模板一样尺寸，才能做相似度比对
                crop_resized = cv2.resize(crop, (tpl_w, tpl_h), interpolation=cv2.INTER_AREA)

                # 颜色相似度打分，不达标直接跳过
                score_hist = calc_hist_cosine_similarity(crop_resized, hist_template)
                if score_hist < hist_threshold:
                    continue
                # 结构相似度打分，过滤同色不同排版的块
                score_ncc = calc_ncc_similarity(crop_resized, tpl_gray_pre, crop_border=ncc_crop_border)
                if score_ncc < ncc_threshold:
                    continue

                # ===================== 全部校验通过！开始导出 =====================
                # 把缩略图坐标，换算回PDF原始pt坐标
                x0_pt = xc / detect_scale
                y0_pt = yc / detect_scale
                x1_pt = (xc + wc) / detect_scale
                y1_pt = (yc + hc) / detect_scale
                # 向外扩展留白边距
                x0_pt -= border_margin_pt
                y0_pt -= border_margin_pt
                x1_pt += border_margin_pt
                y1_pt += border_margin_pt
                # 边界保护：防止框超出页面范围
                x0_pt = max(x0_pt, page.rect.x0)
                y0_pt = max(y0_pt, page.rect.y0)
                x1_pt = min(x1_pt, page.rect.x1)
                y1_pt = min(y1_pt, page.rect.y1)

                rect = pymupdf.Rect(x0_pt, y0_pt, x1_pt, y1_pt)
                clip_h_pt = rect.y1 - rect.y0
                # 根据矩形真实pt高度，计算高清渲染倍率
                zoom = target_pixel_height / clip_h_pt
                zoom = min(zoom, safe_render_zoom) # 渲染上限保护
                # 高清渲染矩形区域（矢量渲染，清晰度由zoom决定）
                mat_clip = pymupdf.Matrix(zoom, zoom)
                pix = page.get_pixmap(matrix=mat_clip, clip=rect, colorspace=pymupdf.csRGB)
                crop_img_rgb = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w, 3)
                ih, iw = crop_img_rgb.shape[:2]

                canvas_rgb = crop_img_rgb
                # 开启白底画布：外围增加一圈白底
                if fill_canvas:
                    pad = 10
                    ch = ih + pad * 2
                    cw = iw + pad * 2
                    canvas_rgb = np.ones((ch, cw, 3), dtype=np.uint8) * 255
                    off_y = pad
                    off_x = pad
                    canvas_rgb[off_y:off_y + ih, off_x:off_x + iw] = crop_img_rgb

                # PNG二次缩放，只作用图片，PDF矢量不受影响
                if export_scale != 1.0:
                    ch_, cw_ = canvas_rgb.shape[:2]
                    new_w = int(round(cw_ * export_scale))
                    new_h = int(round(ch_ * export_scale))
                    canvas_rgb = cv2.resize(canvas_rgb, (new_w, new_h), interpolation=cv2.INTER_LANCZOS4)

                # 保存PNG：cv2写文件需要BGR格式，RGB→BGR转换
                if export_png:
                    out_png_path = os.path.join(out_img_dir, f"{idx+1}.png")
                    canvas_bgr = cv2.cvtColor(canvas_rgb, cv2.COLOR_RGB2BGR)
                    cv2.imwrite(out_png_path, canvas_bgr)
                # 保存单张PDF矢量图：PIL直接接收RGB数组
                if export_pdf and out_pdf_dir is not None:
                    out_pdf_path = os.path.join(out_pdf_dir, f"{idx+1}.pdf")
                    im = Image.fromarray(crop_img_rgb)
                    im.save(out_pdf_path, "PDF")

                log(f"    [{idx_c}] ✅ 匹配成功，输出图块 {idx+1}")
                idx += 1
                # =================================================================

            # 主动释放，减少内存占用
            pix_detect = None

    gc.collect()
    log(f"\n✅ 全部处理完成！一共输出 {idx} 个图块")


if __name__ == "__main__":
    # 独立直接运行入口（命令行调试用，GUI调用不走这里）
    detect_export_slice(
        pdf_path="test.pdf",
        template_path="template.png",
        out_img_dir="out_img",
        out_pdf_dir="out_slice_pdf",
        target_pixel_height=800,
        auto_target_height=True,   # False固定800；True自动读取屏幕高度
        detect_scale=0.15,
        border_margin_pt=6.0,
        export_png=True,
        export_pdf=True,
        fill_canvas=True,
        debug_draw=True,
        debug_max_height=1200,
        debug_dir='debug_dir',
        safe_render_zoom=2.0,
        area_min=800,
        area_max=80000,
        ar_min=0.4,
        ar_max=2.2,
        hist_threshold=0.60,
        ncc_threshold=0.50,
        enable_template_ratio_check=True,
        ratio_tol_low=0.88,
        ratio_tol_high=1.12,
        ncc_crop_border=4,
        use_adaptive_bin=True,
        fixed_thresh_val=240,
        adaptive_block_size=31,
        adaptive_c=8,
        export_scale=1.0
    )
