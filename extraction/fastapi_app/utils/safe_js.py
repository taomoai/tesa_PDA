"""安全转换为json对象"""

from typing import Optional, Annotated
from pydantic import BeforeValidator

# JavaScript 的最大安全整数是 2**53 - 1
max_safe_integer = 2 ** 53 - 1

def encode_list_numbers(v: Optional[list]) -> Optional[list]:
    """遍历列表，如果元素是大于JS安全整数范围的整数，则转换为字符串。"""
    if v is None:
        return None
    return [str(i) if isinstance(i, int) and i > max_safe_integer else i for i in v]


json_encoders_config = {
    int: lambda x: str(x) if x > max_safe_integer else x,
    list: encode_list_numbers
}

# ------------ 预校验器 ------------
BeforeValidatorStrip = BeforeValidator(lambda x: x.strip() if isinstance(x, str) else x)
'''str预验证器：预先进行strip'''


BeforeValidatorEmptyStrToNone = BeforeValidator(lambda x: None if isinstance(x, str) and x.strip() == '' else x)
'''str预验证器：空字符串转为None'''


# ------------ 以下可直接用于 pydantic 字段类型声明 ------------
StrStrip = Annotated[str, BeforeValidatorStrip]
'''str类型，用于声明在 pydantic 中对字符串进行 .strip() 预处理的字段类型'''
