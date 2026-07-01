import sqlite3
c = sqlite3.connect("data/competitor_search.db")
for row in c.execute("SELECT name, sql FROM sqlite_master WHERE type='table'"):
    print(row[0])
    print(row[1])
    print()
