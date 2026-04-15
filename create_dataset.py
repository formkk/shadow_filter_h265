#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据集准备脚本 - 为增量训练准备数据集
使用方法: python create_dataset.py --source_dir /path/to/new/images --output_dir ./new_dataset
"""

import argparse
import os
import shutil
from pathlib import Path
import yaml

def create_dataset_structure(output_dir, classes):
    """创建数据集目录结构"""
    output_path = Path(output_dir)
    
    output_path.mkdir(parents=True, exist_ok=True)
    
    train_dir = output_path / 'train'
    val_dir = output_path / 'val'
    
    train_dir.mkdir(exist_ok=True)
    val_dir.mkdir(exist_ok=True)
    
    for class_name in classes:
        (train_dir / class_name).mkdir(exist_ok=True)
        (val_dir / class_name).mkdir(exist_ok=True)
    
    print(f"数据集目录结构已创建: {output_path}")
    return output_path, train_dir, val_dir

def create_dataset_yaml(output_dir, classes, dataset_name="new_dataset"):
    """创建数据集配置文件"""
    output_path = Path(output_dir)
    
    names_dict = {i: class_name for i, class_name in enumerate(classes)}
    
    config = {
        'path': str(output_path.absolute()),
        'train': 'train',
        'val': 'val',
        'names': names_dict
    }
    
    yaml_path = output_path / f'{dataset_name}.yaml'
    with open(yaml_path, 'w', encoding='utf-8') as f:
        yaml.dump(config, f, default_flow_style=False, allow_unicode=True)
    
    print(f"数据集配置文件已创建: {yaml_path}")
    return yaml_path

def main():
    parser = argparse.ArgumentParser(description='创建增量训练数据集')
    parser.add_argument('--output_dir', type=str, default='./new_dataset',
                       help='输出数据集目录 (默认: ./new_dataset)')
    parser.add_argument('--classes', type=str, nargs='+', 
                       default=['zhedang', 'zhengchang'],
                       help='类别名称列表 (默认: zhedang zhengchang)')
    parser.add_argument('--dataset_name', type=str, default='new_dataset',
                       help='数据集名称 (默认: new_dataset)')
    parser.add_argument('--val_split', type=float, default=0.2,
                       help='验证集比例 (默认: 0.2)')
    
    args = parser.parse_args()
    
    print("=" * 60)
    print("创建增量训练数据集")
    print("=" * 60)
    print(f"输出目录: {args.output_dir}")
    print(f"类别: {args.classes}")
    print(f"验证集比例: {args.val_split}")
    print("=" * 60)
    
    try:
        output_path, train_dir, val_dir = create_dataset_structure(args.output_dir, args.classes)
        
        yaml_path = create_dataset_yaml(args.output_dir, args.classes, args.dataset_name)
        
        print("\n数据集结构创建完成!")
        print("\n请按以下步骤准备数据:")
        print("1. 将新的训练图片放入对应的类别目录:")
        for class_name in args.classes:
            print(f"   - {class_name} 类别图片 -> {train_dir / class_name}")
        
        print("\n2. 将验证图片放入对应的类别目录:")
        for class_name in args.classes:
            print(f"   - {class_name} 类别图片 -> {val_dir / class_name}")
        
        print(f"\n3. 使用配置文件进行训练:")
        print(f"   python incremental_train.py --data {yaml_path}")
        
        print("\n注意事项:")
        print("- 确保图片格式为 .jpg, .jpeg, .png, .bmp")
        print("- 建议每个类别至少有50张训练图片")
        print("- 验证集用于监控训练效果，防止过拟合")
        
    except Exception as e:
        print(f"创建数据集时出现错误: {str(e)}")

if __name__ == "__main__":
    main()