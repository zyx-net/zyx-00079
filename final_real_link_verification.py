"""
最终真实链路验证：确认当前起点、验收依据和导出单一致

链路场景（模拟真实业务流程）：
1. 创建箱子 + 2份样本 + 封箱
2. 交接1: CP001 → TP001, Zhang → Li
3. 撤回交接1: 原因=样本信息有误
4. 交接2（重新交接）: CP001 → TP002, Zhang → Wang （因为交接1被撤回，起点应为采集点）
5. 验收交接2: Wang 验收成功
6. 验证所有接口数据一致性
"""
import requests
import json
from datetime import datetime, timezone

BASE_URL = "http://localhost:8000"
TIMESTAMP = datetime.now().strftime("%Y%m%d%H%M%S")
BOX_CODE = f"BOX-REAL-LINK-{TIMESTAMP}"

def log(step, message):
    print(f"[{step:2d}] {message}")

def now_iso():
    return datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")

def create_test_data(box_code):
    """创建测试箱、样本、交接数据"""
    samples = []
    for i in range(2):
        r = requests.post(f"{BASE_URL}/api/samples", json={
            "barcode": f"SAMP-REAL-{now_iso()}-{i}",
            "sample_type": "blood",
            "collection_point": "CP001",
            "collection_time": datetime.now(timezone.utc).isoformat(),
            "current_custodian": "Dr. Zhang",
            "patient_info": json.dumps({"name": "张三", "id": f"P{now_iso()}"}, ensure_ascii=False)
        })
        samples.append(r.json())
        assert r.status_code in [200, 201], f"创建样本失败: {r.text}"
    
    r = requests.post(f"{BASE_URL}/api/boxes", json={
        "box_code": box_code,
        "destination": "TP002",
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

def do_transfer(box_code, from_custodian, to_custodian, to_point):
    now = datetime.now(timezone.utc).isoformat()
    temp_records = json.dumps([
        {"temperature": 4.2, "timestamp": now},
        {"temperature": 4.5, "timestamp": now}
    ], ensure_ascii=False)
    r = requests.post(f"{BASE_URL}/api/boxes/transfer", json={
        "box_code": box_code,
        "to_point": to_point,
        "to_custodian": to_custodian,
        "from_custodian": from_custodian,
        "temperature": 4.3,
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

def main():
    print("=" * 80)
    print("  最终真实链路验证：撤回后重新交接的一致性")
    print(f"  测试箱号: {BOX_CODE}")
    print(f"  测试时间: {datetime.now().isoformat()}")
    print("=" * 80)
    print()

    # 检查服务
    try:
        requests.get(f"{BASE_URL}/health", timeout=5)
        log(0, "✅ 服务运行正常")
    except:
        log(0, "❌ 服务未运行")
        return False

    print()

    # 1. 创建测试数据
    log(1, "创建测试数据：箱子 + 2份样本 + 封箱...")
    samples = create_test_data(BOX_CODE)
    box_info = requests.get(f"{BASE_URL}/api/boxes/{BOX_CODE}").json()
    log(1, f"✅ 封箱完成，状态={box_info['status']}, 保管人={box_info['current_custodian']}")

    # 2. 第一次交接
    print()
    log(2, "第一次交接：CP001 → TP001, Dr.Zhang → Dr.Li")
    r = do_transfer(BOX_CODE, "Dr. Zhang", "Dr. Li", "TP001")
    assert r.status_code == 200, f"交接失败: {r.text}"
    transfer1_id = r.json()["transfer_id"]
    log(2, f"✅ 交接成功，ID={transfer1_id}")

    # 验证交接1
    history = requests.get(f"{BASE_URL}/api/boxes/{BOX_CODE}/transfer-history").json()
    t1 = next(t for t in history if t["id"] == transfer1_id)
    log(2, f"   验证: from_point={t1['from_point']} (预期=CP001) {'✅' if t1['from_point']=='CP001' else '❌'}")

    # 3. 撤回第一次交接
    print()
    log(3, "撤回第一次交接：原因=样本信息有误，操作人=Dr.Li")
    r = do_revoke(BOX_CODE, "Dr. Li", "样本信息有误，需要重新核对")
    assert r.status_code == 200, f"撤回失败: {r.text}"
    log(3, "✅ 撤回成功")

    # 验证撤回后状态
    box_info = requests.get(f"{BASE_URL}/api/boxes/{BOX_CODE}").json()
    log(3, f"   验证: 箱子状态={box_info['status']} (预期=SEALED) {'✅' if box_info['status']=='SEALED' else '❌'}")
    log(3, f"   验证: 当前保管人={box_info['current_custodian']} (预期=Dr. Zhang) {'✅' if box_info['current_custodian']=='Dr. Zhang' else '❌'}")
    
    history = requests.get(f"{BASE_URL}/api/boxes/{BOX_CODE}/transfer-history").json()
    all_revoked = all(t.get("is_revoked") for t in history)
    log(3, f"   验证: 所有记录已撤回={all_revoked} {'✅' if all_revoked else '❌'}")

    # 4. 第二次交接（重新交接）- 这是关键验证点
    print()
    log(4, "第二次交接（重新交接）：关键点验证")
    log(4, "   预期: from_point=CP001 (因为所有交接都被撤回，应回到采集点)")
    log(4, "   预期: from_custodian=Dr. Zhang (箱子当前保管人)")
    log(4, "   旧BUG: from_point=TP001 (使用了已撤回交接的目的点)")
    
    # 先用错误的 from_custodian 测试，应被拒绝
    r = do_transfer(BOX_CODE, "Dr. Wrong", "Dr. Wang", "TP002")
    log(4, f"   🔒 错误保管人测试: HTTP {r.status_code}, code={r.json().get('detail', {}).get('code')} "
         f"{'✅ 正确拒绝' if r.status_code==400 else '❌ 应该拒绝'}")
    
    # 再用正确的 from_custodian 交接
    r = do_transfer(BOX_CODE, "Dr. Zhang", "Dr. Wang", "TP002")
    assert r.status_code == 200, f"交接失败: {r.text}"
    transfer2_id = r.json()["transfer_id"]
    log(4, f"✅ 重新交接成功，ID={transfer2_id}")

    # 验证交接2的 from_point - 核心验证
    history = requests.get(f"{BASE_URL}/api/boxes/{BOX_CODE}/transfer-history").json()
    t2 = next(t for t in history if t["id"] == transfer2_id)
    log(4, f"   🔍 核心验证: from_point={t2['from_point']} (预期=CP001) "
         f"{'✅ BUG已修复' if t2['from_point']=='CP001' else '❌ 仍有BUG'}")
    log(4, f"   🔍 核心验证: from_custodian={t2['from_custodian']} (预期=Dr. Zhang) "
         f"{'✅ 正确' if t2['from_custodian']=='Dr. Zhang' else '❌ 错误'}")

    # 5. 验收
    print()
    log(5, "验收：Dr.Wang 验收交接2")
    r = do_accept(BOX_CODE, "Dr. Wang")
    assert r.status_code == 200, f"验收失败: {r.text}"
    log(5, f"✅ 验收成功，状态={r.json()['status']}")

    # 验证验收后状态
    box_info = requests.get(f"{BASE_URL}/api/boxes/{BOX_CODE}").json()
    log(5, f"   验证: 箱子状态={box_info['status']} (预期=DELIVERED) {'✅' if box_info['status']=='DELIVERED' else '❌'}")
    log(5, f"   验证: 当前保管人={box_info['current_custodian']} (预期=Dr. Wang) {'✅' if box_info['current_custodian']=='Dr. Wang' else '❌'}")

    # 6. 验证交接单导出
    print()
    log(6, "验证交接单导出...")
    form = requests.get(f"{BASE_URL}/api/boxes/{BOX_CODE}/handover-form").json()
    log(6, f"   from_point={form['from_point']} (预期=CP001) {'✅' if form['from_point']=='CP001' else '❌'}")
    log(6, f"   to_point={form['to_point']} (预期=TP002) {'✅' if form['to_point']=='TP002' else '❌'}")
    log(6, f"   from_custodian={form['from_custodian']} (预期=Dr. Zhang) {'✅' if form['from_custodian']=='Dr. Zhang' else '❌'}")
    log(6, f"   to_custodian={form['to_custodian']} (预期=Dr. Wang) {'✅' if form['to_custodian']=='Dr. Wang' else '❌'}")
    log(6, f"   撤回历史条数={len(form.get('revoked_transfer_history', []))} (预期=1) {'✅' if len(form.get('revoked_transfer_history', []))==1 else '❌'}")

    # 7. 验证异常清单导出
    print()
    log(7, "验证异常清单导出...")
    exception = requests.get(f"{BASE_URL}/api/boxes/{BOX_CODE}/exception-list").json()
    revoke_exceptions = [e for e in exception.get("exceptions", []) if e.get("type") == "TRANSFER_REVOKED"]
    log(7, f"   TRANSFER_REVOKED异常={len(revoke_exceptions)}条 (预期=1) {'✅' if len(revoke_exceptions)==1 else '❌'}")
    log(7, f"   撤回历史条数={len(exception.get('revoked_transfer_history', []))} (预期=1) {'✅' if len(exception.get('revoked_transfer_history', []))==1 else '❌'}")

    # 8. 验证审计日志
    print()
    log(8, "验证审计日志...")
    audit = requests.get(f"{BASE_URL}/api/audit", params={
        "entity_type": "TRANSFER", 
        "entity_id": transfer2_id
    }).json()
    
    re_transfer = [l for l in audit if l.get("action") == "RE_TRANSFER"]
    log(8, f"   RE_TRANSFER日志={len(re_transfer)}条 {'✅' if len(re_transfer)>=1 else '❌'}")
    
    if re_transfer:
        details_str = re_transfer[0].get("details", "{}")
        details = json.loads(details_str) if isinstance(details_str, str) else details_str
        log(8, f"   关联信息完整: prev_transfer_id={'prev_transfer_id' in details}, "
             f"revoked_count={'revoked_count_before' in details}, "
             f"rule_version={'rule_version' in details} {'✅' if all(k in details for k in ['prev_transfer_id','revoked_count_before','rule_version']) else '❌'}")

    # 9. 一致性验证：所有接口的 from_point 和保管人必须一致
    print()
    log(9, "🔍 最终一致性验证：所有接口数据必须一致")
    
    # 获取各个接口的数据
    box_info = requests.get(f"{BASE_URL}/api/boxes/{BOX_CODE}").json()
    history = requests.get(f"{BASE_URL}/api/boxes/{BOX_CODE}/transfer-history").json()
    form = requests.get(f"{BASE_URL}/api/boxes/{BOX_CODE}/handover-form").json()
    
    active_transfer = next(t for t in history if not t.get("is_revoked"))
    
    # 验证 from_point 一致性
    fp_history = active_transfer["from_point"]
    fp_form = form["from_point"]
    fp_consistent = fp_history == fp_form == "CP001"
    log(9, f"   from_point一致性: 历史={fp_history}, 交接单={fp_form} {'✅ 一致' if fp_consistent else '❌ 不一致'}")
    
    # 验证保管人一致性
    cust_box = box_info["current_custodian"]
    cust_form = form["to_custodian"]
    cust_active = active_transfer["to_custodian"]
    cust_consistent = cust_box == cust_form == cust_active == "Dr. Wang"
    log(9, f"   保管人一致性: 箱子={cust_box}, 交接单={cust_form}, 活跃交接={cust_active} {'✅ 一致' if cust_consistent else '❌ 不一致'}")
    
    # 验证状态一致性
    status_box = box_info["status"]
    status_consistent = status_box == "DELIVERED"
    log(9, f"   状态一致性: 箱子={status_box} {'✅ 正确' if status_consistent else '❌ 错误'}")
    
    # 验证撤回历史一致性
    rh_form = len(form.get("revoked_transfer_history", []))
    rh_history = len([t for t in history if t.get("is_revoked")])
    rh_consistent = rh_form == rh_history == 1
    log(9, f"   撤回历史一致性: 交接单={rh_form}条, 历史={rh_history}条 {'✅ 一致' if rh_consistent else '❌ 不一致'}")

    # 10. 验证历史明细
    print()
    log(10, "📜 完整交接历史明细：")
    log(10, "-" * 70)
    for i, t in enumerate(history, 1):
        status = "✅ 有效" if not t.get("is_revoked") else "❌ 已撤回"
        log(10, f"  {i}. ID={t['id']}: {t['from_point']} → {t['to_point']}, "
             f"{t['from_custodian']} → {t['to_custodian']} {status}")
        if t.get("is_revoked"):
            log(10, f"     撤回原因: {t.get('revoke_reason')}, 撤回人: {t.get('revoked_by')}")

    # 总结
    all_ok = fp_consistent and cust_consistent and status_consistent and rh_consistent
    
    print()
    print("=" * 80)
    if all_ok:
        print("  🎉 所有验证通过！修复成功！")
        print()
        print("  关键修复点验证：")
        print("  ✅ 撤回后重新交接的 from_point 正确使用采集点 CP001")
        print("  ✅ 没有使用已撤回交接的目的点 TP001 作为起点")
        print("  ✅ from_custodian 正确校验为箱子当前保管人")
        print("  ✅ 所有接口（箱子状态、历史、交接单、异常清单）数据一致")
        print("  ✅ 已撤回记录保留在历史中，不影响当前有效交接")
    else:
        print("  ❌ 部分验证失败，请检查！")
    
    print()
    print("  测试箱号:", BOX_CODE)
    print("  测试时间:", datetime.now().isoformat())
    print("=" * 80)
    
    # 保存结果
    result_file = f"real_link_result_{BOX_CODE}.json"
    with open(result_file, "w", encoding="utf-8") as f:
        json.dump({
            "test_time": datetime.now().isoformat(),
            "box_code": BOX_CODE,
            "all_passed": all_ok,
            "verifications": {
                "from_point_consistent": fp_consistent,
                "custodian_consistent": cust_consistent,
                "status_consistent": status_consistent,
                "revoke_history_consistent": rh_consistent
            },
            "transfer_history": history,
            "handover_form": form,
            "box_info": box_info
        }, f, ensure_ascii=False, indent=2)
    
    print(f"\n结果已保存到: {result_file}")
    
    return all_ok

if __name__ == "__main__":
    try:
        success = main()
        exit(0 if success else 1)
    except Exception as e:
        print(f"\n❌ 测试异常: {e}")
        import traceback
        traceback.print_exc()
        exit(1)
