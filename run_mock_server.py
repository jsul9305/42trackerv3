# c:/toolpy/42tracker/42tracker/run_mock_server.py
import os
from flask import Flask, render_template_string, abort, render_template

# --- Mock Server ---
# 이 파일은 크롤러 파서 테스트를 위한 간단한 목(Mock) 서버입니다.
# 실제 마라톤 사이트의 HTML 구조를 흉내내어,
# 네트워크 연결 없이도 파서가 올바르게 동작하는지 검증할 수 있습니다.
#
# 실행: python run_mock_server.py
#
# 사용법:
# 1. 이 스크립트를 실행하여 목 서버를 켭니다 (기본 포트 5001).
# 2. 42Tracker 관리자 페이지에서 새 대회를 등록합니다.
# 3. URL 템플릿에 아래 주소 중 하나를 입력합니다.
#    - Smartchip: http://127.0.0.1:5001/mock/smartchip/{nameorbibno}
#    - SPCT:      http://127.0.0.1:5001/mock/spct/{nameorbibno}
#    - MyResult:  http://127.0.0.1:5001/mock/myresult/{nameorbibno}
# 4. 해당 대회에 참가자를 추가하면, 크롤러가 이 목 서버의 데이터를 가져갑니다.


app = Flask(__name__, template_folder="mocks")

@app.route('/')
def index():
    return """
    <h1>42Tracker Mock Server</h1>
    <p>크롤러 테스트를 위한 목업 페이지를 제공합니다.</p>
    <ul>
        <li><a href="/mock/smartchip/101">Smartchip 테스트 (/mock/smartchip/&lt;bib&gt;)</a></li>
        <li><a href="/mock/spct/202">SPCT 테스트 (/mock/spct/&lt;bib&gt;)</a></li>
        <li><a href="/mock/myresult/303">MyResult 테스트 (/mock/myresult/&lt;bib&gt;)</a></li>
    </ul>
    """

@app.route('/mock/<site>/<bib>')
def serve_mock_page(site, bib):
    """
    사이트 종류에 맞는 목업 HTML을 렌더링합니다.
    BIB 번호를 HTML 내에 주입하여 동적으로 보이게 합니다.
    """
    template_map = {
        "smartchip": "smartchip_sample.html",
        "spct": "spct_sample.html",
        "myresult": "myresult_sample.html",
    }

    template_name = template_map.get(site)
    if not template_name:
        abort(404, "Unknown site")

    # 템플릿 파일이 존재하는지 확인
    if not os.path.exists(os.path.join("mocks", template_name)):
        abort(404, f"Template not found: {template_name}")

    return render_template(template_name, bib=bib, name=f"테스트_{bib}")

if __name__ == '__main__':
    print("="*50)
    print("🚀 42Tracker Mock Server is running at http://127.0.0.1:5001")
    print("   테스트를 위해 이 터미널을 켜두세요.")
    print("="*50)
    app.run(host='0.0.0.0', port=5001, debug=False)