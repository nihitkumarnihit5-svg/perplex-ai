from flask import Flask, request, jsonify, session, redirect, url_for, g
from authlib.integrations.flask_client import OAuth
from werkzeug.middleware.proxy_fix import ProxyFix
import sqlite3, time, requests, os, datetime
from datetime import timedelta

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app)

app.secret_key = os.environ.get("SECRET_KEY", "nihit_pro_max")
DATABASE = "perplex.db"

# ---------------- DB ----------------
def get_db():
    db = getattr(g, '_db', None)
    if db is None:
        db = g._db = sqlite3.connect(DATABASE)
        db.execute("CREATE TABLE IF NOT EXISTS chats(id TEXT, user TEXT, title TEXT)")
        db.execute("CREATE TABLE IF NOT EXISTS messages(chat_id TEXT, role TEXT, content TEXT)")
        db.execute("CREATE TABLE IF NOT EXISTS usage(user TEXT, date TEXT, chats INT, imgs INT, PRIMARY KEY(user,date))")
        db.commit()
    return db

@app.teardown_appcontext
def close_db(e):
    db = getattr(g, '_db', None)
    if db: db.close()

# ---------------- GOOGLE AUTH ----------------
oauth = OAuth(app)
google = oauth.register(
    name='google',
    client_id=os.environ.get("GOOGLE_CLIENT_ID"),
    client_secret=os.environ.get("GOOGLE_CLIENT_SECRET"),
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={"scope": "openid email profile"}
)

# ---------------- AI ----------------
def ai(msg, cid, img=None):
    db = get_db()
    hist = db.execute("SELECT role, content FROM messages WHERE chat_id=? ORDER BY rowid DESC LIMIT 6",(cid,)).fetchall()
    msgs = [{"role":r,"content":c} for r,c in hist[::-1]]

    user_content = [{"type":"text","text":msg}]
    if img:
        user_content.append({"type":"image_url","image_url":{"url":f"data:image/jpeg;base64,{img}"}})

    payload = {
        "model":"google/gemini-2.0-flash-001",
        "messages":[{"role":"system","content":"You are Perplex AI made by Nihit Kumar."}]
        + msgs +
        [{"role":"user","content":user_content}]
    }

    r = requests.post("https://openrouter.ai/api/v1/chat/completions",
        headers={"Authorization":f"Bearer {os.environ.get('OPENROUTER_KEY')}"},
        json=payload)
    return r.json()["choices"][0]["message"]["content"]

# ---------------- ROUTES ----------------
@app.route("/")
def home():
    return redirect("/chat") if "user" in session else LOGIN

@app.route("/login")
def login():
    return google.authorize_redirect(url_for("callback",_external=True))

@app.route("/callback")
def callback():
    token = google.authorize_access_token()
    user = google.get("https://www.googleapis.com/oauth2/v2/userinfo").json()
    session["user"] = user["email"]
    return redirect("/chat")

@app.route("/chat")
def chat():
    if "user" not in session: return redirect("/")
    return UI

@app.route("/send", methods=["POST"])
def send():
    db=get_db()
    user=session["user"]
    msg=request.form.get("msg")
    img=request.form.get("image")
    cid=request.form.get("chat")

    today=datetime.datetime.now().strftime("%Y-%m-%d")
    u=db.execute("SELECT chats,imgs FROM usage WHERE user=? AND date=?",(user,today)).fetchone()
    c,i=(u if u else (0,0))

    if c>=50: return jsonify({"reply":"Limit reached (50/day)"})
    if img and i>=5: return jsonify({"reply":"Image limit reached"})

    if not cid or cid=="null":
        cid=str(int(time.time()))
        db.execute("INSERT INTO chats VALUES(?,?,?)",(cid,user,msg[:30]))

    reply=ai(msg,cid,img)

    db.execute("INSERT INTO messages VALUES(?,?,?)",(cid,"user",msg))
    db.execute("INSERT INTO messages VALUES(?,?,?)",(cid,"assistant",reply))
    db.execute("INSERT OR REPLACE INTO usage VALUES(?,?,?,?)",(user,today,c+1,i+(1 if img else 0)))
    db.commit()

    return jsonify({"reply":reply,"chat_id":cid,"title":msg[:30]})

@app.route("/history")
def history():
    rows=get_db().execute("SELECT id,title FROM chats WHERE user=? ORDER BY id DESC",(session["user"],)).fetchall()
    return jsonify(rows)

@app.route("/msgs")
def msgs():
    cid=request.args.get("c")
    rows=get_db().execute("SELECT role,content FROM messages WHERE chat_id=?",(cid,)).fetchall()
    return jsonify(rows)

@app.route("/clear",methods=["POST"])
def clear():
    get_db().execute("DELETE FROM chats WHERE user=?",(session["user"],))
    get_db().commit()
    return jsonify({"ok":1})

# ---------------- UI ----------------
LOGIN="""
<body style="background:#000;color:#fff;display:flex;align-items:center;justify-content:center;height:100vh">
<a href="/login" style="padding:15px 30px;background:white;color:black;border-radius:30px;">Continue with Google</a>
</body>
"""

UI="""
<!DOCTYPE html>
<html>
<body style="margin:0;background:#0d0d0d;color:white;display:flex;height:100vh;font-family:sans-serif">

<div style="width:260px;background:#161616;padding:10px;display:flex;flex-direction:column">
<button onclick="newChat()">+ New Chat</button>
<input id="s" oninput="f()" placeholder="Search" style="margin:10px 0">
<div id="h" style="flex:1;overflow:auto"></div>
<button onclick="clearAll()">⚙ Settings</button>
</div>

<div style="flex:1;display:flex;flex-direction:column">
<div id="b" style="flex:1;overflow:auto;padding:20px"></div>

<div style="display:flex;padding:10px;background:#111">
<input type="file" id="fimg" hidden onchange="pre(this)">
<button onclick="document.getElementById('fimg').click()">+</button>
<input id="i" style="flex:1">
<button onclick="mic()">🎤</button>
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
function clearAll(){fetch("/clear",{method:"POST"}).then(()=>location.reload())}
function f(){let q=s.value.toLowerCase();document.querySelectorAll("#h div").forEach(e=>e.style.display=e.innerText.toLowerCase().includes(q)?"block":"none")}
function pre(f){let r=new FileReader();r.onload=e=>img=e.target.result.split(",")[1];r.readAsDataURL(f.files[0])}
function mic(){let r=new(window.SpeechRecognition||webkitSpeechRecognition)();r.onresult=e=>i.value=e.results[0][0].transcript;r.start()}
load();
</script>
</body>
</html>
"""

if __name__ == "__main__":
    app.run()
