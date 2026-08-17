"""生产启动前验证静态产物和所有素材文件。"""
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from backend.config import MATERIALS, STATIC_DIR
from backend.materials import load_material


def main():
    errors = []
    if not (STATIC_DIR / "index.html").is_file():
        errors.append(f"缺少前端构建产物：{STATIC_DIR / 'index.html'}")
    if not (STATIC_DIR / "assets").is_dir():
        errors.append(f"缺少前端资源目录：{STATIC_DIR / 'assets'}")

    for key in MATERIALS:
        try:
            items = load_material(key)
            if not items:
                errors.append(f"素材为空：{key}")
        except (OSError, ValueError) as exc:
            errors.append(f"素材不可用：{key}（{exc}）")

    if errors:
        print("运行环境检查失败：", file=sys.stderr)
        print("\n".join(f"- {error}" for error in errors), file=sys.stderr)
        return 1
    print(f"运行环境检查通过：{len(MATERIALS)} 套素材和前端静态产物已就绪")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
