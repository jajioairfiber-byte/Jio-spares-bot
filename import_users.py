"""
import_users.py
--------------
Run this ONCE on your Render server or locally to import
your 3000+ Active_Users into the SQLite database.

Usage:
  1. Export your data as CSV from Excel/SQL with columns:
       Employee_Key, Employee_Name, Region, State, JC_ID, Work_Area, Work_Stream, Position

  2. Place the CSV file in the same folder as this script.

  3. Run:
       python import_users.py your_file.csv

  OR to import from a SQL INSERT script:
       python import_users.py your_file.sql
"""

import sys
import sqlite3
import csv
import os

DB_PATH = "jio_spares_bot.db"

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def import_from_csv(filepath):
    conn = get_db()
    inserted = 0
    skipped  = 0

    with open(filepath, newline='', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                conn.execute("""
                    INSERT OR REPLACE INTO Active_Users
                        (Employee_Key, Employee_Name, Region, State, JC_ID, Work_Area, Work_Stream, Position)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    int(str(row.get('Employee_Key', '')).strip()),
                    str(row.get('Employee_Name', '')).strip(),
                    str(row.get('Region', '')).strip(),
                    str(row.get('State', '')).strip(),
                    str(row.get('JC_ID', '')).strip(),
                    str(row.get('Work_Area', '')).strip(),
                    str(row.get('Work_Stream', '')).strip(),
                    str(row.get('Position', '')).strip()
                ))
                inserted += 1
            except Exception as e:
                print(f"  ⚠ Skipped row {row}: {e}")
                skipped += 1

    conn.commit()

    total = conn.execute("SELECT COUNT(*) as c FROM Active_Users").fetchone()["c"]
    conn.close()

    print(f"\n✅ Import complete!")
    print(f"   Inserted : {inserted}")
    print(f"   Skipped  : {skipped}")
    print(f"   Total in DB: {total}")

def verify_sample():
    """Show first 5 records to verify import"""
    conn = get_db()
    rows = conn.execute("SELECT * FROM Active_Users LIMIT 5").fetchall()
    conn.close()
    print("\n--- Sample Records ---")
    for r in rows:
        r = dict(r)
        print(f"  EP: {r['Employee_Key']} | Name: {r['Employee_Name']} | JC_ID: {r['JC_ID']} | Region: {r['Region']}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python import_users.py <your_file.csv>")
        print("\nCSV must have these columns:")
        print("  Employee_Key, Employee_Name, Region, State, JC_ID, Work_Area, Work_Stream, Position")
        sys.exit(1)

    filepath = sys.argv[1]
    if not os.path.exists(filepath):
        print(f"❌ File not found: {filepath}")
        sys.exit(1)

    print(f"📂 Importing from: {filepath}")
    import_from_csv(filepath)
    verify_sample()
