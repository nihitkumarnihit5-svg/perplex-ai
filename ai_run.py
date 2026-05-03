from flask import Flask, request, jsonify, session, redirect, url_for, g
from authlib.integrations.flask_client import OAuth
from werkzeug.middleware.proxy_fix import ProxyFix
import sqlite3, time, requests, os, datetime
from datetime import timedelta

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

app.secret_key = os.environ.get("SECRET_KEY", "nihit_gemini_v3")
app.config["SESSION_PERMANENT"] = True
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=30)

DATABASE = "nihit_v3.db"


def get_db():
    db = getattr(g, "_database", None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        db.execute("CREATE TABLE IF NOT EXISTS chats(id TEXT, user TEXT, title TEXT)")
        db.execute("CREATE TABLE IF NOT EXISTS messages(chat_id TEXT, role TEXT, content TEXT)")
        db.execute(
            "CREATE TABLE IF NOT EXISTS usage(user TEXT, date TEXT, chats INT, PRIMARY KEY(user, date))"
        )
        db.commit()
    return db


@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, "_database", None)
    if db is not None:
        db.close()


oauth = OAuth(app)
google = oauth.register(
    name="google",
    client_id=os.environ.get("GOOGLE_CLIENT_ID"),
    client_secret=os.environ.get("GOOGLE_CLIENT_SECRET"),
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "email profile"},
)


def ai(msg, cid, img=None):
    try:
        db = get_db()
        hist = db.execute(
            "SELECT role, content FROM messages WHERE chat_id=? ORDER BY rowid DESC LIMIT 6",
            (cid,),
        ).fetchall()

        msgs = [
            {
                "role": "assistant" if r in ["assistant", "ai"] else "user",
                "content": c,
            }
            for r, c in hist[::-1]
        ]

        payload = {
            "model": "google/gemini-2.0-flash-001",
            "messages": [
                {
                    "role": "system",
                    "content": "You are Nihit AI developed by Nihit Kr. Use ```html blocks for code.",
                }
            ]
            + msgs
            + [{"role": "user", "content": msg}],
        }

        r = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {os.environ.get('OPENROUTER_KEY')}"
            },
            json=payload,
            timeout=60,
        )

        return r.json()["choices"][0]["message"]["content"]

    except Exception as e:
        return f"Error: {str(e)}"


@app.route("/")
def index():
    return redirect("/chat") if "user" in session else UI_LOGIN


@app.route("/login")
def login():
    return google.authorize_redirect(
        url_for("callback", _external=True, _scheme="https")
    )


@app.route("/callback")
def callback():
    google.authorize_access_token()
    resp = google.get("https://www.googleapis.com/oauth2/v2/userinfo")
    session["user"] = resp.json()["email"]
    return redirect("/chat")


@app.route("/chat")
def chat_page():
    if "user" not in session:
        return redirect("/")

    today = datetime.datetime.now().strftime("%Y-%m-%d")
    u = get_db().execute(
        "SELECT chats FROM usage WHERE user=? AND date=?",
        (session["user"], today),
    ).fetchone()

    return UI_HTML.replace("{{c}}", str(u[0] if u else 0))


@app.route("/send", methods=["POST"])
def send_msg():
    if "user" not in session:
        return jsonify({"reply": "Login required"})

    db = get_db()

    msg = request.form.get("msg")
    cid = request.form.get("chat")
    user = session["user"]

    today = datetime.datetime.now().strftime("%Y-%m-%d")

    u = db.execute(
        "SELECT chats FROM usage WHERE user=? AND date=?",
        (user, today),
    ).fetchone()

    c_count = u[0] if u else 0

    if c_count >= 50:
        return jsonify({"reply": "Daily limit over", "c": c_count})

    if not cid or cid == "null":
        cid = str(int(time.time()))
        db.execute("INSERT INTO chats VALUES(?,?,?)", (cid, user, msg[:30]))

    reply = ai(msg, cid)

    db.execute("INSERT INTO messages VALUES(?,?,?)", (cid, "user", msg))
    db.execute("INSERT INTO messages VALUES(?,?,?)", (cid, "assistant", reply))
    db.execute(
        "INSERT OR REPLACE INTO usage VALUES(?,?,?)",
        (user, today, c_count + 1),
    )

    db.commit()

    return jsonify({"reply": reply, "chat_id": cid, "c": c_count + 1})


@app.route("/history")
def history():
    if "user" not in session:
        return jsonify([])

    rows = get_db().execute(
        "SELECT id, title FROM chats WHERE user=? ORDER BY id DESC",
        (session["user"],),
    ).fetchall()

    return jsonify(rows)


UI_LOGIN = """
<body style="background:#000;color:#fff;display:flex;align-items:center;justify-content:center;height:100vh;font-family:sans-serif;">
<div style="text-align:center;">
<h1>Nihit AI</h1>
<a href="/login" style="background:#fff;color:#000;padding:12px 24px;text-decoration:none;border-radius:30px;font-weight:bold;">Sign in with Google</a>
</div>
</body>
"""

UI_HTML = """
<!DOCTYPE html>
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Nihit AI</title>
<style>
body{margin:0;background:#0d0d0d;color:white;font-family:sans-serif}
.sidebar{position:fixed;left:0;top:0;bottom:0;width:260px;background:#151515;padding:15px}
.main{margin-left:260px;height:100vh;display:flex;flex-direction:column}
#box{flex:1;overflow:auto;padding:20px}
.bubble{padding:12px;border-radius:15px;margin:10px 0;max-width:75%}
.user{background:#2563eb;margin-left:auto}
.ai{background:#222}
.bar{display:flex;padding:12px;border-top:1px solid #333}
.bar input{flex:1;padding:12px;background:#111;border:none;color:white}
button{padding:10px 16px}
</style>
</head>
<body>

<div class="sidebar">
<div>DAILY USAGE: <span id="c-tag">{{c}}</span>/50</div>
<h2>Nihit AI</h2>
</div>

<div class="main">
<div id="box"></div>
<div class="bar">
<input id="in" placeholder="Type message...">
<button onclick="send()">Send</button>
</div>
</div>

<script>
let cid = null;

async function send(){
    const i = document.getElementById("in");
    if(!i.value) return;

    const box = document.getElementById("box");
    box.innerHTML += `<div class="bubble user">${i.value}</div>`;

    const fd = new FormData();
    fd.append("msg", i.value);
    fd.append("chat", cid);

    i.value = "";

    const r = await fetch("/send", {method:"POST", body:fd});
    const d = await r.json();

    cid = d.chat_id;
    document.getElementById("c-tag").innerText = d.c;
    box.innerHTML += `<div class="bubble ai">${d.reply}</div>`;
    box.scrollTop = box.scrollHeight;
}
</script>

</body>
</html>
"""

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
