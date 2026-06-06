import sqlite3
import os

db_path = os.path.join(os.path.dirname(__file__), "data", "sample_transport_v2.db")
print(f"DB Path: {db_path}")
print(f"Exists: {os.path.exists(db_path)}")

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

cursor.execute("SELECT id, reservation_no, status, rule_version, rule_snapshot FROM reservations ORDER BY id")
rows = cursor.fetchall()
print("\nAll reservations:")
for row in rows:
    has_snapshot = "YES" if row[4] is not None else "NO"
    snapshot_preview = str(row[4])[:30] if row[4] else "None"
    print(f"  ID: {row[0]:2d}, No: {row[1]}, status: {row[2]:10s}, version: {row[3]}, snapshot: {has_snapshot} ({snapshot_preview})")

conn.close()
