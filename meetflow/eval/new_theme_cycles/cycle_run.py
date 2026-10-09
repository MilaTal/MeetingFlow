"""Цикл создания проекта по скиллу meetflow: проект, «Команда», две встречи через HTTP стенда, сверка с ожиданиями,
записанными ДО прогона. Запуск: python cycle_run.py <файл сценария.json> <порт>."""
import json
import sys
import time
import urllib.error
import urllib.request
import uuid

scn = json.load(open(sys.argv[1], encoding="utf-8"))
BASE = f"http://127.0.0.1:{sys.argv[2]}"
import urllib.parse
H = {"X-User-Role": "super_admin", "X-User-Name": urllib.parse.quote("Прогон цикла")}


def call(method, path, body=None, files=None):
    data, headers = None, dict(H)
    if files:
        b = uuid.uuid4().hex
        name, content = files
        data = (f"--{b}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{name}\"\r\n"
                f"Content-Type: text/plain\r\n\r\n").encode("utf-8") + content.encode("utf-8") + f"\r\n--{b}--\r\n".encode()
        headers["Content-Type"] = f"multipart/form-data; boundary={b}"
    elif body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=1800) as r:
            return r.status, json.loads(r.read().decode("utf-8") or "null")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8")[:300]


for _ in range(60):
    try:
        if call("GET", "/health")[0] == 200:
            break
    except Exception:
        time.sleep(1)

out = {"scenario": scn["title"], "team": [], "meetings": []}
_, p = call("POST", "/api/projects", {"name": scn["project"]})
pid = p["id"]
for person in scn["team"]:
    st, r = call("POST", f"/api/projects/{pid}/people", person)
    out["team"].append({"who": person["full_name"], "status": st, "answer": r if st != 200 else "заведён"})

for m in scn["meetings"]:
    _, mm = call("POST", f"/api/projects/{pid}/meetings", {"date": m["date"], "label": m["label"]})
    mid = mm["id"]
    st_up, up = call("POST", f"/api/meetings/{mid}/sources", files=(m["file"], m["text"]))
    t0 = time.time()
    st_run, rep = call("POST", f"/api/meetings/{mid}/run")
    secs = round(time.time() - t0, 1)
    _, tasks = call("GET", f"/api/projects/{pid}/tasks?status=all")
    _, cards = call("GET", f"/api/projects/{pid}/cards")
    _, proto = call("GET", f"/api/meetings/{mid}/protocol")
    out["meetings"].append({"label": m["label"], "upload": [st_up, up if st_up != 200 else up.get("status")],
                            "run_status": st_run, "seconds": secs, "report": rep, "expect": m["expect"],
                            "tasks": tasks, "cards": cards, "protocol": proto})
json.dump(out, open(sys.argv[1].replace(".json", "__итог.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("готово:", sys.argv[1].replace(".json", "__итог.json"))
