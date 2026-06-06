import requests
import json
from datetime import datetime

BASE_URL = "http://localhost:8000"
TIMESTAMP = datetime.now().strftime("%Y%m%d%H%M%S")
BOX_CODE = f"BOX-E2E-FINAL-{TIMESTAMP}"

def log(step, message):
    print(f"[{step:3d}] {message}")

def main():
    print("=" * 80)
    print("  样本箱撤回后再交接 - 完整端到端真实链路验证")
    print(f"  测试箱号: {BOX_CODE}")
    print("=" * 80)
    print()

    results = []

    # 1. 创建测试数据
    log(1, "创建测试数据...")

    # 先创建样本
    samples = []
    for i in range(2):
        r = requests.post(f"{BASE_URL}/api/samples", json={
            "barcode": f"SAMP-E2E-{TIMESTAMP}-{i}",
            "sample_type": "blood",
            "collection_point": "CP001",
            "collection_time": "2024-01-01T10:00:00",
            "current_custodian": "Dr. Zhang",
            "patient_info": json.dumps({"name": "Test Patient"}, ensure_ascii=False)
        })
        assert r.status_code in [200, 201], f"创建样本失败: {r.text}"
        samples.append(r.json())
    log(1, "✅ 创建2份样本成功")

    # 再创建箱子
    r = requests.post(f"{BASE_URL}/api/boxes", json={
        "box_code": BOX_CODE,
        "destination": "TP003",
        "current_custodian": "Dr. Zhang"
    })
    assert r.status_code in [200, 201], f"创建箱子失败: {r.text}"
    log(1, "✅ 创建箱子成功")

    # 把样本装入箱子
    barcodes = [s["barcode"] for s in samples]
    r = requests.post(f"{BASE_URL}/api/boxes/pack", json={
        "box_code": BOX_CODE,
        "barcodes": barcodes,
        "custodian": "Dr. Zhang"
    })
    assert r.status_code == 200, f"装样本失败: {r.text}"
    log(1, "✅ 样本装箱成功")

    # 封箱
    r = requests.post(f"{BASE_URL}/api/boxes/seal",
        params={"box_code": BOX_CODE, "custodian": "Dr. Zhang"})
    assert r.status_code == 200, f"封箱失败: {r.text}"
    log(1, "✅ 封箱成功，状态=SEALED")

    # 2. 第一次交接
    log(2, "第一次交接: CP001 → TP001, 保管人: Dr. Zhang → Dr. Li")
    temp_records = json.dumps([
        {"temperature": 4.0, "timestamp": "2024-01-01T10:00:00"},
        {"temperature": 4.2, "timestamp": "2024-01-01T10:05:00"}
    ], ensure_ascii=False)
    r = requests.post(f"{BASE_URL}/api/boxes/transfer", json={
        "box_code": BOX_CODE,
        "from_custodian": "Dr. Zhang",
        "to_custodian": "Dr. Li",
        "to_point": "TP001",
        "temperature": 4.0,
        "temperature_records": temp_records
    })
    assert r.status_code == 200, f"交接失败: {r.text}"
    transfer1_id = r.json()["transfer_id"]
    log(2, f"✅ 第一次交接成功，ID={transfer1_id}")

    # 3. 第一次撤回
    log(3, "第一次撤回: 撤回 ID={} 的交接记录，原因: 样本信息有误".format(transfer1_id))
    r = requests.post(f"{BASE_URL}/api/boxes/revoke-transfer", json={
        "box_code": BOX_CODE,
        "custodian": "Dr. Li",
        "reason": "样本信息有误"
    })
    assert r.status_code == 200, f"撤回失败: {r.text}"
    log(3, "✅ 第一次撤回成功，箱子状态已回退为 SEALED")

    # 4. 重复撤回（应失败）
    log(4, "尝试重复撤回（应返回 409 TRANSFER_ALREADY_REVOKED）")
    r = requests.post(f"{BASE_URL}/api/boxes/revoke-transfer", json={
        "box_code": BOX_CODE,
        "custodian": "Dr. Zhang",
        "reason": "重复撤回测试"
    })
    assert r.status_code == 409, f"重复撤回应返回409: {r.text}"
    error_code = r.json().get("detail", {}).get("code")
    assert error_code == "TRANSFER_ALREADY_REVOKED", f"错误码错误: {error_code}"
    log(4, f"✅ 重复撤回已被拒绝，code={error_code}")

    # 5. 第二次交接（重新交接）
    log(5, "第二次交接（重新交接）: from_point应=TP001，保管人: Dr. Zhang → Dr. Wang")
    temp_records = json.dumps([
        {"temperature": 4.5, "timestamp": "2024-01-01T11:00:00"},
        {"temperature": 4.7, "timestamp": "2024-01-01T11:05:00"}
    ], ensure_ascii=False)
    r = requests.post(f"{BASE_URL}/api/boxes/transfer", json={
        "box_code": BOX_CODE,
        "from_custodian": "Dr. Zhang",
        "to_custodian": "Dr. Wang",
        "to_point": "TP002",
        "temperature": 4.5,
        "temperature_records": temp_records
    })
    assert r.status_code == 200, f"重新交接失败: {r.text}"
    transfer2_id = r.json()["transfer_id"]
    log(5, f"✅ 重新交接成功，ID={transfer2_id}")

    # 验证 from_point
    history = requests.get(f"{BASE_URL}/api/boxes/{BOX_CODE}/transfer-history").json()
    t2 = next(t for t in history if t["id"] == transfer2_id)
    assert t2["from_point"] == "TP001", f"from_point错误: {t2['from_point']}"
    log(5, f"✅ from_point验证通过: {t2['from_point']} == TP001")

    # 6. 第二次撤回
    log(6, "第二次撤回: 撤回 ID={} 的交接记录，原因: 运输温度超标".format(transfer2_id))
    r = requests.post(f"{BASE_URL}/api/boxes/revoke-transfer", json={
        "box_code": BOX_CODE,
        "custodian": "Dr. Wang",
        "reason": "运输温度超标"
    })
    assert r.status_code == 200, f"第二次撤回失败: {r.text}"
    log(6, "✅ 第二次撤回成功")

    # 7. 第三次交接（重新交接）
    log(7, "第三次交接: from_point应=TP002，保管人: Dr. Zhang → Dr. Zhao")
    temp_records = json.dumps([
        {"temperature": 3.8, "timestamp": "2024-01-01T12:00:00"},
        {"temperature": 4.0, "timestamp": "2024-01-01T12:05:00"}
    ], ensure_ascii=False)
    r = requests.post(f"{BASE_URL}/api/boxes/transfer", json={
        "box_code": BOX_CODE,
        "from_custodian": "Dr. Zhang",
        "to_custodian": "Dr. Zhao",
        "to_point": "TP003",
        "temperature": 3.8,
        "temperature_records": temp_records
    })
    assert r.status_code == 200, f"第三次交接失败: {r.text}"
    transfer3_id = r.json()["transfer_id"]
    log(7, f"✅ 第三次交接成功，ID={transfer3_id}")

    # 验证 from_point
    history = requests.get(f"{BASE_URL}/api/boxes/{BOX_CODE}/transfer-history").json()
    t3 = next(t for t in history if t["id"] == transfer3_id)
    assert t3["from_point"] == "TP002", f"from_point错误: {t3['from_point']}"
    log(7, f"✅ from_point验证通过: {t3['from_point']} == TP002")

    # 8. 验收
    log(8, "验收: 由 Dr. Zhao 验收")
    temp_records = json.dumps([
        {"temperature": 4.0, "timestamp": "2024-01-01T12:30:00"},
        {"temperature": 4.1, "timestamp": "2024-01-01T12:35:00"}
    ], ensure_ascii=False)
    r = requests.post(f"{BASE_URL}/api/boxes/accept", json={
        "box_code": BOX_CODE,
        "custodian": "Dr. Zhao",
        "check_duration": False,
        "temperature_records": temp_records
    })
    assert r.status_code == 200, f"验收失败: {r.text}"
    status = r.json()["status"]
    assert status == "DELIVERED", f"验收后状态错误: {status}"
    log(8, f"✅ 验收成功，状态={status}")

    # 9. 验证交接单导出
    log(9, "验证交接单导出...")
    r = requests.get(f"{BASE_URL}/api/boxes/{BOX_CODE}/handover-form")
    assert r.status_code == 200, f"交接单导出失败: {r.text}"
    form_data = r.json()
    assert form_data["from_point"] == "TP002", f"交接单from_point错误: {form_data['from_point']}"
    assert form_data["to_point"] == "TP003", f"交接单to_point错误: {form_data['to_point']}"
    assert len(form_data.get("revoked_transfer_history", [])) == 2, f"撤回历史数量错误"
    assert form_data["is_revoked"] == False, f"当前交接is_revoked错误"
    log(9, "✅ 交接单导出验证通过: from_point=TP002, 撤回历史=2条, 当前交接有效")

    # 10. 验证异常清单导出
    log(10, "验证异常清单导出...")
    r = requests.get(f"{BASE_URL}/api/boxes/{BOX_CODE}/exception-list")
    assert r.status_code == 200, f"异常清单导出失败: {r.text}"
    exception_data = r.json()
    revoke_exceptions = [e for e in exception_data.get("exceptions", []) if e.get("type") == "TRANSFER_REVOKED"]
    assert len(revoke_exceptions) == 2, f"TRANSFER_REVOKED异常数量错误: {len(revoke_exceptions)}"
    log(10, f"✅ 异常清单验证通过: TRANSFER_REVOKED异常={len(revoke_exceptions)}条")

    # 11. 验证审计日志
    log(11, "验证审计日志...")
    r = requests.get(f"{BASE_URL}/api/audit", params={"entity_type": "TRANSFER", "entity_id": transfer3_id})
    assert r.status_code == 200, f"审计日志查询失败: {r.text}"
    audit_logs = r.json()
    re_transfer_logs = [l for l in audit_logs if l.get("action") == "RE_TRANSFER"]
    transfer_logs = [l for l in audit_logs if l.get("action") == "TRANSFER"]
    assert len(re_transfer_logs) >= 1, f"缺少RE_TRANSFER审计日志"
    assert len(transfer_logs) >= 1, f"缺少TRANSFER审计日志"

    # 检查 RE_TRANSFER 日志详情
    re_transfer = re_transfer_logs[0]
    details_str = re_transfer.get("details", "{}")
    details = json.loads(details_str) if isinstance(details_str, str) else details_str
    assert "prev_transfer_id" in details, f"RE_TRANSFER缺少prev_transfer_id"
    assert "revoked_count_before" in details, f"RE_TRANSFER缺少revoked_count_before"
    assert "rule_version" in details, f"RE_TRANSFER缺少rule_version"
    assert details["from_custodian"] == "Dr. Zhang", f"RE_TRANSFER from_custodian错误"
    assert details["to_custodian"] == "Dr. Zhao", f"RE_TRANSFER to_custodian错误"
    log(11, f"✅ 审计日志验证通过: RE_TRANSFER={len(re_transfer_logs)}条, 关联信息完整")

    # 12. 验证交接历史
    log(12, "验证完整交接历史...")
    history = requests.get(f"{BASE_URL}/api/boxes/{BOX_CODE}/transfer-history").json()
    assert len(history) == 3, f"历史记录数量错误: {len(history)}"
    revoked_count = len([t for t in history if t.get("is_revoked")])
    active_count = len([t for t in history if not t.get("is_revoked")])
    assert revoked_count == 2, f"已撤回记录数量错误: {revoked_count}"
    assert active_count == 1, f"活跃记录数量错误: {active_count}"
    log(12, f"✅ 交接历史验证通过: 总记录={len(history)}条, 已撤回={revoked_count}条, 活跃={active_count}条")

    # 13. 验证箱子状态
    log(13, "验证箱子最终状态...")
    box_info = requests.get(f"{BASE_URL}/api/boxes/{BOX_CODE}").json()
    assert box_info["status"] == "DELIVERED", f"箱子状态错误: {box_info['status']}"
    assert box_info["current_custodian"] == "Dr. Zhao", f"保管人错误: {box_info['current_custodian']}"
    log(13, f"✅ 箱子状态验证通过: status={box_info['status']}, custodian={box_info['current_custodian']}")

    # 14. 验证 OpenAPI 文档包含 CONCURRENT_CONFLICT
    log(14, "验证 OpenAPI 文档...")
    r = requests.get(f"{BASE_URL}/openapi.json")
    openapi = r.json()
    revoke_path = openapi["paths"]["/api/boxes/revoke-transfer"]["post"]
    responses = str(revoke_path.get("responses", {}))
    assert "CONCURRENT_CONFLICT" in responses, f"OpenAPI缺少CONCURRENT_CONFLICT错误码"
    log(14, "✅ OpenAPI文档验证通过: 包含CONCURRENT_CONFLICT错误码")

    # 15. 验收后尝试撤回（应失败）
    log(15, "验收后尝试撤回（应返回 409 BOX_INVALID_STATUS）")
    r = requests.post(f"{BASE_URL}/api/boxes/revoke-transfer", json={
        "box_code": BOX_CODE,
        "custodian": "Dr. Zhao",
        "reason": "验收后撤回测试"
    })
    assert r.status_code == 409, f"验收后撤回应返回409: {r.text}"
    error_code = r.json().get("detail", {}).get("code")
    assert error_code == "BOX_INVALID_STATUS", f"错误码错误: {error_code}"
    log(15, f"✅ 验收后撤回已被拒绝，code={error_code}")

    # 16. 非保管人尝试撤回（应失败）
    log(16, "非保管人尝试撤回（应返回 400 INVALID_CUSTODIAN）")
    r = requests.post(f"{BASE_URL}/api/boxes/revoke-transfer", json={
        "box_code": BOX_CODE,
        "custodian": "Dr. Stranger",
        "reason": "非保管人测试"
    })
    assert r.status_code == 400, f"非保管人撤回应返回400: {r.text}"
    error_code = r.json().get("detail", {}).get("code")
    assert error_code == "INVALID_CUSTODIAN", f"错误码错误: {error_code}"
    log(16, f"✅ 非保管人撤回已被拒绝，code={error_code}")

    print()
    print("=" * 80)
    print("  🎉 完整端到端链路验证全部通过!")
    print("=" * 80)
    print()
    print("  测试箱号:", BOX_CODE)
    print("  测试时间:", datetime.now().isoformat())
    print()
    print("  完整链路:")
    print("    1. 创建箱子 + 2份样本 + 封箱 (SEALED)")
    print("    2. 交接1: CP001→TP001, 保管人: Dr.Zhang→Dr.Li")
    print("    3. 撤回1: 原因=样本信息有误")
    print("    4. 重复撤回验证: ✅ 被拒绝")
    print("    5. 交接2（重发）: TP001→TP002, Dr.Zhang→Dr.Wang")
    print("    6. 撤回2: 原因=运输温度超标")
    print("    7. 交接3（重发）: TP002→TP003, Dr.Zhang→Dr.Zhao")
    print("    8. 验收: Dr.Zhao 验收成功 (DELIVERED)")
    print("    9. 交接单导出: ✅ from_point正确, 包含撤回历史")
    print("   10. 异常清单导出: ✅ 包含2条TRANSFER_REVOKED")
    print("   11. 审计日志: ✅ 包含RE_TRANSFER, 关联信息完整")
    print("   12. 交接历史: ✅ 3条记录, 2撤回1活跃")
    print("   13. 箱子状态: ✅ DELIVERED, 保管人Dr.Zhao")
    print("   14. OpenAPI文档: ✅ 包含CONCURRENT_CONFLICT")
    print("   15. 验收后撤回: ✅ 被拒绝")
    print("   16. 非保管人撤回: ✅ 被拒绝")
    print()

    # 保存结果
    result_file = f"e2e_result_{BOX_CODE}.json"
    with open(result_file, "w", encoding="utf-8") as f:
        json.dump({
            "test_time": datetime.now().isoformat(),
            "box_code": BOX_CODE,
            "all_passed": True,
            "steps": 16,
            "transfer_ids": [transfer1_id, transfer2_id, transfer3_id],
            "transfer_history": history
        }, f, ensure_ascii=False, indent=2)
    print(f"  结果已保存到: {result_file}")
    print()

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        exit(1)
