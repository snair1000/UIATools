import sqlite3, json

c = sqlite3.connect("C:/SCM_UIA_Repo.db")
c.row_factory = sqlite3.Row

# checkbox click was at abs (66,294) with win rect (-8,-8,...) => rel (74,302)
rows = c.execute(
    """SELECT element_id,path,depth,left,top,right,bottom,is_offscreen,properties
       FROM elements
       WHERE screen_id=12 AND 74 BETWEEN left AND right AND 302 BETWEEN top AND bottom
       ORDER BY depth DESC"""
).fetchall()
print("hit count (incl offscreen):", len(rows))
for r in rows:
    p = json.loads(r["properties"])
    print(
        r["depth"],
        p.get("control_type_name"),
        repr(p.get("name"))[:40],
        p.get("automation_id"),
        (r["left"], r["top"], r["right"], r["bottom"]),
        "OFFSCREEN" if r["is_offscreen"] else "",
    )

n = c.execute(
    "SELECT COUNT(*) FROM elements WHERE screen_id=12 AND properties LIKE '%CheckBox%'"
).fetchone()[0]
print("checkbox rows on screen 12:", n)

# deepest paths stored
row = c.execute("SELECT MAX(depth) AS d FROM elements WHERE screen_id=12").fetchone()
print("max stored depth on screen 12:", row["d"])

# what does the k-grid0-checkbox0 row look like, if present
rows = c.execute(
    "SELECT path,depth,left,top,right,bottom,is_offscreen FROM elements "
    "WHERE screen_id=12 AND properties LIKE '%k-grid0-checkbox0%'"
).fetchall()
for r in rows:
    print("checkbox0:", dict(r))
