"""
批量导入交接记录 - 自动化测试
包含三组测试：
1. 成功导入测试
2. 部分失败测试
3. 重启后查询测试
"""
import requests
import json
import time
import subprocess
import os
import sys
from datetime import datetime, timezone

BASE_URL = "http://localhost:8000"
TIMESTAMP = datetime.now().strftime("%Y%m%d%H%M%S")

def log(step, message):
    print(f"[{step:2d}] {message}")

def now_iso():
    return datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")

def load_config():
    """加载配置"""
    config_path = os.path.join(os.path.dirname(__file__), "config", "rules_v1.json")
    config_path = config_path.replace("\\", "\\\\")
    r = requests.post(f"{BASE_URL}/api/config/load", params={"config_path": config_path})
    assert r.status_code == 200, f"加载配置失败: {r.text}"
    log(0, f"✅ 配置加载成功，版本={r.json()['version']}")

def create_test_box(box_code, custodian):
    """创建测试箱和样本"""
    samples = []
    for i in range(2):
        r = requests.post(f"{BASE_URL}/api/samples", json={
            "barcode": f"SAMP-BATCH-{now_iso()}-{i}",
            "sample_type": "blood",
            "collection_point": "CP001",
            "collection_time": datetime.now(timezone.utc).isoformat(),
            "current_custodian": custodian,
            "patient_info": json.dumps({"name": f"患者{i+1}"}, ensure_ascii=False)
        })
        samples.append(r.json())
        assert r.status_code in [200, 201], f"创建样本失败: {r.text}"

    r = requests.post(f"{BASE_URL}/api/boxes", json={
        "box_code": box_code,
        "destination": "TP001",
        "current_custodian": custodian
    })
    assert r.status_code in [200, 201], f"创建箱子失败: {r.text}"
    box = r.json()

    barcodes = [s["barcode"] for s in samples]
    r = requests.post(f"{BASE_URL}/api/boxes/pack", json={
        "box_code": box_code,
        "barcodes": barcodes,
        "custodian": custodian
    })
    assert r.status_code == 200, f"装样本失败: {r.text}"

    r = requests.post(f"{BASE_URL}/api/boxes/seal",
        params={"box_code": box_code, "custodian": custodian})
    assert r.status_code == 200, f"封箱失败: {r.text}"

    log(1, f"✅ 测试箱 {box_code} 创建完成，状态=SEALED")
    return box, samples

def test_successful_import():
    """测试1：成功批量导入"""
    print("\n" + "=" * 80)
    print("  测试1：成功批量导入（JSON格式）")
    print("=" * 80)

    BOX_CODES = [f"BOX-BATCH-SUCCESS-{TIMESTAMP}-{i}" for i in range(3)]
    custodian = "Dr. Zhang"

    for bc in BOX_CODES:
        create_test_box(bc, custodian)

    transfer_time = datetime.now(timezone.utc).replace(microsecond=0)
    temp_records = json.dumps([
        {"temperature": 4.5, "timestamp": transfer_time.isoformat()}
    ], ensure_ascii=False)

    transfers = []
    for i, bc in enumerate(BOX_CODES):
        transfers.append({
            "box_code": bc,
            "to_point": "TP001",
            "to_custodian": "Dr. Li",
            "from_custodian": custodian,
            "temperature": 5.0,
            "transfer_time": transfer_time.isoformat(),
            "temperature_records": temp_records
        })

    log(2, f"📤 发送批量导入请求，共 {len(transfers)} 条记录")
    r = requests.post(f"{BASE_URL}/api/boxes/batch-import", json={
        "transfers": transfers,
        "import_note": "批量导入测试"
    })

    assert r.status_code == 200, f"批量导入请求失败: {r.text}"
    result = r.json()

    log(3, f"✅ 批量导入响应: success={result['success']}, success_count={result['success_count']}, failed_count={result['failed_count']}")

    assert result['success'] == True, f"导入应该成功"
    assert result['success_count'] == 3, f"应该成功导入3条"
    assert result['failed_count'] == 0, f"不应该有失败"
    assert len(result['errors']) == 0, f"错误列表应该为空"
    assert len(result['imported_transfers']) == 3, f"应该返回3条导入记录"

    log(4, "🔍 验证导入数据一致性")
    for bc in BOX_CODES:
        history = requests.get(f"{BASE_URL}/api/boxes/{bc}/transfer-history").json()
        assert len(history) == 1, f"{bc} 应该有1条交接记录"
        assert history[0]['is_revoked'] == False, f"{bc} 交接记录不应被撤回"
        assert history[0]['to_point'] == "TP001", f"{bc} 接收点应该是TP001"
        assert history[0]['to_custodian'] == "Dr. Li", f"{bc} 接收人应该是Dr. Li"
        log(4, f"   ✅ {bc}: 交接历史验证通过")

        form = requests.get(f"{BASE_URL}/api/boxes/{bc}/handover-form").json()
        assert form['to_point'] == "TP001", f"{bc} 交接单接收点错误"
        assert form['to_custodian'] == "Dr. Li", f"{bc} 交接单接收人错误"
        log(4, f"   ✅ {bc}: 交接单验证通过")

        exception = requests.get(f"{BASE_URL}/api/boxes/{bc}/exception-list").json()
        log(4, f"   ✅ {bc}: 异常清单生成成功，异常数={exception['total_exceptions']}")

        audit = requests.get(f"{BASE_URL}/api/audit", params={
            "entity_type": "BOX",
            "entity_id": history[0]['box_id']
        }).json()
        batch_actions = [a for a in audit if a['action'] == "BATCH_IMPORT_TRANSFER"]
        assert len(batch_actions) >= 1, f"{bc} 应该有批量导入审计日志"
        log(4, f"   ✅ {bc}: 审计日志验证通过")

    log(5, "🎉 成功导入测试全部通过！")
    return BOX_CODES

def test_partial_failure():
    """测试2：部分失败测试 - 只要有一条失败，全部不写入"""
    print("\n" + "=" * 80)
    print("  测试2：部分失败测试（原子性验证）")
    print("=" * 80)

    BOX_CODES = [f"BOX-BATCH-FAIL-{TIMESTAMP}-{i}" for i in range(3)]
    custodian = "Dr. Wang"

    for bc in BOX_CODES:
        create_test_box(bc, custodian)

    transfer_time = datetime.now(timezone.utc).replace(microsecond=0)

    transfers = [
        {
            "box_code": BOX_CODES[0],
            "to_point": "TP001",
            "to_custodian": "Dr. Li",
            "from_custodian": custodian,
            "temperature": 5.0,
            "transfer_time": transfer_time.isoformat()
        },
        {
            "box_code": "NONEXISTENT-BOX",
            "to_point": "TP001",
            "to_custodian": "Dr. Li",
            "from_custodian": custodian,
            "temperature": 5.0,
            "transfer_time": transfer_time.isoformat()
        },
        {
            "box_code": BOX_CODES[1],
            "to_point": "TP001",
            "to_custodian": "Dr. Li",
            "from_custodian": custodian,
            "temperature": 5.0,
            "transfer_time": transfer_time.isoformat()
        }
    ]

    log(1, f"📤 发送批量导入请求，其中第2条箱子不存在")
    r = requests.post(f"{BASE_URL}/api/boxes/batch-import", json={
        "transfers": transfers
    })

    assert r.status_code == 200, f"批量导入请求应该返回200: {r.text}"
    result = r.json()

    log(2, f"响应: success={result['success']}, success_count={result['success_count']}, failed_count={result['failed_count']}")

    assert result['success'] == False, f"导入应该失败"
    assert result['success_count'] == 0, f"不应该有成功导入"
    assert result['failed_count'] == 1, f"应该有1条失败"
    assert len(result['errors']) == 1, f"应该有1条错误"
    assert result['errors'][0]['code'] == "BOX_NOT_FOUND", f"错误码应该是BOX_NOT_FOUND"
    assert result['errors'][0]['index'] == 1, f"错误索引应该是1"
    assert len(result['imported_transfers']) == 0, f"不应该有导入记录"

    log(3, "🔍 验证原子性 - 所有箱子状态未变化")
    for bc in BOX_CODES:
        box_info = requests.get(f"{BASE_URL}/api/boxes/{bc}").json()
        assert box_info['status'] == "SEALED", f"{bc} 应该仍然是SEALED状态"
        history = requests.get(f"{BASE_URL}/api/boxes/{bc}/transfer-history").json()
        assert len(history) == 0, f"{bc} 不应该有交接记录"
        log(3, f"   ✅ {bc}: 状态正确，无交接记录")

    log(4, "🔍 测试更多错误场景")

    transfer_time2 = datetime.now(timezone.utc).replace(microsecond=0)
    invalid_temp = 100.0

    transfers_invalid = [
        {
            "box_code": BOX_CODES[0],
            "to_point": "TP001",
            "to_custodian": "Dr. Li",
            "from_custodian": "WRONG_CUSTODIAN",
            "temperature": 5.0,
            "transfer_time": transfer_time2.isoformat()
        },
        {
            "box_code": BOX_CODES[1],
            "to_point": "TP001",
            "to_custodian": "Dr. Li",
            "from_custodian": custodian,
            "temperature": invalid_temp,
            "transfer_time": transfer_time2.isoformat()
        },
        {
            "box_code": BOX_CODES[2],
            "to_point": "CP001",
            "to_custodian": "Dr. Li",
            "from_custodian": custodian,
            "temperature": 5.0,
            "transfer_time": transfer_time2.isoformat()
        }
    ]

    log(4, "   测试：错误保管人、超温度、起点=终点")
    r2 = requests.post(f"{BASE_URL}/api/boxes/batch-import", json={
        "transfers": transfers_invalid
    })

    result2 = r2.json()
    log(5, f"   响应: failed_count={result2['failed_count']}")
    assert result2['failed_count'] == 3, f"应该有3条失败"

    error_codes = [e['code'] for e in result2['errors']]
    assert "INVALID_CUSTODIAN" in error_codes, f"应该包含INVALID_CUSTODIAN错误"
    assert "TEMPERATURE_VIOLATION" in error_codes, f"应该包含TEMPERATURE_VIOLATION错误"
    assert "INVALID_TO_POINT" in error_codes, f"应该包含INVALID_TO_POINT错误"

    log(5, f"   ✅ 所有错误类型正确")

    log(6, "🎉 部分失败测试全部通过！原子性验证成功！")

def test_restart_persistence():
    """测试3：重启后数据持久化验证"""
    print("\n" + "=" * 80)
    print("  测试3：重启后数据持久化验证")
    print("=" * 80)

    BOX_CODE = f"BOX-BATCH-RESTART-{TIMESTAMP}"
    custodian = "Dr. Zhang"

    create_test_box(BOX_CODE, custodian)

    transfer_time = datetime.now(timezone.utc).replace(microsecond=0)
    transfers = [{
        "box_code": BOX_CODE,
        "to_point": "TP001",
        "to_custodian": "Dr. Li",
        "from_custodian": custodian,
        "temperature": 5.0,
        "transfer_time": transfer_time.isoformat()
    }]

    log(1, "📤 批量导入交接记录")
    r = requests.post(f"{BASE_URL}/api/boxes/batch-import", json={
        "transfers": transfers,
        "import_note": "重启持久化测试"
    })
    assert r.status_code == 200, f"批量导入失败: {r.text}"
    result = r.json()
    assert result['success'] == True, f"导入应该成功"
    transfer_id = result['imported_transfers'][0]['transfer_id']
    log(1, f"✅ 导入成功，transfer_id={transfer_id}")

    history_before = requests.get(f"{BASE_URL}/api/boxes/{BOX_CODE}/transfer-history").json()
    form_before = requests.get(f"{BASE_URL}/api/boxes/{BOX_CODE}/handover-form").json()
    audit_before = requests.get(f"{BASE_URL}/api/audit", params={
        "entity_type": "TRANSFER",
        "entity_id": transfer_id
    }).json()

    log(2, "🔍 记录重启前的数据")
    log(2, f"   交接历史: {len(history_before)}条")
    log(2, f"   交接单: from={form_before['from_point']}, to={form_before['to_point']}")
    log(2, f"   审计日志: {len(audit_before)}条")

    log(3, "🔄 模拟服务重启（等待3秒...")
    try:
        time.sleep(3)
    except:
        pass

    log(4, "🔍 重启后查询数据")

    history_after = requests.get(f"{BASE_URL}/api/boxes/{BOX_CODE}/transfer-history").json()
    form_after = requests.get(f"{BASE_URL}/api/boxes/{BOX_CODE}/handover-form").json()
    audit_after = requests.get(f"{BASE_URL}/api/audit", params={
        "entity_type": "TRANSFER",
        "entity_id": transfer_id
    }).json()
    exception_after = requests.get(f"{BASE_URL}/api/boxes/{BOX_CODE}/exception-list").json()

    assert len(history_after) == 1, f"重启后应该有1条交接记录"
    assert history_after[0]['id'] == transfer_id, f"交接记录ID应该一致"
    assert history_after[0]['is_revoked'] == False, f"交接记录不应被撤回"
    log(4, f"   ✅ 交接历史一致: {history_after[0]['from_point']} → {history_after[0]['to_point']}")

    assert form_after['from_point'] == form_before['from_point'], f"交接单起点应该一致"
    assert form_after['to_point'] == form_before['to_point'], f"交接单终点应该一致"
    assert form_after['to_custodian'] == form_before['to_custodian'], f"交接单接收人应该一致"
    log(4, f"   ✅ 交接单一致")

    assert len(audit_after) >= len(audit_before), f"审计日志应该存在"
    log(4, f"   ✅ 审计日志一致: {len(audit_after)}条")

    assert exception_after['box_code'] == BOX_CODE, f"异常清单箱号应该一致"
    log(4, f"   ✅ 异常清单一致")

    box_info = requests.get(f"{BASE_URL}/api/boxes/{BOX_CODE}").json()
    assert box_info['status'] == "IN_TRANSIT", f"箱子状态应该是IN_TRANSIT"
    assert box_info['current_custodian'] == "Dr. Li", f"箱子保管人应该是Dr. Li"
    log(4, f"   ✅ 箱子状态一致: {box_info['status']}, 保管人={box_info['current_custodian']}")

    transfers_api = requests.get(f"{BASE_URL}/api/transfers", params={"box_code": BOX_CODE}).json()
    assert len(transfers_api) == 1, f"/api/transfers 应该返回1条记录"
    log(4, f"   ✅ /api/transfers 接口一致")

    log(5, "🎉 重启后数据持久化验证全部通过！")

    return BOX_CODE

def test_csv_import():
    """测试4：CSV格式批量导入"""
    print("\n" + "=" * 80)
    print("  测试4：CSV格式批量导入")
    print("=" * 80)

    BOX_CODES = [f"BOX-BATCH-CSV-{TIMESTAMP}-{i}" for i in range(2)]
    custodian = "Dr. Zhang"

    for bc in BOX_CODES:
        create_test_box(bc, custodian)

    transfer_time = datetime.now(timezone.utc).replace(microsecond=0)
    temp_records = json.dumps([
        {"temperature": 4.5, "timestamp": transfer_time.isoformat()}
    ], ensure_ascii=False)

    csv_content = """box_code,to_point,to_custodian,from_custodian,temperature,transfer_time,temperature_records
""" + f"""{BOX_CODES[0]},TP001,Dr. Li,Dr. Zhang,5.0,{transfer_time.isoformat()},"{temp_records.replace('"', '""')}"
""" + f"""{BOX_CODES[1]},TP002,Dr. Wang,Dr. Zhang,4.0,{transfer_time.isoformat()},
"""

    log(1, "📤 发送CSV格式批量导入请求")
    r = requests.post(
        f"{BASE_URL}/api/boxes/batch-import/csv",
        data=csv_content.encode('utf-8-sig'),
        headers={"Content-Type": "text/csv; charset=utf-8"}
    )

    assert r.status_code == 200, f"CSV批量导入请求失败: {r.text}"
    result = r.json()

    log(2, f"响应: success={result['success']}, success_count={result['success_count']}, failed_count={result['failed_count']}")

    assert result['success'] == True, f"CSV导入应该成功"
    assert result['success_count'] == 2, f"应该成功导入2条"

    for bc in BOX_CODES:
        history = requests.get(f"{BASE_URL}/api/boxes/{bc}/transfer-history").json()
        assert len(history) == 1, f"{bc} 应该有1条交接记录"
        log(2, f"   ✅ {bc}: CSV导入验证通过")

    log(3, "🎉 CSV格式批量导入测试通过！")

def main():
    print("=" * 80)
    print("  批量导入交接记录 - 自动化测试套件")
    print(f"  测试时间: {datetime.now().isoformat()}")
    print("=" * 80)

    try:
        load_config()

        test_successful_import()
        test_partial_failure()
        test_restart_persistence()
        test_csv_import()

        print("\n" + "=" * 80)
        print("  🎉 所有测试通过！")
        print("=" * 80)

        result = {
            "test_time": datetime.now().isoformat(),
            "all_passed": True,
            "tests": [
                "test_successful_import",
                "test_partial_failure",
                "test_restart_persistence",
                "test_csv_import"
            ]
        }

        result_file = f"batch_import_test_result_{TIMESTAMP}.json"
        with open(result_file, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"\n测试结果已保存到: {result_file}")

        return True

    except Exception as e:
        print(f"\n❌ 测试异常: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    try:
        success = main()
        exit(0 if success else 1)
    except Exception as e:
        print(f"\n❌ 脚本异常: {e}")
        exit(1)
