import json
import uuid
import logging
from typing import Any, Dict, List, Literal, Optional, Union
from types import TracebackType

from .database.aiosqlite import ConversationDB

logger = logging.getLogger(__name__)


class ConversationManager:
    def __init__(self, db_path: str = ":memory:") -> None:
        self._db = ConversationDB(db_path)

    async def __aenter__(self) -> "ConversationManager":
        await self._db.initialize()
        return self

    async def __aexit__(
        self,
        exc_type: Optional[type],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> Optional[bool]:
        await self._db.close()
        return False

    async def connect(self) -> None:
        await self._db.initialize()

    async def close(self) -> None:
        await self._db.close()

    async def add_message(
        self,
        role: Literal["user", "system", "assistant"],
        content: Union[str, List[Dict[str, Any]]],
        branchable: bool = False,
    ) -> str:
        new_id = uuid.uuid4().hex
        content_json = json.dumps(content, ensure_ascii=False)
        async with self._db.write_transaction() as tx:
            current_id = await tx.compute_current_node_id()
            await tx.insert_node(new_id, role, content_json, current_id, branchable)
            await tx.update_current_branch(current_id, new_id)
        logger.debug(f"Added {role} message: id={new_id}")
        return new_id

    async def get_linear_history(self) -> List[Dict[str, Any]]:
        async with self._db.read_transaction() as tx:
            path = await tx.get_path_to_current()
        return [{"role": n["role"], "content": n["content"]} for n in path if n["role"] != "root"]

    async def get_linear_nodes(self) -> List[Dict[str, Any]]:
        async with self._db.read_transaction() as tx:
            path = await tx.get_path_to_current()
        return [n for n in path if n["role"] != "root"]

    async def clear(self) -> None:
        async with self._db.write_transaction() as tx:
            root_id = await tx.get_root_id()
            await tx.delete_all_except_root(root_id)
            await tx.update_current_branch(root_id, None)
        logger.debug("Conversation cleared")

    async def get_current_node_id(self) -> str:
        async with self._db.read_transaction() as tx:
            return await tx.compute_current_node_id()

    async def get_node_by_id(self, node_id: str) -> Optional[Dict[str, Any]]:
        async with self._db.read_transaction() as tx:
            return await tx.get_node(node_id)
    
    async def get_children_ids(self, node_id: str) -> List[str]:
        async with self._db.read_transaction() as tx:
            return await tx.get_children_ids(node_id)

    async def switch_to_branch(self, node_id: str, target_branch_id: str) -> None:
        async with self._db.write_transaction() as tx:
            children = await tx.get_children_ids(node_id)
            if target_branch_id not in children:
                raise ValueError(f"节点 {node_id} 没有子节点 {target_branch_id}")
            
            node = await tx.get_node(node_id)
            if node is None:
                raise ValueError(f"节点 {node_id} 不存在")
            if not node["branchable"]:
                raise ValueError(f"节点 {node_id} 不是可分支点")
                
            await tx.update_current_branch(node_id, target_branch_id)
        logger.debug(f"Switched branch of {node_id} to {target_branch_id}")

    async def fork(self, node_id: str) -> None:
        async with self._db.write_transaction() as tx:
            node = await tx.get_node(node_id)
            if node is None:
                raise ValueError(f"节点 {node_id} 不存在")
            if not node["branchable"]:
                raise ValueError(f"节点 {node_id} 不是可分支点")
            await tx.update_current_branch(node_id, None)
        logger.debug(f"Forked new branch at {node_id}")

    async def get_branches(self, node_id: str) -> List[str]:
        async with self._db.read_transaction() as tx:
            return await tx.get_children_ids(node_id)

    async def get_root_id(self) -> str:
        async with self._db.read_transaction() as tx:
            return await tx.get_root_id()

    async def get_last_branchable_node_id(self) -> str:
        async with self._db.read_transaction() as tx:
            return await tx.get_last_branchable_node_id()