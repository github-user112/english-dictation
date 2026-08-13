"""英语听打系统 - Flask 入口"""
from backend import create_app

app = create_app()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8200, debug=False)
