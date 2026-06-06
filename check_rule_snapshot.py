import requests

BASE_URL = "http://localhost:8002"

r = requests.get(f"{BASE_URL}/api/reservations?status=LOADED")
d = r.json()
no = d[0]['reservation_no']
print(f'Checking: {no}')

r2 = requests.get(f'{BASE_URL}/api/reservations/{no}')
d2 = r2.json()

print(f'Has rule_snapshot: {d2.get("rule_snapshot") is not None}')
print(f'rule_snapshot type: {type(d2.get("rule_snapshot"))}')
if d2.get("rule_snapshot"):
    print(f'rule_snapshot preview: {str(d2.get("rule_snapshot"))[:80]}...')
