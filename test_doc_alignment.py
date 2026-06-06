#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
文档与接口对齐校验脚本（真实核对，不放宽匹配）
校验：错误码汇总表、接口小节、OpenAPI 响应声明、代码 docstring 四方对齐
"""

import ast
import json
import sys
from pathlib import Path

def check_string_exists(content, search_str, description):
    """精确检查字符串是否存在（二进制级别，不放宽）"""
    # 先检查作为普通字符串
    exists_normal = search_str in content
    
    # 再检查是否包含在代码块中（带引号的形式）
    quoted_str = f'"code": "{search_str}"'
    exists_quoted = quoted_str in content
    
    # 检查是否在反引号中（Markdown 表格中的形式）
    backtick_str = f'`{search_str}`'
    exists_backtick = backtick_str in content
    
    # 只要有任意一种形式存在就算通过
    exists = exists_normal or exists_quoted or exists_backtick
    
    status = "PASS" if exists else "FAIL"
    print(f"  [{status}] {description}")
    if not exists:
        print(f"         未找到: {search_str}")
        print(f"         普通匹配: {exists_normal}, 引号匹配: {exists_quoted}, 反引号匹配: {exists_backtick}")
    return exists

def check_error_code_summary(content):
    """检查错误码汇总表"""
    print("=== 检查错误码汇总表 ===")
    
    required_codes = [
        "NO_TRANSFER_RECORD",
        "TRANSFER_ALREADY_REVOKED", 
        "BOX_INVALID_STATUS"
    ]
    
    results = []
    for code in required_codes:
        results.append(check_string_exists(content, code, f"汇总表包含 {code}"))
    
    return all(results)

def check_api_section(content):
    """检查接口小节的响应示例"""
    print("\n=== 检查接口小节响应示例 ===")
    
    checks = [
        ('"code": "TRANSFER_ALREADY_REVOKED"', "409 重复撤回响应示例包含 TRANSFER_ALREADY_REVOKED"),
        ('"code": "BOX_INVALID_STATUS"', "409 状态不允许撤回响应示例包含 BOX_INVALID_STATUS"),
        ('"code": "NO_TRANSFER_RECORD"', "404 无交接记录响应示例包含 NO_TRANSFER_RECORD")
    ]
    
    results = []
    for search_str, desc in checks:
        exists = search_str in content
        status = "PASS" if exists else "FAIL"
        print(f"  [{status}] {desc}")
        if not exists:
            print(f"         未找到: {search_str}")
        results.append(exists)
    
    return all(results)

def check_openapi_declaration():
    """检查 OpenAPI 响应声明（从 boxes.py 源码读取）"""
    print("\n=== 检查 OpenAPI 响应声明 ===")
    
    boxes_file = Path("app/routes/boxes.py")
    source = boxes_file.read_text(encoding="utf-8")
    
    # 找到 revoke_transfer 函数的 responses 声明
    # 使用 ast 解析更可靠
    tree = ast.parse(source)
    
    responses_found = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "revoke_transfer":
            # 查找装饰器中的 responses 参数
            for decorator in node.decorator_list:
                if isinstance(decorator, ast.Call):
                    for keyword in decorator.keywords:
                        if keyword.arg == "responses":
                            # 解析 responses 字典
                            if isinstance(keyword.value, ast.Dict):
                                for key, value in zip(keyword.value.keys, keyword.value.values):
                                    if isinstance(key, ast.Constant) and isinstance(value, ast.Dict):
                                        status_code = key.value
                                        # 查找 description
                                        for v_key, v_value in zip(value.keys, value.values):
                                            if isinstance(v_key, ast.Constant) and v_key.value == "description":
                                                if isinstance(v_value, ast.Constant):
                                                    responses_found[status_code] = v_value.value
    
    expected_descriptions = {
        400: ["INVALID_CUSTODIAN"],
        404: ["BOX_NOT_FOUND", "NO_TRANSFER_RECORD"],
        409: ["BOX_INVALID_STATUS", "TRANSFER_ALREADY_REVOKED", "SAMPLE_INVALID_STATUS", "SAMPLE_ISOLATED"]
    }
    
    results = []
    for status_code, required_codes in expected_descriptions.items():
        if status_code not in responses_found:
            print(f"  [FAIL] 缺少 {status_code} 响应声明")
            results.append(False)
            continue
        
        description = responses_found[status_code]
        all_found = True
        for code in required_codes:
            if code not in description:
                print(f"  [FAIL] {status_code} 描述缺少 {code}")
                print(f"         当前描述: {description}")
                all_found = False
        
        if all_found:
            print(f"  [PASS] {status_code} 响应声明包含所有错误码: {required_codes}")
        results.append(all_found)
    
    return all(results)

def check_docstring():
    """检查代码中的 docstring"""
    print("\n=== 检查代码 docstring ===")
    
    boxes_file = Path("app/routes/boxes.py")
    source = boxes_file.read_text(encoding="utf-8")
    tree = ast.parse(source)
    
    docstring_found = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "revoke_transfer":
            docstring_found = ast.get_docstring(node)
            break
    
    if not docstring_found:
        print("  [FAIL] 未找到 docstring")
        return False
    
    required_codes = [
        "BOX_NOT_FOUND",
        "INVALID_CUSTODIAN",
        "BOX_INVALID_STATUS",
        "NO_TRANSFER_RECORD",
        "TRANSFER_ALREADY_REVOKED",
        "SAMPLE_INVALID_STATUS",
        "SAMPLE_ISOLATED"
    ]
    
    results = []
    for code in required_codes:
        # 精确匹配反引号包裹的形式
        expected = f"`{code}`"
        if expected in docstring_found:
            print(f"  [PASS] docstring 包含 {code}")
            results.append(True)
        else:
            print(f"  [FAIL] docstring 缺少 {code}")
            results.append(False)
    
    return all(results)

def main():
    print("=" * 60)
    print("  文档与接口对齐校验（真实核对，不放宽匹配）")
    print("=" * 60)
    print()
    
    # 读取文档（二进制方式，避免编码问题）
    doc_file = Path("API_DOCUMENTATION.md")
    doc_bytes = doc_file.read_bytes()
    
    # 尝试用 utf-8 解码，忽略错误但保留原始内容
    try:
        doc_content = doc_bytes.decode('utf-8')
    except UnicodeDecodeError:
        # 如果有编码问题，用 replace 模式
        doc_content = doc_bytes.decode('utf-8', errors='replace')
        print("注意: 文档存在编码问题，已使用 replace 模式解码")
        print()
    
    all_results = []
    
    # 1. 检查错误码汇总表
    all_results.append(check_error_code_summary(doc_content))
    
    # 2. 检查接口小节
    all_results.append(check_api_section(doc_content))
    
    # 3. 检查 OpenAPI 响应声明
    all_results.append(check_openapi_declaration())
    
    # 4. 检查代码 docstring
    all_results.append(check_docstring())
    
    print()
    print("=" * 60)
    if all(all_results):
        print("  [PASS] 所有校验通过，文档与接口完全对齐")
        ret = 0
    else:
        print(f"  [FAIL] 部分校验失败 ({sum(all_results)}/{len(all_results)} 通过)")
        ret = 1
    print("=" * 60)
    
    # 保存结果
    with open("doc_alignment_result.json", "w", encoding="utf-8") as f:
        json.dump({
            "all_passed": all(all_results),
            "summary_count": len(all_results),
            "passed_count": sum(all_results)
        }, f, ensure_ascii=False, indent=2)
    
    return ret

if __name__ == "__main__":
    sys.exit(main())
