import json
from fastapi.testclient import TestClient
from api import app
c = TestClient(app)
def show(title, r):
    print("\n==", title, r.status_code)
    print(json.dumps(r.json(), ensure_ascii=False, indent=1)[:1800])
show("top gharbia", c.get("/api/top", params=dict(gov="gharbia", n=3)))
show("check wheat", c.get("/api/check", params=dict(gov="gharbia", crop="قمح")))
show("check rice", c.get("/api/check", params=dict(gov="sharqia", crop="rice")))
show("check watermelon", c.get("/api/check", params=dict(gov="aswan", crop="بطيخ")))
show("climate luxor", c.get("/api/climate", params=dict(gov="luxor")))
print(len(c.get("/api/governorates").json()), "governorates")
show("bad crop", c.get("/api/check", params=dict(gov="gharbia", crop="xyz")))
