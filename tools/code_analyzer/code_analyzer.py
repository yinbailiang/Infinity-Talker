#!/usr/bin/env python3
"""
代码分析工具

分析Python代码的质量问题，包括函数长度、类长度、文档缺失等。
"""

import ast
import json
import os
import sys
from pathlib import Path
from typing import Dict, List, Any
import argparse


def analyze_python_file(file_path: Path) -> Dict[str, Any]:
    """分析单个Python文件"""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
    except UnicodeDecodeError:
        try:
            with open(file_path, "r", encoding="gbk") as f:
                content = f.read()
        except Exception as e:
            return {"file": str(file_path), "error": f"无法读取文件: {e}", "total_issues": 0}
    
    issues = {
        "long_functions": [],      # 函数过长（>50行）
        "long_classes": [],        # 类过长（>200行）
        "missing_docstrings": [],  # 缺少文档字符串
        "syntax_error": None,
    }
    
    try:
        tree = ast.parse(content)
        
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                # 检查函数长度（兼容无 end_lineno 的旧版Python）
                if node.end_lineno is not None:
                    func_lines = node.end_lineno - node.lineno + 1
                else:
                    func_lines = 0  # 无法精确计算，跳过
                if func_lines > 50:
                    issues["long_functions"].append({
                        "name": node.name,
                        "lines": func_lines,
                        "line": node.lineno
                    })
                
                # 检查文档字符串
                if not ast.get_docstring(node):
                    issues["missing_docstrings"].append({
                        "type": "function",
                        "name": node.name,
                        "line": node.lineno
                    })
                
            elif isinstance(node, ast.ClassDef):
                # 检查类长度
                if node.end_lineno is not None:
                    class_lines = node.end_lineno - node.lineno + 1
                else:
                    class_lines = 0
                if class_lines > 200:
                    issues["long_classes"].append({
                        "name": node.name,
                        "lines": class_lines,
                        "line": node.lineno
                    })
                
                # 检查类文档字符串
                if not ast.get_docstring(node):
                    issues["missing_docstrings"].append({
                        "type": "class",
                        "name": node.name,
                        "line": node.lineno
                    })
    
    except SyntaxError as e:
        issues["syntax_error"] = str(e)
    
    total = sum(len(v) for v in issues.values() if isinstance(v, list))
    return {
        "file": str(file_path),
        "issues": issues,
        "total_issues": total,
        "error": issues.get("syntax_error")  # 若有语法错误则记录
    }


def analyze_directory(directory: Path, recursive: bool = True) -> Dict[str, Any]:
    """分析目录下的所有Python文件"""
    results = {
        "directory": str(directory),
        "files_analyzed": 0,
        "total_issues": 0,
        "files": [],
        "summary": {
            "long_functions": 0,
            "long_classes": 0,
            "missing_docstrings": 0
        }
    }
    
    if recursive:
        file_iter = directory.rglob("*.py")
    else:
        file_iter = directory.glob("*.py")
    
    for py_file in file_iter:
        if "__pycache__" in str(py_file):
            continue
        
        analysis = analyze_python_file(py_file)
        results["files"].append(analysis)
        results["files_analyzed"] += 1
        results["total_issues"] += analysis.get("total_issues", 0)
        
        # 更新摘要（跳过错误文件）
        if "issues" in analysis:
            issues = analysis["issues"]
            results["summary"]["long_functions"] += len(issues.get("long_functions", []))
            results["summary"]["long_classes"] += len(issues.get("long_classes", []))
            results["summary"]["missing_docstrings"] += len(issues.get("missing_docstrings", []))
    
    return results


def main():
    parser = argparse.ArgumentParser(description="分析Python代码质量")
    parser.add_argument("path", help="要分析的目录或文件路径")
    parser.add_argument("--recursive", "-r", action="store_true", help="递归分析子目录")
    parser.add_argument("--output", "-o", help="输出JSON文件路径")
    parser.add_argument("--format", "-f", choices=["json", "text"], default="text", help="输出格式")
    
    args = parser.parse_args()
    
    target_path = Path(args.path)
    
    if not target_path.exists():
        print(f"错误: 路径不存在: {target_path}")
        sys.exit(1)
    
    # 统一生成分析结果结构（包含 summary 和 files）
    if target_path.is_file():
        file_result = analyze_python_file(target_path)
        # 构建与目录分析一致的结构
        results = {
            "files_analyzed": 1,
            "total_issues": file_result.get("total_issues", 0),
            "files": [file_result],
            "summary": {
                "long_functions": len(file_result.get("issues", {}).get("long_functions", [])),
                "long_classes": len(file_result.get("issues", {}).get("long_classes", [])),
                "missing_docstrings": len(file_result.get("issues", {}).get("missing_docstrings", []))
            }
        }
    else:
        results = analyze_directory(target_path, args.recursive)
    
    # 输出结果
    if args.format == "json" or args.output:
        output_data = {
            "summary": results["summary"],
            "files_analyzed": results["files_analyzed"],
            "total_issues": results["total_issues"],
            "files": results["files"]
        }
        
        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump(output_data, f, indent=2, ensure_ascii=False)
            print(f"分析结果已保存到: {args.output}")
        else:
            print(json.dumps(output_data, indent=2, ensure_ascii=False))
    else:
        # 文本格式输出
        print("代码分析报告")
        print("=" * 50)
        print(f"分析路径: {target_path}")
        print(f"分析文件数: {results['files_analyzed']}")
        print(f"总问题数: {results['total_issues']}")
        print("问题摘要:")
        print(f"  过长函数(>50行): {results['summary']['long_functions']}")
        print(f"  过长类(>200行): {results['summary']['long_classes']}")
        print(f"  缺少文档字符串: {results['summary']['missing_docstrings']}")
        
        # 显示有问题的文件（排除错误文件）
        problematic_files = [f for f in results["files"] if f.get("total_issues", 0) > 0]
        if problematic_files:
            print("有问题的文件:")
            for file_info in problematic_files[:10]:
                print(f"  {file_info['file']}: {file_info['total_issues']}个问题")
            if len(problematic_files) > 10:
                print(f"  ... 还有{len(problematic_files) - 10}个文件")
        
        # 显示解析失败的文件
        error_files = [f for f in results["files"] if f["error"] is not None]
        if error_files:
            print("\n无法分析的文件:")
            for err_file in error_files:
                print(f"  {err_file['file']}: {err_file['error']}")


if __name__ == "__main__":
    main()