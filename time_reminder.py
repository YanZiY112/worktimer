import time
import datetime
import tkinter as tk
from tkinter import ttk, messagebox
import threading
import random
import pygame
import os
import sys
import logging
import pystray
from PIL import Image, ImageDraw
import io
import json
import types  # 添加types模块支持

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('time_reminder.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)

class TimeReminder:
    def _patch_tkinter_frame_class(self):
        """修补Tkinter的Frame类，彻底禁用鼠标悬停效果"""
        try:
            # 保存原始方法
            original_tk_frame_bind = tk.Frame.bind
            original_tk_frame_configure = tk.Frame._configure
            
            # 创建新的bind方法
            def patched_frame_bind(self, sequence=None, func=None, add=None):
                # 如果是鼠标事件且不是Button，则禁用
                if sequence in ("<Enter>", "<Leave>", "<Motion>") and not isinstance(self, tk.Button):
                    # 使用一个空函数替代
                    def empty_handler(event):
                        return "break"
                    return original_tk_frame_bind(self, sequence, empty_handler, add)
                # 其他情况正常处理
                return original_tk_frame_bind(self, sequence, func, add)
            
            # 创建新的_configure方法，防止颜色变化
            def patched_frame_configure(self, cmd, cnf, kw):
                # 拦截可能导致颜色变化的配置
                if 'background' in kw and kw['background'] == '#F5F5F5':
                    kw['background'] = '#FEFFFE'  # 使用surface_elevated的颜色
                if 'bg' in kw and kw['bg'] == '#F5F5F5':
                    kw['bg'] = '#FEFFFE'
                
                # 调用原方法
                return original_tk_frame_configure(self, cmd, cnf, kw)
                
            # 替换原方法
            tk.Frame.bind = patched_frame_bind
            tk.Frame._configure = patched_frame_configure
            
            logging.info("成功修补Tkinter Frame类")
        except Exception as e:
            logging.error(f"修补Tkinter Frame类失败: {e}")
    
    def _disable_hover_feedback(self, widget):
        """禁用控件鼠标悬停反馈，避免界面变白问题"""
        def empty_event(event):
            return "break"  # 使用return "break"阻止事件继续传播
            
        # 清除可能存在的Enter和Leave事件绑定
        widget.bind("<Enter>", empty_event, "+")
        widget.bind("<Leave>", empty_event, "+")
        widget.bind("<Motion>", empty_event, "+")
        
        # 对所有子组件也应用此设置（除按钮外）
        for child in widget.winfo_children():
            if not isinstance(child, tk.Button):
                self._disable_hover_feedback(child)
                
    def __init__(self):
        """初始化应用程序"""
        # 创建主窗口
        self.root = tk.Tk()
        self.root.title("时间提醒助手")
        self.root.geometry("385x525")  # 调整为指定宽度 (缩小30%)
        self.root.minsize(375, 525)  # 调整最小尺寸 (缩小30%)
        
        # 修改Tkinter Frame类，彻底禁用鼠标悬停效果
        self._patch_tkinter_frame_class()
        
        # 全局TK样式配置 - 禁用所有Frame的悬停高亮
        self.root.option_add('*Frame.highlightBackground', '#FEFFFE')
        self.root.option_add('*Frame.highlightColor', '#FEFFFE')
        self.root.option_add('*Canvas.highlightBackground', '#FEFFFE')
        self.root.option_add('*Canvas.highlightColor', '#FEFFFE')
        self.root.option_add('*Label.highlightBackground', '#FEFFFE')
        self.root.option_add('*Label.highlightColor', '#FEFFFE')
        self.root.option_add('*Frame.takeFocus', '0')  # 禁止Frame获取焦点
        
        # 设置窗口图标
        try:
            icon_path = self.resource_path("icon.ico")
            if os.path.exists(icon_path):
                self.root.iconbitmap(icon_path)
        except Exception as e:
            logging.error(f"设置窗口图标失败: {e}")
        
        # 初始化变量
        self.is_running = False
        self.is_paused = False
        self.is_mini_window = False
        self.has_floating_window = False
        self.is_dim_screen = False
        self.is_mode_locked = False  # 添加模式锁定变量
        self.mini_window = None
        self.floating_window = None
        self.dim_window = None
        self.tray_icon = None
        self.current_session_start = None
        self.current_focus_time = 0
        self.mode_buttons = {}  # 存储模式按钮引用
        self.current_work_mode = 'study'  # 当前选中的工作模式
        
        # 时间设置
        self.total_minutes = 90
        self.interval_minutes = 15
        self.random_minutes = 2
        self.rest_minutes = 10
        self.second_reminder_delay = 10
        
        # 时间设置变量
        self.total_minutes_var = tk.StringVar(value="90")
        self.interval_minutes_var = tk.StringVar(value="15")
        self.random_minutes_var = tk.StringVar(value="2")
        self.rest_minutes_var = tk.StringVar(value="10")
        self.second_reminder_var = tk.StringVar(value="10")
        
        # 初始化统计数据
        self.daily_work_time = 0
        self.total_sessions = 0
        self.daily_stats = {}
        
        # 改进：自定义模式数据结构
        self.custom_modes = {}
        self.custom_mode_selected = None
        self.custom_mode_history = {
            "last_used": [],  # 最近使用的模式列表，按时间倒序
            "most_used": []   # 最常用的模式列表，按使用次数倒序
        }
        
        # 改进：标语系统数据结构
        self.slogan_categories = {
            "default": {
                "name": "默认分类",
                "description": "系统默认标语",
                "enabled": True,
                "created_time": datetime.datetime.now().isoformat(),
                "slogans": [
                    "放松一下眼睛，看看远处",
                    "站起来活动一下身体",
                    "深呼吸，调整一下坐姿",
                    "喝口水，补充水分",
                    "记得保持专注，你做得很棒"
                ]
            },
            "motivational": {
                "name": "激励标语",
                "description": "激励自己的标语",
                "enabled": True,
                "created_time": datetime.datetime.now().isoformat(),
                "slogans": [
                    "坚持就是胜利",
                    "今天的努力，明天的实力",
                    "每一个小进步都值得欣赏",
                    "专注当下，成就未来",
                    "不要让昨天占用太多的今天"
                ]
            }
        }
        
        # 标语设置
        self.slogan_settings = {
            "current_slogan": "放松一下眼睛，看看远处",
            "use_random": True,
            "enabled_categories": ["default", "motivational"],
            "display_style": "standard",
            "favorite_slogans": []  # 收藏的标语
        }
        
        # 兼容旧版本的标语数据
        self.dim_messages = []
        self.current_dim_message = ""
        
        self.stats_file = "work_statistics.json"  # 添加统计文件路径
        
        # 默认设置
        self.close_to_tray = tk.BooleanVar(value=True)
        self.show_seconds = tk.BooleanVar(value=True)
        self.auto_dim_screen = tk.BooleanVar(value=True)
        self.sound_enabled = tk.BooleanVar(value=True)  # 重命名为 sound_enabled
        
        # 随机标语显示设置
        self.use_random_message = tk.BooleanVar(value=True)
        
        # 功能开关变量
        self.screen_dim_enabled = tk.BooleanVar(value=True)
        self.force_screen_dim = tk.BooleanVar(value=False)
        self.mini_window_enabled = tk.BooleanVar(value=False)
        self.minimize_on_close = tk.BooleanVar(value=True)
        self.floating_enabled = tk.BooleanVar(value=True)
        self.is_minimized_to_tray = False
        
        # 初始化苹果风格
        self._init_apple_style()
        
        # 加载统计数据
        self.load_statistics()
        
        # 初始化音频
        self._init_audio()
        
        # 检查音频文件
        self.check_audio_files()
        
        # 设置键盘快捷键
        self._setup_keyboard_shortcuts()
        
        # 设置用户界面
        self._setup_ui()
        
        # 设置关闭事件处理
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        
        # 应用默认工作模式
        self._apply_default_work_mode()
        
        # 计时器相关变量
        self.start_time = None
        self.end_time = None
        self.next_reminder_time = None
        self.reminder_thread = None
        self.countdown_thread = None
        self.pause_time = None
        self.total_pause_duration = 0
        self.last_reset_time = 0  # 重置防抖时间戳
        
        logging.info("时间提醒程序初始化完成")
    
    def _test_custom_mode(self):
        """测试自定义模式功能"""
        try:
            # 创建一个测试自定义模式
            test_mode_name = "测试模式"
            test_mode_key = self.save_custom_mode(test_mode_name, 30, 10, 1, 5, 5)
            if test_mode_key:
                logging.info(f"测试自定义模式创建成功: {test_mode_key}")
                # 删除测试模式
                if self.delete_custom_mode(test_mode_key):
                    logging.info("测试自定义模式删除成功")
                else:
                    logging.error("测试自定义模式删除失败")
            else:
                logging.error("测试自定义模式创建失败")
        except Exception as e:
            logging.error(f"测试自定义模式失败: {e}")

    def _apply_default_work_mode(self):
        """应用默认工作模式设置"""
        if self.current_work_mode == 'study':
            # 应用深度学习模式的设置
            self.total_minutes_var.set("90")
            self.interval_minutes_var.set("15")
            self.random_minutes_var.set("2")
            self.rest_minutes_var.set("10")
            
            # 更新按钮状态
            if hasattr(self, 'mode_buttons'):
                self._update_mode_buttons()
            
            # 启用开始按钮并更新文本
            if hasattr(self, 'start_button'):
                self.start_button.configure(state='normal')
                self.start_button.configure(text=f"{self.icons['rocket']} 开始深度学习")

    def _update_most_used_modes(self):
        """更新最常用模式列表"""
        try:
            # 按使用次数排序
            sorted_modes = sorted(
                [(key, data.get('use_count', 0)) for key, data in self.custom_modes.items()],
                key=lambda x: x[1],
                reverse=True
            )
            
            # 更新最常用列表
            self.custom_mode_history["most_used"] = [key for key, _ in sorted_modes[:10]]
            
            logging.info("已更新最常用模式列表")
        except Exception as e:
            logging.error(f"更新最常用模式列表失败: {e}")
            
    def _record_mode_usage(self, mode_key):
        """记录模式使用情况
        
        Args:
            mode_key: 模式键值
        """
        if mode_key not in self.custom_modes:
            return
            
        # 更新使用次数和最后使用时间
        if 'use_count' not in self.custom_modes[mode_key]:
            self.custom_modes[mode_key]['use_count'] = 0
        self.custom_modes[mode_key]['use_count'] += 1
        self.custom_modes[mode_key]['last_used'] = datetime.datetime.now().isoformat()
        
        # 更新最近使用历史
        if mode_key in self.custom_mode_history["last_used"]:
            self.custom_mode_history["last_used"].remove(mode_key)
        self.custom_mode_history["last_used"].insert(0, mode_key)
        
        # 限制历史记录长度
        if len(self.custom_mode_history["last_used"]) > 10:
            self.custom_mode_history["last_used"] = self.custom_mode_history["last_used"][:10]
            
        # 更新最常用列表
        self._update_most_used_modes()
        
        # 保存统计数据
        self.save_statistics()

    def _init_apple_style(self):
        """初始化商业化苹果风格样式配置"""
        # 商业化苹果风格配色方案 - 更现代更精致
        self.colors = {
            # 主色调 - 现代苹果蓝系
            'primary': '#007AFF',
            'primary_dark': '#0051D5',
            'primary_light': '#66B3FF',
            'primary_transparent': '#CCDFFF',  # 浅蓝色代替半透明效果
            'primary_gradient_start': '#007AFF',
            'primary_gradient_end': '#5AC8FA',
            
            # 系统颜色 - 更丰富的层次
            'background': '#F8F9FA',
            'surface': '#FFFFFF',
            'surface_secondary': '#F8F9FA',
            'surface_tertiary': '#F1F3F4',
            'surface_elevated': '#FEFFFE',
            'secondary_transparent': '#F8FAFA',  # 浅灰色代替半透明效果
            'card_shadow': '#E8EAED',
            
            # 文本颜色 - 更好的对比度
            'text_primary': '#1A1A1A',
            'text_secondary': '#5F6368',
            'text_tertiary': '#9AA0A6',
            'text_quaternary': '#BDC1C6',
            'text_accent': '#1976D2',
            
            # 语义颜色 - 现代化配色
            'success': '#0F9D58',
            'success_light': '#E8F5E8',
            'warning': '#F29900',
            'warning_light': '#FFF4E5',
            'error': '#EA4335',
            'error_light': '#FFEAE8',
            'info': '#4285F4',
            'info_light': '#E8F0FE',
            'info_transparent': '#E8F0FE',  # 添加info半透明颜色
            
            # 特殊颜色 - 商业化风格
            'separator': '#E8EAED',
            'accent': '#FF6F00',
            'tint': '#007AFF',
            'premium': '#7B1FA2',
            'premium_light': '#E8D0F0',
            'gradient_bg_start': '#F8F9FA',
            'gradient_bg_end': '#FFFFFF',
            'hover': '#FEFFFE'  # 悬停效果颜色 - 改为与surface_elevated相同
        }
        
        # 现代化图标系统 - 使用专业图标符号
        self.icons = {
            'timer': '⏱',
            'play': '▶',
            'pause': '⏸',
            'stop': '⏹',
            'reset': '↻',
            'settings': '⚙',
            'stats': '📈',
            'tomato': '🔴',
            'study': '🎯',
            'work': '💼',
            'sprint': '⚡',
            'status': '📊',
            'today': '📅',
            'keyboard': '⌨',
            'close': '✕',
            'check': '✓',
            'rocket': '🚀',
            'focus': '🎯',
            'gear': '⚙'
        }
        
        # 商业化字体配置 - 更精致的字体层次 (尺寸缩小30%)
        self.fonts = {
            'brand_title': ('SF Pro Display', 17, 'bold'),
            'title_large': ('SF Pro Display', 14, 'bold'),
            'title': ('SF Pro Display', 13, 'bold'),
            'headline': ('SF Pro Display', 11, 'bold'),
            'subheadline': ('SF Pro Display', 10, 'bold'),
            'body': ('SF Pro Text', 9, 'normal'),
            'body_emphasis': ('SF Pro Text', 9, 'bold'),
            'callout': ('SF Pro Text', 8, 'normal'),
            'subhead': ('SF Pro Text', 8, 'normal'),
            'footnote': ('SF Pro Text', 7, 'normal'),
            'caption': ('SF Pro Text', 7, 'normal'),
            'timer_large': ('SF Pro Display', 25, 'bold'),
            
            # 备用字体系统
            'brand_title_fallback': ('Microsoft YaHei UI', 15, 'bold'),
            'title_large_fallback': ('Microsoft YaHei UI', 13, 'bold'),
            'title_fallback': ('Microsoft YaHei UI', 11, 'bold'),
            'headline_fallback': ('Microsoft YaHei UI', 11, 'bold'),
            'subheadline_fallback': ('Microsoft YaHei UI', 9, 'bold'),
            'body_fallback': ('Microsoft YaHei UI', 8, 'normal'),
            'body_emphasis_fallback': ('Microsoft YaHei UI', 8, 'bold'),
            'callout_fallback': ('Microsoft YaHei UI', 8, 'normal'),
            'subhead_fallback': ('Microsoft YaHei UI', 7, 'normal'),
            'footnote_fallback': ('Microsoft YaHei UI', 7, 'normal'),
            'caption_fallback': ('Microsoft YaHei UI', 6, 'normal'),
            'timer_large_fallback': ('Microsoft YaHei UI', 22, 'bold')
        }
        
        # 尝试获取最佳字体
        self.current_fonts = self._get_best_fonts()
        
        # 现代化尺寸和间距系统 (尺寸缩小30%)
        self.dimensions = {
            # 圆角系统
            'corner_radius': 11,
            'corner_radius_small': 8,
            'corner_radius_large': 14,
            'corner_radius_button': 10,
            
            # 间距系统
            'spacing_xs': 3,
            'spacing_s': 6,
            'spacing_m': 11,
            'spacing_l': 17,
            'spacing_xl': 22,
            'spacing_xxl': 34,
            
            # 组件尺寸
            'button_height': 34,
            'button_height_small': 25,
            'card_padding': 17,
            'section_spacing': 28,
            
            # 阴影系统
            'shadow_offset': 1,
            'shadow_blur': 6,
            'shadow_elevation': 3
        }
        
        # 动画和效果配置
        self.animations = {
            'transition_duration': 200,
            'hover_scale': 1.02,
            'click_scale': 0.98,
            'fade_duration': 300
        }

    def _get_best_fonts(self):
        """获取最佳可用字体"""
        import tkinter.font as tkFont
        available_fonts = tkFont.families()
        
        # 检查是否有SF Pro字体
        has_sf_pro = any('SF Pro' in font for font in available_fonts)
        
        if has_sf_pro:
            return {
                'brand_title': self.fonts['brand_title'],
                'title_large': self.fonts['title_large'],
                'title': self.fonts['title'],
                'headline': self.fonts['headline'],
                'subheadline': self.fonts['subheadline'],
                'body': self.fonts['body'],
                'body_emphasis': self.fonts['body_emphasis'],
                'callout': self.fonts['callout'],
                'subhead': self.fonts['subhead'],
                'footnote': self.fonts['footnote'],
                'caption': self.fonts['caption'],
                'timer_large': self.fonts['timer_large']
            }
        else:
            return {
                'brand_title': self.fonts['brand_title_fallback'],
                'title_large': self.fonts['title_large_fallback'],
                'title': self.fonts['title_fallback'],
                'headline': self.fonts['headline_fallback'],
                'subheadline': self.fonts['subheadline_fallback'],
                'body': self.fonts['body_fallback'],
                'body_emphasis': self.fonts['body_emphasis_fallback'],
                'callout': self.fonts['callout_fallback'],
                'subhead': self.fonts['subhead_fallback'],
                'footnote': self.fonts['footnote_fallback'],
                'caption': self.fonts['caption_fallback'],
                'timer_large': self.fonts['timer_large_fallback']
            }

    def _create_apple_button(self, parent, text, command=None, style='primary', width=None, icon=None):
        """创建现代化商业苹果风格按钮"""
        # 样式配置字典
        style_configs = {
            'primary': {
                'bg': self.colors['primary'],
                'fg': 'white',
                'active_bg': self.colors['primary_dark'],
                'hover_bg': self.colors['primary_light'],
                'font': self.current_fonts['body_emphasis'] if 'body_emphasis' in self.current_fonts else self.current_fonts['body']
            },
            'secondary': {
                'bg': self.colors['surface_elevated'],
                'fg': self.colors['text_primary'],
                'active_bg': self.colors['surface_tertiary'],
                'hover_bg': self.colors['surface_secondary'],
                'font': self.current_fonts['body']
            },
            'success': {
                'bg': self.colors['success'],
                'fg': 'white',
                'active_bg': '#0A7C47',
                'hover_bg': '#12B669',
                'font': self.current_fonts['body_emphasis'] if 'body_emphasis' in self.current_fonts else self.current_fonts['body']
            },
            'warning': {
                'bg': self.colors['warning'],
                'fg': 'white',
                'active_bg': '#E08900',
                'hover_bg': '#FFB74D',
                'font': self.current_fonts['body_emphasis'] if 'body_emphasis' in self.current_fonts else self.current_fonts['body']
            },
            'error': {
                'bg': self.colors['error'],
                'fg': 'white',
                'active_bg': '#D23B2F',
                'hover_bg': '#F05545',
                'font': self.current_fonts['body_emphasis'] if 'body_emphasis' in self.current_fonts else self.current_fonts['body']
            }
        }
        
        config = style_configs.get(style, style_configs['primary'])
        
        # 处理图标和文本
        button_text = text
        if icon and icon in self.icons:
            button_text = f"{self.icons[icon]} {text}"
        elif icon:
            button_text = f"{icon} {text}"
        
        button = tk.Button(
            parent,
            text=button_text,
            command=command,
            font=config['font'],
            fg=config['fg'],
            bg=config['bg'],
            activebackground=config['active_bg'],
            activeforeground=config['fg'],
            relief='flat',
            bd=0,
            padx=self.dimensions['spacing_m'],
            pady=self.dimensions['spacing_s'] + 2,  # 稍微增加垂直间距
            cursor='hand2',
            width=width
        )
        
        # 现代化交互效果
        original_bg = config['bg']
        hover_bg = config['hover_bg']
        active_bg = config['active_bg']
        
        def on_enter(e):
            button.configure(bg=hover_bg)
            
        def on_leave(e):
            button.configure(bg=original_bg)
            
        def on_press(e):
            button.configure(bg=active_bg)
            
        def on_release(e):
            # 检查鼠标是否还在按钮范围内
            x, y = e.x, e.y
            if 0 <= x <= button.winfo_width() and 0 <= y <= button.winfo_height():
                button.configure(bg=hover_bg)
            else:
                button.configure(bg=original_bg)
        
        button.bind('<Enter>', on_enter)
        button.bind('<Leave>', on_leave)
        button.bind('<Button-1>', on_press)
        button.bind('<ButtonRelease-1>', on_release)
        
        return button

    def _create_apple_card(self, parent, bg_color=None, elevated=True):
        """创建现代化苹果风格卡片容器"""
        if bg_color is None:
            bg_color = self.colors['surface_elevated'] if elevated else self.colors['surface']
        
        # 创建外层容器用于阴影效果模拟
        container = tk.Frame(parent, bg=self.colors['background'])
        
        # 创建卡片主体
        card = tk.Frame(
            container,
            bg=bg_color,
            relief='flat',
            bd=0,
            padx=self.dimensions['card_padding']*0.7,  # 减小内边距
            pady=self.dimensions['card_padding']*0.7,  # 减小内边距
            takefocus=0  # 禁止获取焦点
        )
        card.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)
        
        # 如果需要立体效果，添加边框模拟阴影
        if elevated:
            # 创建微妙的边框效果
            card.configure(highlightthickness=1, highlightcolor=self.colors['card_shadow'], highlightbackground=self.colors['card_shadow'])
        
        # 禁止卡片响应鼠标悬停事件，防止变白
        def block_hover(event):
            return "break"
            
        card.bind("<Enter>", block_hover, "+")
        card.bind("<Leave>", block_hover, "+")
        card.bind("<Motion>", block_hover, "+")
        
        return container

    def _create_preset_modes_frame(self, parent):
        """创建预设模式区域"""
        # 创建预设模式容器
        modes_container = tk.Frame(parent, bg=self.colors['background'])
        modes_container.pack(fill=tk.X, padx=(self.dimensions['spacing_s'], self.dimensions['spacing_s']), pady=self.dimensions['spacing_s'])
        
        # 预设模式卡片
        modes_card = self._create_apple_card(modes_container, elevated=True)
        modes_card.pack(fill=tk.X)
        
        # 设置最大宽度
        modes_container.configure(width=390)
        
        # 获取实际的卡片框架
        card_frame = modes_card.winfo_children()[0]
        
        # 标题区域
        title_frame = tk.Frame(card_frame, bg=self.colors['surface_elevated'])
        title_frame.pack(fill=tk.X, pady=(0, self.dimensions['spacing_s']))
        
        # 模式选择标题
        modes_title = tk.Label(
            title_frame,
            text=f"{self.icons['mode']} 选择工作模式",
            font=self.current_fonts['callout'],
            fg=self.colors['text_primary'],
            bg=self.colors['surface_elevated']
        )
        modes_title.pack()
        
        # 模式按钮网格
        modes_grid = tk.Frame(card_frame, bg=self.colors['surface_elevated'])
        modes_grid.pack(fill=tk.X)
        
        # 第一行（番茄钟和深度学习）
        row1 = tk.Frame(modes_grid, bg=self.colors['surface_elevated'])
        row1.pack(fill=tk.X, pady=(0, 5))
        
        # 番茄钟
import time
import datetime
import tkinter as tk
from tkinter import ttk, messagebox
import threading
import random
import pygame
import os
import sys
import logging
import pystray
from PIL import Image, ImageDraw
import io
import json
import types  # 添加types模块支持

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('time_reminder.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)

class TimeReminder:
    def _patch_tkinter_frame_class(self):
        """修补Tkinter的Frame类，彻底禁用鼠标悬停效果"""
        try:
            # 保存原始方法
            original_tk_frame_bind = tk.Frame.bind
            original_tk_frame_configure = tk.Frame._configure
            
            # 创建新的bind方法
            def patched_frame_bind(self, sequence=None, func=None, add=None):
                # 如果是鼠标事件且不是Button，则禁用
                if sequence in ("<Enter>", "<Leave>", "<Motion>") and not isinstance(self, tk.Button):
                    # 使用一个空函数替代
                    def empty_handler(event):
                        return "break"
                    return original_tk_frame_bind(self, sequence, empty_handler, add)
                # 其他情况正常处理
                return original_tk_frame_bind(self, sequence, func, add)
            
            # 创建新的_configure方法，防止颜色变化
            def patched_frame_configure(self, cmd, cnf, kw):
                # 拦截可能导致颜色变化的配置
                if 'background' in kw and kw['background'] == '#F5F5F5':
                    kw['background'] = '#FEFFFE'  # 使用surface_elevated的颜色
                if 'bg' in kw and kw['bg'] == '#F5F5F5':
                    kw['bg'] = '#FEFFFE'
                
                # 调用原方法
                return original_tk_frame_configure(self, cmd, cnf, kw)
                
            # 替换原方法
            tk.Frame.bind = patched_frame_bind
            tk.Frame._configure = patched_frame_configure
            
            logging.info("成功修补Tkinter Frame类")
        except Exception as e:
            logging.error(f"修补Tkinter Frame类失败: {e}")
    
    def _disable_hover_feedback(self, widget):
        """禁用控件鼠标悬停反馈，避免界面变白问题"""
        def empty_event(event):
            return "break"  # 使用return "break"阻止事件继续传播
            
        # 清除可能存在的Enter和Leave事件绑定
        widget.bind("<Enter>", empty_event, "+")
        widget.bind("<Leave>", empty_event, "+")
        widget.bind("<Motion>", empty_event, "+")
        
        # 对所有子组件也应用此设置（除按钮外）
        for child in widget.winfo_children():
            if not isinstance(child, tk.Button):
                self._disable_hover_feedback(child)
                
    def __init__(self):
        """初始化应用程序"""
        # 创建主窗口
        self.root = tk.Tk()
        self.root.title("时间提醒助手")
        self.root.geometry("385x525")  # 调整为指定宽度 (缩小30%)
        self.root.minsize(375, 525)  # 调整最小尺寸 (缩小30%)
        
        # 修改Tkinter Frame类，彻底禁用鼠标悬停效果
        self._patch_tkinter_frame_class()
        
        # 全局TK样式配置 - 禁用所有Frame的悬停高亮
        self.root.option_add('*Frame.highlightBackground', '#FEFFFE')
        self.root.option_add('*Frame.highlightColor', '#FEFFFE')
        self.root.option_add('*Canvas.highlightBackground', '#FEFFFE')
        self.root.option_add('*Canvas.highlightColor', '#FEFFFE')
        self.root.option_add('*Label.highlightBackground', '#FEFFFE')
        self.root.option_add('*Label.highlightColor', '#FEFFFE')
        self.root.option_add('*Frame.takeFocus', '0')  # 禁止Frame获取焦点
        
        # 设置窗口图标
        try:
            icon_path = self.resource_path("icon.ico")
            if os.path.exists(icon_path):
                self.root.iconbitmap(icon_path)
        except Exception as e:
            logging.error(f"设置窗口图标失败: {e}")
        
        # 初始化变量
        self.is_running = False
        self.is_paused = False
        self.is_mini_window = False
        self.has_floating_window = False
        self.is_dim_screen = False
        self.is_mode_locked = False  # 添加模式锁定变量
        self.mini_window = None
        self.floating_window = None
        self.dim_window = None
        self.tray_icon = None
        self.current_session_start = None
        self.current_focus_time = 0
        self.mode_buttons = {}  # 存储模式按钮引用
        self.current_work_mode = 'study'  # 当前选中的工作模式
        
        # 时间设置
        self.total_minutes = 90
        self.interval_minutes = 15
        self.random_minutes = 2
        self.rest_minutes = 10
        self.second_reminder_delay = 10
        
        # 时间设置变量
        self.total_minutes_var = tk.StringVar(value="90")
        self.interval_minutes_var = tk.StringVar(value="15")
        self.random_minutes_var = tk.StringVar(value="2")
        self.rest_minutes_var = tk.StringVar(value="10")
        self.second_reminder_var = tk.StringVar(value="10")
        
        # 初始化统计数据
        self.daily_work_time = 0
        self.total_sessions = 0
        self.daily_stats = {}
        
        # 改进：自定义模式数据结构
        self.custom_modes = {}
        self.custom_mode_selected = None
        self.custom_mode_history = {
            "last_used": [],  # 最近使用的模式列表，按时间倒序
            "most_used": []   # 最常用的模式列表，按使用次数倒序
        }
        
        # 改进：标语系统数据结构
        self.slogan_categories = {
            "default": {
                "name": "默认分类",
                "description": "系统默认标语",
                "enabled": True,
                "created_time": datetime.datetime.now().isoformat(),
                "slogans": [
                    "放松一下眼睛，看看远处",
                    "站起来活动一下身体",
                    "深呼吸，调整一下坐姿",
                    "喝口水，补充水分",
                    "记得保持专注，你做得很棒"
                ]
            },
            "motivational": {
                "name": "激励标语",
                "description": "激励自己的标语",
                "enabled": True,
                "created_time": datetime.datetime.now().isoformat(),
                "slogans": [
                    "坚持就是胜利",
                    "今天的努力，明天的实力",
                    "每一个小进步都值得欣赏",
                    "专注当下，成就未来",
                    "不要让昨天占用太多的今天"
                ]
            }
        }
        
        # 标语设置
        self.slogan_settings = {
            "current_slogan": "放松一下眼睛，看看远处",
            "use_random": True,
            "enabled_categories": ["default", "motivational"],
            "display_style": "standard",
            "favorite_slogans": []  # 收藏的标语
        }
        
        # 兼容旧版本的标语数据
        self.dim_messages = []
        self.current_dim_message = ""
        
        self.stats_file = "work_statistics.json"  # 添加统计文件路径
        
        # 默认设置
        self.close_to_tray = tk.BooleanVar(value=True)
        self.show_seconds = tk.BooleanVar(value=True)
        self.auto_dim_screen = tk.BooleanVar(value=True)
        self.sound_enabled = tk.BooleanVar(value=True)  # 重命名为 sound_enabled
        
        # 随机标语显示设置
        self.use_random_message = tk.BooleanVar(value=True)
        
        # 功能开关变量
        self.screen_dim_enabled = tk.BooleanVar(value=True)
        self.force_screen_dim = tk.BooleanVar(value=False)
        self.mini_window_enabled = tk.BooleanVar(value=False)
        self.minimize_on_close = tk.BooleanVar(value=True)
        self.floating_enabled = tk.BooleanVar(value=True)
        self.is_minimized_to_tray = False
        
        # 初始化苹果风格
        self._init_apple_style()
        
        # 加载统计数据
        self.load_statistics()
        
        # 初始化音频
        self._init_audio()
        
        # 检查音频文件
        self.check_audio_files()
        
        # 设置键盘快捷键
        self._setup_keyboard_shortcuts()
        
        # 设置用户界面
        self._setup_ui()
        
        # 设置关闭事件处理
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        
        # 应用默认工作模式
        self._apply_default_work_mode()
        
        # 计时器相关变量
        self.start_time = None
        self.end_time = None
        self.next_reminder_time = None
        self.reminder_thread = None
        self.countdown_thread = None
        self.pause_time = None
        self.total_pause_duration = 0
        self.last_reset_time = 0  # 重置防抖时间戳
        
        logging.info("时间提醒程序初始化完成")
    
    def _test_custom_mode(self):
        """测试自定义模式功能"""
        try:
            # 创建一个测试自定义模式
            test_mode_name = "测试模式"
            test_mode_key = self.save_custom_mode(test_mode_name, 30, 10, 1, 5, 5)
            if test_mode_key:
                logging.info(f"测试自定义模式创建成功: {test_mode_key}")
                # 删除测试模式
                if self.delete_custom_mode(test_mode_key):
                    logging.info("测试自定义模式删除成功")
                else:
                    logging.error("测试自定义模式删除失败")
            else:
                logging.error("测试自定义模式创建失败")
        except Exception as e:
            logging.error(f"测试自定义模式失败: {e}")

    def _apply_default_work_mode(self):
        """应用默认工作模式设置"""
        if self.current_work_mode == 'study':
            # 应用深度学习模式的设置
            self.total_minutes_var.set("90")
            self.interval_minutes_var.set("15")
            self.random_minutes_var.set("2")
            self.rest_minutes_var.set("10")
            
            # 更新按钮状态
            if hasattr(self, 'mode_buttons'):
                self._update_mode_buttons()
            
            # 启用开始按钮并更新文本
            if hasattr(self, 'start_button'):
                self.start_button.configure(state='normal')
                self.start_button.configure(text=f"{self.icons['rocket']} 开始深度学习")

    def _update_most_used_modes(self):
        """更新最常用模式列表"""
        try:
            # 按使用次数排序
            sorted_modes = sorted(
                [(key, data.get('use_count', 0)) for key, data in self.custom_modes.items()],
                key=lambda x: x[1],
                reverse=True
            )
            
            # 更新最常用列表
            self.custom_mode_history["most_used"] = [key for key, _ in sorted_modes[:10]]
            
            logging.info("已更新最常用模式列表")
        except Exception as e:
            logging.error(f"更新最常用模式列表失败: {e}")
            
    def _record_mode_usage(self, mode_key):
        """记录模式使用情况
        
        Args:
            mode_key: 模式键值
        """
        if mode_key not in self.custom_modes:
            return
            
        # 更新使用次数和最后使用时间
        if 'use_count' not in self.custom_modes[mode_key]:
            self.custom_modes[mode_key]['use_count'] = 0
        self.custom_modes[mode_key]['use_count'] += 1
        self.custom_modes[mode_key]['last_used'] = datetime.datetime.now().isoformat()
        
        # 更新最近使用历史
        if mode_key in self.custom_mode_history["last_used"]:
            self.custom_mode_history["last_used"].remove(mode_key)
        self.custom_mode_history["last_used"].insert(0, mode_key)
        
        # 限制历史记录长度
        if len(self.custom_mode_history["last_used"]) > 10:
            self.custom_mode_history["last_used"] = self.custom_mode_history["last_used"][:10]
            
        # 更新最常用列表
        self._update_most_used_modes()
        
        # 保存统计数据
        self.save_statistics()

    def _init_apple_style(self):
        """初始化商业化苹果风格样式配置"""
        # 商业化苹果风格配色方案 - 更现代更精致
        self.colors = {
            # 主色调 - 现代苹果蓝系
            'primary': '#007AFF',
            'primary_dark': '#0051D5',
            'primary_light': '#66B3FF',
            'primary_transparent': '#CCDFFF',  # 浅蓝色代替半透明效果
            'primary_gradient_start': '#007AFF',
            'primary_gradient_end': '#5AC8FA',
            
            # 系统颜色 - 更丰富的层次
            'background': '#F8F9FA',
            'surface': '#FFFFFF',
            'surface_secondary': '#F8F9FA',
            'surface_tertiary': '#F1F3F4',
            'surface_elevated': '#FEFFFE',
            'secondary_transparent': '#F8FAFA',  # 浅灰色代替半透明效果
            'card_shadow': '#E8EAED',
            
            # 文本颜色 - 更好的对比度
            'text_primary': '#1A1A1A',
            'text_secondary': '#5F6368',
            'text_tertiary': '#9AA0A6',
            'text_quaternary': '#BDC1C6',
            'text_accent': '#1976D2',
            
            # 语义颜色 - 现代化配色
            'success': '#0F9D58',
            'success_light': '#E8F5E8',
            'warning': '#F29900',
            'warning_light': '#FFF4E5',
            'error': '#EA4335',
            'error_light': '#FFEAE8',
            'info': '#4285F4',
            'info_light': '#E8F0FE',
            'info_transparent': '#E8F0FE',  # 添加info半透明颜色
            
            # 特殊颜色 - 商业化风格
            'separator': '#E8EAED',
            'accent': '#FF6F00',
            'tint': '#007AFF',
            'premium': '#7B1FA2',
            'premium_light': '#E8D0F0',
            'gradient_bg_start': '#F8F9FA',
            'gradient_bg_end': '#FFFFFF',
            'hover': '#FEFFFE'  # 悬停效果颜色 - 改为与surface_elevated相同
        }
        
        # 现代化图标系统 - 使用专业图标符号
        self.icons = {
            'timer': '⏱',
            'play': '▶',
            'pause': '⏸',
            'stop': '⏹',
            'reset': '↻',
            'settings': '⚙',
            'stats': '📈',
            'tomato': '🔴',
            'study': '🎯',
            'work': '💼',
            'sprint': '⚡',
            'status': '📊',
            'today': '📅',
            'keyboard': '⌨',
            'close': '✕',
            'check': '✓',
            'rocket': '🚀',
            'focus': '🎯',
            'gear': '⚙'
        }
        
        # 商业化字体配置 - 更精致的字体层次 (尺寸缩小30%)
        self.fonts = {
            'brand_title': ('SF Pro Display', 17, 'bold'),
            'title_large': ('SF Pro Display', 14, 'bold'),
            'title': ('SF Pro Display', 13, 'bold'),
            'headline': ('SF Pro Display', 11, 'bold'),
            'subheadline': ('SF Pro Display', 10, 'bold'),
            'body': ('SF Pro Text', 9, 'normal'),
            'body_emphasis': ('SF Pro Text', 9, 'bold'),
            'callout': ('SF Pro Text', 8, 'normal'),
            'subhead': ('SF Pro Text', 8, 'normal'),
            'footnote': ('SF Pro Text', 7, 'normal'),
            'caption': ('SF Pro Text', 7, 'normal'),
            'timer_large': ('SF Pro Display', 25, 'bold'),
            
            # 备用字体系统
            'brand_title_fallback': ('Microsoft YaHei UI', 15, 'bold'),
            'title_large_fallback': ('Microsoft YaHei UI', 13, 'bold'),
            'title_fallback': ('Microsoft YaHei UI', 11, 'bold'),
            'headline_fallback': ('Microsoft YaHei UI', 11, 'bold'),
            'subheadline_fallback': ('Microsoft YaHei UI', 9, 'bold'),
            'body_fallback': ('Microsoft YaHei UI', 8, 'normal'),
            'body_emphasis_fallback': ('Microsoft YaHei UI', 8, 'bold'),
            'callout_fallback': ('Microsoft YaHei UI', 8, 'normal'),
            'subhead_fallback': ('Microsoft YaHei UI', 7, 'normal'),
            'footnote_fallback': ('Microsoft YaHei UI', 7, 'normal'),
            'caption_fallback': ('Microsoft YaHei UI', 6, 'normal'),
            'timer_large_fallback': ('Microsoft YaHei UI', 22, 'bold')
        }
        
        # 尝试获取最佳字体
        self.current_fonts = self._get_best_fonts()
        
        # 现代化尺寸和间距系统 (尺寸缩小30%)
        self.dimensions = {
            # 圆角系统
            'corner_radius': 11,
            'corner_radius_small': 8,
            'corner_radius_large': 14,
            'corner_radius_button': 10,
            
            # 间距系统
            'spacing_xs': 3,
            'spacing_s': 6,
            'spacing_m': 11,
            'spacing_l': 17,
            'spacing_xl': 22,
            'spacing_xxl': 34,
            
            # 组件尺寸
            'button_height': 34,
            'button_height_small': 25,
            'card_padding': 17,
            'section_spacing': 28,
            
            # 阴影系统
            'shadow_offset': 1,
            'shadow_blur': 6,
            'shadow_elevation': 3
        }
        
        # 动画和效果配置
        self.animations = {
            'transition_duration': 200,
            'hover_scale': 1.02,
            'click_scale': 0.98,
            'fade_duration': 300
        }

    def _get_best_fonts(self):
        """获取最佳可用字体"""
        import tkinter.font as tkFont
        available_fonts = tkFont.families()
        
        # 检查是否有SF Pro字体
        has_sf_pro = any('SF Pro' in font for font in available_fonts)
        
        if has_sf_pro:
            return {
                'brand_title': self.fonts['brand_title'],
                'title_large': self.fonts['title_large'],
                'title': self.fonts['title'],
                'headline': self.fonts['headline'],
                'subheadline': self.fonts['subheadline'],
                'body': self.fonts['body'],
                'body_emphasis': self.fonts['body_emphasis'],
                'callout': self.fonts['callout'],
                'subhead': self.fonts['subhead'],
                'footnote': self.fonts['footnote'],
                'caption': self.fonts['caption'],
                'timer_large': self.fonts['timer_large']
            }
        else:
            return {
                'brand_title': self.fonts['brand_title_fallback'],
                'title_large': self.fonts['title_large_fallback'],
                'title': self.fonts['title_fallback'],
                'headline': self.fonts['headline_fallback'],
                'subheadline': self.fonts['subheadline_fallback'],
                'body': self.fonts['body_fallback'],
                'body_emphasis': self.fonts['body_emphasis_fallback'],
                'callout': self.fonts['callout_fallback'],
                'subhead': self.fonts['subhead_fallback'],
                'footnote': self.fonts['footnote_fallback'],
                'caption': self.fonts['caption_fallback'],
                'timer_large': self.fonts['timer_large_fallback']
            }

    def _create_apple_button(self, parent, text, command=None, style='primary', width=None, icon=None):
        """创建现代化商业苹果风格按钮"""
        # 样式配置字典
        style_configs = {
            'primary': {
                'bg': self.colors['primary'],
                'fg': 'white',
                'active_bg': self.colors['primary_dark'],
                'hover_bg': self.colors['primary_light'],
                'font': self.current_fonts['body_emphasis'] if 'body_emphasis' in self.current_fonts else self.current_fonts['body']
            },
            'secondary': {
                'bg': self.colors['surface_elevated'],
                'fg': self.colors['text_primary'],
                'active_bg': self.colors['surface_tertiary'],
                'hover_bg': self.colors['surface_secondary'],
                'font': self.current_fonts['body']
            },
            'success': {
                'bg': self.colors['success'],
                'fg': 'white',
                'active_bg': '#0A7C47',
                'hover_bg': '#12B669',
                'font': self.current_fonts['body_emphasis'] if 'body_emphasis' in self.current_fonts else self.current_fonts['body']
            },
            'warning': {
                'bg': self.colors['warning'],
                'fg': 'white',
                'active_bg': '#E08900',
                'hover_bg': '#FFB74D',
                'font': self.current_fonts['body_emphasis'] if 'body_emphasis' in self.current_fonts else self.current_fonts['body']
            },
            'error': {
                'bg': self.colors['error'],
                'fg': 'white',
                'active_bg': '#D23B2F',
                'hover_bg': '#F05545',
                'font': self.current_fonts['body_emphasis'] if 'body_emphasis' in self.current_fonts else self.current_fonts['body']
            }
        }
        
        config = style_configs.get(style, style_configs['primary'])
        
        # 处理图标和文本
        button_text = text
        if icon and icon in self.icons:
            button_text = f"{self.icons[icon]} {text}"
        elif icon:
            button_text = f"{icon} {text}"
        
        button = tk.Button(
            parent,
            text=button_text,
            command=command,
            font=config['font'],
            fg=config['fg'],
            bg=config['bg'],
            activebackground=config['active_bg'],
            activeforeground=config['fg'],
            relief='flat',
            bd=0,
            padx=self.dimensions['spacing_m'],
            pady=self.dimensions['spacing_s'] + 2,  # 稍微增加垂直间距
            cursor='hand2',
            width=width
        )
        
        # 现代化交互效果
        original_bg = config['bg']
        hover_bg = config['hover_bg']
        active_bg = config['active_bg']
        
        def on_enter(e):
            button.configure(bg=hover_bg)
            
        def on_leave(e):
            button.configure(bg=original_bg)
            
        def on_press(e):
            button.configure(bg=active_bg)
            
        def on_release(e):
            # 检查鼠标是否还在按钮范围内
            x, y = e.x, e.y
            if 0 <= x <= button.winfo_width() and 0 <= y <= button.winfo_height():
                button.configure(bg=hover_bg)
            else:
                button.configure(bg=original_bg)
        
        button.bind('<Enter>', on_enter)
        button.bind('<Leave>', on_leave)
        button.bind('<Button-1>', on_press)
        button.bind('<ButtonRelease-1>', on_release)
        
        return button

    def _create_apple_card(self, parent, bg_color=None, elevated=True):
        """创建现代化苹果风格卡片容器"""
        if bg_color is None:
            bg_color = self.colors['surface_elevated'] if elevated else self.colors['surface']
        
        # 创建外层容器用于阴影效果模拟
        container = tk.Frame(parent, bg=self.colors['background'])
        
        # 创建卡片主体
        card = tk.Frame(
            container,
            bg=bg_color,
            relief='flat',
            bd=0,
            padx=self.dimensions['card_padding']*0.7,  # 减小内边距
            pady=self.dimensions['card_padding']*0.7,  # 减小内边距
            takefocus=0  # 禁止获取焦点
        )
        card.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)
        
        # 如果需要立体效果，添加边框模拟阴影
        if elevated:
            # 创建微妙的边框效果
            card.configure(highlightthickness=1, highlightcolor=self.colors['card_shadow'], highlightbackground=self.colors['card_shadow'])
        
        # 禁止卡片响应鼠标悬停事件，防止变白
        def block_hover(event):
            return "break"
            
        card.bind("<Enter>", block_hover, "+")
        card.bind("<Leave>", block_hover, "+")
        card.bind("<Motion>", block_hover, "+")
        
        return container

    def _create_preset_modes_frame(self, parent):
        """创建预设模式区域"""
        # 创建预设模式容器
        modes_container = tk.Frame(parent, bg=self.colors['background'])
        modes_container.pack(fill=tk.X, padx=(self.dimensions['spacing_s'], self.dimensions['spacing_s']), pady=self.dimensions['spacing_s'])
        
        # 预设模式卡片
        modes_card = self._create_apple_card(modes_container, elevated=True)
        modes_card.pack(fill=tk.X)
        
        # 设置最大宽度
        modes_container.configure(width=390)
        
        # 获取实际的卡片框架
        card_frame = modes_card.winfo_children()[0]
        
        # 标题区域
        title_frame = tk.Frame(card_frame, bg=self.colors['surface_elevated'])
        title_frame.pack(fill=tk.X, pady=(0, self.dimensions['spacing_s']))
        
        # 模式选择标题
        modes_title = tk.Label(
            title_frame,
            text=f"{self.icons['mode'] if 'mode' in self.icons else '🔄'} 选择工作模式",
            font=self.current_fonts['callout'],
            fg=self.colors['text_primary'],
            bg=self.colors['surface_elevated']
        )
        modes_title.pack()
        
        # 模式按钮网格
        modes_grid = tk.Frame(card_frame, bg=self.colors['surface_elevated'])
        modes_grid.pack(fill=tk.X)
        
        # 第一行（番茄钟和深度学习）
        row1 = tk.Frame(modes_grid, bg=self.colors['surface_elevated'])
        row1.pack(fill=tk.X, pady=(0, 5))
        
        # 番茄钟
        tomato_btn = self._create_apple_button(
            row1,
            text="番茄工作法",
            command=lambda: self._select_work_mode('tomato'),
            style='secondary',
            icon='tomato'
        )
        tomato_btn.configure(
            bg=self.colors['error_light'],
            fg=self.colors['error'],
            activebackground='#FFD0D0',
            width=12,  # 设置固定宽度
            height=2   # 设置固定高度
        )
        tomato_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10))
        
        # 深度学习
        study_btn = self._create_apple_button(
            row1,
            text="深度学习",
            command=lambda: self._select_work_mode('study'),
            style='secondary',
            icon='study'
        )
        study_btn.configure(
            bg=self.colors['info_light'],
            fg=self.colors['info'],
            activebackground='#D0E0FF',
            width=12,  # 设置固定宽度
            height=2   # 设置固定高度
        )
        study_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(10, 0))
        
        # 第二行（办公和冲刺）
        row2 = tk.Frame(modes_grid, bg=self.colors['surface_elevated'])
        row2.pack(fill=tk.X, pady=(5, 5))
        
        # 办公模式
        work_btn = self._create_apple_button(
            row2,
            text="办公模式",
            command=lambda: self._select_work_mode('work'),
            style='secondary',
            icon='work'
        )
        work_btn.configure(
            bg=self.colors['success_light'],
            fg=self.colors['success'],
            activebackground='#D0E8D0',
            width=12,  # 设置固定宽度
            height=2   # 设置固定高度
        )
        work_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10))
        
        # 快速冲刺
        sprint_btn = self._create_apple_button(
            row2,
            text="快速冲刺",
            command=lambda: self._select_work_mode('sprint'),
            style='secondary',
            icon='sprint'
        )
        sprint_btn.configure(
            bg=self.colors['warning_light'],
            fg=self.colors['warning'],
            activebackground='#FFE5CC',
            width=12,  # 设置固定宽度
            height=2   # 设置固定高度
        )
        sprint_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(10, 0))
        
        # 第三行（自定义模式）
        row3 = tk.Frame(modes_grid, bg=self.colors['surface_elevated'])
        row3.pack(fill=tk.X, pady=(5, 0))
        
        # 自定义模式按钮
        custom_btn = self._create_apple_button(
            row3,
            text="自定义模式",
            command=self._select_custom_mode,
            style='secondary',
            icon='gear'
        )
        custom_btn.configure(
            bg=self.colors['premium_light'] if hasattr(self.colors, 'premium_light') else '#E8D0F0',
            fg=self.colors['premium'],
            activebackground='#D0C0E0',
            width=12,  # 设置固定宽度
            height=2   # 设置固定高度
        )
        custom_btn.pack(fill=tk.X, expand=True)
        
        # 保存按钮引用，用于更新状态
        self.mode_buttons = {
            'tomato': tomato_btn,
            'study': study_btn,
            'work': work_btn,
            'sprint': sprint_btn
        }
        
        return modes_container

    def _create_status_frame(self, parent):
        """创建状态区域"""
        status_frame = self._create_apple_card(parent, bg_color=self.colors['surface_elevated'], elevated=True)
        
        # 创建状态标签
        status_labels = {
            'total_time': {'label': None, 'value': None},
            'remaining_time': {'label': None, 'value': None},
            'focus_time': {'label': None, 'value': None},
            'sessions': {'label': None, 'value': None}
        }
        
        for i, (key, data) in enumerate(status_labels.items()):
            label = tk.Label(
                status_frame,
                text=f"{self.icons['status']} {self._get_status_label_text(key)}",
                font=self.current_fonts['body'],
                fg=self.colors['text_primary'],
                bg=self.colors['surface_elevated'],
                anchor='w',
                width=12,
                takefocus=0  # 禁止获取焦点
            )
            label.grid(row=i, column=0, padx=self.dimensions['spacing_m'], pady=self.dimensions['spacing_s'], sticky='w')
            
            value = tk.Label(
                status_frame,
                text=self._get_status_value_text(key),
                font=self.current_fonts['body_emphasis'],
                fg=self.colors['text_primary'],
                bg=self.colors['surface_elevated'],
                anchor='e',
                width=12,
                takefocus=0  # 禁止获取焦点
            )
            value.grid(row=i, column=1, padx=self.dimensions['spacing_m'], pady=self.dimensions['spacing_s'], sticky='e')
            
            data['label'] = label
            data['value'] = value
        
        # 更新状态标签的宽度
        for data in status_labels.values():
            data['label'].config(width=12)
            data['value'].config(width=12)
        
        return status_frame

    def _create_control_frame(self, parent):
        """创建控制区域"""
        control_frame = self._create_apple_card(parent, bg_color=self.colors['surface_elevated'], elevated=True)
        
        # 创建控制按钮
        self.start_button = self._create_apple_button(
            control_frame,
            text=f"{self.icons['play']} 开始",
            command=self.start_timer,
            style='primary',
            width=10
        )
        self.start_button.pack(side=tk.LEFT, padx=self.dimensions['spacing_m'], pady=self.dimensions['spacing_m'])
        
        self.pause_button = self._create_apple_button(
            control_frame,
            text=f"{self.icons['pause']} 暂停",
            command=self.pause_timer,
            style='secondary',
            width=10
        )
        self.pause_button.pack(side=tk.LEFT, padx=self.dimensions['spacing_m'], pady=self.dimensions['spacing_m'])
        
        self.stop_button = self._create_apple_button(
            control_frame,
            text=f"{self.icons['stop']} 停止",
            command=self.stop_timer,
            style='secondary',
            width=10
        )
        self.stop_button.pack(side=tk.LEFT, padx=self.dimensions['spacing_m'], pady=self.dimensions['spacing_m'])
        
        self.reset_button = self._create_apple_button(
            control_frame,
            text=f"{self.icons['reset']} 重置",
            command=self.reset_timer,
            style='secondary',
            width=10
        )
        self.reset_button.pack(side=tk.LEFT, padx=self.dimensions['spacing_m'], pady=self.dimensions['spacing_m'])
        
        return control_frame

    def _create_keyboard_shortcuts_frame(self, parent):
        """创建快捷键区域"""
        shortcuts_frame = self._create_apple_card(parent, bg_color=self.colors['surface_elevated'], elevated=True)
        
        # 创建快捷键标签
        shortcut_labels = {
            'start': {'label': None, 'key': None},
            'pause': {'label': None, 'key': None},
            'stop': {'label': None, 'key': None},
            'reset': {'label': None, 'key': None}
        }
        
        for i, (key, data) in enumerate(shortcut_labels.items()):
            label = tk.Label(
                shortcuts_frame,
                text=f"{self.icons['keyboard']} {self._get_shortcut_label_text(key)}",
                font=self.current_fonts['body'],
                fg=self.colors['text_primary'],
                bg=self.colors['surface_elevated'],
                anchor='w',
                width=12,
                takefocus=0  # 禁止获取焦点
            )
            label.grid(row=i, column=0, padx=self.dimensions['spacing_m'], pady=self.dimensions['spacing_s'], sticky='w')
            
            key_text = self._get_shortcut_key_text(key)
            key_label = tk.Label(
                shortcuts_frame,
                text=key_text,
                font=self.current_fonts['body_emphasis'],
                fg=self.colors['text_primary'],
                bg=self.colors['surface_elevated'],
                anchor='e',
                width=12,
                takefocus=0  # 禁止获取焦点
            )
            key_label.grid(row=i, column=1, padx=self.dimensions['spacing_m'], pady=self.dimensions['spacing_s'], sticky='e')
            
            data['label'] = label
            data['key'] = key_label
        
        # 更新快捷键标签的宽度
        for data in shortcut_labels.values():
            data['label'].config(width=12)
            data['key'].config(width=12)
        
        return shortcuts_frame

    def _create_settings_frame(self, parent):
        """创建设置区域"""
        settings_frame = self._create_apple_card(parent, bg_color=self.colors['surface_elevated'], elevated=True)
        
        # 创建设置标签和输入框
        settings_labels = {
            'total_minutes': {'label': None, 'entry': None},
            'interval_minutes': {'label': None, 'entry': None},
            'random_minutes': {'label': None, 'entry': None},
            'rest_minutes': {'label': None, 'entry': None},
            'second_reminder': {'label': None, 'entry': None}
        }
        
        for i, (key, data) in enumerate(settings_labels.items()):
            label = tk.Label(
                settings_frame,
                text=self._get_setting_label_text(key),
                font=self.current_fonts['body'],
                fg=self.colors['text_primary'],
                bg=self.colors['surface_elevated'],
                anchor='w',
                width=12,
                takefocus=0  # 禁止获取焦点
            )
            label.grid(row=i, column=0, padx=self.dimensions['spacing_m'], pady=self.dimensions['spacing_s'], sticky='w')
            
            entry = tk.Entry(
                settings_frame,
                textvariable=getattr(self, f"{key}_var"),
                font=self.current_fonts['body_emphasis'],
                fg=self.colors['text_primary'],
                bg=self.colors['surface_elevated'],
                relief='flat',
                bd=0,
                width=12,
                justify='center',
                takefocus=0  # 禁止获取焦点
            )
            entry.grid(row=i, column=1, padx=self.dimensions['spacing_m'], pady=self.dimensions['spacing_s'], sticky='e')
            
            data['label'] = label
            data['entry'] = entry
        
        # 更新设置标签的宽度
        for data in settings_labels.values():
            data['label'].config(width=12)
            data['entry'].config(width=12)
        
        return settings_frame

    def _create_statistics_frame(self, parent):
        """创建统计区域"""
        stats_frame = self._create_apple_card(parent, bg_color=self.colors['surface_elevated'], elevated=True)
        
        # 创建统计标签
        stats_labels = {
            'daily_work_time': {'label': None, 'value': None},
            'total_sessions': {'label': None, 'value': None},
            'most_used_mode': {'label': None, 'value': None}
        }
        
        for i, (key, data) in enumerate(stats_labels.items()):
            label = tk.Label(
                stats_frame,
                text=self._get_stat_label_text(key),
                font=self.current_fonts['body'],
                fg=self.colors['text_primary'],
                bg=self.colors['surface_elevated'],
                anchor='w',
                width=12,
                takefocus=0  # 禁止获取焦点
            )
            label.grid(row=i, column=0, padx=self.dimensions['spacing_m'], pady=self.dimensions['spacing_s'], sticky='w')
            
            value = tk.Label(
                stats_frame,
                text=self._get_stat_value_text(key),
                font=self.current_fonts['body_emphasis'],
                fg=self.colors['text_primary'],
                bg=self.colors['surface_elevated'],
                anchor='e',
                width=12,
                takefocus=0  # 禁止获取焦点
            )
            value.grid(row=i, column=1, padx=self.dimensions['spacing_m'], pady=self.dimensions['spacing_s'], sticky='e')
            
            data['label'] = label
            data['value'] = value
        
        # 更新统计标签的宽度
        for data in stats_labels.values():
            data['label'].config(width=12)
            data['value'].config(width=12)
        
        return stats_frame

    def _create_progress_frame(self, parent):
        """创建进度区域"""
        progress_frame = self._create_apple_card(parent, bg_color=self.colors['surface_elevated'], elevated=True)
        
        # 创建进度标签
        progress_label = tk.Label(
            progress_frame,
            text="进度",
            font=self.current_fonts['title'],
            fg=self.colors['text_primary'],
            bg=self.colors['surface_elevated'],
            anchor='w',
            takefocus=0  # 禁止获取焦点
        )
        progress_label.pack(side=tk.TOP, padx=self.dimensions['spacing_m'], pady=self.dimensions['spacing_s'])
        
        # 创建进度条
        self.progress_bar = ttk.Progressbar(
            progress_frame,
            orient='horizontal',
            length=200,
            mode='determinate',
            takefocus=0  # 禁止获取焦点
        )
        self.progress_bar.pack(side=tk.TOP, padx=self.dimensions['spacing_m'], pady=self.dimensions['spacing_s'])
        
        # 创建进度文本
        self.progress_text = tk.Label(
            progress_frame,
            text="0%",
            font=self.current_fonts['body'],
            fg=self.colors['text_primary'],
            bg=self.colors['surface_elevated'],
            anchor='center',
            takefocus=0  # 禁止获取焦点
        )
        self.progress_text.pack(side=tk.TOP, padx=self.dimensions['spacing_m'], pady=self.dimensions['spacing_s'])
        
        return progress_frame

    def _create_timer_frame(self, parent):
        """创建计时器区域"""
        timer_frame = self._create_apple_card(parent, bg_color=self.colors['surface_elevated'], elevated=True)
        
        # 创建计时器标签
        self.timer_label = tk.Label(
            timer_frame,
            text="00:00:00",
            font=self.current_fonts['timer_large'],
            fg=self.colors['text_primary'],
            bg=self.colors['surface_elevated'],
            anchor='center',
            takefocus=0  # 禁止获取焦点
        )
        self.timer_label.pack(side=tk.TOP, padx=self.dimensions['spacing_m'], pady=self.dimensions['spacing_s'])
        
        return timer_frame

    def _create_slogan_frame(self, parent):
        """创建标语区域"""
        slogan_frame = self._create_apple_card(parent, bg_color=self.colors['surface_elevated'], elevated=True)
        
        # 创建标语标签
        self.slogan_label = tk.Label(
            slogan_frame,
            text="标语",
            font=self.current_fonts['body'],
            fg=self.colors['text_primary'],
            bg=self.colors['surface_elevated'],
            anchor='center',
            wraplength=200,
            justify='center',
            takefocus=0  # 禁止获取焦点
        )
        self.slogan_label.pack(side=tk.TOP, padx=self.dimensions['spacing_m'], pady=self.dimensions['spacing_s'])
        
        return slogan_frame

    def _create_dim_screen_frame(self, parent):
        """创建屏幕变暗区域"""
        dim_frame = self._create_apple_card(parent, bg_color=self.colors['surface_elevated'], elevated=True)
        
        # 创建屏幕变暗标签
        dim_label = tk.Label(
            dim_frame,
            text="屏幕变暗",
            font=self.current_fonts['title'],
            fg=self.colors['text_primary'],
            bg=self.colors['surface_elevated'],
            anchor='w',
            takefocus=0  # 禁止获取焦点
        )
        dim_label.pack(side=tk.TOP, padx=self.dimensions['spacing_m'], pady=self.dimensions['spacing_s'])
        
        # 创建屏幕变暗开关
        self.dim_switch = ttk.Checkbutton(
            dim_frame,
            text="开启",
            variable=self.screen_dim_enabled,
            command=lambda: self._update_ui(self._trigger_screen_dim_effect)
        )
        self.dim_switch.pack(side=tk.RIGHT, padx=self.dimensions['spacing_m'])
        
        return dim_frame  # 返回框架

    def _patch_frame_duplicate(self):
        """这是一个空方法，用于替换重复的_test_custom_mode方法定义"""
        pass
    
    def _disable_hover_feedback(self, widget):
        """禁用控件鼠标悬停反馈，避免界面变白问题"""
        def empty_event(event):
            return "break"  # 使用return "break"阻止事件继续传播
            
        # 清除可能存在的Enter和Leave事件绑定
        widget.bind("<Enter>", empty_event, "+")
        widget.bind("<Leave>", empty_event, "+")
        widget.bind("<Motion>", empty_event, "+")
        
        # 对所有子组件也应用此设置（除按钮外）
        for child in widget.winfo_children():
            if not isinstance(child, tk.Button):
                self._disable_hover_feedback(child)
                
    def __init__(self):
        """初始化应用程序"""
        # 创建主窗口
        self.root = tk.Tk()
        self.root.title("时间提醒助手")
        self.root.geometry("385x525")  # 调整为指定宽度 (缩小30%)
        self.root.minsize(375, 525)  # 调整最小尺寸 (缩小30%)
        
        # 修改Tkinter Frame类，彻底禁用鼠标悬停效果
        self._patch_tkinter_frame_class()
        
        # 全局TK样式配置 - 禁用所有Frame的悬停高亮
        self.root.option_add('*Frame.highlightBackground', '#FEFFFE')
        self.root.option_add('*Frame.highlightColor', '#FEFFFE')
        self.root.option_add('*Canvas.highlightBackground', '#FEFFFE')
        self.root.option_add('*Canvas.highlightColor', '#FEFFFE')
        self.root.option_add('*Label.highlightBackground', '#FEFFFE')
        self.root.option_add('*Label.highlightColor', '#FEFFFE')
        self.root.option_add('*Frame.takeFocus', '0')  # 禁止Frame获取焦点
        
        # 设置窗口图标
        try:
            icon_path = self.resource_path("icon.ico")
            if os.path.exists(icon_path):
                self.root.iconbitmap(icon_path)
        except Exception as e:
            logging.error(f"设置窗口图标失败: {e}")
        
        # 初始化变量
        self.is_running = False
        self.is_paused = False
        self.is_mini_window = False
        self.has_floating_window = False
        self.is_dim_screen = False
        self.is_mode_locked = False  # 添加模式锁定变量
        self.mini_window = None
        self.floating_window = None
        self.dim_window = None
        self.tray_icon = None
        self.current_session_start = None
        self.current_focus_time = 0
        self.mode_buttons = {}  # 存储模式按钮引用
        self.current_work_mode = 'study'  # 当前选中的工作模式
        
        # 时间设置
        self.total_minutes = 90
        self.interval_minutes = 15
        self.random_minutes = 2
        self.rest_minutes = 10
        self.second_reminder_delay = 10
        
        # 时间设置变量
        self.total_minutes_var = tk.StringVar(value="90")
        self.interval_minutes_var = tk.StringVar(value="15")
        self.random_minutes_var = tk.StringVar(value="2")
        self.rest_minutes_var = tk.StringVar(value="10")
        self.second_reminder_var = tk.StringVar(value="10")
        
        # 初始化统计数据
        self.daily_work_time = 0
        self.total_sessions = 0
        self.daily_stats = {}
        
        # 改进：自定义模式数据结构
        self.custom_modes = {}
        self.custom_mode_selected = None
        self.custom_mode_history = {
            "last_used": [],  # 最近使用的模式列表，按时间倒序
            "most_used": []   # 最常用的模式列表，按使用次数倒序
        }
        
        # 改进：标语系统数据结构
        self.slogan_categories = {
            "default": {
                "name": "默认分类",
                "description": "系统默认标语",
                "enabled": True,
                "created_time": datetime.datetime.now().isoformat(),
                "slogans": [
                    "放松一下眼睛，看看远处",
                    "站起来活动一下身体",
                    "深呼吸，调整一下坐姿",
                    "喝口水，补充水分",
                    "记得保持专注，你做得很棒"
                ]
            },
            "motivational": {
                "name": "激励标语",
                "description": "激励自己的标语",
                "enabled": True,
                "created_time": datetime.datetime.now().isoformat(),
                "slogans": [
                    "坚持就是胜利",
                    "今天的努力，明天的实力",
                    "每一个小进步都值得欣赏",
                    "专注当下，成就未来",
                    "不要让昨天占用太多的今天"
                ]
            }
        }
        
        # 标语设置
        self.slogan_settings = {
            "current_slogan": "放松一下眼睛，看看远处",
            "use_random": True,
            "enabled_categories": ["default", "motivational"],
            "display_style": "standard",
            "favorite_slogans": []  # 收藏的标语
        }
        
        # 兼容旧版本的标语数据
        self.dim_messages = []
        self.current_dim_message = ""
        
        self.stats_file = "work_statistics.json"  # 添加统计文件路径
        
        # 默认设置
        self.close_to_tray = tk.BooleanVar(value=True)
        self.show_seconds = tk.BooleanVar(value=True)
        self.auto_dim_screen = tk.BooleanVar(value=True)
        self.sound_enabled = tk.BooleanVar(value=True)  # 重命名为 sound_enabled
        
        # 随机标语显示设置
        self.use_random_message = tk.BooleanVar(value=True)
        
        # 功能开关变量
        self.screen_dim_enabled = tk.BooleanVar(value=True)
        self.force_screen_dim = tk.BooleanVar(value=False)
        self.mini_window_enabled = tk.BooleanVar(value=False)
        self.minimize_on_close = tk.BooleanVar(value=True)
        self.floating_enabled = tk.BooleanVar(value=True)
        self.is_minimized_to_tray = False
        
        # 初始化苹果风格
        self._init_apple_style()
        
        # 加载统计数据
        self.load_statistics()
        
        # 初始化音频
        self._init_audio()
        
        # 检查音频文件
        self.check_audio_files()
        
        # 设置键盘快捷键
        self._setup_keyboard_shortcuts()
        
        # 设置用户界面
        self._setup_ui()
        
        # 设置关闭事件处理
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        
        # 应用默认工作模式
        self._apply_default_work_mode()
        
        # 计时器相关变量
        self.start_time = None
        self.end_time = None
        self.next_reminder_time = None
        self.reminder_thread = None
        self.countdown_thread = None
        self.pause_time = None
        self.total_pause_duration = 0
        self.last_reset_time = 0  # 重置防抖时间戳
        
        logging.info("时间提醒程序初始化完成")
    
    def _test_custom_mode(self):
        """测试自定义模式功能"""
        try:
            # 创建一个测试自定义模式
            test_mode_name = "测试模式"
            test_mode_key = self.save_custom_mode(test_mode_name, 30, 10, 1, 5, 5)
            if test_mode_key:
                logging.info(f"测试自定义模式创建成功: {test_mode_key}")
                # 删除测试模式
                if self.delete_custom_mode(test_mode_key):
                    logging.info("测试自定义模式删除成功")
                else:
                    logging.error("测试自定义模式删除失败")
            else:
                logging.error("测试自定义模式创建失败")
        except Exception as e:
            logging.error(f"测试自定义模式失败: {e}")

    def _apply_default_work_mode(self):
        """应用默认工作模式设置"""
        if self.current_work_mode == 'study':
            # 应用深度学习模式的设置
            self.total_minutes_var.set("90")
            self.interval_minutes_var.set("15")
            self.random_minutes_var.set("2")
            self.rest_minutes_var.set("10")
            
            # 更新按钮状态
            if hasattr(self, 'mode_buttons'):
                self._update_mode_buttons()
            
            # 启用开始按钮并更新文本
            if hasattr(self, 'start_button'):
                self.start_button.configure(state='normal')
                self.start_button.configure(text=f"{self.icons['rocket']} 开始深度学习")

    def _update_most_used_modes(self):
        """更新最常用模式列表"""
        try:
            # 按使用次数排序
            sorted_modes = sorted(
                [(key, data.get('use_count', 0)) for key, data in self.custom_modes.items()],
                key=lambda x: x[1],
                reverse=True
            )
            
            # 更新最常用列表
            self.custom_mode_history["most_used"] = [key for key, _ in sorted_modes[:10]]
            
            logging.info("已更新最常用模式列表")
        except Exception as e:
            logging.error(f"更新最常用模式列表失败: {e}")
            
    def _record_mode_usage(self, mode_key):
        """记录模式使用情况
        
        Args:
            mode_key: 模式键值
        """
        if mode_key not in self.custom_modes:
            return
            
        # 更新使用次数和最后使用时间
        if 'use_count' not in self.custom_modes[mode_key]:
            self.custom_modes[mode_key]['use_count'] = 0
        self.custom_modes[mode_key]['use_count'] += 1
        self.custom_modes[mode_key]['last_used'] = datetime.datetime.now().isoformat()
        
        # 更新最近使用历史
        if mode_key in self.custom_mode_history["last_used"]:
            self.custom_mode_history["last_used"].remove(mode_key)
        self.custom_mode_history["last_used"].insert(0, mode_key)
        
        # 限制历史记录长度
        if len(self.custom_mode_history["last_used"]) > 10:
            self.custom_mode_history["last_used"] = self.custom_mode_history["last_used"][:10]
            
        # 更新最常用列表
        self._update_most_used_modes()
        
        # 保存统计数据
        self.save_statistics()

    def _init_apple_style(self):
        """初始化商业化苹果风格样式配置"""
        # 商业化苹果风格配色方案 - 更现代更精致
        self.colors = {
            # 主色调 - 现代苹果蓝系
            'primary': '#007AFF',
            'primary_dark': '#0051D5',
            'primary_light': '#66B3FF',
            'primary_transparent': '#CCDFFF',  # 浅蓝色代替半透明效果
            'primary_gradient_start': '#007AFF',
            'primary_gradient_end': '#5AC8FA',
            
            # 系统颜色 - 更丰富的层次
            'background': '#F8F9FA',
            'surface': '#FFFFFF',
            'surface_secondary': '#F8F9FA',
            'surface_tertiary': '#F1F3F4',
            'surface_elevated': '#FEFFFE',
            'secondary_transparent': '#F8FAFA',  # 浅灰色代替半透明效果
            'card_shadow': '#E8EAED',
            
            # 文本颜色 - 更好的对比度
            'text_primary': '#1A1A1A',
            'text_secondary': '#5F6368',
            'text_tertiary': '#9AA0A6',
            'text_quaternary': '#BDC1C6',
            'text_accent': '#1976D2',
            
            # 语义颜色 - 现代化配色
            'success': '#0F9D58',
            'success_light': '#E8F5E8',
            'warning': '#F29900',
            'warning_light': '#FFF4E5',
            'error': '#EA4335',
            'error_light': '#FFEAE8',
            'info': '#4285F4',
            'info_light': '#E8F0FE',
            'info_transparent': '#E8F0FE',  # 添加info半透明颜色
            
            # 特殊颜色 - 商业化风格
            'separator': '#E8EAED',
            'accent': '#FF6F00',
            'tint': '#007AFF',
            'premium': '#7B1FA2',
            'premium_light': '#E8D0F0',
            'gradient_bg_start': '#F8F9FA',
            'gradient_bg_end': '#FFFFFF',
            'hover': '#FEFFFE'  # 悬停效果颜色 - 改为与surface_elevated相同
        }
        
        # 现代化图标系统 - 使用专业图标符号
        self.icons = {
            'timer': '⏱',
            'play': '▶',
            'pause': '⏸',
            'stop': '⏹',
            'reset': '↻',
            'settings': '⚙',
            'stats': '📈',
            'tomato': '🔴',
            'study': '🎯',
            'work': '💼',
            'sprint': '⚡',
            'status': '📊',
            'today': '📅',
            'keyboard': '⌨',
            'close': '✕',
            'check': '✓',
            'rocket': '🚀',
            'focus': '🎯',
            'gear': '⚙'
        }
        
        # 商业化字体配置 - 更精致的字体层次 (尺寸缩小30%)
        self.fonts = {
            'brand_title': ('SF Pro Display', 17, 'bold'),
            'title_large': ('SF Pro Display', 14, 'bold'),
            'title': ('SF Pro Display', 13, 'bold'),
            'headline': ('SF Pro Display', 11, 'bold'),
            'subheadline': ('SF Pro Display', 10, 'bold'),
            'body': ('SF Pro Text', 9, 'normal'),
            'body_emphasis': ('SF Pro Text', 9, 'bold'),
            'callout': ('SF Pro Text', 8, 'normal'),
            'subhead': ('SF Pro Text', 8, 'normal'),
            'footnote': ('SF Pro Text', 7, 'normal'),
            'caption': ('SF Pro Text', 7, 'normal'),
            'timer_large': ('SF Pro Display', 25, 'bold'),
            
            # 备用字体系统
            'brand_title_fallback': ('Microsoft YaHei UI', 15, 'bold'),
            'title_large_fallback': ('Microsoft YaHei UI', 13, 'bold'),
            'title_fallback': ('Microsoft YaHei UI', 11, 'bold'),
            'headline_fallback': ('Microsoft YaHei UI', 11, 'bold'),
            'subheadline_fallback': ('Microsoft YaHei UI', 9, 'bold'),
            'body_fallback': ('Microsoft YaHei UI', 8, 'normal'),
            'body_emphasis_fallback': ('Microsoft YaHei UI', 8, 'bold'),
            'callout_fallback': ('Microsoft YaHei UI', 8, 'normal'),
            'subhead_fallback': ('Microsoft YaHei UI', 7, 'normal'),
            'footnote_fallback': ('Microsoft YaHei UI', 7, 'normal'),
            'caption_fallback': ('Microsoft YaHei UI', 6, 'normal'),
            'timer_large_fallback': ('Microsoft YaHei UI', 22, 'bold')
        }
        
        # 尝试获取最佳字体
        self.current_fonts = self._get_best_fonts()
        
        # 现代化尺寸和间距系统 (尺寸缩小30%)
        self.dimensions = {
            # 圆角系统
            'corner_radius': 11,
            'corner_radius_small': 8,
            'corner_radius_large': 14,
            'corner_radius_button': 10,
            
            # 间距系统
            'spacing_xs': 3,
            'spacing_s': 6,
            'spacing_m': 11,
            'spacing_l': 17,
            'spacing_xl': 22,
            'spacing_xxl': 34,
            
            # 组件尺寸
            'button_height': 34,
            'button_height_small': 25,
            'card_padding': 17,
            'section_spacing': 28,
            
            # 阴影系统
            'shadow_offset': 1,
            'shadow_blur': 6,
            'shadow_elevation': 3
        }
        
        # 动画和效果配置
        self.animations = {
            'transition_duration': 200,
            'hover_scale': 1.02,
            'click_scale': 0.98,
            'fade_duration': 300
        }

    def _get_best_fonts(self):
        """获取最佳可用字体"""
        import tkinter.font as tkFont
        available_fonts = tkFont.families()
        
        # 检查是否有SF Pro字体
        has_sf_pro = any('SF Pro' in font for font in available_fonts)
        
        if has_sf_pro:
            return {
                'brand_title': self.fonts['brand_title'],
                'title_large': self.fonts['title_large'],
                'title': self.fonts['title'],
                'headline': self.fonts['headline'],
                'subheadline': self.fonts['subheadline'],
                'body': self.fonts['body'],
                'body_emphasis': self.fonts['body_emphasis'],
                'callout': self.fonts['callout'],
                'subhead': self.fonts['subhead'],
                'footnote': self.fonts['footnote'],
                'caption': self.fonts['caption'],
                'timer_large': self.fonts['timer_large']
            }
        else:
            return {
                'brand_title': self.fonts['brand_title_fallback'],
                'title_large': self.fonts['title_large_fallback'],
                'title': self.fonts['title_fallback'],
                'headline': self.fonts['headline_fallback'],
                'subheadline': self.fonts['subheadline_fallback'],
                'body': self.fonts['body_fallback'],
                'body_emphasis': self.fonts['body_emphasis_fallback'],
                'callout': self.fonts['callout_fallback'],
                'subhead': self.fonts['subhead_fallback'],
                'footnote': self.fonts['footnote_fallback'],
                'caption': self.fonts['caption_fallback'],
                'timer_large': self.fonts['timer_large_fallback']
            }

    def _create_apple_button(self, parent, text, command=None, style='primary', width=None, icon=None):
        """创建现代化商业苹果风格按钮"""
        # 样式配置字典
        style_configs = {
            'primary': {
                'bg': self.colors['primary'],
                'fg': 'white',
                'active_bg': self.colors['primary_dark'],
                'hover_bg': self.colors['primary_light'],
                'font': self.current_fonts['body_emphasis'] if 'body_emphasis' in self.current_fonts else self.current_fonts['body']
            },
            'secondary': {
                'bg': self.colors['surface_elevated'],
                'fg': self.colors['text_primary'],
                'active_bg': self.colors['surface_tertiary'],
                'hover_bg': self.colors['surface_secondary'],
                'font': self.current_fonts['body']
            },
            'success': {
                'bg': self.colors['success'],
                'fg': 'white',
                'active_bg': '#0A7C47',
                'hover_bg': '#12B669',
                'font': self.current_fonts['body_emphasis'] if 'body_emphasis' in self.current_fonts else self.current_fonts['body']
            },
            'warning': {
                'bg': self.colors['warning'],
                'fg': 'white',
                'active_bg': '#E08900',
                'hover_bg': '#FFB74D',
                'font': self.current_fonts['body_emphasis'] if 'body_emphasis' in self.current_fonts else self.current_fonts['body']
            },
            'error': {
                'bg': self.colors['error'],
                'fg': 'white',
                'active_bg': '#D23B2F',
                'hover_bg': '#F05545',
                'font': self.current_fonts['body_emphasis'] if 'body_emphasis' in self.current_fonts else self.current_fonts['body']
            }
        }
        
        config = style_configs.get(style, style_configs['primary'])
        
        # 处理图标和文本
        button_text = text
        if icon and icon in self.icons:
            button_text = f"{self.icons[icon]} {text}"
        elif icon:
            button_text = f"{icon} {text}"
        
        button = tk.Button(
            parent,
            text=button_text,
            command=command,
            font=config['font'],
            fg=config['fg'],
            bg=config['bg'],
            activebackground=config['active_bg'],
            activeforeground=config['fg'],
            relief='flat',
            bd=0,
            padx=self.dimensions['spacing_m'],
            pady=self.dimensions['spacing_s'] + 2,  # 稍微增加垂直间距
            cursor='hand2',
            width=width
        )
        
        # 现代化交互效果
        original_bg = config['bg']
        hover_bg = config['hover_bg']
        active_bg = config['active_bg']
        
        def on_enter(e):
            button.configure(bg=hover_bg)
            
        def on_leave(e):
            button.configure(bg=original_bg)
            
        def on_press(e):
            button.configure(bg=active_bg)
            
        def on_release(e):
            # 检查鼠标是否还在按钮范围内
            x, y = e.x, e.y
            if 0 <= x <= button.winfo_width() and 0 <= y <= button.winfo_height():
                button.configure(bg=hover_bg)
            else:
                button.configure(bg=original_bg)
        
        button.bind('<Enter>', on_enter)
        button.bind('<Leave>', on_leave)
        button.bind('<Button-1>', on_press)
        button.bind('<ButtonRelease-1>', on_release)
        
        return button

    def _create_apple_card(self, parent, bg_color=None, elevated=True):
        """创建现代化苹果风格卡片容器"""
        if bg_color is None:
            bg_color = self.colors['surface_elevated'] if elevated else self.colors['surface']
        
        # 创建外层容器用于阴影效果模拟
        container = tk.Frame(parent, bg=self.colors['background'])
        
        # 创建卡片主体
        card = tk.Frame(
            container,
            bg=bg_color,
            relief='flat',
            bd=0,
            padx=self.dimensions['card_padding']*0.7,  # 减小内边距
            pady=self.dimensions['card_padding']*0.7,  # 减小内边距
            takefocus=0  # 禁止获取焦点
        )
        card.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)
        
        # 如果需要立体效果，添加边框模拟阴影
        if elevated:
            # 创建微妙的边框效果
            card.configure(highlightthickness=1, highlightcolor=self.colors['card_shadow'], highlightbackground=self.colors['card_shadow'])
        
        # 禁止卡片响应鼠标悬停事件，防止变白
        def block_hover(event):
            return "break"
            
        card.bind("<Enter>", block_hover, "+")
        card.bind("<Leave>", block_hover, "+")
        card.bind("<Motion>", block_hover, "+")
        
        return container

    def _create_preset_modes_frame_old(self, parent):
        """旧的预设模式区域实现 - 已废弃"""
        
    def _update_mode_buttons(self):
        """更新模式按钮状态（兼容Canvas版本和传统按钮版本）"""
        try:
            # 检查是否使用Canvas版本的模式按钮
            if hasattr(self, 'preset_canvas') and self.preset_canvas:
                # Canvas版本的模式按钮更新
                for mode, items in self.mode_buttons.items():
                    if isinstance(items, dict) and 'bg' in items and 'text' in items:
                        # Canvas版本的按钮（字典对象，包含bg和text键）
                        if mode != self.current_work_mode:
                            if mode == 'tomato':
                                self.preset_canvas.itemconfig(items['bg'], fill=self.colors['error_light'])
                                self.preset_canvas.itemconfig(items['text'], fill=self.colors['error'])
                            elif mode == 'study':
                                self.preset_canvas.itemconfig(items['bg'], fill=self.colors['info_light'])
                                self.preset_canvas.itemconfig(items['text'], fill=self.colors['info'])
                            elif mode == 'work':
                                self.preset_canvas.itemconfig(items['bg'], fill=self.colors['success_light'])
                                self.preset_canvas.itemconfig(items['text'], fill=self.colors['success'])
                            elif mode == 'sprint':
                                self.preset_canvas.itemconfig(items['bg'], fill=self.colors['warning_light'])
                                self.preset_canvas.itemconfig(items['text'], fill=self.colors['warning'])
                                
                # 突出显示当前选中的模式
                if self.current_work_mode in self.mode_buttons:
                    items = self.mode_buttons[self.current_work_mode]
                    if isinstance(items, dict) and 'bg' in items and 'text' in items:
                        if self.current_work_mode == 'tomato':
                            self.preset_canvas.itemconfig(items['bg'], fill=self.colors['error'])
                            self.preset_canvas.itemconfig(items['text'], fill='white')
                        elif self.current_work_mode == 'study':
                            self.preset_canvas.itemconfig(items['bg'], fill=self.colors['info'])
                            self.preset_canvas.itemconfig(items['text'], fill='white')
                        elif self.current_work_mode == 'work':
                            self.preset_canvas.itemconfig(items['bg'], fill=self.colors['success'])
                            self.preset_canvas.itemconfig(items['text'], fill='white')
                        elif self.current_work_mode == 'sprint':
                            self.preset_canvas.itemconfig(items['bg'], fill=self.colors['warning'])
                            self.preset_canvas.itemconfig(items['text'], fill='white')
            else:
                # 传统按钮版本的更新（按钮对象）
                for mode_key, button in self.mode_buttons.items():
                    # 检查是否是按钮对象而非Canvas项目字典
                    if not isinstance(button, dict) and hasattr(button, 'configure'):
                        if mode_key == self.current_work_mode:
                            # 选中状态 - 深色高亮+边框+稍微放大效果
                            if mode_key == 'tomato':
                                self._safe_config(button,
                                    bg=self.colors['error'], 
                                    fg='white',
                                    relief='solid',
                                    bd=3,
                                    font=self.current_fonts['body_emphasis'] if 'body_emphasis' in self.current_fonts else self.current_fonts['body']
                                )
                            elif mode_key == 'study':
                                self._safe_config(button,
                                    bg=self.colors['info'], 
                                    fg='white',
                                    relief='solid',
                                    bd=3,
                                    font=self.current_fonts['body_emphasis'] if 'body_emphasis' in self.current_fonts else self.current_fonts['body']
                                )
                            elif mode_key == 'work':
                                self._safe_config(button,
                                    bg=self.colors['success'], 
                                    fg='white',
                                    relief='solid',
                                    bd=3,
                                    font=self.current_fonts['body_emphasis'] if 'body_emphasis' in self.current_fonts else self.current_fonts['body']
                                )
                            elif mode_key == 'sprint':
                                self._safe_config(button,
                                    bg=self.colors['warning'], 
                                    fg='white',
                                    relief='solid',
                                    bd=3,
                                    font=self.current_fonts['body_emphasis'] if 'body_emphasis' in self.current_fonts else self.current_fonts['body']
                                )
                        else:
                            # 未选中状态 - 恢复原色
                            if mode_key == 'tomato':
                                self._safe_config(button,
                                    bg=self.colors['error_light'], 
                                    fg=self.colors['error'],
                                    relief='flat',
                                    bd=0,
                                    font=self.current_fonts['body']
                                )
                            elif mode_key == 'study':
                                self._safe_config(button,
                                    bg=self.colors['info_light'], 
                                    fg=self.colors['info'],
                                    relief='flat',
                                    bd=0,
                                    font=self.current_fonts['body']
                                )
                            elif mode_key == 'work':
                                self._safe_config(button,
                                    bg=self.colors['success_light'], 
                                    fg=self.colors['success'],
                                    relief='flat',
                                    bd=0,
                                    font=self.current_fonts['body']
                                )
                            elif mode_key == 'sprint':
                                self._safe_config(button,
                                    bg=self.colors['warning_light'], 
                                    fg=self.colors['warning'],
                                    relief='flat',
                                    bd=0,
                                    font=self.current_fonts['body']
                                )
        except Exception as e:
            logging.error(f"更新模式按钮状态失败: {e}")
                
    def _create_preset_modes_frame(self, parent):
        """创建现代化预设模式区域 - 使用Canvas实现，避免悬停变白问题"""
        # 预设模式容器 - 使用Canvas代替Frame可以更好地控制绘制，不会有变白问题
        preset_container = tk.Canvas(parent, bg=self.colors['background'], 
                             highlightthickness=0, borderwidth=0, relief='flat')
        preset_container.pack(fill=tk.X, padx=(self.dimensions['spacing_s'], self.dimensions['spacing_s']), pady=self.dimensions['spacing_s'])
        
        # 为Canvas设置固定宽度
        preset_container.configure(width=385, height=260)
        
        # 在Canvas上创建一个矩形作为卡片背景
        card_x = 0
        card_y = 0
        card_width = 385
        card_height = 260
        
        # 绘制矩形卡片（带圆角的矩形）
        preset_container.create_rectangle(
            card_x, card_y, card_width, card_height,
            fill=self.colors['surface_elevated'],
            outline=self.colors['card_shadow'],
            width=1,
            tags="card_bg"
        )
        
        # 在Canvas上创建文本作为标题
        preset_container.create_text(
            card_width/2, 20,
            text=f"{self.icons['focus']} 工作模式",
            font=self.current_fonts['headline'],
            fill=self.colors['text_primary'],
            tags="title"
        )
        
        # 在Canvas上创建按钮
        padding = 15
        btn_width = (card_width - padding*3) / 2
        btn_height = 40
        
        # 第一行按钮位置
        row1_y = 60
        
        # 番茄工作法 - 使用Canvas创建自定义按钮
        tomato_x1 = padding
        tomato_x2 = tomato_x1 + btn_width
        
        # 创建番茄工作法按钮背景
        tomato_btn_bg = preset_container.create_rectangle(
            tomato_x1, row1_y, tomato_x2, row1_y + btn_height,
            fill=self.colors['error_light'],
            outline="",
            width=0,
            tags="tomato_btn"
        )
        
        # 番茄工作法文字
        tomato_text = preset_container.create_text(
            tomato_x1 + btn_width/2, row1_y + btn_height/2,
            text=f"{self.icons['tomato']} 番茄工作法",
            font=self.current_fonts['body'],
            fill=self.colors['error'],
            tags="tomato_text"
        )
        
        # 深度学习按钮
        study_x1 = tomato_x2 + padding
        study_x2 = study_x1 + btn_width
        
        # 创建深度学习按钮背景
        study_btn_bg = preset_container.create_rectangle(
            study_x1, row1_y, study_x2, row1_y + btn_height,
            fill=self.colors['info_light'],
            outline="",
            width=0,
            tags="study_btn"
        )
        
        # 深度学习文字
        study_text = preset_container.create_text(
            study_x1 + btn_width/2, row1_y + btn_height/2,
            text=f"{self.icons['study']} 深度学习",
            font=self.current_fonts['body'],
            fill=self.colors['info'],
            tags="study_text"
        )
        
        # 第二行按钮位置
        row2_y = row1_y + btn_height + padding
        
        # 办公模式按钮
        work_x1 = padding
        work_x2 = work_x1 + btn_width
        
        # 创建办公模式按钮背景
        work_btn_bg = preset_container.create_rectangle(
            work_x1, row2_y, work_x2, row2_y + btn_height,
            fill=self.colors['success_light'],
            outline="",
            width=0,
            tags="work_btn"
        )
        
        # 办公模式文字
        work_text = preset_container.create_text(
            work_x1 + btn_width/2, row2_y + btn_height/2,
            text=f"{self.icons['work']} 办公模式",
            font=self.current_fonts['body'],
            fill=self.colors['success'],
            tags="work_text"
        )
        
        # 快速冲刺按钮
        sprint_x1 = work_x2 + padding
        sprint_x2 = sprint_x1 + btn_width
        
        # 创建快速冲刺按钮背景
        sprint_btn_bg = preset_container.create_rectangle(
            sprint_x1, row2_y, sprint_x2, row2_y + btn_height,
            fill=self.colors['warning_light'],
            outline="",
            width=0,
            tags="sprint_btn"
        )
        
        # 快速冲刺文字
        sprint_text = preset_container.create_text(
            sprint_x1 + btn_width/2, row2_y + btn_height/2,
            text=f"{self.icons['sprint']} 快速冲刺",
            font=self.current_fonts['body'],
            fill=self.colors['warning'],
            tags="sprint_text"
        )
        
        # 第三行按钮位置
        row3_y = row2_y + btn_height + padding
        
        # 自定义模式按钮
        custom_x1 = padding
        custom_x2 = card_width - padding
        
        # 创建自定义模式按钮背景
        custom_color = self.colors['premium_light'] if hasattr(self.colors, 'premium_light') else '#E8D0F0'
        custom_btn_bg = preset_container.create_rectangle(
            custom_x1, row3_y, custom_x2, row3_y + btn_height,
            fill=custom_color,
            outline="",
            width=0,
            tags="custom_btn"
        )
        
        # 自定义模式文字
        custom_text = preset_container.create_text(
            (custom_x1 + custom_x2)/2, row3_y + btn_height/2,
            text=f"{self.icons['gear']} 自定义模式",
            font=self.current_fonts['body'],
            fill=self.colors['premium'],
            tags="custom_text"
        )
        
        # 绑定点击事件
        preset_container.tag_bind("tomato_btn", "<Button-1>", lambda e: self._select_work_mode('tomato'))
        preset_container.tag_bind("tomato_text", "<Button-1>", lambda e: self._select_work_mode('tomato'))
        
        preset_container.tag_bind("study_btn", "<Button-1>", lambda e: self._select_work_mode('study'))
        preset_container.tag_bind("study_text", "<Button-1>", lambda e: self._select_work_mode('study'))
        
        preset_container.tag_bind("work_btn", "<Button-1>", lambda e: self._select_work_mode('work'))
        preset_container.tag_bind("work_text", "<Button-1>", lambda e: self._select_work_mode('work'))
        
        preset_container.tag_bind("sprint_btn", "<Button-1>", lambda e: self._select_work_mode('sprint'))
        preset_container.tag_bind("sprint_text", "<Button-1>", lambda e: self._select_work_mode('sprint'))
        
        preset_container.tag_bind("custom_btn", "<Button-1>", lambda e: self._select_custom_mode())
        preset_container.tag_bind("custom_text", "<Button-1>", lambda e: self._select_custom_mode())
        
        # 保存按钮项引用
        self.mode_buttons = {
            'tomato': {'bg': tomato_btn_bg, 'text': tomato_text},
            'study': {'bg': study_btn_bg, 'text': study_text},
            'work': {'bg': work_btn_bg, 'text': work_text},
            'sprint': {'bg': sprint_btn_bg, 'text': sprint_text}
        }
        
        # 保存Canvas引用
        self.preset_canvas = preset_container
        
        # 应用按钮初始状态
        self._update_mode_buttons()
        
        # 绑定按钮点击事件
        preset_container.tag_bind("tomato_btn", "<Button-1>", lambda e: self._select_work_mode('tomato'))
        preset_container.tag_bind("tomato_text", "<Button-1>", lambda e: self._select_work_mode('tomato'))
        
        preset_container.tag_bind("study_btn", "<Button-1>", lambda e: self._select_work_mode('study'))
        preset_container.tag_bind("study_text", "<Button-1>", lambda e: self._select_work_mode('study'))
        
        preset_container.tag_bind("work_btn", "<Button-1>", lambda e: self._select_work_mode('work'))
        preset_container.tag_bind("work_text", "<Button-1>", lambda e: self._select_work_mode('work'))
        
        preset_container.tag_bind("sprint_btn", "<Button-1>", lambda e: self._select_work_mode('sprint'))
        preset_container.tag_bind("sprint_text", "<Button-1>", lambda e: self._select_work_mode('sprint'))
        
        preset_container.tag_bind("custom_btn", "<Button-1>", lambda e: self._select_custom_mode())
        preset_container.tag_bind("custom_text", "<Button-1>", lambda e: self._select_custom_mode())
        
        # 保存按钮引用到字典中，用于更新状态
        self.mode_buttons = {
            'tomato': {'bg': tomato_btn_bg, 'text': tomato_text},
            'study': {'bg': study_btn_bg, 'text': study_text},
            'work': {'bg': work_btn_bg, 'text': work_text},
            'sprint': {'bg': sprint_btn_bg, 'text': sprint_text}
        }
        
        # 保存Canvas引用，用于更新高亮显示
        self.preset_canvas = preset_container
        
        return preset_container

    def _select_work_mode(self, mode):
        """选择工作模式（带状态管理）"""
        if self.is_mode_locked:
            self._show_apple_notification("运行期间无法切换模式\n请先停止当前任务")
            return
            
        # 防止重复选择相同模式
        if self.current_work_mode == mode:
            return
            
        presets = {
            'tomato': {
                'name': '🍅 番茄工作法',
                'total': 25,
                'interval': 25,  # 25分钟后提醒休息
                'random': 0,
                'rest': 5,  # 休息5分钟
                'description': '25分钟专注 + 5分钟休息',
                'second': 10
            },
            'study': {
                'name': '📚 深度学习',
                'total': 90,
                'interval': 15,  # 每15分钟提醒一次
                'random': 2,
                'rest': 10,  # 休息10分钟
                'description': '90分钟深度学习 + 10分钟休息',
                'second': 10
            },
            'work': {
                'name': '💼 办公模式',
                'total': 45,
                'interval': 10,  # 每10分钟提醒一次
                'random': 1,
                'rest': 5,  # 休息5分钟
                'description': '45分钟高效工作 + 5分钟休息',
                'second': 10
            },
            'sprint': {
                'name': '⚡ 快速冲刺',
                'total': 15,
                'interval': 15,  # 15分钟后结束提醒
                'random': 0,
                'rest': 3,  # 休息3分钟
                'description': '15分钟高强度专注 + 3分钟休息',
                'second': 10
            }
        }
        
        # 检查是否是自定义模式
        if mode.startswith('custom_') and mode in self.custom_modes:
            preset = self.custom_modes[mode]
            self.custom_mode_selected = mode
            
            # 记录使用情况
            self._record_mode_usage(mode)
            
            # 更新当前模式
            self.current_work_mode = mode
            
            # 应用设置到变量
            self.total_minutes_var.set(str(preset['total']))
            self.interval_minutes_var.set(str(preset['interval']))
            self.random_minutes_var.set(str(preset['random']))
            self.rest_minutes_var.set(str(preset['rest']))
            self.second_reminder_var.set(str(preset['second']))
            
            # 更新按钮状态
            self._update_mode_buttons()
                
            # 显示确认消息
            self._show_apple_notification(
                f"已选择 {preset['name']}\n{preset['description']}\n总时长:{preset['total']}min 间隔:{preset['interval']}min 休息:{preset['rest']}min"
            )
            
            # 启用开始按钮并更新文本
            if hasattr(self, 'start_button') and hasattr(self.start_button, 'configure'):
                self._safe_config(self.start_button, state='normal')
                button_text = f"开始{preset['name'].replace('⭐ ', '')}"
                self._safe_config(self.start_button, text=f"{self.icons['rocket']} {button_text}")
                
            logging.info(f"选择自定义工作模式: {preset['name']}, 使用次数: {preset.get('use_count', 1)}")
            
        elif mode in presets:
            preset = presets[mode]
            
            # 清除自定义模式选择
            self.custom_mode_selected = None
            
            # 更新当前模式
            self.current_work_mode = mode
            
            # 应用设置到变量
            self.total_minutes_var.set(str(preset['total']))
            self.interval_minutes_var.set(str(preset['interval']))
            self.random_minutes_var.set(str(preset['random']))
            self.rest_minutes_var.set(str(preset['rest']))
            self.second_reminder_var.set(str(preset['second']))
            
            # 更新按钮状态
            self._update_mode_buttons()
                
            # 显示确认消息
            self._show_apple_notification(
                f"已选择 {preset['name']}\n{preset['description']}\n总时长:{preset['total']}min 间隔:{preset['interval']}min 休息:{preset['rest']}min"
            )
            
            # 启用开始按钮并更新文本
            if hasattr(self, 'start_button') and hasattr(self.start_button, 'configure'):
                self._safe_config(self.start_button, state='normal')
                button_text = f"开始{preset['name'].replace('📚 ', '').replace('🍅 ', '').replace('💼 ', '').replace('⚡ ', '')}"
                self._safe_config(self.start_button, text=f"{self.icons['rocket']} {button_text}")
                
            logging.info(f"选择工作模式: {preset['name']}")

    def _update_mode_buttons_legacy(self):
        """旧版更新模式按钮的显示状态 (针对Button组件) - 保留向后兼容性"""
        try:
            # 如果使用的是Canvas版本，则调用新方法
            if hasattr(self, 'preset_canvas') and self.preset_canvas:
                return self._update_mode_buttons()
                
            # 旧版实现：使用Button组件
            for mode_key, button in self.mode_buttons.items():
                # 检查是否是按钮对象而非Canvas项目字典
                if not isinstance(button, dict) and hasattr(button, 'configure'):
                    if mode_key == self.current_work_mode:
                        # 选中状态 - 深色高亮+边框+稍微放大效果
                        if mode_key == 'tomato':
                            button.configure(
                                bg=self.colors['error'], 
                                fg='white',
                                relief='solid',
                                bd=3,
                                font=self.current_fonts['body_emphasis'] if 'body_emphasis' in self.current_fonts else self.current_fonts['body']
                            )
                        elif mode_key == 'study':
                            button.configure(
                                bg=self.colors['info'], 
                                fg='white',
                                relief='solid',
                                bd=3,
                                font=self.current_fonts['body_emphasis'] if 'body_emphasis' in self.current_fonts else self.current_fonts['body']
                            )
                        elif mode_key == 'work':
                            button.configure(
                                bg=self.colors['success'], 
                                fg='white',
                                relief='solid',
                                bd=3,
                                font=self.current_fonts['body_emphasis'] if 'body_emphasis' in self.current_fonts else self.current_fonts['body']
                            )
                        elif mode_key == 'sprint':
                            button.configure(
                                bg=self.colors['warning'], 
                                fg='white',
                                relief='solid',
                                bd=3,
                                font=self.current_fonts['body_emphasis'] if 'body_emphasis' in self.current_fonts else self.current_fonts['body']
                            )
                    else:
                        # 未选中状态 - 恢复原色
                        if mode_key == 'tomato':
                            button.configure(
                                bg=self.colors['error_light'], 
                                fg=self.colors['error'],
                                relief='flat',
                                bd=0,
                                font=self.current_fonts['body']
                            )
                        elif mode_key == 'study':
                            button.configure(
                                bg=self.colors['info_light'], 
                                fg=self.colors['info'],
                                relief='flat',
                                bd=0,
                                font=self.current_fonts['body']
                            )
                        elif mode_key == 'work':
                            button.configure(
                                bg=self.colors['success_light'], 
                                fg=self.colors['success'],
                                relief='flat',
                                bd=0,
                                font=self.current_fonts['body']
                            )
                        elif mode_key == 'sprint':
                            button.configure(
                                bg=self.colors['warning_light'], 
                                fg=self.colors['warning'],
                                relief='flat',
                                bd=0,
                                font=self.current_fonts['body']
                            )
        except Exception as e:
            logging.error(f"更新模式按钮状态(旧版)失败: {e}")

    def _update_mode_buttons_locked(self):
        """更新锁定状态下的模式按钮 - 完全禁用点击（兼容Canvas版本和传统按钮版本）"""
        # 检查是否使用Canvas版本的模式按钮
        if hasattr(self, 'preset_canvas') and self.preset_canvas:
            # Canvas版本的按钮锁定 - 只需要更新颜色，不需要禁用状态
            for mode, items in self.mode_buttons.items():
                if isinstance(items, dict) and 'bg' in items and 'text' in items:
                    if mode == self.current_work_mode:
                        # 选中且锁定状态 - 保持高亮
                        if mode == 'tomato':
                            self.preset_canvas.itemconfig(items['bg'], fill=self.colors['error'])
                            self.preset_canvas.itemconfig(items['text'], fill='white')
                        elif mode == 'study':
                            self.preset_canvas.itemconfig(items['bg'], fill=self.colors['info'])
                            self.preset_canvas.itemconfig(items['text'], fill='white')
                        elif mode == 'work':
                            self.preset_canvas.itemconfig(items['bg'], fill=self.colors['success'])
                            self.preset_canvas.itemconfig(items['text'], fill='white')
                        elif mode == 'sprint':
                            self.preset_canvas.itemconfig(items['bg'], fill=self.colors['warning'])
                            self.preset_canvas.itemconfig(items['text'], fill='white')
                    else:
                        # 未选中且锁定状态 - 灰色显示
                        if mode == 'tomato':
                            self.preset_canvas.itemconfig(items['bg'], fill=self.colors['error_light'])
                            self.preset_canvas.itemconfig(items['text'], fill=self.colors['text_tertiary'])
                        elif mode == 'study':
                            self.preset_canvas.itemconfig(items['bg'], fill=self.colors['info_light'])
                            self.preset_canvas.itemconfig(items['text'], fill=self.colors['text_tertiary'])
                        elif mode == 'work':
                            self.preset_canvas.itemconfig(items['bg'], fill=self.colors['success_light'])
                            self.preset_canvas.itemconfig(items['text'], fill=self.colors['text_tertiary'])
                        elif mode == 'sprint':
                            self.preset_canvas.itemconfig(items['bg'], fill=self.colors['warning_light'])
                            self.preset_canvas.itemconfig(items['text'], fill=self.colors['text_tertiary'])
            return
            
        # 传统按钮版本的锁定
        for mode_key, button in self.mode_buttons.items():
            # 检查button是否是有效的按钮对象
            if not isinstance(button, dict) and hasattr(button, 'configure'):
                if mode_key == self.current_work_mode:
                    # 选中且锁定状态 - 保持高亮但禁用
                    if mode_key == 'tomato':
                        self._safe_config(button,
                            bg=self.colors['error'], 
                            fg='white',
                            state='disabled',
                            relief='solid',
                            bd=3,
                            disabledforeground='white'
                        )
                    elif mode_key == 'study':
                        self._safe_config(button,
                            bg=self.colors['info'], 
                            fg='white',
                            state='disabled',
                            relief='solid',
                            bd=3,
                            disabledforeground='white'
                        )
                    elif mode_key == 'work':
                        self._safe_config(button,
                            bg=self.colors['success'], 
                            fg='white',
                            state='disabled',
                            relief='solid',
                            bd=3,
                            disabledforeground='white'
                        )
                    elif mode_key == 'sprint':
                        self._safe_config(button,
                            bg=self.colors['warning'], 
                            fg='white',
                            state='disabled',
                            relief='solid',
                            bd=3,
                            disabledforeground='white'
                        )
                    
                    # 重要：安全地移除所有事件绑定，确保完全不可点击
                    try:
                        button.unbind('<Button-1>')
                        button.unbind('<ButtonRelease-1>')
                        button.unbind('<Enter>')
                        button.unbind('<Leave>')
                    except Exception as e:
                        logging.warning(f"无法解除模式按钮{mode_key}的事件绑定: {e}")
                    
                else:
                    # 未选中且锁定状态 - 深度灰色禁用
                    self._safe_config(button,
                        bg='#E0E0E0', 
                        fg='#A0A0A0',
                        state='disabled',
                        relief='flat',
                        bd=0,
                        disabledforeground='#A0A0A0'
                    )
                    
                    # 重要：安全地移除所有事件绑定
                    try:
                        button.unbind('<Button-1>')
                        button.unbind('<ButtonRelease-1>')
                        button.unbind('<Enter>')
                        button.unbind('<Leave>')
                    except Exception as e:
                        logging.warning(f"无法解除模式按钮{mode_key}的事件绑定: {e}")

    def _apply_preset_mode_apple(self, mode):
        """应用预设模式 - 苹果风格版本（保持向后兼容）"""
        self._select_work_mode(mode)

    def _show_apple_notification(self, message):
        """显示苹果风格通知"""
        # 创建通知窗口
        notification = tk.Toplevel(self.root)
        notification.title("")
        notification.configure(bg=self.colors['surface'])
        notification.overrideredirect(True)
        notification.resizable(False, False)
        
        # 设置窗口大小和位置
        notification.geometry("300x100")
        notification.update_idletasks()
        
        # 居中显示在主窗口上
        main_x = self.root.winfo_x()
        main_y = self.root.winfo_y()
        main_width = self.root.winfo_width()
        main_height = self.root.winfo_height()
        
        x = main_x + (main_width - 300) // 2
        y = main_y + (main_height - 100) // 2
        notification.geometry(f"300x100+{x}+{y}")
        
        # 创建消息标签
        message_label = tk.Label(
            notification,
            text=message,
            font=self.current_fonts['body'],
            fg=self.colors['text_primary'],
            bg=self.colors['surface'],
            justify=tk.CENTER,
            wraplength=250
        )
        message_label.pack(expand=True)
        
        # 2秒后自动关闭
        notification.after(2000, notification.destroy)

    def load_statistics(self):
        """加载统计数据"""
        try:
            if os.path.exists(self.stats_file):
                with open(self.stats_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    
                # 获取今天的日期
                today = datetime.datetime.now().strftime("%Y-%m-%d")
                
                # 加载今日数据
                if today in data.get('daily_records', {}):
                    self.daily_work_time = data['daily_records'][today].get('work_time', 0)
                    self.total_sessions = data['daily_records'][today].get('sessions', 0)
                else:
                    self.daily_work_time = 0
                    self.total_sessions = 0
                
                # 加载自定义模式
                if 'custom_modes' in data:
                    self.custom_modes = data['custom_modes']
                    # 检查并升级旧版本的自定义模式数据结构
                    for mode_key, mode_data in self.custom_modes.items():
                        if "use_count" not in mode_data:
                            mode_data["use_count"] = 0
                        if "last_used" not in mode_data:
                            mode_data["last_used"] = mode_data.get("created_time", datetime.datetime.now().isoformat())
                        if "tags" not in mode_data:
                            mode_data["tags"] = []
                        if "notes" not in mode_data:
                            mode_data["notes"] = ""
                            
                    # 更新自定义模式历史记录
                    self._update_most_used_modes()
                            
                    logging.info(f"加载了 {len(self.custom_modes)} 个自定义模式")
                
                # 加载标语分类系统
                if 'slogan_categories' in data:
                    # 新版数据结构
                    self.slogan_categories = data['slogan_categories']
                    self.slogan_settings = data.get('slogan_settings', {
                        "current_slogan": "",
                        "use_random": True,
                        "enabled_categories": ["default"],
                        "display_style": "standard",
                        "favorite_slogans": []
                    })
                    
                    # 确保有所有必要的字段
                    if "current_slogan" not in self.slogan_settings:
                        if "default" in self.slogan_categories and self.slogan_categories["default"]["slogans"]:
                            self.slogan_settings["current_slogan"] = self.slogan_categories["default"]["slogans"][0]
                        else:
                            self.slogan_settings["current_slogan"] = "放松一下眼睛，看看远处"
                    
                    if "use_random" not in self.slogan_settings:
                        self.slogan_settings["use_random"] = True
                        
                    if "enabled_categories" not in self.slogan_settings:
                        self.slogan_settings["enabled_categories"] = ["default"]
                        
                    if "display_style" not in self.slogan_settings:
                        self.slogan_settings["display_style"] = "standard"
                        
                    if "favorite_slogans" not in self.slogan_settings:
                        self.slogan_settings["favorite_slogans"] = []
                    
                    # 同步标语到旧UI变量
                    self.current_dim_message = self.slogan_settings["current_slogan"]
                    self.use_random_message.set(self.slogan_settings["use_random"])
                    
                    # 导入为旧格式标语列表以兼容旧代码
                    self.dim_messages = []
                    for category_id, category_data in self.slogan_categories.items():
                        if category_data["enabled"]:
                            self.dim_messages.extend(category_data["slogans"])
                    
                    if not self.dim_messages:
                        self.dim_messages = ["放松一下眼睛，看看远处"]
                    
                    logging.info(f"加载了 {len(self.slogan_categories)} 个标语分类")
                    
                # 兼容旧版本 - 导入旧格式标语
                elif 'dim_messages' in data:
                    self.dim_messages = data['dim_messages']
                    
                    # 转换为新格式
                    if 'default' not in self.slogan_categories:
                        self.slogan_categories['default'] = {
                            "name": "默认分类",
                            "description": "从旧版本导入的标语",
                            "enabled": True,
                            "created_time": datetime.datetime.now().isoformat(),
                            "slogans": data['dim_messages']
                        }
                        
                    # 设置当前标语
                    if 'dim_message_settings' in data:
                        self.current_dim_message = data['dim_message_settings'].get('current_message', self.dim_messages[0])
                        self.use_random_message.set(data['dim_message_settings'].get('use_random', True))
                        
                        # 同步到新格式
                        self.slogan_settings["current_slogan"] = self.current_dim_message
                        self.slogan_settings["use_random"] = self.use_random_message.get()
                    
                    logging.info(f"从旧版本加载了 {len(self.dim_messages)} 条标语")
                
                # 加载自定义模式历史
                if 'custom_mode_history' in data:
                    self.custom_mode_history = data['custom_mode_history']
                else:
                    self.custom_mode_history = {
                        "last_used": [],
                        "most_used": []
                    }
                
                logging.info("统计数据加载成功")
            else:
                self._create_initial_stats_file()
                logging.info("创建初始统计数据文件")
        except Exception as e:
            logging.error(f"加载统计数据失败: {e}")
            self._create_initial_stats_file()

    def save_statistics(self):
        """保存统计数据到文件"""
        try:
            # 获取今天的日期
            today = datetime.datetime.now().strftime("%Y-%m-%d")
            
            # 准备数据字典
            data = {}
            
            # 如果文件已存在，先读取原有数据
            if os.path.exists(self.stats_file):
                with open(self.stats_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            
            # 确保数据结构完整
            if 'daily_records' not in data:
                data['daily_records'] = {}
            
            if 'total_stats' not in data:
                data['total_stats'] = {
                    'total_work_time': 0,
                    'total_sessions': 0,
                    'created_date': datetime.datetime.now().isoformat()
                }
                
            # 更新今日数据
            if today not in data['daily_records']:
                data['daily_records'][today] = {
                    'work_time': self.daily_work_time,
                    'sessions': self.total_sessions,
                    'focus_periods': [],
                    'date': today
                }
            else:
                data['daily_records'][today]['work_time'] = self.daily_work_time
                data['daily_records'][today]['sessions'] = self.total_sessions
            
            # 更新总计数据
            total_work_time = 0
            total_sessions = 0
            for day_data in data['daily_records'].values():
                total_work_time += day_data.get('work_time', 0)
                total_sessions += day_data.get('sessions', 0)
                
            data['total_stats']['total_work_time'] = total_work_time
            data['total_stats']['total_sessions'] = total_sessions
            data['total_stats']['last_updated'] = datetime.datetime.now().isoformat()
            
            # 保存自定义模式
            data['custom_modes'] = self.custom_modes
            data['custom_mode_history'] = self.custom_mode_history
            
            # 保存标语系统
            data['slogan_categories'] = self.slogan_categories
            data['slogan_settings'] = self.slogan_settings
            
            # 兼容旧版本
            data['dim_messages'] = list(self.dim_messages)
            data['dim_message_settings'] = {
                'current_message': self.current_dim_message if hasattr(self, 'current_dim_message') else self.slogan_settings.get('current_slogan', ''),
                'use_random': self.slogan_settings.get('use_random', True)
            }
            
            # 添加版本号
            data['version'] = '2.0'
            
            # 写入文件
            with open(self.stats_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
                
            logging.info("统计数据保存成功")
            return True
        except Exception as e:
            logging.error(f"保存统计数据失败: {e}")
            return False

    def save_custom_mode(self, name, total, interval, random_val, rest, second, description=None, tags=None, notes=None):
        """保存自定义工作模式
        
        Args:
            name: 模式名称
            total: 总时长(分钟)
            interval: 间隔时间(分钟)
            random_val: 随机时间(分钟)
            rest: 休息时间(分钟)
            second: 二次提醒时间(秒)
            description: 描述
            tags: 标签列表
            notes: 备注
            
        Returns:
            str: 模式键值，保存失败返回None
        """
        try:
            # 创建参数转换为整数
            total = int(total)
            interval = int(interval)
            random_val = int(random_val)
            rest = int(rest)
            second = int(second)
            
            # 生成唯一ID
            import uuid
            mode_id = f"custom_{uuid.uuid4().hex[:8]}"
            
            # 检查是否是编辑现有模式
            is_editing = False
            for key, mode in self.custom_modes.items():
                if mode['name'] == name:
                    mode_id = key
                    is_editing = True
                    break
            
            # 准备标签列表
            if isinstance(tags, str):
                tags = [tag.strip() for tag in tags.split(',') if tag.strip()]
            elif not tags:
                tags = []
                
            # 如果是编辑模式，保留原有的使用统计
            use_count = 0
            last_used = None
            if is_editing and mode_id in self.custom_modes:
                use_count = self.custom_modes[mode_id].get('use_count', 0)
                last_used = self.custom_modes[mode_id].get('last_used', None)
            
            # 准备模式数据
            mode_data = {
                'name': name,
                'total': total,
                'interval': interval,
                'random': random_val,
                'rest': rest,
                'second': second,
                'description': description if description else f"{total}分钟，间隔{interval}分钟",
                'created_time': self.custom_modes.get(mode_id, {}).get('created_time', datetime.datetime.now().isoformat()),
                'modified_time': datetime.datetime.now().isoformat(),
                'use_count': use_count,
                'last_used': last_used,
                'tags': tags,
                'notes': notes if notes else ""
            }
            
            # 保存到自定义模式字典
            self.custom_modes[mode_id] = mode_data
            
            # 更新最近使用历史
            if mode_id in self.custom_mode_history["last_used"]:
                self.custom_mode_history["last_used"].remove(mode_id)
            self.custom_mode_history["last_used"].insert(0, mode_id)
            
            # 限制历史记录长度
            if len(self.custom_mode_history["last_used"]) > 10:
                self.custom_mode_history["last_used"] = self.custom_mode_history["last_used"][:10]
                
            # 更新最常用列表
            self._update_most_used_modes()
                
            # 保存到文件
            self.save_statistics()
            
            action = "更新" if is_editing else "创建"
            logging.info(f"{action}自定义模式: {name}, ID: {mode_id}")
            return mode_id
        except Exception as e:
            logging.error(f"保存自定义模式失败: {e}")
            return None


    def delete_custom_mode(self, mode_key):
        """删除自定义工作模式
        
        Args:
            mode_key: 要删除的模式键值
            
        Returns:
            bool: 删除成功返回True，失败返回False
        """
        try:
            # 检查模式是否存在
            if mode_key not in self.custom_modes:
                return False
            
            # 从历史记录中删除
            if mode_key in self.custom_mode_history["last_used"]:
                self.custom_mode_history["last_used"].remove(mode_key)
            
            if mode_key in self.custom_mode_history["most_used"]:
                self.custom_mode_history["most_used"].remove(mode_key)
            
            # 删除模式
            mode_name = self.custom_modes[mode_key]['name']
            del self.custom_modes[mode_key]
            
            # 如果删除的是当前选择的模式，清除选择
            if mode_key == self.custom_mode_selected:
                self.custom_mode_selected = None
                
            # 保存到文件
            self.save_statistics()
            
            logging.info(f"删除自定义模式: {mode_name}, ID: {mode_key}")
            return True
        except Exception as e:
            logging.error(f"删除自定义模式失败: {e}")
            return False
            
    def export_custom_modes(self, file_path=None, selected_modes=None):
        """导出自定义模式
        
        Args:
            file_path: 导出文件路径，None则弹出选择对话框
            selected_modes: 要导出的模式键值列表，None则导出全部
            
        Returns:
            bool: 导出成功返回True，失败返回False
        """
        try:
            from tkinter import filedialog
            
            # 选择保存位置
            if not file_path:
                file_path = filedialog.asksaveasfilename(
                    title="导出自定义模式",
                    defaultextension=".json",
                    filetypes=[
                        ("JSON文件", "*.json"),
                        ("所有文件", "*.*")
                    ]
                )
                
            if not file_path:
                return False  # 用户取消了导出
                
            # 准备导出数据
            export_data = {
                "version": "2.0",
                "exported_date": datetime.datetime.now().isoformat(),
                "modes": {}
            }
            
            # 确定要导出的模式列表
            if selected_modes is None:
                selected_modes = list(self.custom_modes.keys())
                
            # 添加模式数据
            for mode_key in selected_modes:
                if mode_key in self.custom_modes:
                    export_data["modes"][mode_key] = self.custom_modes[mode_key]
                    
            # 写入文件
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(export_data, f, ensure_ascii=False, indent=2)
                
            logging.info(f"已导出 {len(export_data['modes'])} 个自定义模式")
            return True
        except Exception as e:
            logging.error(f"导出自定义模式失败: {e}")
            return False
            
    def import_custom_modes(self, file_path=None, overwrite=False):
        """导入自定义模式
        
        Args:
            file_path: 导入文件路径，None则弹出选择对话框
            overwrite: 是否覆盖同名模式
            
        Returns:
            tuple: (导入成功的模式数, 跳过的模式数)
        """
        try:
            from tkinter import filedialog
            import uuid
            
            # 选择文件
            if not file_path:
                file_path = filedialog.askopenfilename(
                    title="导入自定义模式",
                    filetypes=[
                        ("JSON文件", "*.json"),
                        ("所有文件", "*.*")
                    ]
                )
                
            if not file_path or not os.path.exists(file_path):
                return (0, 0)  # 用户取消了导入或文件不存在
                
            # 读取文件
            with open(file_path, 'r', encoding='utf-8') as f:
                import_data = json.load(f)
                
            # 检查数据格式
            if not isinstance(import_data, dict) or "modes" not in import_data:
                logging.error("导入文件格式错误")
                return (0, 0)
                
            # 导入模式
            imported = 0
            skipped = 0
            
            for mode_key, mode_data in import_data["modes"].items():
                # 检查必要字段
                required_fields = ["name", "total", "interval", "random", "rest", "second"]
                if not all(field in mode_data for field in required_fields):
                    skipped += 1
                    continue
                    
                # 检查是否已存在同名模式
                exists = False
                for existing_key, existing_data in self.custom_modes.items():
                    if existing_data["name"] == mode_data["name"]:
                        exists = True
                        if overwrite:
                            # 保留使用统计
                            use_count = existing_data.get("use_count", 0)
                            last_used = existing_data.get("last_used", None)
                            
                            # 更新数据
                            self.custom_modes[existing_key] = mode_data
                            
                            # 保留使用统计
                            self.custom_modes[existing_key]["use_count"] = use_count
                            self.custom_modes[existing_key]["last_used"] = last_used
                            
                            imported += 1
                        else:
                            skipped += 1
                        break
                
                # 如果不存在，直接添加
                if not exists:
                    # 确保使用新的mode_key避免冲突
                    new_mode_key = f"custom_{uuid.uuid4().hex[:8]}" if not mode_key.startswith("custom_") else mode_key
                    
                    # 添加模式
                    self.custom_modes[new_mode_key] = mode_data
                    
                    # 确保有必要的字段
                    if "use_count" not in self.custom_modes[new_mode_key]:
                        self.custom_modes[new_mode_key]["use_count"] = 0
                        
                    if "last_used" not in self.custom_modes[new_mode_key]:
                        self.custom_modes[new_mode_key]["last_used"] = None
                        
                    if "created_time" not in self.custom_modes[new_mode_key]:
                        self.custom_modes[new_mode_key]["created_time"] = datetime.datetime.now().isoformat()
                        
                    if "tags" not in self.custom_modes[new_mode_key]:
                        self.custom_modes[new_mode_key]["tags"] = []
                        
                    if "notes" not in self.custom_modes[new_mode_key]:
                        self.custom_modes[new_mode_key]["notes"] = ""
                        
                    imported += 1
                    
            # 更新最常用列表
            self._update_most_used_modes()
                    
            # 保存到文件
            self.save_statistics()
            
            logging.info(f"导入自定义模式: 成功 {imported} 个，跳过 {skipped} 个")
            return (imported, skipped)
        except Exception as e:
            logging.error(f"导入自定义模式失败: {e}")
            return (0, 0)
    
    def _create_initial_stats_file(self):
        """创建初始统计数据文件"""
        initial_data = {
            "daily_records": {},
            "total_stats": {
                "total_work_time": 0,
                "total_sessions": 0,
                "created_date": datetime.datetime.now().isoformat()
            },
            "custom_modes": {},
            "custom_mode_history": {
                "last_used": [],
                "most_used": []
            },
            "slogan_categories": {
                "default": {
                    "name": "默认分类",
                    "description": "系统默认标语",
                    "enabled": True,
                    "created_time": datetime.datetime.now().isoformat(),
                    "slogans": [
                        "放松一下眼睛，看看远处",
                        "站起来活动一下身体",
                        "深呼吸，调整一下坐姿",
                        "喝口水，补充水分",
                        "记得保持专注，你做得很棒"
                    ]
                },
                "motivational": {
                    "name": "激励标语",
                    "description": "激励自己的标语",
                    "enabled": True,
                    "created_time": datetime.datetime.now().isoformat(),
                    "slogans": [
                        "坚持就是胜利",
                        "今天的努力，明天的实力",
                        "每一个小进步都值得欣赏",
                        "专注当下，成就未来",
                        "不要让昨天占用太多的今天"
                    ]
                }
            },
            "slogan_settings": {
                "current_slogan": "放松一下眼睛，看看远处",
                "use_random": True,
                "enabled_categories": ["default", "motivational"],
                "display_style": "standard",
                "favorite_slogans": []
            },
            "dim_messages": self.dim_messages,
            "dim_message_settings": {
                "current_message": self.dim_messages[0],
                "use_random": True
            },
            "version": "2.0"
        }
        
        try:
            with open(self.stats_file, 'w', encoding='utf-8') as f:
                json.dump(initial_data, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            logging.error(f"创建初始统计数据文件失败: {e}")
            return False

    def create_slogan_category(self, category_id, name, description=None):
        """创建标语分类
        
        Args:
            category_id: 分类ID
            name: 分类名称
            description: 分类描述
            
        Returns:
            bool: 创建成功返回True，失败返回False
        """
        try:
            # 检查分类是否已存在
            if category_id in self.slogan_categories:
                return False
            
            # 创建新分类
            self.slogan_categories[category_id] = {
                "name": name,
                "description": description or f"{name}分类",
                "enabled": True,
                "created_time": datetime.datetime.now().isoformat(),
                "slogans": ["这是一个新的标语分类"]  # 默认添加一个标语
            }
            
            # 将新分类添加到启用分类列表
            if category_id not in self.slogan_settings["enabled_categories"]:
                self.slogan_settings["enabled_categories"].append(category_id)
                
            # 保存更改
            self.save_statistics()
            
            logging.info(f"创建标语分类: {name}")
            return True
        except Exception as e:
            logging.error(f"创建标语分类失败: {e}")
            return False
            
    def add_slogan(self, slogan_text, category_id="default"):
        """向指定分类添加标语
        
        Args:
            slogan_text: 标语文本
            category_id: 分类ID
            
        Returns:
            bool: 添加成功返回True，失败返回False
        """
        try:
            # 检查分类是否存在
            if category_id not in self.slogan_categories:
                return False
            
            # 检查标语是否已存在
            if slogan_text in self.slogan_categories[category_id]["slogans"]:
                return False
            
            # 添加标语
            self.slogan_categories[category_id]["slogans"].append(slogan_text)
            
            # 同步到旧版dim_messages用于兼容
            if category_id == "default" and slogan_text not in self.dim_messages:
                self.dim_messages.append(slogan_text)
            
            # 保存更改
            self.save_statistics()
            
            logging.info(f"添加标语: {slogan_text[:20]}... 到分类 {self.slogan_categories[category_id]['name']}")
            return True
        except Exception as e:
            logging.error(f"添加标语失败: {e}")
            return False
    
    def delete_slogan(self, slogan_text, category_id=None):
        """从指定分类删除标语
        
        Args:
            slogan_text: 标语文本
            category_id: 分类ID，None表示在所有分类中搜索
            
        Returns:
            bool: 删除成功返回True，失败返回False
        """
        try:
            # 如果指定了分类
            if category_id is not None:
                # 检查分类是否存在
                if category_id not in self.slogan_categories:
                    return False
                
                # 检查标语是否在分类中
                if slogan_text not in self.slogan_categories[category_id]["slogans"]:
                    return False
                
                # 删除标语
                self.slogan_categories[category_id]["slogans"].remove(slogan_text)
                
                # 如果是当前标语，重置
                if self.slogan_settings["current_slogan"] == slogan_text:
                    if self.slogan_categories[category_id]["slogans"]:
                        self.slogan_settings["current_slogan"] = self.slogan_categories[category_id]["slogans"][0]
                    elif "default" in self.slogan_categories and self.slogan_categories["default"]["slogans"]:
                        self.slogan_settings["current_slogan"] = self.slogan_categories["default"]["slogans"][0]
                    else:
                        self.slogan_settings["current_slogan"] = ""
                
                # 从收藏列表中删除
                if slogan_text in self.slogan_settings["favorite_slogans"]:
                    self.slogan_settings["favorite_slogans"].remove(slogan_text)
                
                # 从旧版dim_messages中删除
                if slogan_text in self.dim_messages:
                    self.dim_messages.remove(slogan_text)
                
                # 保存更改
                self.save_statistics()
                
                logging.info(f"删除标语: {slogan_text[:20]}... 从分类 {self.slogan_categories[category_id]['name']}")
                return True
            
            # 在所有分类中搜索
            for cat_id, category in self.slogan_categories.items():
                if slogan_text in category["slogans"]:
                    # 删除标语
                    category["slogans"].remove(slogan_text)
                    
                    # 如果是当前标语，重置
                    if self.slogan_settings["current_slogan"] == slogan_text:
                        if category["slogans"]:
                            self.slogan_settings["current_slogan"] = category["slogans"][0]
                        elif "default" in self.slogan_categories and self.slogan_categories["default"]["slogans"]:
                            self.slogan_settings["current_slogan"] = self.slogan_categories["default"]["slogans"][0]
                        else:
                            self.slogan_settings["current_slogan"] = ""
                    
                    # 从收藏列表中删除
                    if slogan_text in self.slogan_settings["favorite_slogans"]:
                        self.slogan_settings["favorite_slogans"].remove(slogan_text)
                    
                    # 从旧版dim_messages中删除
                    if slogan_text in self.dim_messages:
                        self.dim_messages.remove(slogan_text)
                    
                    # 保存更改
                    self.save_statistics()
                    
                    logging.info(f"删除标语: {slogan_text[:20]}... 从分类 {category['name']}")
                    return True
            
            return False
        except Exception as e:
            logging.error(f"删除标语失败: {e}")
            return False
    
    def get_random_slogan(self):
        """获取随机标语
        
        Returns:
            str: 随机标语，无可用标语返回空字符串
        """
        try:
            # 收集所有启用分类中的标语
            available_slogans = []
            
            # 优先从收藏中选择（20%概率）
            if self.slogan_settings["favorite_slogans"] and random.random() < 0.2:
                return random.choice(self.slogan_settings["favorite_slogans"])
            
            # 从启用的分类中收集标语
            for category_id in self.slogan_settings["enabled_categories"]:
                if category_id in self.slogan_categories and self.slogan_categories[category_id]["enabled"]:
                    available_slogans.extend(self.slogan_categories[category_id]["slogans"])
            
            # 如果没有可用标语，尝试从旧版dim_messages中获取
            if not available_slogans and self.dim_messages:
                available_slogans = self.dim_messages
            
            # 如果还是没有可用标语，返回空字符串
            if not available_slogans:
                return ""
            
            # 返回随机标语
            return random.choice(available_slogans)
        except Exception as e:
            logging.error(f"获取随机标语失败: {e}")
            return "放松一下眼睛，看看远处"
    
    def toggle_favorite_slogan(self, slogan_text):
        """切换标语收藏状态
        
        Args:
            slogan_text: 标语文本
            
        Returns:
            bool: 切换后的收藏状态，True表示已收藏，False表示未收藏
        """
        try:
            # 检查标语是否存在于任何分类
            slogan_exists = False
            for category in self.slogan_categories.values():
                if slogan_text in category["slogans"]:
                    slogan_exists = True
                    break
            
            if not slogan_exists:
                return False
            
            # 切换收藏状态
            if slogan_text in self.slogan_settings["favorite_slogans"]:
                self.slogan_settings["favorite_slogans"].remove(slogan_text)
                is_favorite = False
            else:
                self.slogan_settings["favorite_slogans"].append(slogan_text)
                is_favorite = True
            
            # 保存更改
            self.save_statistics()
            
            status = "收藏" if is_favorite else "取消收藏"
            logging.info(f"{status}标语: {slogan_text[:20]}...")
            return is_favorite
        except Exception as e:
            logging.error(f"切换标语收藏状态失败: {e}")
            return False
    
    def get_favorite_slogans(self):
        """获取收藏标语列表
        
        Returns:
            list: 收藏标语列表
        """
        try:
            return self.slogan_settings["favorite_slogans"]
        except Exception as e:
            logging.error(f"获取收藏标语列表失败: {e}")
            return []
    
    def delete_slogan_category(self, category_id):
        """删除标语分类
        
        Args:
            category_id: 分类的唯一标识符
            
        Returns:
            bool: 删除成功返回True，失败返回False
        """
        try:
            # 检查分类是否存在
            if category_id not in self.slogan_categories:
                return False
                
            # 不允许删除默认分类
            if category_id == "default":
                logging.warning("无法删除默认标语分类")
                return False
                
            # 从启用分类列表中移除
            if category_id in self.slogan_settings["enabled_categories"]:
                self.slogan_settings["enabled_categories"].remove(category_id)
                
            # 如果当前标语在被删除的分类中，重置当前标语
            category_slogans = self.slogan_categories[category_id]["slogans"]
            if self.slogan_settings["current_slogan"] in category_slogans:
                # 重置为默认分类的第一个标语
                if "default" in self.slogan_categories and self.slogan_categories["default"]["slogans"]:
                    self.slogan_settings["current_slogan"] = self.slogan_categories["default"]["slogans"][0]
                    
            # 删除分类
            category_name = self.slogan_categories[category_id]["name"]
            del self.slogan_categories[category_id]
            
            # 保存更改
            self.save_statistics()
            
            logging.info(f"删除标语分类: {category_name}")
            return True
        except Exception as e:
            logging.error(f"删除标语分类失败: {e}")
            return False
            
    def rename_slogan_category(self, category_id, new_name, new_description=None):
        """重命名标语分类
        
        Args:
            category_id: 分类的唯一标识符
            new_name: 新的分类名称
            new_description: 新的分类描述，None表示不修改
            
        Returns:
            bool: 重命名成功返回True，失败返回False
        """
        try:
            # 检查分类是否存在
            if category_id not in self.slogan_categories:
                return False
                
            # 更新分类名称
            old_name = self.slogan_categories[category_id]["name"]
            self.slogan_categories[category_id]["name"] = new_name
            
            # 更新描述（如果提供）
            if new_description is not None:
                self.slogan_categories[category_id]["description"] = new_description
                
            # 保存更改
            self.save_statistics()
            
            logging.info(f"重命名标语分类: {old_name} -> {new_name}")
            return True
        except Exception as e:
            logging.error(f"重命名标语分类失败: {e}")
            return False
            
    def toggle_slogan_category(self, category_id, enabled=None):
        """启用或禁用标语分类
        
        Args:
            category_id: 分类的唯一标识符
            enabled: True启用，False禁用，None切换当前状态
            
        Returns:
            bool: 操作成功返回True，失败返回False
        """
        try:
            # 检查分类是否存在
            if category_id not in self.slogan_categories:
                return False
                
            # 获取当前状态
            current_status = self.slogan_categories[category_id]["enabled"]
            
            # 确定新状态
            new_status = not current_status if enabled is None else enabled
            
            # 更新状态
            self.slogan_categories[category_id]["enabled"] = new_status
            
            # 更新启用分类列表
            if new_status:
                if category_id not in self.slogan_settings["enabled_categories"]:
                    self.slogan_settings["enabled_categories"].append(category_id)
            else:
                if category_id in self.slogan_settings["enabled_categories"]:
                    self.slogan_settings["enabled_categories"].remove(category_id)
                    
            # 保存更改
            self.save_statistics()
            
            status_text = "启用" if new_status else "禁用"
            logging.info(f"{status_text}标语分类: {self.slogan_categories[category_id]['name']}")
            return True
        except Exception as e:
            logging.error(f"切换标语分类状态失败: {e}")
            return False
            
    def set_current_slogan(self, message, category_id=None):
        """设置当前标语
        
        Args:
            message: 标语内容
            category_id: 标语所在分类，None表示在所有分类中搜索
            
        Returns:
            bool: 设置成功返回True，失败返回False
        """
        try:
            # 如果指定了分类
            if category_id is not None:
                # 检查分类是否存在
                if category_id not in self.slogan_categories:
                    return False
                    
                # 检查标语是否在指定分类中
                if message not in self.slogan_categories[category_id]["slogans"]:
                    return False
                    
                # 设置当前标语
                self.slogan_settings["current_slogan"] = message
                
                # 同步到旧变量
                self.current_dim_message = message
                
                # 保存更改
                self.save_statistics()
                
                logging.info(f"设置当前标语: {message}")
                return True
            
            # 在所有分类中搜索
            for category_id, category in self.slogan_categories.items():
                if message in category["slogans"]:
                    # 设置当前标语
                    self.slogan_settings["current_slogan"] = message
                    
                    # 同步到旧变量
                    self.current_dim_message = message
                    
                    # 保存更改
                    self.save_statistics()
                    
                    logging.info(f"设置当前标语: {message}")
                    return True
            
            return False
        except Exception as e:
            logging.error(f"设置当前标语失败: {e}")
            return False
            
    def export_slogans(self, file_path=None, category_id=None):
        """导出标语到文本文件
        
        Args:
            file_path: 导出文件路径，如果为None则使用默认路径
            category_id: 要导出的分类ID，None表示导出所有分类
            
        Returns:
            bool: 导出成功返回True，失败返回False
        """
        try:
            if not file_path:
                # 默认导出文件名: slogans_YYYYMMDD.json
                date_str = datetime.datetime.now().strftime("%Y%m%d")
                file_path = f"slogans_{date_str}.json"
            
            # 创建要导出的数据
            export_data = {
                "version": "1.0",
                "export_time": datetime.datetime.now().isoformat(),
                "categories": {}
            }
            
            # 导出指定分类或所有分类
            if category_id is not None:
                if category_id in self.slogan_categories:
                    export_data["categories"][category_id] = self.slogan_categories[category_id]
                else:
                    return False
            else:
                export_data["categories"] = self.slogan_categories
            
            # 保存到文件
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(export_data, f, ensure_ascii=False, indent=2)
            
            categories_count = len(export_data["categories"])
            slogans_count = sum(len(category["slogans"]) for category in export_data["categories"].values())
            
            logging.info(f"导出标语成功，共 {categories_count} 个分类，{slogans_count} 条标语: {file_path}")
            return True
        except Exception as e:
            logging.error(f"导出标语失败: {e}")
            return False
            
    def import_slogans(self, file_path, overwrite=False):
        """从文本文件导入标语
        
        Args:
            file_path: 导入文件路径
            overwrite: True表示覆盖已有分类，False表示合并
            
        Returns:
            tuple: (导入的分类数, 导入的标语数, 跳过的标语数)
        """
        try:
            if not os.path.exists(file_path):
                logging.error(f"导入文件不存在: {file_path}")
                return (0, 0, 0)
            
            # 检查文件类型
            file_ext = os.path.splitext(file_path)[1].lower()
            
            # 如果是txt文件，直接按行读取
            if file_ext == '.txt':
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        lines = f.readlines()
                        
                    # 获取当前选中的分类ID
                    category_id = self.selected_category.get()
                    
                    # 如果没有选中分类，使用default
                    if not category_id or category_id not in self.slogan_categories:
                        category_id = "default"
                    
                    # 添加标语
                    imported = 0
                    skipped = 0
                    for line in lines:
                        line = line.strip()
                        if line and line not in self.slogan_categories[category_id]["slogans"]:
                            self.slogan_categories[category_id]["slogans"].append(line)
                            imported += 1
                        elif line:  # 非空行但已存在
                            skipped += 1
                    
                    # 保存更改
                    if imported > 0:
                        self.save_statistics()
                    
                    logging.info(f"导入TXT文件成功: {imported} 条标语导入到分类 {self.slogan_categories[category_id]['name']}，{skipped} 条标语跳过")
                    return (0, imported, skipped)
                except Exception as e:
                    logging.error(f"导入TXT文件失败: {e}")
                    return (0, 0, 0)
            
            # JSON格式导入
            try:
                # 读取文件内容
                with open(file_path, 'r', encoding='utf-8') as f:
                    import_data = json.load(f)
                
                # 检查格式
                if not isinstance(import_data, dict) or "categories" not in import_data:
                    # 尝试以简单文本列表格式导入
                    if isinstance(import_data, list):
                        category_id = "imported"
                        category_name = "导入的标语"
                        
                        # 创建新分类（如果不存在）
                        if category_id not in self.slogan_categories:
                            self.slogan_categories[category_id] = {
                                "name": category_name,
                                "description": f"从 {os.path.basename(file_path)} 导入的标语",
                                "enabled": True,
                                "slogans": []
                            }
                        
                        # 添加标语
                        imported = 0
                        skipped = 0
                        for slogan in import_data:
                            if slogan not in self.slogan_categories[category_id]["slogans"]:
                                self.slogan_categories[category_id]["slogans"].append(slogan)
                                imported += 1
                            else:
                                skipped += 1
                        
                        # 保存更改
                        if imported > 0:
                            self.save_statistics()
                        
                        logging.info(f"导入标语列表成功: {imported} 条标语导入，{skipped} 条标语跳过")
                        return (1, imported, skipped)
                    else:
                        logging.error("导入文件格式错误")
                        return (0, 0, 0)
            except json.JSONDecodeError:
                # JSON解析失败，尝试作为纯文本导入
                return self.import_slogans_as_txt(file_path)
            
            # 导入分类和标语
            categories_imported = 0
            slogans_imported = 0
            slogans_skipped = 0
            
            for category_id, category_data in import_data["categories"].items():
                # 检查分类数据完整性
                if not isinstance(category_data, dict) or "name" not in category_data or "slogans" not in category_data:
                    continue
                
                # 如果分类已存在
                if category_id in self.slogan_categories:
                    if overwrite:
                        # 覆盖现有分类
                        self.slogan_categories[category_id] = category_data.copy()
                        slogans_imported += len(category_data["slogans"])
                        categories_imported += 1
                    else:
                        # 合并标语
                        existing_slogans = set(self.slogan_categories[category_id]["slogans"])
                        for slogan in category_data["slogans"]:
                            if slogan not in existing_slogans:
                                self.slogan_categories[category_id]["slogans"].append(slogan)
                                slogans_imported += 1
                            else:
                                slogans_skipped += 1
                        categories_imported += 1
                else:
                    # 创建新分类
                    self.slogan_categories[category_id] = category_data.copy()
                    slogans_imported += len(category_data["slogans"])
                    categories_imported += 1
                    
                    # 添加到启用分类列表
                    if category_id not in self.slogan_settings["enabled_categories"]:
                        self.slogan_settings["enabled_categories"].append(category_id)
            
            # 保存更改
            if categories_imported > 0:
                self.save_statistics()
            
            logging.info(f"导入标语成功: {categories_imported} 个分类，{slogans_imported} 条标语导入，{slogans_skipped} 条标语跳过")
            return (categories_imported, slogans_imported, slogans_skipped)
        except Exception as e:
            logging.error(f"导入标语失败: {e}")
            return (0, 0, 0)

    def import_slogans_as_txt(self, file_path):
        """从纯文本文件导入标语
        
        Args:
            file_path: 导入文件路径
            
        Returns:
            tuple: (导入的分类数, 导入的标语数, 跳过的标语数)
        """
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
                
            # 获取当前选中的分类ID
            category_id = getattr(self, 'selected_category', None)
            if category_id and hasattr(category_id, 'get'):
                category_id = category_id.get()
            
            # 如果没有选中分类，使用default
            if not category_id or category_id not in self.slogan_categories:
                category_id = "default"
            
            # 添加标语
            imported = 0
            skipped = 0
            for line in lines:
                line = line.strip()
                if line and line not in self.slogan_categories[category_id]["slogans"]:
                    self.slogan_categories[category_id]["slogans"].append(line)
                    imported += 1
                elif line:  # 非空行但已存在
                    skipped += 1
            
            # 保存更改
            if imported > 0:
                self.save_statistics()
            
            logging.info(f"导入TXT文件成功: {imported} 条标语导入到分类 {self.slogan_categories[category_id]['name']}，{skipped} 条标语跳过")
            return (0, imported, skipped)
        except Exception as e:
            logging.error(f"导入TXT文件失败: {e}")
            return (0, 0, 0)

    def _record_session_start(self):
        """记录会话开始"""
        self.current_session_start = datetime.datetime.now()
        self.current_focus_time = 0
        logging.info("开始记录工作会话")

    def _record_session_end(self):
        """记录会话结束"""
        if self.current_session_start:
            # 计算本次会话时长
            session_duration = (datetime.datetime.now() - self.current_session_start).total_seconds()
            
            # 更新统计数据
            self.daily_work_time += int(session_duration)
            self.total_sessions += 1
            
            # 保存数据
            self.save_statistics()
            
            # 更新统计显示
            self._update_stats_display()
            
            logging.info(f"会话结束，本次时长: {session_duration//60:.1f} 分钟")
            self.current_session_start = None

    def get_today_stats(self):
        """获取今日统计数据"""
        return {
            'work_time': self.daily_work_time,
            'sessions': self.total_sessions,
            'work_time_formatted': f"{self.daily_work_time//3600}小时{(self.daily_work_time%3600)//60}分钟"
        }

    def resource_path(self, relative_path):
        """获取资源文件的绝对路径，适用于PyInstaller打包后的情况"""
        try:
            # PyInstaller创建临时文件夹，将路径存储在_MEIPASS中
            base_path = sys._MEIPASS
        except Exception:
            base_path = os.path.abspath(".")
        
        return os.path.join(base_path, relative_path)

    def _init_audio(self):
        """初始化音频系统"""
        try:
            pygame.mixer.init(frequency=22050, size=-16, channels=2, buffer=512)
            logging.info("音频系统初始化成功")
            return True
        except pygame.error as e:
            logging.error(f"音频系统初始化失败: {e}")
            messagebox.showerror("错误", f"音频系统初始化失败: {e}")
            return False

    def _create_audio_folder(self):
        """创建音频文件夹"""
        try:
            if not os.path.exists("sounds"):
                os.makedirs("sounds")
                logging.info("创建sounds文件夹")
        except OSError as e:
            logging.error(f"创建音频文件夹失败: {e}")

    def _setup_ui(self):
        """设置用户界面 - 苹果风格"""
        # 创建固定尺寸的外部容器（宽度和高度都减少30%）
        main_container = tk.Frame(self.root, bg=self.colors['background'], width=385, height=525)
        main_container.pack_propagate(False)  # 防止子组件改变大小
        
        # 创建主滚动区域 - 限制宽度
        main_canvas = tk.Canvas(main_container, bg=self.colors['background'], highlightthickness=0)
        main_scrollbar = tk.Scrollbar(main_container, orient="vertical", command=main_canvas.yview)
        main_frame = tk.Frame(main_canvas, bg=self.colors['background'])
        
        main_frame.bind(
            "<Configure>",
            lambda e: main_canvas.configure(scrollregion=main_canvas.bbox("all"))
        )
        
        main_canvas.create_window((0, 0), window=main_frame, anchor="nw")
        main_canvas.configure(yscrollcommand=main_scrollbar.set)
        
        # 绑定鼠标滚轮 - 只绑定到特定canvas避免冲突
        def _on_mousewheel(event):
            try:
                if main_canvas.winfo_exists():
                    main_canvas.yview_scroll(int(-1*(event.delta/120)), "units")
            except tk.TclError:
                pass  # 忽略窗口已销毁的错误
        
        # 只在鼠标在canvas上时才响应滚轮
        def bind_wheel(event):
            main_canvas.bind_all("<MouseWheel>", _on_mousewheel)
            # 防止框架变白
            return "break"
            
        def unbind_wheel(event):
            main_canvas.unbind_all("<MouseWheel>")
            # 防止框架变白
            return "break"
            
        main_canvas.bind('<Enter>', bind_wheel)
        main_canvas.bind('<Leave>', unbind_wheel)
        
        # 禁用鼠标移动事件默认行为
        main_canvas.bind('<Motion>', lambda e: "break")
        

        
        # 倒计时显示区域
        self._create_display_frame(main_frame)
        
        # 控制面板区域
        self._create_control_frame(main_frame)
        
        # 预设模式区域
        self._create_preset_modes_frame(main_frame)
        
        # 状态区域
        self._create_status_frame(main_frame)
        
        # 布局组件
        main_scrollbar.pack(side="right", fill="y")
        main_canvas.pack(side="left", fill="both", expand=True)
        
        # 最后将主容器添加到root
        main_container.pack(side="left")
        
        # 全局禁用所有鼠标悬停默认行为，防止框架变白
        def disable_hover_events(widget):
            widget.bind("<Enter>", lambda e: "break")
            widget.bind("<Leave>", lambda e: "break")
            widget.bind("<Motion>", lambda e: "break")
            # 递归处理所有子组件（按钮除外）
            for child in widget.winfo_children():
                if not isinstance(child, tk.Button):
                    disable_hover_events(child)
        
        # 处理主框架
        disable_hover_events(main_frame)

    def _create_display_frame(self, parent):
        """创建现代化倒计时显示区域 - 圆形进度条设计"""
        # 倒计时区域容器
        display_container = tk.Frame(parent, bg=self.colors['background'])
        display_container.pack(fill=tk.X, padx=(self.dimensions['spacing_s'], self.dimensions['spacing_s']), pady=self.dimensions['spacing_s'])
        
        # 主显示卡片 - 高级立体效果
        display_card = self._create_apple_card(display_container, elevated=True)
        display_card.pack(fill=tk.X)
        
        # 设置最大宽度
        display_container.configure(width=390)
        
        # 禁用鼠标悬停事件
        display_container.bind("<Enter>", lambda e: "break")
        display_container.bind("<Leave>", lambda e: "break")
        display_container.bind("<Motion>", lambda e: "break")
        
        # 获取实际的卡片框架
        card_frame = display_card.winfo_children()[0]
        
        # 品牌标题区域 - 更紧凑
        brand_header = tk.Frame(card_frame, bg=self.colors['surface_elevated'])
        brand_header.pack(fill=tk.X, pady=(0, self.dimensions['spacing_s']))
        
        # 时间提醒助手标题 - 更小的字体
        brand_title = tk.Label(
            brand_header,
            text=f"{self.icons['timer']} 时间提醒助手",
            font=self.current_fonts['headline'],
            fg=self.colors['text_primary'],
            bg=self.colors['surface_elevated']
        )
        brand_title.pack()
        
        # 副标题 - 更小的字体
        subtitle = tk.Label(
            brand_header,
            text="专注工作，优雅提醒",
            font=self.current_fonts['callout'],
            fg=self.colors['text_secondary'],
            bg=self.colors['surface_elevated']
        )
        subtitle.pack(pady=(2, 0))
        
        # 圆形进度条和时间显示区域
        circle_frame = tk.Frame(card_frame, bg=self.colors['surface_elevated'])
        circle_frame.pack(pady=(self.dimensions['spacing_m'], self.dimensions['spacing_s']))
        
        # 创建Canvas用于绘制圆形进度条
        circle_size = 204  # 圆形进度条的大小 - 更小
        self.circle_canvas = tk.Canvas(
            circle_frame,
            width=circle_size,
            height=circle_size,
            bg=self.colors['surface_elevated'],
            highlightthickness=0,
            relief='flat'
        )
        self.circle_canvas.pack()
        
        # 禁用圆形进度条的鼠标悬停事件
        self.circle_canvas.bind("<Enter>", lambda e: "break")
        self.circle_canvas.bind("<Leave>", lambda e: "break")
        self.circle_canvas.bind("<Motion>", lambda e: "break")
        
        # 计算圆形参数
        center_x = circle_size // 2
        center_y = circle_size // 2
        radius = 84  # 进度条半径 - 更小
        inner_radius = 74  # 内圆半径
        
        # 绘制背景圆环
        self.bg_circle = self.circle_canvas.create_oval(
            center_x - radius, center_y - radius,
            center_x + radius, center_y + radius,
            outline=self.colors['surface_tertiary'],
            width=6,  # 更细的线条
            fill=""
        )
        
        # 创建进度圆弧 (初始为空)
        self.progress_arc = self.circle_canvas.create_arc(
            center_x - radius, center_y - radius,
            center_x + radius, center_y + radius,
            start=90,  # 从顶部开始
            extent=0,  # 初始角度为0
            outline=self.colors['primary'],
            width=6,  # 更细的线条
            style='arc'
        )
        
        # 时间显示标签 - 位于圆形中心
        self.countdown_label = tk.Label(
            circle_frame,
            text="00:00:00", 
            font=self.current_fonts['timer_large'],
            fg=self.colors['primary'],
            bg=self.colors['surface_elevated']
        )
        # 将时间标签放置在Canvas中央
        self.circle_canvas.create_window(
            center_x, center_y,
            window=self.countdown_label
        )
        

        
        # 进度信息容器 - 更紧凑的布局
        progress_container = tk.Frame(card_frame, bg=self.colors['surface_elevated'])
        progress_container.pack(fill=tk.X, padx=self.dimensions['spacing_m'], pady=(0, self.dimensions['spacing_s']))
        
        # 进度标签 - 居中显示
        self.progress_info_label = tk.Label(
            progress_container,
            text="进度 0%",
            font=self.current_fonts['footnote'],
            fg=self.colors['text_tertiary'],
            bg=self.colors['surface_elevated']
        )
        self.progress_info_label.pack()

    def _update_circle_progress(self, progress_percent):
        """更新圆形进度条"""
        try:
            if hasattr(self, 'circle_canvas') and hasattr(self, 'progress_arc'):
                # 计算进度角度 (360度对应100%)
                extent = int(360 * progress_percent / 100)
                
                # 更新进度圆弧
                self.circle_canvas.itemconfig(
                    self.progress_arc,
                    extent=extent
                )
                
                # 根据进度改变颜色
                if progress_percent < 25:
                    color = self.colors['success']
                elif progress_percent < 50:
                    color = self.colors['primary']
                elif progress_percent < 75:
                    color = self.colors['warning']
                else:
                    color = self.colors['error']
                    
                self.circle_canvas.itemconfig(
                    self.progress_arc,
                    outline=color
                )
                
        except Exception as e:
            # 如果圆形进度条出错，继续使用原有进度条
            pass

    def _create_control_frame(self, parent):
        """创建控制面板区域"""
        # 控制面板容器
        control_container = tk.Frame(parent, bg=self.colors['background'])
        control_container.pack(fill=tk.X, padx=(self.dimensions['spacing_s'], self.dimensions['spacing_s']), pady=self.dimensions['spacing_s'])
        
        # 控制面板卡片
        control_card = self._create_apple_card(control_container, elevated=True)
        control_card.pack(fill=tk.X)
        
        # 设置最大宽度
        control_container.configure(width=390)
        
        # 获取实际的卡片框架
        card_frame = control_card.winfo_children()[0]
        
        # 控制按钮行
        control_row = tk.Frame(card_frame, bg=self.colors['surface_elevated'])
        control_row.pack(fill=tk.X, pady=(0, self.dimensions['spacing_s']))
        
        # 开始按钮
        self.start_button = self._create_apple_button(
            control_row,
            text=f"{self.icons['rocket']} 开始深度学习",
            command=self.toggle_reminder,
            style='primary',
            width=15
        )
        self.start_button.pack(side=tk.LEFT, padx=(0, self.dimensions['spacing_s']))
        
        # 暂停按钮
        self.pause_button = self._create_apple_button(
            control_row,
            text=f"{self.icons['pause']} 暂停",
            command=self.toggle_pause,
            style='secondary',
            width=8
        )
        self.pause_button.pack(side=tk.LEFT, padx=(0, self.dimensions['spacing_s']))
        self.pause_button.configure(state='disabled')
        
        # 重置按钮
        self.reset_button = self._create_apple_button(
            control_row,
            text=f"{self.icons['reset']} 重置",
            command=self.reset_timer,
            style='secondary',
            width=8
        )
        self.reset_button.pack(side=tk.LEFT)
        
        # 功能按钮行
        function_row = tk.Frame(card_frame, bg=self.colors['surface_elevated'])
        function_row.pack(fill=tk.X)
        
        # 设置按钮
        settings_button = self._create_apple_button(
            function_row,
            text=f"{self.icons['settings']} 设置",
            command=self.open_settings_window,
            style='secondary'
        )
        settings_button.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, self.dimensions['spacing_s']))
        
        # 统计按钮
        stats_button = self._create_apple_button(
            function_row,
            text=f"{self.icons['stats']} 统计",
            command=self.open_statistics_window,
            style='secondary'
        )
        stats_button.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, self.dimensions['spacing_s']))
        
        # 自定义模式按钮
        custom_mode_button = self._create_apple_button(
            function_row,
            text="⭐ 自定义模式",
            command=lambda: self._open_custom_mode_with_log(),
            style='secondary'
        )
        custom_mode_button.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
    def _open_custom_mode_with_log(self):
        """带日志的打开自定义模式对话框"""
        logging.info("点击自定义模式按钮")
        try:
            # 确保自定义模式对话框正常打开
            self.open_custom_mode_dialog()
        except Exception as e:
            # 如果出现异常，显示详细错误信息
            error_msg = f"打开自定义模式对话框失败: {e}"
            logging.error(error_msg)
            messagebox.showerror("错误", error_msg)
            
    def _select_custom_mode(self):
        """当点击工作区域中的自定义模式按钮时调用
        弹出简易选择框选择已有自定义模式并立即应用"""
        logging.info("点击工作区域的自定义模式按钮")
        
        # 检查是否已有自定义模式
        if not self.custom_modes:
            self._show_apple_notification("尚未创建自定义模式\n请先在设置中创建自定义模式")
            self._open_custom_mode_with_log()  # 如果没有自定义模式，则打开设置
            return

        # 如果模式运行中，禁止切换
        if self.is_mode_locked:
            self._show_apple_notification("运行期间无法切换模式\n请先停止当前任务")
            return
            
        # 创建选择对话框
        dialog = tk.Toplevel(self.root)
        dialog.title("选择自定义模式")
        dialog.geometry("400x300")
        dialog.minsize(400, 300)
        dialog.resizable(False, False)
        dialog.transient(self.root)
        dialog.grab_set()
        
        # 设置对话框样式
        dialog.configure(bg=self.colors['background'])
        
        # 标题
        title_label = tk.Label(
            dialog,
            text="⭐ 选择要运行的自定义模式",
            font=self.current_fonts['subheadline'],
            fg=self.colors['text_primary'],
            bg=self.colors['background']
        )
        title_label.pack(pady=(15, 10))
        
        # 创建列表框架
        list_frame = self._create_apple_card(dialog)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=15, pady=10)
        
        # 创建列表容器
        list_container = list_frame.winfo_children()[0] if list_frame.winfo_children() else list_frame
        
        # 创建列表框
        custom_mode_listbox = tk.Listbox(
            list_container,
            font=self.current_fonts['body'],
            bg=self.colors['surface'],
            fg=self.colors['text_primary'],
            bd=0,
            highlightthickness=0,
            selectbackground=self.colors['primary_light'],
            selectforeground=self.colors['text_primary'],
            activestyle='none',
            relief='flat'
        )
        custom_mode_listbox.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # 添加滚动条
        scrollbar = tk.Scrollbar(custom_mode_listbox)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        custom_mode_listbox.config(yscrollcommand=scrollbar.set)
        scrollbar.config(command=custom_mode_listbox.yview)
        
        # 填充列表
        sorted_modes = sorted(self.custom_modes.items(), 
                             key=lambda x: x[1].get('use_count', 0), 
                             reverse=True)
        
        for mode_key, mode_data in sorted_modes:
            use_count = mode_data.get('use_count', 0)
            use_text = f"[{use_count}次]" if use_count > 0 else "[未使用]"
            display_text = f"{mode_data['name']}  •  {mode_data.get('description', '')}  {use_text}"
            custom_mode_listbox.insert(tk.END, display_text)
            
        # 如果有选中的模式，默认选中它
        if self.custom_mode_selected and self.custom_mode_selected in self.custom_modes:
            mode_keys = [key for key, _ in sorted_modes]
            if self.custom_mode_selected in mode_keys:
                current_index = mode_keys.index(self.custom_mode_selected)
                custom_mode_listbox.selection_set(current_index)
                custom_mode_listbox.see(current_index)
                
        # 底部按钮区域
        button_frame = tk.Frame(dialog, bg=self.colors['background'])
        button_frame.pack(fill=tk.X, pady=(5, 15), padx=15)
        
        # 运行按钮
        def run_selected_mode():
            selected_index = custom_mode_listbox.curselection()
            if not selected_index:
                return
                
            mode_key = sorted_modes[selected_index[0]][0]
            dialog.destroy()
            # 调用现有的选择工作模式方法
            self._select_work_mode(mode_key)
            
        run_button = self._create_apple_button(
            button_frame,
            text="✅ 运行",
            command=run_selected_mode,
            style='primary',
            width=80
        )
        run_button.pack(side=tk.LEFT, padx=(0, 5))
        
        # 编辑按钮
        def edit_modes():
            dialog.destroy()
            # 打开设置对话框
            self._open_custom_mode_with_log()
            
        edit_button = self._create_apple_button(
            button_frame,
            text="⚙️ 编辑",
            command=edit_modes,
            style='secondary',
            width=80
        )
        edit_button.pack(side=tk.LEFT)
        
        # 关闭按钮
        close_button = self._create_apple_button(
            button_frame,
            text="取消",
            command=dialog.destroy,
            style='secondary',
            width=80
        )
        close_button.pack(side=tk.RIGHT)
        
        # 双击直接运行
        custom_mode_listbox.bind('<Double-1>', lambda e: run_selected_mode())

    def open_settings_window(self):
        """打开设置窗口"""
        if hasattr(self, 'settings_window') and self.settings_window and self.settings_window.winfo_exists():
            self.settings_window.lift()
            self.settings_window.focus_force()
            return

        # 创建设置窗口 - 现代化苹果风格
        self.settings_window = tk.Toplevel(self.root)
        self.settings_window.title("⚙️ 设置选项")
        self.settings_window.geometry("500x650")
        self.settings_window.configure(bg=self.colors['background'])
        self.settings_window.resizable(False, False)
        self.settings_window.transient(self.root)
        self.settings_window.grab_set()
        
        # 设置窗口透明度
        try:
            self.settings_window.wm_attributes('-alpha', 0.98)
        except:
            pass
        
        # 将设置窗口放在主窗口右侧，平行显示
        self.root.update_idletasks()
        main_x = self.root.winfo_x()
        main_y = self.root.winfo_y()
        main_width = self.root.winfo_width()
        
        settings_x = main_x + main_width + 10  # 主窗口右侧，间隔10px
        settings_y = main_y  # 与主窗口同一水平线
        
        self.settings_window.geometry(f"500x650+{settings_x}+{settings_y}")
        
        # 创建滚动区域
        canvas = tk.Canvas(self.settings_window, bg=self.colors['background'], highlightthickness=0)
        scrollbar = tk.Scrollbar(self.settings_window, orient="vertical", command=canvas.yview)
        scrollable_frame = tk.Frame(canvas, bg=self.colors['background'])
        
        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        
        # 设置scrollable_frame的宽度并居中内容
        def update_scroll_region(event=None):
            canvas.configure(scrollregion=canvas.bbox("all"))
            # 确保scrollable_frame占据canvas的全部宽度
            canvas_width = canvas.winfo_width()
            if canvas_width > 1:
                canvas.itemconfig(canvas_window, width=canvas_width)
        
        canvas_window = canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        # 绑定事件以更新布局
        canvas.bind('<Configure>', update_scroll_region)
        scrollable_frame.bind('<Configure>', update_scroll_region)
        
        # 确保初始宽度正确
        self.settings_window.update_idletasks()
        update_scroll_region()
        
        # 标题
        title_label = tk.Label(
            scrollable_frame,
            text=f"{self.icons['settings']} 时间提醒设置",
            font=self.current_fonts['brand_title'],
            fg=self.colors['text_primary'],
            bg=self.colors['background']
        )
        title_label.pack(pady=(20, 30))
        
        # 时间设置区域
        self._create_time_settings_section(scrollable_frame)
        
        # 功能选项区域
        self._create_function_settings_section(scrollable_frame)
        
        # 按钮区域
        button_frame = tk.Frame(scrollable_frame, bg=self.colors['background'])
        button_frame.pack(fill=tk.X, padx=30, pady=(20, 30))
        
        # 确定按钮
        ok_button = self._create_apple_button(
            button_frame,
            text="确定",
            command=self.settings_window.destroy,
            style='success',
            icon='check'
        )
        ok_button.pack(side=tk.RIGHT, padx=(10, 0))
        
        # 取消按钮
        cancel_button = self._create_apple_button(
            button_frame,
            text="取消",
            command=self.settings_window.destroy,
            style='secondary',
            icon='close'
        )
        cancel_button.pack(side=tk.RIGHT)
        
        # 布局
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        # 绑定鼠标滚轮 - 避免与主窗口冲突
        def _on_mousewheel(event):
            try:
                if canvas.winfo_exists():
                    canvas.yview_scroll(int(-1*(event.delta/120)), "units")
            except tk.TclError:
                pass  # 忽略窗口已销毁的错误
        
        # 只在鼠标在设置窗口canvas上时才响应滚轮
        def bind_wheel(event):
            canvas.bind_all("<MouseWheel>", _on_mousewheel)
        def unbind_wheel(event):
            canvas.unbind_all("<MouseWheel>")
            
        canvas.bind('<Enter>', bind_wheel)
        canvas.bind('<Leave>', unbind_wheel)

    def open_statistics_window(self):
        """打开统计窗口"""
        if hasattr(self, 'stats_window') and self.stats_window and self.stats_window.winfo_exists():
            self.stats_window.lift()
            self.stats_window.focus_force()
            return
                
        # 创建统计窗口
        self.stats_window = tk.Toplevel(self.root)
        self.stats_window.title("📊 工作统计报告")
        self.stats_window.geometry("500x650")
        self.stats_window.configure(bg='white')
        self.stats_window.resizable(False, False)
        self.stats_window.transient(self.root)
        self.stats_window.grab_set()
        
        # 居中显示
        self.stats_window.update_idletasks()
        x = (self.stats_window.winfo_screenwidth() // 2) - (500 // 2)
        y = (self.stats_window.winfo_screenheight() // 2) - (650 // 2)
        self.stats_window.geometry(f"500x650+{x}+{y}")
        
        # 创建滚动区域
        canvas = tk.Canvas(self.stats_window, bg='white', highlightthickness=0)
        scrollbar = tk.Scrollbar(self.stats_window, orient="vertical", command=canvas.yview)
        scrollable_frame = tk.Frame(canvas, bg='white')
        
        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        # 标题
        title_label = tk.Label(
            scrollable_frame,
            text="📊 工作统计报告",
            font=('Microsoft YaHei UI', 18, 'bold'),
            fg='#1a73e8',
            bg='white'
        )
        title_label.pack(pady=(20, 30))
        
        # 今日统计区域
        self._create_today_stats_section(scrollable_frame)
        
        # 历史统计区域
        self._create_history_stats_section(scrollable_frame)
        
        # 操作按钮区域
        button_frame = tk.Frame(scrollable_frame, bg='white')
        button_frame.pack(fill=tk.X, padx=30, pady=(20, 30))
        
        # 导出数据按钮
        export_button = tk.Button(
            button_frame,
            text="📁 导出数据",
            command=self._export_statistics,
            font=('Microsoft YaHei UI', 11),
            fg='#38a169',
            bg='white',
            relief='solid',
            bd=1,
            pady=8,
            cursor='hand2'
        )
        export_button.pack(side=tk.LEFT, padx=(0, 10))
        
        # 刷新按钮
        refresh_button = tk.Button(
            button_frame,
            text="🔄 刷新",
            command=lambda: self._refresh_statistics_window(scrollable_frame),
            font=('Microsoft YaHei UI', 11),
            fg='#1a73e8',
            bg='white',
            relief='solid',
            bd=1,
            pady=8,
            cursor='hand2'
        )
        refresh_button.pack(side=tk.LEFT, padx=(0, 10))
        
        # 关闭按钮
        close_button = tk.Button(
            button_frame,
            text="❌ 关闭",
            command=self.stats_window.destroy,
            font=('Microsoft YaHei UI', 11, 'bold'),
            fg='white',
            bg='#ea4335',
            relief='solid',
            bd=0,
            pady=8,
            cursor='hand2'
        )
        close_button.pack(side=tk.RIGHT)
        
        # 布局
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        # 绑定鼠标滚轮 - 避免与其他窗口冲突
        def _on_mousewheel(event):
            try:
                if canvas.winfo_exists():
                    canvas.yview_scroll(int(-1*(event.delta/120)), "units")
            except tk.TclError:
                pass
        
        # 只在鼠标在统计窗口canvas上时才响应滚轮
        def bind_wheel(event):
            canvas.bind_all("<MouseWheel>", _on_mousewheel)
        def unbind_wheel(event):
            canvas.unbind_all("<MouseWheel>")
            
        canvas.bind('<Enter>', bind_wheel)
        canvas.bind('<Leave>', unbind_wheel)

    def _create_today_stats_section(self, parent):
        """创建今日统计区域"""
        today_container = tk.Frame(parent, bg='white')
        today_container.pack(fill=tk.X, padx=30, pady=(0, 20))
        
        # 区域标题
        today_title = tk.Label(
            today_container,
            text="📅 今日统计",
            font=('Microsoft YaHei UI', 14, 'bold'),
            fg='#1a73e8',
            bg='white'
        )
        today_title.pack(anchor='w', pady=(0, 15))
        
        # 统计卡片区域
        cards_frame = tk.Frame(today_container, bg='white')
        cards_frame.pack(fill=tk.X, pady=(0, 10))
        
        # 获取今日统计数据
        today_stats = self.get_today_stats()
        work_hours = today_stats['work_time'] // 3600
        work_minutes = (today_stats['work_time'] % 3600) // 60
        sessions = today_stats['sessions']
        
        # 工作时间卡片
        time_card = tk.Frame(cards_frame, bg='#e8f5e8', relief='solid', bd=1)
        time_card.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10))
        
        time_icon = tk.Label(time_card, text="⏰", font=('Microsoft YaHei UI', 24), 
                           bg='#e8f5e8', fg='#38a169')
        time_icon.pack(pady=(10, 5))
        
        time_value = tk.Label(time_card, text=f"{work_hours}小时{work_minutes}分钟", 
                            font=('Microsoft YaHei UI', 14, 'bold'), 
                            bg='#e8f5e8', fg='#2d3748')
        time_value.pack()
        
        time_label = tk.Label(time_card, text="工作时间", 
                            font=('Microsoft YaHei UI', 10), 
                            bg='#e8f5e8', fg='#718096')
        time_label.pack(pady=(0, 10))
        
        # 专注会话卡片
        session_card = tk.Frame(cards_frame, bg='#e3f2fd', relief='solid', bd=1)
        session_card.pack(side=tk.RIGHT, fill=tk.X, expand=True, padx=(10, 0))
        
        session_icon = tk.Label(session_card, text="🎯", font=('Microsoft YaHei UI', 24), 
                              bg='#e3f2fd', fg='#1976d2')
        session_icon.pack(pady=(10, 5))
        
        session_value = tk.Label(session_card, text=f"{sessions}次", 
                               font=('Microsoft YaHei UI', 14, 'bold'), 
                               bg='#e3f2fd', fg='#2d3748')
        session_value.pack()
        
        session_label = tk.Label(session_card, text="专注会话", 
                               font=('Microsoft YaHei UI', 10), 
                               bg='#e3f2fd', fg='#718096')
        session_label.pack(pady=(0, 10))

    def _create_history_stats_section(self, parent):
        """创建历史统计区域"""
        history_container = tk.Frame(parent, bg='white')
        history_container.pack(fill=tk.X, padx=30, pady=(0, 20))
        
        # 区域标题
        history_title = tk.Label(
            history_container,
            text="📈 历史统计",
            font=('Microsoft YaHei UI', 14, 'bold'),
            fg='#1a73e8',
            bg='white'
        )
        history_title.pack(anchor='w', pady=(0, 15))
        
        # 读取历史数据
        try:
            if os.path.exists(self.stats_file):
                with open(self.stats_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                total_stats = data.get('total_stats', {})
                daily_records = data.get('daily_records', {})
                
                # 总体统计信息
                total_frame = tk.Frame(history_container, bg='#f8f9fa', relief='solid', bd=1)
                total_frame.pack(fill=tk.X, pady=(0, 15))
                
                total_work_time = total_stats.get('total_work_time', 0)
                total_sessions = total_stats.get('total_sessions', 0)
                total_days = len(daily_records)
                
                total_hours = total_work_time // 3600
                total_minutes = (total_work_time % 3600) // 60
                avg_daily_minutes = (total_work_time // 60 // max(total_days, 1)) if total_days > 0 else 0
                
                total_info = tk.Label(
                    total_frame,
                    text=f"📊 总计: {total_hours}小时{total_minutes}分钟 | 共{total_sessions}次会话 | 使用{total_days}天 | 日均{avg_daily_minutes}分钟",
                    font=('Microsoft YaHei UI', 11),
                    bg='#f8f9fa',
                    fg='#3c4043'
                )
                total_info.pack(pady=10)
                
                # 最近7天数据
                recent_frame = tk.Frame(history_container, bg='white')
                recent_frame.pack(fill=tk.X)
                
                recent_title = tk.Label(
                    recent_frame,
                    text="📅 最近7天记录",
                    font=('Microsoft YaHei UI', 12, 'bold'),
                    fg='#1a73e8',
                    bg='white'
                )
                recent_title.pack(anchor='w', pady=(0, 10))
                
                # 创建表格头
                header_frame = tk.Frame(recent_frame, bg='#f1f3f4')
                header_frame.pack(fill=tk.X, pady=(0, 2))
                
                tk.Label(header_frame, text="日期", font=('Microsoft YaHei UI', 10, 'bold'),
                        bg='#f1f3f4', fg='#3c4043', width=12).pack(side=tk.LEFT, padx=5, pady=5)
                tk.Label(header_frame, text="工作时间", font=('Microsoft YaHei UI', 10, 'bold'),
                        bg='#f1f3f4', fg='#3c4043', width=12).pack(side=tk.LEFT, padx=5, pady=5)
                tk.Label(header_frame, text="专注会话", font=('Microsoft YaHei UI', 10, 'bold'),
                        bg='#f1f3f4', fg='#3c4043', width=12).pack(side=tk.LEFT, padx=5, pady=5)
                
                # 显示最近7天的数据
                today = datetime.datetime.now()
                for i in range(7):
                    date = (today - datetime.timedelta(days=i)).strftime("%Y-%m-%d")
                    day_data = daily_records.get(date, {'work_time': 0, 'sessions': 0})
                    
                    work_time = day_data['work_time']
                    sessions = day_data['sessions']
                    work_hours = work_time // 3600
                    work_mins = (work_time % 3600) // 60
                    
                    row_frame = tk.Frame(recent_frame, bg='white' if i % 2 == 0 else '#f8f9fa')
                    row_frame.pack(fill=tk.X, pady=1)
                    
                    # 日期显示
                    date_display = date if i != 0 else f"{date} (今天)"
                    tk.Label(row_frame, text=date_display, font=('Microsoft YaHei UI', 9),
                            bg=row_frame['bg'], fg='#3c4043', width=12).pack(side=tk.LEFT, padx=5, pady=3)
                    
                    # 工作时间显示
                    time_text = f"{work_hours}时{work_mins}分" if work_time > 0 else "-"
                    tk.Label(row_frame, text=time_text, font=('Microsoft YaHei UI', 9),
                            bg=row_frame['bg'], fg='#3c4043', width=12).pack(side=tk.LEFT, padx=5, pady=3)
                    
                    # 会话次数显示
                    session_text = f"{sessions}次" if sessions > 0 else "-"
                    tk.Label(row_frame, text=session_text, font=('Microsoft YaHei UI', 9),
                            bg=row_frame['bg'], fg='#3c4043', width=12).pack(side=tk.LEFT, padx=5, pady=3)
                
            else:
                no_data_label = tk.Label(
                    history_container,
                    text="📝 暂无历史数据，开始使用程序后将会显示统计信息",
                    font=('Microsoft YaHei UI', 11),
                    fg='#9aa0a6',
                    bg='white'
                )
                no_data_label.pack(pady=20)
                
        except Exception as e:
            error_label = tk.Label(
                history_container,
                text=f"❌ 加载历史数据失败: {str(e)}",
                font=('Microsoft YaHei UI', 11),
                fg='#ea4335',
                bg='white'
            )
            error_label.pack(pady=20)

    def _refresh_statistics_window(self, parent):
        """刷新统计窗口数据"""
        # 重新加载统计数据
        self.load_statistics()
        
        # 销毁当前内容并重新创建
        for widget in parent.winfo_children():
            widget.destroy()
        
        # 重新创建内容
        title_label = tk.Label(
            parent,
            text="📊 工作统计报告",
            font=('Microsoft YaHei UI', 18, 'bold'),
            fg='#1a73e8',
            bg='white'
        )
        title_label.pack(pady=(20, 30))
        
        self._create_today_stats_section(parent)
        self._create_history_stats_section(parent)
        
        # 重新创建按钮区域
        button_frame = tk.Frame(parent, bg='white')
        button_frame.pack(fill=tk.X, padx=30, pady=(20, 30))
        
        export_button = tk.Button(
            button_frame,
            text="📁 导出数据",
            command=self._export_statistics,
            font=('Microsoft YaHei UI', 11),
            fg='#38a169',
            bg='white',
            relief='solid',
            bd=1,
            pady=8,
            cursor='hand2'
        )
        export_button.pack(side=tk.LEFT, padx=(0, 10))
        
        refresh_button = tk.Button(
            button_frame,
            text="🔄 刷新",
            command=lambda: self._refresh_statistics_window(parent),
            font=('Microsoft YaHei UI', 11),
            fg='#1a73e8',
            bg='white',
            relief='solid',
            bd=1,
            pady=8,
            cursor='hand2'
        )
        refresh_button.pack(side=tk.LEFT, padx=(0, 10))
        
        close_button = tk.Button(
            button_frame,
            text="❌ 关闭",
            command=self.stats_window.destroy,
            font=('Microsoft YaHei UI', 11, 'bold'),
            fg='white',
            bg='#ea4335',
            relief='solid',
            bd=0,
            pady=8,
            cursor='hand2'
        )
        close_button.pack(side=tk.RIGHT)

    def _export_statistics(self):
        """导出统计数据"""
        try:
            from tkinter import filedialog
            
            # 选择保存位置
            file_path = filedialog.asksaveasfilename(
                title="导出统计数据",
                defaultextension=".json",
                filetypes=[
                    ("JSON文件", "*.json"),
                    ("文本文件", "*.txt"),
                    ("所有文件", "*.*")
                ]
            )
            
            if file_path:
                if os.path.exists(self.stats_file):
                    # 复制统计文件
                    import shutil
                    shutil.copy2(self.stats_file, file_path)
                    messagebox.showinfo("导出成功", f"统计数据已导出到：\n{file_path}")
                else:
                    messagebox.showwarning("导出失败", "没有找到统计数据文件")
                    
        except Exception as e:
            messagebox.showerror("导出失败", f"导出统计数据时发生错误：\n{str(e)}")

    def _create_preset_modes_section(self, parent):
        """创建现代化预设模式区域"""
        # 预设模式容器
        preset_container = self._create_apple_card(parent, elevated=True)
        preset_container.pack(fill=tk.X, padx=30, pady=(0, 20))
        
        # 获取实际的卡片框架
        card_frame = preset_container.winfo_children()[0] if preset_container.winfo_children() else preset_container
        
        # 区域标题
        preset_title = tk.Label(
            card_frame,
            text=f"{self.icons['focus']} 快速预设",
            font=self.current_fonts['headline'],
            fg=self.colors['text_primary'],
            bg=self.colors['surface_elevated']
        )
        preset_title.pack(anchor='w', pady=(0, 15))
        
        # 预设模式按钮框架
        preset_buttons_frame = tk.Frame(card_frame, bg=self.colors['surface_elevated'])
        preset_buttons_frame.pack(fill=tk.X, pady=(0, 10))
        
        # 定义预设模式数据 - 与主界面完全匹配
        preset_modes = [
            {
                'name': f"{self.icons['tomato']} 番茄工作法",
                'description': '25分钟工作 + 5分钟休息',
                'total': 25,
                'interval': 25,  # 25分钟后提醒休息
                'random': 0,
                'rest': 5,  # 休息5分钟
                'second': 10,
                'color': self.colors['error']
            },
            {
                'name': f"{self.icons['study']} 深度学习",
                'description': '90分钟学习 + 10分钟休息',
                'total': 90,
                'interval': 15,  # 每15分钟提醒一次
                'random': 2,
                'rest': 10,  # 休息10分钟
                'second': 10,
                'color': self.colors['info']
            },
            {
                'name': f"{self.icons['work']} 办公模式",
                'description': '45分钟工作 + 5分钟休息',
                'total': 45,
                'interval': 10,  # 每10分钟提醒一次
                'random': 1,
                'rest': 5,  # 休息5分钟
                'second': 10,
                'color': self.colors['success']
            },
            {
                'name': f"{self.icons['sprint']} 快速冲刺",
                'description': '15分钟冲刺 + 3分钟休息',
                'total': 15,
                'interval': 15,  # 15分钟后结束提醒
                'random': 0,
                'rest': 3,  # 休息3分钟
                'second': 10,
                'color': self.colors['warning']
            }
        ]
        
        # 创建预设按钮（每行2个）
        for i, preset in enumerate(preset_modes):
            if i % 2 == 0:
                # 创建新行
                row_frame = tk.Frame(preset_buttons_frame, bg=self.colors['surface_elevated'])
                row_frame.pack(fill=tk.X, pady=(0, 10))
            
            # 创建现代化预设按钮
            preset_btn = tk.Button(
                row_frame,
                text=f"{preset['name']}\n{preset['description']}",
                font=self.current_fonts['callout'],
                fg='white',
                bg=preset['color'],
                activebackground=self._darken_color(preset['color']),
                activeforeground='white',
                relief='flat',
                bd=0,
                padx=15,
                pady=10,
                cursor='hand2',
                command=lambda p=preset: self._apply_preset_mode(p)
            )
            
            # 布局按钮（左右各一个）
            if i % 2 == 0:
                preset_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
            else:
                preset_btn.pack(side=tk.RIGHT, fill=tk.X, expand=True, padx=(5, 0))
        
        # 自定义模式说明
        custom_info = tk.Label(
            card_frame,
            text="💡 提示：选择预设模式会自动填充下方的时间设置，您也可以手动调整",
            font=self.current_fonts['footnote'],
            fg=self.colors['text_tertiary'],
            bg=self.colors['surface_elevated'],
            wraplength=400
        )
        custom_info.pack(anchor='w', pady=(10, 0))

    def _darken_color(self, hex_color):
        """将颜色变暗（用于按钮活动状态）"""
        # 移除#号
        hex_color = hex_color.lstrip('#')
        # 转换为RGB
        rgb = tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
        # 变暗（乘以0.8）
        darkened = tuple(int(c * 0.8) for c in rgb)
        # 转换回十六进制
        return f"#{darkened[0]:02x}{darkened[1]:02x}{darkened[2]:02x}"

    def _apply_preset_mode(self, preset):
        """应用预设模式"""
        try:
            # 更新时间设置变量
            self.total_minutes_var.set(str(preset['total']))
            self.interval_minutes_var.set(str(preset['interval']))
            self.random_minutes_var.set(str(preset['random']))
            self.second_reminder_var.set(str(preset['second']))
            self.rest_minutes_var.set(str(preset['rest']))  # 添加休息时间
            
            # 显示确认消息
            messagebox.showinfo(
                "预设应用成功",
                f"已应用 {preset['name']} 模式！\n\n"
                f"总时长: {preset['total']} 分钟\n"
                f"间隔时间: {preset['interval']} 分钟\n"
                f"随机时间: {preset['random']} 分钟\n"
                f"休息时间: {preset['rest']} 分钟\n"
                f"二次提醒: {preset['second']} 秒"
            )
            
            logging.info(f"应用预设模式: {preset['name']}")
            
        except Exception as e:
            logging.error(f"应用预设模式失败: {e}")
            messagebox.showerror("错误", f"应用预设模式失败: {e}")

    def _create_time_settings_section(self, parent):
        """创建现代化时间设置区域"""
        # 首先创建预设模式区域
        self._create_preset_modes_section(parent)
        
        # 时间设置容器
        time_container = self._create_apple_card(parent, elevated=True)
        time_container.pack(fill=tk.X, padx=30, pady=(0, 20))
        
        # 获取实际的卡片框架
        card_frame = time_container.winfo_children()[0] if time_container.winfo_children() else time_container
        
        # 区域标题
        time_title = tk.Label(
            card_frame,
            text=f"{self.icons['timer']} 时间设置",
            font=self.current_fonts['headline'],
            fg=self.colors['text_primary'],
            bg=self.colors['surface_elevated']
        )
        time_title.pack(anchor='w', pady=(0, 15))
        
        # 总时长设置
        total_frame = tk.Frame(card_frame, bg=self.colors['surface_elevated'])
        total_frame.pack(fill=tk.X, pady=(0, 12))
        
        total_label = tk.Label(
            total_frame,
            text="📊 总时长(分钟):",
            font=self.current_fonts['body'],
            fg=self.colors['text_secondary'],
            bg=self.colors['surface_elevated']
        )
        total_label.pack(side=tk.LEFT)
        
        self.total_minutes_entry = tk.Spinbox(
            total_frame,
            from_=1,
            to=999,
            textvariable=self.total_minutes_var,
            font=self.current_fonts['body'],
            width=8,
            relief='flat',
            bd=1,
            validate='key',
            validatecommand=(self.root.register(self._validate_number), '%P')
        )
        self.total_minutes_entry.pack(side=tk.RIGHT)
        
        # 间隔时间设置
        interval_frame = tk.Frame(card_frame, bg=self.colors['surface_elevated'])
        interval_frame.pack(fill=tk.X, pady=(0, 12))
        
        interval_label = tk.Label(
            interval_frame,
            text="⏱️ 间隔时间(分钟):",
            font=self.current_fonts['body'],
            fg=self.colors['text_secondary'],
            bg=self.colors['surface_elevated']
        )
        interval_label.pack(side=tk.LEFT)
        
        self.interval_minutes_entry = tk.Spinbox(
            interval_frame,
            from_=1,
            to=60,
            textvariable=self.interval_minutes_var,
            font=self.current_fonts['body'],
            width=8,
            relief='flat',
            bd=1,
            validate='key',
            validatecommand=(self.root.register(self._validate_number), '%P')
        )
        self.interval_minutes_entry.pack(side=tk.RIGHT)
        
        # 随机提醒时间设置
        random_frame = tk.Frame(card_frame, bg=self.colors['surface_elevated'])
        random_frame.pack(fill=tk.X, pady=(0, 12))
        
        random_label = tk.Label(
            random_frame,
            text="🎲 随机提醒时间(分钟):",
            font=self.current_fonts['body'],
            fg=self.colors['text_secondary'],
            bg=self.colors['surface_elevated']
        )
        random_label.pack(side=tk.LEFT)
        
        self.random_minutes_entry = tk.Spinbox(
            random_frame,
            from_=0,
            to=10,
            textvariable=self.random_minutes_var,
            font=self.current_fonts['body'],
            width=8,
            relief='flat',
            bd=1,
            validate='key',
            validatecommand=(self.root.register(self._validate_number), '%P')
        )
        self.random_minutes_entry.pack(side=tk.RIGHT)
        
        # 休息时间设置
        rest_frame = tk.Frame(card_frame, bg=self.colors['surface_elevated'])
        rest_frame.pack(fill=tk.X, pady=(0, 12))
        
        rest_label = tk.Label(
            rest_frame,
            text="☕ 休息时间(分钟):",
            font=self.current_fonts['body'],
            fg=self.colors['text_secondary'],
            bg=self.colors['surface_elevated']
        )
        rest_label.pack(side=tk.LEFT)
        
        self.rest_minutes_entry = tk.Spinbox(
            rest_frame,
            from_=1,
            to=30,
            textvariable=self.rest_minutes_var,
            font=self.current_fonts['body'],
            width=8,
            relief='flat',
            bd=1,
            validate='key',
            validatecommand=(self.root.register(self._validate_number), '%P')
        )
        self.rest_minutes_entry.pack(side=tk.RIGHT)
        
        # 第二次提醒延迟设置
        second_frame = tk.Frame(card_frame, bg=self.colors['surface_elevated'])
        second_frame.pack(fill=tk.X)
        
        second_label = tk.Label(
            second_frame,
            text="⏰ 第二次提醒延迟(秒):",
            font=self.current_fonts['body'],
            fg=self.colors['text_secondary'],
            bg=self.colors['surface_elevated']
        )
        second_label.pack(side=tk.LEFT)
        
        self.second_reminder_entry = tk.Spinbox(
            second_frame,
            from_=0,
            to=60,
            textvariable=self.second_reminder_var,
            font=self.current_fonts['body'],
            width=8,
            relief='flat',
            bd=1,
            validate='key',
            validatecommand=(self.root.register(self._validate_number), '%P')
        )
        self.second_reminder_entry.pack(side=tk.RIGHT)

    def _create_function_settings_section(self, parent):
        """创建现代化功能设置区域"""
        # 功能设置容器
        function_container = self._create_apple_card(parent, elevated=True)
        function_container.pack(fill=tk.X, padx=30, pady=(20, 0))
        
        # 获取实际的卡片框架
        card_frame = function_container.winfo_children()[0] if function_container.winfo_children() else function_container
        
        # 区域标题
        function_title = tk.Label(
            card_frame,
            text=f"{self.icons['settings']} 功能选项",
            font=self.current_fonts['headline'],
            fg=self.colors['text_primary'],
            bg=self.colors['surface_elevated']
        )
        function_title.pack(anchor='w', pady=(0, 15))
        
        # 屏幕变暗选项
        self.screen_dim_check = tk.Checkbutton(
            card_frame, 
            text="🌙 提醒时屏幕变暗效果",
            variable=self.screen_dim_enabled,
            font=self.current_fonts['body'],
            fg=self.colors['text_secondary'],
            bg=self.colors['surface_elevated'],
            selectcolor='white',
            relief='flat',
            bd=0,
            cursor='hand2',
            indicatoron=1
        )
        self.screen_dim_check.pack(anchor='w', pady=(0, 15))
        
        # 强制变暗选项
        self.force_dim_check = tk.Checkbutton(
            card_frame, 
            text="🔒 强制变暗10秒（不可点击穿透）",
            variable=self.force_screen_dim,
            font=self.current_fonts['body'],
            fg=self.colors['text_secondary'],
            bg=self.colors['surface_elevated'],
            selectcolor='white',
            relief='flat',
            bd=0,
            cursor='hand2',
            indicatoron=1
        )
        self.force_dim_check.pack(anchor='w', pady=(0, 15))
        
        # 随机标语选项
        self.random_message_check = tk.Checkbutton(
            card_frame, 
            text="🎲 随机显示变暗标语",
            variable=self.use_random_message,
            font=self.current_fonts['body'],
            fg=self.colors['text_secondary'],
            bg=self.colors['surface_elevated'],
            selectcolor='white',
            relief='flat',
            bd=0,
            cursor='hand2',
            indicatoron=1
        )
        self.random_message_check.pack(anchor='w', pady=(0, 15))
        
        # 设置标语按钮和当前标语显示
        dim_message_button_frame = tk.Frame(card_frame, bg=self.colors['surface_elevated'])
        dim_message_button_frame.pack(fill=tk.X, pady=(0, 5))
        
        # 显示当前标语
        current_message_frame = tk.Frame(dim_message_button_frame, bg=self.colors['surface_elevated'])
        current_message_frame.pack(fill=tk.X, pady=(0, 10))
        
        current_message_label = tk.Label(
            current_message_frame,
            text="当前标语:",
            font=self.current_fonts['caption'],
            fg=self.colors['text_secondary'],
            bg=self.colors['surface_elevated']
        )
        current_message_label.pack(side=tk.LEFT, padx=(0, 10))
        
        current_message_content = tk.Label(
            current_message_frame,
            text=self.current_dim_message,
            font=self.current_fonts['body'],
            fg=self.colors['primary'],
            bg=self.colors['surface_elevated'],
            wraplength=350
        )
        current_message_content.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        # 设置标语按钮 - 使用新的标语管理器
        dim_message_button = self._create_apple_button(
            dim_message_button_frame,
            text="📝 管理标语与分类",
            command=self.open_slogan_manager_dialog,
            style='secondary'
        )
        dim_message_button.pack(fill=tk.X, pady=(5, 0))
        
        # 关闭行为选项
        self.minimize_close_check = tk.Checkbutton(
            card_frame, 
            text="🔽 关闭窗口时最小化到系统托盘",
            variable=self.minimize_on_close,
            font=self.current_fonts['body'],
            fg=self.colors['text_secondary'],
            bg=self.colors['surface_elevated'],
            selectcolor='white',
            relief='flat',
            bd=0,
            cursor='hand2',
            indicatoron=1
        )
        self.minimize_close_check.pack(anchor='w', pady=(0, 15))
        
        # 功能说明
        info_frame = tk.Frame(card_frame, bg=self.colors['surface_tertiary'], relief='flat', bd=1)
        info_frame.pack(fill=tk.X, pady=(10, 0))
        
        info_text = """💡 功能说明：
• 🌙 屏幕变暗：提醒时屏幕变暗，可点击穿透继续工作
• 🔒 强制变暗：变暗时阻止点击，强制休息10秒
• 🔽 最小化到托盘：关闭窗口时不退出，而是最小化到系统托盘"""

        info_label = tk.Label(
            info_frame,
            text=info_text,
            font=self.current_fonts['footnote'],
            fg=self.colors['text_tertiary'],
            bg=self.colors['surface_tertiary'],
            justify='left',
            wraplength=350,
            padx=15,
            pady=10
        )
        info_label.pack(fill=tk.X)

    def _validate_number(self, value):
        """验证输入是否为数字"""
        if value == "":
            return True
        try:
            int(value)
            return True
        except ValueError:
            return False

    def _update_ui(self, func, *args, **kwargs):
        """线程安全的UI更新"""
        self.root.after(0, lambda: func(*args, **kwargs))

    def _safe_config(self, widget, **kwargs):
        """安全的控件配置"""
        try:
            if hasattr(widget, 'config'):
                widget.config(**kwargs)
            elif hasattr(widget, 'configure'):
                widget.configure(**kwargs)
        except (tk.TclError, AttributeError):
            pass  # 忽略控件已销毁或不存在的错误

    def check_audio_files(self):
        """检查音频文件是否存在"""
        required_files = {
            "reminder.wav": "提醒音效",
            "start.mp3": "开始音效", 
            "stop.mp3": "停止音效"
        }
        
        missing_files = []
        for file, desc in required_files.items():
            file_path = self.resource_path(os.path.join("sounds", file))
            if not os.path.exists(file_path):
                missing_files.append(f"{desc}({file})")
                logging.warning(f"音频文件不存在: {file_path}")
        
        if missing_files:
            error_msg = f"缺少音频文件: {', '.join(missing_files)}"
            logging.warning(f"缺少音频文件: {missing_files}")
            return False
        else:
            logging.info("音频文件检查通过")
            return True

    def play_sound(self, sound_file):
        """播放音频文件"""
        def _play():
            try:
                sound_path = self.resource_path(os.path.join("sounds", sound_file))
                if os.path.exists(sound_path):
                    sound = pygame.mixer.Sound(sound_path)
                    sound.play()
                    logging.info(f"播放音频: {sound_file} (路径: {sound_path})")
                else:
                    logging.warning(f"音频文件不存在: {sound_path}")
            except pygame.error as e:
                logging.error(f"播放音频失败 {sound_file}: {e}")
            except Exception as e:
                logging.error(f"播放音频时发生未知错误 {sound_file}: {e}")
        
        # 在新线程中播放音频，避免阻塞
        threading.Thread(target=_play, daemon=True).start()

    def _play_reminder_sound_sequence(self):
        """播放提醒音频序列"""
        try:
            delay_seconds = int(self.second_reminder_var.get())
            
            # 播放第一次提醒
            if self.sound_enabled.get():
                self.play_sound("reminder.wav")
            
            # 如果启用了屏幕变暗功能，显示变暗效果
            if self.screen_dim_enabled.get():
                self._trigger_screen_dim_effect()
            
            # 如果设置了延迟且程序仍在运行，播放第二次提醒
            if delay_seconds > 0 and self.is_running and not self.is_paused:
                def delayed_reminder():
                    time.sleep(delay_seconds)
                    if self.is_running and not self.is_paused and self.sound_enabled.get():
                        self.play_sound("reminder.wav")
                        logging.info(f"播放第二次提醒，延迟{delay_seconds}秒")
                
                threading.Thread(target=delayed_reminder, daemon=True).start()
                
        except (ValueError, AttributeError) as e:
            logging.error(f"播放提醒音频序列失败: {e}")

    def update_countdown(self):
        """更新倒计时的主循环"""
        try:
            # 获取设置参数
            total_minutes = int(self.total_minutes_var.get())
            interval_minutes = int(self.interval_minutes_var.get())
            random_minutes = int(self.random_minutes_var.get())
            
            # 验证参数
            if not self._validate_settings(total_minutes, interval_minutes, random_minutes):
                return
            
            # 初始化时间变量
            start_time = datetime.datetime.now()
            end_time = start_time + datetime.timedelta(minutes=total_minutes)
            next_reminder_base_time = start_time + datetime.timedelta(minutes=interval_minutes)
            next_actual_reminder_time = None  # 实际的随机提醒时间
            
            logging.info(f"开始倒计时: 总时长{total_minutes}分钟, 间隔{interval_minutes}分钟")
            
            # 主循环
            while self.is_running:
                current_time = datetime.datetime.now()
                
                # 处理暂停逻辑
                if self.is_paused:
                    time.sleep(0.1)
                    continue
                    
                # 如果从暂停中恢复，调整结束时间
                if self.total_pause_duration > 0:
                    end_time += datetime.timedelta(seconds=self.total_pause_duration)
                    next_reminder_base_time += datetime.timedelta(seconds=self.total_pause_duration)
                    if next_actual_reminder_time:
                        next_actual_reminder_time += datetime.timedelta(seconds=self.total_pause_duration)
                    self.total_pause_duration = 0
                
                # 检查是否结束
                if current_time >= end_time:
                    self._finish_countdown()
                    break
                
                # 更新显示
                self._update_display(current_time, end_time, next_reminder_base_time, start_time, total_minutes)
                
                # 检查是否需要设置随机提醒时间
                if current_time >= next_reminder_base_time and next_actual_reminder_time is None:
                    # 第一次到达提醒基础时间，计算随机提醒时间
                    max_random_seconds = random_minutes * 60
                    random_delay = random.randint(0, max_random_seconds)
                    next_actual_reminder_time = next_reminder_base_time + datetime.timedelta(seconds=random_delay)
                    logging.info(f"计划提醒时间: {next_actual_reminder_time.strftime('%H:%M:%S')}, 随机延迟: {random_delay}秒")
                
                # 检查是否到了实际提醒时间
                if next_actual_reminder_time and current_time >= next_actual_reminder_time:
                    if self.is_running and not self.is_paused:
                        self._play_reminder_sound_sequence()
                        reminder_msg = f"上次提醒: {datetime.datetime.now().strftime('%H:%M:%S')}"
                        self._update_ui(self._safe_config, self.status_label, text=reminder_msg)
                        logging.info("播放提醒音效")
                    
                    # 设置下一个间隔的基础时间，重置实际提醒时间
                    next_reminder_base_time += datetime.timedelta(minutes=interval_minutes)
                    next_actual_reminder_time = None
                
                time.sleep(0.1)
                
        except Exception as e:
            logging.error(f"倒计时循环出错: {e}")
            self._update_ui(self._safe_config, self.status_label, text=f"程序错误: {str(e)}")
            self._stop_countdown()

    def _validate_settings(self, total_minutes, interval_minutes, random_minutes):
        """验证设置参数"""
        if total_minutes < 1 or interval_minutes < 1 or random_minutes < 0:
            error_msg = "请输入有效的数字(总时长、间隔时间需≥1，随机时间需≥0)"
            self._update_ui(self._safe_config, self.status_label, text=error_msg)
            logging.warning(f"参数验证失败: 总时长{total_minutes}, 间隔{interval_minutes}, 随机{random_minutes}")
            return False
        return True

    def _update_display(self, current_time, end_time, next_reminder_time, start_time, total_minutes):
        """更新显示界面"""
        try:
            # 计算剩余时间
            remaining_time = end_time - current_time
            total_seconds = int(remaining_time.total_seconds())
            
            if total_seconds <= 0:
                countdown_text = "时间到了！"
                progress = 100.0
                remaining_minutes = 0
                remaining_seconds = 0
            else:
                hours = total_seconds // 3600
                minutes = (total_seconds % 3600) // 60
                seconds = total_seconds % 60
                
                if hours > 0:
                    countdown_text = f"总倒计时：{hours:02d}:{minutes:02d}:{seconds:02d}"
                else:
                    countdown_text = f"总倒计时：{minutes:02d}:{seconds:02d}"
                
                # 计算进度
                elapsed_time = current_time - start_time
                total_duration = end_time - start_time
                progress = (elapsed_time.total_seconds() / total_duration.total_seconds()) * 100
                
                remaining_minutes = minutes
                remaining_seconds = seconds
                
                # 计算下次提醒时间显示
                if next_reminder_time:
                    time_to_reminder = next_reminder_time - current_time
                    reminder_seconds = int(time_to_reminder.total_seconds())
                    if reminder_seconds > 0:
                        reminder_minutes = reminder_seconds // 60
                        reminder_secs = reminder_seconds % 60
                        status_text = f"下次提醒：{reminder_minutes:02d}:{reminder_secs:02d}"
                    else:
                        status_text = "即将提醒"
                else:
                    status_text = "运行中"
            
            # 线程安全更新UI
            self._update_ui(self._safe_config, self.countdown_label, text=countdown_text.replace("总倒计时：", ""))
            self._update_ui(self._safe_config, self.progress_info_label, text=f"进度 {progress:.0f}%")
            
            # 更新圆形进度条
            self._update_ui(self._update_circle_progress, progress)
            
            # 更新小窗口
            if self.mini_window and self.mini_window.winfo_exists():
                self._update_ui(self.update_mini_window, countdown_text)
            
            # 更新浮动窗口
            self._update_ui(self.update_floating_window, countdown_text, status_text)
            
        except Exception as e:
            logging.error(f"更新显示时出错: {e}")

    def _finish_countdown(self):
        """完成倒计时"""
        if self.sound_enabled.get():
            self.play_sound("stop.mp3")
        self._stop_countdown()
        self._update_ui(self._safe_config, self.status_label, text="提醒已完成！")
        logging.info("倒计时完成")

    def _stop_countdown(self):
        """停止倒计时"""
        self.is_running = False
        self.is_paused = False
        self.total_pause_duration = 0
        
        self._update_ui(self._safe_config, self.start_button, text="🚀 开始专注", state="normal")
        self._update_ui(self._safe_config, self.pause_button, text="⏸️ 暂停", state="disabled")
        self._update_ui(self._safe_config, self.reset_button, state="normal")
        self._update_ui(self._safe_config, self.countdown_label, text="00:00:00")
        self._update_ui(self._safe_config, self.progress_info_label, text="进度 0%")
        
        # 重置圆形进度条
        self._update_ui(self._update_circle_progress, 0)
        
        # 更新浮动窗口显示停止状态
        self._update_ui(self.update_floating_window, "总倒计时: --:--", "已停止")

    def toggle_reminder(self):
        """切换提醒状态"""
        if not self.is_running:
            self._start_reminder()
        else:
            self._stop_reminder()

    def _start_reminder(self):
        """开始提醒"""
        try:
            # 工作模式检查（现在有默认模式，应该总是有效的）
            if not self.current_work_mode:
                self.current_work_mode = 'study'  # 确保有默认模式
            
            # 检查音频文件
            if not self.check_audio_files():
                return
            
            # 验证输入
            try:
                total_minutes = int(self.total_minutes_var.get())
                interval_minutes = int(self.interval_minutes_var.get())
                random_minutes = int(self.random_minutes_var.get())
                second_reminder_delay = int(self.second_reminder_var.get())
            except ValueError:
                self._update_ui(self._safe_config, self.status_label, text="请输入有效的数字")
                return
            
            if not self._validate_settings(total_minutes, interval_minutes, random_minutes):
                return
            
            if second_reminder_delay < 0:
                self._update_ui(self._safe_config, self.status_label, text="第二次提醒延迟不能为负数")
                return
            
            # 记录会话开始
            self._record_session_start()
            
            # 启动倒计时
            self.is_running = True
            self.is_paused = False
            self.total_pause_duration = 0
            self.is_mode_locked = True  # 锁定模式
            
            # 使用_safe_config方法来安全地更新UI元素
            self._update_ui(self._safe_config, self.start_button, text=f"{self.icons['stop']} 停止")
            self._update_ui(self._safe_config, self.pause_button, state="normal")
            self._update_ui(self._safe_config, self.reset_button, state="disabled")
            self._update_ui(self._safe_config, self.status_label, text="提醒已启动")
            
            # 更新模式按钮状态（锁定时变暗）
            self._update_mode_buttons_locked()
            
            if self.sound_enabled.get():
                self.play_sound("start.mp3")
            
            # 启动倒计时线程
            self.countdown_thread = threading.Thread(target=self.update_countdown, daemon=True)
            self.countdown_thread.start()
            
            logging.info("提醒启动成功")
            
        except Exception as e:
            logging.error(f"启动提醒失败: {e}")
            self.is_mode_locked = False
            self._update_ui(self._safe_config, self.status_label, text=f"启动失败: {str(e)}")

    def _stop_reminder(self):
        """停止提醒"""
        # 记录会话结束
        self._record_session_end()
        
        # 解锁模式
        self.is_mode_locked = False
        
        # 恢复模式按钮状态
        self._restore_mode_buttons()
        
        if self.sound_enabled.get():
            self.play_sound("stop.mp3")
        self._stop_countdown()
        self._update_ui(self._safe_config, self.status_label, text="提醒已停止")
        logging.info("提醒已停止")

    def _restore_mode_buttons(self):
        """恢复模式按钮的正常状态（兼容Canvas版本和传统按钮版本）"""
        # 检查是否使用Canvas版本的模式按钮
        if hasattr(self, 'preset_canvas') and self.preset_canvas:
            # Canvas版本的按钮不需要恢复状态，直接更新显示
            self._update_mode_buttons()
            return
            
        # 传统按钮版本的恢复
        for mode_key, button in self.mode_buttons.items():
            # 检查button是否真的是一个按钮对象而不是字典
            if not isinstance(button, dict) and hasattr(button, 'configure'):
                # 使用安全配置方法
                self._safe_config(button, state='normal')
            
                # 重新绑定点击事件
                def make_select_handler(mode_key):
                    return lambda: self._select_work_mode(mode_key)
                
                self._safe_config(button, command=make_select_handler(mode_key))
            
        # 更新显示状态
        self._update_mode_buttons()

    def toggle_pause(self):
        """切换暂停状态"""
        # 恢复置顶刷新（如果从浮动窗口菜单调用）
        if hasattr(self, '_pause_floating_top_refresh'):
            self._pause_floating_top_refresh = False
            
        if not self.is_running:
            return
            
        if self.is_paused:
            # 恢复
            if self.pause_time:
                self.total_pause_duration += (datetime.datetime.now() - self.pause_time).total_seconds()
                self.pause_time = None
            
            self.is_paused = False
            self._update_ui(self._safe_config, self.pause_button, text="⏸️ 暂停")
            self._update_ui(self._safe_config, self.status_label, text="提醒已恢复")
            # 更新浮动窗口状态
            current_countdown = self.countdown_label.cget("text") if hasattr(self, 'countdown_label') else "总倒计时: --:--"
            self._update_ui(self.update_floating_window, current_countdown, "运行中")
            logging.info("提醒恢复")
        else:
            # 暂停
            self.is_paused = True
            self.pause_time = datetime.datetime.now()
            self._update_ui(self._safe_config, self.pause_button, text="▶️ 恢复")
            self._update_ui(self._safe_config, self.status_label, text="提醒已暂停")
            # 更新浮动窗口状态
            current_countdown = self.countdown_label.cget("text") if hasattr(self, 'countdown_label') else "总倒计时: --:--"
            self._update_ui(self.update_floating_window, current_countdown, "暂停中")
            logging.info("提醒暂停")

    def reset_timer(self):
        """重置计时器和所有设置到初始状态"""
        # 防抖机制：防止重复快速点击
        current_time = time.time()
        if current_time - self.last_reset_time < 1.0:  # 1秒内不允许重复重置
            return
        self.last_reset_time = current_time
        
        # 首先停止当前运行的计时器
        if self.is_running:
            self._stop_reminder()
        
        # 重置所有设置变量到默认值
        self._update_ui(self.total_minutes_var.set, "90")
        self._update_ui(self.interval_minutes_var.set, "5")
        self._update_ui(self.random_minutes_var.set, "2")
        self._update_ui(self.second_reminder_var.set, "10")
        
        # 重置显示界面
        self._update_ui(self._safe_config, self.countdown_label, text="00:00:00")
        self._update_ui(self._safe_config, self.progress_info_label, text="进度 0%")
        
        # 重置圆形进度条
        self._update_ui(self._update_circle_progress, 0)
        
        # 重置按钮状态
        self._update_ui(self._safe_config, self.start_button, text=f"{self.icons['rocket']} 开始专注", state="normal")
        self._update_ui(self._safe_config, self.pause_button, text=f"{self.icons['pause']} 暂停", state="disabled")
        self._update_ui(self._safe_config, self.reset_button, state="normal")
        
        # 重置状态变量
        self.is_running = False
        self.is_paused = False
        self.pause_time = None
        self.total_pause_duration = 0
        self.is_mode_locked = False  # 解锁模式
        self.current_work_mode = 'study'  # 重置为默认深度学习模式
        
        # 恢复模式按钮状态
        self._restore_mode_buttons()
        
        # 重新应用默认模式
        self._apply_default_work_mode()
        
        # 重置小窗口
        if self.mini_window and self.mini_window.winfo_exists():
            self._update_ui(self.update_mini_window, "总倒计时: --:--")
        
        # 重置浮动窗口
        self._update_ui(self.update_floating_window, "总倒计时: --:--", "已重置")
        
        # 更新状态信息
        self._update_ui(self._safe_config, self.status_label, text="✅ 所有设置已重置到默认值")
        logging.info("计时器和设置已完全重置")

    def toggle_mini_window(self):
        """小窗口功能已被禁用"""
        # 该功能已被禁用
        logging.info("小窗口功能已被禁用")
        return

    def create_mini_window(self):
        """小窗口功能已被禁用"""
        # 该功能已被禁用
        return

    def close_mini_window(self):
        """关闭小窗口（已禁用）"""
        # 无需执行任何操作
        pass

    def close_mini_window_and_uncheck(self):
        """关闭小窗口并取消选中（已禁用）"""
        self.mini_window_enabled.set(False)
        # 无需执行关闭操作
        pass

    def update_mini_window(self, countdown_text):
        """更新小窗口显示（已禁用）"""
        # 无需执行任何操作
        pass

    def minimize_to_tray(self):
        """最小化到系统托盘"""
        # 防止重复最小化
        if self.is_minimized_to_tray:
            return
        
        # 检查 floating_enabled 是否存在且可用
        try:
            floating_enabled = hasattr(self, 'floating_enabled') and self.floating_enabled.get()
        except:
            floating_enabled = True  # 默认启用浮动窗口
            
        self.is_minimized_to_tray = True
        self.root.withdraw()  # 隐藏主窗口
        # 小窗口功能已禁用，不需要关闭
        
        # 只有当托盘图标不存在时才创建
        if not self.tray_icon:
            self.create_tray_icon()   # 创建托盘图标
            
        if floating_enabled:
            self.create_floating_window()  # 创建浮动窗口
        logging.info("程序最小化到系统托盘")

    def create_tray_icon(self):
        """创建系统托盘图标"""
        # 创建简单的图标图像
        image = Image.new('RGB', (64, 64), color=(240, 242, 245))
        draw = ImageDraw.Draw(image)
        
        # 绘制圆形背景
        draw.ellipse([16, 16, 48, 48], fill=(26, 115, 232))
        # 绘制时钟指针
        draw.line([32, 32, 32, 20], fill=(255, 255, 255), width=2)
        draw.line([32, 32, 42, 32], fill=(255, 255, 255), width=2)
        
        # 创建托盘菜单
        menu = pystray.Menu(
            pystray.MenuItem("显示主窗口", self.show_main_window),
            pystray.MenuItem("切换浮动窗口", self.toggle_floating_window),
            pystray.Menu.SEPARATOR,
            # 添加快速控制菜单
            pystray.MenuItem("开始/停止计时", self._toggle_timer_from_tray),
            pystray.MenuItem("暂停/继续", self._toggle_pause_from_tray, 
                           enabled=lambda item: self.is_running),
            pystray.MenuItem("重置计时", self._reset_timer_from_tray),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("退出程序", self.quit_application)
        )
        
        self.tray_icon = pystray.Icon("时间提醒助手", image, menu=menu)
        
        # 在单独线程中运行托盘图标
        threading.Thread(target=self.tray_icon.run, daemon=True).start()

    def _toggle_timer_from_tray(self, icon=None, item=None):
        """从系统托盘切换计时状态"""
        try:
            self.toggle_reminder()
            logging.info("从系统托盘切换计时状态")
        except Exception as e:
            logging.error(f"从系统托盘切换计时状态失败: {e}")

    def _toggle_pause_from_tray(self, icon=None, item=None):
        """从系统托盘切换暂停状态"""
        try:
            if self.is_running:
                self.toggle_pause()
                logging.info("从系统托盘切换暂停状态")
        except Exception as e:
            logging.error(f"从系统托盘切换暂停状态失败: {e}")

    def _reset_timer_from_tray(self, icon=None, item=None):
        """从系统托盘重置计时"""
        try:
            self.reset_timer()
            logging.info("从系统托盘重置计时")
        except Exception as e:
            logging.error(f"从系统托盘重置计时失败: {e}")

    def show_main_window(self, icon=None, item=None):
        """显示主窗口"""
        # 恢复置顶刷新（如果从浮动窗口菜单调用）
        if hasattr(self, '_pause_floating_top_refresh'):
            self._pause_floating_top_refresh = False
            
        # 防止重复恢复
        if not self.is_minimized_to_tray:
            return
            
        self.is_minimized_to_tray = False
        self.root.deiconify()  # 显示窗口
        self.root.lift()       # 提升到前台
        self.root.focus_force() # 获取焦点
        self.close_floating_window()  # 关闭浮动窗口
        
        # 停止托盘图标
        if self.tray_icon:
            try:
                self.tray_icon.stop()
            except:
                pass
            self.tray_icon = None
        logging.info("从系统托盘恢复主窗口")

    def toggle_floating_window(self, icon=None, item=None):
        """切换浮动窗口显示"""
        try:
            if hasattr(self, 'floating_enabled') and self.floating_enabled:
                self.floating_enabled.set(not self.floating_enabled.get())
                if self.is_minimized_to_tray:
                    if self.floating_enabled.get():
                        self.create_floating_window()
                    else:
                        self.close_floating_window()
        except Exception as e:
            logging.error(f"切换浮动窗口失败: {e}")

    def create_floating_window(self):
        """创建右上角浮动窗口"""
        if self.floating_window and self.floating_window.winfo_exists():
            return
            
        self.floating_window = tk.Toplevel()
        self.floating_window.title("倒计时")
        self.floating_window.resizable(False, False)
        self.floating_window.overrideredirect(True)  # 无边框窗口
        
        # 设置窗口位置到右上角
        screen_width = self.floating_window.winfo_screenwidth()
        window_width = 280
        window_height = 100
        x = screen_width - window_width - 20  # 距离右边20像素
        y = 20  # 距离顶部20像素
        
        self.floating_window.geometry(f"{window_width}x{window_height}+{x}+{y}")
        
        # 强制置顶设置
        self.floating_window.wm_attributes("-topmost", True)
        self.floating_window.attributes('-topmost', True)
        
        # 设置透明度和样式
        try:
            self.floating_window.attributes('-alpha', 0.9)
        except:
            pass
        
        # 设置窗口背景
        self.floating_window.configure(bg="#1a1a1a")
        
        # 创建主框架
        main_frame = tk.Frame(self.floating_window, bg="#1a1a1a", padx=10, pady=10)
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # 标题标签
        title_label = tk.Label(
            main_frame,
            text="⏰ 时间提醒",
            font=("Microsoft YaHei UI", 10, "bold"),
            bg="#1a1a1a",
            fg="#00ff88",
            anchor='w'
        )
        title_label.pack(fill=tk.X)
        
        # 倒计时显示标签
        self.floating_countdown_label = tk.Label(
            main_frame,
            text="总倒计时: --:--",
            font=("Consolas", 14, "bold"),
            bg="#1a1a1a",
            fg="#ffffff",
            anchor='w'
        )
        self.floating_countdown_label.pack(fill=tk.X)
        
        # 状态标签
        self.floating_status_label = tk.Label(
            main_frame,
            text="待机中",
            font=("Microsoft YaHei UI", 8),
            bg="#1a1a1a",
            fg="#888888",
            anchor='w'
        )
        self.floating_status_label.pack(fill=tk.X)
        
        # 创建右击菜单
        self.floating_context_menu = tk.Menu(self.floating_window, tearoff=0, 
                                           bg="#2d2d2d", fg="white", 
                                           activebackground="#404040", 
                                           activeforeground="white",
                                           font=("Microsoft YaHei UI", 9))
        
        # 添加菜单项
        self.floating_context_menu.add_command(label="🏠 显示主窗口", 
                                             command=self.show_main_window)
        self.floating_context_menu.add_separator()
        
        # 动态菜单项 - 开始/停止
        if self.is_running:
            self.floating_context_menu.add_command(label="⏹️ 停止计时", 
                                                 command=self._stop_timer_from_floating)
        else:
            self.floating_context_menu.add_command(label="▶️ 开始计时", 
                                                 command=self._start_timer_from_floating)
        
        # 动态菜单项 - 暂停/继续
        if self.is_running:
            if self.is_paused:
                self.floating_context_menu.add_command(label="▶️ 继续计时", 
                                                     command=self.toggle_pause)
            else:
                self.floating_context_menu.add_command(label="⏸️ 暂停计时", 
                                                     command=self.toggle_pause)
        
        self.floating_context_menu.add_separator()
        self.floating_context_menu.add_command(label="🔄 重置计时", 
                                             command=self._reset_timer_from_floating)
        self.floating_context_menu.add_separator()
        self.floating_context_menu.add_command(label="❌ 关闭浮动窗口", 
                                             command=self._close_floating_from_menu)
        self.floating_context_menu.add_command(label="🚪 退出程序", 
                                             command=self.quit_application)
        
        # 绑定右击事件到所有组件
        def show_context_menu(event):
            try:
                # 暂停置顶刷新
                self._pause_floating_top_refresh = True
                
                # 更新菜单状态
                self._update_floating_context_menu()
                
                # 确保菜单显示在最顶层
                self.floating_context_menu.post(event.x_root, event.y_root)
                
                # 设置菜单关闭后的回调
                def on_menu_close():
                    # 延迟恢复置顶刷新，确保菜单完全关闭
                    self.floating_window.after(500, lambda: setattr(self, '_pause_floating_top_refresh', False))
                
                # 重新绑定菜单关闭事件
                self.floating_context_menu.bind('<Unmap>', lambda e: on_menu_close())
                
                # 点击菜单外部也要恢复刷新
                def on_focus_out(event):
                    on_menu_close()
                
                self.floating_context_menu.bind('<FocusOut>', on_focus_out)
                
            except Exception as e:
                logging.error(f"显示右击菜单失败: {e}")
                self._pause_floating_top_refresh = False
        
        # 为所有组件绑定右击菜单
        self.floating_window.bind("<Button-3>", show_context_menu)
        main_frame.bind("<Button-3>", show_context_menu)
        title_label.bind("<Button-3>", show_context_menu)
        self.floating_countdown_label.bind("<Button-3>", show_context_menu)
        self.floating_status_label.bind("<Button-3>", show_context_menu)
        
        # 绑定双击事件显示主窗口
        self.floating_window.bind("<Double-Button-1>", lambda e: self.show_main_window())
        title_label.bind("<Double-Button-1>", lambda e: self.show_main_window())
        self.floating_countdown_label.bind("<Double-Button-1>", lambda e: self.show_main_window())
        self.floating_status_label.bind("<Double-Button-1>", lambda e: self.show_main_window())
        
        # 支持拖拽移动
        self._make_draggable(self.floating_window)
        
        # 初始化置顶刷新控制标志
        self._pause_floating_top_refresh = False
        
        # 定期保持置顶
        def keep_floating_on_top():
            if self.floating_window and self.floating_window.winfo_exists():
                # 只有在未暂停时才执行置顶
                if not getattr(self, '_pause_floating_top_refresh', False):
                    self.floating_window.lift()
                self.floating_window.after(2000, keep_floating_on_top)
        
        keep_floating_on_top()
        logging.info("浮动窗口已创建（支持右击菜单）")

    def _update_floating_context_menu(self):
        """更新浮动窗口右击菜单的状态"""
        if not hasattr(self, 'floating_context_menu'):
            return
            
        try:
            # 清除现有菜单项
            self.floating_context_menu.delete(0, tk.END)
            
            # 重新添加菜单项
            self.floating_context_menu.add_command(label="🏠 显示主窗口", 
                                                 command=self.show_main_window)
            self.floating_context_menu.add_separator()
            
            # 动态菜单项 - 开始/停止
            if self.is_running:
                self.floating_context_menu.add_command(label="⏹️ 停止计时", 
                                                     command=self._stop_timer_from_floating)
            else:
                self.floating_context_menu.add_command(label="▶️ 开始计时", 
                                                     command=self._start_timer_from_floating)
            
            # 动态菜单项 - 暂停/继续
            if self.is_running:
                if self.is_paused:
                    self.floating_context_menu.add_command(label="▶️ 继续计时", 
                                                         command=self.toggle_pause)
                else:
                    self.floating_context_menu.add_command(label="⏸️ 暂停计时", 
                                                         command=self.toggle_pause)
            
            self.floating_context_menu.add_separator()
            self.floating_context_menu.add_command(label="🔄 重置计时", 
                                                 command=self._reset_timer_from_floating)
            self.floating_context_menu.add_separator()
            self.floating_context_menu.add_command(label="❌ 关闭浮动窗口", 
                                                 command=self._close_floating_from_menu)
            self.floating_context_menu.add_command(label="🚪 退出程序", 
                                                 command=self.quit_application)
        except Exception as e:
            logging.error(f"更新右击菜单失败: {e}")

    def _start_timer_from_floating(self):
        """从浮动窗口开始计时"""
        try:
            # 恢复置顶刷新
            self._pause_floating_top_refresh = False
            if not self.is_running:
                self.toggle_reminder()
                logging.info("从浮动窗口开始计时")
        except Exception as e:
            logging.error(f"从浮动窗口开始计时失败: {e}")

    def _stop_timer_from_floating(self):
        """从浮动窗口停止计时"""
        try:
            # 恢复置顶刷新
            self._pause_floating_top_refresh = False
            if self.is_running:
                self.toggle_reminder()
                logging.info("从浮动窗口停止计时")
        except Exception as e:
            logging.error(f"从浮动窗口停止计时失败: {e}")

    def _reset_timer_from_floating(self):
        """从浮动窗口重置计时"""
        try:
            # 恢复置顶刷新
            self._pause_floating_top_refresh = False
            # 确认重置操作
            if self.is_running:
                # 创建临时确认窗口
                confirm_window = tk.Toplevel()
                confirm_window.title("确认重置")
                confirm_window.geometry("260x120")
                confirm_window.resizable(False, False)
                confirm_window.configure(bg="#f0f0f0")
                confirm_window.wm_attributes("-topmost", True)
                confirm_window.attributes('-topmost', True)
                
                # 居中显示
                screen_width = confirm_window.winfo_screenwidth()
                screen_height = confirm_window.winfo_screenheight()
                x = (screen_width // 2) - 130
                y = (screen_height // 2) - 60
                confirm_window.geometry(f"260x120+{x}+{y}")
                
                # 确认消息
                msg_label = tk.Label(confirm_window, 
                                   text="确定要重置当前计时吗？\n这将停止计时并清除进度。",
                                   font=("Microsoft YaHei UI", 10),
                                   bg="#f0f0f0", fg="#333333",
                                   justify=tk.CENTER)
                msg_label.pack(pady=10)
                
                # 按钮框架
                btn_frame = tk.Frame(confirm_window, bg="#f0f0f0")
                btn_frame.pack(pady=10)
                
                def do_reset():
                    confirm_window.destroy()
                    self.reset_timer()
                    logging.info("从浮动窗口重置计时")
                
                def cancel_reset():
                    confirm_window.destroy()
                
                # 确认按钮
                confirm_btn = tk.Button(btn_frame, text="确定", 
                                      command=do_reset,
                                      bg="#d93025", fg="white",
                                      font=("Microsoft YaHei UI", 9),
                                      width=8, height=1,
                                      relief=tk.FLAT, bd=0)
                confirm_btn.pack(side=tk.LEFT, padx=5)
                
                # 取消按钮
                cancel_btn = tk.Button(btn_frame, text="取消", 
                                     command=cancel_reset,
                                     bg="#5f6368", fg="white",
                                     font=("Microsoft YaHei UI", 9),
                                     width=8, height=1,
                                     relief=tk.FLAT, bd=0)
                cancel_btn.pack(side=tk.LEFT, padx=5)
                
                # 关闭窗口时取消
                confirm_window.protocol("WM_DELETE_WINDOW", cancel_reset)
                
                # 自动聚焦到确认窗口
                confirm_window.focus_force()
                confirm_window.grab_set()
                
            else:
                # 未运行时直接重置
                self.reset_timer()
                logging.info("从浮动窗口重置计时")
                
        except Exception as e:
            logging.error(f"从浮动窗口重置计时失败: {e}")

    def _close_floating_from_menu(self):
        """从菜单关闭浮动窗口"""
        try:
            # 恢复置顶刷新
            self._pause_floating_top_refresh = False
            self.floating_enabled.set(False)
            self.close_floating_window()
            logging.info("从菜单关闭浮动窗口")
        except Exception as e:
            logging.error(f"从菜单关闭浮动窗口失败: {e}")

    def _make_draggable(self, window):
        """使窗口可拖拽"""
        def start_drag(event):
            window.start_x = event.x
            window.start_y = event.y

        def on_drag(event):
            x = window.winfo_x() + event.x - window.start_x
            y = window.winfo_y() + event.y - window.start_y
            window.geometry(f"+{x}+{y}")

        # 使用左键拖拽，避免与右键菜单冲突
        window.bind("<Button-1>", start_drag)
        window.bind("<B1-Motion>", on_drag)
        
        # 添加鼠标悬停效果
        def on_enter(event):
            try:
                window.attributes('-alpha', 1.0)  # 完全不透明
            except:
                pass
        
        def on_leave(event):
            try:
                window.attributes('-alpha', 0.9)  # 恢复半透明
            except:
                pass
        
        window.bind("<Enter>", on_enter)
        window.bind("<Leave>", on_leave)

    def close_floating_window(self):
        """关闭浮动窗口"""
        if self.floating_window:
            try:
                self.floating_window.destroy()
                self.floating_window = None
                logging.info("浮动窗口已关闭")
            except:
                pass

    def update_floating_window(self, countdown_text, status_text="运行中"):
        """更新浮动窗口显示"""
        if self.floating_window and self.floating_window.winfo_exists():
            try:
                self.floating_countdown_label.config(text=countdown_text)
                self.floating_status_label.config(text=status_text)
            except:
                pass

    def _trigger_screen_dim_effect(self):
        """触发屏幕变暗效果"""
        try:
            self._create_dim_window()
            
            # 在新线程中控制变暗效果的持续时间
            def dim_effect_controller():
                # 变暗持续10秒
                time.sleep(10.0)
                self._close_dim_window()
                
            threading.Thread(target=dim_effect_controller, daemon=True).start()
            logging.info("屏幕变暗效果已触发，持续10秒")
            
        except Exception as e:
            logging.error(f"屏幕变暗效果失败: {e}")

    def _create_dim_window(self):
        """创建屏幕变暗窗口"""
        try:
            if self.dim_window and self.dim_window.winfo_exists():
                return  # 如果窗口已存在，不重复创建
                
            # 创建全屏透明黑色窗口
            self.dim_window = tk.Toplevel()
            self.dim_window.title("Screen Dim")
            
            # 获取屏幕尺寸
            screen_width = self.dim_window.winfo_screenwidth()
            screen_height = self.dim_window.winfo_screenheight()
            
            # 设置为全屏
            self.dim_window.geometry(f"{screen_width}x{screen_height}+0+0")
            
            # 设置窗口属性
            self.dim_window.configure(bg='black')
            self.dim_window.overrideredirect(True)  # 去除窗口边框
            self.dim_window.attributes('-topmost', True)  # 置顶显示
            self.dim_window.attributes('-alpha', 0.7)  # 70%透明度，更明显
            
            # 检查是否启用强制变暗模式
            is_force_mode = self.force_screen_dim.get()
            
            if not is_force_mode:
                # 普通模式：阻止窗口获取焦点，支持点击穿透
                self.dim_window.attributes('-disabled', True)
                
                # 添加点击穿透效果（Windows系统）
                try:
                    import ctypes
                    from ctypes import wintypes
                    hwnd = self.dim_window.winfo_id()
                    # 设置窗口样式为点击穿透
                    style = ctypes.windll.user32.GetWindowLongW(hwnd, -20)  # GWL_EXSTYLE
                    style |= 0x20  # WS_EX_TRANSPARENT
                    ctypes.windll.user32.SetWindowLongW(hwnd, -20, style)
                except:
                    pass  # 如果设置失败，忽略错误
                
                logging.info("屏幕变暗窗口已创建（普通模式，支持点击穿透）")
            else:
                # 强制模式：不设置点击穿透，强制显示10秒
                self.dim_window.focus_force()  # 强制获取焦点
                
                # 禁用Alt+Tab和其他快捷键（尽量）
                self.dim_window.bind('<Alt-Tab>', lambda e: 'break')
                self.dim_window.bind('<Control-Alt-Delete>', lambda e: 'break')
                
                logging.info("屏幕变暗窗口已创建（强制模式，不可点击穿透）")
                
            # 获取要显示的标语
            display_message = self.get_random_dim_message()
                
            # 添加提示文本
            hint_label = tk.Label(
                self.dim_window,
                text=display_message,
                font=('Microsoft YaHei UI', 28, 'bold'),
                fg='white',
                bg='black'
            )
            hint_label.place(relx=0.5, rely=0.5, anchor='center')
            
            # 如果是强制模式，添加倒计时显示
            if is_force_mode:
                self._start_countdown_display()
            
        except Exception as e:
            logging.error(f"创建屏幕变暗窗口失败: {e}")

    def _start_countdown_display(self):
        """在强制模式下显示倒计时"""
        try:
            if not self.dim_window or not self.dim_window.winfo_exists():
                return
                
            # 添加倒计时标签
            countdown_label = tk.Label(
                self.dim_window,
                text="还有 10 秒",
                font=('Microsoft YaHei UI', 16),
                fg='#ffcc00',
                bg='black'
            )
            countdown_label.place(relx=0.5, rely=0.6, anchor='center')
            
            # 倒计时更新函数
            def update_countdown(remaining):
                if self.dim_window and self.dim_window.winfo_exists() and remaining > 0:
                    countdown_label.config(text=f"还有 {remaining} 秒")
                    self.dim_window.after(1000, lambda: update_countdown(remaining - 1))
                    
            # 开始倒计时
            update_countdown(10)
            
        except Exception as e:
            logging.error(f"倒计时显示失败: {e}")

    def _close_dim_window(self):
        """关闭屏幕变暗窗口"""
        try:
            if self.dim_window and self.dim_window.winfo_exists():
                self._update_ui(self.dim_window.destroy)
                self.dim_window = None
                logging.info("屏幕变暗窗口已关闭")
        except Exception as e:
            logging.error(f"关闭屏幕变暗窗口失败: {e}")

    def quit_application(self, icon=None, item=None):
        """完全退出应用程序"""
        self.quit_application_directly()
    
    def force_quit(self):
        """强制退出程序"""
        try:
            import sys
            import os
            
            # 停止所有线程
            self.is_running = False
            self.is_paused = False
            
            # 强制退出pygame
            try:
                pygame.mixer.quit()
            except:
                pass
            
            # 强制退出程序
            os._exit(0)
        except:
            # 最后的保险
            import sys
            sys.exit()

    def on_closing(self):
        """程序关闭时的清理工作"""
        try:
            # 检查是否选择最小化到托盘
            minimize_enabled = hasattr(self, 'minimize_on_close') and self.minimize_on_close.get()
        except:
            minimize_enabled = True  # 默认最小化到托盘
            
        if minimize_enabled:
            # 最小化到系统托盘
            self.minimize_to_tray()
        else:
            # 直接退出程序
            self.quit_application_directly()
    
    def quit_application_directly(self):
        """直接退出程序（不通过托盘）"""
        if self.is_running:
            self.is_running = False
        
        # 关闭小窗口和浮动窗口
        self.close_mini_window()
        self.close_floating_window()
        
        # 关闭屏幕变暗窗口
        self._close_dim_window()
        
        # 停止系统托盘图标（如果存在）
        if hasattr(self, 'tray_icon') and self.tray_icon:
            try:
                self.tray_icon.stop()
            except:
                pass
            self.tray_icon = None
            
        try:
            pygame.mixer.quit()
        except:
            pass
            
        logging.info("程序正常退出")
        try:
            self.root.quit()
            self.root.destroy()
        except:
            pass

    def run(self):
        """运行程序"""
        try:
            # 启动后台线程修复Frame背景色问题
            def fix_backgrounds():
                """定期检查并修复所有Frame背景色"""
                try:
                    while True:
                        # 递归函数设置所有帧的背景为surface_elevated
                        def set_bg_recursive(widget):
                            if isinstance(widget, tk.Frame) and not isinstance(widget, tk.Button):
                                try:
                                    current_bg = widget.cget('bg')
                                    if current_bg == '#F5F5F5' or current_bg == 'white':
                                        widget.configure(bg=self.colors['surface_elevated'])
                                except:
                                    pass
                            
                            # 递归处理子组件
                            try:
                                for child in widget.winfo_children():
                                    set_bg_recursive(child)
                            except:
                                pass
                        
                        # 设置背景色
                        if hasattr(self, 'root') and self.root:
                            set_bg_recursive(self.root)
                        
                        # 短暂休眠
                        time.sleep(0.05)
                except:
                    pass
            
            # 启动背景色修复线程
            bg_fix_thread = threading.Thread(target=fix_backgrounds, daemon=True)
            bg_fix_thread.start()
            logging.info("已启动背景色自动修复线程")
            
            # 启动主循环
            self.root.mainloop()
            
        except Exception as e:
            logging.error(f"程序运行错误: {e}")
        finally:
            try:
                pygame.mixer.quit()
            except:
                pass

    def _setup_keyboard_shortcuts(self):
        """设置键盘快捷键"""
        try:
            # 绑定全局快捷键到主窗口
            self.root.bind('<Control-s>', lambda e: self.toggle_reminder())  # Ctrl+S 开始/停止
            self.root.bind('<Control-p>', lambda e: self.toggle_pause())     # Ctrl+P 暂停/继续
            self.root.bind('<Control-r>', lambda e: self.reset_timer())      # Ctrl+R 重置
            self.root.bind('<Control-m>', lambda e: self.minimize_to_tray()) # Ctrl+M 最小化到托盘
            self.root.bind('<F1>', lambda e: self._show_help())              # F1 显示帮助
            self.root.bind('<Escape>', lambda e: self.minimize_to_tray())    # ESC 最小化
            
            # 全局拦截所有组件的Enter和Leave事件
            def hover_event_interceptor(event):
                # 根据事件类型区分处理
                if hasattr(event, 'widget'):
                    # 如果不是按钮，阻止默认的悬停行为
                    if not isinstance(event.widget, tk.Button):
                        return "break"
                return
                
            # 绑定全局鼠标悬停拦截器
            self.root.bind_all("<Enter>", hover_event_interceptor, "+")
            self.root.bind_all("<Leave>", hover_event_interceptor, "+")
            self.root.bind_all("<Motion>", hover_event_interceptor, "+")
            
            # 确保窗口能接收键盘事件
            self.root.focus_set()
            
            logging.info("键盘快捷键和全局事件拦截设置完成")
        except Exception as e:
            logging.error(f"设置键盘快捷键失败: {e}")

    def _show_help(self):
        """显示帮助信息"""
        help_text = """时间提醒助手 v2.2 - 快捷键说明

🎯 快捷键：
• Ctrl+S    开始/停止计时
• Ctrl+P    暂停/继续计时  
• Ctrl+R    重置计时
• Ctrl+M    最小化到系统托盘
• F1        显示此帮助
• ESC       最小化窗口

🖱️ 浮动窗口操作：
• 左键拖拽   移动窗口位置
• 双击      显示主窗口
• 右键      打开功能菜单
• 鼠标悬停   窗口变为不透明

🌙 屏幕变暗功能：
• 可在设置中勾选"提醒时屏幕变暗效果"
• 提醒时屏幕变暗10秒，显示"牛马歇一会吧！"
• 普通模式：支持点击穿透，不影响操作
• 强制模式：不可点击穿透，强制休息10秒

💡 提示：
程序最小化到系统托盘后，可通过托盘图标快速控制。
浮动窗口提供便捷的右键菜单操作。
屏幕变暗功能特别适合研究学习场景。

🔽 关闭行为设置：
• 默认点击关闭按钮最小化到托盘，不退出程序
• 可在设置中取消勾选"关闭窗口时最小化到系统托盘"
• 也可点击主界面底部的关闭行为提示快速切换
• Ctrl+Q 始终为强制退出程序"""

        # 创建帮助窗口
        help_window = tk.Toplevel(self.root)
        help_window.title("帮助 - 时间提醒助手")
        help_window.geometry("400x380")
        help_window.resizable(False, False)
        help_window.configure(bg="#f8f9fa")
        
        # 居中显示
        help_window.transient(self.root)
        help_window.grab_set()
        
        # 计算居中位置
        self.root.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width() // 2) - 200
        y = self.root.winfo_y() + (self.root.winfo_height() // 2) - 190
        help_window.geometry(f"400x380+{x}+{y}")
        
        # 添加滚动文本框
        text_frame = tk.Frame(help_window, bg="#f8f9fa")
        text_frame.pack(fill=tk.BOTH, expand=True, padx=15, pady=15)
        
        # 创建文本框和滚动条
        text_widget = tk.Text(text_frame, 
                            font=("Microsoft YaHei UI", 10),
                            bg="white", fg="#333333",
                            wrap=tk.WORD, 
                            padx=15, pady=15,
                            selectbackground="#e3f2fd",
                            relief=tk.FLAT, bd=0)
        
        scrollbar = ttk.Scrollbar(text_frame, orient=tk.VERTICAL, command=text_widget.yview)
        text_widget.configure(yscrollcommand=scrollbar.set)
        
        # 插入帮助文本
        text_widget.insert(tk.END, help_text)
        text_widget.config(state=tk.DISABLED)  # 只读
        
        # 布局
        text_widget.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # 关闭按钮
        close_btn = tk.Button(help_window, text="知道了", 
                            command=help_window.destroy,
                            bg="#1a73e8", fg="white",
                            font=("Microsoft YaHei UI", 10, "bold"),
                            width=12, height=1,
                            relief=tk.FLAT, bd=0,
                            cursor="hand2")
        close_btn.pack(pady=(0, 15))
        
        # ESC 关闭
        help_window.bind('<Escape>', lambda e: help_window.destroy())
        help_window.focus_set()

    def _create_status_frame(self, parent):
        """创建现代化状态区域"""
        # 状态容器
        status_container = tk.Frame(parent, bg=self.colors['background'])
        status_container.pack(fill=tk.X, padx=(self.dimensions['spacing_s'], self.dimensions['spacing_s']), pady=self.dimensions['spacing_s'])
        
        # 状态卡片
        status_card = self._create_apple_card(status_container, elevated=True)
        status_card.pack(fill=tk.X)
        
        # 设置最大宽度
        status_container.configure(width=390)
        
        # 获取实际的卡片框架
        card_frame = status_card.winfo_children()[0]
        
        # 状态标题
        status_title = tk.Label(
            card_frame,
            text=f"{self.icons['status']} 状态信息",
            font=self.current_fonts['headline'],
            fg=self.colors['text_primary'],
            bg=self.colors['surface_elevated']
        )
        status_title.pack(pady=(0, self.dimensions['spacing_s']))
        
        # 主状态显示
        self.status_label = tk.Label(
            card_frame, 
            text="音频文件检查完成", 
            font=self.current_fonts['body'],
            fg=self.colors['text_secondary'],
            bg=self.colors['surface_elevated'],
            wraplength=280,
            justify='center'
        )
        self.status_label.pack(fill=tk.X, pady=(0, self.dimensions['spacing_m']))
        
        # 统计信息部分 - 整合到同一卡片
        # 分隔线
        separator = tk.Frame(card_frame, bg=self.colors['separator'], height=1)
        separator.pack(fill=tk.X, pady=self.dimensions['spacing_s'])
        
        # 统计标题
        stats_title = tk.Label(
            card_frame,
            text=f"{self.icons['today']} 今日统计",
            font=self.current_fonts['subheadline'],
            fg=self.colors['text_primary'],
            bg=self.colors['surface_elevated']
        )
        stats_title.pack(pady=(self.dimensions['spacing_s'], self.dimensions['spacing_s']))
        
        # 统计数据显示
        self.stats_label = tk.Label(
            card_frame,
            text="工作时间: 0分钟 | 专注会话: 14次",
            font=self.current_fonts['callout'],
            fg=self.colors['text_secondary'],
            bg=self.colors['surface_elevated']
        )
        self.stats_label.pack()
        
        # 初始化统计显示
        self._update_stats_display()
        
        # 简化的快捷键提示 - 在底部
        shortcuts_container = tk.Frame(parent, bg=self.colors['background'])
        shortcuts_container.pack(fill=tk.X, padx=(self.dimensions['spacing_s'], self.dimensions['spacing_s']), pady=(0, self.dimensions['spacing_s']))
        
        # 快捷键提示 - 更简洁
        shortcuts_text = f"{self.icons['keyboard']} 快捷键: Ctrl+S(开始/停止) | Ctrl+P(暂停) | Ctrl+R(重置) | Ctrl+Q(强制退出) | F1(帮助)"
        shortcuts_label = tk.Label(
            shortcuts_container,
            text=shortcuts_text,
            font=self.current_fonts['footnote'],
            fg=self.colors['text_tertiary'],
            bg=self.colors['background'],
            cursor='hand2',
            wraplength=400
        )
        shortcuts_label.pack(pady=self.dimensions['spacing_xs'])
        
        # 点击快捷键提示显示帮助
        shortcuts_label.bind('<Button-1>', lambda e: self._show_help())
        
        # 关闭行为提示 - 更简洁
        close_behavior_text = f"{self.icons['close']} 关闭行为: {'最小化到托盘' if self.minimize_on_close.get() else '直接退出程序'}"
        self.close_behavior_label = tk.Label(
            shortcuts_container,
            text=close_behavior_text,
            font=self.current_fonts['footnote'],
            fg=self.colors['text_tertiary'],
            bg=self.colors['background'],
            cursor='hand2'
        )
        self.close_behavior_label.pack()
        
        # 点击切换关闭行为
        self.close_behavior_label.bind('<Button-1>', self._toggle_close_behavior)
    
    def _toggle_close_behavior(self, event=None):
        """切换关闭行为"""
        current_value = self.minimize_on_close.get()
        self.minimize_on_close.set(not current_value)
        
        # 更新显示文本
        close_behavior_text = f"{self.icons['close']} 关闭行为: {'最小化到托盘' if self.minimize_on_close.get() else '直接退出程序'}"
        self.close_behavior_label.config(text=close_behavior_text)
        
        # 显示提示信息
        behavior = "最小化到托盘" if self.minimize_on_close.get() else "直接退出程序"
        self._update_ui(self._safe_config, self.status_label, text=f"关闭行为已切换为: {behavior}")
        
        logging.info(f"关闭行为已切换为: {behavior}")

    def _update_stats_display(self):
        """更新统计信息显示"""
        try:
            stats = self.get_today_stats()
            work_minutes = stats['work_time'] // 60
            sessions = stats['sessions']
            
            stats_text = f"工作时间: {work_minutes}分钟 | 专注会话: {sessions}次"
            
            # 如果当前有会话正在进行，显示实时时间
            if self.current_session_start:
                current_session_minutes = int((datetime.datetime.now() - self.current_session_start).total_seconds() // 60)
                stats_text += f" | 当前会话: {current_session_minutes}分钟"
            
            self._update_ui(self._safe_config, self.stats_label, text=stats_text)
            
        except Exception as e:
            logging.error(f"更新统计显示失败: {e}")

    def update_progress_display(self):
        """更新进度显示 - 兼容性方法"""
        # 这个方法保留用于兼容性，实际更新在_update_display中处理
        pass

    def open_slogan_manager_dialog(self):
        """打开标语管理对话框 - 支持分类管理和标语编辑"""
        try:
            # 记录日志
            logging.info("正在打开标语管理对话框...")
            # 导入所需模块
            import time
            
            # 创建对话框
            dialog = tk.Toplevel(self.root)
            dialog.title("标语管理")
            dialog.geometry("850x650")  # 更大的窗口尺寸，更舒适的视觉体验
            dialog.minsize(750, 600)    # 调整最小窗口尺寸
            dialog.resizable(True, True)
            dialog.transient(self.root)  # 设置为主窗口的临时窗口
            dialog.grab_set()  # 模态对话框
            
            # 设置对话框样式
            dialog.configure(bg=self.colors['background'])
            
            # 创建主框架
            main_frame = tk.Frame(dialog, bg=self.colors['background'])
            main_frame.pack(fill=tk.BOTH, expand=True, padx=24, pady=(20, 10))  # 调整边距
            
            # 标题区域 - 改进视觉风格
            header_frame = tk.Frame(main_frame, bg=self.colors['background'])
            header_frame.pack(fill=tk.X, pady=(0, 18))  # 增加标题与内容之间的间距
            
            # 使用更醒目的标题字体
            title_label = tk.Label(
                header_frame,
                text="📝 标语管理中心",
                font=(self.current_fonts['title'][0], 18, 'bold'),  # 更大更粗的标题字体
                fg=self.colors['primary'],  # 使用主题色
                bg=self.colors['background']
            )
            title_label.pack(side=tk.LEFT, anchor='w')
            
            # 精简说明文本
            description = tk.Label(
                header_frame,
                text="管理标语内容与分类",
                font=self.current_fonts['callout'],
                fg=self.colors['text_secondary'],
                bg=self.colors['background'],
                justify=tk.LEFT
            )
            description.pack(side=tk.LEFT, anchor='w', padx=(10, 0), pady=(4, 0))  # 微调间距
            
            # 分类选择区域 - 增强视觉效果
            category_frame = tk.Frame(main_frame, bg=self.colors['surface_secondary'], padx=15, pady=12, bd=1, highlightthickness=1, highlightbackground=self.colors['separator'])
            category_frame.pack(fill=tk.X, pady=(0, 15))
            
            category_label = tk.Label(
                category_frame,
                text="当前分类:",
                font=self.current_fonts['body_emphasis'] if 'body_emphasis' in self.current_fonts else self.current_fonts['body'],
                fg=self.colors['text_primary'],
                bg=self.colors['surface_secondary']
            )
            category_label.pack(side=tk.LEFT, padx=(0, 10))
            
            # 分类下拉菜单
            categories = list(self.slogan_categories.keys())
            self.selected_category = tk.StringVar(value=categories[0] if categories else "default")
            
            category_dropdown = ttk.Combobox(
                category_frame,
                textvariable=self.selected_category,
                values=categories,
                state="readonly",
                font=self.current_fonts['body'],
                width=20
            )
            category_dropdown.pack(side=tk.LEFT)
            
            # 标语数量统计显示 - 改进样式
            stats_frame = tk.Frame(category_frame, bg=self.colors['info_light'], padx=10, pady=4, bd=0)
            stats_frame.pack(side=tk.RIGHT, padx=10)
            
            stats_label = tk.Label(
                stats_frame,
                text="",  # 初始为空，后面会更新
                font=self.current_fonts['caption'],
                fg=self.colors['info'],
                bg=self.colors['info_light']
            )
            stats_label.pack()
            
            # 保存到对话框对象以便后续更新
            dialog.stats_label = stats_label
            
            # 创建Canvas滚动区域
            canvas_frame = tk.Frame(main_frame, bg=self.colors['background'], bd=0, highlightthickness=0)
            canvas_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 8))
            
            # 设计更精致的滚动条
            canvas = tk.Canvas(
                canvas_frame, 
                bg=self.colors['background'], 
                highlightthickness=0, 
                bd=0
            )
            
            # 自定义滚动条样式
            scrollbar = tk.Scrollbar(
                canvas_frame, 
                orient="vertical", 
                command=canvas.yview,
                width=10  # 稍微变窄的滚动条
            )
            
            # 内容框架 - 平滑边缘
            content_frame = tk.Frame(canvas, bg=self.colors['background'], bd=0)
            
            # 配置Canvas
            canvas.configure(yscrollcommand=scrollbar.set)
            canvas_window = canvas.create_window((0, 0), window=content_frame, anchor="nw")
            
            # 滚动区域更新函数
            def update_scroll_region(event=None):
                canvas.configure(scrollregion=canvas.bbox("all"))
                # 确保content_frame占据canvas的全部宽度
                canvas_width = canvas.winfo_width()
                if canvas_width > 1:
                    canvas.itemconfig(canvas_window, width=canvas_width)
            
            # 绑定事件以更新滚动区域
            content_frame.bind("<Configure>", update_scroll_region)
            canvas.bind("<Configure>", lambda e: canvas.itemconfig(canvas_window, width=e.width))
            
            # 鼠标滚轮滚动支持 - 更流畅的滚动
            def _on_mousewheel(event):
                try:
                    if canvas.winfo_exists():
                        # 调整滚动速度
                        scroll_speed = 2
                        canvas.yview_scroll(int(-1*(event.delta/120)) * scroll_speed, "units")
                except tk.TclError:
                    pass  # 忽略窗口已销毁的错误
            
            def bind_wheel(event):
                canvas.bind_all("<MouseWheel>", _on_mousewheel)
                
            def unbind_wheel(event):
                canvas.unbind_all("<MouseWheel>")
                
            canvas.bind('<Enter>', bind_wheel)
            canvas.bind('<Leave>', unbind_wheel)
            
            # 左右两列布局的设计 - 左侧略宽于右侧
            left_frame = tk.Frame(content_frame, bg=self.colors['background'])
            left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 15), pady=(0, 5))
            
            right_frame = tk.Frame(content_frame, bg=self.colors['background'])
            right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=False, padx=(0, 0), pady=(0, 5), anchor='n')
            
            # 左侧：标语列表区域 - 更加精致的设计
            slogan_list_card = self._create_apple_card(left_frame, elevated=True)
            slogan_list_card.pack(fill=tk.BOTH, expand=True)
            
            slogan_card_frame = slogan_list_card.winfo_children()[0]
            
            # 使用更精美的标题区域
            list_header_frame = tk.Frame(slogan_card_frame, bg=self.colors['surface_elevated'])
            list_header_frame.pack(fill=tk.X, pady=(0, 10))
            
            list_title = tk.Label(
                list_header_frame,
                text="✍️ 标语列表",
                font=self.current_fonts['headline'] if 'headline' in self.current_fonts else self.current_fonts['title'],
                fg=self.colors['primary'],
                bg=self.colors['surface_elevated']
            )
            list_title.pack(side=tk.LEFT, anchor='w')
            
            # 添加筛选图标
            filter_label = tk.Label(
                list_header_frame,
                text="🔍",
                font=self.current_fonts['title'],
                fg=self.colors['text_secondary'],
                bg=self.colors['surface_elevated'],
                cursor="hand2"
            )
            filter_label.pack(side=tk.RIGHT, anchor='e')
            
            # 标语列表和滚动条
            list_container = tk.Frame(slogan_card_frame, bg=self.colors['surface_elevated'])
            list_container.pack(fill=tk.BOTH, expand=True)
            
            # 美化滚动条
            scrollbar_list = tk.Scrollbar(
                list_container, 
                width=10
            )
            scrollbar_list.pack(side=tk.RIGHT, fill=tk.Y)
            
            # 改进列表框样式和视觉设计
            self.slogan_listbox = tk.Listbox(
                list_container,
                font=self.current_fonts['body'],
                bg=self.colors['surface'],
                fg=self.colors['text_primary'],
                selectbackground=self.colors['primary_transparent'],  # 半透明选择背景
                selectforeground=self.colors['primary'],  # 选中项使用主题色
                relief='flat',
                borderwidth=1,
                highlightthickness=1,
                highlightbackground=self.colors['separator'],  # 添加微妙边框
                highlightcolor=self.colors['primary'],  # 获得焦点时的边框颜色
                activestyle='none',  # 移除下划线
                height=18  # 确保可以看到更多条目
            )
            
            # 添加悬停高亮效果
            def on_list_enter(event):
                index = self.slogan_listbox.nearest(event.y)
                if index != self.slogan_listbox.curselection():
                    self.slogan_listbox.itemconfig(index, bg=self.colors['secondary_transparent'])
            
            def on_list_leave(event):
                index = self.slogan_listbox.nearest(event.y)
                if index != self.slogan_listbox.curselection():
                    self.slogan_listbox.itemconfig(index, bg=self.colors['surface'])
                    
            def on_list_motion(event):
                # 计算光标位置对应的列表项
                index = self.slogan_listbox.nearest(event.y)
                # 添加有效性检查，确保index有效
                if index < 0 or index >= self.slogan_listbox.size():
                    return
                    
                for i in range(self.slogan_listbox.size()):
                    if i != index and i not in self.slogan_listbox.curselection():
                        self.slogan_listbox.itemconfig(i, bg=self.colors['surface'])
                if index not in self.slogan_listbox.curselection():
                    self.slogan_listbox.itemconfig(index, bg=self.colors['secondary_transparent'])
            
            self.slogan_listbox.bind('<Motion>', on_list_motion)
            self.slogan_listbox.bind('<Leave>', lambda e: [self.slogan_listbox.itemconfig(i, bg=self.colors['surface']) for i in range(self.slogan_listbox.size()) if i not in self.slogan_listbox.curselection()])
            self.slogan_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            
            # 配置滚动条
            scrollbar_list.config(command=self.slogan_listbox.yview)
            self.slogan_listbox.config(yscrollcommand=scrollbar_list.set)
            
            # 右侧：分类管理区域 - 更紧凑更美观的设计
            category_card = self._create_apple_card(right_frame, elevated=True, bg_color=self.colors['surface'])
            category_card.pack(fill=tk.BOTH, expand=False)
            
            category_card_frame = category_card.winfo_children()[0]
            
            cat_title = tk.Label(
                category_card_frame,
                text="📁 分类管理",
                font=self.current_fonts['headline'] if 'headline' in self.current_fonts else self.current_fonts['title'],
                fg=self.colors['primary'],
                bg=self.colors['surface_elevated']
            )
            cat_title.pack(anchor='w', pady=(0, 12))
            
            # 分类信息框 - 更清晰的分组
            category_info_frame = tk.Frame(category_card_frame, bg=self.colors['surface_elevated'])
            category_info_frame.pack(fill=tk.X, pady=(0, 15))
            
            self.category_name_var = tk.StringVar()
            self.category_desc_var = tk.StringVar()
            self.category_enabled_var = tk.BooleanVar(value=True)
            
            # 更美观的表单设计
            cat_name_label = tk.Label(
                category_info_frame,
                text="分类名称:",
                font=self.current_fonts['body_emphasis'] if 'body_emphasis' in self.current_fonts else self.current_fonts['body'],
                fg=self.colors['text_primary'],
                bg=self.colors['surface_elevated']
            )
            cat_name_label.grid(row=0, column=0, sticky='w', padx=(0, 10), pady=(0, 10))
            
            # 自定义输入框悬停效果
            def on_entry_enter(event):
                event.widget.config(highlightbackground=self.colors['primary_light'])
            
            def on_entry_leave(event):
                event.widget.config(highlightbackground=self.colors['separator'])
            
            # 更精美的输入框
            cat_name_entry = tk.Entry(
                category_info_frame,
                textvariable=self.category_name_var,
                font=self.current_fonts['body'],
                bg=self.colors['surface'],
                fg=self.colors['text_primary'],
                relief='flat',
                borderwidth=1,
                highlightthickness=1,
                highlightbackground=self.colors['separator'],
                highlightcolor=self.colors['primary'],
                width=24
            )
            cat_name_entry.bind("<Enter>", on_entry_enter)
            cat_name_entry.bind("<Leave>", on_entry_leave)
            cat_name_entry.grid(row=0, column=1, sticky='we', pady=(0, 8))
            
            cat_desc_label = tk.Label(
                category_info_frame,
                text="分类描述:",
                font=self.current_fonts['body_emphasis'] if 'body_emphasis' in self.current_fonts else self.current_fonts['body'],
                fg=self.colors['text_primary'],
                bg=self.colors['surface_elevated']
            )
            cat_desc_label.grid(row=1, column=0, sticky='w', padx=(0, 10), pady=(0, 5))
            
            cat_desc_entry = tk.Entry(
                category_info_frame,
                textvariable=self.category_desc_var,
                font=self.current_fonts['body'],
                bg=self.colors['surface'],
                fg=self.colors['text_primary'],
                relief='flat',
                borderwidth=1,
                highlightthickness=1,
                highlightbackground=self.colors['separator'],
                highlightcolor=self.colors['primary'],
                width=24
            )
            cat_desc_entry.bind("<Enter>", on_entry_enter)
            cat_desc_entry.bind("<Leave>", on_entry_leave)
            cat_desc_entry.grid(row=1, column=1, sticky='we', pady=(0, 8))
            
            category_info_frame.columnconfigure(1, weight=1)
            
            # 启用/禁用分类复选框 - 更现代的切换设计
            check_frame = tk.Frame(category_card_frame, bg=self.colors['surface_elevated'], padx=0, pady=5)
            check_frame.pack(fill=tk.X, pady=(0, 12))
            
            # 更好看的复选框
            cat_enabled_check = tk.Checkbutton(
                check_frame, 
                text="启用此分类",
                variable=self.category_enabled_var,
                font=self.current_fonts['body_emphasis'] if 'body_emphasis' in self.current_fonts else self.current_fonts['body'],
                fg=self.colors['text_primary'],
                bg=self.colors['surface_elevated'],
                selectcolor='white',  # 使用白色背景，让勾选标记更清晰
                activebackground=self.colors['surface_elevated'],
                activeforeground=self.colors['primary'],
                relief='flat',
                bd=0,
                cursor='hand2',
                indicatoron=1  # 确保显示指示器
            )
            cat_enabled_check.pack(anchor='w')
            
            # 分类管理按钮 - 更现代化的垂直按钮布局
            cat_button_frame = tk.Frame(category_card_frame, bg=self.colors['surface_elevated'])
            cat_button_frame.pack(fill=tk.X, pady=(5, 0))
            
            # 使用更清晰的图标
            create_cat_button = self._create_apple_button(
                cat_button_frame,
                text="新建分类",
                command=lambda: self._create_slogan_category_dialog(dialog),
                style='success',
                icon="＋"
            )
            create_cat_button.pack(side=tk.TOP, fill=tk.X, pady=(0, 6))
            
            rename_cat_button = self._create_apple_button(
                cat_button_frame,
                text="重命名",
                command=lambda: self._rename_slogan_category_dialog(dialog),
                style='primary',
                icon="✎"
            )
            rename_cat_button.pack(side=tk.TOP, fill=tk.X, pady=(0, 6))
            
            delete_cat_button = self._create_apple_button(
                cat_button_frame,
                text="删除分类",
                command=lambda: self._delete_slogan_category_dialog(dialog),
                style='error',
                icon="✕"
            )
            delete_cat_button.pack(side=tk.TOP, fill=tk.X)
            
            # 配置canvas和scrollbar的布局
            canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
            
            # 随机显示选项 - 更精美的开关区域
            random_check_frame = tk.Frame(main_frame, bg=self.colors['background'])
            random_check_frame.pack(fill=tk.X, pady=(8, 16))
            
            # 创建调色板风格的检查框区域
            palette_frame = tk.Frame(random_check_frame, bg=self.colors['info_transparent'], padx=15, pady=10, bd=0)
            palette_frame.pack(side=tk.LEFT, fill=tk.Y)
            
            # 添加标签图标增强视觉效果
            random_icon = tk.Label(
                palette_frame,
                text="🎲",
                font=(self.current_fonts['title'][0], 16),
                fg=self.colors['info'],
                bg=self.colors['info_transparent']
            )
            random_icon.pack(side=tk.LEFT, padx=(0, 8))
            
            random_check = tk.Checkbutton(
                palette_frame, 
                text="随机显示标语",
                variable=self.use_random_message,
                font=self.current_fonts['body_emphasis'] if 'body_emphasis' in self.current_fonts else self.current_fonts['body'],
                fg=self.colors['info'],
                bg=self.colors['info_transparent'],
                selectcolor='white',  # 使用白色背景，让勾选标记更清晰
                activebackground=self.colors['info_transparent'],
                activeforeground=self.colors['info'],
                relief='flat',
                bd=0,
                cursor='hand2',
                indicatoron=1  # 确保显示指示器
            )
            random_check.pack(side=tk.LEFT)
            
            # ============== 底部固定操作区域 ==============
            # 创建更精美的分隔符
            separator = tk.Frame(dialog, height=1, bg=self.colors['separator'])
            separator.pack(fill=tk.X, padx=0, pady=0)
            
            # 创建一个容纳底部操作按钮的固定Frame - 渐变背景效果
            bottom_frame = tk.Frame(dialog, bg=self.colors['surface'])
            bottom_frame.pack(fill=tk.X, padx=0, pady=0)
            
            # 底部内容容器 - 适当内边距
            bottom_content = tk.Frame(bottom_frame, bg=self.colors['surface'])
            bottom_content.pack(fill=tk.X, padx=24, pady=15)
            
            # 左侧 - 新标语输入区域
            input_frame = tk.Frame(bottom_content, bg=self.colors['surface'])
            input_frame.pack(side=tk.LEFT, fill=tk.X, expand=True, pady=(0, 0), padx=(0, 12))
            
            # 输入框标签
            input_label = tk.Label(
                input_frame,
                text="✏️ 新标语:",
                font=self.current_fonts['body_emphasis'] if 'body_emphasis' in self.current_fonts else self.current_fonts['body'],
                fg=self.colors['text_primary'],
                bg=self.colors['surface']
            )
            input_label.pack(side=tk.LEFT, padx=(0, 8))
            
            # 更美观的输入框
            self.new_slogan_var = tk.StringVar()
            new_slogan_entry = tk.Entry(
                input_frame,
                textvariable=self.new_slogan_var,
                font=self.current_fonts['body'],
                bg=self.colors['background'],
                fg=self.colors['text_primary'],
                relief='flat',
                borderwidth=1,
                highlightthickness=1,
                highlightbackground=self.colors['separator'],
                highlightcolor=self.colors['primary'],
                insertbackground=self.colors['primary']  # 光标颜色
            )
            new_slogan_entry.bind("<Enter>", on_entry_enter)
            new_slogan_entry.bind("<Leave>", on_entry_leave)
            new_slogan_entry.pack(fill=tk.X, expand=True, side=tk.LEFT, padx=(0, 0))
            
            # 右侧 - 操作按钮区域 - 更合理的间距和大小
            button_frame = tk.Frame(bottom_content, bg=self.colors['surface'])
            button_frame.pack(side=tk.RIGHT, fill=tk.Y)
            
            # 添加标语按钮 - 更紧凑的设计
            add_slogan_button = self._create_apple_button(
                button_frame,
                text="添加",
                command=lambda: self._add_slogan_dialog(dialog),
                style='success', 
                icon="＋"
            )
            add_slogan_button.pack(side=tk.LEFT, padx=(0, 5))
            
            # 批量添加按钮
            batch_add_button = self._create_apple_button(
                button_frame,
                text="批量",
                command=lambda: self._batch_add_slogans_dialog(dialog),
                style='primary',
                icon="≡"
            )
            batch_add_button.pack(side=tk.LEFT, padx=(0, 5))
            
            # 删除标语按钮
            delete_slogan_button = self._create_apple_button(
                button_frame,
                text="删除",
                command=lambda: self._delete_slogan_dialog(dialog),
                style='error',
                icon="✕"
            )
            delete_slogan_button.pack(side=tk.LEFT, padx=(0, 5))
            
            # 设为当前标语按钮 - 更突出
            set_current_button = self._create_apple_button(
                button_frame,
                text="设为当前", 
                command=lambda: self._set_current_slogan_dialog(dialog),
                style='success',
                icon="✓"
            )
            set_current_button.pack(side=tk.LEFT, padx=(0, 5))
            
            # 关闭按钮
            close_button = self._create_apple_button(
                button_frame,
                text="关闭",
                command=dialog.destroy,
                style='secondary'
            )
            close_button.pack(side=tk.LEFT)
            
            # 绑定事件
            category_dropdown.bind("<<ComboboxSelected>>", lambda e: self._refresh_slogan_list(dialog))
            self.slogan_listbox.bind('<Double-1>', lambda e: self._set_current_slogan_dialog(dialog))
            new_slogan_entry.bind('<Return>', lambda e: self._add_slogan_dialog(dialog))
            
            # 初始化显示
            self._refresh_slogan_list(dialog)
            self._refresh_category_info(dialog)
            
            # 设置焦点
            new_slogan_entry.focus_set()
            
            # 返回对话框引用
            return dialog
            
        except Exception as e:
            logging.error(f"打开标语管理对话框失败: {e}")
            return None

    def _refresh_slogan_list(self, dialog):
        """刷新标语列表"""
        try:
            # 清空列表
            self.slogan_listbox.delete(0, tk.END)
            
            # 获取选中的分类
            category_id = self.selected_category.get()
            if not category_id or category_id not in self.slogan_categories:
                return
                
            # 填充列表
            for slogan in self.slogan_categories[category_id]["slogans"]:
                self.slogan_listbox.insert(tk.END, slogan)
                
            # 选择当前标语
            if self.slogan_settings["current_slogan"] in self.slogan_categories[category_id]["slogans"]:
                index = self.slogan_categories[category_id]["slogans"].index(self.slogan_settings["current_slogan"])
                self.slogan_listbox.selection_set(index)
                self.slogan_listbox.see(index)
                
            # 刷新分类信息
            self._refresh_category_info(dialog)
            
            # 更新标语统计信息
            if hasattr(dialog, 'stats_label'):
                # 计算总标语数量和当前分类数量
                total_slogans = sum(len(cat["slogans"]) for cat in self.slogan_categories.values())
                current_slogans = len(self.slogan_categories[category_id]["slogans"])
                cat_name = self.slogan_categories[category_id]["name"]
                
                # 更新统计标签
                dialog.stats_label.config(
                    text=f"当前分类: {current_slogans}条 | 所有分类: {total_slogans}条"
                )
            
        except Exception as e:
            logging.error(f"刷新标语列表失败: {e}")

    def _refresh_category_info(self, dialog):
        """刷新分类信息"""
        try:
            # 获取选中的分类
            category_id = self.selected_category.get()
            if not category_id or category_id not in self.slogan_categories:
                return
                
            # 更新分类信息
            self.category_name_var.set(self.slogan_categories[category_id]["name"])
            self.category_desc_var.set(self.slogan_categories[category_id]["description"])
            self.category_enabled_var.set(self.slogan_categories[category_id]["enabled"])
            
        except Exception as e:
            logging.error(f"刷新分类信息失败: {e}")

    def _batch_add_slogans_dialog(self, parent_dialog):
        """批量添加标语对话框 - 更加人性化的设计"""
        try:
            # 记录日志
            logging.info("打开批量添加标语对话框...")
            # 获取当前选中的分类
            category_id = self.selected_category.get()
            if not category_id:
                messagebox.showwarning("错误", "未选择标语分类")
                return
                
            # 创建对话框
            dialog = tk.Toplevel(parent_dialog)
            dialog.title("批量添加标语")
            dialog.geometry("600x450")
            dialog.resizable(True, True)
            dialog.transient(parent_dialog)  # 设置为父窗口的临时窗口
            dialog.grab_set()  # 模态对话框
            
            # 设置对话框样式
            dialog.configure(bg=self.colors['background'])
            
            # 创建主框架
            main_frame = tk.Frame(dialog, bg=self.colors['background'])
            main_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)
            
            # 标题
            title_label = tk.Label(
                main_frame,
                text="📋 批量添加标语",
                font=self.current_fonts['title'],
                fg=self.colors['text_primary'],
                bg=self.colors['background']
            )
            title_label.pack(anchor='w', pady=(0, 10))
            
            # 说明文本 - 简化说明，更加清晰
            description = tk.Label(
                main_frame,
                text=f"每行输入一条标语，将添加到分类 \"{self.slogan_categories[category_id]['name']}\" 中。\n"
                     f"支持直接粘贴多行文本，无需特殊格式。",
                font=self.current_fonts['body'],
                fg=self.colors['text_secondary'],
                bg=self.colors['background'],
                justify=tk.LEFT,
                wraplength=560
            )
            description.pack(anchor='w', pady=(0, 10))
            
            # 文本编辑框
            text_frame = self._create_apple_card(main_frame, elevated=True)
            text_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 20))
            
            card_frame = text_frame.winfo_children()[0] if text_frame.winfo_children() else text_frame
            
            # 文本编辑框和滚动条
            text_container = tk.Frame(card_frame, bg=self.colors['surface_elevated'])
            text_container.pack(fill=tk.BOTH, expand=True)
            
            scrollbar = tk.Scrollbar(text_container)
            scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
            
            self.batch_text = tk.Text(
                text_container,
                font=self.current_fonts['body'],
                bg=self.colors['surface'],
                fg=self.colors['text_primary'],
                relief='flat',
                bd=1,
                wrap=tk.WORD
            )
            self.batch_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            
            # 添加提示文本示例
            example_text = "放松一下眼睛，看看远处\n站起来活动一下身体\n深呼吸，调整一下坐姿\n喝口水，补充水分\n"
            self.batch_text.insert("1.0", example_text)
            self.batch_text.tag_add("example", "1.0", f"{len(example_text.splitlines())}.0")
            self.batch_text.tag_config("example", foreground=self.colors['text_tertiary'])
            
            # 配置滚动条
            scrollbar.config(command=self.batch_text.yview)
            self.batch_text.config(yscrollcommand=scrollbar.set)
            
            # 点击时清除示例文本
            def on_text_click(event):
                if self.batch_text.get("1.0", tk.END).strip() == example_text.strip():
                    self.batch_text.delete("1.0", tk.END)
                    self.batch_text.tag_remove("example", "1.0", "end")
                self.batch_text.unbind("<Button-1>", click_binding)
                
            click_binding = self.batch_text.bind("<Button-1>", on_text_click)
            
            # 按钮
            button_frame = tk.Frame(main_frame, bg=self.colors['background'])
            button_frame.pack(fill=tk.X, pady=(0, 0))
            
            # 添加一个帮助文本
            help_text = tk.Label(
                button_frame,
                text="添加后将保存到当前选中的分类中",
                font=self.current_fonts['caption'],
                fg=self.colors['text_tertiary'],
                bg=self.colors['background']
            )
            help_text.pack(side=tk.LEFT)
            
            cancel_button = self._create_apple_button(
                button_frame,
                text="取消",
                command=dialog.destroy,
                style='secondary',
                width=100
            )
            cancel_button.pack(side=tk.RIGHT, padx=(10, 0))
            
            add_button = self._create_apple_button(
                button_frame,
                text="批量添加",
                command=lambda: self._process_batch_slogans(dialog, parent_dialog),
                style='primary',
                width=120
            )
            add_button.pack(side=tk.RIGHT)
            
            # 设置焦点
            self.batch_text.focus_set()
            
            return dialog
            
        except Exception as e:
            logging.error(f"打开批量添加标语对话框失败: {e}")
            messagebox.showerror("错误", f"打开批量添加标语对话框失败: {str(e)}")
            return None
            
    def _process_batch_slogans(self, dialog, parent_dialog):
        """处理批量添加的标语"""
        try:
            # 获取当前选中的分类
            category_id = self.selected_category.get()
            if not category_id:
                messagebox.showwarning("错误", "未选择标语分类")
                return
                
            # 获取文本内容
            text_content = self.batch_text.get("1.0", tk.END).strip()
            if not text_content:
                messagebox.showwarning("输入无效", "请输入标语内容")
                return
                
            # 判断是否是示例文本
            if hasattr(self, 'batch_text') and hasattr(self.batch_text, 'tag_names'):
                tags = self.batch_text.tag_names()
                if "example" in tags:
                    # 用户没有修改示例，清除它并返回
                    messagebox.showinfo("添加提示", "请输入您的标语内容，替换示例文本")
                    return
                
            # 按行分割
            lines = text_content.splitlines()
            
            # 过滤空行
            valid_lines = [line.strip() for line in lines if line.strip()]
            
            if not valid_lines:
                messagebox.showwarning("输入无效", "没有发现有效的标语内容")
                return
                
            # 添加标语
            added_count = 0
            skipped_count = 0
            
            for slogan_text in valid_lines:
                if self.add_slogan(slogan_text, category_id):
                    added_count += 1
                else:
                    skipped_count += 1
            
            # 保存统计数据
            self.save_statistics()
            
            # 关闭对话框
            dialog.destroy()
            
            # 刷新标语列表
            self._refresh_slogan_list(parent_dialog)
            
            # 显示结果
            if added_count > 0:
                messagebox.showinfo("添加成功", 
                    f"成功添加 {added_count} 条标语" + 
                    (f"\n跳过 {skipped_count} 条重复标语" if skipped_count > 0 else ""))
            else:
                messagebox.showinfo("添加失败", f"没有成功添加任何标语\n跳过 {skipped_count} 条重复标语")
                
        except Exception as e:
            logging.error(f"批量添加标语失败: {e}")
            messagebox.showerror("添加失败", f"批量添加标语时发生错误: {str(e)}")

    def _add_slogan_dialog(self, dialog):
        """添加标语"""
        try:
            # 获取输入的标语和分类
            slogan_text = self.new_slogan_var.get().strip()
            if not slogan_text:
                messagebox.showwarning("输入无效", "请输入标语内容")
                return
                
            category_id = self.selected_category.get()
            if not category_id:
                messagebox.showwarning("错误", "未选择标语分类")
                return
                
            # 添加标语
            if self.add_slogan(slogan_text, category_id):
                # 清空输入框
                self.new_slogan_var.set("")
                
                # 刷新列表
                self._refresh_slogan_list(dialog)
                
                # 选中新添加的标语
                idx = self.slogan_categories[category_id]["slogans"].index(slogan_text)
                self.slogan_listbox.selection_set(idx)
                self.slogan_listbox.see(idx)
                
                # 显示成功消息
                messagebox.showinfo("添加成功", f"已添加标语:\n{slogan_text}")
                
        except Exception as e:
            logging.error(f"添加标语失败: {e}")
            messagebox.showerror("添加失败", f"添加标语时发生错误: {str(e)}")

    def _delete_slogan_dialog(self, dialog):
        """删除选中的标语"""
        try:
            # 获取选中的标语
            selected_idx = self.slogan_listbox.curselection()
            if not selected_idx:
                return
                
            selected_idx = selected_idx[0]
            slogan_text = self.slogan_listbox.get(selected_idx)
            category_id = self.selected_category.get()
            
            # 确认删除
            if messagebox.askyesno("确认删除", f"确定要删除标语：\n\"{slogan_text}\"吗？"):
                # 删除标语
                if self.delete_slogan(slogan_text, category_id):
                    # 刷新列表
                    self._refresh_slogan_list(dialog)
                    
        except Exception as e:
            logging.error(f"删除标语失败: {e}")

    def _set_current_slogan_dialog(self, dialog):
        """设置当前标语"""
        try:
            # 获取选中的标语
            selected_idx = self.slogan_listbox.curselection()
            if not selected_idx:
                return
                
            selected_idx = selected_idx[0]
            slogan_text = self.slogan_listbox.get(selected_idx)
            category_id = self.selected_category.get()
            
            # 设置当前标语
            if self.set_current_slogan(slogan_text, category_id):
                # 更新当前标语显示
                self.current_dim_message = slogan_text
                
                # 尝试更新设置窗口中的标语显示
                try:
                    # 确保dialog是一个窗口对象，而非字符串
                    if hasattr(dialog, 'winfo_children'):
                        for widget in dialog.winfo_children():
                            if isinstance(widget, tk.Frame):
                                for child in widget.winfo_children():
                                    if isinstance(child, tk.Label) and "当前标语" in str(child.cget("text")):
                                        for sibling in child.master.winfo_children():
                                            if isinstance(sibling, tk.Label) and sibling != child:
                                                sibling.config(text=slogan_text)
                                                break
                except Exception as e:
                    logging.error(f"更新对话框标语显示失败: {e}")
                
                # 提示用户设置成功
                messagebox.showinfo("设置成功", f"当前标语已设置为:\n{slogan_text}")
        except Exception as e:
            logging.error(f"设置当前标语失败: {e}")

    def _create_slogan_category_dialog(self, dialog):
        """创建新的标语分类"""
        try:
            # 获取信息
            new_name = self.category_name_var.get().strip()
            new_desc = self.category_desc_var.get().strip()
            is_enabled = self.category_enabled_var.get()
            
            if not new_name:
                messagebox.showwarning("输入无效", "请输入分类名称")
                return
                
            # 生成分类ID
            import time
            new_id = "category_" + "".join(
                c.lower() for c in new_name if c.isalnum() or c.isspace()
            ).replace(" ", "_") + f"_{int(time.time())}"
            
            # 创建分类
            if self.create_slogan_category(new_id, new_name, new_desc):
                # 更新分类启用状态
                self.toggle_slogan_category(new_id, is_enabled)
                
                # 刷新下拉列表
                categories = list(self.slogan_categories.keys())
                ttk_combobox = None
                
                # 确保dialog是一个窗口对象
                if hasattr(dialog, 'winfo_children'):
                    for widget in dialog.winfo_children():
                        if isinstance(widget, tk.Frame):
                            for child in widget.winfo_children():
                                if isinstance(child, tk.Frame):
                                    for grand_child in child.winfo_children():
                                        if hasattr(grand_child, 'winfo_class') and grand_child.winfo_class() == 'TCombobox':
                                            ttk_combobox = grand_child
                                            break
                
                if ttk_combobox:
                    ttk_combobox['values'] = categories
                    ttk_combobox.set(new_id)
                    
                # 刷新界面
                self.selected_category.set(new_id)
                self._refresh_slogan_list(dialog)
                
                # 清空输入框，方便继续添加
                self.category_name_var.set("")
                self.category_desc_var.set("")
                
                messagebox.showinfo("成功", f"已创建标语分类: {new_name}")
                
        except Exception as e:
            logging.error(f"创建标语分类失败: {e}")
            messagebox.showerror("创建失败", f"创建标语分类时发生错误: {str(e)}")
            
    def _rename_slogan_category_dialog(self, dialog):
        """重命名标语分类"""
        try:
            # 获取信息
            category_id = self.selected_category.get()
            new_name = self.category_name_var.get().strip()
            new_desc = self.category_desc_var.get().strip()
            
            if not new_name:
                messagebox.showwarning("输入无效", "请输入分类名称")
                return
                
            # 检查是否为默认分类
            if category_id == "default":
                messagebox.showwarning("操作无效", "无法修改默认分类的名称")
                # 恢复原值
                self._refresh_category_info(dialog)
                return
                
            # 重命名分类
            if self.rename_slogan_category(category_id, new_name, new_desc):
                # 更新启用状态
                self.toggle_slogan_category(category_id, self.category_enabled_var.get())
                
                # 刷新界面
                self._refresh_slogan_list(dialog)
                
                messagebox.showinfo("成功", f"已更新标语分类: {new_name}")
                
        except Exception as e:
            logging.error(f"重命名标语分类失败: {e}")

    def _delete_slogan_category_dialog(self, dialog):
        """删除标语分类"""
        try:
            # 获取选中的分类
            category_id = self.selected_category.get()
            
            # 检查是否为默认分类
            if category_id == "default":
                messagebox.showwarning("操作无效", "无法删除默认分类")
                return
                
            # 确认删除
            if not messagebox.askyesno("确认删除", f"确定要删除分类\"{self.slogan_categories[category_id]['name']}\"吗？\n包含的所有标语都将被删除。"):
                return
                
            # 删除分类
            if self.delete_slogan_category(category_id):
                # 刷新下拉列表
                categories = list(self.slogan_categories.keys())
                ttk_combobox = None
                
                # 确保dialog是一个窗口对象
                if hasattr(dialog, 'winfo_children'):
                    for widget in dialog.winfo_children():
                        if isinstance(widget, tk.Frame):
                            for child in widget.winfo_children():
                                if isinstance(child, tk.Frame):
                                    for grand_child in child.winfo_children():
                                        if hasattr(grand_child, 'winfo_class') and grand_child.winfo_class() == 'TCombobox':
                                            ttk_combobox = grand_child
                                            break
                
                if ttk_combobox:
                    ttk_combobox['values'] = categories
                    ttk_combobox.set(categories[0] if categories else "default")
                    
                # 刷新界面
                self.selected_category.set(categories[0] if categories else "default")
                self._refresh_slogan_list(dialog)
                
                messagebox.showinfo("成功", "已删除标语分类")
                
        except Exception as e:
            logging.error(f"删除标语分类失败: {e}")
            messagebox.showerror("删除失败", f"删除标语分类时发生错误: {str(e)}")

    def _import_slogans_dialog(self, dialog):
        """导入标语对话框"""
        try:
            # 导入必要模块
            from tkinter import filedialog
            
            # 选择文件
            file_path = filedialog.askopenfilename(
                title="选择标语文件",
                filetypes=[("JSON文件", "*.json"), ("文本文件", "*.txt"), ("所有文件", "*.*")],
                initialdir=os.path.dirname(os.path.abspath(__file__))
            )
            
            if not file_path:
                return
                
            # 确认导入方式
            overwrite = messagebox.askyesno(
                "导入选项", 
                "是否覆盖同名标语?\n选择\"是\"将覆盖已存在的标语\n选择\"否\"将跳过已存在的标语"
            )
            
            # 导入
            result = self.import_slogans(file_path, overwrite)
            
            if result:
                categories_imported, slogans_imported, slogans_skipped = result
                
                # 刷新界面
                categories = list(self.slogan_categories.keys())
                ttk_combobox = None
                
                # 确保dialog是一个窗口对象
                if hasattr(dialog, 'winfo_children'):
                    for widget in dialog.winfo_children():
                        if isinstance(widget, tk.Frame):
                            for child in widget.winfo_children():
                                if isinstance(child, tk.Frame):
                                    for grand_child in child.winfo_children():
                                        if hasattr(grand_child, 'winfo_class') and grand_child.winfo_class() == 'TCombobox':
                                            ttk_combobox = grand_child
                                            break
                
                if ttk_combobox:
                    ttk_combobox['values'] = categories
                
                self._refresh_slogan_list(dialog)
                
                messagebox.showinfo("导入成功", 
                    f"成功导入 {categories_imported} 个分类，{slogans_imported} 条标语\n"
                    f"跳过 {slogans_skipped} 条已存在的标语"
                )
                
        except Exception as e:
            logging.error(f"导入标语失败: {e}")
            messagebox.showerror("导入失败", f"导入标语时发生错误: {str(e)}")

    def _export_slogans_dialog(self, dialog):
        """导出标语对话框"""
        try:
            # 导入必要模块
            from tkinter import filedialog
            
            # 获取选中的分类
            category_id = self.selected_category.get()
            
            # 是否导出所有分类
            export_all = True
            if category_id and category_id in self.slogan_categories:
                export_all = messagebox.askyesno(
                    "导出选项", 
                    f"是否导出所有分类的标语？\n选择\"是\"将导出所有分类\n选择\"否\"仅导出当前分类\"{self.slogan_categories[category_id]['name']}\""
                )
            
            # 选择文件
            file_path = filedialog.asksaveasfilename(
                title="保存标语文件",
                filetypes=[("JSON文件", "*.json"), ("文本文件", "*.txt")],
                defaultextension=".json",
                initialdir=os.path.dirname(os.path.abspath(__file__))
            )
            
            if not file_path:
                return
                
            # 导出
            result = self.export_slogans(file_path, None if export_all else category_id)
            
            if result:
                categories_count, slogans_count = result
                messagebox.showinfo("导出成功", 
                    f"成功导出 {categories_count} 个分类，共 {slogans_count} 条标语\n"
                    f"文件保存至: {file_path}"
                )
                
        except Exception as e:
            logging.error(f"导出标语失败: {e}")
            messagebox.showerror("导出失败", f"导出标语时发生错误: {str(e)}")

    def open_dim_message_dialog(self):
        """打开屏幕变暗标语设置对话框"""
        try:
            # 创建对话框
            dialog = tk.Toplevel(self.root)
            dialog.title("设置屏幕变暗标语")
            dialog.geometry("600x500")
            dialog.resizable(True, True)
            dialog.transient(self.root)  # 设置为主窗口的临时窗口
            dialog.grab_set()  # 模态对话框
            
            # 设置对话框样式
            dialog.configure(bg=self.colors['background'])
            
            # 创建主框架
            main_frame = tk.Frame(dialog, bg=self.colors['background'])
            main_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)
            
            # 标题
            title_label = tk.Label(
                main_frame,
                text="✏️ 设置屏幕变暗标语",
                font=self.current_fonts['title'],
                fg=self.colors['text_primary'],
                bg=self.colors['background']
            )
            title_label.pack(anchor='w', pady=(0, 20))
            
            # 说明文本
            description = tk.Label(
                main_frame,
                text="请在下方文本框输入内容并点击\"添加标语\"按钮来添加新标语。\n要删除标语，选中列表中的项目并点击\"删除所选\"按钮。\n选中列表中的项目并点击\"设为当前标语\"来设置显示的标语。",
                font=self.current_fonts['body'],
                fg=self.colors['text_secondary'],
                bg=self.colors['background'],
                justify=tk.LEFT,
                wraplength=560
            )
            description.pack(anchor='w', pady=(0, 10))
            
            # 当前标语显示
            current_message_frame = tk.Frame(main_frame, bg=self.colors['background'])
            current_message_frame.pack(fill=tk.X, pady=(0, 20))
            
            current_label = tk.Label(
                current_message_frame,
                text="当前标语:",
                font=self.current_fonts['body_emphasis'],
                fg=self.colors['text_primary'],
                bg=self.colors['background']
            )
            current_label.pack(side=tk.LEFT, pady=(0, 5))
            
            # 当前标语内容
            current_message = tk.Label(
                current_message_frame,
                text=self.current_dim_message,
                font=self.current_fonts['body'],
                fg=self.colors['primary'],
                bg=self.colors['background'],
                wraplength=550
            )
            current_message.pack(side=tk.LEFT, padx=(10, 0))
            
            # 创建标语列表框架
            list_frame = self._create_apple_card(main_frame, elevated=True)
            list_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 20))
            
            card_frame = list_frame.winfo_children()[0] if list_frame.winfo_children() else list_frame
            
            # 标语列表
            list_label = tk.Label(
                card_frame,
                text="现有标语:",
                font=self.current_fonts['subheadline'],
                fg=self.colors['text_primary'],
                bg=self.colors['surface_elevated']
            )
            list_label.pack(anchor='w', pady=(0, 10))
            
            # 创建列表框和滚动条
            list_container = tk.Frame(card_frame, bg=self.colors['surface_elevated'])
            list_container.pack(fill=tk.BOTH, expand=True)
            
            scrollbar = tk.Scrollbar(list_container)
            scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
            
            self.message_listbox = tk.Listbox(
                list_container,
                font=self.current_fonts['body'],
                bg=self.colors['surface'],
                fg=self.colors['text_primary'],
                selectbackground=self.colors['primary'],
                selectforeground='white',
                relief='flat',
                bd=1,
                highlightthickness=0,
                height=8
            )
            self.message_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            
            # 配置滚动条
            scrollbar.config(command=self.message_listbox.yview)
            self.message_listbox.config(yscrollcommand=scrollbar.set)
            
            # 填充列表
            for message in self.dim_messages:
                self.message_listbox.insert(tk.END, message)
            
            # 选择当前标语
            if self.current_dim_message in self.dim_messages:
                current_index = self.dim_messages.index(self.current_dim_message)
                self.message_listbox.selection_set(current_index)
                self.message_listbox.see(current_index)
            
            # 添加新标语框架
            add_frame = tk.Frame(main_frame, bg=self.colors['background'])
            add_frame.pack(fill=tk.X, pady=(0, 20))
            
            # 新标语输入框
            self.new_message_var = tk.StringVar()
            new_message_entry = tk.Entry(
                add_frame,
                textvariable=self.new_message_var,
                font=self.current_fonts['body'],
                bg=self.colors['surface'],
                fg=self.colors['text_primary'],
                relief='flat',
                bd=1
            )
            new_message_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10))
            
            # 添加按钮
            add_button = self._create_apple_button(
                add_frame,
                text="➕ 添加标语",
                command=lambda: self._add_dim_message(dialog),
                style='primary',
                width=120
            )
            add_button.pack(side=tk.RIGHT)
            
            # 按钮框架
            button_frame = tk.Frame(main_frame, bg=self.colors['background'])
            button_frame.pack(fill=tk.X)
            
            # 删除按钮
            delete_button = self._create_apple_button(
                button_frame,
                text="❌ 删除所选",
                command=lambda: self._delete_dim_message(dialog),
                style='danger',
                width=120
            )
            delete_button.pack(side=tk.LEFT, padx=(0, 10))
            
            # 设为当前按钮
            set_current_button = self._create_apple_button(
                button_frame,
                text="✓ 设为当前标语",
                command=lambda: self._set_current_dim_message(dialog),
                style='secondary',
                width=200
            )
            set_current_button.pack(side=tk.LEFT, fill=tk.X, expand=True)
            
            # 随机显示选项
            random_frame = tk.Frame(main_frame, bg=self.colors['background'])
            random_frame.pack(fill=tk.X, pady=(20, 0))
            
            random_check = tk.Checkbutton(
                random_frame, 
                text="🎲 随机显示标语",
                variable=self.use_random_message,
                font=self.current_fonts['body'],
                fg=self.colors['text_secondary'],
                bg=self.colors['background'],
                selectcolor='white',
                relief='flat',
                bd=0,
                cursor='hand2',
                indicatoron=1
            )
            random_check.pack(side=tk.LEFT)
            
            # 关闭按钮
            close_button = self._create_apple_button(
                main_frame,
                text="关闭",
                command=dialog.destroy,
                style='primary'
            )
            close_button.pack(fill=tk.X, pady=(20, 0))
            
            # 绑定双击事件
            self.message_listbox.bind('<Double-1>', lambda e: self._set_current_dim_message(dialog))
            
            # 绑定回车键
            new_message_entry.bind('<Return>', lambda e: self._add_dim_message(dialog))
            
            # 设置焦点
            new_message_entry.focus_set()
            
        except Exception as e:
            logging.error(f"打开标语设置对话框失败: {e}")
            messagebox.showerror("错误", f"打开标语设置对话框失败: {e}")

    def open_custom_mode_dialog(self):
        """打开自定义工作模式对话框"""
        logging.info("尝试打开自定义工作模式对话框")
        try:
            # 创建对话框
            dialog = tk.Toplevel(self.root)
            dialog.title("自定义工作模式")
            dialog.geometry("700x500")  # 增加窗口宽度和高度
            dialog.minsize(650, 460)    # 设置更合理的最小窗口尺寸
            dialog.resizable(True, True)
            dialog.transient(self.root)  # 设置为主窗口的临时窗口
            dialog.grab_set()  # 模态对话框
            
            # 设置对话框样式
            dialog.configure(bg=self.colors['background'])
            
            # 创建主框架 - 极小内边距
            main_frame = tk.Frame(dialog, bg=self.colors['background'])
            main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
            
            # 简化布局 - 更小的标题区域
            header_frame = tk.Frame(main_frame, bg=self.colors['background'])
            header_frame.pack(fill=tk.X, pady=(0, 5))
            
            # 标题和说明在同一行，减小字体
            title_label = tk.Label(
                header_frame,
                text="⭐ 自定义工作模式",
                font=self.current_fonts['subheadline'],  # 使用更小的字体
                fg=self.colors['text_primary'],
                bg=self.colors['background']
            )
            title_label.pack(side=tk.LEFT, anchor='w')
            
            # 简化说明文本并放在标题旁边
            description = tk.Label(
                header_frame,
                text="创建、管理和应用自定义时间模式",
                font=self.current_fonts['caption'],  # 使用更小的字体
                fg=self.colors['text_secondary'],
                bg=self.colors['background']
            )
            description.pack(side=tk.LEFT, anchor='w', padx=(10, 0), pady=(2, 0))
            
            # 创建标签页控件
            from tkinter import ttk
            
            # 设置ttk样式 - 使标签页更加苹果风格
            style = ttk.Style()
            style.configure("TNotebook", background=self.colors['background'])
            style.configure("TNotebook.Tab", 
                           font=(self.current_fonts['body'][0], self.current_fonts['body'][1] + 1),  # 增大字体
                           padding=[12, 6],  # 增加内边距
                           background=self.colors['surface_secondary'],
                           foreground=self.colors['text_primary'])
            style.map("TNotebook.Tab",
                     background=[("selected", self.colors['surface'])],
                     foreground=[("selected", self.colors['primary'])])
            
            notebook = ttk.Notebook(main_frame)
            notebook.pack(fill=tk.BOTH, expand=True, pady=(0, 5))
            
            # 存储notebook引用，供其他方法使用
            self.custom_mode_notebook = notebook
            
            # 创建三个标签页
            settings_tab = tk.Frame(notebook, bg=self.colors['background'])
            presets_tab = tk.Frame(notebook, bg=self.colors['background'])
            modes_tab = tk.Frame(notebook, bg=self.colors['background'])
            
            # 添加标签页到notebook
            notebook.add(settings_tab, text='参数设置')
            notebook.add(presets_tab, text='预设参考')
            notebook.add(modes_tab, text='已有模式')
            
            # 创建自定义模式变量
            self.custom_mode_name_var = tk.StringVar()
            self.custom_total_var = tk.StringVar(value="90")
            self.custom_interval_var = tk.StringVar(value="15")
            self.custom_random_var = tk.StringVar(value="2")
            self.custom_rest_var = tk.StringVar(value="10")
            self.custom_second_var = tk.StringVar(value="10")
            self.custom_description_var = tk.StringVar()
            self.custom_tags_var = tk.StringVar()
            
            # === 预设参考标签页 - 带滚动条 ===
            # 创建外部框架以包含滚动区域
            presets_outer_frame = tk.Frame(presets_tab, bg=self.colors['background'])
            presets_outer_frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=5)
            
            # 创建Canvas用于滚动
            presets_canvas = tk.Canvas(presets_outer_frame, bg=self.colors['background'], 
                                     highlightthickness=0, bd=0)
            presets_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            
            # 添加滚动条
            presets_scrollbar = tk.Scrollbar(presets_outer_frame, orient=tk.VERTICAL, 
                                          command=presets_canvas.yview)
            presets_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
            presets_canvas.configure(yscrollcommand=presets_scrollbar.set)
            
            # 创建内部框架放置实际内容
            presets_inner_frame = tk.Frame(presets_canvas, bg=self.colors['background'])
            presets_canvas_window = presets_canvas.create_window((0, 0), window=presets_inner_frame, 
                                                              anchor="nw", tags="presets_inner_frame")
            
            # 配置滚动区域自适应            
            def _presets_configure_canvas(event):
                presets_canvas.configure(scrollregion=presets_canvas.bbox("all"))
                presets_canvas.itemconfig(presets_canvas_window, width=event.width)
            
            presets_inner_frame.bind("<Configure>", _presets_configure_canvas)
            presets_canvas.bind("<Configure>", lambda e: presets_canvas.itemconfig(
                presets_canvas_window, width=e.width))
            
            # 创建一个全局变量记录当前活动的Canvas
            self.active_canvas = None
            
            # 通用的鼠标滚轮处理函数
            def _on_mousewheel(event, canvas):
                canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
                
            # 创建一个全局滚轮事件处理函数，将事件路由到活动的Canvas
            def _global_mousewheel(event):
                if self.active_canvas is not None:
                    self.active_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
                
            # 添加进入/离开Canvas事件处理函数
            def _enter_canvas(event, canvas):
                self.active_canvas = canvas
                
            def _leave_canvas(event, canvas):
                if self.active_canvas == canvas:
                    self.active_canvas = None
            
            # 绑定全局鼠标滚轮事件到对话框
            dialog.bind("<MouseWheel>", _global_mousewheel)
            
            # 绑定进入/离开事件
            presets_canvas.bind("<Enter>", lambda e: _enter_canvas(e, presets_canvas))
            presets_canvas.bind("<Leave>", lambda e: _leave_canvas(e, presets_canvas))
            
            # 预设模式参考框架 - 使用更大的空间
            presets_frame = self._create_apple_card(presets_inner_frame, elevated=True)
            presets_frame.pack(fill=tk.BOTH, expand=True)
            
            presets_card = presets_frame.winfo_children()[0] if presets_frame.winfo_children() else presets_frame
            
            # 预设模式参数
            presets = {
                'tomato': {
                    'name': '🍅 番茄工作法',
                    'total': 25,
                    'interval': 25,
                    'random': 0,
                    'rest': 5,
                    'second': 10,
                    'description': '25分钟专注 + 5分钟休息',
                    'color': self.colors['error_light']
                },
                'study': {
                    'name': '📚 深度学习',
                    'total': 90,
                    'interval': 15,
                    'random': 2,
                    'rest': 10,
                    'second': 10,
                    'description': '90分钟深度学习 + 10分钟休息',
                    'color': self.colors['primary_light']
                },
                'work': {
                    'name': '💼 办公模式',
                    'total': 45,
                    'interval': 10,
                    'random': 1,
                    'rest': 5,
                    'second': 10,
                    'description': '45分钟高效工作 + 5分钟休息',
                    'color': self.colors['success_light']
                },
                'sprint': {
                    'name': '⚡ 快速冲刺',
                    'total': 15,
                    'interval': 15,
                    'random': 0,
                    'rest': 3,
                    'second': 10,
                    'description': '15分钟高强度专注 + 3分钟休息',
                    'color': self.colors['warning_light']
                }
            }
            
            # 苹果风格的预设按钮区域
            preset_buttons_frame = tk.Frame(presets_card, bg=self.colors['surface_elevated'])
            preset_buttons_frame.pack(fill=tk.X, pady=(10, 15))
            
            # 添加醒目的标题
            preset_title = tk.Label(
                    preset_buttons_frame,
                text="预设快捷选择:",
                font=self.current_fonts['body_emphasis'] if 'body_emphasis' in self.current_fonts else self.current_fonts['body'],
                fg=self.colors['primary'],
                bg=self.colors['surface_elevated']
            )
            preset_title.pack(side=tk.LEFT, padx=(0, 10))
            
            # 创建更现代的按钮容器
            buttons_container = tk.Frame(preset_buttons_frame, bg=self.colors['surface_elevated'])
            buttons_container.pack(side=tk.LEFT, fill=tk.X, expand=True)
            
            for i, (key, preset) in enumerate(presets.items()):
                # 创建苹果风格的按钮框架
                btn_frame = tk.Frame(buttons_container, 
                                     bg=preset.get('color', self.colors['surface']),
                                     bd=0, highlightthickness=1,
                                     highlightbackground=self.colors['separator'])
                btn_frame.pack(side=tk.LEFT, padx=(0 if i == 0 else 10, 0))
                
                # 添加图标标签
                icon_label = tk.Label(
                    btn_frame,
                    text=preset['name'].split(' ')[0],  # 只显示emoji图标
                    font=(self.current_fonts['body'][0], self.current_fonts['body'][1] + 2),  # 更大的图标
                    bg=preset.get('color', self.colors['surface']),
                    fg=self.colors['text_primary']
                )
                icon_label.pack(side=tk.LEFT, padx=5, pady=8)
                
                # 添加文本标签
                text_label = tk.Label(
                    btn_frame,
                    text=preset['name'].split(' ')[1],
                    font=self.current_fonts['body'],
                    bg=preset.get('color', self.colors['surface']),
                    fg=self.colors['text_primary']
                )
                text_label.pack(side=tk.LEFT, padx=(0, 10), pady=8)
                
                # 绑定点击事件
                for widget in (btn_frame, icon_label, text_label):
                    widget.bind("<Button-1>", lambda e, p=preset: self._load_preset_to_custom(p))
                    widget.bind("<Enter>", lambda e, f=btn_frame: f.config(cursor="hand2", 
                                                                         highlightbackground=self.colors['primary']))
                    widget.bind("<Leave>", lambda e, f=btn_frame: f.config(cursor="", 
                                                                         highlightbackground=self.colors['separator']))
                
            # 预设模式参数表格 - 更紧凑的表格
            preset_params_frame = tk.Frame(presets_card, bg=self.colors['surface_elevated'])
            preset_params_frame.pack(fill=tk.X, pady=(0, 5))
            
            # 表格标题 - 更加醒目
            headers = ["模式", "总时长", "间隔", "随机", "休息", "二次提醒"]
            for i, header in enumerate(headers):
                lbl = tk.Label(
                    preset_params_frame,
                    text=header,
                    font=self.current_fonts['body_emphasis'] if 'body_emphasis' in self.current_fonts else self.current_fonts['body'],  # 更大的标题字体
                    fg=self.colors['primary'],  # 使用主题色增强显示
                    bg=self.colors['surface_elevated'],
                    width=8 if i > 0 else 10  # 增加列宽
                )
                lbl.grid(row=0, column=i, padx=3, pady=(0, 6), sticky='w')
            
            # 表格内容 - 苹果风格表格
            for i, (key, preset) in enumerate(presets.items()):
                # 模式名 - 更醒目的字体
                name_lbl = tk.Label(
                    preset_params_frame,
                    text=preset['name'].split(' ')[1],
                    font=self.current_fonts['body'],  # 更大的字体
                    fg=self.colors['text_primary'],
                    bg=self.colors['surface_elevated']
                )
                name_lbl.grid(row=i+1, column=0, padx=3, pady=4, sticky='w')  # 增加间距
                
                # 参数 - 苹果风格的数据展示
                params = [preset['total'], preset['interval'], preset['random'], preset['rest'], preset['second']]
                for j, param in enumerate(params):
                    # 为了达到苹果风格的效果，使用Frame包装每个数值，增加视觉层次感
                    cell_frame = tk.Frame(preset_params_frame, bg=self.colors['surface_elevated'])
                    cell_frame.grid(row=i+1, column=j+1, padx=3, pady=4)
                    
                    param_lbl = tk.Label(
                        cell_frame,
                        text=str(param),
                        font=self.current_fonts['body'],  # 更大的字体
                        fg=self.colors['text_primary'],
                        bg=self.colors['surface_elevated']
                    )
                    param_lbl.pack(pady=2)
            
            # === 已有模式标签页 - 带滚动条 ===
            # 创建外部框架以包含滚动区域
            modes_outer_frame = tk.Frame(modes_tab, bg=self.colors['background'])
            modes_outer_frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=5)
            
            # 创建Canvas用于滚动
            modes_canvas = tk.Canvas(modes_outer_frame, bg=self.colors['background'], 
                                   highlightthickness=0, bd=0)
            modes_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            
            # 添加滚动条
            modes_scrollbar = tk.Scrollbar(modes_outer_frame, orient=tk.VERTICAL, 
                                        command=modes_canvas.yview)
            modes_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
            modes_canvas.configure(yscrollcommand=modes_scrollbar.set)
            
            # 创建内部框架放置实际内容
            modes_inner_frame = tk.Frame(modes_canvas, bg=self.colors['background'])
            modes_canvas_window = modes_canvas.create_window((0, 0), window=modes_inner_frame, 
                                                          anchor="nw", tags="modes_inner_frame")
            
            # 配置滚动区域自适应            
            def _modes_configure_canvas(event):
                modes_canvas.configure(scrollregion=modes_canvas.bbox("all"))
                modes_canvas.itemconfig(modes_canvas_window, width=event.width)
            
            modes_inner_frame.bind("<Configure>", _modes_configure_canvas)
            modes_canvas.bind("<Configure>", lambda e: modes_canvas.itemconfig(
                modes_canvas_window, width=e.width))
            
            # 绑定进入/离开事件
            modes_canvas.bind("<Enter>", lambda e: _enter_canvas(e, modes_canvas))
            modes_canvas.bind("<Leave>", lambda e: _leave_canvas(e, modes_canvas))
            
            # 创建自定义模式列表框架
            list_frame = self._create_apple_card(modes_inner_frame, elevated=True)
            list_frame.pack(fill=tk.BOTH, expand=True)
            
            card_frame = list_frame.winfo_children()[0] if list_frame.winfo_children() else list_frame
            
            # 创建列表框和滚动条
            list_container = tk.Frame(card_frame, bg=self.colors['surface_elevated'])
            list_container.pack(fill=tk.BOTH, expand=True)
            
            # 更紧凑的筛选区域
            filter_frame = tk.Frame(card_frame, bg=self.colors['surface_elevated'])
            filter_frame.pack(fill=tk.X, pady=(5, 8))
            
            # 排序选项 - 更紧凑
            sort_label = tk.Label(
                filter_frame,
                text="排序:",
                font=self.current_fonts['caption'],
                fg=self.colors['text_secondary'],
                bg=self.colors['surface_elevated']
            )
            sort_label.pack(side=tk.LEFT, padx=(0, 3))
            
            # 排序方式下拉框
            self.sort_var = tk.StringVar(value="最近使用")
            sort_options = ["最近使用", "最常使用", "名称", "创建时间"]
            sort_menu = ttk.Combobox(
                filter_frame,
                textvariable=self.sort_var,
                values=sort_options,
                width=8,  # 缩小宽度
                state="readonly"
            )
            sort_menu.pack(side=tk.LEFT, padx=(0, 8))
            
            # 搜索框
            search_label = tk.Label(
                filter_frame,
                text="搜索:",
                font=self.current_fonts['caption'],
                fg=self.colors['text_secondary'],
                bg=self.colors['surface_elevated']
            )
            search_label.pack(side=tk.LEFT, padx=(0, 3))
            
            self.search_var = tk.StringVar()
            search_entry = tk.Entry(
                filter_frame,
                textvariable=self.search_var,
                font=self.current_fonts['caption'],
                bg=self.colors['surface'],
                fg=self.colors['text_primary'],
                relief='flat',
                bd=1,
                width=12  # 缩小宽度
            )
            search_entry.pack(side=tk.LEFT)
            
            # 刷新按钮
            refresh_button = self._create_apple_button(
                filter_frame,
                text="🔄",
                command=lambda: self._refresh_custom_mode_list(dialog),
                style='secondary',
                width=25  # 缩小按钮宽度
            )
            refresh_button.pack(side=tk.RIGHT)
            
            # 列表框和滚动条 - 更紧凑的列表区域
            list_frame = tk.Frame(list_container, bg=self.colors['surface_elevated'])
            list_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 0))
            
            scrollbar = tk.Scrollbar(list_frame)
            scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
            
            # 创建苹果风格的自定义模式列表容器
            modes_container = tk.Frame(list_frame, bg=self.colors['surface'])
            modes_container.pack(fill=tk.BOTH, expand=True)
            
            # 列表头部 - 标题和操作指引
            header_frame = tk.Frame(modes_container, bg=self.colors['surface'], pady=5)
            header_frame.pack(fill=tk.X, pady=(5, 0))
            
            header_label = tk.Label(
                header_frame,
                text="自定义模式列表",
                font=self.current_fonts['subheadline'] if 'subheadline' in self.current_fonts else ('SF Pro Display', 14, 'bold'),
                fg=self.colors['text_primary'],
                bg=self.colors['surface'],
            )
            header_label.pack(side=tk.LEFT, padx=(10, 0))
            
            hint_label = tk.Label(
                header_frame,
                text="点击条目查看详情",
                font=self.current_fonts['caption'],
                fg=self.colors['text_secondary'],
                bg=self.colors['surface'],
            )
            hint_label.pack(side=tk.RIGHT, padx=(0, 10))
            
            # 创建列表框架
            list_container = tk.Frame(modes_container, bg=self.colors['surface'])
            list_container.pack(fill=tk.BOTH, expand=True)
            
            # 自定义模式列表框 - 采用现代苹果风格
            self.custom_mode_listbox = tk.Listbox(
                list_container,
                font=('SF Pro Display', 12),
                bg=self.colors['surface'],
                fg=self.colors['text_primary'],
                selectbackground=self.colors['primary_light'],
                selectforeground=self.colors['text_primary'],
                relief='flat',
                bd=0,
                highlightthickness=0,
                height=7,  # 增加列表默认高度
                activestyle='none'  # 去除激活时的下划线
            )
            self.custom_mode_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(5, 0))
            
            # 配置滚动条 - 苹果风格细滚动条
            scrollbar = tk.Scrollbar(
                list_container,
                orient="vertical",
                command=self.custom_mode_listbox.yview,
                width=10
            )
            scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
            self.custom_mode_listbox.config(yscrollcommand=scrollbar.set)
            
            # 操作按钮区域
            actions_frame = tk.Frame(modes_container, bg=self.colors['surface'], height=40)
            actions_frame.pack(fill=tk.X, pady=5)
            
            # 添加操作按钮 - 苹果风格小按钮
            buttons_frame = tk.Frame(actions_frame, bg=self.colors['surface'])
            buttons_frame.pack(side=tk.LEFT, padx=10)
            
            # 编辑按钮
            edit_button = tk.Button(
                buttons_frame,
                text="编辑",
                font=('SF Pro Display', 11),
                fg="#007AFF",  # 苹果蓝
                bg=self.colors['surface'],
                bd=0,
                padx=8,
                pady=2,
                relief='flat',
                highlightthickness=0,
                cursor="hand2",
                activebackground="#E5F1FF",  # 淡蓝色激活背景
                activeforeground="#0062CC",  # 深蓝色激活前景
                command=lambda: self._load_preset_to_custom(self.custom_modes.get(self.custom_mode_selected, {}))
            )
            edit_button.pack(side=tk.LEFT, padx=(0, 5))
            
            # 复制按钮
            duplicate_button = tk.Button(
                buttons_frame,
                text="复制",
                font=('SF Pro Display', 11),
                fg="#30B356",  # 苹果绿
                bg=self.colors['surface'],
                bd=0,
                padx=8,
                pady=2,
                relief='flat',
                highlightthickness=0,
                cursor="hand2",
                activebackground="#E3F7E9",  # 淡绿色激活背景
                activeforeground="#259144",  # 深绿色激活前景
                command=lambda: self._duplicate_custom_mode(self.custom_mode_selected)
            )
            duplicate_button.pack(side=tk.LEFT, padx=(0, 5))
            
            # 删除按钮
            delete_button = tk.Button(
                buttons_frame,
                text="删除",
                font=('SF Pro Display', 11),
                fg="#FF3B30",  # 苹果红
                bg=self.colors['surface'],
                bd=0,
                padx=8,
                pady=2,
                relief='flat',
                highlightthickness=0,
                cursor="hand2",
                activebackground="#FFEBE9",  # 淡红色激活背景
                activeforeground="#E0352B",  # 深红色激活前景
                command=lambda: self._delete_selected_custom_mode(dialog)
            )
            delete_button.pack(side=tk.LEFT)
            
            # 填充列表 - 使用更美观的显示格式
            for mode_key, mode_data in self.custom_modes.items():
                # 格式化显示文本 - 更丰富的信息展示 (苹果风格)
                use_count = mode_data.get('use_count', 0)
                use_text = f"[{use_count}次使用]" if use_count > 0 else "[未使用]"
                display_text = f"{mode_data['name']}  •  {mode_data.get('description', '')}  {use_text}"
                self.custom_mode_listbox.insert(tk.END, display_text)
            
            # 选择当前自定义模式
            if self.custom_mode_selected in self.custom_modes:
                mode_keys = list(self.custom_modes.keys())
                current_index = mode_keys.index(self.custom_mode_selected)
                self.custom_mode_listbox.selection_set(current_index)
                self.custom_mode_listbox.see(current_index)
            
            # 绑定鼠标悬停事件 - 增强交互体验
            def on_listbox_enter(event):
                """鼠标进入列表项时的效果"""
                try:
                    index = self.custom_mode_listbox.nearest(event.y)
                    if index >= 0:
                        self.custom_mode_listbox.itemconfig(index, bg=self.colors['hover'])
                except Exception as e:
                    logging.error(f"列表项悬停效果错误: {e}")
                    
            def on_listbox_leave(event):
                """鼠标离开列表项时的效果"""
                try:
                    index = self.custom_mode_listbox.nearest(event.y)
                    if index >= 0:
                        # 根据项目是否被选中决定背景颜色
                        if index in self.custom_mode_listbox.curselection():
                            self.custom_mode_listbox.itemconfig(index, bg=self.colors['primary_light'])
                        else:
                            self.custom_mode_listbox.itemconfig(index, bg=self.colors['surface'])
                except Exception as e:
                    logging.error(f"列表项离开效果错误: {e}")
            
            # 绑定鼠标移动事件
            self.custom_mode_listbox.bind('<Motion>', on_listbox_enter)
            self.custom_mode_listbox.bind('<Leave>', on_listbox_leave)
            
            # 绑定自定义模式列表选择事件
            def on_mode_select(event):
                """当选择自定义模式时更新选中状态"""
                try:
                    # 获取选中的索引
                    selected_index = self.custom_mode_listbox.curselection()
                    if not selected_index:
                        return
                        
                    # 获取排序和筛选后的模式列表
                    sort_by = self.sort_var.get()
                    search_text = self.search_var.get().lower()
                    
                    filtered_modes = []
                    for key, mode in self.custom_modes.items():
                        # 搜索过滤
                        if search_text:
                            name_match = search_text in mode['name'].lower()
                            desc_match = search_text in mode.get('description', '').lower()
                            tags_match = any(search_text in tag.lower() for tag in mode.get('tags', []))
                            notes_match = search_text in mode.get('notes', '').lower()
                            
                            if not (name_match or desc_match or tags_match or notes_match):
                                continue
                        
                        filtered_modes.append((key, mode))
                    
                    # 获取选中的模式键
                    selected_key = filtered_modes[selected_index[0]][0]
                    
                    # 设置为当前选中模式
                    self.custom_mode_selected = selected_key
                    
                    # 高亮显示选中项
                    self.custom_mode_listbox.selection_set(selected_index)
                    
                except Exception as e:
                    logging.error(f"选择自定义模式失败: {e}")
                    
            # 绑定列表选择事件
            self.custom_mode_listbox.bind('<<ListboxSelect>>', on_mode_select)
            
            # === 参数设置标签页 - 带滚动条 ===
            # 创建外部框架以包含滚动区域
            settings_outer_frame = tk.Frame(settings_tab, bg=self.colors['background'])
            settings_outer_frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=5)
            
            # 创建Canvas用于滚动
            settings_canvas = tk.Canvas(settings_outer_frame, bg=self.colors['background'], 
                                      highlightthickness=0, bd=0)
            settings_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            
            # 添加滚动条
            settings_scrollbar = tk.Scrollbar(settings_outer_frame, orient=tk.VERTICAL, 
                                           command=settings_canvas.yview)
            settings_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
            settings_canvas.configure(yscrollcommand=settings_scrollbar.set)
            
            # 创建内部框架放置实际内容
            settings_inner_frame = tk.Frame(settings_canvas, bg=self.colors['background'])
            settings_canvas_window = settings_canvas.create_window((0, 0), window=settings_inner_frame, 
                                                               anchor="nw", tags="settings_inner_frame")
            
            # 配置滚动区域自适应            
            def _settings_configure_canvas(event):
                settings_canvas.configure(scrollregion=settings_canvas.bbox("all"))
                settings_canvas.itemconfig(settings_canvas_window, width=event.width)
            
            settings_inner_frame.bind("<Configure>", _settings_configure_canvas)
            settings_canvas.bind("<Configure>", lambda e: settings_canvas.itemconfig(
                settings_canvas_window, width=e.width))
            
            # 绑定进入/离开事件
            settings_canvas.bind("<Enter>", lambda e: _enter_canvas(e, settings_canvas))
            settings_canvas.bind("<Leave>", lambda e: _leave_canvas(e, settings_canvas))
            
            # 设置标签页切换事件，激活当前标签页上的Canvas
            def _on_tab_changed(event):
                tab_id = notebook.index("current")
                if tab_id == 0:  # 参数设置
                    self.active_canvas = settings_canvas
                elif tab_id == 1:  # 预设参考
                    self.active_canvas = presets_canvas
                elif tab_id == 2:  # 已有模式
                    self.active_canvas = modes_canvas
            
            # 绑定标签页切换事件
            notebook.bind("<<NotebookTabChanged>>", _on_tab_changed)
            
            # 初始化默认活动Canvas
            self.active_canvas = settings_canvas
            
            # 创建新模式设置框架 - 苹果风格
            settings_frame = self._create_apple_card(settings_inner_frame, elevated=True)
            settings_frame.pack(fill=tk.BOTH, expand=True)
            
            settings_card = settings_frame.winfo_children()[0] if settings_frame.winfo_children() else settings_frame
            
            # 基本信息区域标题 - 苹果风格区域标题
            header_label = tk.Label(
                settings_card,
                text="⚙️ 模式基本信息",
                font=self.current_fonts['headline'] if 'headline' in self.current_fonts else self.current_fonts['subheadline'],
                fg=self.colors['primary'],
                bg=self.colors['surface_elevated']
            )
            header_label.pack(anchor='w', pady=(5, 10), padx=5)
            
            # 基本信息区域 - 使用更现代的布局
            basic_frame = tk.Frame(settings_card, bg=self.colors['surface_elevated'])
            basic_frame.pack(fill=tk.X, pady=(0, 12), padx=5)
            
            # 使用苹果风格的表单布局
            top_grid = tk.Frame(basic_frame, bg=self.colors['surface_elevated'])
            top_grid.pack(fill=tk.X)
            top_grid.columnconfigure(0, weight=0)
            top_grid.columnconfigure(1, weight=1)
            
            # 模式名称 - 苹果风格的表单项
            name_frame = tk.Frame(top_grid, bg=self.colors['surface_elevated'])
            name_frame.grid(row=0, column=0, columnspan=2, sticky='ew', pady=(0, 12))
            
            name_label = tk.Label(
                name_frame,
                text="⭐ 模式名称",
                font=self.current_fonts['body_emphasis'] if 'body_emphasis' in self.current_fonts else self.current_fonts['body'],
                fg=self.colors['text_primary'],
                bg=self.colors['surface_elevated']
            )
            name_label.pack(anchor='w', pady=(0, 5))
            
            self.custom_mode_name_var = tk.StringVar()
            name_entry = tk.Entry(
                name_frame,
                textvariable=self.custom_mode_name_var,
                font=self.current_fonts['body'],
                bg=self.colors['surface'],
                fg=self.colors['text_primary'],
                relief='flat',
                bd=0,
                highlightthickness=1,
                highlightbackground=self.colors['separator'],
                highlightcolor=self.colors['primary']
            )
            name_entry.pack(fill='x')
            
            # 描述 - 苹果风格的表单项
            desc_frame = tk.Frame(top_grid, bg=self.colors['surface_elevated'])
            desc_frame.grid(row=1, column=0, columnspan=2, sticky='ew', pady=(0, 12))
            
            desc_label = tk.Label(
                desc_frame,
                text="📝 描述",
                font=self.current_fonts['body_emphasis'] if 'body_emphasis' in self.current_fonts else self.current_fonts['body'],
                fg=self.colors['text_primary'],
                bg=self.colors['surface_elevated']
            )
            desc_label.pack(anchor='w', pady=(0, 5))
            
            self.custom_description_var = tk.StringVar()
            desc_entry = tk.Entry(
                desc_frame,
                textvariable=self.custom_description_var,
                font=self.current_fonts['body'],
                bg=self.colors['surface'],
                fg=self.colors['text_primary'],
                relief='flat',
                bd=0,
                highlightthickness=1,
                highlightbackground=self.colors['separator'],
                highlightcolor=self.colors['primary']
            )
            desc_entry.pack(fill='x')
            
            # 标签 - 苹果风格的表单项
            tags_frame = tk.Frame(top_grid, bg=self.colors['surface_elevated'])
            tags_frame.grid(row=2, column=0, columnspan=2, sticky='ew')
            
            tags_label = tk.Label(
                tags_frame,
                text="🏷️ 标签 (用逗号分隔)",
                font=self.current_fonts['body_emphasis'] if 'body_emphasis' in self.current_fonts else self.current_fonts['body'],
                fg=self.colors['text_primary'],
                bg=self.colors['surface_elevated']
            )
            tags_label.pack(anchor='w', pady=(0, 5))
            
            self.custom_tags_var = tk.StringVar()
            tags_entry = tk.Entry(
                tags_frame,
                textvariable=self.custom_tags_var,
                font=self.current_fonts['body'],
                bg=self.colors['surface'],
                fg=self.colors['text_primary'],
                relief='flat',
                bd=0,
                highlightthickness=1,
                highlightbackground=self.colors['separator'],
                highlightcolor=self.colors['primary']
            )
            tags_entry.pack(fill='x')
            
            # 时间参数区域 - 苹果风格设计
            time_label = tk.Label(
                settings_card,
                text="⏱️ 时间参数设置",
                font=self.current_fonts['headline'] if 'headline' in self.current_fonts else self.current_fonts['subheadline'],
                fg=self.colors['primary'],
                bg=self.colors['surface_elevated']
            )
            time_label.pack(anchor='w', pady=(5, 10), padx=5)
            
            time_frame = tk.Frame(
                settings_card,
                bg=self.colors['surface_elevated'],
            )
            time_frame.pack(fill=tk.X, pady=(0, 10), padx=5)
            
            # 创建更现代化的网格布局
            time_grid = tk.Frame(time_frame, bg=self.colors['surface_elevated'])
            time_grid.pack(fill=tk.X)
            
            # 使用响应式网格布局
            time_grid.columnconfigure(0, weight=1)
            time_grid.columnconfigure(1, weight=1)
            
            # 创建苹果风格的参数控件
            # 时间参数容器1 - 总时长和间隔
            param_frame1 = tk.Frame(time_grid, bg=self.colors['surface_elevated'])
            param_frame1.grid(row=0, column=0, padx=(0, 10), pady=10, sticky='nsew')
            
            # 总时长 - 左列
            total_container = tk.Frame(param_frame1, bg=self.colors['surface'])
            total_container.pack(fill='x', pady=5)
            total_container.configure(highlightthickness=1, highlightbackground=self.colors['separator'])
            
            total_label = tk.Label(
                total_container,
                text="总时长(分钟)",
                font=self.current_fonts['body'],
                fg=self.colors['text_primary'],
                bg=self.colors['surface']
            )
            total_label.pack(anchor='w', padx=10, pady=(8, 4))
            
            self.custom_total_var = tk.StringVar(value="60")
            total_entry = tk.Spinbox(
                total_container,
                from_=1,
                to=999,
                textvariable=self.custom_total_var,
                font=(self.current_fonts['body'][0], self.current_fonts['body'][1] + 2),  # 增大字体
                width=8,
                relief='flat',
                bd=0,
                bg=self.colors['surface'],
                fg=self.colors['primary'],
                validate='key',
                validatecommand=(self.root.register(self._validate_number), '%P')
            )
            total_entry.pack(anchor='w', padx=10, pady=(0, 8))
            
            # 间隔时间
            interval_container = tk.Frame(param_frame1, bg=self.colors['surface'])
            interval_container.pack(fill='x', pady=5)
            interval_container.configure(highlightthickness=1, highlightbackground=self.colors['separator'])
            
            interval_label = tk.Label(
                interval_container,
                text="间隔时间(分钟)",
                font=self.current_fonts['body'],
                fg=self.colors['text_primary'],
                bg=self.colors['surface']
            )
            interval_label.pack(anchor='w', padx=10, pady=(8, 4))
            
            self.custom_interval_var = tk.StringVar(value="15")
            interval_entry = tk.Spinbox(
                interval_container,
                from_=1,
                to=60,
                textvariable=self.custom_interval_var,
                font=(self.current_fonts['body'][0], self.current_fonts['body'][1] + 2),  # 增大字体
                width=8,
                relief='flat',
                bd=0,
                bg=self.colors['surface'],
                fg=self.colors['primary'],
                validate='key',
                validatecommand=(self.root.register(self._validate_number), '%P')
            )
            interval_entry.pack(anchor='w', padx=10, pady=(0, 8))
            
            # 时间参数容器2 - 随机和休息
            param_frame2 = tk.Frame(time_grid, bg=self.colors['surface_elevated'])
            param_frame2.grid(row=0, column=1, padx=(10, 0), pady=10, sticky='nsew')
            
            # 随机时间
            random_container = tk.Frame(param_frame2, bg=self.colors['surface'])
            random_container.pack(fill='x', pady=5)
            random_container.configure(highlightthickness=1, highlightbackground=self.colors['separator'])
            
            random_label = tk.Label(
                random_container,
                text="随机提醒(分钟)",
                font=self.current_fonts['body'],
                fg=self.colors['text_primary'],
                bg=self.colors['surface']
            )
            random_label.pack(anchor='w', padx=10, pady=(8, 4))
            
            self.custom_random_var = tk.StringVar(value="2")
            random_entry = tk.Spinbox(
                random_container,
                from_=0,
                to=10,
                textvariable=self.custom_random_var,
                font=(self.current_fonts['body'][0], self.current_fonts['body'][1] + 2),  # 增大字体
                width=8,
                relief='flat',
                bd=0,
                bg=self.colors['surface'],
                fg=self.colors['primary'],
                validate='key',
                validatecommand=(self.root.register(self._validate_number), '%P')
            )
            random_entry.pack(anchor='w', padx=10, pady=(0, 8))
            
            # 休息时间
            rest_container = tk.Frame(param_frame2, bg=self.colors['surface'])
            rest_container.pack(fill='x', pady=5)
            rest_container.configure(highlightthickness=1, highlightbackground=self.colors['separator'])
            
            rest_label = tk.Label(
                rest_container,
                text="休息时间(分钟)",
                font=self.current_fonts['body'],
                fg=self.colors['text_primary'],
                bg=self.colors['surface']
            )
            rest_label.pack(anchor='w', padx=10, pady=(8, 4))
            
            self.custom_rest_var = tk.StringVar(value="5")
            rest_entry = tk.Spinbox(
                rest_container,
                from_=1,
                to=30,
                textvariable=self.custom_rest_var,
                font=(self.current_fonts['body'][0], self.current_fonts['body'][1] + 2),  # 增大字体
                width=8,
                relief='flat',
                bd=0,
                bg=self.colors['surface'],
                fg=self.colors['primary'],
                validate='key',
                validatecommand=(self.root.register(self._validate_number), '%P')
            )
            rest_entry.pack(anchor='w', padx=10, pady=(0, 8))
            
            # 二次提醒 - 单独一行
            second_container = tk.Frame(time_frame, bg=self.colors['surface'])
            second_container.pack(fill='x', pady=5)
            second_container.configure(highlightthickness=1, highlightbackground=self.colors['separator'])
            
            second_label = tk.Label(
                second_container,
                text="二次提醒时间(秒)",
                font=self.current_fonts['body'],
                fg=self.colors['text_primary'],
                bg=self.colors['surface']
            )
            second_label.pack(anchor='w', padx=10, pady=(8, 4))
            
            self.custom_second_var = tk.StringVar(value="10")
            second_entry = tk.Spinbox(
                second_container,
                from_=0,
                to=60,
                textvariable=self.custom_second_var,
                font=(self.current_fonts['body'][0], self.current_fonts['body'][1] + 2),  # 增大字体
                width=8,
                relief='flat',
                bd=0,
                bg=self.colors['surface'],
                fg=self.colors['primary'],
                validate='key',
                validatecommand=(self.root.register(self._validate_number), '%P')
            )
            second_entry.pack(anchor='w', padx=10, pady=(0, 8))
            
            # 苹果风格备注区域 
            notes_label = tk.Label(
                settings_card, 
                text="📋 备注信息",
                font=self.current_fonts['headline'] if 'headline' in self.current_fonts else self.current_fonts['subheadline'],
                fg=self.colors['primary'],
                bg=self.colors['surface_elevated']
            )
            notes_label.pack(anchor='w', pady=(10, 8), padx=5)
            
            # 创建有边框的苹果风格容器
            notes_container = tk.Frame(settings_card, bg=self.colors['surface'], bd=0,
                                       highlightthickness=1, highlightbackground=self.colors['separator'])
            notes_container.pack(fill=tk.BOTH, expand=True, pady=(0, 8), padx=5)
            
            # 滚动条
            notes_scroll = tk.Scrollbar(notes_container)
            notes_scroll.pack(side=tk.RIGHT, fill=tk.Y)
            
            # 文本区域
            self.custom_notes_text = tk.Text(
                notes_container, 
                font=self.current_fonts['body'],  # 使用正常字体
                bg=self.colors['surface'],
                fg=self.colors['text_primary'],
                height=2,  # 稍微增加高度
                relief='flat',
                bd=0,
                padx=8,
                pady=8,
                yscrollcommand=notes_scroll.set
            )
            self.custom_notes_text.pack(fill=tk.BOTH, expand=True)
            notes_scroll.config(command=self.custom_notes_text.yview)
            
            # 添加提示文本
            self.custom_notes_text.insert("1.0", "在此处输入备注信息...")
            self.custom_notes_text.bind("<FocusIn>", lambda e: self.custom_notes_text.delete("1.0", tk.END) if self.custom_notes_text.get("1.0", "end-1c") == "在此处输入备注信息..." else None)
            self.custom_notes_text.bind("<FocusOut>", lambda e: self.custom_notes_text.insert("1.0", "在此处输入备注信息...") if not self.custom_notes_text.get("1.0", "end-1c") else None)
            
            # 创建StringVar用于保存文本内容
            self.custom_notes_var = tk.StringVar()
            
            # 底部按钮区域 - 极度紧凑
            button_frame = tk.Frame(main_frame, bg=self.colors['background'])
            button_frame.pack(fill=tk.X, pady=(2, 0))
            
            # 使用更紧凑的按钮布局
            left_buttons = tk.Frame(button_frame, bg=self.colors['background'])
            left_buttons.pack(side=tk.LEFT, fill=tk.X, expand=True)
            
            right_buttons = tk.Frame(button_frame, bg=self.colors['background'])
            right_buttons.pack(side=tk.RIGHT, fill=tk.X)
            
            # 保存按钮
            save_button = self._create_apple_button(
                left_buttons,
                text="💾 保存",
                command=lambda: self._save_custom_mode(dialog),  # 修正方法名
                style='primary',
                width=100
            )
            save_button.pack(side=tk.LEFT, padx=(0, 5))
            
            # 删除按钮
            delete_button = self._create_apple_button(
                left_buttons,
                text="❌ 删除",
                command=lambda: self._delete_selected_custom_mode(dialog),  # 修正方法名
                style='danger',
                width=100
            )
            delete_button.pack(side=tk.LEFT, padx=(0, 5))
            
            # 应用按钮
            apply_button = self._create_apple_button(
                left_buttons,
                text="✅ 应用",
                command=lambda: self._select_work_mode(self.custom_mode_selected),  # 修正方法名
                style='secondary',
                width=100
            )
            apply_button.pack(side=tk.LEFT)
            
            # 关闭按钮
            close_button = self._create_apple_button(
                right_buttons,
                text="关闭",
                command=dialog.destroy,
                style='secondary',
                width=80
            )
            close_button.pack(side=tk.RIGHT)
            
            # 绑定双击事件 - 应用选中的模式
            self.custom_mode_listbox.bind('<Double-1>', lambda e: self._select_work_mode(self.custom_mode_selected))
            
            # 绑定选择事件 - 更新表单内容
            self.custom_mode_listbox.bind('<<ListboxSelect>>', lambda e: self._load_preset_to_custom(self.custom_modes.get(self.custom_mode_selected, {})))
            
            # 设置焦点
            name_entry.focus_set()
            
            logging.info("自定义工作模式对话框创建成功")
            
        except Exception as e:
            logging.error(f"打开自定义工作模式对话框失败: {e}")
            messagebox.showerror("错误", f"打开自定义工作模式对话框失败: {e}")
            
    def _save_custom_mode(self, dialog):
        """保存自定义模式"""
        try:
            # 获取输入值
            name = self.custom_mode_name_var.get()
            total = self.custom_total_var.get()
            interval = self.custom_interval_var.get()
            random_val = self.custom_random_var.get()
            rest = self.custom_rest_var.get()
            second = self.custom_second_var.get()
            description = self.custom_description_var.get()
            tags = self.custom_tags_var.get()
            notes = self.custom_notes_text.get("1.0", tk.END).strip()
            
            # 验证输入
            if not name:
                messagebox.showwarning("提示", "请输入模式名称")
                return
            
            # 保存模式
            mode_key = self.save_custom_mode(
                name, int(total), int(interval), int(random_val), int(rest), int(second),
                description=description, tags=tags, notes=notes
            )
            
            if mode_key:
                # 刷新列表
                self._refresh_custom_mode_list(dialog)
                # 设置为当前选中模式
                self.custom_mode_selected = mode_key
                # 显示成功消息
                messagebox.showinfo("成功", f"已保存自定义模式: {name}")
                logging.info(f"已保存自定义模式: {name} (key={mode_key})")
            else:
                messagebox.showerror("错误", "保存自定义模式失败")
                
        except Exception as e:
            logging.error(f"保存自定义模式失败: {e}")
            messagebox.showerror("错误", f"保存自定义模式失败: {e}")
    
    def _load_preset_to_custom(self, preset):
        """将预设模式加载到自定义模式设置中"""
        try:
            # 设置输入框值
            if not preset:
                return
                
            # 如果是预设模式则添加"自定义"后缀，否则直接使用原名称
            if 'name' in preset and len(preset['name'].split(' ')) > 1:
                name = preset['name'].split(' ')[1] + "自定义"  # 添加"自定义"后缀
            else:
                name = preset.get('name', '')
                
            self.custom_mode_name_var.set(name)
            self.custom_total_var.set(str(preset.get('total', 60)))
            self.custom_interval_var.set(str(preset.get('interval', 15)))
            self.custom_random_var.set(str(preset.get('random', 2)))
            self.custom_rest_var.set(str(preset.get('rest', 5)))
            self.custom_second_var.set(str(preset.get('second', 10)))
            
            # 设置描述字段（如果有）
            if hasattr(self, 'custom_description_var') and 'description' in preset:
                self.custom_description_var.set(preset['description'])
                
            # 设置标签字段（如果有）
            if hasattr(self, 'custom_tags_var'):
                self.custom_tags_var.set("")
                
            # 设置备注字段（如果有）
            if hasattr(self, 'custom_notes_text'):
                self.custom_notes_text.delete("1.0", tk.END)
                if preset.get('notes', ''):
                    self.custom_notes_text.insert("1.0", preset.get('notes', ''))
            
            # 显示提示
            messagebox.showinfo("提示", f"已加载{preset.get('name', '')}的参数设置，您可以根据需要进行调整")
            
            logging.info(f"已加载预设模式到自定义模式编辑框: {preset.get('name', '')}")
        except Exception as e:
            logging.error(f"加载预设模式到自定义设置失败: {e}")
            messagebox.showerror("错误", f"加载预设模式失败: {e}")

    def _refresh_custom_mode_list(self, dialog):
        """刷新自定义模式列表
        
        根据排序方式和搜索关键词刷新列表
        """
        try:
            # 获取排序方式和搜索关键词
            sort_by = self.sort_var.get()
            search_text = self.search_var.get().lower()
            
            # 过滤模式
            filtered_modes = []
            for key, mode in self.custom_modes.items():
                # 搜索过滤
                if search_text:
                    name_match = search_text in mode['name'].lower()
                    desc_match = search_text in mode.get('description', '').lower()
                    tags_match = any(search_text in tag.lower() for tag in mode.get('tags', []))
                    notes_match = search_text in mode.get('notes', '').lower()
                    
                    if not (name_match or desc_match or tags_match or notes_match):
                        continue
                
                filtered_modes.append((key, mode))
            
            # 排序
            if sort_by == "最近使用":
                # 按最近使用顺序排序
                sorted_modes = []
                for mode_key in self.custom_mode_history.get("last_used", []):
                    for key, mode in filtered_modes:
                        if key == mode_key:
                            sorted_modes.append((key, mode))
                            break
                
                # 添加未在最近使用列表中的模式
                for key, mode in filtered_modes:
                    if key not in self.custom_mode_history.get("last_used", []):
                        sorted_modes.append((key, mode))
                
            elif sort_by == "最常使用":
                # 按使用次数排序
                sorted_modes = sorted(
                    filtered_modes,
                    key=lambda x: x[1].get('use_count', 0),
                    reverse=True
                )
                
            elif sort_by == "名称":
                # 按名称排序
                sorted_modes = sorted(
                    filtered_modes,
                    key=lambda x: x[1]['name']
                )
                
            elif sort_by == "创建时间":
                # 按创建时间排序
                sorted_modes = sorted(
                    filtered_modes,
                    key=lambda x: x[1].get('created_time', ''),
                    reverse=True
                )
                
            else:
                sorted_modes = filtered_modes
            
            # 更新列表
            self.custom_mode_listbox.delete(0, tk.END)
            for key, mode in sorted_modes:
                # 显示格式：名称 - 描述 (使用次数)
                display_text = f"{mode['name']} - {mode.get('description', '')} [{mode.get('use_count', 0)}次]"
                self.custom_mode_listbox.insert(tk.END, display_text)
                
            # 选择当前模式
            if self.custom_mode_selected:
                for i, (key, _) in enumerate(sorted_modes):
                    if key == self.custom_mode_selected:
                        self.custom_mode_listbox.selection_set(i)
                        self.custom_mode_listbox.see(i)
                        break
                        
            logging.info(f"刷新自定义模式列表: {len(sorted_modes)}个模式")
        except Exception as e:
            logging.error(f"刷新自定义模式列表失败: {e}")
            messagebox.showerror("错误", f"刷新列表失败: {e}")

    def _delete_selected_custom_mode(self, dialog):
        """删除选中的自定义模式"""
        try:
            # 获取选中的索引
            selected_index = self.custom_mode_listbox.curselection()
            if not selected_index:
                messagebox.showinfo("提示", "请先选择要删除的模式")
                return
                
            # 获取选中模式的键
            sorted_modes = []
            sort_by = self.sort_var.get()
            search_text = self.search_var.get().lower()
            
            # 按当前排序和筛选规则获取模式列表
            for key, mode in self.custom_modes.items():
                # 搜索过滤
                if search_text:
                    name_match = search_text in mode['name'].lower()
                    desc_match = search_text in mode.get('description', '').lower()
                    tags_match = any(search_text in tag.lower() for tag in mode.get('tags', []))
                    notes_match = search_text in mode.get('notes', '').lower()
                    
                    if not (name_match or desc_match or tags_match or notes_match):
                        continue
                
                sorted_modes.append((key, mode))
            
            # 应用相同的排序规则
            if sort_by == "最近使用":
                # 按最近使用顺序排序
                sorted_modes_new = []
                for mode_key in self.custom_mode_history.get("last_used", []):
                    for key, mode in sorted_modes:
                        if key == mode_key:
                            sorted_modes_new.append((key, mode))
                            break
                
                # 添加未在最近使用列表中的模式
                for key, mode in sorted_modes:
                    if key not in self.custom_mode_history.get("last_used", []):
                        sorted_modes_new.append((key, mode))
                sorted_modes = sorted_modes_new
                
            elif sort_by == "最常使用":
                # 按使用次数排序
                sorted_modes = sorted(
                    sorted_modes,
                    key=lambda x: x[1].get('use_count', 0),
                    reverse=True
                )
                
            elif sort_by == "名称":
                # 按名称排序
                sorted_modes = sorted(
                    sorted_modes,
                    key=lambda x: x[1]['name']
                )
                
            elif sort_by == "创建时间":
                # 按创建时间排序
                sorted_modes = sorted(
                    sorted_modes,
                    key=lambda x: x[1].get('created_time', ''),
                    reverse=True
                )
                
            # 获取要删除的模式键
            selected_key = sorted_modes[selected_index[0]][0]
            selected_name = self.custom_modes[selected_key]['name']
            
            # 确认删除
            if messagebox.askyesno("确认删除", f"确定要删除模式\"{selected_name}\"吗？\n此操作不可恢复。"):
                # 删除模式
                self.delete_custom_mode(selected_key)
                
                # 如果当前选中的就是被删除的
                if self.custom_mode_selected == selected_key:
                    self.custom_mode_selected = None
                    
                # 刷新列表
                self._refresh_custom_mode_list(dialog)
                
                messagebox.showinfo("成功", f"已删除自定义模式: {selected_name}")
                logging.info(f"已删除自定义模式: {selected_name} (key={selected_key})")
                
        except Exception as e:
            logging.error(f"删除自定义模式失败: {e}")
            messagebox.showerror("错误", f"删除自定义模式失败: {e}")
        
    def _duplicate_custom_mode(self, mode_key):
        """复制自定义模式"""
        try:
            if not mode_key or mode_key not in self.custom_modes:
                messagebox.showinfo("提示", "请先选择要复制的模式")
                return
                
            # 获取选中的模式
            mode = self.custom_modes[mode_key]
            
            # 复制模式参数到表单
            new_name = f"{mode['name']} 副本"
            self.custom_mode_name_var.set(new_name)
            self.custom_total_var.set(str(mode.get('total', 60)))
            self.custom_interval_var.set(str(mode.get('interval', 15)))
            self.custom_random_var.set(str(mode.get('random', 2)))
            self.custom_rest_var.set(str(mode.get('rest', 5)))
            self.custom_second_var.set(str(mode.get('second', 10)))
            
            # 复制其他字段
            if hasattr(self, 'custom_description_var') and 'description' in mode:
                self.custom_description_var.set(mode['description'])
                
            if hasattr(self, 'custom_tags_var') and 'tags' in mode:
                self.custom_tags_var.set(','.join(mode.get('tags', [])))
                
            if hasattr(self, 'custom_notes_text') and 'notes' in mode:
                self.custom_notes_text.delete("1.0", tk.END)
                self.custom_notes_text.insert(tk.END, mode.get('notes', ''))
            
            # 切换到参数设置选项卡
            if hasattr(self, 'custom_mode_notebook') and self.custom_mode_notebook:
                self.custom_mode_notebook.select(0)  # 参数设置是第一个标签页
            
            # 显示成功消息
            messagebox.showinfo("成功", f"已复制模式\"{mode['name']}\"，\n您可以编辑后保存为新模式")
            logging.info(f"已复制自定义模式: {mode['name']} (key={mode_key})")
            
        except Exception as e:
            logging.error(f"复制自定义模式失败: {e}")
            messagebox.showerror("错误", f"复制自定义模式失败: {e}")

if __name__ == "__main__":
    app = TimeReminder()
    app.run() 