import os
import time
import requests
from datetime import datetime, timedelta
# 导入 TimeoutError 以便专门捕获它
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
import re

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
         #           log(f"📝 使用字段 {selector} 填入用户名/邮箱")
                    break
                except:
                    continue

            # === Step 2: 填密码 ===
            password_selectors = ["#inputPassword", "input[name='password']", "input[type='password']", "#password"]
            for selector in password_selectors:
                try:
                    page.wait_for_selector(selector, timeout=5000)
                    page.fill(selector, PWD)
 #                   log(f"🔒 使用字段 {selector} 填入密码")
                    break
                except:
                    continue

            time.sleep(0.8)

            # === Step 3: 提交表单 ===
            submitted = False
            button_labels = ["Login", "Sign in", "Sign In", "Validate", "Submit", "Log in"]
            for label in button_labels:
                try:
                    # 使用 text= 匹配按钮文本
                    page.get_by_role("button", name=label, exact=True).click(timeout=3000)
                    log(f"🔘 点击按钮 '{label}'")
                    submitted = True
                    break
                except:
                    continue
            if not submitted:
                try:
                    page.evaluate("document.querySelector('form')?.submit()")
  #                  log("🔘 使用JS提交表单")
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
            fail_msgs_check = ["Invalid login", "Incorrect", "Login failed"] # 避免与外部变量名冲突

            html = page.content()
            if any(sign.lower() in html.lower() for sign in success_signs):
                log(f"✅ 账号 {USER} 登录成功")

                # === ✅ Step 6: 倒计时检查 (修复荷兰语匹配问题) ===
                
                # 各种语言的倒计时提示文本。
                # 修复点：将带有冒号的语言的短语去除冒号 (如 "Tijd tot schorsing:") 
                # 以提高 Playwright 'text=' 文本定位的鲁棒性，同时保留时间提取的有效性。
                countdown_phrases = {
                    "EN": "Time until suspension",          # 英文 (不带冒号)
                    "NL": "Tijd tot schorsing",            # 修复：去除冒号
                    "DE": "Zeit bis zur Sperrung",         # 修复：去除冒号
                    "JP": "停止までの時間",                # 修复：去除冒号
                    "ES": "Tiempo hasta la suspensión"     # 修复：去除冒号
                }
                
                try:
                    # --- 阶段1: 并发等待 (最高效) ---
 #                   log(f"🔍 正在并发等待 {len(countdown_phrases)} 种语言的倒计时...")
                    
                    # 构建不区分大小写的正则表达式
                    regex_pattern = "|".join(re.escape(t) for t in countdown_phrases.values())
                    selector_regex = f"text=/{regex_pattern}/i"
                    
                    # 等待任意一个出现 (10秒超时)
                    # 匹配到后，Playwright 会返回包含该文本的元素，该元素的 text_content() 应该包含完整倒计时
                    page.wait_for_selector(selector_regex, timeout=10000)
                    
                    # 获取匹配到的那个元素的文本
                    countdown_elem = page.query_selector(selector_regex)
                    if not countdown_elem:
                        # 应该在 wait_for_selector 处捕获，但作为后备检查
                        raise RuntimeError("Element not found after waiting.")
                    
                    countdown_text = countdown_elem.text_content().strip()
                    log(f"🔍 并发等待成功，检测到元素文本: {countdown_text}")

                    # 用正则提取时间段 (格式: 44d 23h 59m 19s)
                    match = re.search(r"(\d+d\s+\d+h\s+\d+m\s+\d+s)", countdown_text)
                    if match:
                        remaining_time = match.group(1)
                        log(f"⏱️ 登录后检测到倒计时: {remaining_time}")
                    else:
                        log(f"⚠️ 登录成功，检测到文本 '{countdown_text}'，但未匹配到时间格式")

                except PlaywrightTimeoutError:
                    # --- 阶段2: 并发等待超时，执行用户要求的“遍历”来复核 ---
                    log(f"⚠️ 并发等待 10 秒超时，未检测到倒计时。")
                    log("🔍 开始遍历复核 (使用 is_visible 检查当前页面)...")
                    
                    found_in_loop = False
                    # 遍历复核仍使用去除冒号后的短语
                    for lang, phrase in countdown_phrases.items():
                        # 使用 re.escape 确保特殊字符被正确处理
                        selector = f"text=/{re.escape(phrase)}/i"
                        elem = page.locator(selector).first
                        
                        # is_visible() 是立即检查，不等待
                        if elem.is_visible():
                            log(f"🔍 [遍历复核] ✅ 找到 ({lang}): '{phrase}'")
                            found_in_loop = True
                            
                            try:
                                found_text = elem.text_content().strip()
                                match = re.search(r"(\d+d\s+\d+h\s+\d+m\s+\d+s)", found_text)
                                if match:
                                    remaining_time = match.group(1)
                                    log(f"⏱️ [遍历复核] 提取倒计时: {remaining_time}")
                                else:
                                    log(f"⚠️ [遍历复核] 虽找到文本，但未匹配到时间格式: {found_text}")
                            except Exception as e_inner:
                                log(f"⚠️ [遍历复核] 提取文本时出错: {e_inner}")
                            break # 找到一个就行
                        else:
                            log(f"🔍 [遍历复核] ❌ 未立即可见 ({lang}): '{phrase}'")
                    
                    if not found_in_loop:
                        log("⚠️ [遍历复核] 确认页面上当前无倒计时显示。")

                except Exception as e:
                    # 捕获其他所有异常
                    log(f"⚠️ 登录成功，但在提取/处理倒计时文本时出错: {e}")
                # === Step 6 结束 ===

                # 清理资源
                context.close()
                browser.close()
                return

            elif any(msg.lower() in html.lower() for msg in fail_msgs_check):
                log(f"❌ 账号 {USER} 登录失败（检测到错误提示）")
                raise RuntimeError("login-failed")
            else:
                log("⚠️ 未检测到成功或失败标识，可能页面延迟或结构变化")
                # 抛出异常以触发重试
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
    if not accounts:
        log("❌ 未配置 SITE_ACCOUNTS 环境变量，请按 'username,password;...' 格式配置")
        return
    with sync_playwright() as playwright:
        for acc in accounts:
            login_account(playwright, acc["username"], acc["password"])
            time.sleep(2)

if __name__ == "__main__":
    run()
    send_tg_log() # 发送日志
