from fastapi_app.schemas.schema import ApiResponse
from flask_app.middlewares.response import success, error


class ResponseUtil:
    @staticmethod
    def success(data=None, message="success", code=0) -> ApiResponse:
        """成功响应"""
        return ApiResponse(**success(data=data, message=message, code=code))

    @staticmethod
    def error(message="error", code=1, data=None) -> ApiResponse:
        """错误响应"""
        return ApiResponse(message=message, code=code, data=data)

    @staticmethod
    def failure(message="failure", code=2, data=None) -> ApiResponse:
        """失败响应"""
        return ApiResponse(message=message, code=code, data=data)
