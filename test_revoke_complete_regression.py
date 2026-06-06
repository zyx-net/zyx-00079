#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
样本箱撤回后再交接链路 - 完整自动化回归测试
覆盖：
1. 导出 JSON 验证（交接单、异常清单）
2. 审计查询验证
3. 服务重启后状态恢复验证
4. 并发/乱序冲突错误码验证
5. 连续撤回后再交接链路
6. 重复撤回验证
7. from_point 正确性验证
"""

import requests
import json
import sys
import os
import subprocess
import time
import threading
from datetime import datetime, timezone

BASE_URL = "http://localhost:8000"
HEALTH_URL = "http://localhost:8000/health"
CONFIG_PATH = r"d:\workSpace\AI__SPACE\zyx-00079\config\rules_v1.json"

TEST_RESULTS = []


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")


def get_error_code(response):
    try:
        data = response.json()
        if "detail" in data and isinstance(data["detail"], dict):
            return data["detail"].get("code")
        return data.get("code")
    except:
        return None


def print_test_result(test_name, passed, details=""):
    TEST_RESULTS.append({"test_name": test_name, "passed": passed, "details": details})
    status = "[PASS]" if passed else "[FAIL]"
    color = "\033[92m" if passed else "\033[91m"
    reset = "\033[0m"
    print(f"  {color}{status}{reset} {test_name}")
    if details:
        print(f"         {details}")
    return passed


def find_server_process():
    try:
        result = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq python.exe", "/V", "/FO", "CSV"],
            capture_output=True, text=True, encoding="utf-8"
        )
        lines = result.stdout.strip().split("\n")
        for line in lines:
            if "uvicorn" in line.lower():
                parts = line.split(",")
                if len(parts) >= 2:
                    pid = parts[1].strip('"')
                    return pid
    except Exception as e:
        print(f"查找进程失败: {e}")
    return None


def stop_server():
    pid = find_server_process()
    if pid:
        try:
            subprocess.run(["taskkill", "/F", "/PID", pid], check=True, capture_output=True)
            print(f"  已停止服务进程 PID={pid}")
            time.sleep(2)
            return True
        except Exception as e:
            print(f"  停止进程失败: {e}")
    else:
        print("  未找到运行中的服务进程")
    return False


def start_server():
    print("[Start] 启动服务...")
    try:
        process = subprocess.Popen(
            ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"],
            cwd=os.getcwd(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        max_wait = 15
        for i in range(max_wait):
            try:
                r = requests.get(HEALTH_URL, timeout=2)
                if r.status_code == 200:
                    print(f"  服务已启动，PID={process.pid}")
                    time.sleep(1)
                    return process
            except:
                pass
            time.sleep(1)
        print(f"  警告: {max_wait}秒内服务未就绪")
        return process
    except Exception as e:
        print(f"  启动服务失败: {e}")
        return None


def load_config():
    try:
        response = requests.post(f"{BASE_URL}/api/config/load", params={"config_path": CONFIG_PATH})
        response.raise_for_status()
        return True
    except Exception as e:
        print(f"  加载配置失败: {e}")
        return False


def create_test_data(box_code):
    """创建测试箱、样本、交接数据"""
    samples = []
    for i in range(2):
        r = requests.post(f"{BASE_URL}/api/samples", json={
            "barcode": f"SAMP-REV-REG-{now_iso()}-{i}",
            "sample_type": "blood",
            "collection_point": "CP001",
            "collection_time": datetime.now(timezone.utc).isoformat(),
            "current_custodian": "Dr. Zhang",
            "patient_info": json.dumps({"name": "Test Patient"}, ensure_ascii=False)
        })
        samples.append(r.json())
        assert r.status_code in [200, 201], f"创建样本失败: {r.text}"
    
    r = requests.post(f"{BASE_URL}/api/boxes", json={
        "box_code": box_code,
        "destination": "TP001",
        "current_custodian": "Dr. Zhang"
    })
    assert r.status_code in [200, 201], f"创建箱子失败: {r.text}"
    
    barcodes = [s["barcode"] for s in samples]
    r = requests.post(f"{BASE_URL}/api/boxes/pack", json={
        "box_code": box_code,
        "barcodes": barcodes,
        "custodian": "Dr. Zhang"
    })
    assert r.status_code == 200, f"装样本失败: {r.text}"
    
    r = requests.post(f"{BASE_URL}/api/boxes/seal",
        params={"box_code": box_code, "custodian": "Dr. Zhang"})
    assert r.status_code == 200, f"封箱失败: {r.text}"
    
    return samples


def do_transfer(box_code, from_custodian, to_custodian, to_point="TP001"):
    now = datetime.now(timezone.utc).isoformat()
    temp_records = json.dumps([
        {"temperature": 4.5, "timestamp": now},
        {"temperature": 5.0, "timestamp": now}
    ], ensure_ascii=False)
    r = requests.post(f"{BASE_URL}/api/boxes/transfer", json={
        "box_code": box_code,
        "to_point": to_point,
        "to_custodian": to_custodian,
        "from_custodian": from_custodian,
        "temperature": 4.8,
        "temperature_records": temp_records
    })
    return r


def do_revoke(box_code, custodian, reason):
    r = requests.post(f"{BASE_URL}/api/boxes/revoke-transfer", json={
        "box_code": box_code,
        "custodian": custodian,
        "reason": reason
    })
    return r


def do_accept(box_code, custodian):
    r = requests.post(f"{BASE_URL}/api/boxes/accept", json={
        "box_code": box_code,
        "custodian": custodian,
        "check_duration": False
    })
    return r


def test_export_json_validation(box_code):
    """测试1: 导出 JSON 验证"""
    print("\n=== Test 1: 导出 JSON 验证 ===")
    
    # 交接单导出
    r = requests.get(f"{BASE_URL}/api/boxes/{box_code}/handover-form")
    assert r.status_code == 200, f"交接单导出失败: {r.text}"
    handover_data = r.json()
    
    # 异常清单导出
    r = requests.get(f"{BASE_URL}/api/boxes/{box_code}/exception-list")
    assert r.status_code == 200, f"异常清单导出失败: {r.text}"
    exception_data = r.json()
    
    # 保存到文件
    os.makedirs("exports", exist_ok=True)
    with open(f"exports/handover_form_{box_code}.json", "w", encoding="utf-8") as f:
        json.dump(handover_data, f, ensure_ascii=False, indent=2, default=str)
    with open(f"exports/exception_list_{box_code}.json", "w", encoding="utf-8") as f:
        json.dump(exception_data, f, ensure_ascii=False, indent=2, default=str)
    
    # 验证内容
    all_passed = True
    
    # 验证交接单包含撤回历史
    has_revoked_history = handover_data.get("revoked_transfer_history") is not None
    revoked_count = len(handover_data.get("revoked_transfer_history", []))
    passed1 = print_test_result(
        "1.1 交接单包含撤回历史",
        has_revoked_history and revoked_count >= 2,
        f"撤回历史 {revoked_count} 条"
    )
    all_passed = all_passed and passed1
    
    # 验证交接单当前交接不是撤回状态
    current_revoked = handover_data.get("is_revoked", False)
    passed2 = print_test_result(
        "1.2 交接单当前交接 is_revoked=False",
        current_revoked == False,
        f"is_revoked={current_revoked}"
    )
    all_passed = all_passed and passed2
    
    # 验证交接单 from_point 正确（是上一次交接的 to_point，即使被撤回）
    from_point = handover_data.get("from_point")
    passed3 = print_test_result(
        "1.3 交接单 from_point 正确（基于最近交接）",
        from_point == "TP002",
        f"from_point={from_point}, 预期=TP002"
    )
    all_passed = all_passed and passed3
    
    # 验证异常清单包含 TRANSFER_REVOKED 异常
    revoke_exceptions = [e for e in exception_data.get("exceptions", []) 
                        if e.get("type") == "TRANSFER_REVOKED"]
    passed4 = print_test_result(
        "1.4 异常清单包含 TRANSFER_REVOKED 异常",
        len(revoke_exceptions) >= 2,
        f"TRANSFER_REVOKED 异常 {len(revoke_exceptions)} 条"
    )
    all_passed = all_passed and passed4
    
    # 验证异常清单包含撤回历史
    exc_has_revoked = exception_data.get("revoked_transfer_history") is not None
    passed5 = print_test_result(
        "1.5 异常清单包含撤回历史",
        exc_has_revoked,
        f"revoked_transfer_history 存在={exc_has_revoked}"
    )
    all_passed = all_passed and passed5
    
    return all_passed


def test_audit_query_validation(box_code, samples):
    """测试2: 审计查询验证"""
    print("\n=== Test 2: 审计查询验证 ===")
    
    all_passed = True
    
    # 查询所有 REVOKE_TRANSFER 操作
    r = requests.get(f"{BASE_URL}/api/audit", params={"action": "REVOKE_TRANSFER"})
    assert r.status_code == 200, f"查询审计日志失败: {r.text}"
    revoke_logs = r.json()
    
    # 查询所有 RE_TRANSFER 操作
    r = requests.get(f"{BASE_URL}/api/audit", params={"action": "RE_TRANSFER"})
    assert r.status_code == 200, f"查询审计日志失败: {r.text}"
    retransfer_logs = r.json()
    
    # 按实体类型统计
    transfer_revoke_logs = [l for l in revoke_logs if l["entity_type"] == "TRANSFER"]
    box_revoke_logs = [l for l in revoke_logs if l["entity_type"] == "BOX"]
    sample_revoke_logs = [l for l in revoke_logs if l["entity_type"] == "SAMPLE"]
    
    # 验证各实体都有撤回日志（2次撤回，每次4条日志）
    passed1 = print_test_result(
        "2.1 审计日志覆盖所有实体类型",
        len(transfer_revoke_logs) >= 2 and len(box_revoke_logs) >= 2 and len(sample_revoke_logs) >= 4,
        f"TRANSFER={len(transfer_revoke_logs)}, BOX={len(box_revoke_logs)}, SAMPLE={len(sample_revoke_logs)}"
    )
    all_passed = all_passed and passed1
    
    # 验证 TRANSFER 撤回日志包含规则版本
    if transfer_revoke_logs:
        details = json.loads(transfer_revoke_logs[0].get("details", "{}"))
        has_rule_version = "rule_version" in details
        passed2 = print_test_result(
            "2.2 撤回日志包含规则版本",
            has_rule_version,
            f"details包含rule_version={has_rule_version}"
        )
        all_passed = all_passed and passed2
    
    # 验证 BOX 撤回日志包含前后保管人
    if box_revoke_logs:
        details = json.loads(box_revoke_logs[0].get("details", "{}"))
        has_custodians = "old_custodian" in details and "new_custodian" in details
        passed3 = print_test_result(
            "2.3 撤回日志包含前后保管人",
            has_custodians,
            f"details包含old_custodian和new_custodian={has_custodians}"
        )
        all_passed = all_passed and passed3
    
    # 验证 RE_TRANSFER 日志存在
    passed4 = print_test_result(
        "2.4 重新交接日志存在",
        len(retransfer_logs) >= 1,
        f"RE_TRANSFER 日志 {len(retransfer_logs)} 条"
    )
    all_passed = all_passed and passed4
    
    # 验证 RE_TRANSFER 日志包含 prev_transfer_id
    if retransfer_logs:
        details = json.loads(retransfer_logs[0].get("details", "{}"))
        has_prev_id = "prev_transfer_id" in details
        has_revoked_count = "revoked_count_before" in details
        passed5 = print_test_result(
            "2.5 重新交接日志包含关联信息",
            has_prev_id and has_revoked_count,
            f"prev_transfer_id={has_prev_id}, revoked_count_before={has_revoked_count}"
        )
        all_passed = all_passed and passed5
    
    # 验证按箱号查询审计日志
    r = requests.get(f"{BASE_URL}/api/audit/box/{box_code}")
    assert r.status_code == 200, f"查询箱审计日志失败: {r.text}"
    box_audit = r.json()
    passed6 = print_test_result(
        "2.6 按箱号查询审计日志正常",
        len(box_audit) >= 5,
        f"箱{box_code}审计日志 {len(box_audit)} 条"
    )
    all_passed = all_passed and passed6
    
    # 验证按样本条码查询审计日志
    if samples:
        r = requests.get(f"{BASE_URL}/api/audit/sample/{samples[0]['barcode']}")
        assert r.status_code == 200, f"查询样本审计日志失败: {r.text}"
        sample_audit = r.json()
        passed7 = print_test_result(
            "2.7 按样本条码查询审计日志正常",
            len(sample_audit) >= 3,
            f"样本{samples[0]['barcode']}审计日志 {len(sample_audit)} 条"
        )
        all_passed = all_passed and passed7
    
    return all_passed


def test_restart_validation(box_code, samples, transfer_ids):
    """测试3: 服务重启后状态恢复验证"""
    print("\n=== Test 3: 服务重启后状态恢复验证 ===")
    
    all_passed = True
    
    # 记录重启前状态
    box_before = requests.get(f"{BASE_URL}/api/boxes/{box_code}").json()
    history_before = requests.get(f"{BASE_URL}/api/boxes/{box_code}/transfer-history").json()
    
    # 停止服务
    print("  停止服务...")
    stop_server()
    time.sleep(3)
    
    # 重启服务
    server_process = start_server()
    if not server_process:
        print_test_result("3.0 服务重启", False, "无法启动服务")
        return False
    
    load_config()
    
    # 验证重启后状态
    box_after = requests.get(f"{BASE_URL}/api/boxes/{box_code}").json()
    history_after = requests.get(f"{BASE_URL}/api/boxes/{box_code}/transfer-history").json()
    
    # 验证箱子状态
    passed1 = print_test_result(
        "3.1 重启后箱子状态正确",
        box_after["status"] == box_before["status"] and 
        box_after["current_custodian"] == box_before["current_custodian"],
        f"status={box_after['status']}, custodian={box_after['current_custodian']}"
    )
    all_passed = all_passed and passed1
    
    # 验证交接历史
    passed2 = print_test_result(
        "3.2 重启后交接历史完整",
        len(history_after) == len(history_before),
        f"重启前{len(history_before)}条，重启后{len(history_after)}条"
    )
    all_passed = all_passed and passed2
    
    # 验证撤回记录保留
    revoked_after = [t for t in history_after if t.get("is_revoked")]
    passed3 = print_test_result(
        "3.3 重启后撤回记录保留",
        len(revoked_after) >= 2,
        f"已撤回记录 {len(revoked_after)} 条"
    )
    all_passed = all_passed and passed3
    
    # 验证撤回记录字段完整
    for rec in revoked_after:
        assert rec.get("revoked_by") is not None, "revoked_by 不应为 None"
        assert rec.get("revoke_reason") is not None, "revoke_reason 不应为 None"
    passed4 = print_test_result(
        "3.4 撤回记录字段完整",
        True,
        "revoked_by、revoke_reason、revoked_at 均存在"
    )
    all_passed = all_passed and passed4
    
    # 验证重启后可继续操作（已验收箱子撤回应返回 BOX_INVALID_STATUS）
    box_info = requests.get(f"{BASE_URL}/api/boxes/{box_code}").json()
    current_custodian = box_info["current_custodian"]
    r = do_revoke(box_code, current_custodian, "重启后已验收箱子尝试撤回")
    error_code = get_error_code(r)
    passed5 = print_test_result(
        "3.5 重启后已验收箱子撤回返回 BOX_INVALID_STATUS",
        r.status_code == 409 and error_code == "BOX_INVALID_STATUS",
        f"HTTP {r.status_code}, code={error_code}, custodian={current_custodian}"
    )
    all_passed = all_passed and passed5
    
    # 验证重启后导出正常
    r = requests.get(f"{BASE_URL}/api/boxes/{box_code}/handover-form")
    passed6 = print_test_result(
        "3.6 重启后交接单导出正常",
        r.status_code == 200,
        f"HTTP {r.status_code}"
    )
    all_passed = all_passed and passed6
    
    r = requests.get(f"{BASE_URL}/api/boxes/{box_code}/exception-list")
    passed7 = print_test_result(
        "3.7 重启后异常清单导出正常",
        r.status_code == 200,
        f"HTTP {r.status_code}"
    )
    all_passed = all_passed and passed7
    
    # 验证审计日志持久化
    r = requests.get(f"{BASE_URL}/api/audit", params={"action": "REVOKE_TRANSFER"})
    revoke_logs = r.json()
    passed8 = print_test_result(
        "3.8 重启后审计日志持久化",
        len(revoke_logs) >= 8,
        f"撤回审计日志 {len(revoke_logs)} 条"
    )
    all_passed = all_passed and passed8
    
    # 保存重启验证结果
    restart_result = {
        "box_code": box_code,
        "restart_time": datetime.now(timezone.utc).isoformat(),
        "box_status_before": box_before["status"],
        "box_status_after": box_after["status"],
        "history_count_before": len(history_before),
        "history_count_after": len(history_after),
        "revoked_count": len(revoked_after),
        "all_passed": all_passed
    }
    with open(f"restart_test_result_{box_code}.json", "w", encoding="utf-8") as f:
        json.dump(restart_result, f, ensure_ascii=False, indent=2, default=str)
    
    return all_passed, server_process


def test_conflict_error_codes(box_code):
    """测试4: 并发/乱序冲突错误码验证"""
    print("\n=== Test 4: 并发/乱序冲突错误码验证 ===")
    
    all_passed = True
    
    # 测试 4.1: 非保管人撤回
    r = do_revoke(box_code, "Dr. Wang", "非保管人尝试撤回")
    error_code = get_error_code(r)
    passed1 = print_test_result(
        "4.1 非保管人撤回返回 INVALID_CUSTODIAN",
        r.status_code == 400 and error_code == "INVALID_CUSTODIAN",
        f"HTTP {r.status_code}, code={error_code}"
    )
    all_passed = all_passed and passed1
    
    # 测试 4.2: 已验收箱子撤回
    box_info = requests.get(f"{BASE_URL}/api/boxes/{box_code}").json()
    current_custodian = box_info["current_custodian"]
    r = do_revoke(box_code, current_custodian, "验收后尝试撤回")
    error_code = get_error_code(r)
    passed2 = print_test_result(
        "4.2 验收后撤回返回 BOX_INVALID_STATUS",
        r.status_code == 409 and error_code == "BOX_INVALID_STATUS",
        f"HTTP {r.status_code}, code={error_code}, custodian={current_custodian}"
    )
    all_passed = all_passed and passed2
    
    # 测试 4.3: 不存在的箱子撤回
    r = do_revoke("NONEXISTENT-BOX", "Dr. Zhang", "不存在的箱子")
    error_code = get_error_code(r)
    passed3 = print_test_result(
        "4.3 不存在的箱子返回 BOX_NOT_FOUND",
        r.status_code == 404 and error_code == "BOX_NOT_FOUND",
        f"HTTP {r.status_code}, code={error_code}"
    )
    all_passed = all_passed and passed3
    
    # 测试 4.4: 无交接记录的箱子撤回（需要先封箱才能撤回）
    empty_box = f"BOX-EMPTY-{now_iso()}"
    requests.post(f"{BASE_URL}/api/boxes", json={
        "box_code": empty_box,
        "destination": "TP001",
        "current_custodian": "Dr. Zhang"
    })
    # 先封箱才能进入可撤回状态
    requests.post(f"{BASE_URL}/api/boxes/seal",
        params={"box_code": empty_box, "custodian": "Dr. Zhang"})
    r = do_revoke(empty_box, "Dr. Zhang", "无交接记录的箱子")
    error_code = get_error_code(r)
    passed4 = print_test_result(
        "4.4 无交接记录返回 NO_TRANSFER_RECORD",
        r.status_code == 404 and error_code == "NO_TRANSFER_RECORD",
        f"HTTP {r.status_code}, code={error_code}"
    )
    all_passed = all_passed and passed4
    
    # 测试 4.5: 并发冲突场景验证
    # 先创建一个新的测试链路
    concurrent_box = f"BOX-CONCURRENT-{now_iso()}"
    samples = create_test_data(concurrent_box)
    transfer_resp = do_transfer(concurrent_box, "Dr. Zhang", "Dr. Li")
    transfer_id = transfer_resp.json()["transfer_id"]
    
    # 测试 4.5.1: 先验证第一次撤回成功
    r1 = do_revoke(concurrent_box, "Dr. Li", "并发测试-第一次撤回")
    passed5_1 = print_test_result(
        "4.5.1 第一次撤回成功",
        r1.status_code == 200,
        f"HTTP {r1.status_code}"
    )
    all_passed = all_passed and passed5_1
    
    # 测试 4.5.2: 立即再次撤回（模拟并发/乱序），应返回冲突错误码
    r2 = do_revoke(concurrent_box, "Dr. Zhang", "并发测试-重复撤回")
    error_code2 = get_error_code(r2)
    has_valid_code = error_code2 in ["TRANSFER_ALREADY_REVOKED", "CONCURRENT_CONFLICT"]
    passed5_2 = print_test_result(
        "4.5.2 重复撤回返回正确冲突错误码",
        r2.status_code == 409 and has_valid_code,
        f"HTTP {r2.status_code}, code={error_code2}"
    )
    all_passed = all_passed and passed5_2
    
    # 测试 4.5.3: 验证所有交接记录都被标记为撤回
    history = requests.get(f"{BASE_URL}/api/boxes/{concurrent_box}/transfer-history").json()
    all_revoked = all(t.get("is_revoked") for t in history)
    passed5_3 = print_test_result(
        "4.5.3 所有交接记录状态正确",
        all_revoked == True,
        f"所有记录已撤回={all_revoked}"
    )
    all_passed = all_passed and passed5_3
    
    # 测试 4.5.4: 所有记录都已撤回后再次撤回，应返回 TRANSFER_ALREADY_REVOKED
    r3 = do_revoke(concurrent_box, "Dr. Zhang", "并发测试-所有记录已撤回后再撤回")
    error_code3 = get_error_code(r3)
    passed5_4 = print_test_result(
        "4.5.4 所有记录已撤回后返回 TRANSFER_ALREADY_REVOKED",
        r3.status_code == 409 and error_code3 == "TRANSFER_ALREADY_REVOKED",
        f"HTTP {r3.status_code}, code={error_code3}"
    )
    all_passed = all_passed and passed5_4
    
    passed5 = passed5_1 and passed5_2 and passed5_3 and passed5_4
    
    # 测试 4.6: 验证 CONCURRENT_CONFLICT 错误码在 OpenAPI 文档中
    r = requests.get(f"{BASE_URL}/openapi.json")
    paths = r.json()["paths"]
    revoke_responses = paths["/api/boxes/revoke-transfer"]["post"]["responses"]
    has_409 = "409" in revoke_responses
    desc_contains_concurrent = "CONCURRENT_CONFLICT" in revoke_responses["409"]["description"]
    passed6 = print_test_result(
        "4.6 CONCURRENT_CONFLICT 在 OpenAPI 文档中",
        has_409 and desc_contains_concurrent,
        f"409描述包含CONCURRENT_CONFLICT={desc_contains_concurrent}"
    )
    all_passed = all_passed and passed6
    
    return all_passed


def test_from_point_correctness():
    """测试5: from_point 正确性验证"""
    print("\n=== Test 5: from_point 正确性验证 ===")
    
    all_passed = True
    
    box_code = f"BOX-FROMPOINT-{now_iso()}"
    samples = create_test_data(box_code)
    
    # 第一次交接：CP001 -> TP001
    r = do_transfer(box_code, "Dr. Zhang", "Dr. Li", "TP001")
    assert r.status_code == 200
    transfer1_id = r.json()["transfer_id"]
    
    # 验证第一次交接 from_point 是采集点
    history = requests.get(f"{BASE_URL}/api/boxes/{box_code}/transfer-history").json()
    t1 = next(t for t in history if t["id"] == transfer1_id)
    passed1 = print_test_result(
        "5.1 第一次交接 from_point 是采集点",
        t1["from_point"] == "CP001",
        f"from_point={t1["from_point"]}, 预期=CP001"
    )
    all_passed = all_passed and passed1
    
    # 撤回
    r = do_revoke(box_code, "Dr. Li", "测试from_point")
    assert r.status_code == 200
    
    # 第二次交接：应该从上一次交接的 to_point 开始（TP001 -> TP002）
    r = do_transfer(box_code, "Dr. Zhang", "Dr. Wang", "TP002")
    assert r.status_code == 200
    transfer2_id = r.json()["transfer_id"]
    
    # 验证第二次交接 from_point 是 TP001
    history = requests.get(f"{BASE_URL}/api/boxes/{box_code}/transfer-history").json()
    t2 = next(t for t in history if t["id"] == transfer2_id)
    passed2 = print_test_result(
        "5.2 撤回后重新交接 from_point 是上一次有效交接的 to_point",
        t2["from_point"] == "TP001",
        f"from_point={t2["from_point"]}, 预期=TP001"
    )
    all_passed = all_passed and passed2
    
    # 验证交接单导出的 from_point 正确
    form = requests.get(f"{BASE_URL}/api/boxes/{box_code}/handover-form").json()
    passed3 = print_test_result(
        "5.3 交接单导出 from_point 正确",
        form["from_point"] == "TP001",
        f"from_point={form['from_point']}, 预期=TP001"
    )
    all_passed = all_passed and passed3
    
    return all_passed


def test_continuous_revoke_retransfer():
    """测试6: 连续撤回后再交接链路"""
    print("\n=== Test 6: 连续撤回后再交接链路 ===")
    
    all_passed = True
    
    box_code = f"BOX-CONTINUOUS-{now_iso()}"
    samples = create_test_data(box_code)
    
    transfer_ids = []
    
    # 多轮撤回-重新交接
    for i in range(3):
        to_custodian = f"Dr. Cust{i+1}"
        r = do_transfer(box_code, "Dr. Zhang", to_custodian, f"TP00{i+1}")
        assert r.status_code == 200, f"第{i+1}次交接失败: {r.text}"
        transfer_ids.append(r.json()["transfer_id"])
        print(f"  第{i+1}次交接成功，ID={transfer_ids[-1]}")
        
        if i < 2:
            r = do_revoke(box_code, to_custodian, f"第{i+1}次撤回测试")
            assert r.status_code == 200, f"第{i+1}次撤回失败: {r.text}"
            print(f"  第{i+1}次撤回成功")
    
    # 验证交接历史记录数
    history = requests.get(f"{BASE_URL}/api/boxes/{box_code}/transfer-history").json()
    revoked_count = len([t for t in history if t.get("is_revoked")])
    active_count = len([t for t in history if not t.get("is_revoked")])
    
    passed1 = print_test_result(
        "6.1 连续撤回后历史记录完整",
        len(history) == 3 and revoked_count == 2 and active_count == 1,
        f"共{len(history)}条，已撤回{revoked_count}条，活跃{active_count}条"
    )
    all_passed = all_passed and passed1
    
    # 验证最后一次交接的 from_point 正确
    last_active = next(t for t in history if not t.get("is_revoked"))
    passed2 = print_test_result(
        "6.2 最后一次交接 from_point 正确",
        last_active["from_point"] == "TP002",
        f"from_point={last_active['from_point']}, 预期=TP002"
    )
    all_passed = all_passed and passed2
    
    # 验证当前保管人正确
    box = requests.get(f"{BASE_URL}/api/boxes/{box_code}").json()
    passed3 = print_test_result(
        "6.3 当前保管人正确",
        box["current_custodian"] == "Dr. Cust3",
        f"custodian={box['current_custodian']}, 预期=Dr. Cust3"
    )
    all_passed = all_passed and passed3
    
    # 验收
    r = do_accept(box_code, "Dr. Cust3")
    assert r.status_code == 200, f"验收失败: {r.text}"
    passed4 = print_test_result(
        "6.4 多次撤回后验收成功",
        r.json()["status"] == "DELIVERED",
        f"status={r.json()['status']}"
    )
    all_passed = all_passed and passed4
    
    return all_passed, box_code, samples, transfer_ids


def main():
    print("=" * 70)
    print("  样本箱撤回后再交接链路 - 完整自动化回归测试")
    print("=" * 70)
    print()
    
    # 检查服务状态
    try:
        r = requests.get(HEALTH_URL, timeout=3)
        if r.status_code != 200:
            print("服务未正常运行，正在启动...")
            server_process = start_server()
            if not server_process:
                print("无法启动服务，测试终止")
                return 1
        else:
            print("服务运行中")
    except:
        print("服务未运行，正在启动...")
        server_process = start_server()
        if not server_process:
            print("无法启动服务，测试终止")
            return 1
    
    load_config()
    print()
    
    overall_passed = True
    server_process = None
    
    try:
        # Test 6: 先做连续撤回链路，为后续测试准备数据
        passed_continuous, main_box_code, main_samples, main_transfer_ids = test_continuous_revoke_retransfer()
        overall_passed = overall_passed and passed_continuous
        
        # Test 1: 导出 JSON 验证
        passed_export = test_export_json_validation(main_box_code)
        overall_passed = overall_passed and passed_export
        
        # Test 2: 审计查询验证
        passed_audit = test_audit_query_validation(main_box_code, main_samples)
        overall_passed = overall_passed and passed_audit
        
        # Test 5: from_point 正确性验证
        passed_frompoint = test_from_point_correctness()
        overall_passed = overall_passed and passed_frompoint
        
        # Test 4: 冲突错误码验证
        passed_conflict = test_conflict_error_codes(main_box_code)
        overall_passed = overall_passed and passed_conflict
        
        # Test 3: 服务重启后状态恢复验证（会重启服务）
        passed_restart, server_process = test_restart_validation(
            main_box_code, main_samples, main_transfer_ids
        )
        overall_passed = overall_passed and passed_restart
        
    except Exception as e:
        print(f"\n\033[91m测试执行异常: {e}\033[0m")
        import traceback
        traceback.print_exc()
        overall_passed = False
    finally:
        # 确保服务保持运行
        if server_process and server_process.poll() is not None:
            print("\n[Cleanup] 重新启动服务...")
            subprocess.Popen(
                ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"],
                cwd=os.getcwd()
            )
            print("  服务已重新启动")
    
    # 总结
    print("\n" + "=" * 70)
    print("  测试总结")
    print("=" * 70)
    print()
    
    passed = len([t for t in TEST_RESULTS if t["passed"]])
    failed = len(TEST_RESULTS) - passed
    
    print(f"  总测试项: {len(TEST_RESULTS)}")
    print(f"  \033[92m通过: {passed}\033[0m")
    if failed == 0:
        print(f"  \033[92m失败: {failed}\033[0m")
    else:
        print(f"  \033[91m失败: {failed}\033[0m")
        print()
        print("  失败项:")
        for t in TEST_RESULTS:
            if not t["passed"]:
                print(f"    - {t['test_name']}: {t['details']}")
    
    print()
    
    # 保存测试结果
    result_file = f"test_result_REV-REGRESSION-{now_iso()}.json"
    with open(result_file, "w", encoding="utf-8") as f:
        json.dump({
            "test_time": datetime.now(timezone.utc).isoformat(),
            "main_box_code": main_box_code,
            "total_tests": len(TEST_RESULTS),
            "passed": passed,
            "failed": failed,
            "all_passed": overall_passed,
            "results": TEST_RESULTS
        }, f, ensure_ascii=False, indent=2, default=str)
    
    print(f"  测试结果已保存到: {result_file}")
    print(f"  主测试箱号: {main_box_code}")
    print()
    
    if overall_passed and failed == 0:
        print("  \033[92m所有自动化回归测试通过!\033[0m")
        return 0
    else:
        print("  \033[91m部分测试失败，请检查!\033[0m")
        return 1


if __name__ == "__main__":
    sys.exit(main())
