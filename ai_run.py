from flask import Flask, request, jsonify, session, redirect, url_for, g
from authlib.integrations.flask_client import OAuth
import sqlite3, time, requests, os, datetime

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "nihit_secret")

DATABASE = "perplex.db"

# ---------------- DB ----------------
def get_db():
    db = getattr(g, "_db", None)
    if db is None:
        db = g._db = sqlite3.connect(DATABASE)
        db.execute("CREATE TABLE IF NOT EXISTS chats(id TEXT, user TEXT, title TEXT)")
        db.execute("CREATE TABLE IF NOT EXISTS messages(chat_id TEXT, role TEXT, content TEXT)")
        db.execute("CREATE TABLE IF NOT EXISTS usage(user TEXT, date TEXT, chats INT, imgs INT, PRIMARY KEY(user,date))")
        db.commit()
    return db

@app.teardown_appcontext
def close_db(e):
    db = getattr(g, "_db", None)
    if db:
        db.close()

# ---------------- GOOGLE AUTH ----------------
oauth = OAuth(app)
google = oauth.register(
    name="google",
    client_id=os.environ.get("GOOGLE_CLIENT_ID"),
    client_secret=os.environ.get("GOOGLE_CLIENT_SECRET"),
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"}
)

# ---------------- AI FIXED ----------------
def ai(msg, cid, img=None):
    try:
        db = get_db()
        hist = db.execute(
            "SELECT role, content FROM messages WHERE chat_id=? ORDER BY rowid DESC LIMIT 6",
            (cid,)
        ).fetchall()

        msgs = [{"role": r, "content": c} for r, c in hist[::-1]]

        user_content = [{"type": "text", "text": msg}]
        if img:
            user_content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{img}"}
            })

        payload = {
            "model": "openai/gpt-4o-mini",  # ✅ SAFE MODEL
            "messages": [
                {"role": "system", "content": "You are Perplex AI made by Nihit Kumar."}
            ] + msgs + [
                {"role": "user", "content": user_content}
            ]
        }

        headers = {
            "Authorization": f"Bearer {os.environ.get('OPENROUTER_KEY')}",
            "Content-Type": "application/json"
        }

        r = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers=headers,
            json=payload,
            timeout=60
        )

        print("STATUS:", r.status_code)
        print("RESPONSE:", r.text)

        if r.status_code != 200:
            return "❌ API Error: " + r.text

        return r.json()["choices"][0]["message"]["content"]

    except Exception as e:
        return "❌ SERVER ERROR: " + str(e)

# ---------------- ROUTES ----------------
@app.route("/")
def home():
    return redirect("/chat") if "user" in session else LOGIN

@app.route("/login")
def login():
    return google.authorize_redirect(url_for("callback", _external=True))

@app.route("/callback")
def callback():
    token = google.authorize_access_token()
    user = google.get("https://www.googleapis.com/oauth2/v2/userinfo").json()
    session["user"] = user["email"]
    return redirect("/chat")

@app.route("/chat")
def chat():
    if "user" not in session:
        return redirect("/")
    return UI

@app.route("/send", methods=["POST"])
def send():
    db = get_db()
    user = session["user"]

    msg = request.form.get("msg")
    img = request.form.get("image")
    cid = request.form.get("chat")

    today = datetime.datetime.now().strftime("%Y-%m-%d")
    u = db.execute("SELECT chats, imgs FROM usage WHERE user=? AND date=?", (user, today)).fetchone()
    c, i = (u if u else (0, 0))

    if c >= 50:
        return jsonify({"reply": "Limit reached (50/day)"})

    if img and i >= 5:
        return jsonify({"reply": "Image limit reached"})

    if not cid or cid == "null":
        cid = str(int(time.time()))
        db.execute("INSERT INTO chats VALUES(?,?,?)", (cid, user, msg[:30]))

    reply = ai(msg, cid, img)

    db.execute("INSERT INTO messages VALUES(?,?,?)", (cid, "user", msg))
    db.execute("INSERT INTO messages VALUES(?,?,?)", (cid, "assistant", reply))

    db.execute("INSERT OR REPLACE INTO usage VALUES(?,?,?,?)",
               (user, today, c + 1, i + (1 if img else 0)))

    db.commit()

    return jsonify({"reply": reply, "chat_id": cid, "title": msg[:30]})

@app.route("/history")
def history():
    rows = get_db().execute(
        "SELECT id, title FROM chats WHERE user=? ORDER BY id DESC",
        (session["user"],)
    ).fetchall()
    return jsonify(rows)

@app.route("/msgs")
def msgs():
    cid = request.args.get("c")
    rows = get_db().execute(
        "SELECT role, content FROM messages WHERE chat_id=?",
        (cid,)
    ).fetchall()
    return jsonify(rows)

# ---------------- UI ----------------
LOGIN = """
<body style="background:black;color:white;display:flex;align-items:center;justify-content:center;height:100vh">
<a href="/login" style="padding:15px 30px;background:white;color:black;border-radius:30px">Continue with Google</a>
</body>
"""

UI = """
<body style="margin:0;background:#111;color:white;font-family:sans-serif;display:flex;height:100vh">
<div style="width:250px;background:#1a1a1a;padding:10px">
<button onclick="newChat()">+ New Chat</button>
<input id="s" placeholder="Search" oninput="filter()">
<div id="h"></div>
</div>

<div style="flex:1;display:flex;flex-direction:column">
<div id="b" style="flex:1;overflow:auto;padding:20px"></div>

<div style="display:flex;padding:10px;background:#222">
<input type="file" id="f" hidden onchange="pre(this)">
<button onclick="f.click()">+</button>
<input id="i" style="flex:1">
<button onclick="send()">Send</button>
</div>
</div>

<script>
let cid=null,img=null;

function send(){
let v=i.value;
if(!v&&!img)return;
b.innerHTML+=`<div style='text-align:right'>${v}</div>`;
fetch("/send",{method:"POST",body:new URLSearchParams({msg:v,chat:cid,image:img})})
.then(r=>r.json()).then(d=>{
cid=d.chat_id;
b.innerHTML+=`<div>${d.reply}</div>`;
load();
});
i.value="";img=null;
}

function load(){
fetch("/history").then(r=>r.json()).then(d=>{
h.innerHTML="";
d.forEach(x=>h.innerHTML+=`<div onclick="openChat('${x[0]}')">${x[1]}</div>`);
});
}

function openChat(id){
cid=id;
fetch("/msgs?c="+id).then(r=>r.json()).then(d=>{
b.innerHTML="";
d.forEach(m=>b.innerHTML+=`<div>${m[1]}</div>`);
});
}

function newChat(){cid=null;b.innerHTML=""}
function filter(){let q=s.value.toLowerCase();document.querySelectorAll("#h div").forEach(e=>e.style.display=e.innerText.toLowerCase().includes(q)?"block":"none")}
function pre(f){let r=new FileReader();r.onload=e=>img=e.target.result.split(",")[1];r.readAsDataURL(f.files[0])}
load();
</script>
"""
# ---------------- RUN ----------------
if __name__ == "__main__":
    app.run(debug=True)
