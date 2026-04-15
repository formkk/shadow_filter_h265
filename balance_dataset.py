#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据平衡处理脚本 - 处理类别不平衡问题
使用方法: python balance_dataset.py --input_dir ./unbalanced_dataset --output_dir ./balanced_dataset
"""

import argparse
import os
import shutil
import random
from pathlib import Path
from collections import Counter
import cv2
import numpy as np


def count_samples_per_class(data_dir):
    """统计每个类别的样本数量"""
    class_counts = {}
    data_path = Path(data_dir)

    for class_dir in data_path.iterdir():
        if class_dir.is_dir():
            class_name = class_dir.name
            image_files = [f for f in class_dir.iterdir()
                           if f.suffix.lower() in ['.jpg', '.jpeg', '.png', '.bmp']]
            class_counts[class_name] = len(image_files)

    return class_counts


def augment_image(image_path, output_dir, num_augmentations=3):
    """对图像进行数据增强"""
    image = cv2.imread(str(image_path))
    if image is None:
        return []

    augmented_paths = []
    base_name = image_path.stem

    for i in range(num_augmentations):
        augmentation_type = random.choice(['flip', 'rotate', 'brightness', 'noise'])

        if augmentation_type == 'flip':
            augmented = cv2.flip(image, 1)
        elif augmentation_type == 'rotate':
            angle = random.uniform(-15, 15)
            center = (image.shape[1]//2, image.shape[0]//2)
            matrix = cv2.getRotationMatrix2D(center, angle, 1.0)
            augmented = cv2.warpAffine(image, matrix, (image.shape[1], image.shape[0]))
        elif augmentation_type == 'brightness':
            factor = random.uniform(0.7, 1.3)
            augmented = cv2.convertScaleAbs(image, alpha=factor, beta=0)
        else:  # noise
            noise = np.random.normal(0, 25, image.shape).astype(np.uint8)
            augmented = cv2.add(image, noise)

        output_path = output_dir / f"{base_name}_aug_{i+1}.jpg"
        cv2.imwrite(str(output_path), augmented)
        augmented_paths.append(output_path)

    return augmented_paths


def balance_dataset_oversample(input_dir, output_dir, target_samples=None):
    """通过过采样平衡数据集"""
    input_path = Path(input_dir)
    output_path = Path(output_dir)

    output_path.mkdir(parents=True, exist_ok=True)

    inplace = input_path.resolve() == output_path.resolve()
    if inplace:
        print("提示: 输入与输出目录相同，将进行就地过采样（不拷贝原始文件）。")

    class_counts = count_samples_per_class(input_dir)
    print("原始数据分布:")
    for class_name, count in class_counts.items():
        print(f"  {class_name}: {count} 张")

    if target_samples is None:
        target_samples = max(class_counts.values())

    print(f"\n目标样本数: {target_samples}")

    for class_name, current_count in class_counts.items():
        class_input_dir = input_path / class_name
        class_output_dir = output_path / class_name
        class_output_dir.mkdir(exist_ok=True)

        image_files = [f for f in class_input_dir.iterdir()
                       if f.suffix.lower() in ['.jpg', '.jpeg', '.png', '.bmp']]

        if not inplace:
            for img_file in image_files:
                shutil.copy2(img_file, class_output_dir / img_file.name)

        if current_count < target_samples:
            needed_samples = target_samples - current_count
            print(f"  {class_name}: 需要增加 {needed_samples} 张")

            generated = 0
            while generated < needed_samples:
                source_img = random.choice(image_files)

                remaining = needed_samples - generated
                num_aug = min(3, remaining)

                aug_paths = augment_image(source_img, class_output_dir, num_aug)
                generated += len(aug_paths)

        final_images = [f for f in class_output_dir.iterdir()
                        if f.suffix.lower() in ['.jpg', '.jpeg', '.png', '.bmp']]
        print(f"  {class_name}: 完成，共 {len(final_images)} 张")


def balance_dataset_undersample(input_dir, output_dir, target_samples=None):
    """通过欠采样平衡数据集"""
    input_path = Path(input_dir)
    output_path = Path(output_dir)

    output_path.mkdir(parents=True, exist_ok=True)

    class_counts = count_samples_per_class(input_dir)
    print("原始数据分布:")
    for class_name, count in class_counts.items():
        print(f"  {class_name}: {count} 张")

    if target_samples is None:
        target_samples = min(class_counts.values())

    print(f"\n目标样本数: {target_samples}")

    for class_name, current_count in class_counts.items():
        class_input_dir = input_path / class_name
        class_output_dir = output_path / class_name
        class_output_dir.mkdir(exist_ok=True)

        image_files = [f for f in class_input_dir.iterdir()
                       if f.suffix.lower() in ['.jpg', '.jpeg', '.png', '.bmp']]

        if current_count > target_samples:
            selected_files = random.sample(image_files, target_samples)
            print(f"  {class_name}: 从 {current_count} 张中选择 {target_samples} 张")
        else:
            selected_files = image_files
            print(f"  {class_name}: 保留全部 {current_count} 张")

        for img_file in selected_files:
            shutil.copy2(img_file, class_output_dir / img_file.name)


def main():
    parser = argparse.ArgumentParser(description='数据平衡处理')
    parser.add_argument('--input_dir', type=str, required=True,
                        help='输入数据集目录')
    parser.add_argument('--output_dir', type=str, required=True,
                        help='输出平衡数据集目录')
    parser.add_argument('--method', type=str, choices=['oversample', 'undersample'],
                        default='oversample',
                        help='平衡方法: oversample(过采样) 或 undersample(欠采样)')
    parser.add_argument('--target_samples', type=int, default=None,
                        help='目标样本数量 (默认: 过采样使用最大值，欠采样使用最小值)')
    parser.add_argument('--split', type=str, choices=['train', 'val'], default='train',
                        help='处理训练集还是验证集')

    args = parser.parse_args()

    input_split_dir = Path(args.input_dir) / args.split
    output_split_dir = Path(args.output_dir) / args.split

    if not input_split_dir.exists():
        print(f"错误: 输入目录 {input_split_dir} 不存在")
        return

    print("=" * 60)
    print(f"数据平衡处理 - {args.method}")
    print("=" * 60)
    print(f"输入目录: {input_split_dir}")
    print(f"输出目录: {output_split_dir}")
    print(f"处理集合: {args.split}")

    try:
        if args.method == 'oversample':
            balance_dataset_oversample(input_split_dir, output_split_dir, args.target_samples)
        else:
            balance_dataset_undersample(input_split_dir, output_split_dir, args.target_samples)

        print("\n处理后数据分布:")
        final_counts = count_samples_per_class(output_split_dir)
        for class_name, count in final_counts.items():
            print(f"  {class_name}: {count} 张")

        print(f"\n数据平衡处理完成! 结果保存在: {output_split_dir}")

    except Exception as e:
        print(f"处理过程中出现错误: {str(e)}")


if __name__ == "__main__":
    main()