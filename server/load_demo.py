import json
from pathlib import Path
 
import requests
 
SERVER = "http://localhost:8000"
SOURCES = Path(__file__).resolve().parent.parent / "demo" / "sources.json"  # works from any folder
 
with open(SOURCES, encoding="utf-8") as f:
    demo = json.load(f)
 
requests.post(f"{SERVER}/clear")
for url in demo["sources"]:
    r = requests.post(f"{SERVER}/debug/capture-url", json={"url": url}).json()
    print(f"{r}  <-  {url}")
 
print()
for test in demo["test_sentences"]:
    r = requests.post(f"{SERVER}/check", json={"sentence": test["sentence"]}).json()
    got = "match" if r["match"] else "no match"
    flag = "OK  " if got == test["expect"] else "FAIL"
    score = f"{r['score']:.2f}" if r.get("score") is not None else "  - "
    label = r.get("label", "")
    print(f"{flag} {score} {label:<11} {test['sentence'][:60]}")