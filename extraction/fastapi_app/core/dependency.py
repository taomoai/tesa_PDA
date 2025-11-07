import inspect
from types import UnionType
from typing import Type, Optional, Callable, get_args, get_origin, Annotated, Union, Any
from pydantic import BaseModel, Json
from fastapi import Query
from pydantic.fields import FieldInfo
from pydantic_core import PydanticUndefined


def _is_json_in_annotation(annotation: type | None) -> bool:
    """
    类型检查函数，检查给定的类型注解（及其内部）是否包含 pydantic.Json。
    它能正确处理 Optional[T] 和 Pydantic V2 内部使用的 Annotated[T, Json]。
    """
    origin = get_origin(annotation)

    # 1. 解构 Union 类型, 例如 Optional[T]
    if origin in [Union, UnionType]:
        return any(_is_json_in_annotation(arg) for arg in get_args(annotation))

    # 2. 解构 Annotated 类型
    if origin is Annotated:
        # 首先，递归检查基础类型 T
        base_type = get_args(annotation)[0]
        if _is_json_in_annotation(base_type):
            return True
        # 然后，检查元数据中是否有 Json 标记 (例如 Pydantic V2 的 Annotated[Any, Json()])
        for metadata in get_args(annotation)[1:]:
            if isinstance(metadata, Json) or metadata is Json:
                return True
        return False

    # 3. 处理泛型 Json, 例如 Json[dict[str, str]] 或 Json[list[int]]，对于这种情况, get_origin(annotation) 会返回 Json 类本身。
    if origin is Json:
        return True

    # 4. 直接判断
    if isinstance(annotation, type) and issubclass(annotation, Json):
        return True

    return False


def is_json_type(field_info: FieldInfo) -> bool:
    """
    一个健壮的函数，通过检查 FieldInfo 对象的元数据(metadata)和注解(annotation) 来判断一个字段是否为 pydantic.Json 类型。
    """
    # 策略 1: 检查元数据。这是处理 Json[T] 的关键。
    # Pydantic V2 会把 Json 包装器放在 metadata 中。
    for item in field_info.metadata:
        if item is Json or isinstance(item, Json):
            return True
        # 也兼容元数据中是泛型别名的情况
        if get_origin(item) is Json:
            return True

    # 策略 2: 如果元数据中没有，则检查注解本身。
    # 这主要处理 c: Json, d: Optional[Json], f: Json | str 等情况。
    return _is_json_in_annotation(field_info.annotation)


def as_query(model: Type[BaseModel]) -> Callable:
    """
    一个依赖项工厂，它接收一个 Pydantic 模型，并动态创建一个依赖函数。
    这个函数会将模型的字段转换为一组 FastAPI 的 Query 参数，同时完美解决文档问题。

    使用示例::

        @router.get('/list')
        async def get_list(query: OneSchema = Depends(as_query(OneSchema))):
            return await controller.get_list(query)
    """

    # 动态创建的依赖函数的参数列表
    new_params = []

    # 遍历 Pydantic 模型的所有字段
    for field_name, field_info in model.model_fields.items():
        field_name: str
        field_info: FieldInfo

        # 1. 确定参数的类型注解
        # 如果字段类型是 Json 或 Json[T]，告诉 FastAPI 它是一个 str，否则，使用原始的字段类型
        if is_json_type(field_info):
            param_annotation = str if field_info.is_required() else Optional[str]
        else:
            param_annotation = field_info.annotation

        # 2. 确定 Query 的默认值
        default_value: Any
        if field_info.is_required():
            default_value = ...
        elif field_info.default_factory:
            # 字段可选，且由 default_factory 提供默认值。
            # 在 Query 依赖项中，它不应该有一个默认的查询值（即 None，因为它不可在URL中表示），
            # Pydantic 验证时会使用 default_factory 来生成值。
            default_value = None
        elif field_info.default is not PydanticUndefined:
            default_value = field_info.default
        else:
            # 理论上，如果不是必填，没有 default_factory，也没有 default，那么它应该是 Optional 的。在这种情况下，默认值应该是 None。
            default_value = None

        # --- 创建 Query 参数 ---
        query_param = Query(
            default=default_value,
            description=field_info.description,
            example=field_info.examples[0] if field_info.examples else None,
        )

        # 创建一个新的函数签名参数
        new_params.append(
            inspect.Parameter(
                name=field_name,
                kind=inspect.Parameter.KEYWORD_ONLY,
                default=query_param,
                annotation=param_annotation
            )
        )

    # 创建新的函数签名
    new_signature = inspect.Signature(new_params)

    # --- 动态创建依赖函数 ---
    async def dependency(**kwargs):
        """这个函数是 FastAPI 实际调用的依赖项"""
        # FastAPI 会将接收到的查询参数通过 kwargs 传入
        # 我们用这些参数来验证和创建 Pydantic 模型实例
        return model(**kwargs)

    # 将动态创建的签名赋予这个函数
    dependency.__signature__ = new_signature

    # 返回这个全新的、为指定模型量身定做的依赖函数
    return dependency