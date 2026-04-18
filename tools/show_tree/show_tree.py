#!/usr/bin/env python3
"""
目录树状结构展示工具 (支持正则过滤)
"""

import argparse
import os
import re
import sys
from typing import Any, Generator, List, Optional, Tuple


def compile_patterns(patterns: Optional[List[str]]) -> Optional[List[re.Pattern[Any]]]:
    if not patterns:
        return None
    compiled: List[re.Pattern[Any]] = []
    for p in patterns:
        try:
            compiled.append(re.compile(p, re.IGNORECASE))
        except re.error as e:
            print(f"警告: 无效正则表达式 '{p}': {e}", file=sys.stderr)
    return compiled or None


def matches_any(name: str, patterns: Optional[List[re.Pattern[Any]]]) -> bool:
    if not patterns:
        return False
    return any(p.search(name) for p in patterns)


def filter_item(name: str, is_dir: bool,
                exclude_patterns: Optional[List[re.Pattern[Any]]],
                include_patterns: Optional[List[re.Pattern[Any]]],
                dir_only: bool, file_only: bool) -> bool:
    if dir_only and not is_dir:
        return False
    if file_only and is_dir:
        return False
    if include_patterns and not matches_any(name, include_patterns):
        return False
    if exclude_patterns and matches_any(name, exclude_patterns):
        return False
    return True


def format_size(size: int) -> str:
    if size < 1024:
        return f"{size}B"
    units: List[str] = ["KB", "MB", "GB", "TB", "PB"]
    for unit in units:
        size = int(size/1024)
        if size < 1024:
            if size.is_integer():
                return f"{int(size)}{unit}"
            return f"{size:.1f}{unit}"
    return f"{size:.1f}PB"


def get_tree(path: str, prefix: str = "",
             show_hidden: bool = False,
             max_depth: Optional[int] = None,
             current_depth: int = 0,
             dir_only: bool = False,
             file_only: bool = False,
             exclude_patterns: Optional[List[re.Pattern[Any]]] = None,
             include_patterns: Optional[List[re.Pattern[Any]]] = None
) -> Generator[Tuple[str, str, bool],None,None]:
    """生成器：产出 (行字符串, 是否为目录) 用于显示，同时累加统计信息"""
    if max_depth is not None and current_depth >= max_depth:
        return

    try:
        items = sorted(os.listdir(path))
    except PermissionError:
        yield (prefix + "[权限不足]", "error", False)
        return
    except FileNotFoundError:
        yield (prefix + "[目录不存在]", "error", False)
        return

    if not show_hidden:
        items: List[str] = [item for item in items if not item.startswith('.')]

    dirs: List[str] = []
    files: List[str] = []
    for item in items:
        item_path: str = os.path.join(path, item)
        is_dir: bool = os.path.isdir(item_path)
        if filter_item(item, is_dir, exclude_patterns, include_patterns, dir_only, file_only):
            if is_dir:
                dirs.append(item)
            else:
                files.append(item)

    all_items: List[str] = dirs + files
    total: int = len(all_items)

    for i, item in enumerate(all_items):
        is_last = (i == total - 1)
        item_path = os.path.join(path, item)
        is_dir = os.path.isdir(item_path)

        connector = "└── " if is_last else "├── "
        new_prefix = prefix + ("    " if is_last else "│   ")

        size_str = ""
        if not is_dir:
            try:
                size = os.path.getsize(item_path)
                size_str = f" ({format_size(size)})"
            except:
                pass

        display_name = item + ("/" if is_dir else "")
        line = prefix + connector + display_name + size_str
        yield (line, "dir" if is_dir else "file", is_dir)

        if is_dir:
            yield from get_tree(
                item_path, new_prefix, show_hidden, max_depth,
                current_depth + 1, dir_only, file_only,
                exclude_patterns, include_patterns
            )


def count_items(path: str, show_hidden: bool, max_depth: Optional[int],
                current_depth: int, dir_only: bool, file_only: bool,
                exclude_patterns: Optional[List[re.Pattern[Any]]],
                include_patterns: Optional[List[re.Pattern[Any]]]) -> Tuple[int, int]:
    """统计目录和文件数量（应用相同过滤规则）"""
    if max_depth is not None and current_depth >= max_depth:
        return 0, 0
    try:
        items: List[str] = os.listdir(path)
    except:
        return 0, 0
    if not show_hidden:
        items = [item for item in items if not item.startswith('.')]
    dir_count = 0
    file_count = 0
    for item in items:
        item_path: str = os.path.join(path, item)
        is_dir: bool = os.path.isdir(item_path)
        if not filter_item(item, is_dir, exclude_patterns, include_patterns, dir_only, file_only):
            continue
        if is_dir:
            dir_count += 1
            sub_dirs, sub_files = count_items(
                item_path, show_hidden, max_depth, current_depth + 1,
                dir_only, file_only, exclude_patterns, include_patterns
            )
            dir_count += sub_dirs
            file_count += sub_files
        else:
            file_count += 1
    return dir_count, file_count


def main() -> None:
    parser = argparse.ArgumentParser(
        description="目录树状结构展示工具 (支持正则过滤)",
        epilog="示例: %(prog)s . -d 2 --exclude '__pycache__|\\.git' --include '\\.py$'"
    )
    parser.add_argument("path", nargs="?", default=".",
                        help="要展示的目录路径 (默认: 当前目录)")
    parser.add_argument("-a", "--all", action="store_true",
                        help="显示隐藏文件")
    parser.add_argument("-d", "--depth", type=int, default=None,
                        help="最大显示深度")
    parser.add_argument("--dir-only", action="store_true",
                        help="只显示目录")
    parser.add_argument("--file-only", action="store_true",
                        help="只显示文件")
    parser.add_argument("--exclude", nargs="+",
                        help="排除匹配正则表达式的文件/目录 (不区分大小写)")
    parser.add_argument("--include", nargs="+",
                        help="只显示匹配正则表达式的文件/目录 (不区分大小写)")
    parser.add_argument("--no-size", action="store_true",
                        help="不显示文件大小")
    parser.add_argument("--no-summary", action="store_true",
                        help="不显示统计摘要")

    args = parser.parse_args()

    target_path = os.path.abspath(args.path)
    if not os.path.exists(target_path):
        print(f"错误: 路径不存在: {target_path}", file=sys.stderr)
        sys.exit(1)
    if not os.path.isdir(target_path):
        print(f"错误: 不是目录: {target_path}", file=sys.stderr)
        sys.exit(1)

    exclude_patterns: List[re.Pattern[Any]] | None = compile_patterns(args.exclude)
    include_patterns: List[re.Pattern[Any]] | None = compile_patterns(args.include)

    root_name = os.path.basename(target_path) or target_path
    print(f"{root_name}/")

    dir_cnt = 0
    file_cnt = 0
    for line, _, is_dir in get_tree(
        target_path,
        show_hidden=args.all,
        max_depth=args.depth,
        dir_only=args.dir_only,
        file_only=args.file_only,
        exclude_patterns=exclude_patterns,
        include_patterns=include_patterns
    ):
        if args.no_size and " (" in line:
            # 安全移除大小部分：仅在最后一个空格后包含括号时处理
            line = line.rsplit(" (", 1)[0]
        print(line)
        if is_dir:
            dir_cnt += 1
        else:
            file_cnt += 1

    if not args.no_summary:
        # 注意：由于 get_tree 已应用过滤，统计可直接使用累加值，但根目录本身未计入，故无需额外操作。
        # 如果想包括更深层的统计（例如被过滤掉的子目录），需调用 count_items。
        # 为保持一致性，我们基于显示结果累加即可。
        print(f"{dir_cnt} 个目录, {file_cnt} 个文件")


if __name__ == "__main__":
    main()