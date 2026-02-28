"""
CDUT 教务系统 Playwright 自动登录 + 课表采集
"""

import asyncio
import sys
from playwright.async_api import async_playwright, Page, BrowserContext

LOGIN_URL = (
    "https://cas.paas.cdut.edu.cn/cas/login"
    "?service=http%3A%2F%2Fjw.cdut.edu.cn%2Fsso%2Flogin.jsp"
    "%3FtargetUrl%3Dbase64aHR0cDovL2p3LmNkdXQuZWR1LmNuL0xvZ29uLmRvP21ldGhvZD1sb2dvblNTT2NkbGdkeA%3D%3D"
)
JW_BASE     = "https://jw.cdut.edu.cn"
KBJCMSID    = "7E5976C91D9A4146930951FD11516BCC"


async def login(context: BrowserContext, username: str, password: str) -> "Page | None":
    """Playwright 登录，成功返回已登录的 Page，失败返回 None"""
    page = await context.new_page()
    await page.goto(LOGIN_URL, wait_until="networkidle")
    # CAS 页面可能渲染中文或英文 placeholder
    username_input = page.locator(
        'input[placeholder*="Username"], input[placeholder*="用户名"]'
    ).first
    await username_input.wait_for(timeout=10000)

    await username_input.fill(username)
    await page.locator(
        'input[placeholder*="Password"], input[placeholder*="密码"]'
    ).first.fill(password)
    await page.locator(
        'input[type="button"]:visible, button:has-text("登录"):visible'
    ).first.click()

    try:
        await page.wait_for_url("**/jsxsd/framework/**", timeout=12000)
        print("✅ 登录成功")
        return page
    except Exception:
        print("❌ 登录失败，请检查账号密码")
        await page.close()
        return None


async def get_terms(page: Page) -> list[str]:
    """通过 jQuery ajax 获取课表页 HTML，解析学期下拉列表"""
    return await page.evaluate("""
        () => new Promise((resolve) => {
            jQuery.ajax({
                url: '/jsxsd/xskb/xsqtkb.do',
                method: 'GET',
                dataType: 'html',
                success: function(html) {
                    const doc = new DOMParser().parseFromString(html, 'text/html');
                    const sel = doc.getElementById('xnxq01id');
                    if (!sel) { resolve([]); return; }
                    resolve(Array.from(sel.options).map(o => o.value).filter(v => v));
                },
                error: function() { resolve([]); }
            });
        })
    """)


async def fetch_students(page: Page, keyword: str) -> list[dict]:
    """用 jQuery ajax 搜索学生"""
    return await page.evaluate(f"""
        () => new Promise((resolve) => {{
            jQuery.ajax({{
                url: '/jsxsd/xskb/cxxs',
                method: 'POST',
                data: 'maxRow=100000000&xsmc={keyword}',
                dataType: 'json',
                success: function(data) {{
                    if (!data.result || !data.list) {{ resolve([]); return; }}
                    resolve(data.list.filter(item =>
                        item.xh && /^\\d{{12}}$/.test(item.xh) && item.xh.startsWith('{keyword}')
                    ));
                }},
                error: function() {{ resolve([]); }}
            }});
        }})
    """)


async def fetch_schedule(page: Page, student_id: str, term: str) -> str:
    """获取课表 HTML（tab3 + tab2）"""
    return await page.evaluate(f"""
        () => new Promise((resolve) => {{
            jQuery.ajax({{
                url: '/jsxsd/xskb/viewtable.do',
                method: 'GET',
                data: {{
                    xnxq01id: '{term}',
                    kbjcmsid: '{KBJCMSID}',
                    xs0101id: '{student_id}',
                    lx: 'xs0101id'
                }},
                dataType: 'html',
                success: function(full) {{
                    const doc = new DOMParser().parseFromString(full, 'text/html');
                    const tab3 = doc.querySelector('table.tab3');
                    const tab2 = doc.querySelector('table.tab2');
                    if (!tab3 && !tab2) {{ resolve(''); return; }}
                    resolve((tab3 ? tab3.outerHTML : '') + (tab2 ? tab2.outerHTML : ''));
                }},
                error: function() {{ resolve(''); }}
            }});
        }})
    """)


def get_terms_for_student(student_id: str, all_terms: list[str]) -> list[str]:
    year = int(student_id[:4])
    start = f"{year}-{year + 1}-1"
    idx = all_terms.index(start) if start in all_terms else -1
    if idx == -1:
        return [t for t in all_terms if t >= start]
    return list(reversed(all_terms[:idx + 1]))


async def collect_schedules(page: Page, keyword: str):
    print(f"\n📋 正在获取学期列表...")
    all_terms = await get_terms(page)
    print(f"   共 {len(all_terms)} 个学期: {all_terms[:3]}{'...' if len(all_terms) > 3 else ''}")

    print(f"\n🔍 正在搜索学号前缀 '{keyword}' 的学生...")
    students = await fetch_students(page, keyword)
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
                html = await fetch_schedule(page, sid, term)
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


async def main(username: str, password: str, keyword: str = "2022"):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()

        page = await login(context, username, password)
        if page is None:
            await browser.close()
            return

        # 等待 jQuery 加载（WAF 质询完成后 JS 才会加载）
        for _ in range(30):
            has_jquery = await page.evaluate("typeof jQuery !== 'undefined'")
            if has_jquery:
                break
            await asyncio.sleep(1)
        else:
            print("❌ jQuery 未加载，WAF 质询可能未通过")
            await page.close()
            await browser.close()
            return

        await collect_schedules(page, keyword)
        await page.close()
        await browser.close()


if __name__ == "__main__":
    user    = sys.argv[1] if len(sys.argv) > 1 else input("用户名: ")
    pwd     = sys.argv[2] if len(sys.argv) > 2 else input("密码: ")
    keyword = sys.argv[3] if len(sys.argv) > 3 else input("学号前缀 (默认 2022): ") or "2022"
    asyncio.run(main(user, pwd, keyword))
