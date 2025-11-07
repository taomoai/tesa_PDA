import asyncio
from contextvars import ContextVar
from typing import Coroutine, Any, Callable
from fastapi import Request, Response, BackgroundTasks
from fastapi_app.schemas.schema import ContextInfo


class BackgroundTaskStore:
    """
    简单后台任务的暂存器

    仅用于存储在请求返回响应后，需要执行的后台异步任务。这个任务应该只是轻量级的任务，比如，后台刷新缓存。
    实际执行是在中间件将其交给FastAPI框架来执行。FastAPI会将响应返回后再执行，能提高响应速度。
    """
    def __init__(self):
        self._tasks: list[tuple[Callable[..., Coroutine[Any, Any, None]], tuple[Any, ...], dict[str, Any]]] = []

    def add_task(self, func_or_coro: Callable | Coroutine, *args, **kwargs) -> None:
        """
        智能地向暂存器中添加一个后台任务。

        本方法支持两种调用方式：
        1. 传递函数及其参数: add_task(my_func, arg1, kwarg1='foo')
        2. 传递一个已创建的协程对象: add_task(my_func(arg1, kwarg1='foo'))
        """
        # 检查传入的第一个参数是否是一个协程对象
        if asyncio.iscoroutine(func_or_coro):
            # 安全检查：如果传入了协程对象，就不应该再有额外的 args 或 kwargs
            if args or kwargs:
                raise ValueError("当向 add_task 传递协程对象时，不能再提供额外的 *args 或 **kwargs。")

            # 创建一个简单的异步包装函数，它的唯一作用就是 await 传入的协程对象
            # Starlette 的 BackgroundTasks 会调用并 await 这个 wrapper
            async def wrapper() -> None:
                await func_or_coro

            # 将这个无参数的包装函数存入任务列表
            self._tasks.append((wrapper, (), {}))

        # 否则，判断是一个普通的可调用函数
        else:
            if not callable(func_or_coro):
                raise TypeError("传递给 add_task 的第一个参数必须是可调用函数或协程对象。")
            self._tasks.append((func_or_coro, args, kwargs))

    @property
    def tasks(self) -> list[tuple[Callable[..., Coroutine[Any, Any, None]], tuple[Any, ...], dict[str, Any]]]:
        """获取所有已添加的任务"""
        return self._tasks


# 定义一个 ContextVar，用于存储当前操作请求上下文的信息 （一个请求进来，通过鉴权才会有）
# default=None 是可选的，表示如果未设置，获取时会返回 None
current_context: ContextVar[ContextInfo] = ContextVar("Current-Context")

# 当前上下文的请求对象 （一个请求进来必定会有）
current_request: ContextVar[Request] = ContextVar("Current-Request")
# 当前上下文的后台任务暂存器 （一个请求进来必定会有）
current_tasks_store: ContextVar[BackgroundTaskStore] = ContextVar("Background-TaskStore")


def safe_get_context_user_id() -> int | None:
    """安全获取当前上下文用户的ID，获取失败或无上下文则返回 None"""
    try:
        user_id = current_context.get().user_id  # 获取当前上下文
    except LookupError:
        try:
            from flask import request
            user_id = request.user_id  # 尝试从 flask 请求上下文中获取
        except Exception:
            return None
    return user_id or None


def safe_get_context_username() -> str | None:
    """安全获取当前上下文用户的名称，获取失败或无上下文则返回 None"""
    try:
        user = current_context.get().user  # 获取当前上下文
        username = user.username
    except LookupError:
        try:
            from flask import request
            user = request.user  # 尝试从 flask 请求上下文中获取
            username = user.username
        except Exception:
            return None
    return username or None


def safe_get_context_belong_org_id() -> str | None:
    """安全获取当前上下文用户的所属组织ID，获取失败或无上下文则返回 None"""
    try:
        belong_org = current_context.get().belong_org  # 获取当前上下文
    except LookupError:
        try:
            from flask import request
            belong_org = request.belong_org  # 尝试从 flask 请求上下文中获取
        except Exception:
            return None
    return belong_org or None


def safe_get_context_manage_orgs() -> list[str] | list:
    """安全获取当前上下文用户的管理组织ID列表，获取失败或无上下文则返回空list"""
    try:
        manage_orgs = current_context.get().manage_orgs  # 获取当前上下文
    except LookupError:
        try:
            from flask import request
            manage_orgs = request.manage_orgs  # 尝试从 flask 请求上下文中获取
        except Exception:
            return []
    return manage_orgs or []


def safe_get_context_tenant_id() -> int | None:
    """安全获取当前上下文租户的ID，获取失败或无上下文则返回 None"""
    try:
        tenant_id = current_context.get().tenant_id
    except LookupError:
        try:
            from flask import request
            tenant_id = request.tenant_id  # 尝试从 flask 请求上下文中获取
        except Exception:
            return None
    return tenant_id or None


class WithRequestContext:
    """
    请求上下文管理器，用于在请求处理过程中，将请求上下文信息存储在当前请求的 ContextVar 中。

    使用示例::

        with WithRequestContext(request) as wr:
            ...

    - 跟随一次任意请求，任何请求都会创建上下文
    - 自动处理token的set和reset
    """

    task_store: BackgroundTaskStore
    '''当前请求的后端任务暂存器'''

    def __init__(self, request: Request):
        self.request = request

    def __enter__(self):
        self.__request_token = current_request.set(self.request)  # 上下文：存储当前fastapi的请求对象

        self.task_store = BackgroundTaskStore()
        self.__tasks_store_token = current_tasks_store.set(self.task_store)  # 上下文：存储当前fastapi请求的后台任务暂存器
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        current_request.reset(self.__request_token)
        current_tasks_store.reset(self.__tasks_store_token)

    def submit_tasks(self, response: Response):
        """
        将后台任务暂存器的任务提交给fastapi
        :param response: 中间件 call_next 返回的fastapi响应对象
        """
        if background_tasks := self.task_store.tasks:
            final_background_tasks = BackgroundTasks()
            for func, args, kwargs in background_tasks:
                final_background_tasks.add_task(func, *args, **kwargs)
            # 通过赋值 background，告知 FastAPI：在返回响应后执行这些后台任务
            response.background = final_background_tasks


class WithAuthenticatedContext:
    """
    认证上下文管理器，用于在请求处理过程中，将认证信息存储在当前请求的 ContextVar 中。

    使用示例::

        with WithAuthenticatedContext(context_info):
            ...

    - 跟随一次已认证通过的请求，只有认证通过的请求才会创建上下文
    - 自动处理token的set和reset
    """
    def __init__(self, context_info: ContextInfo):
        self.context_info = context_info

    def __enter__(self):
        self.__context_token = current_context.set(self.context_info)  # 上下文：存储当前请求的认证信息
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        current_context.reset(self.__context_token)