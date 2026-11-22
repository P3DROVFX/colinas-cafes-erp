from pathlib import Path

from streamlit.testing.v1 import AppTest

from core.config import PROJECT_ROOT

APP_FILE = str(Path(PROJECT_ROOT) / "app.py")
ADMIN_EMAIL = "admin@colinas.com.br"


def run_app(user: dict | None = None) -> AppTest:
    app = AppTest.from_file(APP_FILE)
    app.secrets["app"] = {"admin_emails": [ADMIN_EMAIL]}
    if user is not None:
        app.user = {"is_logged_in": True, **user}
    return app.run(timeout=30)


def sidebar_text(app: AppTest) -> str:
    return " ".join(element.value for element in app.sidebar.markdown)


def test_logged_out_visitor_sees_login_page(database_url):
    app = run_app()
    assert not app.exception
    assert [button.label for button in app.button] == ["Entrar com Google"]


def test_admin_lands_on_home_page(database_url):
    app = run_app({"email": ADMIN_EMAIL, "name": "Ana Admin"})
    assert not app.exception
    assert app.title[0].value == "Olá, Ana!"
    assert "Perfil: Administrador" in [caption.value for caption in app.sidebar.caption]


def test_new_google_account_signs_in_as_viewer(database_url):
    app = run_app({"email": "Novo.Usuario@gmail.com", "name": "Novo Usuário"})
    assert not app.exception
    assert "novo.usuario@gmail.com" in sidebar_text(app)
    assert "Perfil: Visitante" in [caption.value for caption in app.sidebar.caption]
