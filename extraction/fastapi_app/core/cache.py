"""
内存中的缓存数据
"""
from __future__ import annotations
import asyncio
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi_app.core.database import readonly
from fastapi_app.core.context import current_tasks_store
from fastapi_app.utils.tiny_func import simple_exception

# --- 全局缓存变量 ---
# 组织树结构: {tenant_id: [OrganizationTreeNode, ...]}
_organization_tree_cache: dict[int, list['OrganizationTreeNode']] = {}
# 平铺结构：{tenant_id: [OrganizationSimple, ...]}
_organization_simple_cache: dict[int, list['OrganizationSimple']] = {}


class OrganizationCacheManager:
    """管理组织树内存缓存的单例类"""
    _lock = asyncio.Lock()

    # ----------对外提供5个方法：后台任务刷新租户缓存、后台任务刷新全部缓存、获取缓存；立即执行刷新租户缓存、立即执行刷新全部缓存--------

    def refresh_tenant_cache(self, tenant_id: int):
        """[任务安全·非阻塞] 添加任务：后台刷新指定租户的组织树缓存。"""
        try:
            task_store = current_tasks_store.get()
        except LookupError:
            raise ValueError("无法添加刷新缓存任务，当前无请求上下文")
        task_store.add_task(self.refresh_tenant_cache_async(tenant_id=tenant_id))

    def refresh_all_cache(self):
        """[任务安全·非阻塞] 添加任务：后台刷新所有租户的组织树缓存"""
        try:
            task_store = current_tasks_store.get()
            task_store.add_task(self.refresh_all_cache_async())
        except LookupError:
            # 无上下文，通过 asyncio.create_task 创建任务（初始化时）
            asyncio.create_task(self.refresh_all_cache_async())

    async def get_scoped_org_ids_by_tree(self, belong_org: str, manage_orgs: list[str] | None, tenant_id: int) -> list[str]:
        """[任务安全/核心] 从内存组织树结构缓存中异步获取可见的所有组织ID

        - 包含指定的管理组织及其所有后代组织。
        - 若管理组织有值，则以管理组织为准；否则以所属组织为准。
        - 此方法会遍历所有后代组织，所以可见组织ID只会增加（或不变），不会减少

        :param belong_org: 所属组织ID
        :param manage_orgs: 管理组织ID列表
        :param tenant_id: 所在租户ID
        :return: 可见的所有组织ID列表
        """
        assert manage_orgs is None or isinstance(manage_orgs, list), f"管理组织ID列表必须是 list[org_id] 或 None，而非{type(manage_orgs)}"
        if not belong_org and not manage_orgs:
            return []
        real_manage_orgs: list[str] = manage_orgs or [belong_org]  # 无管理组织，则以所属的组织为准

        async with self._lock:
            tenant_tree = _organization_tree_cache.get(tenant_id, [])

        if not tenant_tree:
            logger.warning(f"缓存中未找到租户 {tenant_id} 的组织树。")
            return real_manage_orgs  # 默认返回自身（优先以管理组织ID为准）

        # 获取每个管理组织及其所有后代组织
        all_manage_orgs = set(real_manage_orgs)
        for manage_org in real_manage_orgs:
            node = self._find_node_in_list(tenant_tree, manage_org)
            if node:
                all_manage_orgs.update(self._get_descendant_ids_from_node(node))
        return list(all_manage_orgs)

    async def get_scoped_org_ids_by_simple(self, belong_org: str, manage_orgs: list[str] | None, tenant_id: int) -> list[str]:
        """[任务安全/核心] 从内存组织平铺结构缓存中异步获取可见的所有组织ID

        - 精确指定管理组织，如果禁用（is_active==False）则将排除于可见组织。
        - 若管理组织有值，则以管理组织为准；否则以所属组织为准。
        - 此方法仅对禁用组织做排除，所以可见组织ID只会减少（或不变），不会增加

        :param belong_org: 所属组织ID
        :param manage_orgs: 管理组织ID列表
        :param tenant_id: 所在租户ID
        :return: 可见的所有组织ID列表
        """
        assert manage_orgs is None or isinstance(manage_orgs, list), f"管理组织ID列表必须是 list[org_id] 或 None，而非{type(manage_orgs)}"
        if not belong_org and not manage_orgs:
            return []
        real_manage_orgs = manage_orgs or [belong_org]  # 无管理组织，则以所属的组织为准

        async with self._lock:
            tenant_simple = _organization_simple_cache.get(tenant_id, [])

        if not tenant_simple:
            logger.warning(f"缓存中未找到租户 {tenant_id} 的组织平铺结构。")
            return real_manage_orgs # 默认返回自身（优先以管理组织ID为准）
        return list({org.id for org in tenant_simple if org.id in real_manage_orgs and org.is_active})

    async def get_organization_tree(self, tenant_id: int) -> list[OrganizationTreeNode] | None:
        """[任务安全] 从内存缓存中获取指定租户的组织树。

        :param tenant_id: 租户ID
        :return: 组织树列表，如果缓存未命中则返回 None
        """
        async with self._lock:
            return _organization_tree_cache.get(tenant_id)

    async def get_organization_simple(self, tenant_id: int) -> list[OrganizationSimple] | None:
        """[任务安全] 从内存缓存中获取指定租户的所有组织平铺结构。

        :param tenant_id: 租户ID
        :return: 组织平铺结构列表，如果缓存未命中则返回 None
        """
        async with self._lock:
            return _organization_simple_cache.get(tenant_id)

    # ---------核心方法：异步刷新组织树缓存---------

    @readonly()
    async def refresh_tenant_cache_async(self, tenant_id: int, *, db: AsyncSession = None):
        """[任务安全] 异步刷新指定租户的组织树缓存。"""
        async with self._lock:
            await self.__internal_refresh_tenant_cache(tenant_id=tenant_id, db=db)

    @readonly()
    async def refresh_all_cache_async(self, *, db: AsyncSession = None):
        """[任务安全] 异步刷新所有租户的缓存，用于服务启动时。"""
        from fastapi_app.modules.master_data_service.organization.model import Organization

        logger.info("------开始刷新所有租户的组织树缓存------")
        tenant_ids = await Organization.select_all_tenant_ids(db=db)
        async with self._lock:
            logger.info("持有锁，开始批量刷新所有租户...")
            for tenant_id in tenant_ids:
                # 直接调用内部方法，避免重入锁导致死锁
                await self.__internal_refresh_tenant_cache(tenant_id=tenant_id, db=db)
        logger.info("------所有租户的组织树缓存已刷新------")
        logger.info(f'当前所有组织树：')
        for tenant_id, tree in _organization_tree_cache.items():
            logger.info(f'租户 {tenant_id} 组织树：{[node.model_dump() for node in tree]}')

    # ---------私有方法-----------

    @staticmethod
    def _build_tree(org_list: list[OrganizationSimple]) -> list[OrganizationTreeNode]:
        """
        将扁平的组织列表构建成树形结构。
        采用迭代方式，性能更优，且避免递归深度限制。

        :param org_list: 所有组织列表
        """
        node_map = {org.id: OrganizationTreeNode(**org.model_dump()) for org in org_list}
        root_nodes = []

        for org in org_list:
            node = node_map[org.id]
            if org.parent_id and org.parent_id in node_map:
                parent_node = node_map[org.parent_id]
                parent_node.children.append(node)
            else:
                # 如果没有父ID，或者父ID不存在（数据异常），则视为根节点
                root_nodes.append(node)
        return root_nodes

    async def __internal_refresh_tenant_cache(self, tenant_id: int, db: AsyncSession):
        """
        [私有方法] 刷新指定租户缓存的核心逻辑，不包含锁。
        仅应在已持有锁的上下文中调用。
        """
        from fastapi_app.modules.master_data_service.organization.model import Organization

        logger.info(f"开始刷新租户 {tenant_id} 的组织树缓存...")
        try:
            org_flat_list = await Organization.select_all_orgs_info(tenant_id=tenant_id, active_only=False, db=db)
            tree = self._build_tree(org_flat_list)
        except Exception as e:
            logger.error(f"刷新租户 {tenant_id} 的组织树缓存失败：{simple_exception(e)}")
            raise e
        _organization_tree_cache[tenant_id] = tree
        _organization_simple_cache[tenant_id] = org_flat_list
        logger.info(f"租户 {tenant_id} 的组织树缓存刷新完成，根节点数: {len(tree)}；总节点数: {len(org_flat_list)}")

    @staticmethod
    def _find_node_in_list(nodes: list[OrganizationTreeNode], org_id: str) -> OrganizationTreeNode | None:
        """在节点列表中广度优先搜索指定ID的节点"""
        if not nodes:
            return None
        queue = list(nodes)
        while queue:
            node = queue.pop(0)
            if node.id == org_id:
                return node
            queue.extend(node.children)
        return None

    @staticmethod
    def _get_descendant_ids_from_node(node: OrganizationTreeNode) -> list[str]:
        """从指定节点开始，获取所有后代节点的ID"""
        ids = []
        queue = list(node.children)
        while queue:
            child = queue.pop(0)
            ids.append(child.id)
            queue.extend(child.children)
        return ids


# 创建一个全局实例供应用各处使用
orgCacheManager = OrganizationCacheManager()
__all__ = ["orgCacheManager"]


from fastapi_app.modules.master_data_service.organization.schema import OrganizationSimple, OrganizationTreeNode