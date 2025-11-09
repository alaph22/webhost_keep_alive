import os
import time
import requests
from datetime import datetime, timedelta
from playwright.sync_api import sync_playwright

# -------------------------------
log_buffer = []

def log(msg):
    print(msg)
    log_buffer.append(msg)
# -------------------------------

# Telegram 推送函数
def send_tg_log():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("⚠️ Telegram 未配置，跳过推送")
        return

    utc_now = datetime.utcnow()
    beijing_now = utc_now + timedelta(hours=8)
    now_str = beijing_now.strftime("%Y-%m-%d %H:%M:%S") + " UTC+8"

    final_msg = f"📌 webhostmost 保活执行日志\n🕒 {now_str}\n\n" + "\n".join(log_buffer)

    for i in range(0, len(final_msg), 3900):
        chunk = final_msg[i:i+3900]
        try:
            resp = requests.get(
                f"https://api.telegram.org/bot{token}/sendMessage",
                params={"chat_id": chat_id, "text": chunk},
                timeout=10
            )
            if resp.status_code == 200:
                print(f"✅ Telegram 推送成功 [{i//3900 + 1}]")
            else:
                print(f"⚠️ Telegram 推送失败 [{i//3900 + 1}]: HTTP {resp.status_code}, 响应: {resp.text}")
        except Exception as e:
            print(f"⚠️ Telegram 推送异常 [{i//3900 + 1}]: {e}")

# 从环境变量解析多个账号
accounts_env = os.environ.get("SITE_ACCOUNTS", "")
accounts = []

for item in accounts_env.split(";"):
    if item.strip():
        try:
            username, password = item.split(",", 1)
            accounts.append({"username": username.strip(), "password": password.strip()})
        except ValueError:
            log(f"⚠️ 忽略格式错误的账号项: {item}")

fail_msgs = [
    "Invalid credentials.",
    "Not connected to server.",
    "Error with the login: login size should be between 2 and 50 (currently: 1)"
]

import re
import time
from datetime import datetime

def login_account(playwright, USER, PWD, max_retries: int = 2):
    attempt = 0
    while attempt <= max_retries:
        attempt += 1
        log(f"🚀 开始登录账号: {USER} (尝试 {attempt}/{max_retries + 1})")
        browser = None
        context = None
        page = None
        try:
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context()
            page = context.new_page()

            page.goto("https://client.webhostmost.com/login", timeout=60000)
            page.wait_for_load_state("networkidle", timeout=60000)
            time.sleep(1)

            # === Step 1: 填用户名 ===
            input_selectors = [
                "#inputEmail", "#inputUsername", "#username", "input[name='username']",
                "input[name='email']", "input[type='email']"
            ]
            for selector in input_selectors:
                try:
                    page.wait_for_selector(selector, timeout=5000)
                    page.fill(selector, USER)
                    log(f"📝 使用字段 {selector} 填入用户名/邮箱")
                    break
                except:
                    continue

            # === Step 2: 填密码 ===
            password_selectors = ["#inputPassword", "input[name='password']", "input[type='password']", "#password"]
            for selector in password_selectors:
                try:
                    page.wait_for_selector(selector, timeout=5000)
                    page.fill(selector, PWD)
                    log(f"🔒 使用字段 {selector} 填入密码")
                    break
                except:
                    continue

            time.sleep(0.8)

            # === Step 3: 提交表单 ===
            submitted = False
            button_labels = ["Login", "Sign in", "Sign In", "Validate", "Submit", "Log in"]
            for label in button_labels:
                try:
                    page.get_by_role("button", name=label).click(timeout=3000)
                    log(f"🔘 点击按钮 '{label}'")
                    submitted = True
                    break
                except:
                    continue
            if not submitted:
                try:
                    page.evaluate("document.querySelector('form')?.submit()")
                    log("🔘 使用JS提交表单")
                except:
                    page.press("#inputPassword", "Enter")
                    log("🔘 使用回车键提交")

            # === Step 4: 等待页面变化 ===
            try:
                page.wait_for_load_state("networkidle", timeout=60000)
            except:
                log("⚠️ 页面未完全加载，但继续检查内容")
            time.sleep(3)

            # === Step 5: 检查登录结果 ===
            success_signs = ["Client Area", "Dashboard", "My Services"]
            fail_msgs = ["Invalid login", "Incorrect", "Login failed"]

            html = page.content()
            if any(sign.lower() in html.lower() for sign in success_signs):
                log(f"✅ 账号 {USER} 登录成功")

                # === ✅ Step 6: 登录成功后获取倒计时信息 ===
                # 登录成功后，尝试提取倒计时信息
try:
    # 等待包含倒计时的元素出现（最多等待10秒）
    page.wait_for_selector("text=Time until suspension", timeout=10000)

    # 获取包含这段文本的完整内容
    countdown_elem = page.query_selector("text=Time until suspension")
    countdown_text = countdown_elem.text_content().strip() if countdown_elem else ""

    # 用正则提取时间段（如“44d 23h 57m 40s”）
    import re
    match = re.search(r"(\d+d\s+\d+h\s+\d+m\s+\d+s)", countdown_text)
    if match:
        remaining_time = match.group(1)
        log(f"⏱️ 登录后检测到倒计时: {remaining_time}")
    else:
        log("⚠️ 登录成功，但未检测到倒计时文本")
except Exception as e:
    log(f"⚠️ 登录成功，但提取倒计时时出错: {e}")


                # 清理资源
                context.close()
                browser.close()
                return

            elif any(msg.lower() in html.lower() for msg in fail_msgs):
                log(f"❌ 账号 {USER} 登录失败（检测到错误提示）")
                raise RuntimeError("login-failed")
            else:
                log("⚠️ 未检测到成功或失败标识，可能页面延迟或结构变化")
                raise RuntimeError("login-unknown")

        except Exception as e:
            log(f"❌ 账号 {USER} 尝试 ({attempt}) 异常: {e}")
            if attempt <= max_retries:
                wait_sec = 5 + attempt * 5
                log(f"⏳ {wait_sec}s 后重试...")
                time.sleep(wait_sec)
                try:
                    if context: context.close()
                    if browser: browser.close()
                except:
                    pass
                continue
            else:
                log(f"❌ 账号 {USER} 登录最终失败（{max_retries + 1} 次尝试）")
                try:
                    if context: context.close()
                    if browser: browser.close()
                except:
                    pass
                return



def run():
    with sync_playwright() as playwright:
        for acc in accounts:
            login_account(playwright, acc["username"], acc["password"])
            time.sleep(2)

if __name__ == "__main__":
    run()
    send_tg_log()  # 发送日志
