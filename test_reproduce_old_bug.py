"""
复现旧问题测试：验证撤回后重新交接时，from_point 是否错误地使用了已撤回交接的目的点

预期正确行为：
- 所有交接都被撤回后，重新交接的 from_point 应该是采集点 CP001
- from_custodian 应该是当前保管人（封箱后的保管人）

旧错误行为：
- from_point 错误地使用了已撤回交接的 to_point（TP001）
"""
import requests
import json
from datetime import datetime, timezone

BASE_URL = "http://localhost:8000"
TIMESTAMP = datetime.now().strftime("%Y%m%d%H%M%S")
BOX_CODE = f"BOX-REPRODUCE-BUG-{TIMESTAMP}"

def now_iso():
    return datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")

def create_test_data(box_code):
    """创建测试箱、样本、交接数据"""
    samples = []
    for i in range(2):
        r = requests.post(f"{BASE_URL}/api/samples", json={
            "barcode": f"SAMP-REPRO-{now_iso()}-{i}",
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

def main():
    print("=" * 70)
    print("  复现旧问题测试：撤回后重新交接的 from_point 正确性")
    print(f"  测试箱号: {BOX_CODE}")
    print("=" * 70)
    print()

    # 1. 创建测试数据
    print("[1/5] 创建测试数据...")
    samples = create_test_data(BOX_CODE)
    print("      ✅ 箱子+样本+封箱完成")

    # 2. 第一次交接
    print("[2/5] 第一次交接: CP001 → TP001, Dr.Zhang → Dr.Li")
    r = do_transfer(BOX_CODE, "Dr. Zhang", "Dr. Li", "TP001")
    assert r.status_code == 200, f"第一次交接失败: {r.text}"
    transfer1_id = r.json()["transfer_id"]
    print(f"      ✅ 交接成功, ID={transfer1_id}")

    # 验证第一次交接的 from_point
    history = requests.get(f"{BASE_URL}/api/boxes/{BOX_CODE}/transfer-history").json()
    t1 = next(t for t in history if t["id"] == transfer1_id)
    print(f"      第一次交接 from_point: {t1['from_point']} (预期: CP001)")
    assert t1["from_point"] == "CP001", f"第一次交接 from_point 错误: {t1['from_point']}"

    # 3. 撤回第一次交接
    print("[3/5] 撤回第一次交接...")
    r = do_revoke(BOX_CODE, "Dr. Li", "样本信息有误")
    assert r.status_code == 200, f"撤回失败: {r.text}"
    print("      ✅ 撤回成功")

    # 验证撤回后所有记录都是撤回状态
    history = requests.get(f"{BASE_URL}/api/boxes/{BOX_CODE}/transfer-history").json()
    all_revoked = all(t.get("is_revoked") for t in history)
    print(f"      所有记录已撤回: {all_revoked}")
    assert all_revoked == True, "还有未撤回的记录"

    # 验证箱子状态已回退
    box_info = requests.get(f"{BASE_URL}/api/boxes/{BOX_CODE}").json()
    print(f"      箱子状态: {box_info['status']} (预期: SEALED)")
    print(f"      当前保管人: {box_info['current_custodian']} (预期: Dr. Zhang)")
    assert box_info["status"] == "SEALED", f"箱子状态错误: {box_info['status']}"
    assert box_info["current_custodian"] == "Dr. Zhang", f"保管人错误: {box_info['current_custodian']}"

    # 4. 第二次交接（重新交接）- 这是关键测试点
    print("\n[4/5] 第二次交接（重新交接）: 关键点验证")
    print("      预期: from_point=CP001, from_custodian=Dr.Zhang")
    print("      旧BUG: from_point=TP001（使用了已撤回交接的目的点）")
    r = do_transfer(BOX_CODE, "Dr. Zhang", "Dr. Wang", "TP002")
    
    if r.status_code != 200:
        print(f"      ❌ 交接失败: {r.status_code}, {r.text}")
        return False
    
    transfer2_id = r.json()["transfer_id"]
    print(f"      ✅ 交接成功, ID={transfer2_id}")

    # 验证第二次交接的 from_point - 这是复现BUG的关键
    history = requests.get(f"{BASE_URL}/api/boxes/{BOX_CODE}/transfer-history").json()
    t2 = next(t for t in history if t["id"] == transfer2_id)
    print(f"\n      🔍 关键验证: 第二次交接 from_point = {t2['from_point']}")
    print(f"                        预期正确值 = CP001")
    print(f"                        旧BUG错误值 = TP001")

    if t2["from_point"] == "TP001":
        print("\n      ❌ BUG 复现成功！from_point 错误地使用了已撤回交接的目的点")
        print(f"         from_point={t2['from_point']}, 应该是 CP001")
        bug_reproduced = True
    elif t2["from_point"] == "CP001":
        print("\n      ✅ BUG 已修复！from_point 正确使用了采集点")
        bug_reproduced = False
    else:
        print(f"\n      ❓ 意外值: from_point={t2['from_point']}")
        bug_reproduced = True

    # 5. 验证交接单导出
    print("\n[5/5] 验证交接单导出...")
    form = requests.get(f"{BASE_URL}/api/boxes/{BOX_CODE}/handover-form").json()
    print(f"      交接单 from_point: {form['from_point']}")
    print(f"      交接单 to_point: {form['to_point']}")
    print(f"      交接单 from_custodian: {form['from_custodian']}")
    print(f"      交接单 to_custodian: {form['to_custodian']}")
    print(f"      撤回历史条数: {len(form.get('revoked_transfer_history', []))}")

    if form["from_point"] == "TP001":
        print("      ❌ 交接单导出也存在同样的 BUG")
    elif form["from_point"] == "CP001":
        print("      ✅ 交接单导出正确")

    # 打印完整历史
    print("\n" + "=" * 70)
    print("  完整交接历史:")
    print("-" * 70)
    for t in history:
        status = "❌ 已撤回" if t.get("is_revoked") else "✅ 有效"
        print(f"  ID={t['id']}: {t['from_point']} → {t['to_point']}, "
              f"{t['from_custodian']} → {t['to_custodian']} {status}")
        if t.get("is_revoked"):
            print(f"          撤回原因: {t.get('revoke_reason')}, 撤回人: {t.get('revoked_by')}")

    print("\n" + "=" * 70)
    if bug_reproduced:
        print("  🔴 测试结果: BUG 已复现，需要修复！")
        print("     问题: 撤回后重新交接时，from_point 使用了已撤回交接的目的点")
        print("     修复方向: from_point 应只基于有效（未撤回）交接记录")
        return False
    else:
        print("  🟢 测试结果: BUG 已修复，所有验证通过！")
        return True

if __name__ == "__main__":
    try:
        success = main()
        exit(0 if success else 1)
    except Exception as e:
        print(f"\n❌ 测试异常: {e}")
        import traceback
        traceback.print_exc()
        exit(1)
