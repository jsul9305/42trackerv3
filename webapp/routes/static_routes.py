"""정적 파일 서빙 라우트"""

from flask import Blueprint, send_from_directory
from config.settings import STATIC_DIR

static_bp = Blueprint('static_routes', __name__)

# ★ 핵심: endpoint 이름을 'static'으로 맞춰준다.
@static_bp.route("/static/<path:filename>", endpoint="static")
def serve_static(filename):
    """/static/ 경로의 파일을 static 폴더에서 찾아 서빙합니다."""
    return send_from_directory(STATIC_DIR, filename)