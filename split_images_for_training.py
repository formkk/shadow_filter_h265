#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
图像分割脚本 - 将大图像分割为224x224的小块用于训练
参照predict.py中的分割方法实现
使用方法: python split_images_for_training.py --input_dir ./continuous_photos --output_dir ./training_tiles
"""

import argparse
import os
import cv2
import numpy as np
from pathlib import Path
import shutil

def split_image_to_tiles(image_path, output_dir, tile_size=224, class_name="unknown"):
    """
    将单张图像分割为指定大小的瓦片
    
    Args:
        image_path: 输入图像路径
        output_dir: 输出目录
        tile_size: 瓦片大小 (默认224x224)
        class_name: 类别名称，用于创建子目录
    
    Returns:
        分割后的瓦片数量
    """
    im = cv2.imread(str(image_path))
    if im is None:
        print(f"错误: 无法读取图像 {image_path}")
        return 0
    
    h, w, _ = im.shape
    print(f"原始图像尺寸: {w}x{h}")
    
    nh = int(np.ceil(h / tile_size) * tile_size)
    nw = int(np.ceil(w / tile_size) * tile_size)
    
    re_im = cv2.resize(im.copy(), (nw, nh))
    print(f"调整后尺寸: {nw}x{nh}")
    
    gh = nh // tile_size
    gw = nw // tile_size
    print(f"分割为 {gh}x{gw} = {gh*gw} 个瓦片")
    
    class_output_dir = Path(output_dir) / class_name
    class_output_dir.mkdir(parents=True, exist_ok=True)
    
    base_name = Path(image_path).stem
    
    tile_count = 0
    for i in range(gh):
        for j in range(gw):
            cim = re_im[i*tile_size:(i+1)*tile_size, j*tile_size:(j+1)*tile_size]
            
            tile_filename = f"{base_name}_tile_{i}_{j}.jpg"
            tile_path = class_output_dir / tile_filename
            
            cv2.imwrite(str(tile_path), cim)
            tile_count += 1
    
    print(f"成功生成 {tile_count} 个瓦片，保存在: {class_output_dir}")
    return tile_count

def process_directory(input_dir, output_dir, tile_size=224, class_mapping=None):
    """
    处理目录中的所有图像
    
    Args:
        input_dir: 输入目录
        output_dir: 输出目录
        tile_size: 瓦片大小
        class_mapping: 文件名到类别的映射字典
    """
    input_path = Path(input_dir)
    output_path = Path(output_dir)
    
    if not input_path.exists():
        print(f"错误: 输入目录 {input_dir} 不存在")
        return
    
    output_path.mkdir(parents=True, exist_ok=True)
    
    image_extensions = ['.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.tif']
    
    image_files = []
    for ext in image_extensions:
        image_files.extend(input_path.glob(f'*{ext}'))
        image_files.extend(input_path.glob(f'*{ext.upper()}'))
    
    if not image_files:
        print(f"在目录 {input_dir} 中未找到图像文件")
        return
    
    print(f"找到 {len(image_files)} 个图像文件")
    
    total_tiles = 0
    for image_file in image_files:
        print(f"\n处理图像: {image_file.name}")
        
        if class_mapping and image_file.name in class_mapping:
            class_name = class_mapping[image_file.name]
        else:
            class_name = "unknown"
        
        tile_count = split_image_to_tiles(
            image_file, 
            output_dir, 
            tile_size, 
            class_name
        )
        total_tiles += tile_count
    
    print(f"\n处理完成! 总共生成 {total_tiles} 个瓦片")
    print(f"输出目录: {output_path}")

def create_dataset_structure(output_dir, class_names):
    """创建训练数据集目录结构"""
    output_path = Path(output_dir)
    
    train_dir = output_path / 'train'
    val_dir = output_path / 'val'
    
    for class_name in class_names:
        (train_dir / class_name).mkdir(parents=True, exist_ok=True)
        (val_dir / class_name).mkdir(parents=True, exist_ok=True)
    
    print(f"数据集目录结构已创建:")
    print(f"  训练集: {train_dir}")
    print(f"  验证集: {val_dir}")
    
    return train_dir, val_dir

def main():
    parser = argparse.ArgumentParser(description='将图像分割为224x224瓦片用于训练')
    parser.add_argument('--input_dir', type=str, default='./continuous_photos',
                       help='输入图像目录 (默认: ./continuous_photos)')
    parser.add_argument('--output_dir', type=str, default='./training_tiles',
                       help='输出瓦片目录 (默认: ./training_tiles)')
    parser.add_argument('--tile_size', type=int, default=224,
                       help='瓦片大小 (默认: 224)')
    parser.add_argument('--class_name', type=str, default=None,
                       help='指定类别名称 (如果不指定，将提示用户选择)')
    parser.add_argument('--create_dataset', action='store_true',
                       help='创建完整的训练数据集结构 (train/val)')
    parser.add_argument('--split_ratio', type=float, default=0.8,
                       help='训练集比例 (默认: 0.8)')
    
    args = parser.parse_args()
    
    print("=" * 60)
    print("图像分割工具 - 生成训练瓦片")
    print("=" * 60)
    print(f"输入目录: {args.input_dir}")
    print(f"输出目录: {args.output_dir}")
    print(f"瓦片大小: {args.tile_size}x{args.tile_size}")
    
    if not os.path.exists(args.input_dir):
        print(f"错误: 输入目录 {args.input_dir} 不存在")
        return
    
    if args.class_name is None:
        print("\n请选择图像类别:")
        print("1. zhedang (遮挡)")
        print("2. zhengchang (正常)")
        print("3. 自定义类别名称")
        
        choice = input("请输入选择 (1/2/3): ").strip()
        
        if choice == '1':
            class_name = 'zhedang'
        elif choice == '2':
            class_name = 'zhengchang'
        elif choice == '3':
            class_name = input("请输入自定义类别名称: ").strip()
        else:
            print("无效选择，使用默认类别 'unknown'")
            class_name = 'unknown'
    else:
        class_name = args.class_name
    
    print(f"使用类别: {class_name}")
    print("=" * 60)
    
    try:
        if args.create_dataset:
            train_dir, val_dir = create_dataset_structure(args.output_dir, [class_name])
            
            temp_dir = Path(args.output_dir) / 'temp_tiles'
            temp_dir.mkdir(exist_ok=True)
            
            process_directory(args.input_dir, temp_dir, args.tile_size, {})
            
            temp_class_dir = temp_dir / class_name
            if temp_class_dir.exists():
                tiles = list(temp_class_dir.glob('*.jpg'))
                np.random.shuffle(tiles)
                
                split_idx = int(len(tiles) * args.split_ratio)
                train_tiles = tiles[:split_idx]
                val_tiles = tiles[split_idx:]
                
                for tile in train_tiles:
                    shutil.move(str(tile), train_dir / class_name / tile.name)
                
                for tile in val_tiles:
                    shutil.move(str(tile), val_dir / class_name / tile.name)
                
                print(f"数据集分割完成:")
                print(f"  训练集: {len(train_tiles)} 个瓦片")
                print(f"  验证集: {len(val_tiles)} 个瓦片")
            
            shutil.rmtree(temp_dir)
            
        else:
            class_mapping = {}
            
            process_directory(args.input_dir, args.output_dir, args.tile_size, class_mapping)
        
    except Exception as e:
        print(f"处理过程中出现错误: {str(e)}")

if __name__ == "__main__":
    main()