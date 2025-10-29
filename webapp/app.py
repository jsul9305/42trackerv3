"""Flask App Factory"""

from flask import Flask

from config.settings import BASE_DIR


def create_app():
    """Flask 애플리케이션을 생성하고 설정합니다."""
    app = Flask(
        __name__,
        template_folder=BASE_DIR / "templates",
        static_folder=None  # static_routes에서 직접 처리하므로 None으로 설정
    )

    # Blueprint 등록
    from webapp.routes.api import api_bp
    from webapp.routes.pages import pages_bp
    from webapp.routes.static_routes import static_bp
    app.register_blueprint(api_bp)
    app.register_blueprint(pages_bp)
    app.register_blueprint(static_bp)

    return app