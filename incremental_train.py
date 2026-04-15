#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
增量训练脚本 - 基于现有best.pt权重进行训练
使用方法: python incremental_train.py --data your_dataset.yaml --epochs 50
"""

import argparse
import os
from pathlib import Path
from ultralytics import YOLO
from ultralytics.utils import yaml_load


def main():
    parser = argparse.ArgumentParser(description='基于现有best.pt进行增量训练')
    parser.add_argument('--model', type=str, default='./best.pt', 
                       help='预训练模型路径 (默认: ./best.pt)')
    parser.add_argument('--data', type=str, default='ultralytics/cfg/datasets/mqzx_zd.yaml',
                       help='数据集配置文件路径')
    parser.add_argument('--epochs', type=int, default=50,
                       help='训练轮数 (默认: 50)')
    parser.add_argument('--lr0', type=float, default=0.001,
                       help='初始学习率 (默认: 0.001)')
    parser.add_argument('--batch', type=int, default=16,
                       help='批次大小 (默认: 16)')
    parser.add_argument('--imgsz', type=int, default=224,
                       help='输入图像尺寸 (默认: 224)')
    parser.add_argument('--device', type=str, default='0',
                       help='训练设备 (默认: 0)')
    parser.add_argument('--workers', type=int, default=8,
                       help='数据加载线程数 (默认: 8)')
    parser.add_argument('--project', type=str, default='runs/classify',
                       help='项目目录 (默认: runs/classify)')
    parser.add_argument('--name', type=str, default='incremental_train',
                       help='实验名称 (默认: incremental_train)')
    parser.add_argument('--patience', type=int, default=30,
                       help='早停耐心值 (默认: 30)')
    
    args = parser.parse_args()
    
    if not os.path.exists(args.model):
        print(f"错误: 模型文件 '{args.model}' 不存在")
        print("请确保best.pt文件在当前目录下")
        return
    
    data_arg = args.data
    dataset_dir = None
    if data_arg.lower().endswith(('.yaml', '.yml')):
        if not os.path.isfile(data_arg):
            print(f"错误: 数据集配置文件 '{data_arg}' 不存在")
            return
        try:
            data_cfg = yaml_load(data_arg)
        except Exception as e:
            print(f"错误: 读取数据集YAML失败: {e}")
            return
        yaml_dir = Path(data_arg).parent
        path_field = data_cfg.get('path', '')
        if path_field:
            root = Path(path_field)
            if not root.is_absolute():
                root = (yaml_dir / root).resolve()
        else:
            root = yaml_dir
        dataset_dir = root
    else:
        dataset_dir = Path(data_arg).resolve()
    if not dataset_dir.is_dir():
        print(f"错误: 分类数据目录 '{dataset_dir}' 不存在或不是目录")
        return
    
    print("=" * 60)
    print("开始增量训练")
    print("=" * 60)
    print(f"预训练模型: {args.model}")
    print(f"数据集目录: {dataset_dir}")
    print(f"训练轮数: {args.epochs}")
    print(f"学习率: {args.lr0}")
    print(f"批次大小: {args.batch}")
    print(f"图像尺寸: {args.imgsz}")
    print(f"训练设备: {args.device}")
    print("=" * 60)
    
    try:
        model = YOLO(args.model)
        print(f"成功加载预训练模型: {args.model}")
        
        results = model.train(
            data=str(dataset_dir),
            epochs=args.epochs,
            imgsz=args.imgsz,
            batch=args.batch,
            lr0=args.lr0,
            device=args.device,
            workers=args.workers,
            project=args.project,
            name=args.name,
            save=True,
            save_period=10,
            val=True,
            plots=True,
            verbose=True,
            patience=args.patience,
            resume=False,
            pretrained=True,
            amp=True,
            cos_lr=True,
        )
        
        print("\n" + "=" * 60)
        print("训练完成!")
        print("=" * 60)
        print(f"最佳权重保存在: {results.save_dir}/weights/best.pt")
        print(f"最后权重保存在: {results.save_dir}/weights/last.pt")
        print(f"训练结果保存在: {results.save_dir}")
        
        if hasattr(results, 'results_dict'):
            print("\n训练结果摘要:")
            for key, value in results.results_dict.items():
                if isinstance(value, float):
                    print(f"  {key}: {value:.4f}")
                else:
                    print(f"  {key}: {value}")
        
    except Exception as e:
        print(f"训练过程中出现错误: {str(e)}")
        print("请检查:")
        print("1. 模型文件是否存在且格式正确")
        print("2. 数据集路径是否正确")
        print("3. GPU内存是否足够")
        print("4. 数据集格式是否符合要求")

if __name__ == "__main__":
    main()