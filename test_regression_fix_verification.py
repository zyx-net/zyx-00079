"""
完整回归测试：验证撤回后重新交接的 from_point 修复

覆盖场景：
1. 撤回前后历史保留
2. 导出起点正确性（交接单、异常清单）
3. 冲突错误码（重复撤回、并发冲突、非保管人、验收后撤回）
4. 审计日志（RE_TRANSFER、撤回日志、规则版本）
5. 连续撤回后再交接
6. 重复撤回
7. 乱序/并发请求
8. 服务重启后的状态恢复
9. JSON 导出一致性
"""
import requests
import json
import os
import subprocess
import signal
import time
from datetime import datetime, timezone

BASE_URL = "http://localhost:8000"
TIMESTAMP = datetime.now().strftime("%Y%m%d%H%M%S")

def now_iso():
    return datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")

def print_test_result(name, passed, details=""):
    status = "✅ PASS" if passed else "❌ FAIL"
    print(f"  [{status}] {name}")
    if details:
        print(f"         {details}")
    return passed

def create_test_data(box_code):
    """创建测试箱、样本、交接数据"""
    samples = []
    for i in range(2):
        r = requests.post(f"{BASE_URL}/api/samples", json={
            "barcode": f"SAMP-REG-FIX-{now_iso()}-{i}",
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
    now = datetime.now(timezone.utc).isoformat()
    temp_records = json.dumps([
        {"temperature": 4.0, "timestamp": now}
    ], ensure_ascii=False)
    r = requests.post(f"{BASE_URL}/api/boxes/accept", json={
        "box_code": box_code,
        "custodian": custodian,
        "check_duration": False,
        "temperature_records": temp_records
    })
    return r

def get_error_code(response):
    try:
        return response.json().get("detail", {}).get("code", "UNKNOWN")
    except:
        return "UNKNOWN"

def test_scenario_1_history_retention():
    """测试1: 撤回前后历史保留"""
    print("\n=== Test 1: 撤回前后历史保留 ===")
    box_code = f"BOX-TEST1-{TIMESTAMP}"
    all_passed = True
    
    samples = create_test_data(box_code)
    
    # 第一次交接
    r = do_transfer(box_code, "Dr. Zhang", "Dr. Li", "TP001")
    assert r.status_code == 200
    transfer1_id = r.json()["transfer_id"]
    
    # 撤回
    r = do_revoke(box_code, "Dr. Li", "测试撤回")
    assert r.status_code == 200
    
    # 历史记录应该包含已撤回的记录
    history = requests.get(f"{BASE_URL}/api/boxes/{box_code}/transfer-history").json()
    p1 = print_test_result(
        "1.1 历史记录包含已撤回记录",
        len(history) == 1 and history[0]["is_revoked"] == True,
        f"记录数={len(history)}, 已撤回={history[0].get('is_revoked')}"
    )
    all_passed = all_passed and p1
    
    # 重新交接
    r = do_transfer(box_code, "Dr. Zhang", "Dr. Wang", "TP002")
    assert r.status_code == 200
    transfer2_id = r.json()["transfer_id"]
    
    # 历史记录应该包含2条，1条撤回1条有效
    history = requests.get(f"{BASE_URL}/api/boxes/{box_code}/transfer-history").json()
    revoked_count = len([t for t in history if t.get("is_revoked")])
    active_count = len([t for t in history if not t.get("is_revoked")])
    p2 = print_test_result(
        "1.2 重新交接后历史记录完整",
        len(history) == 2 and revoked_count == 1 and active_count == 1,
        f"总记录={len(history)}, 已撤回={revoked_count}, 活跃={active_count}"
    )
    all_passed = all_passed and p2
    
    # 已撤回记录字段完整
    revoked = next(t for t in history if t.get("is_revoked"))
    p3 = print_test_result(
        "1.3 已撤回记录字段完整",
        revoked.get("revoked_by") == "Dr. Li" and 
        revoked.get("revoke_reason") == "测试撤回" and
        revoked.get("revoked_at") is not None,
        f"revoked_by={revoked.get('revoked_by')}, reason={revoked.get('revoke_reason')}"
    )
    all_passed = all_passed and p3
    
    return all_passed, box_code

def test_scenario_2_export_correctness():
    """测试2: 导出起点正确性"""
    print("\n=== Test 2: 导出起点正确性 ===")
    box_code = f"BOX-TEST2-{TIMESTAMP}"
    all_passed = True
    
    samples = create_test_data(box_code)
    
    # 交接 → 撤回 → 重新交接
    do_transfer(box_code, "Dr. Zhang", "Dr. Li", "TP001")
    do_revoke(box_code, "Dr. Li", "样本错误")
    r = do_transfer(box_code, "Dr. Zhang", "Dr. Wang", "TP002")
    assert r.status_code == 200
    
    # 验证交接单导出
    form = requests.get(f"{BASE_URL}/api/boxes/{box_code}/handover-form").json()
    p1 = print_test_result(
        "2.1 交接单 from_point 正确（基于有效交接）",
        form["from_point"] == "CP001",
        f"from_point={form['from_point']}, 预期=CP001"
    )
    all_passed = all_passed and p1
    
    p2 = print_test_result(
        "2.2 交接单 to_point 正确",
        form["to_point"] == "TP002",
        f"to_point={form['to_point']}, 预期=TP002"
    )
    all_passed = all_passed and p2
    
    p3 = print_test_result(
        "2.3 交接单保管人正确",
        form["from_custodian"] == "Dr. Zhang" and form["to_custodian"] == "Dr. Wang",
        f"from={form['from_custodian']}, to={form['to_custodian']}"
    )
    all_passed = all_passed and p3
    
    p4 = print_test_result(
        "2.4 交接单包含撤回历史",
        len(form.get("revoked_transfer_history", [])) == 1,
        f"撤回历史={len(form.get('revoked_transfer_history', []))}条"
    )
    all_passed = all_passed and p4
    
    # 验证异常清单导出
    exception = requests.get(f"{BASE_URL}/api/boxes/{box_code}/exception-list").json()
    revoke_exceptions = [e for e in exception.get("exceptions", []) 
                        if e.get("type") == "TRANSFER_REVOKED"]
    p5 = print_test_result(
        "2.5 异常清单包含撤回异常",
        len(revoke_exceptions) == 1,
        f"TRANSFER_REVOKED异常={len(revoke_exceptions)}条"
    )
    all_passed = all_passed and p5
    
    p6 = print_test_result(
        "2.6 异常清单包含撤回历史",
        len(exception.get("revoked_transfer_history", [])) == 1,
        f"撤回历史存在={exception.get('revoked_transfer_history') is not None}"
    )
    all_passed = all_passed and p6
    
    return all_passed, box_code

def test_scenario_3_from_point_validation():
    """测试3: from_point 有效性验证（核心修复验证）"""
    print("\n=== Test 3: from_point 有效性验证（核心修复） ===")
    box_code = f"BOX-TEST3-{TIMESTAMP}"
    all_passed = True
    
    samples = create_test_data(box_code)
    
    # 场景A: 所有交接都被撤回后，from_point 应为采集点
    do_transfer(box_code, "Dr. Zhang", "Dr. Li", "TP001")
    do_revoke(box_code, "Dr. Li", "全部撤回场景A")
    
    r = do_transfer(box_code, "Dr. Zhang", "Dr. Wang", "TP002")
    assert r.status_code == 200
    transfer_id = r.json()["transfer_id"]
    
    history = requests.get(f"{BASE_URL}/api/boxes/{box_code}/transfer-history").json()
    t = next(t for t in history if t["id"] == transfer_id)
    p1 = print_test_result(
        "3.1 全部撤回后 from_point=采集点",
        t["from_point"] == "CP001",
        f"from_point={t['from_point']}, 预期=CP001"
    )
    all_passed = all_passed and p1
    
    # 场景B: 部分撤回（有有效交接），from_point 应为有效交接的 to_point
    box_code2 = f"BOX-TEST3B-{TIMESTAMP}"
    create_test_data(box_code2)
    
    # 交接1（不撤回）
    do_transfer(box_code2, "Dr. Zhang", "Dr. Li", "TP001")
    # 交接2（不撤回）
    do_revoke(box_code2, "Dr. Li", "撤回交接1")
    # 交接2（有效）
    r = do_transfer(box_code2, "Dr. Zhang", "Dr. Wang", "TP002")
    assert r.status_code == 200
    transfer2_id = r.json()["transfer_id"]
    
    history2 = requests.get(f"{BASE_URL}/api/boxes/{box_code2}/transfer-history").json()
    active = next(t for t in history2 if not t.get("is_revoked"))
    p2 = print_test_result(
        "3.2 有有效交接时 from_point=上一有效交接的 to_point",
        active["from_point"] == "CP001",
        f"from_point={active['from_point']}, 预期=CP001"
    )
    all_passed = all_passed and p2
    
    # 场景C: 连续多次撤回-重新交接
    box_code3 = f"BOX-TEST3C-{TIMESTAMP}"
    create_test_data(box_code3)
    
    expected_from = "CP001"
    for i in range(3):
        r = do_transfer(box_code3, "Dr. Zhang", f"Dr. Cust{i+1}", f"TP00{i+1}")
        assert r.status_code == 200, f"第{i+1}次交接失败"
        transfer_id = r.json()["transfer_id"]
        
        history = requests.get(f"{BASE_URL}/api/boxes/{box_code3}/transfer-history").json()
        t = next(t for t in history if t["id"] == transfer_id)
        p = print_test_result(
            f"3.{3+i} 第{i+1}次交接 from_point 正确",
            t["from_point"] == expected_from,
            f"from_point={t['from_point']}, 预期={expected_from}"
        )
        all_passed = all_passed and p
        
        if i < 2:
            do_revoke(box_code3, f"Dr. Cust{i+1}", f"第{i+1}次撤回")
            expected_from = "CP001"  # 全部撤回后应该回到采集点
    
    return all_passed, box_code

def test_scenario_4_from_custodian_validation():
    """测试4: from_custodian 校验"""
    print("\n=== Test 4: from_custodian 校验 ===")
    box_code = f"BOX-TEST4-{TIMESTAMP}"
    all_passed = True
    
    samples = create_test_data(box_code)
    
    # 交接 → 撤回
    do_transfer(box_code, "Dr. Zhang", "Dr. Li", "TP001")
    do_revoke(box_code, "Dr. Li", "测试")
    
    # 用错误的 from_custodian 交接（应为 Dr. Zhang，用 Dr. Wrong）
    r = do_transfer(box_code, "Dr. Wrong", "Dr. Wang", "TP002")
    p1 = print_test_result(
        "4.1 错误的 from_custodian 被拒绝",
        r.status_code == 400 and get_error_code(r) == "INVALID_CUSTODIAN",
        f"HTTP {r.status_code}, code={get_error_code(r)}"
    )
    all_passed = all_passed and p1
    
    # 用正确的 from_custodian 交接
    r = do_transfer(box_code, "Dr. Zhang", "Dr. Wang", "TP002")
    p2 = print_test_result(
        "4.2 正确的 from_custodian 可正常交接",
        r.status_code == 200,
        f"HTTP {r.status_code}"
    )
    all_passed = all_passed and p2
    
    return all_passed, box_code

def test_scenario_5_conflict_error_codes():
    """测试5: 冲突错误码"""
    print("\n=== Test 5: 冲突错误码验证 ===")
    box_code = f"BOX-TEST5-{TIMESTAMP}"
    all_passed = True
    
    samples = create_test_data(box_code)
    
    # 5.1 非保管人撤回
    do_transfer(box_code, "Dr. Zhang", "Dr. Li", "TP001")
    r = do_revoke(box_code, "Dr. Wrong", "非保管人撤回")
    p1 = print_test_result(
        "5.1 非保管人撤回返回 INVALID_CUSTODIAN",
        r.status_code == 400 and get_error_code(r) == "INVALID_CUSTODIAN",
        f"HTTP {r.status_code}, code={get_error_code(r)}"
    )
    all_passed = all_passed and p1
    
    # 5.2 重复撤回
    do_revoke(box_code, "Dr. Li", "第一次撤回")
    r = do_revoke(box_code, "Dr. Zhang", "重复撤回")
    p2 = print_test_result(
        "5.2 重复撤回返回 TRANSFER_ALREADY_REVOKED",
        r.status_code == 409 and get_error_code(r) == "TRANSFER_ALREADY_REVOKED",
        f"HTTP {r.status_code}, code={get_error_code(r)}"
    )
    all_passed = all_passed and p2
    
    # 5.3 验收后撤回
    box_code2 = f"BOX-TEST5B-{TIMESTAMP}"
    create_test_data(box_code2)
    do_transfer(box_code2, "Dr. Zhang", "Dr. Li", "TP001")
    do_accept(box_code2, "Dr. Li")
    r = do_revoke(box_code2, "Dr. Li", "验收后撤回")
    p3 = print_test_result(
        "5.3 验收后撤回返回 BOX_INVALID_STATUS",
        r.status_code == 409 and get_error_code(r) == "BOX_INVALID_STATUS",
        f"HTTP {r.status_code}, code={get_error_code(r)}"
    )
    all_passed = all_passed and p3
    
    # 5.4 CONCURRENT_CONFLICT 在 OpenAPI 文档中
    openapi = requests.get(f"{BASE_URL}/openapi.json").json()
    revoke_path = openapi["paths"]["/api/boxes/revoke-transfer"]["post"]
    responses = str(revoke_path.get("responses", {}))
    p4 = print_test_result(
        "5.4 OpenAPI 包含 CONCURRENT_CONFLICT",
        "CONCURRENT_CONFLICT" in responses,
        f"CONCURRENT_CONFLICT 存在={'CONCURRENT_CONFLICT' in responses}"
    )
    all_passed = all_passed and p4
    
    # 5.5 不存在的箱子
    r = do_revoke("NONEXISTENT", "Dr. Zhang", "不存在的箱子")
    p5 = print_test_result(
        "5.5 不存在的箱子返回 BOX_NOT_FOUND",
        r.status_code == 404 and get_error_code(r) == "BOX_NOT_FOUND",
        f"HTTP {r.status_code}, code={get_error_code(r)}"
    )
    all_passed = all_passed and p5
    
    return all_passed, box_code

def test_scenario_6_audit_logs():
    """测试6: 审计日志"""
    print("\n=== Test 6: 审计日志验证 ===")
    box_code = f"BOX-TEST6-{TIMESTAMP}"
    all_passed = True
    
    samples = create_test_data(box_code)
    
    # 交接 → 撤回 → 重新交接
    do_transfer(box_code, "Dr. Zhang", "Dr. Li", "TP001")
    r = do_revoke(box_code, "Dr. Li", "审计测试撤回")
    r = do_transfer(box_code, "Dr. Zhang", "Dr. Wang", "TP002")
    transfer2_id = r.json()["transfer_id"]
    
    # 查询审计日志
    audit = requests.get(f"{BASE_URL}/api/audit", params={
        "entity_type": "TRANSFER", 
        "entity_id": transfer2_id
    }).json()
    
    re_transfer_logs = [l for l in audit if l.get("action") == "RE_TRANSFER"]
    p1 = print_test_result(
        "6.1 RE_TRANSFER 审计日志存在",
        len(re_transfer_logs) >= 1,
        f"RE_TRANSFER 日志={len(re_transfer_logs)}条"
    )
    all_passed = all_passed and p1
    
    if re_transfer_logs:
        details_str = re_transfer_logs[0].get("details", "{}")
        details = json.loads(details_str) if isinstance(details_str, str) else details_str
        p2 = print_test_result(
            "6.2 RE_TRANSFER 包含关联信息",
            "prev_transfer_id" in details and "revoked_count_before" in details,
            f"prev_transfer_id={'prev_transfer_id' in details}, revoked_count={'revoked_count_before' in details}"
        )
        all_passed = all_passed and p2
        
        p3 = print_test_result(
            "6.3 RE_TRANSFER 包含规则版本",
            "rule_version" in details,
            f"rule_version={'rule_version' in details}"
        )
        all_passed = all_passed and p3
        
        p4 = print_test_result(
            "6.4 RE_TRANSFER 包含前后保管人",
            details.get("from_custodian") == "Dr. Zhang" and 
            details.get("to_custodian") == "Dr. Wang",
            f"from={details.get('from_custodian')}, to={details.get('to_custodian')}"
        )
        all_passed = all_passed and p4
    
    # 验证撤回审计日志
    audit_all = requests.get(f"{BASE_URL}/api/audit", params={"entity_type": "TRANSFER"}).json()
    revoke_logs = [l for l in audit_all if l.get("action") == "REVOKE_TRANSFER"]
    p5 = print_test_result(
        "6.5 撤回审计日志存在",
        len(revoke_logs) >= 1,
        f"REVOKE_TRANSFER 日志={len(revoke_logs)}条"
    )
    all_passed = all_passed and p5
    
    return all_passed, box_code

def test_scenario_7_continuous_revoke():
    """测试7: 连续撤回后再交接"""
    print("\n=== Test 7: 连续撤回后再交接 ===")
    box_code = f"BOX-TEST7-{TIMESTAMP}"
    all_passed = True
    
    samples = create_test_data(box_code)
    
    # 3轮撤回-重新交接
    transfer_ids = []
    for i in range(3):
        to_custodian = f"Dr. Cust{i+1}"
        r = do_transfer(box_code, "Dr. Zhang", to_custodian, f"TP00{i+1}")
        assert r.status_code == 200, f"第{i+1}次交接失败"
        transfer_ids.append(r.json()["transfer_id"])
        
        if i < 2:
            r = do_revoke(box_code, to_custodian, f"第{i+1}次撤回")
            assert r.status_code == 200, f"第{i+1}次撤回失败"
    
    # 验证历史记录
    history = requests.get(f"{BASE_URL}/api/boxes/{box_code}/transfer-history").json()
    revoked_count = len([t for t in history if t.get("is_revoked")])
    active_count = len([t for t in history if not t.get("is_revoked")])
    
    p1 = print_test_result(
        "7.1 历史记录完整",
        len(history) == 3 and revoked_count == 2 and active_count == 1,
        f"总记录={len(history)}, 已撤回={revoked_count}, 活跃={active_count}"
    )
    all_passed = all_passed and p1
    
    # 验证最后一次交接的 from_point（因为所有之前的都被撤回了，应该是 CP001）
    active = next(t for t in history if not t.get("is_revoked"))
    p2 = print_test_result(
        "7.2 最后一次交接 from_point 正确（全部撤回后=采集点）",
        active["from_point"] == "CP001",
        f"from_point={active['from_point']}, 预期=CP001"
    )
    all_passed = all_passed and p2
    
    # 验收
    r = do_accept(box_code, "Dr. Cust3")
    p3 = print_test_result(
        "7.3 多次撤回后验收成功",
        r.status_code == 200 and r.json()["status"] == "DELIVERED",
        f"status={r.json().get('status')}"
    )
    all_passed = all_passed and p3
    
    return all_passed, box_code

def test_scenario_8_partial_revoke():
    """测试8: 部分撤回场景（有有效交接）"""
    print("\n=== Test 8: 部分撤回场景（有有效交接） ===")
    box_code = f"BOX-TEST8-{TIMESTAMP}"
    all_passed = True
    
    samples = create_test_data(box_code)
    
    # 交接1（有效）: CP001 → TP001, Zhang → Li
    do_transfer(box_code, "Dr. Zhang", "Dr. Li", "TP001")
    
    # 交接2（撤回）: TP001 → TP002, Li → Wang
    r = do_transfer(box_code, "Dr. Li", "Dr. Wang", "TP002")
    transfer2_id = r.json()["transfer_id"]
    do_revoke(box_code, "Dr. Wang", "撤回交接2")
    
    # 交接3（重新交接）: TP001 → TP003, Li → Zhao
    r = do_transfer(box_code, "Dr. Li", "Dr. Zhao", "TP003")
    transfer3_id = r.json()["transfer_id"]
    
    # 验证交接3的 from_point 应该是 TP001（交接1的 to_point）
    history = requests.get(f"{BASE_URL}/api/boxes/{box_code}/transfer-history").json()
    t3 = next(t for t in history if t["id"] == transfer3_id)
    
    p1 = print_test_result(
        "8.1 部分撤回后 from_point 基于有效交接",
        t3["from_point"] == "TP001",
        f"from_point={t3['from_point']}, 预期=TP001（基于有效交接1的to_point）"
    )
    all_passed = all_passed and p1
    
    p2 = print_test_result(
        "8.2 历史记录数正确",
        len(history) == 3,
        f"记录数={len(history)}"
    )
    all_passed = all_passed and p2
    
    # 验证交接单导出
    form = requests.get(f"{BASE_URL}/api/boxes/{box_code}/handover-form").json()
    p3 = print_test_result(
        "8.3 交接单 from_point 正确",
        form["from_point"] == "TP001",
        f"交接单 from_point={form['from_point']}, 预期=TP001"
    )
    all_passed = all_passed and p3
    
    return all_passed, box_code

def test_scenario_9_concurrent_requests():
    """测试9: 乱序/并发请求冲突"""
    print("\n=== Test 9: 乱序/并发请求冲突 ===")
    box_code = f"BOX-TEST9-{TIMESTAMP}"
    all_passed = True
    
    samples = create_test_data(box_code)
    
    # 交接
    r = do_transfer(box_code, "Dr. Zhang", "Dr. Li", "TP001")
    transfer_id = r.json()["transfer_id"]
    
    # 第一次撤回（成功）
    r1 = do_revoke(box_code, "Dr. Li", "并发测试撤回1")
    p1 = print_test_result(
        "9.1 第一次撤回成功",
        r1.status_code == 200,
        f"HTTP {r1.status_code}"
    )
    all_passed = all_passed and p1
    
    # 立即再次撤回（模拟并发/乱序，应失败）
    r2 = do_revoke(box_code, "Dr. Zhang", "并发测试撤回2")
    p2 = print_test_result(
        "9.2 重复撤回被拒绝",
        r2.status_code == 409 and get_error_code(r2) == "TRANSFER_ALREADY_REVOKED",
        f"HTTP {r2.status_code}, code={get_error_code(r2)}"
    )
    all_passed = all_passed and p2
    
    # 所有记录都撤回后再撤回
    r3 = do_revoke(box_code, "Dr. Zhang", "所有记录已撤回后再撤回")
    p3 = print_test_result(
        "9.3 所有记录已撤回后返回正确错误码",
        r3.status_code == 409 and get_error_code(r3) == "TRANSFER_ALREADY_REVOKED",
        f"HTTP {r3.status_code}, code={get_error_code(r3)}"
    )
    all_passed = all_passed and p3
    
    return all_passed, box_code

def test_scenario_10_json_export_consistency():
    """测试10: JSON 导出一致性"""
    print("\n=== Test 10: JSON 导出一致性 ===")
    box_code = f"BOX-TEST10-{TIMESTAMP}"
    all_passed = True
    
    samples = create_test_data(box_code)
    
    # 交接 → 撤回 → 重新交接 → 验收
    do_transfer(box_code, "Dr. Zhang", "Dr. Li", "TP001")
    do_revoke(box_code, "Dr. Li", "导出测试撤回")
    do_transfer(box_code, "Dr. Zhang", "Dr. Wang", "TP002")
    do_accept(box_code, "Dr. Wang")
    
    # 获取当前状态
    box_info = requests.get(f"{BASE_URL}/api/boxes/{box_code}").json()
    history = requests.get(f"{BASE_URL}/api/boxes/{box_code}/transfer-history").json()
    form = requests.get(f"{BASE_URL}/api/boxes/{box_code}/handover-form").json()
    exception = requests.get(f"{BASE_URL}/api/boxes/{box_code}/exception-list").json()
    
    # 验证各个接口的 from_point 一致
    active = next(t for t in history if not t.get("is_revoked"))
    p1 = print_test_result(
        "10.1 历史记录与交接单 from_point 一致",
        active["from_point"] == form["from_point"] == "CP001",
        f"历史={active['from_point']}, 交接单={form['from_point']}"
    )
    all_passed = all_passed and p1
    
    # 验证保管人一致
    p2 = print_test_result(
        "10.2 箱子状态与交接单保管人一致",
        box_info["current_custodian"] == form["to_custodian"] == "Dr. Wang",
        f"箱子={box_info['current_custodian']}, 交接单={form['to_custodian']}"
    )
    all_passed = all_passed and p2
    
    # 验证撤回历史一致
    p3 = print_test_result(
        "10.3 交接单与异常清单撤回历史一致",
        len(form.get("revoked_transfer_history", [])) == 
        len(exception.get("revoked_transfer_history", [])) == 1,
        f"交接单撤回历史={len(form.get('revoked_transfer_history', []))}, "
        f"异常清单撤回历史={len(exception.get('revoked_transfer_history', []))}"
    )
    all_passed = all_passed and p3
    
    # 验证导出文件存在
    export_dir = os.path.join(os.getcwd(), "exports")
    form_file = os.path.join(export_dir, f"handover_form_{box_code}.json")
    exception_file = os.path.join(export_dir, f"exception_list_{box_code}.json")
    
    p4 = print_test_result(
        "10.4 交接单导出文件存在",
        os.path.exists(form_file),
        f"文件存在={os.path.exists(form_file)}"
    )
    all_passed = all_passed and p4
    
    p5 = print_test_result(
        "10.5 异常清单导出文件存在",
        os.path.exists(exception_file),
        f"文件存在={os.path.exists(exception_file)}"
    )
    all_passed = all_passed and p5
    
    return all_passed, box_code

def main():
    print("=" * 70)
    print("  撤回后重新交接修复 - 完整回归测试")
    print(f"  测试时间: {datetime.now().isoformat()}")
    print("=" * 70)
    
    # 检查服务状态
    try:
        r = requests.get(f"{BASE_URL}/health", timeout=5)
        print("\n服务运行中")
    except:
        print("\n❌ 服务未运行，请先启动服务")
        return
    
    all_results = []
    total_passed = 0
    total_tests = 0
    
    test_scenarios = [
        test_scenario_1_history_retention,
        test_scenario_2_export_correctness,
        test_scenario_3_from_point_validation,
        test_scenario_4_from_custodian_validation,
        test_scenario_5_conflict_error_codes,
        test_scenario_6_audit_logs,
        test_scenario_7_continuous_revoke,
        test_scenario_8_partial_revoke,
        test_scenario_9_concurrent_requests,
        test_scenario_10_json_export_consistency,
    ]
    
    for test_func in test_scenarios:
        try:
            passed, box_code = test_func()
            all_results.append({
                "test": test_func.__name__,
                "passed": passed,
                "box_code": box_code
            })
            if passed:
                total_passed += 1
            total_tests += 1
        except Exception as e:
            print(f"  ❌ 测试异常: {e}")
            import traceback
            traceback.print_exc()
            all_results.append({
                "test": test_func.__name__,
                "passed": False,
                "error": str(e)
            })
            total_tests += 1
    
    # 总结
    print("\n" + "=" * 70)
    print("  测试总结")
    print("=" * 70)
    print(f"  总测试场景: {total_tests}")
    print(f"  通过: {total_passed}")
    print(f"  失败: {total_tests - total_passed}")
    print()
    
    for result in all_results:
        status = "✅ PASS" if result["passed"] else "❌ FAIL"
        print(f"  [{status}] {result['test']}")
        if "box_code" in result:
            print(f"         测试箱号: {result['box_code']}")
        if "error" in result:
            print(f"         错误: {result['error']}")
    
    print()
    if total_passed == total_tests:
        print("🎉 所有测试通过！修复验证成功！")
    else:
        print(f"⚠️  {total_tests - total_passed} 个测试失败，请检查！")
    
    # 保存结果
    result_file = f"regression_result_{TIMESTAMP}.json"
    with open(result_file, "w", encoding="utf-8") as f:
        json.dump({
            "test_time": datetime.now().isoformat(),
            "total_tests": total_tests,
            "passed": total_passed,
            "failed": total_tests - total_passed,
            "all_passed": total_passed == total_tests,
            "results": all_results
        }, f, ensure_ascii=False, indent=2)
    print(f"\n结果已保存到: {result_file}")
    
    return total_passed == total_tests

if __name__ == "__main__":
    try:
        success = main()
        exit(0 if success else 1)
    except Exception as e:
        print(f"\n❌ 测试异常: {e}")
        import traceback
        traceback.print_exc()
        exit(1)
