"""
CSV 导出回归测试

覆盖场景：
1. 场景1: 正常交接 - JSON/CSV 同时导出，数据一致
2. 场景2: 撤回后重新交接 - 导出起点正确（使用采集点）
3. 场景3: 多份样本 - CSV 样本清单正确
4. 场景4: 有撤回历史 - CSV 撤回历史正确
5. 场景5: 无交接记录 - 导出正确（使用箱子信息）
6. 场景6: 异常清单导出 - JSON/CSV 数据一致
7. 场景7: API 文档包含 CSV 说明
"""
import requests
import os
import json
import csv
from datetime import datetime, timezone

BASE_URL = "http://localhost:8000"
TIMESTAMP = datetime.now().strftime("%Y%m%d%H%M%S")
EXPORTS_DIR = os.path.join(os.path.dirname(__file__), "exports")

def log(step, message):
    print(f"[{step:2d}] {message}")

def now_iso():
    return datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")

def create_samples(count, collection_point="CP001", custodian="Dr. Zhang"):
    barcodes = []
    for i in range(count):
        barcode = f"SAMP-CSV-{now_iso()}-{i}"
        r = requests.post(f"{BASE_URL}/api/samples", json={
            "barcode": barcode,
            "sample_type": "blood",
            "collection_point": collection_point,
            "collection_time": datetime.now(timezone.utc).isoformat(),
            "current_custodian": custodian,
            "patient_info": json.dumps({"name": f"患者{i}", "id": f"P{now_iso()}"}, ensure_ascii=False)
        })
        assert r.status_code in [200, 201], f"创建样本失败: {r.text}"
        barcodes.append(barcode)
    return barcodes

def create_box(box_code, destination="TP001", custodian="Dr. Zhang"):
    r = requests.post(f"{BASE_URL}/api/boxes", json={
        "box_code": box_code,
        "destination": destination,
        "current_custodian": custodian
    })
    assert r.status_code in [200, 201], f"创建箱子失败: {r.text}"

def pack_samples(box_code, barcodes, custodian="Dr. Zhang"):
    r = requests.post(f"{BASE_URL}/api/boxes/pack", json={
        "box_code": box_code,
        "barcodes": barcodes,
        "custodian": custodian
    })
    assert r.status_code == 200, f"装样本失败: {r.text}"

def seal_box(box_code, custodian="Dr. Zhang"):
    r = requests.post(f"{BASE_URL}/api/boxes/seal",
        params={"box_code": box_code, "custodian": custodian})
    assert r.status_code == 200, f"封箱失败: {r.text}"

def do_transfer(box_code, from_custodian, to_custodian, to_point):
    now = datetime.now(timezone.utc).isoformat()
    temp_records = json.dumps([
        {"temperature": 4.2, "timestamp": now}
    ], ensure_ascii=False)
    r = requests.post(f"{BASE_URL}/api/boxes/transfer", json={
        "box_code": box_code,
        "to_point": to_point,
        "to_custodian": to_custodian,
        "from_custodian": from_custodian,
        "temperature": 4.3,
        "temperature_records": temp_records
    })
    assert r.status_code == 200, f"交接失败: {r.text}"
    return r.json()

def do_revoke(box_code, custodian, reason):
    r = requests.post(f"{BASE_URL}/api/boxes/revoke-transfer", json={
        "box_code": box_code,
        "custodian": custodian,
        "reason": reason
    })
    assert r.status_code == 200, f"撤回失败: {r.text}"
    return r.json()

def clean_files(box_code):
    """清理可能存在的旧文件"""
    for prefix in ["handover_form", "exception_list"]:
        for ext in [".json", ".csv"]:
            path = os.path.join(EXPORTS_DIR, f"{prefix}_{box_code}{ext}")
            if os.path.exists(path):
                os.remove(path)

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
    
    # 先检查 headers（第一行键值对）
    if len(headers) >= 2 and headers[0] == key:
        return headers[1]
    
    # 再检查 rows
    for row in rows:
        if len(row) >= 2 and row[0] == key:
            return row[1]
    return None

def run_test(test_name, test_func):
    """运行单个测试并返回结果"""
    print(f"\n{'=' * 80}")
    print(f"  🧪 {test_name}")
    print("=" * 80)
    try:
        result = test_func()
        if result:
            print(f"  ✅ 通过")
        else:
            print(f"  ❌ 失败")
        return result
    except Exception as e:
        print(f"  ❌ 异常: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_scenario_1():
    """场景1: 正常交接 - JSON/CSV 同时导出，数据一致"""
    box_code = f"BOX-CSV-S1-{TIMESTAMP}"
    log(1, f"测试箱号: {box_code}")
    
    clean_files(box_code)
    barcodes = create_samples(2)
    create_box(box_code)
    pack_samples(box_code, barcodes)
    seal_box(box_code)
    do_transfer(box_code, "Dr. Zhang", "Dr. Li", "TP001")
    
    r = requests.get(f"{BASE_URL}/api/boxes/{box_code}/handover-form")
    assert r.status_code == 200
    json_data = r.json()
    
    json_path = os.path.join(EXPORTS_DIR, f"handover_form_{box_code}.json")
    csv_path = os.path.join(EXPORTS_DIR, f"handover_form_{box_code}.csv")
    
    # 验证文件存在
    assert os.path.exists(json_path), "JSON 文件不存在"
    assert os.path.exists(csv_path), "CSV 文件不存在"
    log(2, "✅ JSON 和 CSV 文件都存在")
    
    # 读取 JSON 文件
    with open(json_path, 'r', encoding='utf-8') as f:
        json_file_data = json.load(f)
    
    # 验证 JSON 响应和文件一致
    assert json_data["from_point"] == json_file_data["from_point"]
    assert json_data["to_point"] == json_file_data["to_point"]
    assert json_data["from_custodian"] == json_file_data["from_custodian"]
    assert json_data["to_custodian"] == json_file_data["to_custodian"]
    log(3, "✅ API 响应与 JSON 文件一致")
    
    # 读取 CSV 并验证
    csv_sections = read_csv_as_dict(csv_path)
    assert "交接单信息" in csv_sections, "CSV 缺少交接单信息"
    
    csv_from_point = get_csv_value(csv_sections, "交接单信息", "起点")
    csv_to_point = get_csv_value(csv_sections, "交接单信息", "终点")
    csv_from_custodian = get_csv_value(csv_sections, "交接单信息", "交出人")
    csv_to_custodian = get_csv_value(csv_sections, "交接单信息", "接收人")
    
    assert csv_from_point == json_data["from_point"], f"CSV起点={csv_from_point} != JSON起点={json_data['from_point']}"
    assert csv_to_point == json_data["to_point"], f"CSV终点={csv_to_point} != JSON终点={json_data['to_point']}"
    assert csv_from_custodian == json_data["from_custodian"], f"CSV交出人={csv_from_custodian} != JSON交出人={json_data['from_custodian']}"
    assert csv_to_custodian == json_data["to_custodian"], f"CSV接收人={csv_to_custodian} != JSON接收人={json_data['to_custodian']}"
    log(4, "✅ CSV 与 JSON 数据一致")
    
    # 验证样本清单
    assert "样本清单" in csv_sections, "CSV 缺少样本清单"
    sample_section = csv_sections["样本清单"]
    assert len(sample_section["rows"]) == 2, f"CSV样本数={len(sample_section['rows'])} != 2"
    assert "样本条码" in sample_section["headers"]
    log(5, "✅ CSV 样本清单正确")
    
    return True

def test_scenario_2():
    """场景2: 撤回后重新交接 - 导出起点正确（使用采集点）"""
    box_code = f"BOX-CSV-S2-{TIMESTAMP}"
    log(1, f"测试箱号: {box_code}")
    
    clean_files(box_code)
    barcodes = create_samples(2, collection_point="CP001")
    create_box(box_code, destination="TP002")
    pack_samples(box_code, barcodes)
    seal_box(box_code)
    
    # 交接1: CP001 → TP001, Zhang → Li
    do_transfer(box_code, "Dr. Zhang", "Dr. Li", "TP001")
    
    # 撤回交接1
    do_revoke(box_code, "Dr. Li", "样本信息有误")
    
    # 交接2（重新交接）: CP001 → TP002, Zhang → Wang
    do_transfer(box_code, "Dr. Zhang", "Dr. Wang", "TP002")
    
    # 导出
    r = requests.get(f"{BASE_URL}/api/boxes/{box_code}/handover-form")
    assert r.status_code == 200
    json_data = r.json()
    
    # 验证 from_point 是采集点 CP001，不是已撤回的 TP001
    assert json_data["from_point"] == "CP001", f"from_point={json_data['from_point']} != CP001"
    assert json_data["to_point"] == "TP002"
    assert json_data["from_custodian"] == "Dr. Zhang"
    assert json_data["to_custodian"] == "Dr. Wang"
    log(2, "✅ API 响应：起点正确使用 CP001，不是已撤回的 TP001")
    
    # 验证 JSON 文件
    json_path = os.path.join(EXPORTS_DIR, f"handover_form_{box_code}.json")
    with open(json_path, 'r', encoding='utf-8') as f:
        json_file_data = json.load(f)
    assert json_file_data["from_point"] == "CP001"
    log(3, "✅ JSON 文件：起点正确使用 CP001")
    
    # 验证 CSV 文件
    csv_path = os.path.join(EXPORTS_DIR, f"handover_form_{box_code}.csv")
    csv_sections = read_csv_as_dict(csv_path)
    csv_from_point = get_csv_value(csv_sections, "交接单信息", "起点")
    assert csv_from_point == "CP001", f"CSV起点={csv_from_point} != CP001"
    log(4, "✅ CSV 文件：起点正确使用 CP001")
    
    # 验证撤回历史
    assert "撤回历史" in csv_sections, "CSV 缺少撤回历史"
    revoke_section = csv_sections["撤回历史"]
    assert len(revoke_section["rows"]) == 1, f"撤回历史数={len(revoke_section['rows'])} != 1"
    log(5, "✅ CSV 撤回历史正确")
    
    # 验证 JSON 中的撤回历史
    assert json_data["revoked_transfer_history"] is not None
    assert len(json_data["revoked_transfer_history"]) == 1
    log(6, "✅ JSON 撤回历史正确")
    
    return True

def test_scenario_3():
    """场景3: 多份样本 - CSV 样本清单正确"""
    box_code = f"BOX-CSV-S3-{TIMESTAMP}"
    log(1, f"测试箱号: {box_code}")
    
    clean_files(box_code)
    barcodes = create_samples(5)  # 5份样本
    create_box(box_code)
    pack_samples(box_code, barcodes)
    seal_box(box_code)
    do_transfer(box_code, "Dr. Zhang", "Dr. Li", "TP001")
    
    requests.get(f"{BASE_URL}/api/boxes/{box_code}/handover-form")
    
    csv_path = os.path.join(EXPORTS_DIR, f"handover_form_{box_code}.csv")
    csv_sections = read_csv_as_dict(csv_path)
    
    sample_section = csv_sections["样本清单"]
    assert len(sample_section["rows"]) == 5, f"CSV样本数={len(sample_section['rows'])} != 5"
    
    # 验证每个样本条码都存在
    csv_barcodes = [row[sample_section["headers"].index("样本条码")] for row in sample_section["rows"]]
    for bc in barcodes:
        assert bc in csv_barcodes, f"样本条码 {bc} 不在 CSV 中"
    log(2, "✅ 5份样本全部在 CSV 清单中")
    
    return True

def test_scenario_4():
    """场景4: 有撤回历史 - CSV 撤回历史正确"""
    box_code = f"BOX-CSV-S4-{TIMESTAMP}"
    log(1, f"测试箱号: {box_code}")
    
    clean_files(box_code)
    barcodes = create_samples(2)
    create_box(box_code)
    pack_samples(box_code, barcodes)
    seal_box(box_code)
    
    # 连续2次交接并撤回
    do_transfer(box_code, "Dr. Zhang", "Dr. Li", "TP001")
    do_revoke(box_code, "Dr. Li", "第一次撤回")
    do_transfer(box_code, "Dr. Zhang", "Dr. Wang", "TP002")
    do_revoke(box_code, "Dr. Wang", "第二次撤回")
    
    # 第三次交接（有效）
    do_transfer(box_code, "Dr. Zhang", "Dr. Zhao", "TP003")
    
    requests.get(f"{BASE_URL}/api/boxes/{box_code}/handover-form")
    
    json_path = os.path.join(EXPORTS_DIR, f"handover_form_{box_code}.json")
    csv_path = os.path.join(EXPORTS_DIR, f"handover_form_{box_code}.csv")
    
    with open(json_path, 'r', encoding='utf-8') as f:
        json_data = json.load(f)
    
    csv_sections = read_csv_as_dict(csv_path)
    
    # 验证当前交接
    assert json_data["from_point"] == "CP001"
    assert json_data["to_point"] == "TP003"
    assert json_data["to_custodian"] == "Dr. Zhao"
    
    csv_from_point = get_csv_value(csv_sections, "交接单信息", "起点")
    csv_to_point = get_csv_value(csv_sections, "交接单信息", "终点")
    csv_to_custodian = get_csv_value(csv_sections, "交接单信息", "接收人")
    assert csv_from_point == "CP001"
    assert csv_to_point == "TP003"
    assert csv_to_custodian == "Dr. Zhao"
    log(2, "✅ 当前交接信息正确")
    
    # 验证撤回历史数量
    assert len(json_data["revoked_transfer_history"]) == 2
    assert "撤回历史" in csv_sections
    assert len(csv_sections["撤回历史"]["rows"]) == 2
    log(3, "✅ 2条撤回历史正确")
    
    # 验证撤回原因
    revoke_section = csv_sections["撤回历史"]
    reasons = [row[revoke_section["headers"].index("撤回原因")] for row in revoke_section["rows"]]
    assert "第一次撤回" in reasons
    assert "第二次撤回" in reasons
    log(4, "✅ 撤回原因正确")
    
    return True

def test_scenario_5():
    """场景5: 无交接记录 - 导出正确（使用箱子信息）"""
    box_code = f"BOX-CSV-S5-{TIMESTAMP}"
    log(1, f"测试箱号: {box_code}")
    
    clean_files(box_code)
    barcodes = create_samples(2, collection_point="CP002")
    create_box(box_code, destination="TP004")
    pack_samples(box_code, barcodes)
    seal_box(box_code)
    # 注意：不做交接
    
    r = requests.get(f"{BASE_URL}/api/boxes/{box_code}/handover-form")
    assert r.status_code == 200
    json_data = r.json()
    
    # 验证使用箱子信息
    assert json_data["from_point"] == "CP002"
    assert json_data["to_point"] == "TP004"
    assert json_data["from_custodian"] == "Dr. Zhang"
    assert json_data["to_custodian"] == "Dr. Zhang"
    log(2, "✅ 无交接时使用箱子信息")
    
    # 验证 CSV
    csv_path = os.path.join(EXPORTS_DIR, f"handover_form_{box_code}.csv")
    csv_sections = read_csv_as_dict(csv_path)
    csv_from_point = get_csv_value(csv_sections, "交接单信息", "起点")
    csv_to_point = get_csv_value(csv_sections, "交接单信息", "终点")
    assert csv_from_point == "CP002"
    assert csv_to_point == "TP004"
    log(3, "✅ CSV 无交接时信息正确")
    
    return True

def test_scenario_6():
    """场景6: 异常清单导出 - JSON/CSV 数据一致"""
    box_code = f"BOX-CSV-S6-{TIMESTAMP}"
    log(1, f"测试箱号: {box_code}")
    
    clean_files(box_code)
    barcodes = create_samples(2)
    create_box(box_code)
    pack_samples(box_code, barcodes)
    seal_box(box_code)
    do_transfer(box_code, "Dr. Zhang", "Dr. Li", "TP001")
    do_revoke(box_code, "Dr. Li", "测试异常")
    
    r = requests.get(f"{BASE_URL}/api/boxes/{box_code}/exception-list")
    assert r.status_code == 200
    json_data = r.json()
    
    json_path = os.path.join(EXPORTS_DIR, f"exception_list_{box_code}.json")
    csv_path = os.path.join(EXPORTS_DIR, f"exception_list_{box_code}.csv")
    
    assert os.path.exists(json_path), "JSON 文件不存在"
    assert os.path.exists(csv_path), "CSV 文件不存在"
    log(2, "✅ 异常清单 JSON 和 CSV 文件都存在")
    
    # 验证 JSON
    assert json_data["box_code"] == box_code
    assert json_data["total_exceptions"] >= 1  # 至少有TRANSFER_REVOKED
    log(3, "✅ 异常清单 JSON 正确")
    
    # 验证 CSV
    csv_sections = read_csv_as_dict(csv_path)
    assert "异常清单信息" in csv_sections
    csv_box_code = get_csv_value(csv_sections, "异常清单信息", "箱号")
    csv_total = get_csv_value(csv_sections, "异常清单信息", "异常总数")
    assert csv_box_code == box_code
    assert int(csv_total) == json_data["total_exceptions"]
    log(4, "✅ 异常清单 CSV 与 JSON 一致")
    
    # 验证异常明细
    assert "异常明细" in csv_sections
    exc_section = csv_sections["异常明细"]
    assert len(exc_section["rows"]) == json_data["total_exceptions"]
    log(5, "✅ 异常明细条数一致")
    
    # 验证撤回历史
    if "撤回历史" in csv_sections:
        assert len(csv_sections["撤回历史"]["rows"]) == len(json_data.get("revoked_transfer_history", []))
        log(6, "✅ 撤回历史条数一致")
    
    return True

def test_scenario_7():
    """场景7: API 文档包含 CSV 说明"""
    log(1, "检查 API 文档...")
    
    doc_path = os.path.join(os.path.dirname(__file__), "API_DOCUMENTATION.md")
    with open(doc_path, 'r', encoding='utf-8') as f:
        doc_content = f.read()
    
    # 检查交接单导出（多种可能的写法）
    has_handover_csv = (
        "handover_form_*.csv" in doc_content or
        "handover_form_" in doc_content and ".csv" in doc_content
    )
    assert has_handover_csv, "文档缺少 handover_form CSV 说明"
    log(2, "✅ 文档包含交接单 CSV 说明")
    
    # 检查异常清单导出
    has_exception_csv = (
        "exception_list_*.csv" in doc_content or
        "exception_list_" in doc_content and ".csv" in doc_content
    )
    assert has_exception_csv, "文档缺少 exception_list CSV 说明"
    log(3, "✅ 文档包含异常清单 CSV 说明")
    
    # 检查详细接口文档包含 CSV 格式说明
    has_csv_format = (
        "CSV 格式交接单" in doc_content and
        ("CSV 格式异常清单" in doc_content or "CSV" in doc_content and "异常清单" in doc_content)
    )
    assert has_csv_format, "文档缺少 CSV 格式说明"
    log(4, "✅ 详细接口文档包含 CSV 格式说明")
    
    # 检查导出文件列表部分包含 CSV（宽松检查，因为反引号和星号可能有格式差异）
    has_export_list = (
        "handover_form" in doc_content and ".csv" in doc_content and
        "exception_list" in doc_content and ".csv" in doc_content
    )
    assert has_export_list, "导出文件列表缺少 CSV 说明"
    log(5, "✅ 导出文件列表包含 CSV 说明")
    
    return True

def main():
    print("=" * 80)
    print("  CSV 导出回归测试")
    print(f"  测试时间: {datetime.now().isoformat()}")
    print("=" * 80)
    
    try:
        requests.get(f"{BASE_URL}/health", timeout=5)
    except:
        print("❌ 服务未运行")
        return False
    
    tests = [
        ("场景1: 正常交接 - JSON/CSV 数据一致", test_scenario_1),
        ("场景2: 撤回后重新交接 - 起点正确", test_scenario_2),
        ("场景3: 多份样本 - 样本清单正确", test_scenario_3),
        ("场景4: 有撤回历史 - 撤回历史正确", test_scenario_4),
        ("场景5: 无交接记录 - 使用箱子信息", test_scenario_5),
        ("场景6: 异常清单导出 - JSON/CSV 一致", test_scenario_6),
        ("场景7: API 文档包含 CSV 说明", test_scenario_7),
    ]
    
    results = []
    for test_name, test_func in tests:
        results.append(run_test(test_name, test_func))
    
    passed = sum(results)
    total = len(results)
    
    print("\n" + "=" * 80)
    print(f"  📊 测试结果: {passed}/{total} 通过")
    print("=" * 80)
    
    if passed == total:
        print("  🎉 所有测试通过！CSV 导出功能正常！")
    else:
        print(f"  ❌ {total - passed} 个测试失败")
    
    # 保存结果
    result_file = f"csv_regression_result_{TIMESTAMP}.json"
    with open(result_file, "w", encoding="utf-8") as f:
        json.dump({
            "test_time": datetime.now().isoformat(),
            "total_tests": total,
            "passed_tests": passed,
            "all_passed": passed == total,
            "results": {name: result for (name, _), result in zip(tests, results)}
        }, f, ensure_ascii=False, indent=2)
    
    print(f"\n结果已保存到: {result_file}")
    
    return passed == total

if __name__ == "__main__":
    try:
        success = main()
        exit(0 if success else 1)
    except Exception as e:
        print(f"\n❌ 测试异常: {e}")
        import traceback
        traceback.print_exc()
        exit(2)
