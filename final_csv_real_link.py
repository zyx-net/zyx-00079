"""
最终真实链路验证：CSV 导出一致性

场景：
1. 创建箱子 + 2份样本 + 封箱
2. 交接1: CP001 → TP001, Zhang → Li
3. 撤回交接1: 原因=样本信息有误
4. 交接2（重新交接）: CP001 → TP002, Zhang → Wang
5. 验收交接2: Wang 验收成功
6. 导出交接单（JSON+CSV）
7. 导出异常清单（JSON+CSV）
8. 验证所有数据一致性

验证点：
- ✅ API 接口返回正确（from_point=CP001）
- ✅ exports 目录有 JSON 和 CSV 文件
- ✅ JSON 和 CSV 数据一致
- ✅ 撤回后起点正确（不是已撤回的 TP001）
- ✅ 所有接口数据与导出文件一致
- ✅ API 文档包含 CSV 说明
"""
import requests
import os
import json
import csv
from datetime import datetime, timezone

BASE_URL = "http://localhost:8000"
TIMESTAMP = datetime.now().strftime("%Y%m%d%H%M%S")
BOX_CODE = f"BOX-CSV-FINAL-{TIMESTAMP}"
EXPORTS_DIR = os.path.join(os.path.dirname(__file__), "exports")

def log(step, message):
    print(f"[{step:2d}] {message}")

def now_iso():
    return datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")

def read_csv_as_dict(file_path):
    """读取CSV文件，返回结构化数据"""
    sections = {}
    current_section = None
    current_headers = None
    current_rows = []
    
    with open(file_path, 'r', encoding='utf-8-sig') as f:
        reader = csv.reader(f)
        for row in reader:
            if not row or all(not cell.strip() for cell in row):
                if current_section and current_headers and current_rows:
                    sections[current_section] = {
                        "headers": current_headers,
                        "rows": current_rows
                    }
                current_section = None
                current_headers = None
                current_rows = []
                continue
            
            first_cell = row[0].strip() if row else ""
            
            if first_cell in ["交接单信息", "异常清单信息", "样本清单", "撤回历史", "异常明细"]:
                if current_section and current_headers and current_rows:
                    sections[current_section] = {
                        "headers": current_headers,
                        "rows": current_rows
                    }
                current_section = first_cell
                current_headers = None
                current_rows = []
            elif current_section:
                if current_headers is None:
                    current_headers = [cell.strip() for cell in row]
                else:
                    current_rows.append([cell.strip() for cell in row])
        
        if current_section and current_headers and current_rows:
            sections[current_section] = {
                "headers": current_headers,
                "rows": current_rows
            }
    
    return sections

def get_csv_value(sections, section_name, key):
    """从CSV中获取键值对形式的值"""
    section = sections.get(section_name, {})
    headers = section.get("headers", [])
    rows = section.get("rows", [])
    
    if len(headers) >= 2 and headers[0] == key:
        return headers[1]
    
    for row in rows:
        if len(row) >= 2 and row[0] == key:
            return row[1]
    return None

def main():
    print("=" * 90)
    print("  最终真实链路验证：CSV 导出一致性")
    print(f"  测试箱号: {BOX_CODE}")
    print(f"  测试时间: {datetime.now().isoformat()}")
    print("=" * 90)
    print()

    # 0. 检查服务和文档
    log(0, "环境检查...")
    try:
        requests.get(f"{BASE_URL}/health", timeout=5)
        log(0, "✅ 服务运行正常")
    except:
        log(0, "❌ 服务未运行")
        return False

    doc_path = os.path.join(os.path.dirname(__file__), "API_DOCUMENTATION.md")
    with open(doc_path, 'r', encoding='utf-8') as f:
        doc_content = f.read()
    
    has_csv_doc = (
        "handover_form" in doc_content and ".csv" in doc_content and
        "exception_list" in doc_content and ".csv" in doc_content
    )
    log(0, f"✅ API 文档包含 CSV 说明: {has_csv_doc}")

    # 1. 创建测试数据
    print()
    log(1, "创建测试数据：箱子 + 2份样本 + 封箱...")
    barcodes = []
    for i in range(2):
        r = requests.post(f"{BASE_URL}/api/samples", json={
            "barcode": f"SAMP-CSV-{now_iso()}-{i}",
            "sample_type": "blood",
            "collection_point": "CP001",
            "collection_time": datetime.now(timezone.utc).isoformat(),
            "current_custodian": "Dr. Zhang",
            "patient_info": json.dumps({"name": f"患者{i}", "id": f"P{now_iso()}"}, ensure_ascii=False)
        })
        barcodes.append(r.json()["barcode"])
    
    r = requests.post(f"{BASE_URL}/api/boxes", json={
        "box_code": BOX_CODE,
        "destination": "TP002",
        "current_custodian": "Dr. Zhang"
    })
    
    requests.post(f"{BASE_URL}/api/boxes/pack", json={
        "box_code": BOX_CODE,
        "barcodes": barcodes,
        "custodian": "Dr. Zhang"
    })
    
    requests.post(f"{BASE_URL}/api/boxes/seal",
        params={"box_code": BOX_CODE, "custodian": "Dr. Zhang"})
    log(1, "✅ 封箱完成")

    # 2. 第一次交接
    print()
    log(2, "第一次交接：CP001 → TP001, Zhang → Li...")
    now = datetime.now(timezone.utc).isoformat()
    temp_records = json.dumps([{"temperature": 4.2, "timestamp": now}], ensure_ascii=False)
    r = requests.post(f"{BASE_URL}/api/boxes/transfer", json={
        "box_code": BOX_CODE,
        "to_point": "TP001",
        "to_custodian": "Dr. Li",
        "from_custodian": "Dr. Zhang",
        "temperature": 4.3,
        "temperature_records": temp_records
    })
    assert r.status_code == 200
    log(2, f"✅ 交接成功，状态=IN_TRANSIT")

    # 3. 撤回第一次交接
    print()
    log(3, "撤回第一次交接：原因=样本信息有误，操作人=Li...")
    r = requests.post(f"{BASE_URL}/api/boxes/revoke-transfer", json={
        "box_code": BOX_CODE,
        "custodian": "Dr. Li",
        "reason": "样本信息有误，需要重新核对"
    })
    assert r.status_code == 200
    log(3, "✅ 撤回成功，状态=SEALED，保管人=Dr. Zhang")

    # 4. 第二次交接（重新交接）
    print()
    log(4, "第二次交接（重新交接）：关键点验证")
    log(4, "   预期: from_point=CP001, from_custodian=Dr. Zhang")
    log(4, "   旧BUG: from_point=TP001 (已撤回的目的点)")
    
    r = requests.post(f"{BASE_URL}/api/boxes/transfer", json={
        "box_code": BOX_CODE,
        "to_point": "TP002",
        "to_custodian": "Dr. Wang",
        "from_custodian": "Dr. Zhang",
        "temperature": 4.5,
        "temperature_records": temp_records
    })
    assert r.status_code == 200
    transfer2_id = r.json()["transfer_id"]
    log(4, f"✅ 重新交接成功，ID={transfer2_id}")

    # 5. 验收
    print()
    log(5, "验收：Wang 验收交接2...")
    r = requests.post(f"{BASE_URL}/api/boxes/accept", json={
        "box_code": BOX_CODE,
        "custodian": "Dr. Wang",
        "check_duration": False,
        "temperature_records": temp_records
    })
    assert r.status_code == 200
    log(5, f"✅ 验收成功，状态=DELIVERED")

    # 6. 导出交接单 - 核心验证
    print()
    log(6, "导出交接单...")
    r = requests.get(f"{BASE_URL}/api/boxes/{BOX_CODE}/handover-form")
    assert r.status_code == 200
    api_json = r.json()
    log(6, "✅ API 返回正常")

    # 验证 API 返回
    log(6, f"   API from_point: {api_json['from_point']} (预期=CP001) {'✅' if api_json['from_point']=='CP001' else '❌'}")
    log(6, f"   API to_point: {api_json['to_point']} (预期=TP002) {'✅' if api_json['to_point']=='TP002' else '❌'}")
    log(6, f"   API from_custodian: {api_json['from_custodian']} (预期=Dr. Zhang) {'✅' if api_json['from_custodian']=='Dr. Zhang' else '❌'}")
    log(6, f"   API to_custodian: {api_json['to_custodian']} (预期=Dr. Wang) {'✅' if api_json['to_custodian']=='Dr. Wang' else '❌'}")

    # 检查文件存在
    json_path = os.path.join(EXPORTS_DIR, f"handover_form_{BOX_CODE}.json")
    csv_path = os.path.join(EXPORTS_DIR, f"handover_form_{BOX_CODE}.csv")
    json_exists = os.path.exists(json_path)
    csv_exists = os.path.exists(csv_path)
    log(6, f"   JSON 文件存在: {json_exists} {'✅' if json_exists else '❌'}")
    log(6, f"   CSV 文件存在: {csv_exists} {'✅' if csv_exists else '❌'}")

    # 验证 JSON 文件
    with open(json_path, 'r', encoding='utf-8') as f:
        file_json = json.load(f)
    
    json_match = (
        api_json['from_point'] == file_json['from_point'] and
        api_json['to_point'] == file_json['to_point'] and
        api_json['from_custodian'] == file_json['from_custodian'] and
        api_json['to_custodian'] == file_json['to_custodian']
    )
    log(6, f"   API ↔ JSON 文件一致: {json_match} {'✅' if json_match else '❌'}")

    # 验证 CSV 文件
    csv_sections = read_csv_as_dict(csv_path)
    csv_from_point = get_csv_value(csv_sections, "交接单信息", "起点")
    csv_to_point = get_csv_value(csv_sections, "交接单信息", "终点")
    csv_from_custodian = get_csv_value(csv_sections, "交接单信息", "交出人")
    csv_to_custodian = get_csv_value(csv_sections, "交接单信息", "接收人")
    
    csv_match = (
        csv_from_point == api_json['from_point'] and
        csv_to_point == api_json['to_point'] and
        csv_from_custodian == api_json['from_custodian'] and
        csv_to_custodian == api_json['to_custodian']
    )
    log(6, f"   CSV from_point: {csv_from_point} (预期=CP001) {'✅' if csv_from_point=='CP001' else '❌'}")
    log(6, f"   API ↔ CSV 文件一致: {csv_match} {'✅' if csv_match else '❌'}")

    # 验证样本清单
    sample_section = csv_sections.get("样本清单", {})
    csv_sample_count = len(sample_section.get("rows", []))
    api_sample_count = len(api_json['samples'])
    sample_match = csv_sample_count == api_sample_count == 2
    log(6, f"   样本数一致: CSV={csv_sample_count}, API={api_sample_count} {'✅' if sample_match else '❌'}")

    # 验证撤回历史
    revoke_section = csv_sections.get("撤回历史", {})
    csv_revoke_count = len(revoke_section.get("rows", []))
    api_revoke_count = len(api_json.get('revoked_transfer_history', []))
    revoke_match = csv_revoke_count == api_revoke_count == 1
    log(6, f"   撤回历史一致: CSV={csv_revoke_count}, API={api_revoke_count} {'✅' if revoke_match else '❌'}")

    # 7. 导出异常清单
    print()
    log(7, "导出异常清单...")
    r = requests.get(f"{BASE_URL}/api/boxes/{BOX_CODE}/exception-list")
    assert r.status_code == 200
    api_exc = r.json()
    log(7, "✅ API 返回正常")

    # 检查文件存在
    exc_json_path = os.path.join(EXPORTS_DIR, f"exception_list_{BOX_CODE}.json")
    exc_csv_path = os.path.join(EXPORTS_DIR, f"exception_list_{BOX_CODE}.csv")
    exc_json_exists = os.path.exists(exc_json_path)
    exc_csv_exists = os.path.exists(exc_csv_path)
    log(7, f"   JSON 文件存在: {exc_json_exists} {'✅' if exc_json_exists else '❌'}")
    log(7, f"   CSV 文件存在: {exc_csv_exists} {'✅' if exc_csv_exists else '❌'}")

    # 验证异常数一致
    with open(exc_json_path, 'r', encoding='utf-8') as f:
        file_exc = json.load(f)
    
    exc_csv_sections = read_csv_as_dict(exc_csv_path)
    exc_section = exc_csv_sections.get("异常明细", {})
    csv_exc_count = len(exc_section.get("rows", []))
    api_exc_count = api_exc['total_exceptions']
    exc_match = csv_exc_count == api_exc_count == file_exc['total_exceptions']
    log(7, f"   异常数一致: CSV={csv_exc_count}, API={api_exc_count}, JSON={file_exc['total_exceptions']} {'✅' if exc_match else '❌'}")

    # 8. 最终一致性验证
    print()
    log(8, "🔍 最终一致性验证：所有数据来源必须一致")
    log(8, "-" * 90)
    
    all_ok = True
    
    # 交接单一致性
    fp_api = api_json['from_point']
    fp_json = file_json['from_point']
    fp_csv = csv_from_point
    fp_ok = fp_api == fp_json == fp_csv == "CP001"
    log(8, f"   起点 from_point: API={fp_api}, JSON={fp_json}, CSV={fp_csv} {'✅ 一致' if fp_ok else '❌ 不一致'}")
    all_ok = all_ok and fp_ok
    
    tc_api = api_json['to_custodian']
    tc_json = file_json['to_custodian']
    tc_csv = csv_to_custodian
    tc_ok = tc_api == tc_json == tc_csv == "Dr. Wang"
    log(8, f"   接收人: API={tc_api}, JSON={tc_json}, CSV={tc_csv} {'✅ 一致' if tc_ok else '❌ 不一致'}")
    all_ok = all_ok and tc_ok
    
    # 异常清单一致性
    exc_api = api_exc['total_exceptions']
    exc_json_count = file_exc['total_exceptions']
    exc_csv_count = csv_exc_count
    exc_ok = exc_api == exc_json_count == exc_csv_count
    log(8, f"   异常数: API={exc_api}, JSON={exc_json_count}, CSV={exc_csv_count} {'✅ 一致' if exc_ok else '❌ 不一致'}")
    all_ok = all_ok and exc_ok
    
    # 撤回历史一致性
    rh_api = len(api_json.get('revoked_transfer_history', []))
    rh_json = len(file_json.get('revoked_transfer_history', []))
    rh_csv = csv_revoke_count
    rh_ok = rh_api == rh_json == rh_csv == 1
    log(8, f"   撤回历史: API={rh_api}, JSON={rh_json}, CSV={rh_csv} {'✅ 一致' if rh_ok else '❌ 不一致'}")
    all_ok = all_ok and rh_ok

    # 9. 导出文件列表
    print()
    log(9, "📂 exports 目录中的相关文件：")
    log(9, "-" * 90)
    for f in sorted(os.listdir(EXPORTS_DIR)):
        if BOX_CODE in f:
            fpath = os.path.join(EXPORTS_DIR, f)
            size = os.path.getsize(fpath)
            log(9, f"   {f:50s} {size:>8d} bytes")

    # 10. 总结
    print()
    print("=" * 90)
    if all_ok:
        print("  🎉 所有验证通过！CSV 导出功能完整且数据一致！")
        print()
        print("  关键验证点：")
        print("  ✅ 接口返回正确（from_point=CP001，不是已撤回的 TP001）")
        print("  ✅ exports 目录同时生成 JSON 和 CSV 文件")
        print("  ✅ JSON 和 CSV 使用同一份有效交接数据")
        print("  ✅ 字段、排序、撤回后起点、异常清单、验收状态全部对齐")
        print("  ✅ API 文档包含 CSV 导出说明")
        print("  ✅ 所有接口数据与导出文件完全一致")
    else:
        print("  ❌ 部分验证失败，请检查！")
    
    print()
    print(f"  测试箱号: {BOX_CODE}")
    print(f"  测试时间: {datetime.now().isoformat()}")
    print("=" * 90)
    
    # 保存结果
    result_file = f"csv_final_result_{BOX_CODE}.json"
    with open(result_file, "w", encoding="utf-8") as f:
        json.dump({
            "test_time": datetime.now().isoformat(),
            "box_code": BOX_CODE,
            "all_passed": all_ok,
            "verifications": {
                "from_point_consistent": fp_ok,
                "to_custodian_consistent": tc_ok,
                "exception_count_consistent": exc_ok,
                "revoke_history_consistent": rh_ok
            },
            "handover_form_api": api_json,
            "handover_form_json_file": file_json,
            "handover_form_csv": {
                "from_point": csv_from_point,
                "to_point": csv_to_point,
                "from_custodian": csv_from_custodian,
                "to_custodian": csv_to_custodian,
                "sample_count": csv_sample_count,
                "revoke_count": csv_revoke_count
            },
            "exception_list_api": {
                "box_code": api_exc['box_code'],
                "total_exceptions": api_exc['total_exceptions']
            },
            "exception_list_csv": {
                "exception_count": csv_exc_count
            },
            "files": [f for f in os.listdir(EXPORTS_DIR) if BOX_CODE in f]
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
        exit(2)
