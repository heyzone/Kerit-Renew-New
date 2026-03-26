import os
import time
import imaplib
import email
import re
import subprocess
import urllib.request
import urllib.parse
from seleniumbase import SB

_account = os.environ["KERIT_ACCOUNT"].split(",")
KERIT_EMAIL    = _account[0].strip()
GMAIL_PASSWORD = _account[1].strip()

LOCAL_PROXY    = "http://127.0.0.1:8080"
MASKED_EMAIL   = "******@" + KERIT_EMAIL.split("@")[1]

LOGIN_URL      = "https://billing.kerit.cloud/"
FREE_PANEL_URL = "https://billing.kerit.cloud/free_panel"

_tg_raw = os.environ.get("TG_BOT", "")
if _tg_raw and "," in _tg_raw:
    _tg = _tg_raw.split(",")
    TG_CHAT_ID = _tg[0].strip()
    TG_TOKEN   = _tg[1].strip()
else:
    TG_CHAT_ID = ""
    TG_TOKEN   = ""


def now_str():
    import datetime
    return datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def send_tg(result, server_id=None, remaining=None):
    lines = [
        f"🎮 Kerit 服务器续期通知",
        f"🕐 运行时间: {now_str()}",
    ]
    if server_id is not None:
        lines.append(f"🖥 服务器ID: {server_id}")
    lines.append(f"📊 续期结果: {result}")
    if remaining is not None:
        lines.append(f"⏱️ 剩余天数: {remaining}天")
    msg = "\n".join(lines)

    if not TG_TOKEN or not TG_CHAT_ID:
        print("⚠️ TG未配置")
        return

    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    data = urllib.parse.urlencode({
        "chat_id": TG_CHAT_ID,
        "text": msg,
    }).encode()

    try:
        urllib.request.urlopen(url, data=data, timeout=10)
    except:
        pass


# ============================================================
# Gmail OTP
# ============================================================

def fetch_otp_from_gmail(wait_seconds=60) -> str:
    deadline = time.time() + wait_seconds

    mail = imaplib.IMAP4_SSL("imap.gmail.com")
    mail.login(KERIT_EMAIL, GMAIL_PASSWORD)
    mail.select("INBOX")

    while time.time() < deadline:
        time.sleep(5)

        _, data = mail.uid("search", None, "UNSEEN")
        uids = data[0].split()

        for uid in reversed(uids[-5:]):
            _, msg_data = mail.uid("fetch", uid, "(RFC822)")
            msg = email.message_from_bytes(msg_data[0][1])

            body = msg.get_payload(decode=True)
            if not body:
                continue

            text = body.decode("utf-8", errors="ignore")
            m = re.search(r'\b(\d{4})\b', text)
            if m:
                mail.logout()
                return m.group(1)

    mail.logout()
    raise TimeoutError("OTP获取失败")


# ============================================================
# xdotool
# ============================================================

def xdotool_click(x, y):
    try:
        subprocess.run(["xdotool", "mousemove", str(x), str(y)])
        subprocess.run(["xdotool", "click", "1"])
        return True
    except:
        return False


def get_window_offset(sb):
    try:
        info = sb.execute_script("""
            return {
                x: window.screenX || 0,
                y: window.screenY || 0,
                outer: window.outerHeight,
                inner: window.innerHeight
            }
        """)
        toolbar = info['outer'] - info['inner']
        return info['x'], info['y'], toolbar
    except:
        return 0, 0, 87


# ============================================================
# Turnstile（保留）
# ============================================================

def turnstile_exists(sb):
    return sb.execute_script(
        "return document.querySelector('input[name=\"cf-turnstile-response\"]') !== null"
    )


def check_token(sb):
    return sb.execute_script(
        "var i=document.querySelector('input[name=\"cf-turnstile-response\"]'); return i&&i.value.length>20;"
    )


def solve_turnstile(sb):
    if check_token(sb):
        return True
    return False


def get_token_value(sb):
    return sb.execute_script(
        "var i=document.querySelector('input[name=\"cf-turnstile-response\"]'); return i?i.value:'';"
    )


# ============================================================
# 页面数据
# ============================================================

def wait_for_page_data(sb, timeout=20):
    for _ in range(timeout):
        data = sb.execute_script("""
            var el=document.querySelector('[id*="renew"][id*="count"]');
            var exp=document.querySelector('[id*="remaining"]');
            return {
                count: el?parseInt(el.innerText):0,
                remaining: exp?parseInt(exp.innerText):0,
                server_id: window.serverData?serverData.id:null
            }
        """)
        if data.get("server_id"):
            return data
        time.sleep(1)
    return {}


def get_renew_button_rect(sb):
    return sb.execute_script("""
        var btn=[...document.querySelectorAll('button')]
        .find(x=>x.innerText.toLowerCase().includes('renew'));
        if(!btn) return null;
        var r=btn.getBoundingClientRect();
        return {x:r.x,y:r.y,w:r.width,h:r.height};
    """)


# ============================================================
# ⭐⭐⭐ 核心修复版续期逻辑 ⭐⭐⭐
# ============================================================

def do_renew(sb):

    sb.open(FREE_PANEL_URL)
    time.sleep(5)

    page_data = wait_for_page_data(sb)

    server_id = page_data.get("server_id")
    count = page_data.get("count", 0)

    need = 7 - count

    for attempt in range(need):

        print(f"🔁 第{attempt+1}次续期... 当前:{count}")

        rect = get_renew_button_rect(sb)
        win_x, win_y, toolbar = get_window_offset(sb)

        x = rect["x"] + rect["w"]/2 + win_x
        y = rect["y"] + rect["h"]/2 + win_y + toolbar

        xdotool_click(x, y)
        time.sleep(2)

        # 等待变化
        time.sleep(3)

        # =========================
        # ✅ 修复点1：检测是否已续期
        # =========================
        new_count = sb.execute_script("""
            var el=document.querySelector('[id*="renew"][id*="count"]');
            return el?parseInt(el.innerText):0;
        """)

        if new_count > count:
            print(f"✅ 自动续期成功 {count}->{new_count}")
            count = new_count
            continue

        # =========================
        # 走验证码流程（如果有）
        # =========================
        if turnstile_exists(sb):
            if not solve_turnstile(sb):
                send_tg("❌ Turnstile失败")
                return

            token = get_token_value(sb)

            sb.execute_script(f"""
                fetch('/api/renew', {{
                    method:'POST',
                    body:JSON.stringify({{id:'{server_id}',captcha:'{token}'}})
                }});
            """)

            time.sleep(3)

            new_count = sb.execute_script("""
                var el=document.querySelector('[id*="renew"][id*="count"]');
                return el?parseInt(el.innerText):0;
            """)

            if new_count > count:
                print(f"✅ 验证码续期成功 {count}->{new_count}")
                count = new_count
                continue

        # =========================
        # ✅ 修复点2：备用点击后再检测
        # =========================
        try:
            sb.click('//button[contains(., "renew")]')
            time.sleep(3)

            new_count = sb.execute_script("""
                var el=document.querySelector('[id*="renew"][id*="count"]');
                return el?parseInt(el.innerText):0;
            """)

            if new_count > count:
                print(f"✅ 备用点击成功 {count}->{new_count}")
                count = new_count
                continue
        except:
            pass

        # =========================
        # ✅ 修复点3：最终兜底判断
        # =========================
        time.sleep(2)

        final_check = sb.execute_script("""
            var el=document.querySelector('[id*="renew"][id*="count"]');
            return el?parseInt(el.innerText):0;
        """)

        if final_check > count:
            print(f"✅ 最终确认成功 {count}->{final_check}")
            count = final_check
            continue

        print("❌ 本次续期失败")
        send_tg("❌ 续期失败", server_id)
        return

    send_tg("✅ 全部续期完成", server_id)


# ============================================================
# 主流程
# ============================================================

def run_script():

    with SB(uc=True, proxy=LOCAL_PROXY) as sb:

        sb.open(LOGIN_URL)
        time.sleep(3)

        sb.type('#email-input', KERIT_EMAIL)
        sb.click('button')

        sb.wait_for_element_visible('.otp-input')

        code = fetch_otp_from_gmail()

        inputs = sb.find_elements('.otp-input')
        for i, c in enumerate(code):
            inputs[i].send_keys(c)

        sb.click('button')

        time.sleep(5)

        do_renew(sb)


if __name__ == "__main__":
    run_script()
