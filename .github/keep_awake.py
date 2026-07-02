"""무료 Streamlit 앱이 잠들지 않도록 주기적으로 방문/깨우는 스크립트."""
import os
from playwright.sync_api import sync_playwright

URL = os.environ.get("STREAMLIT_URL", "").strip()
if not URL:
    # 배포 전이라 URL이 아직 없으면 실패시키지 않고 건너뛴다.
    # 배포 후 repo Settings > Secrets and variables > Actions > Variables 에
    # STREAMLIT_URL 을 추가하면 그때부터 6시간마다 깨운다.
    print("STREAMLIT_URL 미설정 — 배포 후 repo Variable(STREAMLIT_URL)을 추가하세요. 이번 실행은 건너뜀.")
    raise SystemExit(0)

with sync_playwright() as pw:
    browser = pw.chromium.launch()
    page = browser.new_page()
    print(f"방문: {URL}")
    page.goto(URL, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(4000)
    # 앱이 자고 있으면 "Yes, get this app back up!" 버튼이 보인다 -> 클릭
    try:
        btn = page.get_by_text("get this app back up", exact=False)
        if btn.count() > 0:
            print("앱이 잠들어 있어 깨우기 버튼 클릭")
            btn.first.click()
            page.wait_for_timeout(30000)  # 스핀업 대기
        else:
            print("이미 깨어 있음")
    except Exception as e:
        print("깨우기 버튼 없음/이미 활성:", e)
    page.wait_for_timeout(5000)
    print("완료. 제목:", page.title())
    browser.close()
