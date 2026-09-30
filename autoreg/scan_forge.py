import urllib.request
import urllib.error

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

for host in ("https://notabug.org", "https://git.disroot.org", "https://gitea.com",
             "https://git.tilde.team", "https://git.hardenedbsd.org", "https://framagit.org"):
    try:
        req = urllib.request.Request(host + "/user/sign_up", headers=UA)
        with urllib.request.urlopen(req, timeout=25) as r:
            html = r.read().decode("utf-8", "ignore")
        cap = "captcha" in html.lower()
        fields = [s for s in ("user_name", "email", "password", "retype") if s in html]
        print(f"{host:34s} {r.status} fields={len(fields)} captcha={cap}")
    except urllib.error.HTTPError as e:
        print(f"{host:34s} HTTP {e.code}")
    except Exception as e:
        print(f"{host:34s} ERR {str(e)[:60]}")
