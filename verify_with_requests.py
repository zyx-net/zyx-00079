#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
简单的 curl/Python 验证脚本
"""
import requests
import json
from datetime import datetime, timezone

BASE_URL = 'http://localhost:8000'
now = datetime.now(timezone.utc).isoformat()
box_code = f'BOX-CURL-{now[:19].replace(":", "")}'

# 创建测试数据
print('--- 创建测试数据 ---')
requests.post(f'{BASE_URL}/api/boxes', json={'box_code': box_code, 'destination': 'TP001', 'current_custodian': 'Dr. Zhang'})
s = requests.post(f'{BASE_URL}/api/samples', json={
    'barcode': f'SAMP-CURL-{now[:19].replace(":", "")}',
    'sample_type': 'urine',
    'collection_point': 'CP001',
    'collection_time': now,
    'current_custodian': 'Dr. Zhang',
    'patient_info': json.dumps({'name': 'Test'})
})
requests.post(f'{BASE_URL}/api/boxes/pack', json={
    'box_code': box_code,
    'barcodes': [s.json()['barcode']],
    'custodian': 'Dr. Zhang'
})
requests.post(f'{BASE_URL}/api/boxes/seal', params={'box_code': box_code, 'custodian': 'Dr. Zhang'})
tr = requests.post(f'{BASE_URL}/api/boxes/transfer', json={
    'box_code': box_code,
    'to_point': 'TP001',
    'to_custodian': 'Dr. Li',
    'from_custodian': 'Dr. Zhang',
    'temperature': 4.8,
    'temperature_records': json.dumps([{'temperature': 4.5, 'timestamp': now}])
})
print(f'交接成功，ID={tr.json()["transfer_id"]}')

# 第一次撤回
r1 = requests.post(f'{BASE_URL}/api/boxes/revoke-transfer', json={
    'box_code': box_code,
    'custodian': 'Dr. Li',
    'reason': '测试1'
})
print(f'第一次撤回: HTTP {r1.status_code}, success={r1.json()["success"]}')

# 重复撤回
r2 = requests.post(f'{BASE_URL}/api/boxes/revoke-transfer', json={
    'box_code': box_code,
    'custodian': 'Dr. Zhang',
    'reason': '测试2'
})
print(f'重复撤回: HTTP {r2.status_code}, code={r2.json()["detail"]["code"]}')
assert r2.status_code == 409
assert r2.json()["detail"]["code"] == "TRANSFER_ALREADY_REVOKED"

# 重新交接并验收
r3 = requests.post(f'{BASE_URL}/api/boxes/transfer', json={
    'box_code': box_code,
    'to_point': 'TP001',
    'to_custodian': 'Dr. Li',
    'from_custodian': 'Dr. Zhang',
    'temperature': 4.8,
    'temperature_records': json.dumps([{'temperature': 4.5, 'timestamp': now}])
})
r4 = requests.post(f'{BASE_URL}/api/boxes/accept', json={
    'box_code': box_code,
    'custodian': 'Dr. Li',
    'check_duration': False
})
print(f'验收成功，状态={r4.json()["status"]}')

# 验收后撤回
r5 = requests.post(f'{BASE_URL}/api/boxes/revoke-transfer', json={
    'box_code': box_code,
    'custodian': 'Dr. Li',
    'reason': '测试3'
})
print(f'验收后撤回: HTTP {r5.status_code}, code={r5.json()["detail"]["code"]}')
assert r5.status_code == 409
assert r5.json()["detail"]["code"] == "BOX_INVALID_STATUS"

# 验证 openapi.json
print()
print('--- 验证 /openapi.json ---')
r = requests.get(f'{BASE_URL}/openapi.json')
paths = r.json()['paths']
resp = paths['/api/boxes/revoke-transfer']['post']['responses']
print(f'409 描述: {resp["409"]["description"]}')
print(f'404 描述: {resp["404"]["description"]}')
print(f'400 描述: {resp["400"]["description"]}')

# 验证错误码
assert "TRANSFER_ALREADY_REVOKED" in resp["409"]["description"]
assert "BOX_INVALID_STATUS" in resp["409"]["description"]
assert "NO_TRANSFER_RECORD" in resp["404"]["description"]
assert "INVALID_CUSTODIAN" in resp["400"]["description"]

print()
print('=== 所有 Python requests 验证通过 ===')
