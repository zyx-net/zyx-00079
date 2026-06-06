#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
撤回交接文档对齐 - 完整复现/回归测试
覆盖：重复撤回、已验收后撤回、文档总表包含两项、导出JSON与审计日志口径不受影响
"""

import requests
import json
import subprocess
import os
import sys
import signal
from datetime import datetime, timezone
from pathlib import Path

BASE_URL = "http://localhost:8000"
HEALTH_URL = "http://localhost:8000/health"

def now_iso():
    return datetime.now(timezone.utc).isoformat()

def get_error_code(response):
    try:
        return response.json()["detail"]["code"]
    except:
        return None

def print_test_result(test_name, passed, details=""):
    status = "[PASS]" if passed else "[FAIL]"
    color = "\033[92m" if passed else "\033[91m"
    reset = "\033[0m"
    print(f"  {color}{status}{reset} {test_name}")
    if details:
        print(f"         {details}")
    return passed

def create_test_data(box_code):
    """创建测试数据：样本、箱子、装样、封箱、交接"""
    now = now_iso()
    
    # 创建样本
    samples = []
    for i in range(2):
        r = requests.post(f"{BASE_URL}/api/samples", json={
            "barcode": f"SAMP-ALIGN-{now[:19].replace(':', '')}-{i}",
            "sample_type": "urine",
            "collection_point": "CP001",
            "collection_time": now,
            "current_custodian": "Dr. Zhang",
            "patient_info": json.dumps({"name": "Test Patient"}, ensure_ascii=False)
        })
        samples.append(r.json())
        assert r.status_code in [200, 201], f"创建样本失败: {r.text}"
    
    # 创建箱子
    r = requests.post(f"{BASE_URL}/api/boxes", json={
        "box_code": box_code,
        "destination": "TP001",
        "current_custodian": "Dr. Zhang"
    })
    assert r.status_code in [200, 201], f"创建箱子失败: {r.text}"
    
    # 装样本
    barcodes = [s["barcode"] for s in samples]
    r = requests.post(f"{BASE_URL}/api/boxes/pack", json={
        "box_code": box_code,
        "barcodes": barcodes,
        "custodian": "Dr. Zhang"
    })
    assert r.status_code == 200, f"装样本失败: {r.text}"
    
    # 封箱
    r = requests.post(f"{BASE_URL}/api/boxes/seal",
        params={"box_code": box_code, "custodian": "Dr. Zhang"})
    assert r.status_code == 200, f"封箱失败: {r.text}"
    
    # 交接
    temp_records = json.dumps([
        {"temperature": 4.5, "timestamp": now},
        {"temperature": 5.0, "timestamp": now}
    ], ensure_ascii=False)
    r = requests.post(f"{BASE_URL}/api/boxes/transfer", json={
        "box_code": box_code,
        "to_point": "TP001",
        "to_custodian": "Dr. Li",
        "from_custodian": "Dr. Zhang",
        "temperature": 4.8,
        "temperature_records": temp_records
    })
    assert r.status_code == 200, f"交接失败: {r.text}"
    transfer_id = r.json()["transfer_id"]
    
    return samples, transfer_id

def run_doc_alignment_check():
    """运行文档对齐校验脚本"""
    print("[Setup] 运行文档对齐校验...")
    result = subprocess.run(
        ["python", "test_doc_alignment.py"],
        capture_output=True, text=True, encoding="utf-8"
    )
    # 检查结果文件
    result_file = Path("doc_alignment_result.json")
    if result_file.exists():
        with open(result_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("all_passed", False)
    return False

def test_complete_flow():
    """完整测试流程"""
    print("=" * 70)
    print("  撤回交接文档对齐 - 完整复现/回归测试")
    print("=" * 70)
    print()
    
    box_code = f"BOX-ALIGN-{now_iso()[:19].replace(':', '')}"
    print(f"测试箱号: {box_code}")
    print()
    
    results = []
    all_passed = True
    
    # === Setup: 创建测试数据 ===
    print("[Setup] 创建测试数据...")
    samples, first_transfer_id = create_test_data(box_code)
    print(f"  已创建测试数据，初始交接ID: {first_transfer_id}")
    print()
    
    # === Test 1: 第一次撤回成功 ===
    print("[Test 1] 第一次撤回（应该成功）...")
    try:
        r = requests.post(f"{BASE_URL}/api/boxes/revoke-transfer", json={
            "box_code": box_code,
            "custodian": "Dr. Li",
            "reason": "对齐测试-第一次撤回"
        })
        if r.status_code == 200:
            data = r.json()
            passed = (data["success"] == True and 
                     data["old_box_status"] == "IN_TRANSIT" and
                     data["new_box_status"] == "SEALED")
            results.append(print_test_result("Test 1: 第一次撤回成功", passed,
                f"撤回交接ID: {data['revoked_transfer_id']}"))
        else:
            results.append(print_test_result("Test 1: 第一次撤回成功", False,
                f"HTTP {r.status_code}: {r.text}"))
            all_passed = False
    except Exception as e:
        results.append(print_test_result("Test 1: 第一次撤回成功", False, f"Exception: {e}"))
        all_passed = False
    print()
    
    # === Test 2: 重复撤回（应该返回 409/TRANSFER_ALREADY_REVOKED）===
    print("[Test 2] 重复撤回（应该返回 409/TRANSFER_ALREADY_REVOKED）...")
    try:
        r = requests.post(f"{BASE_URL}/api/boxes/revoke-transfer", json={
            "box_code": box_code,
            "custodian": "Dr. Zhang",
            "reason": "对齐测试-重复撤回"
        })
        error_code = get_error_code(r)
        passed = (r.status_code == 409 and error_code == "TRANSFER_ALREADY_REVOKED")
        results.append(print_test_result("Test 2: 重复撤回返回 409/TRANSFER_ALREADY_REVOKED", passed,
            f"HTTP {r.status_code}, code={error_code}"))
        if not passed:
            all_passed = False
    except Exception as e:
        results.append(print_test_result("Test 2: 重复撤回返回 409/TRANSFER_ALREADY_REVOKED", False,
            f"Exception: {e}"))
        all_passed = False
    print()
    
    # === Test 3: 重新交接并验收 ===
    print("[Test 3] 重新交接并验收...")
    try:
        # 重新交接
        now = now_iso()
        temp_records = json.dumps([
            {"temperature": 4.2, "timestamp": now},
            {"temperature": 4.8, "timestamp": now}
        ], ensure_ascii=False)
        r = requests.post(f"{BASE_URL}/api/boxes/transfer", json={
            "box_code": box_code,
            "to_point": "TP001",
            "to_custodian": "Dr. Li",
            "from_custodian": "Dr. Zhang",
            "temperature": 4.5,
            "temperature_records": temp_records
        })
        assert r.status_code == 200, f"重新交接失败: {r.text}"
        second_transfer_id = r.json()["transfer_id"]
        
        # 验收
        r = requests.post(f"{BASE_URL}/api/boxes/accept", json={
            "box_code": box_code,
            "custodian": "Dr. Li",
            "check_duration": False
        })
        passed = r.status_code == 200 and r.json()["status"] == "DELIVERED"
        results.append(print_test_result("Test 3: 重新交接并验收成功", passed,
            f"状态: {r.json().get('status')}"))
        if not passed:
            all_passed = False
    except Exception as e:
        results.append(print_test_result("Test 3: 重新交接并验收成功", False, f"Exception: {e}"))
        all_passed = False
    print()
    
    # === Test 4: 验收后撤回（应该返回 409/BOX_INVALID_STATUS）===
    print("[Test 4] 验收后撤回（应该返回 409/BOX_INVALID_STATUS）...")
    try:
        r = requests.post(f"{BASE_URL}/api/boxes/revoke-transfer", json={
            "box_code": box_code,
            "custodian": "Dr. Li",
            "reason": "对齐测试-验收后撤回"
        })
        error_code = get_error_code(r)
        passed = (r.status_code == 409 and error_code == "BOX_INVALID_STATUS")
        results.append(print_test_result("Test 4: 验收后撤回返回 409/BOX_INVALID_STATUS", passed,
            f"HTTP {r.status_code}, code={error_code}"))
        if not passed:
            all_passed = False
    except Exception as e:
        results.append(print_test_result("Test 4: 验收后撤回返回 409/BOX_INVALID_STATUS", False,
            f"Exception: {e}"))
        all_passed = False
    print()
    
    # === Test 5: 文档总表包含两项错误码 ===
    print("[Test 5] 文档总表包含两项错误码...")
    try:
        doc_passed = run_doc_alignment_check()
        results.append(print_test_result("Test 5: 文档总表包含两项错误码", doc_passed,
            f"文档对齐校验结果: {'通过' if doc_passed else '失败'}"))
        if not doc_passed:
            all_passed = False
    except Exception as e:
        results.append(print_test_result("Test 5: 文档总表包含两项错误码", False, f"Exception: {e}"))
        all_passed = False
    print()
    
    # === Test 6: 导出 JSON 包含撤回历史 ===
    print("[Test 6] 导出 JSON 包含撤回历史...")
    try:
        r = requests.get(f"{BASE_URL}/api/boxes/{box_code}/handover-form")
        handover_data = r.json()
        r = requests.get(f"{BASE_URL}/api/boxes/{box_code}/exception-list")
        exception_data = r.json()
        
        revoked_history = handover_data.get("revoked_transfer_history", [])
        revoke_exceptions = [e for e in exception_data.get("exceptions", []) if e.get("type") == "TRANSFER_REVOKED"]
        
        # 应该有 1 条撤回历史（第一次撤回的记录）
        passed = (len(revoked_history) >= 1 and len(revoke_exceptions) >= 1)
        results.append(print_test_result("Test 6: 导出 JSON 包含撤回历史", passed,
            f"交接单撤回历史: {len(revoked_history)} 条, 异常清单 TRANSFER_REVOKED: {len(revoke_exceptions)} 条"))
        
        # 验证撤回记录的字段完整性
        for rec in revoked_history:
            assert rec.get("revoked_by") is not None, "缺少 revoked_by"
            assert rec.get("revoke_reason") is not None, "缺少 revoke_reason"
        for rec in revoke_exceptions:
            assert rec.get("type") == "TRANSFER_REVOKED", f"类型错误: {rec.get('type')}"
            assert rec.get("revoked_by") is not None, "缺少 revoked_by"
            assert rec.get("revoke_reason") is not None, "缺少 revoke_reason"
        
        if passed:
            print("         撤回记录字段完整")
        
        # 保存导出文件
        os.makedirs("exports", exist_ok=True)
        with open(f"exports/handover_form_{box_code}.json", "w", encoding="utf-8") as f:
            json.dump(handover_data, f, ensure_ascii=False, indent=2)
        with open(f"exports/exception_list_{box_code}.json", "w", encoding="utf-8") as f:
            json.dump(exception_data, f, ensure_ascii=False, indent=2)
        
        if not passed:
            all_passed = False
    except Exception as e:
        results.append(print_test_result("Test 6: 导出 JSON 包含撤回历史", False, f"Exception: {e}"))
        all_passed = False
    print()
    
    # === Test 7: 审计日志口径一致性 ===
    print("[Test 7] 审计日志口径一致性...")
    try:
        r = requests.get(f"{BASE_URL}/api/audit", params={"action": "REVOKE_TRANSFER"})
        logs = r.json()
        
        # 统计各实体类型的日志
        transfer_logs = [l for l in logs if l["entity_type"] == "TRANSFER"]
        box_logs = [l for l in logs if l["entity_type"] == "BOX"]
        sample_logs = [l for l in logs if l["entity_type"] == "SAMPLE"]
        
        # 我们做了 1 次成功的撤回，应该有 1(TRANSFER) + 1(BOX) + 2(SAMPLE) = 4 条日志
        passed = (len(transfer_logs) >= 1 and len(box_logs) >= 1 and len(sample_logs) >= 2)
        results.append(print_test_result("Test 7: 审计日志覆盖所有实体", passed,
            f"TRANSFER:{len(transfer_logs)}, BOX:{len(box_logs)}, SAMPLE:{len(sample_logs)}"))
        
        # 验证状态变化
        for log in transfer_logs:
            assert log["new_status"] == "REVOKED", f"TRANSFER 日志 new_status 错误: {log['new_status']}"
        for log in box_logs:
            assert log["new_status"] == "SEALED", f"BOX 日志 new_status 错误: {log['new_status']}"
        
        if passed:
            print("         状态变化正确")
        
        if not passed:
            all_passed = False
    except Exception as e:
        results.append(print_test_result("Test 7: 审计日志口径一致性", False, f"Exception: {e}"))
        all_passed = False
    print()
    
    # === Test 8: OpenAPI 文档包含错误码（访问 /docs 验证）===
    print("[Test 8] OpenAPI 文档包含错误码描述...")
    try:
        r = requests.get(f"{BASE_URL}/openapi.json")
        openapi_data = r.json()
        
        # 查找 revoke-transfer 接口的响应描述
        paths = openapi_data.get("paths", {})
        revoke_path = paths.get("/api/boxes/revoke-transfer", {})
        post_op = revoke_path.get("post", {})
        responses = post_op.get("responses", {})
        
        # 检查 409 响应描述是否包含两个关键错误码
        resp_409 = responses.get("409", {})
        desc_409 = resp_409.get("description", "")
        has_transfer_revoked = "TRANSFER_ALREADY_REVOKED" in desc_409
        has_box_invalid = "BOX_INVALID_STATUS" in desc_409
        
        resp_404 = responses.get("404", {})
        desc_404 = resp_404.get("description", "")
        has_no_transfer = "NO_TRANSFER_RECORD" in desc_404
        
        passed = (has_transfer_revoked and has_box_invalid and has_no_transfer)
        results.append(print_test_result("Test 8: OpenAPI 文档包含错误码描述", passed,
            f"409包含TRANSFER_ALREADY_REVOKED: {has_transfer_revoked}, "
            f"409包含BOX_INVALID_STATUS: {has_box_invalid}, "
            f"404包含NO_TRANSFER_RECORD: {has_no_transfer}"))
        
        if not passed:
            all_passed = False
    except Exception as e:
        results.append(print_test_result("Test 8: OpenAPI 文档包含错误码描述", False, f"Exception: {e}"))
        all_passed = False
    print()
    
    # === 总结 ===
    print("=" * 70)
    passed_count = sum(results)
    total_count = len(results)
    print(f"  测试结果: {passed_count}/{total_count} 通过")
    print("=" * 70)
    print()
    print(f"测试箱号: {box_code}")
    print(f"导出文件: exports/handover_form_{box_code}.json")
    print(f"         exports/exception_list_{box_code}.json")
    print()
    
    # 保存测试结果
    with open(f"test_result_{box_code}.json", "w", encoding="utf-8") as f:
        json.dump({
            "box_code": box_code,
            "all_passed": all_passed,
            "passed_count": passed_count,
            "total_count": total_count,
            "tests": {
                "duplicate_revoke": results[1],
                "revoke_after_accept": results[3],
                "doc_summary": results[4],
                "export_json": results[5],
                "audit_log": results[6],
                "openapi": results[7]
            }
        }, f, ensure_ascii=False, indent=2)
    
    return all_passed, box_code

if __name__ == "__main__":
    try:
        # 检查服务是否运行
        try:
            r = requests.get(HEALTH_URL, timeout=3)
            if r.status_code != 200:
                print("服务未正常运行")
                sys.exit(1)
        except:
            print("服务未运行")
            sys.exit(1)
        
        passed, box_code = test_complete_flow()
        sys.exit(0 if passed else 1)
    except Exception as e:
        print(f"\033[91m测试执行失败: {e}\033[0m")
        import traceback
        traceback.print_exc()
        sys.exit(1)
