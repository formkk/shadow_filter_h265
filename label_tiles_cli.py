#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
瓦片人工标注并移动到分类目录的交互式脚本

- 输入目录下的瓦片图像逐张展示，按键选择类别后移动到输出目录对应子目录
- 支持无GUI模式（--no_gui），在终端输入类别编号进行标注
- 支持撤销上一步（按键 u）

用法示例：
python label_tiles_cli.py \
  --input_dir ./training_tiles/unknown \
  --output_dir ./training_tiles \
  --classes zhedang zhengchang

按键说明（GUI模式）：
- 1：标注为第1个类别（默认 zhedang）
- 2：标注为第2个类别（默认 zhengchang）
- s：跳过当前图片
- u：撤销上一次移动
- q：退出
"""

import argparse
import os
import sys
import time
import shutil
from pathlib import Path
import csv
from datetime import datetime

import cv2

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff"}


def list_images(input_dir: Path):
    files = []
    for p in sorted(input_dir.iterdir()):
        if p.is_file() and p.suffix.lower() in IMAGE_EXTS:
            files.append(p)
    return files


def safe_move(src: Path, dst_dir: Path, suffix: str = None) -> Path:
    dst_dir.mkdir(parents=True, exist_ok=True)
    base = src.stem
    ext = src.suffix
    if suffix is None:
        suffix = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    candidate = dst_dir / f"{base}_{suffix}{ext}"
    shutil.move(str(src), str(candidate))
    return candidate


def log_action(log_path: Path, action: dict):
    header = ["timestamp", "src", "dst", "class", "action"]
    write_header = not log_path.exists()
    with log_path.open("a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=header)
        if write_header:
            w.writeheader()
        w.writerow(action)


def show_image_with_text(img_path: Path, text: str):
    img = cv2.imread(str(img_path))
    if img is None:
        return False
    h, w = img.shape[:2]
    max_w, max_h = 1280, 720
    scale = min(max_w / max(w, 1), max_h / max(h, 1))
    if scale < 1.0:
        img = cv2.resize(img, (int(w * scale), int(h * scale)))
    overlay = img.copy()
    cv2.rectangle(overlay, (0, 0), (overlay.shape[1], 60), (0, 0, 0), -1)
    cv2.addWeighted(overlay, 0.6, img, 0.4, 0, img)
    cv2.putText(img, text, (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2, cv2.LINE_AA)
    cv2.imshow("Label Tiles", img)
    key = cv2.waitKey(0)
    return key


def main():
    parser = argparse.ArgumentParser(description="瓦片人工标注并移动到分类目录")
    parser.add_argument("--input_dir", type=str, default="./training_tiles/unknown",
                        help="未标注瓦片目录")
    parser.add_argument("--output_dir", type=str, default="./training_tiles",
                        help="分类输出目录（将创建子目录）")
    parser.add_argument("--classes", nargs="+", default=["zhedang", "zhengchang"],
                        help="类别名称列表，按键1对应第1类，2对应第2类")
    parser.add_argument("--no_gui", action="store_true", help="禁用GUI，在终端交互标注")
    args = parser.parse_args()

    input_dir = Path(args.input_dir)
    output_root = Path(args.output_dir)
    class_names = args.classes
    if len(class_names) < 2:
        print("至少需要2个类别名称，例如: zhedang zhengchang")
        return 1

    if not input_dir.exists():
        print(f"输入目录不存在: {input_dir}")
        return 1

    class_dirs = {c: (output_root / c) for c in class_names}
    for d in class_dirs.values():
        d.mkdir(parents=True, exist_ok=True)

    images = list_images(input_dir)
    if not images:
        print(f"未在 {input_dir} 找到待标注瓦片")
        return 0

    print(f"待标注瓦片数量: {len(images)}")

    log_path = output_root / "label_log.csv"
    undo_stack = []  # [(dst_path, original_input_dir)]

    for idx, img_path in enumerate(images, 1):
        title = (
            f"[{idx}/{len(images)}] {img_path.name} | 1:{class_names[0]}  2:{class_names[1]}  s:跳过  u:撤销  q:退出"
        )
        if args.no_gui:
            print(title)
            print("请输入类别编号(1/2)，或 s 跳过，u 撤销，q 退出:", end=" ")
            choice = input().strip().lower()
        else:
            key = show_image_with_text(img_path, title)
            if key == -1:
                print("窗口关闭，退出")
                break
            choice = chr(key & 0xFF) if 32 <= key <= 126 else ""

        if choice == "q":
            print("用户退出")
            break
        elif choice == "s":
            print(f"跳过 {img_path.name}")
            continue
        elif choice == "u":
            if undo_stack:
                last_dst, orig_dir = undo_stack.pop()
                if Path(last_dst).exists():
                    restored = orig_dir / Path(last_dst).name
                    shutil.move(str(last_dst), str(restored))
                    log_action(log_path, {
                        "timestamp": datetime.now().isoformat(),
                        "src": str(last_dst),
                        "dst": str(restored),
                        "class": "UNDO",
                        "action": "undo"
                    })
                    print(f"撤销成功: {Path(last_dst).name} -> {restored}")
                else:
                    print("无法撤销：目标文件不存在")
            else:
                print("没有可撤销的操作")
            continue
        elif choice in ("1", "2"):
            ci = int(choice) - 1
            cls = class_names[ci]
            dst_dir = class_dirs[cls]
            dst_path = safe_move(img_path, dst_dir)
            undo_stack.append((dst_path, input_dir))
            log_action(log_path, {
                "timestamp": datetime.now().isoformat(),
                "src": str(img_path),
                "dst": str(dst_path),
                "class": cls,
                "action": "move"
            })
            print(f"移动: {img_path.name} -> {cls}/{Path(dst_path).name}")
        else:
            print("无效输入，使用 s 跳过或 1/2 选择类别")
            continue

    if not args.no_gui:
        try:
            cv2.destroyAllWindows()
        except Exception:
            pass

    print("标注完成。日志记录在:", log_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())