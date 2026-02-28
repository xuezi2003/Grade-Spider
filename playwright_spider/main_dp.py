"""
CDUT 教务系统 DrissionPage 自动登录 + 课表采集
使用 DrissionPage 接管真实 Chrome，绕过瑞数 WAF
"""

import sys
import time
from DrissionPage import Chromium, ChromiumOptions

LOGIN_URL = (
    "https://cas.paas.cdut.edu.cn/cas/login"
    "?service=http%3A%2F%2Fjw.cdut.edu.cn%2Fsso%2Flogin.jsp"
    "%3FtargetUrl%3Dbase64aHR0cDovL2p3LmNkdXQuZWR1LmNuL0xvZ29uLmRvP21ldGhvZD1sb2dvblNTT2NkbGdkeA%3D%3D"
)
JW_BASE = "https://jw.cdut.edu.cn"
KBJCMSID = "7E5976C91D9A4146930951FD11516BCC"


def login(tab, username: str, password: str) -> bool:
    """登录 CAS，成功返回 True"""
    tab.get(LOGIN_URL)
    tab.wait.doc_loaded()

    user_input = tab.ele('css:input[placeholder*="Username"],input[placeholder*="用户名"]', timeout=10)
    if not user_input:
        print("❌ 找不到用户名输入框")
        return False

    user_input.input(username)
    tab.ele('css:input[placeholder*="Password"],input[placeholder*="密码"]').input(password)
    btn = tab.ele('css:input[type="button"]') or tab.ele('text:登录')
    btn.click()

    # 等待跳转到教务框架页
    for i in range(20):
        time.sleep(1)
        if "jsxsd/framework" in tab.url:
            print("✅ 登录成功")
            return True
    print("❌ 登录失败，请检查账号密码")
    return False


def get_terms(tab) -> list[str]:
    """获取学期列表"""
    result = tab.run_js("""
        const xhr = new XMLHttpRequest();
        xhr.open('GET', '/jsxsd/xskb/xsqtkb.do', false);
        xhr.send();
        if (xhr.status !== 200) return [];
        const doc = new DOMParser().parseFromString(xhr.responseText, 'text/html');
        const sel = doc.getElementById('xnxq01id');
        if (!sel) return [];
        return Array.from(sel.options).map(o => o.value).filter(v => v);
    """)
    return result or []


def fetch_students(tab, keyword: str) -> list[dict]:
    """搜索学生"""
    result = tab.run_js(f"""
        const xhr = new XMLHttpRequest();
        xhr.open('POST', '/jsxsd/xskb/cxxs', false);
        xhr.setRequestHeader('Content-Type', 'application/x-www-form-urlencoded; charset=UTF-8');
        xhr.setRequestHeader('X-Requested-With', 'XMLHttpRequest');
        xhr.send('maxRow=100000000&xsmc={keyword}');
        if (xhr.status !== 200) return [];
        let data;
        try {{ data = JSON.parse(xhr.responseText); }} catch(e) {{ return []; }}
        if (!data.result || !data.list) return [];
        return data.list.filter(item =>
            item.xh && /^\\d{{12}}$/.test(item.xh) && item.xh.startsWith('{keyword}')
        );
    """)
    return result or []


def fetch_schedule(tab, student_id: str, term: str) -> str:
    """获取课表 HTML（tab3 + tab2）"""
    result = tab.run_js(f"""
        const url = '/jsxsd/xskb/viewtable.do'
            + '?xnxq01id={term}&kbjcmsid={KBJCMSID}'
            + '&xs0101id={student_id}&lx=xs0101id';
        const xhr = new XMLHttpRequest();
        xhr.open('GET', url, false);
        xhr.send();
        if (xhr.status !== 200) return '';
        const doc = new DOMParser().parseFromString(xhr.responseText, 'text/html');
        const tab3 = doc.querySelector('table.tab3');
        const tab2 = doc.querySelector('table.tab2');
        if (!tab3 && !tab2) return '';
        return (tab3 ? tab3.outerHTML : '') + (tab2 ? tab2.outerHTML : '');
    """)
    return result or ""


def get_terms_for_student(student_id: str, all_terms: list[str]) -> list[str]:
    year = int(student_id[:4])
    start = f"{year}-{year + 1}-1"
    idx = all_terms.index(start) if start in all_terms else -1
    if idx == -1:
        return [t for t in all_terms if t >= start]
    return list(reversed(all_terms[:idx + 1]))


def collect_schedules(tab, keyword: str):
    print(f"\n📋 正在获取学期列表...")
    all_terms = get_terms(tab)
    print(f"   共 {len(all_terms)} 个学期: {all_terms[:3]}{'...' if len(all_terms) > 3 else ''}")

    print(f"\n🔍 正在搜索学号前缀 '{keyword}' 的学生...")
    students = fetch_students(tab, keyword)
    print(f"   找到 {len(students)} 名学生")

    if not students:
        return

    total_ok = total_empty = total_fail = 0
    for stu in students[:5]:  # 先测试前5个
        sid, name = stu["xh"], stu.get("xsmc", "")
        terms = get_terms_for_student(sid, all_terms)
        print(f"\n👤 {sid} {name}  ({len(terms)} 个学期)")
        for term in terms:
            try:
                html = fetch_schedule(tab, sid, term)
                if html:
                    total_ok += 1
                    print(f"   ✅ {term}  ({len(html)} chars)")
                else:
                    total_empty += 1
                    print(f"   ○  {term}  (空)")
            except Exception as e:
                total_fail += 1
                print(f"   ❌ {term}  ({e})")

    print(f"\n📊 汇总: 有效 {total_ok} / 空 {total_empty} / 失败 {total_fail}")


def main(username: str, password: str, keyword: str = "2022", proxy: str = ""):
    co = ChromiumOptions()
    co.auto_port()
    # Linux 服务器: 用 xvfb-run 启动脚本代替 headless，WAF 会检测 headless
    # 例: xvfb-run python main_dp.py user pass 2022 --proxy http://127.0.0.1:7890
    co.set_argument('--no-sandbox')
    co.set_argument('--disable-gpu')
    if proxy:
        co.set_proxy(proxy)
        print(f"   代理: {proxy}")

    browser = Chromium(co)
    tab = browser.latest_tab

    if not login(tab, username, password):
        browser.quit()
        return

    # 等待页面完全加载（包括 WAF 质询完成后 JS 加载）
    tab.wait.doc_loaded()
    for _ in range(30):
        if tab.run_js("return typeof jQuery !== 'undefined'"):
            break
        time.sleep(1)
    else:
        print("❌ jQuery 未加载，WAF 质询可能未通过")
        browser.quit()
        return

    collect_schedules(tab, keyword)
    browser.quit()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="CDUT 课表采集")
    parser.add_argument("username", help="CAS 用户名")
    parser.add_argument("password", help="CAS 密码")
    parser.add_argument("keyword", nargs="?", default="2022", help="学号前缀 (默认 2022)")
    parser.add_argument("--proxy", "-p", default="", help="代理地址，如 http://127.0.0.1:7890")
    args = parser.parse_args()
    main(args.username, args.password, args.keyword, args.proxy)
