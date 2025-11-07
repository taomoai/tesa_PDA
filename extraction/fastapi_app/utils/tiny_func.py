"""使用频繁的小型方法"""
import re
import traceback
from pathlib import Path


def simple_exception(err: Exception):
    """简化错误日志，将文件路径从项目根路径开始打印"""
    msg = ''.join(traceback.format_exception(err)).replace(str(Path.cwd()), "")
    return f'{err.__class__.__name__}: {err}\nAt: \n{msg}'


def sanitize_for_excel_named_range(name: str) -> str:
    """净化字符串，使其可以作为Excel命名范围。"""
    if not name:
        return ""
    # 替换空格、连字符和其他不允许的字符为下划线
    name = re.sub(r'[\s\-()\[\]{}:;,"\'./\\?*&^%$#@!~`+=<>|]', '_', name)
    # 如果以数字开头，在前面加一个下划线
    if name[0].isdigit():
        name = '_' + name
    # 截断到255个字符以内（Excel命名范围的限制）
    return name[:255]