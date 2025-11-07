"""自定义错误类型"""
from typing import Literal, Any

# ===============一级错误===============
class FastApiAppException(Exception):
    """所有 FastApi 应用中的错误基类"""
    def __init__(
            self,
            reason: str = 'error',
            code: int = 1,
            layer: Literal['controller', 'service', 'model', 'route', 'schema', 'parse', 'ai', 'http', 'others'] = 'others',
            i18n_key: str = 'error',
            i18n_args: dict = None,
            error: Exception = None,
            data: Any = None
    ):
        """
        所有 FastApi 应用中的错误基类

        :param reason: 错误原因
        :param code: 错误码
        :param layer: 发生错误的层级
        :param i18n_key: 国际化配置键
        :param i18n_args: 国际化模板参数
        :param error: 引发此错误的错误
        :param data: 错误相关任意类型数据
        """
        self.reason = reason
        self.code = code
        self.layer = layer
        self.i18n_key = i18n_key
        self.i18n_args: dict = i18n_args or {}
        self.error = error or Exception(reason)
        self.data = data

    def __str__(self):
        return f'{self.__class__.__name__}(code={self.code!r}, reason={self.reason!r}, layer={self.layer!r}, error={self.error!r})'

    def __repr__(self):
        return self.__str__()

# ===============二级错误===============
class ServiceLayerException(FastApiAppException):
    """服务层错误"""
    def __init__(self, reason: str = 'error', code: int = 1, i18n_key: str = 'error', i18n_args: dict = None, error: Exception = None, data: Any = None):
        super().__init__(reason=reason, code=code, layer='service', i18n_key=i18n_key, i18n_args=i18n_args, error=error, data=data)


class ParseException(FastApiAppException):
    """解析错误"""
    def __init__(self, reason: str = 'error', code: int = 1, i18n_key: str = 'error', i18n_args: dict = None, error: Exception = None, data: Any = None):
        super().__init__(reason=reason, code=code, layer='parse', i18n_key=i18n_key, i18n_args=i18n_args, error=error, data=data)


class AIException(FastApiAppException):
    """AI错误"""
    def __init__(self, reason: str = 'error', code: int = 1, i18n_key: str = 'error', i18n_args: dict = None,
                 error: Exception = None, data: Any = None, model_name: str = None, name: str = None, prompt: str = None):
        """
        :param model_name: 模型名称
        :param name: 实例名称
        :param prompt: 提示词
        """
        super().__init__(reason=reason, code=code, layer='ai', i18n_key=i18n_key, i18n_args=i18n_args, error=error, data=data)
        self.model_name = model_name
        self.name = name
        self.prompt = prompt

    def __str__(self):
        return f'{self.__class__.__name__}(code={self.code!r}, reason={self.reason!r}, layer={self.layer!r}, model_name={self.model_name!r}, name={self.name!r})'


class HttpException(FastApiAppException):
    """HTTP错误"""
    def __init__(self, reason: str = 'error', code: int = 1, i18n_key: str = 'error', i18n_args: dict = None, error: Exception = None, data: Any = None):
        super().__init__(reason=reason, code=code, layer='http', i18n_key=i18n_key, i18n_args=i18n_args, error=error, data=data)


class CallBackFailed(FastApiAppException):
    """回调失败"""


# ===============三级错误===============
# -----ServiceLayerException-----
class ServiceCheckFailed(ServiceLayerException):
    """服务层检查数据不通过"""
class ServiceDataNotExist(ServiceLayerException):
    """服务层数据不存在"""


# -----ParseException-----
class ProcessDocumentFailed(ParseException):
    """处理和提取文档内容失败"""
    def __init__(self, reason: str = 'error', code: int = 1, i18n_key: str = 'error', i18n_args: dict = None,
                 error: Exception = None, data: Any = None, extension: str = None):
        """
        :param extension: 文件扩展名/文件类型
        """
        super().__init__(reason=reason, code=code, i18n_key=i18n_key, i18n_args=i18n_args, error=error, data=data)
        self.extension = extension

class JsonLoadFailed(ParseException):
    """JSON加载失败"""


# -----AIException-----
class AIClientError(AIException):
    """AI客户端异常"""
class AIParseFailed(AIException):
    """AI解析失败"""
class AICallFailed(AIException):
    """AI调用失败"""


# -----HttpException-----
class RequestFailed(HttpException):
    """请求失败"""
class ResponseFailed(HttpException):
    """响应失败"""
    def __init__(self, reason: str = 'error', code: int = 1, i18n_key: str = 'error', i18n_args: dict = None,
                 error: Exception = None, data: Any = None, status_code: int = None):
        """
        :param status_code: HTTP状态码
        """
        super().__init__(reason=reason, code=code, i18n_key=i18n_key, i18n_args=i18n_args, error=error, data=data)
        self.status_code = status_code

