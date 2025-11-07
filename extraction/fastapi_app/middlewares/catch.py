from fastapi import FastAPI, Request
from fastapi import status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from loguru import logger
from pydantic import ValidationError

from flask_app.middlewares.response import error
from pydantic_validation_decorator import FieldValidationError
from fastapi_app.i18n import translate_message, get_translations, get_locale_text


async def _format_pydantic_validation_error(request: Request, exc: ValidationError | RequestValidationError, key: str) -> dict:
    """
    格式化 pydantic 校验不通过的错误信息为一句话。返回 code=1 的错误消息dict

    :param request: 请求对象
    :param exc: 错误对象。ValidationError 是单纯数据模型检验不通过，RequestValidationError 是fastapi自动校验后的数据模型校验不通过
    :param key: 开头提示语对应的 i18n 的键
    :return: {'code': 1, 'message': '提示语格式化结果', 'data': {...}}
    """
    # 初始化一个空列表来收集拼接后的错误信息
    message_parts = []

    # 获取三段文本的翻译映射
    translations = get_translations(request)
    key_unknown = 'error.unknown'
    key_loc = 'validation.error.pydantic.location'
    unknown_err = translations.get(key_unknown, key_unknown)
    loc_tp = translations.get(key_loc, key_loc)

    # `exc.errors()` 返回一个包含所有校验错误的列表，每个错误都是一个字典，包含 loc, msg, type 等信息
    for err in exc.errors():
        # err['loc'] 是一个元组，例如 ('body', 'age') 或 ('query', 'q') 转换成 "body.age" 的形式
        field_location = ".".join(map(str, err.get("loc", [])))
        err_msg = err.get("msg", unknown_err)
        message_parts.append(loc_tp.format(loc=field_location, msg=err_msg))

    msg = ' | '.join(message_parts)
    result = {'code': 1, 'message': f"{translations.get(key, key)}：{msg}", 'data': exc.errors()}
    return result


def catch_exception(app: FastAPI):
    """全局异常处理"""

    # 自定义字段检验异常
    @app.exception_handler(FieldValidationError)
    async def field_validation_error_handler(request: Request, exc: FieldValidationError):
        logger.warning(f'[FastAPI] {exc.message}')
        result = error(message=translate_message(exc.message))
        return JSONResponse(status_code=status.HTTP_200_OK, content=jsonable_encoder(result))

    @app.exception_handler(ValidationError)
    async def validation_error_handler(request: Request, exc: ValidationError):
        logger.warning(f'[FastAPI] 数据校验不通过：{exc}')
        key = 'validation.error.request_param' if exc.title == 'PaginationSchema' else 'validation.error.data_failed'
        result = await _format_pydantic_validation_error(request=request, exc=exc, key=key)
        return JSONResponse(status_code=status.HTTP_200_OK, content=jsonable_encoder(result))

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        """全局捕获 Pydantic 校验错误，并重新定义返回格式"""
        result = await _format_pydantic_validation_error(request=request, exc=exc, key='validation.error.request_param')
        return JSONResponse(status_code=422, content=jsonable_encoder(result)) # 保持 422 响应码
