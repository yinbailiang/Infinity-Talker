import aiosqlite
import json
import uuid
import logging
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Dict, List, Literal, Optional
from types import TracebackType

logger = logging.getLogger(__name__)


class _BaseConversationTx:
    """对话树事务基类（共享只读查询逻辑）"""
    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._conn: aiosqlite.Connection = conn
    
    @staticmethod
    def _safe_load_json(raw: str) -> Any:
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return raw

    async def get_node(self, node_id: str) -> Optional[Dict[str, Any]]:
        async with self._conn.execute(
            "SELECT id, role, content, parent_id, branchable, current_branch_id FROM conversation_nodes WHERE id = ?",
            (node_id,),
        ) as cursor:
            row = await cursor.fetchone()
            if row is None:
                return None
            return {
                "id": row[0], "role": row[1],
                "content": self._safe_load_json(row[2]),
                "parent_id": row[3], "branchable": bool(row[4]),
                "current_branch_id": row[5],
            }

    async def get_children_ids(self, node_id: str) -> List[str]:
        async with self._conn.execute(
            "SELECT id FROM conversation_nodes WHERE parent_id = ?", (node_id,)
        ) as cursor:
            return [row[0] for row in await cursor.fetchall()]

    async def get_root_id(self) -> str:
        """在事务上下文中安全获取根节点 ID"""
        async with self._conn.execute("SELECT id FROM conversation_nodes WHERE parent_id IS NULL") as cur:
            row = await cur.fetchone()
            if row is None:
                raise RuntimeError("对话树数据损坏：未找到根节点")
            return row[0]

    async def get_all_nodes(self) -> Dict[str, Dict[str, Any]]:
        async with self._conn.execute(
            "SELECT id, role, content, parent_id, branchable, current_branch_id FROM conversation_nodes"
        ) as cursor:
            nodes: Dict[str, Dict[str, Any]] = {}
            for row in await cursor.fetchall():
                nodes[row[0]] = {
                    "id": row[0], "role": row[1],
                    "content": self._safe_load_json(row[2]),
                    "parent_id": row[3], "branchable": bool(row[4]),
                    "current_branch_id": row[5],
                }
            return nodes

    async def compute_current_node_id(self) -> str:
        async with self._conn.execute("""
            WITH RECURSIVE path(id, parent_id, current_branch_id, depth) AS (
                SELECT id, parent_id, current_branch_id, 0 FROM conversation_nodes WHERE parent_id IS NULL
                UNION ALL
                SELECT n.id, n.parent_id, n.current_branch_id, p.depth + 1
                FROM conversation_nodes n JOIN path p ON n.parent_id = p.id AND n.id = p.current_branch_id
            )
            SELECT id FROM path ORDER BY depth DESC LIMIT 1
        """) as cursor:
            row = await cursor.fetchone()
            if row is None:
                raise RuntimeError("对话树数据损坏：未找到根节点")
            return row[0]

    async def get_path_to_current(self) -> List[Dict[str, Any]]:
        current_id = await self.compute_current_node_id()
        path: List[Dict[str, Any]] = []
        nid: Optional[str] = current_id
        while nid is not None:
            node = await self.get_node(nid)
            if node is None:
                raise ValueError(f"路径断裂：节点 {nid} 不存在")
            path.append(node)
            nid = node["parent_id"]
        path.reverse()
        return [n for n in path if n["role"] != "root"]

    async def get_last_branchable_node_id(self) -> str:
        current_id = await self.compute_current_node_id()
        nid: Optional[str] = current_id
        while nid is not None:
            node = await self.get_node(nid)
            if node and node["branchable"]:
                return node["id"]
            nid = node["parent_id"] if node else None
        raise RuntimeError("未找到任何可分支节点")


class ConversationReadTx(_BaseConversationTx):
    async def __aenter__(self) -> 'ConversationReadTx':
        await self._conn.execute("BEGIN DEFERRED")
        return self

    async def __aexit__(self, exc_type: Optional[type], exc_val: Optional[BaseException], exc_tb: Optional[TracebackType]) -> Optional[bool]:
        try: await self._conn.rollback()
        except Exception: pass
        return False

    def _write_guard(self, method_name: str) -> None:
        raise PermissionError(f"只读事务禁止调用写操作: {method_name}")

    async def insert_node(self, *args: Any, **kwargs: Any) -> None: self._write_guard("insert_node")
    async def update_current_branch(self, *args: Any, **kwargs: Any) -> None: self._write_guard("update_current_branch")
    async def delete_all_except_root(self, *args: Any, **kwargs: Any) -> None: self._write_guard("delete_all_except_root")


class ConversationWriteTx(ConversationReadTx):
    async def __aenter__(self) -> 'ConversationWriteTx':
        await self._conn.execute("BEGIN IMMEDIATE")
        return self

    async def __aexit__(self, exc_type: Optional[type], exc_val: Optional[BaseException], exc_tb: Optional[TracebackType]) -> Optional[bool]:
        if exc_type:
            await self._conn.rollback()
            return False
        await self._conn.commit()
        return False

    async def insert_node(
        self, node_id: str, role: Literal["user", "system", "assistant"],
        content: str, parent_id: Optional[str] = None, branchable: bool = False
    ) -> None:
        await self._conn.execute(
            "INSERT INTO conversation_nodes (id, role, content, parent_id, branchable) VALUES (?, ?, ?, ?, ?)",
            (node_id, role, content, parent_id, int(branchable)),
        )

    async def update_current_branch(self, node_id: str, branch_id: Optional[str]) -> None:
        await self._conn.execute(
            "UPDATE conversation_nodes SET current_branch_id = ? WHERE id = ?",
            (branch_id, node_id),
        )

    async def delete_all_except_root(self, root_id: str) -> None:
        await self._conn.execute("DELETE FROM conversation_nodes WHERE id != ?", (root_id,))


class ConversationDB:
    def __init__(self, db_path: str = ":memory:") -> None:
        self.db_path: str = db_path
        self._conn: Optional[aiosqlite.Connection] = None

    async def initialize(self) -> None:
        if self._conn: return
        self._conn = await aiosqlite.connect(self.db_path)
        await self._conn.execute("PRAGMA journal_mode=WAL;")
        await self._conn.execute("PRAGMA foreign_keys=ON;")
        await self._init_schema()
        await self._ensure_root()

    async def close(self) -> None:
        if self._conn:
            await self._conn.close()
            self._conn = None

    async def _init_schema(self) -> None:
        assert self._conn
        await self._conn.execute("""
            CREATE TABLE IF NOT EXISTS conversation_nodes (
                id TEXT PRIMARY KEY,
                role TEXT NOT NULL CHECK(role IN ('root','user','system','assistant')),
                content TEXT NOT NULL,
                parent_id TEXT,
                branchable INTEGER DEFAULT 0,
                current_branch_id TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (parent_id) REFERENCES conversation_nodes(id) ON DELETE CASCADE,
                FOREIGN KEY (current_branch_id) REFERENCES conversation_nodes(id) ON DELETE SET NULL
            )
        """)
        await self._conn.execute("CREATE INDEX IF NOT EXISTS idx_parent ON conversation_nodes(parent_id);")
        await self._conn.execute("CREATE INDEX IF NOT EXISTS idx_branch ON conversation_nodes(current_branch_id);")
        await self._conn.commit()

    async def _ensure_root(self) -> None:
        assert self._conn
        async with self._conn.execute("SELECT id FROM conversation_nodes WHERE parent_id IS NULL") as cur:
            if not await cur.fetchone():
                root_id = uuid.uuid4().hex
                await self._conn.execute(
                    "INSERT INTO conversation_nodes (id, role, content, branchable) VALUES (?, ?, ?, ?)",
                    (root_id, "root", "", 1),
                )
                await self._conn.commit()

    @asynccontextmanager
    async def read_transaction(self) -> AsyncIterator[ConversationReadTx]:
        if not self._conn: raise RuntimeError("DB 未初始化")
        async with ConversationReadTx(self._conn) as tx:
            yield tx

    @asynccontextmanager
    async def write_transaction(self) -> AsyncIterator[ConversationWriteTx]:
        if not self._conn: raise RuntimeError("DB 未初始化")
        async with ConversationWriteTx(self._conn) as tx:
            yield tx