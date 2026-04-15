#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
将分类目录拆分为 Ultralytics 分类训练所需的 train/val 结构。

输入：一个根目录，包含按类别分好的子目录，例如：
  dataset_root/
    zhedang/
    zhengchang/

输出：在指定 output_root 下生成：
  output_root/
    train/
      zhedang/
      zhengchang/
    val/
      zhedang/
      zhengchang/

默认按 8:2 比例划分，可指定随机种子确保可复现；支持复制或移动（默认复制）。

用法：
python prepare_dataset_split.py --input_root ./training_tiles \
  --output_root ./training_tiles_dataset \
  --train_ratio 0.8 --seed 42 --move
"""

import argparse
import os
import random
import shutil
from pathlib import Path
from collections import defaultdict

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff"}


def list_images_in_dir(dir_path: Path):
    return [p for p in sorted(dir_path.iterdir()) if p.is_file() and p.suffix.lower() in IMAGE_EXTS]


def ensure_split_dirs(output_root: Path, class_names):
    train_dir = output_root / "train"
    val_dir = output_root / "val"
    for cls in class_names:
        (train_dir / cls).mkdir(parents=True, exist_ok=True)
        (val_dir / cls).mkdir(parents=True, exist_ok=True)
    return train_dir, val_dir


def split_class(class_dir: Path, train_dir: Path, val_dir: Path, train_ratio: float, move: bool):
    images = list_images_in_dir(class_dir)
    n = len(images)
    if n == 0:
        return 0, 0
    k = int(n * train_ratio)
    random.shuffle(images)
    train_imgs = images[:k]
    val_imgs = images[k:]

    def transfer(src: Path, dst_dir: Path):
        dst_dir.mkdir(parents=True, exist_ok=True)
        dst = dst_dir / src.name
        if move:
            shutil.move(str(src), str(dst))
        else:
            shutil.copy2(str(src), str(dst))

    cls_name = class_dir.name
    for p in train_imgs:
        transfer(p, train_dir / cls_name)
    for p in val_imgs:
        transfer(p, val_dir / cls_name)
    return len(train_imgs), len(val_imgs)


def main():
    parser = argparse.ArgumentParser(description="将分类目录拆分为train/val结构")
    parser.add_argument("--input_root", type=str, default="./training_tiles", help="按类别分好的根目录")
    parser.add_argument("--output_root", type=str, default="./training_tiles_dataset", help="输出数据集根目录")
    parser.add_argument("--train_ratio", type=float, default=0.8, help="训练集比例")
    parser.add_argument("--seed", type=int, default=42, help="随机种子")
    parser.add_argument("--move", action="store_true", help="移动文件而非复制")
    args = parser.parse_args()

    input_root = Path(args.input_root)
    output_root = Path(args.output_root)
    train_ratio = args.train_ratio

    if not input_root.exists():
        print(f"输入根目录不存在: {input_root}")
        return 1

    class_names = [p.name for p in input_root.iterdir() if p.is_dir()]
    if not class_names:
        print(f"在 {input_root} 未发现类别子目录")
        return 1

    random.seed(args.seed)
    train_dir, val_dir = ensure_split_dirs(output_root, class_names)

    stats = defaultdict(lambda: {"train": 0, "val": 0})
    total_train = total_val = 0
    for cls in class_names:
        t, v = split_class(input_root / cls, train_dir, val_dir, train_ratio, args.move)
        stats[cls]["train"] += t
        stats[cls]["val"] += v
        total_train += t
        total_val += v

    print("拆分完成。统计：")
    for cls in class_names:
        print(f"  {cls}: train {stats[cls]['train']} | val {stats[cls]['val']}")
    print(f"总计: train {total_train} | val {total_val}")
    print(f"输出位置: {output_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())