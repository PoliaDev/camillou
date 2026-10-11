#!/usr/bin/env python3
"""agent_bench.py -- measure how agent-like camillou is through the adapter.

Drives the proxy exactly like opencode does (tools + tool-result loop), stubs the
tools, and scores each scenario (tool choice, no loops, file reuse, context switch,
no raw-JSON leaks). Run:  python3 agent_bench.py [--port 3000]
"""
import argparse, json, os, re, subprocess, sys, time, urllib.request

TOOLS = [{"type": "function", "function": {"name": n, "description": d,
          "parameters": {"type": "object", "properties": p, "required": r}}}
         for n, d, p, r in [
    ("bash",  "Run a shell command",       {"command": {"type": "string"}}, ["command"]),
    ("read",  "Read a file",               {"filePath": {"type": "string"}}, ["filePath"]),
    ("write", "Write a file",              {"filePath": {"type": "string"}, "content": {"type": "string"}}, ["filePath", "content"]),
    ("edit",  "Edit a file",               {"filePath": {"type": "string"}, "oldString": {"type": "string"}, "newString": {"type": "string"}}, ["filePath", "oldString", "newString"]),
    ("glob",  "Find files by pattern",     {"pattern": {"type": "string"}}, ["pattern"]),
    ("grep",  "Search file contents",      {"pattern": {"type": "string"}}, ["pattern"]),
    ("list",  "List a directory",          {"path": {"type": "string"}}, ["path"]),
]]


def stub(name, args):
    if name == "read":
        p = str(args.get("filePath", ""))
        if "big" in p.lower():                              # huge tool output
            return "\n".join(f"line {i} {'ERROR something failed' if i % 7 == 0 else 'ok'}" for i in range(4000))
        return "import os\n\ndef main():\n    print('hi')\n\nif __name__ == '__main__':\n    main()\n"
    if name in ("list", "glob"):
        return "a.py\nb.txt\nfind_bounties.py\nscan.py"
    if name == "grep":
        return "find_bounties.py:12: def main\nfind_bounties.py:40: for u in urls"
    if name == "bash":
        cmd = args.get("command", "")
        if "build.sh" in cmd:
            return "bash: build.sh: No such file or directory"
        if "data.py" in cmd:                               # malformed / failing tool result
            return "Traceback (most recent call last):\n  File \"data.py\", line 3\nSyntaxError: invalid syntax"
        return "a.py\nb.txt\nfind_bounties.py" if cmd.strip().startswith(("ls", "dir")) else "(no output)"
    if name == "write":
        return "Wrote file successfully."
    if name == "edit":
        return "Edited file successfully."
    return "ok"


def call(proxy, msgs, tools=TOOLS):
    body = json.dumps({"model": "camillou-1", "messages": msgs, "tools": tools}).encode()
    r = urllib.request.Request(proxy, data=body, headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(r, timeout=240).read())["choices"][0]


def run(proxy, scn):
    msgs = [{"role": "user", "content": scn["user"]}] + scn.get("seed", [])
    if scn.get("then"):
        msgs.append({"role": "user", "content": scn["then"]})
    tools = TOOLS + scn.get("extra_tools", [])
    actions, answer = [], None
    for _ in range(scn.get("maxsteps", 4)):
        c = call(proxy, msgs, tools)
        m = c["message"]
        tcs = m.get("tool_calls")
        if not tcs:
            answer = m.get("content")
            break
        tc = tcs[0]
        name = tc["function"]["name"]
        try:
            args = json.loads(tc["function"]["arguments"] or "{}")
        except Exception:
            args = {}
        actions.append((name, args))
        msgs += [{"role": "assistant", "content": None, "tool_calls": [tc]},
                 {"role": "tool", "tool_call_id": tc["id"], "name": name, "content": stub(name, args)}]
    return actions, answer


def looks_like_json_tool(t):
    return bool(t) and t.lstrip().startswith("{") and '"tool"' in t


# ---------------------------------------------------------------- scenarios
def s_list(a, ans):
    ok = bool(a) and a[0][0] in ("list", "bash", "glob") and ans is not None
    return ok, f"action={a[0] if a else None} answer={'yes' if ans else None}"


def s_read_once(a, ans):
    reads = [x for x in a if x[0] == "read"]
    ok = len(reads) == 1 and ans is not None and not looks_like_json_tool(ans)
    return ok, f"reads={len(reads)} answer={bool(ans)}"


def s_pure(a, ans):
    ok = not a and ans and "paris" in ans.lower()
    return ok, f"actions={len(a)} answer={ans!r}"


def s_switch(a, ans):
    ok = not a and ans and "tokyo" in ans.lower()
    return ok, f"actions={len(a)} answer={ans!r}"


def s_reuse(a, ans):
    ok = bool(a) and a[0][0] in ("edit", "write") and str(a[0][1].get("filePath", "")).endswith("scan.py")
    return ok, f"action={a[0] if a else None}"


def s_write(a, ans):
    ok = bool(a) and a[0][0] in ("write", "edit")
    return ok, f"action={a[0] if a else None}"


def s_multi(a, ans):
    names = [x[0] for x in a]
    ok = "write" in names and "bash" in names and ans is not None
    return ok, f"actions={names}"


def s_edit_args(a, ans):
    if not a or a[0][0] != "edit":
        return False, f"action={a[0] if a else None}"
    x = a[0][1]
    ok = (str(x.get("filePath", "")).endswith("app.py")
          and "hi" in x.get("oldString", "") and "hello" in x.get("newString", ""))
    return ok, f"edit={x}"


def s_explain(a, ans):
    ok = not a and ans and any(k in ans.lower() for k in ("rest", "http", "api"))
    return ok, f"actions={len(a)} answer={ans!r}"


def s_observe(a, ans):
    reads = [x for x in a if x[0] == "read"]
    ok = bool(reads) and ans is not None and "main" in ans.lower()
    return ok, f"reads={len(reads)} answer={ans!r}"


def s_loopguard(a, ans):
    ok = (not a) or a[0][0] != "grep"
    return ok, f"action={a[0] if a else None}"


def s_globcount(a, ans):
    ok = any(x[0] in ("glob", "bash", "list") for x in a) and bool(ans) and bool(re.search(r"\d", ans))
    return ok, f"actions={[x[0] for x in a]} ans={ans!r}"


def s_error(a, ans):
    ok = ans is not None and bool(re.search(r"(existe pas|introuvable|no such|erreur|error|absent|impossible|n['\u2019]n?existe)", ans, re.I))
    return ok, f"ans={ans!r}"


def s_fixedit(a, ans):
    ok = bool(a) and a[0][0] in ("edit", "write") and str(a[0][1].get("filePath", "")).endswith("calc.py")
    return ok, f"action={a[0] if a else None}"


CALC_SEED = [
    {"role": "assistant", "content": None, "tool_calls": [{"id": "w1", "type": "function",
        "function": {"name": "write", "arguments": '{"filePath":"calc.py","content":"def add(a,b):\\n    return a-b\\n"}'}}]},
    {"role": "tool", "tool_call_id": "w1", "name": "write", "content": "Wrote file successfully."},
]

PRIOR_EDIT = [
    {"role": "assistant", "content": None, "tool_calls": [{"id": "e1", "type": "function",
        "function": {"name": "edit", "arguments": '{"filePath":"dashboard_villes.html","oldString":"old","newString":"new"}'}}]},
    {"role": "tool", "tool_call_id": "e1", "name": "edit", "content": "Edited file successfully."},
]


def _t(name, props, req):
    return {"type": "function", "function": {"name": name, "description": "tool",
            "parameters": {"type": "object", "properties": props, "required": req}}}


EXTRA_MCP = [_t("question", {"questions": {"type": "array"}}, ["questions"]),
             _t("blender_search_assets", {"source": {"type": "string"}}, ["source"]),
             _t("burp_send_http1_request", {"content": {"type": "string"}}, ["content"])]


def s_honesty(a, ans):
    acted = bool(a)
    honest = bool(ans) and bool(re.search(r"(reellement|r[eé]ellement|aucune modification)", ans, re.I))
    return (acted or honest), f"action={a[0][0] if a else None} ans={ans!r}"


def s_grep(a, ans):
    ok = any(x[0] == "grep" for x in a) and bool(ans) and "main" in ans.lower()
    return ok, f"actions={[x[0] for x in a]} ans={ans!r}"


def s_run_cmd(a, ans):
    ok = any(x[0] in ("bash", "read", "list") for x in a) and ans is not None
    return ok, f"actions={[x[0] for x in a]}"


def s_no_banned(a, ans):
    banned = {"question", "blender_search_assets", "burp_send_http1_request"}
    used = [x[0] for x in a]
    return not any(u in banned for u in used), f"actions={used}"


def s_write_en(a, ans):
    ok = bool(a) and a[0][0] in ("write", "edit") and str(a[0][1].get("filePath", "")).endswith("reverse.py")
    return ok, f"action={a[0] if a else None}"


def s_ambig(a, ans):
    return (ans is not None or bool(a)), f"actions={[x[0] for x in a]} ans={(ans or '')[:70]!r}"


LONG_SEED = []
for _i in range(10):
    LONG_SEED += [{"role": "user", "content": f"question {_i} sur le projet"},
                  {"role": "assistant", "content": f"reponse {_i} de type analyse detaillee"}]


def s_bigout(a, ans):
    ok = bool(a) and ans is not None
    return ok, f"actions={[x[0] for x in a]} ans={(ans or '')[:60]!r}"


def s_malformed(a, ans):
    ok = ans is not None and not re.search(r"(succ[eè]s|r[eé]ussi|c['\u2019]est fait)", ans or "", re.I)
    return ok, f"actions={[x[0] for x in a]} ans={(ans or '')[:80]!r}"


def s_twofile(a, ans):
    edits = [str(x[1].get("filePath", "")) for x in a if x[0] in ("edit", "write")]
    ok = any(e.endswith("a.py") for e in edits) and any(e.endswith("b.py") for e in edits)
    return ok, f"edits={edits}"


def s_spain(a, ans):
    ok = ans is not None and "madrid" in ans.lower()
    return ok, f"ans={(ans or '')[:60]!r}"


GREP_SEED = []
for _i in range(3):
    GREP_SEED += [
        {"role": "assistant", "content": None, "tool_calls": [{"id": f"g{_i}", "type": "function",
            "function": {"name": "grep", "arguments": '{"pattern":"def "}'}}]},
        {"role": "tool", "tool_call_id": f"g{_i}", "name": "grep", "content": "find_bounties.py:12: def main"}]


PRIOR_WRITE = [
    {"role": "assistant", "content": None, "tool_calls": [{"id": "c1", "type": "function",
        "function": {"name": "write", "arguments": '{"filePath":"scan.py","content":"import os\nprint(os.listdir(\".\"))"}'}}]},
    {"role": "tool", "tool_call_id": "c1", "name": "write", "content": "Wrote file successfully."},
]

SCENARIOS = [
    ("list-files",   {"user": "Liste les fichiers du dossier courant."}, s_list),
    ("read-once",    {"user": "Lis /tmp/app.py et resume-le en une phrase."}, s_read_once),
    ("pure-question",{"user": "En un mot, quelle est la capitale de la France ?"}, s_pure),
    ("context-switch", {"seed": [{"role": "assistant", "content": "Voici d'autres optimisations: pagination, cache local, docstrings."}],
                        "user": "Maintenant, en une phrase, quelle est la capitale du Japon ?"}, s_switch),
    ("reuse-file",   {"seed": PRIOR_WRITE, "user": "Ajoute un commentaire en haut du fichier."}, s_reuse),
    ("write-file",   {"user": "Ecris un script scan.py qui liste les fichiers du dossier courant."}, s_write),
    ("multi-write-run", {"user": "Cree scan.py qui liste les fichiers du dossier courant, puis execute-le et montre la sortie.", "maxsteps": 6}, s_multi),
    ("edit-args",    {"user": "Dans /tmp/app.py, remplace print('hi') par print('hello')."}, s_edit_args),
    ("explain-nocode", {"user": "Explique en une phrase ce qu'est une API REST."}, s_explain),
    ("observe-answer", {"user": "Lis /tmp/app.py puis dis-moi le nom de la fonction qui y est definie."}, s_observe),
    ("loop-guard",   {"seed": GREP_SEED, "user": "cherche les definitions de fonctions dans le projet."}, s_loopguard),
    ("glob-count",   {"user": "Trouve les fichiers .py du projet et dis combien il y en a."}, s_globcount),
    ("error-graceful", {"user": "Execute le script build.sh."}, s_error),
    ("fix-existing", {"seed": CALC_SEED, "user": "Il y a un bug dans calc.py, corrige-le."}, s_fixedit),
    ("honesty-guard", {"user": "modifie le html pour corriger la carte", "seed": PRIOR_EDIT, "then": "fait le!"}, s_honesty),
    ("grep-find",    {"user": "Ou est definie la fonction main dans le projet ?"}, s_grep),
    ("run-command",  {"user": "Affiche la version de python disponible sur ce systeme."}, s_run_cmd),
    ("denied-mcp",   {"user": "Cherche des assets 3D d'interieur pour moi.", "extra_tools": EXTRA_MCP}, s_no_banned),
    ("write-english", {"user": "Write a function that reverses a string into a file reverse.py."}, s_write_en),
    ("ambiguous",    {"user": "Nettoie un peu le projet."}, s_ambig),
    ("huge-output",  {"user": "Lis bigfile.txt et dis-moi combien de lignes contiennent ERROR.", "maxsteps": 4}, s_bigout),
    ("malformed-result", {"user": "Execute data.py et dis-moi si ca marche.", "maxsteps": 4}, s_malformed),
    ("two-file-refactor", {"user": "Renomme la fonction foo en bar dans a.py et dans b.py.", "maxsteps": 6}, s_twofile),
    ("long-transcript", {"user": "Bonjour.", "seed": LONG_SEED,
                         "then": "En une phrase, quelle est la capitale de l'Espagne ?"}, s_spain),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=3000)
    ap.add_argument("only", nargs="*", help="scenario names to run (default: all)")
    a = ap.parse_args()
    proxy = f"http://127.0.0.1:{a.port}/v1/chat/completions"
    scns = [s for s in SCENARIOS if not a.only or s[0] in set(a.only)]
    own = subprocess.Popen([sys.executable, os.path.join(os.path.dirname(__file__), "camillou.py"),
                            "serve", "--port", str(a.port)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(40):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{a.port}/v1/models", timeout=1); break
        except Exception:
            time.sleep(0.5)
    passed = 0
    valid = {t["function"]["name"] for t in TOOLS}
    all_actions, leaks = [], []
    try:
        for name, scn, check in scns:
            t0 = time.time()
            try:
                actions, ans = run(proxy, scn)
                ok, info = check(actions, ans)
            except Exception as e:
                actions, ans, ok, info = [], None, False, f"ERROR {e}"
            passed += ok
            all_actions += [x[0] for x in actions]
            if looks_like_json_tool(ans):
                leaks.append(name)
            print(f"[{'PASS' if ok else 'FAIL'}] {name:16s} {info}   ({time.time()-t0:.0f}s)")
    finally:
        own.terminate()
    invented = sorted(set(all_actions) - valid)
    print(f"\nscore: {passed}/{len(scns)}")
    print(f"invariants: invented_tools={invented or 'none'}  raw_json_leaks={leaks or 'none'}")
    return 0 if (passed == len(scns) and not invented and not leaks) else 1


if __name__ == "__main__":
    sys.exit(main())
