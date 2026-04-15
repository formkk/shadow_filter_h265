#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
分类模型评估脚本
- 评估给定模型在指定数据集 val 集上的 Top-1 / Top-5 准确率
- 可同时对比两个模型（例如原模型与新模型）

用法示例：
python evaluate_model.py --data training_tiles_dataset.yaml \
  --model_a runs/classify/incremental_train6/weights/best.pt \
  --model_b runs/classify/incremental_train9/weights/best.pt
"""

import argparse
import os
from ultralytics import YOLO


def eval_model(model_path: str, data_yaml: str, imgsz: int = 224):
    if not os.path.exists(model_path):
        print(f"模型不存在: {model_path}")
        return None
    model = YOLO(model_path)
    metrics = model.val(data=data_yaml, imgsz=imgsz, split="val")
    rd = getattr(metrics, "results_dict", {})
    top1 = rd.get("top1_acc") or rd.get("metrics/accuracy_top1")
    top5 = rd.get("top5_acc") or rd.get("metrics/accuracy_top5")
    return {
        "top1": float(top1) if top1 is not None else None,
        "top5": float(top5) if top5 is not None else None,
        "save_dir": getattr(metrics, "save_dir", None),
    }


def main():
    parser = argparse.ArgumentParser(description="评估分类模型 Top-1 / Top-5")
    parser.add_argument("--data", type=str, default="training_tiles_dataset.yaml", help="数据集 YAML")
    parser.add_argument("--imgsz", type=int, default=224, help="评估图像尺寸")
    parser.add_argument("--model_a", type=str, required=True, help="模型A路径")
    parser.add_argument("--model_b", type=str, default=None, help="模型B路径(可选)")
    args = parser.parse_args()

    r_a = eval_model(args.model_a, args.data, args.imgsz)
    if r_a is None:
        return 1

    print("模型A评估结果:")
    print(f"  Top-1: {r_a['top1']:.4f}" if r_a['top1'] is not None else "  Top-1: N/A")
    print(f"  Top-5: {r_a['top5']:.4f}" if r_a['top5'] is not None else "  Top-5: N/A")

    if args.model_b:
        r_b = eval_model(args.model_b, args.data, args.imgsz)
        if r_b:
            print("\n模型B评估结果:")
            print(f"  Top-1: {r_b['top1']:.4f}" if r_b['top1'] is not None else "  Top-1: N/A")
            print(f"  Top-5: {r_b['top5']:.4f}" if r_b['top5'] is not None else "  Top-5: N/A")

            if r_a['top1'] is not None and r_b['top1'] is not None:
                delta = (r_b['top1'] - r_a['top1']) * 100
                print(f"\nTop-1 提升: {delta:+.2f} 百分点")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())