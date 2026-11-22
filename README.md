# PDF批量识别截图工具
[![Python](https://img.shields.io/badge/Python-3.8+-3776AB?logo=python)](https://www.python.org/)
[![OpenCV](https://img.shields.io/badge/OpenCV-opencv--python-5C3EE8?logo=opencv)](https://opencv.org/)
[![PyMuPDF](https://img.shields.io/badge/PyMuPDF-pymupdf-008080)](https://pymupdf.readthedocs.io/)
[![Pillow](https://img.shields.io/badge/Pillow-PIL-1155CC)](https://pillow.readthedocs.io/)
[![NumPy](https://img.shields.io/badge/NumPy-numpy-013243?logo=numpy)](https://numpy.org/)
[![Tkinter](https://img.shields.io/badge/Tkinter-GUI-444444)](https://docs.python.org/3/library/tkinter.html)

> 基于 Python + Tkinter 开发的通用GUI工具，内置截图框选功能，用于PDF内目标识别、裁切导出。

> ⚠️ 本项目代码完全由AI生成

## ✨ 功能清单
- PDF文件选择，调用系统默认PDF软件打开
- 截图框选生成模板，模板预览（纯预览窗口，仅关闭按钮）
- 模板匹配识别，批量裁切输出图片与单页PDF
- 输出分目录存放：`out_img` / `out_slice_pdf`
- 批次归档 `archive_batch`，模板自动备份 `template_backup`
- 顶部菜单收纳目录打开入口，界面简洁，区分必做/可选操作
- 截图框支持暗化遮罩、选框预览、悬浮确认/取消按钮，边界避让
- 日志输出、状态栏提示，可控制导出图片缩放比例

## 📁 目录说明（程序自动创建）
```
├── out_img/            # 输出图片
├── out_slice_pdf/      # 输出单页PDF
├── archive_batch/      # 批次归档文件夹
├── template_backup/    # 模板备份
├── template.png        # 当前使用模板
├── gui.py              # 主界面
├── pdf_cut.py          # PDF识别裁切逻辑
├── screenshot_tool.py  # 框选截图组件
```

## 🧠 实现原理
1. **模板匹配**：采用NCC归一化互相关+轮廓比对，支持渐变、无黑框、圆形目标场景；先识别目标轮廓，再统一缩放裁切，保证图形比例不变。
2. **截图组件**：全屏暗化层框选拾取，悬浮按钮自动避让屏幕边界，锚定鼠标释放位置，方便二次确认生成模板。
3. **文件组织**：最新输出放在out目录，每处理一批自动归档备份。
4. **界面**：原生tkinter，无重型GUI框架；布局使用grid权重控制，状态栏固定不被挤出。
5. **PDF交互**：不内置PDF渲染控件，调用系统默认PDF阅读器打开，降低开发复杂度、保留原生缩放移动能力。

## 🎯 开发初衷
1. 业务上要把一个大pdf中的批量矩形分割成多个图片/pdf
2. 做成通用工具，剥离业务专有文字，交付给非专业人员也能操作。
3. 流程可控：模板可自定义截图制作，每批次结果自动归档，方便回溯核对。

## 📌 运行环境
- Python 3.8+
- 依赖包：
  - `pymupdf`：PDF解析、页面矢量渲染、坐标换算
  - `opencv-python`：轮廓查找、NCC模板匹配、图像相似度计算
  - `numpy`：矩阵运算，OpenCV数值计算依赖
  - `Pillow`：图像保存、导出单页PDF
> Tkinter为Python自带，无需额外安装

## 🚀 运行命令
```bash
# 安装全部依赖
pip install pymupdf opencv-python numpy pillow

# 启动主程序
python gui.py
```

## 📦 打包提示（PyInstaller）
```bash
# 打包命令示例
pyinstaller -F -w gui.py
```
- `-F`：单文件打包；`-w`：不弹出黑色控制台窗口
- 打包后程序同目录会自动生成各个输出文件夹
- 不要把out_img、archive_batch等输出目录打包进exe
- 32位Python打包出来的exe才能在Windows 32位环境正常使用
- 注意：打包后DPI感知代码在部分Win7环境需要测试校验

## 📝 使用步骤
1. 运行 `gui.py`
2. 【必做】选择PDF文件，系统软件打开PDF
3. 【可选】截图框选制作模板，或者直接选用已有模板
4. 确认模板后，点击开始处理，自动识别裁切
5. 处理完成，从菜单打开对应输出目录查看结果

## 🙏 感谢
感谢豆包AI（代码100%由AI生成）以及开源社区 pymupdf、opencv、Pillow、NumPy、Tkinter 等项目提供基础能力支撑。