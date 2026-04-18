#!/usr/bin/env python3
"""
文档生成工具

为Python代码自动生成或更新文档字符串。
"""

import ast
import os
import argparse
import json
from pathlib import Path
from typing import Dict, List, Any, Optional


class DocstringVisitor(ast.NodeVisitor):
    """AST访问器，用于收集缺失文档字符串的节点，并正确识别类方法"""
    def __init__(self):
        self.missing_modules = []
        self.missing_classes = []
        self.missing_functions = []
        self.current_class = None   # 当前正在访问的类名

    def visit_Module(self, node):
        if not ast.get_docstring(node):
            self.missing_modules.append({
                "name": "module",
                "line": 1,
                "docstring": '"""\n    模块文档字符串\n\n    描述模块的功能和用途\n"""'
            })
        self.generic_visit(node)

    def visit_ClassDef(self, node):
        if not ast.get_docstring(node):
            self.missing_classes.append({
                "name": node.name,
                "line": node.lineno,
                "docstring": self._generate_class_docstring(node)
            })
        # 进入类上下文
        old_class = self.current_class
        self.current_class = node.name
        self.generic_visit(node)
        self.current_class = old_class

    def visit_FunctionDef(self, node):
        # 跳过类内部的方法？不，方法也应当有文档，但我们可以区分统计
        # 这里仍然收集函数（包括方法），但用 is_method 标记
        is_method = self.current_class is not None
        if not ast.get_docstring(node):
            entry = {
                "name": node.name,
                "line": node.lineno,
                "docstring": self._generate_function_docstring(node),
                "is_method": is_method
            }
            self.missing_functions.append(entry)
        self.generic_visit(node)

    def _generate_class_docstring(self, class_node: ast.ClassDef) -> str:
        """为类生成文档字符串（标准格式）"""
        return f'"""\n{class_node.name}类\n\n类描述\n"""'

    def _generate_function_docstring(self, func_node: ast.FunctionDef) -> str:
        """为函数/方法生成文档字符串（标准格式）"""
        lines = ['"""']
        lines.append(f"{func_node.name}函数")
        lines.append("")

        # 参数
        args = func_node.args
        if args.args or args.vararg or args.kwarg:
            lines.append("Args:")
            # 位置参数
            for arg in args.args:
                lines.append(f"    {arg.arg}: 参数描述")
            if args.vararg:
                lines.append(f"    *{args.vararg.arg}: 可变位置参数")
            if args.kwarg:
                lines.append(f"    **{args.kwarg.arg}: 可变关键字参数")
            lines.append("")

        # 返回值
        if func_node.returns:
            lines.append("Returns:")
            lines.append("    返回值描述")
            lines.append("")

        lines.append('"""')
        return "\n".join(lines)


def analyze_file_for_missing_docs(file_path: Path) -> Dict[str, Any]:
    """分析文件中缺失的文档字符串"""
    # 读取文件内容（尝试多种编码）
    content = None
    for encoding in ('utf-8', 'gbk'):
        try:
            with open(file_path, "r", encoding=encoding) as f:
                content = f.read()
            break
        except UnicodeDecodeError:
            continue
    if content is None:
        return {"error": f"无法读取文件（编码不支持）: {file_path}"}

    # 解析AST
    try:
        tree = ast.parse(content)
    except SyntaxError as e:
        return {"error": f"语法错误: {e}"}

    # 使用访问器收集缺失项
    visitor = DocstringVisitor()
    visitor.visit(tree)

    return {
        "file": str(file_path),
        "modules": visitor.missing_modules,
        "classes": visitor.missing_classes,
        "functions": visitor.missing_functions
    }


def generate_documentation_report(directory: Path, recursive: bool = True) -> Dict[str, Any]:
    """生成文档缺失报告"""
    results = {
        "directory": str(directory),
        "files_analyzed": 0,
        "missing_docs": {
            "modules": 0,
            "classes": 0,
            "functions": 0,
            "total": 0
        },
        "files": []
    }

    if recursive:
        file_iter = directory.rglob("*.py")
    else:
        file_iter = directory.glob("*.py")

    for py_file in file_iter:
        if "__pycache__" in str(py_file):
            continue

        analysis = analyze_file_for_missing_docs(py_file)
        if "error" not in analysis:
            results["files"].append(analysis)
            results["files_analyzed"] += 1

            # 更新统计
            results["missing_docs"]["modules"] += len(analysis["modules"])
            results["missing_docs"]["classes"] += len(analysis["classes"])
            results["missing_docs"]["functions"] += len(analysis["functions"])
            results["missing_docs"]["total"] += (
                len(analysis["modules"]) + len(analysis["classes"]) + len(analysis["functions"])
            )

    return results


def main():
    parser = argparse.ArgumentParser(description="分析并生成Python文档字符串")
    parser.add_argument("path", help="要分析的目录或文件路径")
    parser.add_argument("--recursive", "-r", action="store_true", help="递归分析子目录")
    parser.add_argument("--report", action="store_true", help="生成报告而不修改文件")
    parser.add_argument("--generate", "-g", action="store_true", help="生成缺失的文档字符串（实验性）")
    parser.add_argument("--output", "-o", help="输出报告文件路径")

    args = parser.parse_args()

    target_path = Path(args.path)

    if not target_path.exists():
        print(f"错误: 路径不存在: {target_path}")
        return 1

    if target_path.is_file():
        # 分析单个文件
        analysis = analyze_file_for_missing_docs(target_path)
        if "error" in analysis:
            print(f"错误: {analysis['error']}")
            return 1

        results = {
            "files_analyzed": 1,
            "missing_docs": {
                "modules": len(analysis["modules"]),
                "classes": len(analysis["classes"]),
                "functions": len(analysis["functions"]),
                "total": len(analysis["modules"]) + len(analysis["classes"]) + len(analysis["functions"])
            },
            "files": [analysis]
        }
    else:
        # 分析目录
        results = generate_documentation_report(target_path, args.recursive)

    # 输出报告
    print(f"文档分析报告")
    print(f"=" * 50)
    print(f"分析路径: {target_path}")
    print(f"分析文件数: {results['files_analyzed']}")
    print(f"缺失文档统计:")
    print(f"  模块文档: {results['missing_docs']['modules']}")
    print(f"  类文档: {results['missing_docs']['classes']}")
    print(f"  函数文档: {results['missing_docs']['functions']}")
    print(f"  总计: {results['missing_docs']['total']}")

    # 显示有缺失的文件
    files_with_missing = [f for f in results["files"] if
                         len(f.get("modules", [])) > 0 or
                         len(f.get("classes", [])) > 0 or
                         len(f.get("functions", [])) > 0]

    if files_with_missing:
        print(f"有缺失文档的文件:")
        for file_info in files_with_missing[:10]:
            missing_count = len(file_info.get("modules", [])) + len(file_info.get("classes", [])) + len(file_info.get("functions", []))
            print(f"  {file_info['file']}: {missing_count}处缺失")
        if len(files_with_missing) > 10:
            print(f"  ... 还有{len(files_with_missing) - 10}个文件")

    # 如果指定了生成文档字符串
    if args.generate:
        print(f"注意: 自动生成文档字符串功能是实验性的")
        print(f"建议手动编写有意义的文档字符串")

    # 输出到文件
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        print(f"报告已保存到: {args.output}")

    return 0


if __name__ == "__main__":
    exit(main())