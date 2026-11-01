"""Static check: foreign keys must not form a cycle (create_all would fail on SQLite). Usage: python ops/check_fk_cycles.py"""
import ast, glob, sys
graph, cur = {}, None
for f in glob.glob("backend/app/models/*.py"):
    for node in ast.parse(open(f).read()).body:
        if isinstance(node, ast.ClassDef):
            tn = None
            for st in node.body:
                if isinstance(st, ast.Assign) and any(getattr(t, "id", "") == "__tablename__" for t in st.targets):
                    tn = st.value.value
            if not tn: continue
            deps = graph.setdefault(tn, set())
            for n in ast.walk(node):
                if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "ForeignKey" and n.args and isinstance(n.args[0], ast.Constant):
                    t = n.args[0].value.split(".")[0]
                    if t != tn: deps.add(t)
state, bad = {}, []
def dfs(n, path):
    state[n] = 1
    for d in graph.get(n, ()):
        if state.get(d) == 1: bad.append(path + [n, d])
        elif d not in state: dfs(d, path + [n])
    state[n] = 2
for n in list(graph): 
    if n not in state: dfs(n, [])
print("FK cycles:", bad or "none"); sys.exit(1 if bad else 0)
