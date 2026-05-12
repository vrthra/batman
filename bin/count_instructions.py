import json

data = json.load(open("/tmp/tmp.json"))

total = 0
for f in data["data"][0]["functions"]:
    for b in f.get("regions", []):
        total += b[4]

print(total)
