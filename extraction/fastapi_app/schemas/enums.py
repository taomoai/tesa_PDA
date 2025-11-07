"""fastapi app中全局的通用枚举"""
from enum import Enum


class FieldFilterModeEnum(str, Enum):
    """字段过滤模式枚举"""
    EQUAL = '='
    NOT_EQUAL = '!='
    CONTAINS = 'contains'
    STARTS_WITH = 'starts_with'
    ENDS_WITH = 'ends_with'
    GREATER_THAN = '>'
    LESS_THAN = '<'
    GREATER_THAN_OR_EQUAL = '>='
    LESS_THAN_OR_EQUAL = '<='
