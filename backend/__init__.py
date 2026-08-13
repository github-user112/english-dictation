"""Flask 应用工厂"""
from flask import Flask, send_from_directory

from . import catalog, db as dbmod, memorize, misc
from .config import STATIC_DIR


def create_app():
    app = Flask(__name__, static_folder=str(STATIC_DIR))
    dbmod.init_db()
    dbmod.migrate()
    for mod in (catalog, memorize, misc):
        app.register_blueprint(mod.bp)

    @app.get("/")
    def index():
        return send_from_directory(app.static_folder, "index.html")

    @app.get("/static/<path:filename>")
    def static_files(filename):
        return send_from_directory(app.static_folder, filename)

    return app
