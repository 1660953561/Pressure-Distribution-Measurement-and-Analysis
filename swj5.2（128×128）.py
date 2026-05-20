import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import serial
import serial.tools.list_ports
import threading
import time
import os
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from scipy.ndimage import convolve
from scipy.interpolate import RectBivariateSpline

# --- 配置常量 ---
DEFAULT_COM = 'COM5'
DEFAULT_BAUD = 9600
V_REF = 3.3
ADC_RESOLUTION = 16383
SAVE_DIR_BASE = r"D:\study\基于面压力分布在位测量的CMP加工机理研究\传感器数据"


class PressureSensorApp:
    def __init__(self, root):
        self.root = root
        self.root.title("压力传感器实时可视化系统 ")
        self.root.geometry("1400x900")

        # 数据存储
        self.data_matrix = np.zeros((16, 16))
        self.lock = threading.Lock()
        self.running = False
        self.data_counter = 0
        self.file_count = 0
        self.current_save_dir = ""

        # UI 构建
        self._setup_ui()

        # 绘图对象初始化 (避免在循环中重复创建)
        self._init_plots()

        # 启动定时刷新
        self.update_ui_loop()

    def _setup_ui(self):
        """初始化界面布局"""
        # 控制面板
        control_frame = ttk.LabelFrame(self.root, text="控制选项")
        control_frame.grid(row=0, column=0, padx=10, pady=5, sticky="nw")

        ttk.Label(control_frame, text="串口:").grid(row=0, column=0, padx=5)
        self.com_var = tk.StringVar(value=DEFAULT_COM)
        self.com_entry = ttk.Entry(control_frame, textvariable=self.com_var, width=10)
        self.com_entry.grid(row=0, column=1, padx=5)

        ttk.Label(control_frame, text="波特率:").grid(row=1, column=0, padx=5)
        self.baud_var = tk.StringVar(value=str(DEFAULT_BAUD))
        ttk.Entry(control_frame, textvariable=self.baud_var, width=10).grid(row=1, column=1, padx=5)

        self.btn_start = ttk.Button(control_frame, text="开始采集", command=self.start_collection)
        self.btn_start.grid(row=2, column=0, pady=5)
        self.btn_stop = ttk.Button(control_frame, text="停止采集", command=self.stop_collection, state=tk.DISABLED)
        self.btn_stop.grid(row=2, column=1, pady=5)

        ttk.Button(control_frame, text="手动保存当前帧", command=self.manual_save).grid(row=3, column=0, columnspan=2,
                                                                                        sticky="ew")

        # 数据表格面板
        self.data_frame = ttk.LabelFrame(self.root, text="实时数值 (16x16)")
        self.data_frame.grid(row=0, column=1, padx=10, pady=5, sticky="nw")
        self.grid_labels = []
        for i in range(16):
            row_labels = []
            for j in range(16):
                lbl = tk.Label(self.data_frame, text="0.0", width=5, relief="flat", font=('Arial', 8))
                lbl.grid(row=i, column=j)
                row_labels.append(lbl)
            self.grid_labels.append(row_labels)

        # 绘图区域
        self.plot_container = tk.Frame(self.root)
        self.plot_container.grid(row=1, column=0, columnspan=2, sticky="nsew")

        self.heatmap_frame = tk.Frame(self.plot_container)
        self.heatmap_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.mesh_frame = tk.Frame(self.plot_container)
        self.mesh_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

    def _init_plots(self):
        """初始化 Matplotlib 图表对象"""
        # 2D 热力图
        self.fig2d, self.ax2d = plt.subplots(figsize=(5, 4))
        self.im = self.ax2d.imshow(self.data_matrix, cmap='jet', vmin=0, vmax=1.8, interpolation='bilinear')
        self.fig2d.colorbar(self.im, ax=self.ax2d)
        self.canvas2d = FigureCanvasTkAgg(self.fig2d, master=self.heatmap_frame)
        self.canvas2d.get_tk_widget().pack(fill=tk.BOTH, expand=True)

        # 3D 曲面图
        self.fig3d = plt.figure(figsize=(5, 4))
        self.ax3d = self.fig3d.add_subplot(111, projection='3d')
        self.canvas3d = FigureCanvasTkAgg(self.fig3d, master=self.mesh_frame)
        self.canvas3d.get_tk_widget().pack(fill=tk.BOTH, expand=True)

    # --- 核心处理逻辑 ---
    def voltage_to_force(self, voltage):
        """电压转换逻辑封装"""
        if voltage <= 0.01: return 0.0  # 忽略噪声
        # 此处保留原有的转换公式位置
        return voltage

    def process_raw_line(self, line):
        """解析串口行数据: 假设格式 Row1Col1: 1234"""
        try:
            if ":" in line:
                header, value = line.split(":")
                if "Row" in header and "Col" in header:
                    # 提取数字
                    r_part = header.split("Col")[0].replace("Row", "")
                    c_part = header.split("Col")[1]
                    row = int(r_part.strip()) - 1
                    col = int(c_part.strip()) - 1

                    adc = int(value.strip())
                    voltage = (adc / ADC_RESOLUTION) * V_REF
                    force = self.voltage_to_force(voltage)

                    if 0 <= row < 16 and 0 <= col < 16:
                        with self.lock:
                            self.data_matrix[row, col] = force
        except Exception as e:
            pass  # 鲁棒性：忽略损坏的帧数据

    def read_serial_thread(self):
        """串口读取线程"""
        try:
            ser = serial.Serial(self.com_var.get(), int(self.baud_var.get()), timeout=0.1)
            while self.running:
                if ser.in_waiting > 0:
                    # 使用 readline 配合解码更安全
                    line = ser.readline().decode('utf-8', errors='ignore').strip()
                    if line:
                        self.process_raw_line(line)
                        self.data_counter += 1

                        # 自动保存逻辑
                        if self.data_counter >= 128:  # 约每 16*16*1.25 采样保存一次
                            self.auto_save_snapshot()
                            self.data_counter = 0
            ser.close()
        except Exception as e:
            messagebox.showerror("串口错误", f"无法打开串口: {e}")
            self.stop_collection()

    # --- 数据处理算法 ---
    def get_processed_data(self):
        """获取降噪和插值后的数据"""
        with self.lock:
            raw = self.data_matrix.copy()

        # 1. 简单均值降噪
        kernel = np.array([[0.1, 0.2, 0.1],
                           [0.2, 0.4, 0.2],
                          [0.1, 0.2, 0.1]])
        denoised = convolve(raw, kernel, mode='constant')
        denoised[denoised < 0.05] = 0

        # 2. 插值
        x = np.arange(16)
        y = np.arange(16)
        interp_func = RectBivariateSpline(y, x, denoised)

        x_new = np.linspace(0, 15, 128)  # 降至 64 提高实时性，128 渲染较慢
        y_new = np.linspace(0, 15, 128)
        interp_data = interp_func(y_new, x_new)

        return raw, interp_data

    # --- UI 更新任务 ---
    def update_ui_loop(self):
        """主循环更新界面"""
        if self.running:
            raw, interp = self.get_processed_data()

            # 更新 2D 图 (直接修改数据而非重绘)
            self.im.set_data(interp)
            self.canvas2d.draw_idle()

            # 更新 3D 图 (3D 绘图较重，可以隔帧更新)
            if self.data_counter % 5 == 0:
                self.update_3d_plot(interp)

            # 更新文本表格 (低频更新以节省资源)
            if self.data_counter % 10 == 0:
                for i in range(16):
                    for j in range(16):
                        val = raw[i, j]
                        color = "#%02x%02x%02x" % (int(min(255, val * 100)), 200, 150)
                        self.grid_labels[i][j].config(text=f"{val:.1f}", bg=color)

        # 约 30 FPS
        self.root.after(33, self.update_ui_loop)

    def update_3d_plot(self, matrix):
        self.ax3d.clear()
        x = np.linspace(0, 15, matrix.shape[1])
        y = np.linspace(0, 15, matrix.shape[0])
        X, Y = np.meshgrid(x, y)
        self.ax3d.plot_surface(X, Y, matrix, cmap='viridis', antialiased=False)
        self.ax3d.set_zlim(0, 1.8)
        self.canvas3d.draw_idle()

    # --- 采集控制 ---
    def start_collection(self):
        self.running = True
        self.btn_start.config(state=tk.DISABLED)
        self.btn_stop.config(state=tk.NORMAL)

        # 创建文件夹
        ts = time.strftime("%Y%m%d_%H%M%S")
        self.current_save_dir = os.path.join(SAVE_DIR_BASE, f"Session_{ts}")
        os.makedirs(self.current_save_dir, exist_ok=True)

        threading.Thread(target=self.read_serial_thread, daemon=True).start()

    def stop_collection(self):
        self.running = False
        self.btn_start.config(state=tk.NORMAL)
        self.btn_stop.config(state=tk.DISABLED)

    def auto_save_snapshot(self):
        """自动保存 16x16 数据"""
        self.file_count += 1
        path = os.path.join(self.current_save_dir, f"Group_{self.file_count}_.txt")
        with self.lock:
            np.savetxt(path, self.data_matrix, fmt='%.4f', delimiter=',')

    def manual_save(self):
        file_path = filedialog.asksaveasfilename(defaultextension=".txt")
        if file_path:
            with self.lock:
                np.savetxt(file_path, self.data_matrix, fmt='%.4f')
 

if __name__ == "__main__":
    root = tk.Tk()
    app = PressureSensorApp(root)
    root.mainloop()