"""Settings, idle timing and display formatting; no hardware side effects."""
from datetime import datetime
from string import Formatter

DEFAULTS = dict(source='QQMusic.exe', lyrics=True, idle_enabled=True, auto_update_check=True,
                idle_minutes=5.0, idle_mode='system', rotation_seconds=5,
                metrics=['cpu', 'frequency', 'cpu_temp', 'memory', 'gpu', 'gpu_temp'],
                custom_text='现在是 {time}\nCPU {cpu}% · 内存 {memory}%\nGPU {gpu}% · {gpu_temp}°C')
METRICS = {'cpu': 'CPU 使用率', 'frequency': 'CPU 频率（估算）',
           'cpu_temp': 'CPU 温度', 'memory': '内存占用率',
           'gpu': 'GPU 使用率', 'gpu_temp': 'GPU 温度'}
TOKENS = {'time', 'date', 'cpu', 'cpu_ghz', 'cpu_temp', 'memory', 'gpu', 'gpu_temp'}


def validate_template(text):
    if len(text) > 2000:
        raise ValueError('自定义内容请控制在 2000 字以内。')
    if not text.strip():
        raise ValueError('请至少填写一行自定义文字。')
    try:
        for _, field, spec, conversion in Formatter().parse(text):
            if field is not None and (field not in TOKENS or spec or conversion):
                raise ValueError('仅支持界面列出的变量，例如 {time}、{cpu}。')
    except ValueError as exc:
        raise ValueError('文字模板格式有误：' + str(exc)) from exc
    if any(len(line) > 160 for line in text.splitlines()):
        raise ValueError('每行请控制在 160 字以内，长内容可分行轮播。')


def settings_from(value):
    out = dict(DEFAULTS, metrics=list(DEFAULTS['metrics']))
    if not isinstance(value, dict):
        return out
    for key in ('lyrics', 'idle_enabled', 'auto_update_check'):
        if isinstance(value.get(key), bool):
            out[key] = value[key]
    if isinstance(value.get('source'), str):
        out['source'] = value['source']
    for key, low, high in [('idle_minutes', .1, 120), ('rotation_seconds', 2, 60)]:
        try:
            number = float(value[key])
            if low <= number <= high:
                out[key] = number
        except (KeyError, TypeError, ValueError):
            pass
    if value.get('idle_mode') in ('system', 'custom'):
        out['idle_mode'] = value['idle_mode']
    if isinstance(value.get('metrics'), list):
        choices = list(dict.fromkeys(x for x in value['metrics'] if isinstance(x, str) and x in METRICS))
        if choices:
            out['metrics'] = choices
    if isinstance(value.get('custom_text'), str):
        try:
            validate_template(value['custom_text'])
            out['custom_text'] = value['custom_text']
        except ValueError:
            pass
    return out


class IdleClock:
    def __init__(self):
        self.since = None

    def active(self, playing, now, enabled, minutes):
        if playing or not enabled:
            self.since = None
            return False
        if self.since is None:
            self.since = now
        return now - self.since >= minutes * 60


def values_for(snapshot, now=None):
    now = now or datetime.now()
    values = {key: '--' if snapshot.get(key) is None else str(snapshot[key]) for key in TOKENS}
    values.update(time=now.strftime('%H:%M'), date=now.strftime('%Y-%m-%d'))
    return values


def idle_needs_stats(settings):
    """Clock/date/literal pages do not need a running hardware sampler."""
    if settings['idle_mode'] == 'system':
        return True
    return any(field in TOKENS - {'time', 'date'}
               for _, field, _, _ in Formatter().parse(settings['custom_text']))


def display_pages(settings, snapshot, now=None):
    values = values_for(snapshot, now)
    if settings['idle_mode'] == 'custom':
        return [line.format_map(values) for line in settings['custom_text'].splitlines() if line.strip()]
    formats = {'cpu': 'CPU {cpu}%', 'frequency': 'CPU ~{cpu_ghz} GHz',
               'cpu_temp': 'CPU {cpu_temp}°C', 'memory': '内存 {memory}%',
               'gpu': 'GPU {gpu}%', 'gpu_temp': 'GPU {gpu_temp}°C'}
    keys = {'frequency': 'cpu_ghz'}
    return [formats[key].format_map(values) if snapshot.get(keys.get(key, key)) is not None
            else METRICS[key] + '：不可用' for key in settings['metrics']]
