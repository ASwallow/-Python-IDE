# -*- coding: utf-8 -*-
#
#  FunkyIDE - 一个专注于炫酷但“无用”功能的Python简易IDE
#  版本: V0.0
#  作者: ASwallow
#  日期: 2025-09-14


import sys
import os
import tkinter as tk
from tkinter import simpledialog, messagebox, Listbox, Scrollbar, END, Frame, Text, Button, Toplevel, Label
import subprocess
import threading
import webbrowser
import markdown

from pygments import lex
from pygments.lexers import guess_lexer_for_filename
from pygments.styles import get_style_by_name
from pygments.util import ClassNotFound


# --- 全局常量与路径设置 ---

def get_base_path():
    """获取脚本或可执行文件的基础路径，兼容PyInstaller打包。"""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(os.path.abspath(sys.executable))
    else:
        return os.path.dirname(os.path.abspath(__file__))


BASE_PATH = get_base_path()
STORAGE_DIR_NAME = "managed_programs"  # 用户代码的存放目录
STORAGE_PATH = os.path.join(BASE_PATH, STORAGE_DIR_NAME)


class FunkyIDE:
    def __init__(self, root):
        self.root = root
        self.root.title(f"FunkyIDE v8.0 - 律动之心")
        self.root.geometry("1000x750")

        self.storage_path = STORAGE_PATH
        self.ensure_storage_dir_exists()

        # --- 编辑器核心状态 ---
        self.open_files = {}  # {filename: {'content': str, 'tab': Frame, 'is_dirty': bool}}
        self.current_file = None
        self._highlight_job = None  # 用于延迟执行语法高亮，避免卡顿

        self.create_widgets()
        self.init_syntax_highlighting()
        self.bind_events()

        self.update_file_list()
        self.update_title()

    def create_widgets(self):
        """构建整个IDE的UI界面。"""
        # 主布局：左侧文件列表，右侧编辑区
        left_panel = Frame(self.root, width=250, padx=10, pady=10)
        left_panel.pack(side="left", fill="y")
        right_panel = Frame(self.root, padx=10, pady=10)
        right_panel.pack(side="right", fill="both", expand=True)

        # 左侧文件列表
        tk.Label(left_panel, text="程序文件列表").pack(pady=(0, 5))
        list_frame = Frame(left_panel)
        list_frame.pack(fill="both", expand=True)
        self.file_listbox = Listbox(list_frame, height=25)
        self.file_listbox.pack(side="left", fill="both", expand=True)
        scrollbar = Scrollbar(list_frame, orient="vertical", command=self.file_listbox.yview)
        scrollbar.pack(side="right", fill="y")
        self.file_listbox.config(yscrollcommand=scrollbar.set)

        # 右侧：按钮栏 + 标签栏 + 编辑区
        button_bar = Frame(right_panel)
        button_bar.pack(fill="x", pady=(0, 5))
        Button(button_bar, text="新建", command=self.new_file).pack(side="left", padx=5)
        self.save_button = Button(button_bar, text="保存", command=self.save_file, state="disabled")
        self.save_button.pack(side="left", padx=5)
        Button(button_bar, text="删除", command=self.delete_file).pack(side="left", padx=5)
        run_button = Button(button_bar, text="▶ 运行/预览", command=self.run_or_preview, bg="#4CAF50", fg="white",
                            font=("Arial", 9, "bold"))
        run_button.pack(side="right", padx=10)

        # 标签栏容器，这是实现“弹跳”效果的关键区域
        self.tab_container = Frame(right_panel, height=35, bg="#3c4043")
        self.tab_container.pack(fill="x", side="top")
        self.tab_container.pack_propagate(False)  # 固定高度，不让子组件撑开

        # 主文本编辑区
        self.text_area = Text(right_panel, wrap="word", font=("Consolas", 12), undo=True,
                              bg="#282c34", fg="#abb2bf", insertbackground="white")
        self.text_area.pack(fill="both", expand=True)
        self.text_area.edit_modified(False)

    def bind_events(self):
        """集中绑定所有事件。"""
        self.file_listbox.bind("<Double-1>", self.on_file_double_click)
        self.text_area.tag_configure("typing_effect", foreground="#00FFFF")  # 打字特效颜色
        self.text_area.bind("<KeyPress>", self.on_key_press_effect)
        self.text_area.bind("<KeyRelease>", self.schedule_syntax_highlight)
        self.text_area.bind("<<Modified>>", self.on_text_modified)
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

    # --- 特效与交互 ---

    def on_tab_enter(self, event):
        """鼠标进入标签：执行弹跳动画。"""
        tab_frame = event.widget
        # 仅当标签未被选中时才触发动画，避免视觉干扰
        if tab_frame.cget("bg") != "#5f6368":
            tab_frame.place_configure(relheight=1.1, y=-2)

    def on_tab_leave(self, event):
        """鼠标离开标签：恢复原状。"""
        tab_frame = event.widget
        tab_frame.place_configure(relheight=1.0, y=0)

    def on_key_press_effect(self, event):
        """实现“骇客帝国”风格的打字特效。"""
        # 忽略功能键和修饰键
        ignore_keys = {'Shift_L', 'Shift_R', 'Control_L', 'Control_R', 'Alt_L', 'Alt_R',
                       'Caps_Lock', 'BackSpace', 'Delete', 'Return', 'Tab', 'Escape',
                       'Up', 'Down', 'Left', 'Right', 'Home', 'End'}
        if event.state & 0x4 or event.keysym in ignore_keys:
            return

        # 只处理可打印字符
        if len(event.char) == 1 and event.char.isprintable():
            insert_index = self.text_area.index(tk.INSERT)
            # 插入带特效tag的字符，并安排一个定时任务来移除特效
            self.text_area.insert(insert_index, event.char, ("typing_effect",))
            self.root.after(400, lambda: self.fade_character_color(insert_index))
            return 'break'  # 阻止默认的字符插入，避免重复

    def fade_character_color(self, index):
        """移除指定位置字符的打字特效tag。"""
        try:
            self.text_area.tag_remove("typing_effect", index, f"{index}+1c")
        except tk.TclError:
            pass  # 如果索引在此期间失效（例如文本被删除），就忽略

    def init_syntax_highlighting(self):
        """配置Pygments语法高亮所需的颜色标签。"""
        self.style = get_style_by_name('one-dark')
        for token, style in self.style:
            tag_name = str(token)
            kwargs = {}
            if style['color']: kwargs['foreground'] = '#' + style['color']
            if style['bold']: kwargs['font'] = ('Consolas', 12, 'bold')
            if kwargs: self.text_area.tag_configure(tag_name, **kwargs)

    def schedule_syntax_highlight(self, event=None):
        """在用户停止输入一小段时间后，触发语法高亮，以提高性能。"""
        if self._highlight_job:
            self.root.after_cancel(self._highlight_job)
        self._highlight_job = self.root.after(200, self.apply_syntax_highlighting)

    def apply_syntax_highlighting(self):
        """实际执行语法高亮的核心逻辑。"""
        if not self.current_file: return

        content = self.text_area.get("1.0", "end-1c")
        if not content: return

        # 先移除旧的高亮
        for token, _ in self.style:
            self.text_area.tag_remove(str(token), "1.0", END)

        try:
            lexer = guess_lexer_for_filename(self.current_file, content)
        except ClassNotFound:
            return  # 找不到合适的词法分析器，不进行高亮

        start_index = "1.0"
        for ttype, tvalue in lex(content, lexer):
            end_index = f"{start_index}+{len(tvalue)}c"
            tag_name = str(ttype)
            if tag_name in self.text_area.tag_names():
                self.text_area.tag_add(tag_name, start_index, end_index)
            start_index = end_index

    # --- 文件与标签页管理 ---

    def open_file(self, filename):
        """打开一个文件：如果已在标签页中，则切换；否则，读取并新建标签页。"""
        if filename in self.open_files:
            self.switch_to_tab(filename)
            return

        filepath = os.path.join(self.storage_path, filename)
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
            self._create_tab(filename, content, is_dirty=False)
            self.switch_to_tab(filename)
        except Exception as e:
            messagebox.showerror("读取失败", f"无法读取文件 '{filename}':\n{e}")

    def _create_tab(self, filename, content, is_dirty):
        """创建一个新的标签页UI组件并存入状态。"""
        # 创建标签UI
        tab = Frame(self.tab_container, bg="#323639", borderwidth=1, relief="raised")
        tab_label = Label(tab, text=filename, bg="#323639", fg="white", padx=5)
        tab_label.pack(side="left", fill="both", expand=True)
        close_btn = Button(tab, text="×", bg="#323639", fg="white", relief="flat",
                           command=lambda f=filename: self.close_tab(f))
        close_btn.pack(side="right")

        # 绑定事件
        switch_cmd = lambda e, f=filename: self.switch_to_tab(f)
        tab.bind("<Button-1>", switch_cmd)
        tab_label.bind("<Button-1>", switch_cmd)

        # 绑定核心的弹跳效果事件
        tab.bind("<Enter>", self.on_tab_enter)
        tab.bind("<Leave>", self.on_tab_leave)

        # 存入状态
        self.open_files[filename] = {'content': content, 'is_dirty': is_dirty, 'tab': tab}
        self.redraw_tabs()

    def redraw_tabs(self):
        """重新绘制所有标签页，以保持正确的顺序和布局。"""
        for widget in self.tab_container.winfo_children():
            widget.pack_forget()  # 使用 pack_forget() 比 destroy() 稍好，因为Frame对象仍在内存中

        for filename in self.open_files:
            self.open_files[filename]['tab'].pack(side="left", fill="y", padx=(1, 0))

    def switch_to_tab(self, filename):
        """切换到指定的标签页。"""
        # A. 保存当前标签页的内容 (如果存在)
        if self.current_file and self.current_file in self.open_files:
            self.open_files[self.current_file]['content'] = self.text_area.get("1.0", "end-1c")

        self.current_file = filename

        # B. 更新所有标签页的视觉样式
        for f, data in self.open_files.items():
            is_active = (f == filename)
            active_bg = "#5f6368"
            inactive_bg = "#323639"
            bg = active_bg if is_active else inactive_bg

            tab, label, btn = data['tab'], data['tab'].winfo_children()[0], data['tab'].winfo_children()[1]
            tab.config(bg=bg)
            label.config(bg=bg)
            btn.config(bg=bg)

        # C. 加载新标签页的内容到编辑器
        file_data = self.open_files[filename]
        self.text_area.delete("1.0", END)
        self.text_area.insert("1.0", file_data['content'])
        self.text_area.edit_modified(False)  # 重置修改标记

        # D. 更新UI状态
        self.update_title()
        self.save_button.config(state="normal" if file_data['is_dirty'] else "disabled")
        self.apply_syntax_highlighting()

    def close_tab(self, filename):
        """关闭一个标签页，处理未保存的更改。"""
        if self.open_files[filename]['is_dirty']:
            res = messagebox.askyesnocancel("未保存", f"文件 '{filename}' 尚未保存，要现在保存吗？", parent=self.root)
            if res is True:
                self.switch_to_tab(filename)  # 必须先切换到这个tab才能保存
                self.save_file()
                if self.open_files[filename]['is_dirty']: return  # 保存失败或取消，则不关闭
            elif res is None:
                return  # 用户点了取消

        # 执行关闭
        self.open_files[filename]['tab'].destroy()
        del self.open_files[filename]

        if not self.open_files:
            self.reset_editor_state()
        elif self.current_file == filename:
            # 自动切换到剩下的第一个标签页
            next_file = list(self.open_files.keys())[0]
            self.switch_to_tab(next_file)

        self.redraw_tabs()

    def new_file(self):
        """创建一个新的未命名文件标签页。"""
        i = 1
        while True:
            new_filename = f"Untitled-{i}.py"
            filepath = os.path.join(self.storage_path, new_filename)
            if new_filename not in self.open_files and not os.path.exists(filepath):
                break
            i += 1

        self._create_tab(new_filename, "", is_dirty=True)
        self.switch_to_tab(new_filename)

    def save_file(self):
        """保存当前活动的文件。"""
        if not self.current_file: return

        filename = self.current_file
        # 如果是未命名文件，则弹出对话框要求输入新文件名
        if filename.startswith("Untitled-"):
            new_name = simpledialog.askstring("保存文件", "请输入文件名:", initialvalue=filename, parent=self.root)
            if not new_name or not self._is_valid_filename(new_name): return
            filename = new_name

        filepath = os.path.join(self.storage_path, filename)
        if os.path.exists(filepath) and self.current_file != filename:
            if not messagebox.askyesno("确认覆盖", f"文件 '{filename}' 已存在，要覆盖它吗？", parent=self.root): return

        try:
            content = self.text_area.get("1.0", "end-1c")
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(content)

            # 更新内部状态，特别是处理重命名的情况
            file_data = self.open_files.pop(self.current_file)
            file_data.update({'content': content, 'is_dirty': False})
            self.open_files[filename] = file_data

            if self.current_file != filename:
                self._update_tab_filename(self.current_file, filename, file_data['tab'])

            self.current_file = filename
            self.text_area.edit_modified(False)

            self.save_button.config(state="disabled")
            self.update_file_list()
            self.update_title()
            self.apply_syntax_highlighting()

        except Exception as e:
            messagebox.showerror("保存失败", f"无法保存文件:\n{e}", parent=self.root)

    def _update_tab_filename(self, old_name, new_name, tab):
        """辅助函数，在重命名后更新标签的UI和事件绑定。"""
        tab.winfo_children()[0].config(text=new_name)
        tab.winfo_children()[1].config(command=lambda f=new_name: self.close_tab(f))

        switch_cmd = lambda e, f=new_name: self.switch_to_tab(f)
        tab.bind("<Button-1>", switch_cmd)
        tab.winfo_children()[0].bind("<Button-1>", switch_cmd)

    def delete_file(self):
        """从文件列表删除选中的文件。"""
        selected_indices = self.file_listbox.curselection()
        if not selected_indices:
            messagebox.showwarning("提示", "请先在左侧列表中选择要删除的文件。")
            return

        filename = self.file_listbox.get(selected_indices[0])

        confirm = messagebox.askyesno("确认删除", f"确定要永久删除 '{filename}' 吗？\n此操作无法撤销！", parent=self.root)
        if confirm:
            try:
                # 如果文件已打开，先强制关闭标签页
                if filename in self.open_files:
                    # 强制关闭，不检查脏状态，因为文件马上就没了
                    self.open_files[filename]['is_dirty'] = False
                    self.close_tab(filename)

                os.remove(os.path.join(self.storage_path, filename))
                self.update_file_list()

            except Exception as e:
                messagebox.showerror("删除失败", f"无法删除文件 '{filename}':\n{e}", parent=self.root)

    # --- 运行与预览 ---

    def run_or_preview(self):
        """根据文件类型执行代码或预览内容。"""
        if not self.current_file:
            messagebox.showwarning("无文件", "没有正在编辑的文件。")
            return
        if self.open_files[self.current_file]['is_dirty']:
            messagebox.showwarning("请先保存", "文件有未保存的更改，请先保存后再操作。")
            return

        _, extension = os.path.splitext(self.current_file.lower())
        if extension == '.py':
            self.run_python_script()
        elif extension in ['.md', '.markdown']:
            self.preview_markdown()
        else:
            messagebox.showinfo("不支持", f"还不支持直接运行或预览 '{extension}' 类型的文件。")

    # ... [run_python_script, read_pipe, update_output_text, preview_markdown 这几个函数无需修改，可直接复制]
    def run_python_script(self):
        script_path = os.path.join(self.storage_path, self.current_file)
        # ... (此函数无需修改)
        output_window = Toplevel(self.root);
        output_window.title(f"运行输出 - {self.current_file}");
        output_window.geometry("600x400");
        output_window.transient(self.root)
        output_text = Text(output_window, wrap="word", font=("Consolas", 10), bg="black", fg="lightgreen");
        output_text.pack(fill="both", expand=True)
        output_text.insert(END, f"--- 正在运行: {script_path} ---\n\n");
        output_text.config(state="disabled")

        def process_runner():
            try:
                process = subprocess.Popen([sys.executable, script_path], stdout=subprocess.PIPE,
                                           stderr=subprocess.PIPE, text=True, encoding='utf-8',
                                           creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0)
                threading.Thread(target=self.read_pipe, args=(process.stdout, 'lightgreen', output_text),
                                 daemon=True).start()
                threading.Thread(target=self.read_pipe, args=(process.stderr, 'red', output_text), daemon=True).start()
            except Exception as e:
                self.root.after(0, self.update_output_text, output_text, f"\n--- 启动失败 ---\n{e}", 'red')

        threading.Thread(target=process_runner, daemon=True).start()

    def read_pipe(self, pipe, color, text_widget):
        try:
            for line in iter(pipe.readline, ''): self.root.after(0, self.update_output_text, text_widget, line, color)
        finally:
            pipe.close()

    def update_output_text(self, text_widget, line, color):
        text_widget.config(state="normal");
        text_widget.tag_config(color, foreground=color);
        text_widget.insert(END, line, color);
        text_widget.see(END);
        text_widget.config(state="disabled")

    def preview_markdown(self):
        filepath = os.path.join(self.storage_path, self.current_file)
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                md_text = f.read()
            html = markdown.markdown(md_text, extensions=['fenced_code', 'tables'])
            preview_path = os.path.join(self.storage_path, "preview.html")
            with open(preview_path, 'w', encoding='utf-8') as f:
                style = """<style>body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif; line-height: 1.6; max-width: 800px; margin: 20px auto; padding: 0 15px; color: #333;} code { background-color: #f0f0f0; padding: 2px 4px; border-radius: 3px; font-family: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, Courier, monospace;} pre { background-color: #f6f8fa; padding: 16px; border-radius: 5px; overflow-x: auto;} pre code { padding: 0; background-color: transparent; } table { border-collapse: collapse; } th, td { border: 1px solid #ddd; padding: 8px; }</style>"""
                f.write(style + html)
            webbrowser.open(f"file://{os.path.realpath(preview_path)}")
        except Exception as e:
            messagebox.showerror("预览失败", f"无法预览Markdown文件:\n{e}")

    # --- 辅助与状态更新 ---

    def ensure_storage_dir_exists(self):
        if not os.path.exists(self.storage_path):
            try:
                os.makedirs(self.storage_path)
            except OSError as e:
                messagebox.showerror("致命错误", f"无法创建工作目录 '{self.storage_path}':\n{e}")
                self.root.destroy()

    def on_file_double_click(self, event):
        selected_indices = self.file_listbox.curselection()
        if not selected_indices: return
        filename = self.file_listbox.get(selected_indices[0])
        self.open_file(filename)

    def on_text_modified(self, event=None):
        if self.current_file and not self.open_files[self.current_file]['is_dirty']:
            self.open_files[self.current_file]['is_dirty'] = True
            self.update_title()
            self.save_button.config(state="normal")
        self.text_area.edit_modified(False)  # 必须重置，否则事件只会触发一次

    def update_title(self):
        title = "FunkyIDE v8.0"
        if self.current_file:
            star = "*" if self.open_files[self.current_file]['is_dirty'] else ""
            title += f" - {self.current_file}{star}"
        self.root.title(title)

    def update_file_list(self):
        self.file_listbox.delete(0, END)
        try:
            files = [f for f in os.listdir(self.storage_path) if os.path.isfile(os.path.join(self.storage_path, f))]
            for f in sorted(files):
                self.file_listbox.insert(END, f)
        except Exception as e:
            messagebox.showerror("错误", f"无法读取文件列表:\n{e}")

    def _is_valid_filename(self, filename):
        if not filename.strip():
            messagebox.showwarning("无效文件名", "文件名不能为空。")
            return False
        return True

    def reset_editor_state(self):
        """当所有标签页关闭时，重置编辑器到初始状态。"""
        self.text_area.delete("1.0", END)
        self.current_file = None
        self.open_files.clear()
        for widget in self.tab_container.winfo_children():
            widget.destroy()
        self.save_button.config(state="disabled")
        self.update_title()
        self.apply_syntax_highlighting()

    def on_closing(self):
        """处理关闭窗口事件，检查所有未保存的文件。"""
        dirty_files = [f for f, data in self.open_files.items() if data['is_dirty']]
        if not dirty_files:
            self.root.destroy()
            return

        msg = "以下文件有未保存的更改:\n\n" + "\n".join(dirty_files) + "\n\n是否在退出前全部保存？"
        res = messagebox.askyesnocancel("退出确认", msg, parent=self.root)

        if res is True:  # 保存所有
            for f in dirty_files:
                self.switch_to_tab(f)
                self.save_file()
            # 再次检查是否都保存成功了
            if not any(data['is_dirty'] for data in self.open_files.values()):
                self.root.destroy()
        elif res is False:  # 不保存并退出
            self.root.destroy()
        # else: res is None (取消), do nothing


if __name__ == "__main__":
    root = tk.Tk()
    app = FunkyIDE(root)
    root.mainloop()


