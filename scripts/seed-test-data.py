#!/usr/bin/env python3
"""Seed LiteLLM_SpendLogs with a week of synthetic activity for a 50-person company."""
import os, random, uuid, json
from datetime import datetime, timedelta, timezone
import psycopg2
from psycopg2.extras import execute_batch

DSN = os.environ.get("DSN", "postgresql://litellm:9m4zBRHnpdc5qHj4Y5VULE8Y@postgres:5432/litellm")

TEAMS = {
    "engineering": 14, "sales": 8, "operations": 8,
    "legal": 4, "marketing": 8, "exec": 4, "hr": 4,
}
FIRST = ["Alex","Jordan","Taylor","Morgan","Casey","Riley","Avery","Quinn","Sam","Jamie",
        "Drew","Reese","Parker","Rowan","Emerson","Hayden","Skyler","Dakota","Logan","Blake",
        "Cameron","Finley","Harper","Kendall","Marley","Noel","Payton","Sage","Teagan","Wren",
        "Kai","Jules","Ellis","Spencer","Adrian","Bailey","Corey","Devon","Eli","Frankie",
        "Gale","Hollis","Indigo","Jesse","Kendrick","Lane","Micah","Nico","Oakley","Presley"]
LAST = ["Smith","Johnson","Williams","Brown","Jones","Garcia","Miller","Davis","Rodriguez","Martinez",
        "Hernandez","Lopez","Gonzalez","Wilson","Anderson","Thomas","Taylor","Moore","Jackson","Martin",
        "Lee","Perez","Thompson","White","Harris","Sanchez","Clark","Ramirez","Lewis","Robinson",
        "Walker","Young","Allen","King","Wright","Scott","Torres","Nguyen","Hill","Flores",
        "Green","Adams","Nelson","Baker","Hall","Rivera","Campbell","Mitchell","Carter","Roberts"]

PRICING = {
    "claude-haiku-4-5":   (0.00000080, 0.00000400),
    "claude-sonnet-4-6":  (0.00000300, 0.00001500),
    "claude-opus-4-6":    (0.00001500, 0.00007500),
}

TEAM_MODEL_MIX = {
    "engineering": [("claude-sonnet-4-6",0.55),("claude-haiku-4-5",0.30),("claude-opus-4-6",0.15)],
    "sales":       [("claude-haiku-4-5",0.65),("claude-sonnet-4-6",0.30),("claude-opus-4-6",0.05)],
    "operations":  [("claude-haiku-4-5",0.70),("claude-sonnet-4-6",0.25),("claude-opus-4-6",0.05)],
    "legal":       [("claude-opus-4-6",0.50),("claude-sonnet-4-6",0.40),("claude-haiku-4-5",0.10)],
    "marketing":   [("claude-sonnet-4-6",0.50),("claude-haiku-4-5",0.40),("claude-opus-4-6",0.10)],
    "exec":        [("claude-opus-4-6",0.40),("claude-sonnet-4-6",0.45),("claude-haiku-4-5",0.15)],
    "hr":          [("claude-haiku-4-5",0.60),("claude-sonnet-4-6",0.35),("claude-opus-4-6",0.05)],
}
TEAM_DAILY = {
    "engineering": (15,50), "sales": (8,25), "operations": (5,20),
    "legal": (3,12), "marketing": (6,22), "exec": (3,12), "hr": (4,15),
}

random.seed(42)

def pick(weighted):
    r = random.random(); acc = 0.0
    for k,w in weighted:
        acc += w
        if r <= acc: return k
    return weighted[-1][0]

def make_users():
    users=[]; used=set()
    for team,count in TEAMS.items():
        for _ in range(count):
            while True:
                f=random.choice(FIRST); l=random.choice(LAST)
                email=f"{f.lower()}.{l.lower()}@uniformedi.local"
                if email not in used: used.add(email); break
            users.append({"user_id":str(uuid.uuid4()),"email":email,"name":f"{f} {l}","team":team,
                          "api_key":"sk-"+uuid.uuid4().hex})
    return users

def gen_hour():
    r=random.random()
    if r<0.70: return random.randint(9,17)
    if r<0.95: return random.choice([7,8,18,19,20,21])
    return random.randint(0,23)

def tokens_for(model):
    if model=="claude-haiku-4-5":
        return random.randint(80,1200), random.randint(40,800)
    if model=="claude-sonnet-4-6":
        return random.randint(200,4000), random.randint(150,2500)
    return random.randint(400,8000), random.randint(300,5000)

def main():
    conn = psycopg2.connect(DSN); conn.autocommit=False
    cur = conn.cursor()
    cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name='LiteLLM_SpendLogs'")
    cols = {r[0] for r in cur.fetchall()}
    print(f"Columns: {sorted(cols)}")

    users = make_users()
    print(f"Generated {len(users)} users across {len(TEAMS)} teams")

    rows=[]
    now = datetime.now(timezone.utc)
    end = now.replace(hour=0,minute=0,second=0,microsecond=0)
    start = end - timedelta(days=7)

    for day_offset in range(7):
        day = start + timedelta(days=day_offset)
        is_weekend = day.weekday()>=5
        for u in users:
            if is_weekend and random.random()<0.82: continue
            if random.random()<0.10: continue
            lo,hi = TEAM_DAILY[u["team"]]
            n = random.randint(lo,hi)
            if is_weekend: n = max(1, n//4)
            for _ in range(n):
                model = pick(TEAM_MODEL_MIX[u["team"]])
                pt,ct = tokens_for(model)
                pp,cp = PRICING[model]
                spend = pt*pp + ct*cp
                hr=gen_hour(); mn=random.randint(0,59); sc=random.randint(0,59)
                ts = day.replace(hour=hr,minute=mn,second=sc)
                blocked = random.random()<0.015
                req_id = str(uuid.uuid4())
                row = {
                    "request_id": req_id,
                    "call_type": "completion",
                    "api_key": u["api_key"],
                    "spend": 0.0 if blocked else spend,
                    "total_tokens": 0 if blocked else pt+ct,
                    "prompt_tokens": 0 if blocked else pt,
                    "completion_tokens": 0 if blocked else ct,
                    "startTime": ts,
                    "endTime": ts + timedelta(milliseconds=random.randint(400,4500)),
                    "completionStartTime": ts + timedelta(milliseconds=random.randint(100,800)),
                    "model": model,
                    "model_id": model,
                    "model_group": model,
                    "api_base": "https://api.anthropic.com",
                    "user": u["email"],
                    "end_user": u["email"],
                    "metadata": json.dumps({"team":u["team"],"user_name":u["name"],
                                           "dlp_blocked":blocked,
                                           "block_reason":"PII detected" if blocked else None}),
                    "cache_hit": "false",
                    "cache_key": None,
                    "request_tags": json.dumps([u["team"], "synthetic"]),
                    "team_id": u["team"],
                    "requester_ip_address": f"10.0.{random.randint(1,5)}.{random.randint(10,250)}",
                    "messages": json.dumps([]),
                    "response": json.dumps({}),
                    "session_id": None,
                    "status": "failure" if blocked else "success",
                    "custom_llm_provider": "anthropic",
                    "proxy_server_request": json.dumps({}),
                }
                rows.append(row)

    print(f"Generated {len(rows)} spend log rows")

    keys = [k for k in rows[0].keys() if k in cols]
    print(f"Using columns: {keys}")
    placeholders = ",".join(["%s"]*len(keys))
    collist = ",".join([f'"{k}"' for k in keys])
    sql = f'INSERT INTO "LiteLLM_SpendLogs" ({collist}) VALUES ({placeholders}) ON CONFLICT DO NOTHING'
    data = [tuple(r[k] for k in keys) for r in rows]
    execute_batch(cur, sql, data, page_size=500)
    conn.commit()

    cur.execute('SELECT COUNT(*), SUM(spend), COUNT(DISTINCT "user") FROM "LiteLLM_SpendLogs"')
    c,s,u = cur.fetchone()
    print(f"Total rows: {c}, total spend: ${s:.2f}, distinct users: {u}")
    cur.execute('SELECT model, COUNT(*), SUM(spend) FROM "LiteLLM_SpendLogs" GROUP BY model ORDER BY 2 DESC')
    for r in cur.fetchall(): print(f"  {r[0]}: {r[1]} calls, ${r[2]:.2f}")
    cur.close(); conn.close()

if __name__=="__main__": main()
