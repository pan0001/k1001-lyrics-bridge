"""Blue-and-white native control panel; original geometric graphics, no game assets."""
import tkinter as tk
from tkinter import ttk
from pathlib import Path
from PIL import Image, ImageTk
from window_chrome import TitleBar, SlimScroll
from idle_display import METRICS, validate_template
from version import VERSION
from blue_widgets import BLUE, CYAN, NAVY, MUTED, BG, LINE, YELLOW, FONT
from blue_widgets import Pattern, CutButton, Toggle, MetricChip, StatCard, Screen, unchanged_size


class SettingsWindow:
    def __init__(self, root, app):
        self.root, self.app = root, app
        self.status = tk.StringVar(value='正在连接播放器…')
        self.output = tk.StringVar(value='等待音乐播放')
        self.track = tk.StringVar(value='等待播放器')
        self.detail = tk.StringVar()
        self.message = tk.StringVar(value='关闭面板后，歌词与待机显示继续在后台运行。')
        self.sensors = tk.StringVar(value='正在读取本机传感器…')
        self.sensor_note = tk.StringVar(value='硬件数据仅在本机读取。')
        self.last_stats = None
        root.title('晴空歌词 · SkyLyrics')
        root.geometry(f'{min(1120, root.winfo_screenwidth()-70)}x{min(800, root.winfo_screenheight()-80)}')
        root.minsize(960, 680)
        root.configure(bg=BG)
        root.option_add('*Font', (FONT, 10))
        style = ttk.Style(root)
        style.theme_use('clam')
        style.configure('.', font=(FONT, 10))
        style.configure('TCombobox', padding=8, fieldbackground='#f4faff', background='#eaf5fd',
                        foreground=NAVY, bordercolor=LINE, arrowcolor=BLUE)
        style.map('TCombobox', fieldbackground=[('readonly','#f4faff')], selectbackground=[('readonly','#f4faff')],
                  selectforeground=[('readonly',NAVY)])
        style.configure('Vertical.TScrollbar', background='#cee5f5', troughcolor='white', borderwidth=0, arrowsize=10)
        pattern = Pattern(root)
        pattern.place(x=0, y=0, relwidth=1, relheight=1)
        asset = Path(__file__).parent / 'assets'
        with Image.open(asset / 'logo.png') as logo:
            self.brand_image = ImageTk.PhotoImage(logo.resize((68,68), Image.Resampling.LANCZOS))
            self.title_image = ImageTk.PhotoImage(logo.resize((26,26), Image.Resampling.LANCZOS))
            self.window_image = ImageTk.PhotoImage(logo.resize((64,64), Image.Resampling.LANCZOS))
        root.iconphoto(True, self.window_image)
        root.iconbitmap(str(asset / 'app.ico'))
        self.chrome = TitleBar(root, app.hide, self.title_image)
        shell = tk.Frame(root, bg=BG)
        shell.pack(fill='both', expand=True, padx=24, pady=(8,18))
        header = tk.Canvas(shell, height=70, bg=BG, highlightthickness=0)
        header.pack(fill='x', pady=(0, 18))
        def draw_header(event=None):
            if unchanged_size(header, event): return
            header.delete('all')
            w=header.winfo_width()
            header.create_image(27, 31, image=self.brand_image)
            header.create_text(67, 22, text='晴空歌词', anchor='w', fill=BLUE, font=(FONT,23,'bold'))
            header.create_text(228, 24, text='SKYLYRICS', anchor='w', fill=NAVY, font=('Segoe UI',17,'bold','italic'))
            header.create_text(67, 50, text='让每一段日常，都有自己的旋律。', anchor='w', fill=MUTED, font=(FONT,9))
            header.create_text(w-7, 20, text='DESKTOP  /  CONTROL PANEL', anchor='e', fill=MUTED, font=('Segoe UI',9))
            header.create_text(w-7, 44, text=f'本地运行  ·  v{VERSION}', anchor='e', fill=BLUE, font=(FONT,9))
            header.create_line(0, 69, w, 69, fill=LINE)
        header.bind('<Configure>', draw_header)
        body = tk.Frame(shell, bg=BG)
        body.pack(fill='both', expand=True)
        body.grid_columnconfigure(1, weight=1)
        body.grid_rowconfigure(0, weight=1)
        rail = tk.Frame(body, bg=BG, width=166)
        rail.grid(row=0, column=0, sticky='nsew', padx=(0,22))
        rail.grid_propagate(False)
        rail.pack_propagate(False)
        self.label(rail, 'WORKSPACE', 9, MUTED, BG, english=True).pack(anchor='w', padx=12, pady=(8,18))
        self.nav = []
        for index, title in enumerate(['自动切换', '文字编辑', '常规设置', '软件更新']):
            button = CutButton(rail, f'0{index+1}   {title}', lambda i=index:self.switch(i), width=164, height=52)
            button.pack(fill='x', pady=(0,10))
            self.nav.append(button)
        lower = tk.Frame(rail, bg=BG)
        lower.pack(side='bottom', fill='x', padx=10, pady=8)
        art=tk.Canvas(lower, height=82, bg=BG, highlightthickness=0)
        art.pack(fill='x')
        art.create_oval(34,8,120,43,outline='#bfe7fa',width=2)
        art.create_polygon(48,70,82,16,115,70,fill='',outline='#cdeafa',width=2)
        art.create_polygon(25,43,34,39,33,50,fill=YELLOW,outline='')
        self.label(lower,'MUSIC & MOMENTS',8,BLUE,BG,english=True).pack(anchor='w')
        self.label(lower,'音乐播放时显示歌词\n闲下来，也有新内容',9,MUTED,BG).pack(anchor='w',pady=(8,0))
        main=tk.Frame(body,bg=BG)
        main.grid(row=0,column=1,sticky='nsew')
        main.grid_columnconfigure(0,weight=1)
        main.grid_rowconfigure(3,weight=1)
        title=tk.Frame(main,bg=BG)
        title.grid(row=0,column=0,sticky='ew',pady=(0,14))
        self.page_title=tk.StringVar(value='自动切换')
        tk.Label(title,textvariable=self.page_title,bg=BG,fg=NAVY,font=(FONT,23,'bold')).pack(side='left')
        self.label(title,' /  DISPLAY SETTINGS',10,BLUE,BG,english=True).pack(side='left',padx=12,pady=(9,0))
        cards=tk.Frame(main,bg=BG)
        cards.grid(row=1,column=0,sticky='ew')
        self.stat_cards={}
        for i,(key,text) in enumerate([('cpu','CPU 使用率'),('memory','内存占用'),('gpu','GPU 使用率')]):
            cards.grid_columnconfigure(i,weight=1,uniform='stats')
            card=StatCard(cards,text,f'0{i+1}')
            card.grid(row=0,column=i,sticky='ew',padx=(0,12 if i<2 else 0))
            self.stat_cards[key]=card
        tk.Label(main,textvariable=self.sensors,bg=BG,fg=MUTED,font=(FONT,9),anchor='w').grid(row=2,column=0,sticky='ew',pady=(10,16))
        panels=tk.Frame(main,bg=BG)
        panels.grid(row=3,column=0,sticky='nsew')
        panels.grid_columnconfigure(0,weight=1)
        panels.grid_columnconfigure(1,minsize=262)
        panels.grid_rowconfigure(0,weight=1)
        paper=tk.Frame(panels,bg='white',highlightbackground=LINE,highlightthickness=1)
        paper.grid(row=0,column=0,sticky='nsew',padx=(0,14))
        stripe=tk.Canvas(paper,height=4,bg='white',highlightthickness=0)
        stripe.pack(fill='x')
        stripe.bind('<Configure>',lambda e: (stripe.delete('all'),stripe.create_polygon(0,0,80,0,76,4,0,4,fill=BLUE,outline='')))
        self.form_canvas=tk.Canvas(paper,bg='white',highlightthickness=0)
        self.form_canvas.configure(yscrollincrement=1)
        scrollbar=SlimScroll(paper,self.form_canvas)
        scrollbar.pack(side='right',fill='y',padx=(0,3),pady=6)
        self.form_canvas.pack(side='left',fill='both',expand=True)
        self.form_canvas.configure(yscrollcommand=scrollbar.set)
        root.bind('<MouseWheel>', self.scroll_form, add='+')
        self.form=tk.Frame(self.form_canvas,bg='white',padx=20,pady=18)
        self.form_id=self.form_canvas.create_window(0,0,window=self.form,anchor='nw')
        self.form_canvas.bind('<Configure>',lambda e:self.form_canvas.itemconfigure(self.form_id,width=e.width))
        self.form.bind('<Configure>',lambda e:self.form_canvas.configure(scrollregion=self.form_canvas.bbox('all')))
        self.pages=[tk.Frame(self.form,bg='white') for _ in range(4)]
        s=app.settings
        self.enabled=tk.BooleanVar(value=s['idle_enabled'])
        self.minutes=tk.StringVar(value=f"{s['idle_minutes']:g}")
        self.rotation=tk.StringVar(value=f"{s['rotation_seconds']:g}")
        self.mode=tk.StringVar(value=s['idle_mode'])
        auto,custom,general,updates=self.pages
        self.section(auto,'01','在音乐暂停之后')
        row=tk.Frame(auto,bg='white');row.pack(fill='x',pady=(15,3))
        self.label(row,'自动进入待机显示',11).pack(side='left')
        Toggle(row,self.enabled).pack(side='right')
        self.label(auto,'恢复播放后，自动回到当前歌词。',9,MUTED).pack(anchor='w',pady=(3,10))
        timing=tk.Frame(auto,bg='white');timing.pack(fill='x')
        timing.grid_columnconfigure(0,weight=1);timing.grid_columnconfigure(1,weight=1)
        self.number(timing,'暂停等待 / 分钟',self.minutes,.1,120,.5).grid(row=0,column=0,sticky='ew',padx=(0,14))
        self.number(timing,'轮播间隔 / 秒',self.rotation,2,60,1).grid(row=0,column=1,sticky='ew')
        self.divider(auto)
        self.section(auto,'02','待机时显示什么')
        modes=tk.Frame(auto,bg='white');modes.pack(fill='x',pady=(10,10))
        modes.grid_columnconfigure(0,weight=1);modes.grid_columnconfigure(1,weight=1)
        self.mode_buttons=[]
        for i,(value,text) in enumerate([('system','系统信息'),('custom','自定义文字')]):
            button=CutButton(modes,text,lambda v=value:self.mode.set(v),width=140,height=38,small=True)
            button.grid(row=0,column=i,sticky='ew',padx=(0,8 if i==0 else 0));self.mode_buttons.append(button)
        def mode_changed(*_):
            for button,value in zip(self.mode_buttons,['system','custom']):
                button.primary=self.mode.get()==value;button.paint()
        self.mode.trace_add('write',mode_changed);mode_changed()
        options=tk.Frame(auto,bg='white');options.pack(fill='x')
        self.metric_vars={}
        chips=[]
        for key,text in METRICS.items():
            var=tk.BooleanVar(value=key in s['metrics']);self.metric_vars[key]=var
            chips.append(MetricChip(options,text.replace('（估算）',' ≈'),var))
        self.chip_columns = None
        def arrange_chips(event=None):
            columns=3 if options.winfo_width()>=490 else 2
            if columns == self.chip_columns: return
            self.chip_columns = columns
            for col in range(3):options.grid_columnconfigure(col,weight=1 if col<columns else 0,minsize=0)
            for i,chip in enumerate(chips):
                chip.grid(row=i//columns,column=i%columns,sticky='ew',padx=(0,7 if i%columns<columns-1 else 0),pady=3)
        options.bind('<Configure>',arrange_chips)
        arrange_chips()
        self.label(auto,'其他播放器正在播放时，不进入待机模式。',9,MUTED,wrap=380).pack(anchor='w',pady=(12,0))
        self.section(custom,'01','写下屏幕上的日常')
        self.label(custom,'每行一页，可以写文字，也可以插入实时数据。',9,MUTED,wrap=390).pack(anchor='w',pady=(12,14))
        self.text=tk.Text(custom,height=7,wrap='word',bd=0,highlightthickness=1,highlightbackground='#cbe3f4',
                          highlightcolor=BLUE,padx=14,pady=14,bg='#f5faff',fg=NAVY,font=(FONT,11),undo=True,insertbackground=BLUE)
        self.text.pack(fill='both',expand=True);self.text.insert('1.0',s['custom_text'])
        self.label(custom,'可用变量',10,NAVY).pack(anchor='w',pady=(17,8))
        self.label(custom,'{time}  {date}  {cpu}  {cpu_ghz}\n{cpu_temp}  {memory}  {gpu}  {gpu_temp}',10,BLUE).pack(anchor='w')
        self.label(custom,'单位可自由填写；未接入的数据以 -- 显示。\n在「自动切换」选择「自定义文字」后保存。',9,MUTED,wrap=380).pack(anchor='w',pady=(12,0))
        self.section(general,'01','播放器与启动方式')
        self.label(general,'音乐来源',10,NAVY).pack(anchor='w',pady=(18,8))
        self.source=tk.StringVar(value=s['source'] or '自动选择')
        self.source_box=ttk.Combobox(general,textvariable=self.source,state='readonly',values=[s['source'] or '自动选择','自动选择'])
        self.source_box.pack(fill='x',pady=(0,16))
        self.lyrics=tk.BooleanVar(value=s['lyrics']);self.startup=tk.BooleanVar();self.refresh_startup()
        for text,var in [('显示 QQ 音乐歌词',self.lyrics),('登录 Windows 后自动启动',self.startup)]:
            row=tk.Frame(general,bg='white');row.pack(fill='x',pady=9)
            self.label(row,text,10).pack(side='left');Toggle(row,var).pack(side='right')
        self.label(general,'自启动时不显示面板。双击托盘图标，或右键\n选择「打开控制面板」，就能回到这里。',9,MUTED,wrap=380).pack(anchor='w',pady=(10,5))
        self.divider(general);self.section(general,'02','关于传感器')
        self.label(general,'配置一次，之后登录 Windows 自动恢复 CPU 温度。\n首次配置需在 Windows 弹窗中授权。\n支持兼容的 AMD / Intel 处理器，需已安装 PawnIO。\n\n采集程序独立运行，主界面与歌词保持普通权限。\n只在显示数据时读取；不用时停止硬件采样。\n可随时关闭温度自动启动，其他功能照常工作。',9,MUTED,wrap=390).pack(anchor='w',pady=(12,8))
        CutButton(general,'配置 / 修复温度自动启动',self.enable_temperature,width=340,height=40,primary=True,small=True).pack(fill='x',pady=(4,8))
        CutButton(general,'关闭温度自动启动',lambda:self.enable_temperature(remove=True),width=340,height=36,small=True).pack(fill='x',pady=(0,8))
        self.temperature_note=tk.StringVar(value='启用后会显示授权和采集状态。')
        tk.Label(general,textvariable=self.temperature_note,bg='white',fg=MUTED,wraplength=380,justify='left',font=(FONT,9)).pack(anchor='w')
        self.section(updates,'01','让晴空保持最新')
        self.label(updates,f'当前版本  v{VERSION}  /  Windows x64',10,BLUE).pack(anchor='w',pady=(16,10))
        self.auto_update=tk.BooleanVar(value=s['auto_update_check'])
        row=tk.Frame(updates,bg='white');row.pack(fill='x',pady=8)
        self.label(row,'自动检查 GitHub 更新',10).pack(side='left')
        Toggle(row,self.auto_update).pack(side='right')
        self.label(updates,'每天检查一次正式版，发现新版时通知。\n点击安装后才下载、重启。开关修改后请保存设置。',9,MUTED,wrap=380).pack(anchor='w',pady=(6,12))
        self.update_note=tk.StringVar(value='等待检查更新。')
        try:
            import json
            from bridge import DATA_DIR
            result=json.loads((DATA_DIR/'update-result.json').read_text(encoding='utf-8-sig'))
            self.update_note.set(result['message'])
        except (OSError,ValueError,KeyError,TypeError):
            pass
        tk.Label(updates,textvariable=self.update_note,bg='white',fg=BLUE,wraplength=380,justify='left',font=(FONT,10)).pack(anchor='w',pady=8)
        CutButton(updates,'立即检查更新',app.check_updates,width=340,height=40,small=True).pack(fill='x',pady=4)
        self.available_release=None
        self.update_busy=False
        self.install_button=CutButton(updates,'暂无可安装更新',lambda:None,width=340,height=40,small=True)
        self.install_button.pack(fill='x',pady=4)
        import webbrowser
        from updater import RELEASES_URL
        CutButton(updates,'打开 GitHub 发布页',lambda:webbrowser.open(RELEASES_URL),width=340,height=36,small=True).pack(fill='x',pady=4)
        self.divider(updates)
        self.section(updates,'02','更新说明')
        self.update_notes=tk.StringVar(value='检查到新版本后，会在这里显示更新内容。')
        tk.Label(updates,textvariable=self.update_notes,bg='white',fg=MUTED,wraplength=380,justify='left',font=(FONT,9)).pack(anchor='w',pady=(12,0))
        preview=tk.Frame(panels,bg='white',width=262,highlightbackground=LINE,highlightthickness=1)
        preview.grid(row=0,column=1,sticky='nsew');preview.grid_propagate(False)
        preview.grid_columnconfigure(0,weight=1)
        self.label(preview,'屏幕预览',14,NAVY,bold=True).grid(row=0,column=0,sticky='w',padx=20,pady=(16,2))
        self.label(preview,'SCREEN / LIVE OUTPUT',8,BLUE,english=True).grid(row=1,column=0,sticky='w',padx=20)
        Screen(preview,self.output).grid(row=2,column=0,sticky='nsew',padx=8,pady=(8,0))
        tk.Label(preview,textvariable=self.status,bg='white',fg=BLUE,wraplength=222,justify='left',font=(FONT,9)).grid(row=3,column=0,sticky='w',padx=20,pady=(4,8))
        tk.Label(preview,textvariable=self.track,bg='white',fg=NAVY,width=22,height=1,anchor='w',font=(FONT,10,'bold')).grid(row=4,column=0,sticky='ew',padx=20,pady=(3,1))
        preview.grid_rowconfigure(2,weight=1,minsize=65)
        CutButton(preview,'预览待机  /  15s',self.preview,width=220,height=40,primary=True,small=True).grid(row=6,column=0,sticky='ew',padx=15,pady=(8,8))
        CutButton(preview,'恢复自动转发',lambda:app.bridge.submit('auto',app.selected),width=220,height=40,small=True).grid(row=7,column=0,sticky='ew',padx=15,pady=(0,8))
        self.label(preview,'预览为发送内容，实际以设备为准。',8,MUTED).grid(row=8,column=0,pady=(0,12))
        footer=tk.Frame(shell,bg=BG);footer.pack(fill='x',pady=(18,0))
        self.label(footer,'✦',16,'#e8be42',BG).pack(side='left',padx=(0,10))
        tk.Label(footer,textvariable=self.message,bg=BG,fg=MUTED,wraplength=700,justify='left',font=(FONT,9)).pack(side='left',fill='x',expand=True)
        CutButton(footer,'保存设置   →',self.save,width=164,height=45,primary=True).pack(side='right',padx=(12,0))
        self.switch(0)

    def scroll_form(self, event):
        # One pixel-based canvas scroll per input event; no animation timer.
        widget = event.widget
        if isinstance(widget, (tk.Text, ttk.Combobox)):
            return
        while widget is not None:
            if widget is self.form_canvas or widget is self.form:
                if self.form_canvas.yview() != (0.0, 1.0):
                    self.form_canvas.yview_scroll(round(-event.delta * .4), 'units')
                return 'break'
            widget = getattr(widget, 'master', None)

    @staticmethod
    def label(parent,text,size=10,color=NAVY,bg='white',bold=False,wrap=0,english=False):
        return tk.Label(parent,text=text,bg=bg,fg=color,justify='left',wraplength=wrap,
                        font=('Segoe UI' if english else FONT,size,'bold' if bold else 'normal'))

    def section(self,parent,index,title):
        row=tk.Frame(parent,bg='white');row.pack(fill='x')
        self.label(row,index,11,BLUE,bold=True,english=True).pack(side='left',padx=(0,10))
        self.label(row,title,12,NAVY,bold=True).pack(side='left')

    @staticmethod
    def divider(parent):
        tk.Frame(parent,bg=LINE,height=1).pack(fill='x',pady=12)

    def number(self,parent,title,var,low,high,step):
        frame=tk.Frame(parent,bg='white')
        self.label(frame,title,9,MUTED).pack(anchor='w',pady=(0,7))
        box=tk.Frame(frame,bg='#f0f7fc',highlightbackground='#dcebf6',highlightthickness=1)
        box.pack(fill='x')
        def adjust(delta):
            try:value=float(var.get())
            except ValueError:value=low
            var.set(f'{min(high,max(low,value+delta)):g}')
        tk.Button(box,text='−',command=lambda:adjust(-step),bg='#f0f7fc',activebackground='#dcefff',fg=BLUE,
                  relief='flat',bd=0,font=('Segoe UI',15),width=2,cursor='hand2').pack(side='left')
        tk.Button(box,text='+',command=lambda:adjust(step),bg='#f0f7fc',activebackground='#dcefff',fg=BLUE,
                  relief='flat',bd=0,font=('Segoe UI',15),width=2,cursor='hand2').pack(side='right')
        tk.Entry(box,textvariable=var,bg='#f0f7fc',fg=NAVY,relief='flat',bd=0,justify='center',
                 font=('Segoe UI',18,'bold'),width=3,insertbackground=BLUE).pack(side='left',fill='x',expand=True,pady=6)
        return frame

    def switch(self,index):
        for page in self.pages:page.pack_forget()
        self.pages[index].pack(fill='both',expand=True)
        self.page_title.set(['自动切换','文字编辑','常规设置','软件更新'][index])
        for i,button in enumerate(self.nav):
            button.primary=i==index;button.paint()
        self.form_canvas.yview_moveto(0)
    def refresh_startup(self):
        from tray import startup_enabled
        self.startup.set(startup_enabled())

    def update_sources(self, sources):
        self.source_box.configure(values=['自动选择'] + sorted(set(sources + [self.source.get()]) - {'自动选择'}))

    def update_state(self, value):
        if value.get('text'):
            self.update_note.set(value['text'])
        if 'release' in value:
            release=value['release']
            self.available_release=release
            self.update_notes.set(release['notes'] if release else '暂时没有比当前版本更新的正式版。')
        if 'busy' in value:
            self.update_busy=value['busy']
        available=self.available_release and not self.update_busy
        self.install_button.text=('下载并安装 '+self.available_release['version']) if available else ('请稍候…' if self.update_busy else '暂无可安装更新')
        self.install_button.primary=bool(available)
        self.install_button.command=self.app.install_update if available else lambda:None
        self.install_button.paint()
        if value.get('notify'):
            self.message.set(value['text']+' · 在「软件更新」中查看。')

    def update_stats(self, snapshot):
        if snapshot == self.last_stats:
            return
        self.last_stats = snapshot
        for key, card in self.stat_cards.items():
            card.set(snapshot.get(key))
        def value(key, unit):
            return str(snapshot[key])+unit if snapshot.get(key) is not None else '未接入'
        self.sensors.set('CPU 频率  '+('~'+value('cpu_ghz',' GHz') if snapshot.get('cpu_ghz') else '未接入')+
                         '    /    CPU 温度  '+value('cpu_temp','°C')+'    /    GPU 温度  '+value('gpu_temp','°C'))
        from cpu_temperature import STATUS_TEXT
        note = STATUS_TEXT.get(snapshot.get('cpu_temp_status'), 'CPU 温度：在「常规设置」查看采集状态。')
        if snapshot.get('cpu_temp_source') == 'external':
            note = 'CPU 温度来自外部监控工具。'
        self.sensor_note.set(note)
        self.temperature_note.set(note)

    def enable_temperature(self, remove=False):
        from cpu_temperature import STATUS_TEXT
        self.app.bridge.stats.enable_cpu_temperature(remove=remove)
        self.temperature_note.set(STATUS_TEXT.get(self.app.bridge.stats.temperature.status, '正在准备采集。'))

    def save(self, preview=False):
        try:
            minutes, rotation = float(self.minutes.get()), float(self.rotation.get())
            if not .1 <= minutes <= 120 or not 2 <= rotation <= 60:
                raise ValueError('等待时间需为 0.1～120 分钟，轮播时间需为 2～60 秒。')
            text = self.text.get('1.0', 'end').strip()
            validate_template(text)
            metrics = [key for key, var in self.metric_vars.items() if var.get()]
            if not metrics:
                raise ValueError('请至少选择一项系统信息。')
            settings = dict(source='' if self.source.get() == '自动选择' else self.source.get(),
                            lyrics=self.lyrics.get(), idle_enabled=self.enabled.get(), idle_minutes=minutes,
                            rotation_seconds=rotation, idle_mode=self.mode.get(), metrics=metrics, custom_text=text,
                            auto_update_check=self.auto_update.get())
            return self.app.apply_settings(settings, self.startup.get(), preview=preview)
        except Exception as exc:
            self.message.set(str(exc) if isinstance(exc, ValueError) else '保存失败，请检查程序日志后重试。')
            return False

    def preview(self):
        self.save(preview=True)

