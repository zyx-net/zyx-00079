#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Service restart persistence verification test
"""

import requests
import json

BOX_CODE = 'BOX-REVOKE-PY-20260606114751'

print('=' * 50)
print('  Service Restart Persistence Verification')
print('=' * 50)
print()

# 1. Verify box status
print('[1/4] Verifying box status after restart...')
r = requests.get(f'http://localhost:8000/api/boxes/{BOX_CODE}')
box_data = r.json()
print(f'  Box status: {box_data["status"]}')
print(f'  Current custodian: {box_data["current_custodian"]}')
assert box_data['status'] == 'DELIVERED', f'Expected DELIVERED, got {box_data["status"]}'
assert box_data['current_custodian'] == 'Dr. Li', f'Expected Dr. Li, got {box_data["current_custodian"]}'
print('  [PASS] Box status correctly persisted as DELIVERED')
print()

# 2. Verify transfer history
print('[2/4] Verifying transfer history after restart...')
r = requests.get(f'http://localhost:8000/api/boxes/{BOX_CODE}/transfer-history')
history = r.json()
print(f'  Total transfer records: {len(history)}')
revoked_count = len([t for t in history if t.get('is_revoked') == True])
active_count = len([t for t in history if t.get('is_revoked') == False])
print(f'  Revoked records: {revoked_count}')
print(f'  Active records: {active_count}')
for t in history:
    print(f'    [{t["id"]}] {t["from_custodian"]} -> {t["to_custodian"]}, revoked: {t.get("is_revoked")}')
    if t.get('is_revoked'):
        print(f'      Revoked by: {t.get("revoked_by")}, reason: {t.get("revoke_reason")}')
assert len(history) >= 2, f'Expected >= 2 records, got {len(history)}'
assert revoked_count >= 1, f'Expected >= 1 revoked records, got {revoked_count}'
assert active_count >= 1, f'Expected >= 1 active records, got {active_count}'
print('  [PASS] Transfer history correctly preserved with revoked and active records')
print()

# 3. Verify audit logs
print('[3/4] Verifying audit logs after restart...')
r = requests.get('http://localhost:8000/api/audit', params={'action': 'REVOKE_TRANSFER'})
audit_logs = r.json()
print(f'  Total REVOKE_TRANSFER audit logs: {len(audit_logs)}')
transfer_logs = [l for l in audit_logs if l['entity_type'] == 'TRANSFER']
box_logs = [l for l in audit_logs if l['entity_type'] == 'BOX']
sample_logs = [l for l in audit_logs if l['entity_type'] == 'SAMPLE']
print(f'  TRANSFER entity logs: {len(transfer_logs)}')
print(f'  BOX entity logs: {len(box_logs)}')
print(f'  SAMPLE entity logs: {len(sample_logs)}')
for log in audit_logs[:3]:
    print(f'    [{log["id"]}] {log["entity_type"]} action={log["action"]}, {log["old_status"]} -> {log["new_status"]} by {log["custodian"]}')
assert len(audit_logs) >= 4, f'Expected >= 4 audit logs (1 transfer + 1 box + 2 samples), got {len(audit_logs)}'
assert len(transfer_logs) >= 1, f'Expected >= 1 TRANSFER logs, got {len(transfer_logs)}'
assert len(box_logs) >= 1, f'Expected >= 1 BOX logs, got {len(box_logs)}'
assert len(sample_logs) >= 2, f'Expected >= 2 SAMPLE logs, got {len(sample_logs)}'
print('  [PASS] Audit logs correctly preserved across service restart')
print()

# 4. Verify export files consistency
print('[4/4] Verifying exported JSON files consistency...')
handover_path = f'd:/workSpace/AI__SPACE/zyx-00079/exports/handover_form_{BOX_CODE}.json'
exception_path = f'd:/workSpace/AI__SPACE/zyx-00079/exports/exception_list_{BOX_CODE}.json'

with open(handover_path, 'r', encoding='utf-8') as f:
    handover_data = json.load(f)
print(f'  Handover form has revoked history: {handover_data.get("revoked_transfer_history") is not None}')
if handover_data.get('revoked_transfer_history'):
    print(f'  Revoked history count: {len(handover_data["revoked_transfer_history"])}')

with open(exception_path, 'r', encoding='utf-8') as f:
    exception_data = json.load(f)
revoke_exceptions = [e for e in exception_data['exceptions'] if e.get('type') == 'TRANSFER_REVOKED']
print(f'  Exception list has TRANSFER_REVOKED entries: {len(revoke_exceptions)}')
print(f'  Exception list has revoked history: {exception_data.get("revoked_transfer_history") is not None}')

assert handover_data.get('revoked_transfer_history') is not None, 'Handover form missing revoked history'
assert len(revoke_exceptions) >= 1, 'Exception list missing TRANSFER_REVOKED entries'
assert exception_data.get('revoked_transfer_history') is not None, 'Exception list missing revoked history'
print('  [PASS] Exported JSON files correctly contain revoke history')
print()

print('=' * 50)
print('  ALL PERSISTENCE TESTS PASSED!')
print('=' * 50)
print()
