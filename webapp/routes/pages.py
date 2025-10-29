from flask import Blueprint, render_template, request, redirect, url_for

from webapp.services.records import RecordsService
from webapp.services.marathon import MarathonService  # Import MarathonService module


pages_bp = Blueprint('pages', __name__)


@pages_bp.route("/")
def page_index():
    # 리스트 뷰
    return render_template("index.html", init_mid=None)

@pages_bp.route("/race/<int:mid>")
def page_race_mid(mid: int):
    # 특정 대회 뷰 (직접 경로)
    return render_template("index.html", init_mid=mid)

@pages_bp.route("/race")
def page_race_qs():
    # 쿼리스트링 ?marathon_id= 로 진입
    mid = request.args.get("marathon_id", type=int)
    if not mid:
        return redirect(url_for("pages.page_index"))
    return render_template("index.html", init_mid=mid)

@pages_bp.route("/admin")
def page_admin():
    return render_template("admin.html")

@pages_bp.route("/records")
def ui_records():
    q = request.args.get("q", "").strip()
    m = request.args.get("m", "").strip()
    items = RecordsService.get_all_records(query=q, marathon_filter=m)
    return render_template("records.html", items=items, q=q, m=m)

# ================== 신규: 참여 코드 진입 ==================
@pages_bp.route("/code/<string:join_code>")
def page_join_code(join_code: str):
    """
    /code/<join_code>
    - join_code로 마라톤 조회
    - 유효하면 index.html을 init_mid로 열어 바로 해당 대회로 진입
    - 무효하면 메인으로 리다이렉트
    """
    code = (join_code or "").strip().upper()
    if not code:
        return redirect(url_for("pages.page_index"))

    m = MarathonService.get_marathon_by_join_code(code)
    if not m:
        # 유효하지 않은 코드 → 메인으로
        return redirect(url_for("pages.page_index"))

    # 유효한 코드 → 해당 대회로 진입
    return render_template("index.html", init_mid=m.get("id"))

@pages_bp.route("/group/<string:group_code>")
def page_group_code(group_code: str):
    code = (group_code or "").strip().upper()
    if not code:
        return redirect(url_for("pages.page_index"))

    # 그룹 유효성 확인 (없으면 메인으로)
    # 존재한다면 index.html 로 내려보내고, 프런트에서 code를 사용해 그룹 뷰를 열도록 해도 됨
    # 예: init_group_code를 Jinja 변수로 전달
    return render_template("index.html", init_mid=None, init_group_code=code)