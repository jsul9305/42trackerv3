# run_webapp_wsgi.py
# 실행 : waitress-serve --listen=127.0.0.1:5010 --threads=8 run_webapp_wsgi:app
from webapp.app import create_app

# create_app()으로 Flask 앱 객체 생성
app = create_app()