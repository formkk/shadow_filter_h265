#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
一键式流水线脚本：采集 -> 分割 -> （可选）人工标注 -> 数据集拆分 -> （可选）训练集平衡 -> 增量训练 -> 评估 -> 备份并替换视频应用权重

示例：
python pipeline_run.py \
  --camera_indices 0,1,2,3 --capture_output continuous_photos --duration 20 --interval 0.2 \
  --tile_output training_tiles --tile_size 224 \
  --do_label --label_gui \
  --dataset_output training_tiles_dataset --train_ratio 0.8 --seed 42 \
  --balance_train \
  --base_model runs/classify/incremental_train6/weights/best.pt \
  --data_yaml training_tiles_dataset.yaml --epochs 25 --lr0 0.001 --batch 16 --imgsz 224 --device 0 --project runs/classify --name incremental_train_auto \
  --eval_data_yaml training_tiles_dataset.yaml \
  --replace_target ./best.pt --backup_dir ./backups --replace_only_if_better

默认会执行全部步骤；可用开关控制跳过某些步骤。
"""

import argparse
import os
import sys
import shutil
from pathlib import Path
from datetime import datetime
import random
from ultralytics.utils import yaml_load

sys.path.append(str(Path(__file__).parent))

from ultralytics import YOLO

try:
    from continuous_camera_capture import ContinuousCameraCapture
except Exception:
    ContinuousCameraCapture = None

try:
    from split_images_for_training import process_directory as split_process_dir
except Exception:
    split_process_dir = None

try:
    from prepare_dataset_split import ensure_split_dirs, split_class
except Exception:
    ensure_split_dirs = None
    split_class = None

try:
    from balance_dataset import balance_dataset_oversample, balance_dataset_undersample, count_samples_per_class, augment_image
except Exception:
    balance_dataset_oversample = None
    balance_dataset_undersample = None
    count_samples_per_class = None
    augment_image = None

try:
    from evaluate_model import eval_model as eval_cls_model
except Exception:
    eval_cls_model = None


def parse_camera_indices(s: str):
    try:
        return [int(x.strip()) for x in s.split(',') if x.strip() != '']
    except Exception:
        return [0, 1, 2, 3]


def step_capture(args):
    if not ContinuousCameraCapture:
        print("[采集] 未找到 ContinuousCameraCapture，跳过采集")
        return args.capture_output
    camera_indices = parse_camera_indices(args.camera_indices)
    capturer = ContinuousCameraCapture(
        camera_indices=camera_indices,
        output_dir=args.capture_output,
        duration=args.duration,
        interval=args.interval,
    )
    if not capturer.initialize_cameras():
        raise RuntimeError("摄像头初始化失败")
    capturer.start_capture()
    capturer.cleanup()
    capturer.print_summary()
    return args.capture_output


def step_split(args, capture_out):
    if not split_process_dir:
        print("[分割] 未找到 split_images_for_training.process_directory，跳过分割")
        return args.tile_output
    Path(args.tile_output).mkdir(parents=True, exist_ok=True)
    print(f"[分割] 从 {capture_out} -> {args.tile_output}，瓦片 {args.tile_size}")
    split_process_dir(capture_out, args.tile_output, args.tile_size, class_mapping={})
    return args.tile_output


def step_label(args, tile_out):
    if not args.do_label:
        print("[标注] 未启用，跳过")
        return
    import subprocess
    cmd = [sys.executable, str(Path(__file__).parent / 'label_tiles_cli.py'),
           '--input_dir', str(Path(tile_out) / 'unknown'),
           '--output_dir', tile_out,
           '--classes', 'zhedang', 'zhengchang']
    if not args.label_gui:
        cmd.append('--no_gui')
    print("[标注] 启动交互式标注：" + ' '.join(cmd))
    subprocess.run(cmd, check=False)


def step_dataset_split(args, tile_out):
    if not ensure_split_dirs or not split_class:
        print("[拆分] 未找到 prepare_dataset_split，跳过")
        return args.dataset_output
    cls_root = Path(tile_out)
    classes = [p.name for p in cls_root.iterdir() if p.is_dir()]
    if not {'zhedang', 'zhengchang'}.issubset(set(classes)):
        print(f"[拆分] 目录 {tile_out} 不包含期望类别 zhedang/zhengchang，跳过拆分。请完成标注后重试。")
        return args.dataset_output

    output_root = Path(args.dataset_output)
    train_dir, val_dir = ensure_split_dirs(output_root, ['zhedang', 'zhengchang'])
    random.seed(args.seed)
    total_train = total_val = 0
    for cls in ['zhedang', 'zhengchang']:
        t, v = split_class(cls_root / cls, train_dir, val_dir, args.train_ratio, move=False)
        total_train += t
        total_val += v
    print(f"[拆分] 完成：train {total_train} / val {total_val} -> {output_root}")
    return args.dataset_output


def _inplace_oversample_train(train_dir: Path):
    """在训练集目录内进行就地过采样，仅生成增强样本，不复制原始图像。"""
    if not count_samples_per_class or not augment_image:
        print("[平衡] 缺少增强函数，跳过")
        return
    class_counts = count_samples_per_class(str(train_dir))
    if not class_counts:
        print("[平衡] 未找到训练集类别")
        return
    target = max(class_counts.values())
    print(f"[平衡] 目标样本数: {target}")
    for cls, cur in class_counts.items():
        cls_dir = train_dir / cls
        if cur >= target:
            print(f"  {cls}: 已满足 {cur}")
            continue
        needed = target - cur
        print(f"  {cls}: 需要增加 {needed}")
        images = [p for p in cls_dir.iterdir() if p.is_file() and p.suffix.lower() in ['.jpg', '.jpeg', '.png', '.bmp']]
        generated = 0
        while generated < needed and images:
            src = random.choice(images)
            remaining = needed - generated
            n_gen = min(3, remaining)
            aug_paths = augment_image(src, cls_dir, num_augmentations=n_gen)
            generated += len(aug_paths)
        print(f"  {cls}: 已生成增强 {generated}")


def step_balance(args, dataset_root):
    if not args.balance_train:
        print("[平衡] 未启用，跳过")
        return
    train_dir = Path(dataset_root) / 'train'
    print(f"[平衡] 训练集过采样: {train_dir}")
    try:
        if balance_dataset_oversample:
            balance_dataset_oversample(str(train_dir), str(train_dir))
        else:
            _inplace_oversample_train(train_dir)
    except Exception as e:
        print(f"[平衡] 直接拷贝增强失败，改用就地增强: {e}")
        _inplace_oversample_train(train_dir)


def select_base_model(args):
    candidates = [args.base_model, './best.pt', './best.pt.ori']
    for p in candidates:
        if p and os.path.exists(p):
            return p
    raise FileNotFoundError("未找到可用的基模型，请通过 --base_model 指定")


def resolve_dataset_dir(data_arg: str) -> Path:
    p = Path(data_arg)
    if p.suffix.lower() in {'.yaml', '.yml'}:
        if not p.is_file():
            raise FileNotFoundError(f"数据集配置不存在: {data_arg}")
        data_cfg = yaml_load(str(p))
        yaml_dir = p.parent
        path_field = data_cfg.get('path', '')
        root = Path(path_field) if path_field else yaml_dir
        if not root.is_absolute():
            root = (yaml_dir / root).resolve()
        return root
    else:
        if not p.exists():
            raise FileNotFoundError(f"数据集目录不存在: {data_arg}")
        return p.resolve()


def step_train(args):
    base_model = select_base_model(args)
    print(f"[训练] 载入基模型: {base_model}")
    dataset_dir = resolve_dataset_dir(args.data_yaml)
    print(f"[训练] 使用数据目录: {dataset_dir}")
    model = YOLO(base_model)
    results = model.train(
        data=str(dataset_dir),
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=args.batch,
        lr0=args.lr0,
        device=str(args.device),
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
    save_dir = getattr(results, 'save_dir', None)
    best_path = str(Path(save_dir) / 'weights' / 'best.pt') if save_dir else None
    print(f"[训练] 输出目录: {save_dir}")
    print(f"[训练] 最佳权重: {best_path}")
    return best_path, base_model


def step_eval(args, base_model, new_model):
    if not eval_cls_model:
        print("[评估] 未找到 evaluate_model，跳过")
        return None, None
    eval_dir = resolve_dataset_dir(args.eval_data_yaml)
    print(f"[评估] 使用数据目录: {eval_dir}")
    r_a = eval_cls_model(base_model, str(eval_dir), imgsz=args.imgsz)
    r_b = eval_cls_model(new_model, str(eval_dir), imgsz=args.imgsz)
    print("[评估] 基模型:")
    print(f"  Top-1: {r_a['top1']}")
    print(f"  Top-5: {r_a['top5']}")
    print("[评估] 新模型:")
    print(f"  Top-1: {r_b['top1']}")
    print(f"  Top-5: {r_b['top5']}")
    delta = None
    if r_a['top1'] is not None and r_b['top1'] is not None:
        delta = (r_b['top1'] - r_a['top1']) * 100
        print(f"[评估] Top-1 提升: {delta:+.2f} 百分点")
    return r_a, r_b


def backup_and_replace(args, new_best_path):
    target = Path(args.replace_target)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        Path(args.backup_dir).mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_path = Path(args.backup_dir) / f"best_{ts}.pt"
        shutil.copy2(str(target), str(backup_path))
        print(f"[替换] 已备份旧权重至: {backup_path}")
        ori = Path('best.pt.ori')
        if not ori.exists():
            shutil.copy2(str(target), str(ori))
            print(f"[替换] 另存原权重: {ori}")
    else:
        print("[替换] 目标文件不存在，直接写入新权重")
    shutil.copy2(str(new_best_path), str(target))
    print(f"[替换] 已更新视频应用权重: {target}")


def main():
    p = argparse.ArgumentParser(description="采集到评估的一键式流水线")
    p.add_argument('--camera_indices', type=str, default='0,1,2,3', help='摄像头索引，逗号分隔')
    p.add_argument('--capture_output', type=str, default='continuous_photos', help='采集输出目录')
    p.add_argument('--duration', type=float, default=20.0, help='采集持续时间(秒)')
    p.add_argument('--interval', type=float, default=0.2, help='采样间隔(秒)')
    p.add_argument('--skip_capture', action='store_true', help='跳过采集步骤')
    p.add_argument('--tile_output', type=str, default='training_tiles', help='分割瓦片输出目录')
    p.add_argument('--tile_size', type=int, default=224, help='瓦片大小')
    p.add_argument('--skip_split', action='store_true', help='跳过分割步骤')
    p.add_argument('--do_label', action='store_true', help='执行交互式标注并归类')
    p.add_argument('--label_gui', action='store_true', help='使用GUI标注(默认终端)')
    p.add_argument('--dataset_output', type=str, default='training_tiles_dataset', help='train/val 输出根目录')
    p.add_argument('--train_ratio', type=float, default=0.8, help='训练集比例')
    p.add_argument('--seed', type=int, default=42, help='随机种子')
    p.add_argument('--skip_split_dataset', action='store_true', help='跳过数据集拆分')
    p.add_argument('--balance_train', action='store_true', help='对训练集进行过采样平衡')
    p.add_argument('--base_model', type=str, default='', help='基模型(默认自动选择)')
    p.add_argument('--data_yaml', type=str, default='training_tiles_dataset.yaml', help='训练数据集配置')
    p.add_argument('--epochs', type=int, default=25, help='训练轮数')
    p.add_argument('--lr0', type=float, default=0.001, help='初始学习率')
    p.add_argument('--batch', type=int, default=16, help='批次大小')
    p.add_argument('--imgsz', type=int, default=224, help='输入尺寸')
    p.add_argument('--device', type=str, default='0', help='设备')
    p.add_argument('--workers', type=int, default=8, help='数据加载线程数')
    p.add_argument('--project', type=str, default='runs/classify', help='训练输出项目目录')
    p.add_argument('--name', type=str, default='incremental_train_auto', help='训练实验名称')
    p.add_argument('--patience', type=int, default=10, help='早停耐心')
    p.add_argument('--skip_train', action='store_true', help='跳过训练')
    p.add_argument('--eval_data_yaml', type=str, default='training_tiles_dataset.yaml', help='评估数据集配置(建议未平衡)')
    p.add_argument('--skip_eval', action='store_true', help='跳过评估')
    p.add_argument('--replace_target', type=str, default='./best.pt', help='视频应用使用的模型路径')
    p.add_argument('--backup_dir', type=str, default='./backups', help='备份目录')
    p.add_argument('--replace_only_if_better', action='store_true', help='仅在新模型更优时替换')
    p.add_argument('--no_replace', action='store_true', help='不进行权重替换，仅训练与可选评估')

    args = p.parse_args()

    capture_out = args.capture_output
    if not args.skip_capture:
        capture_out = step_capture(args)
    else:
        print("[采集] 跳过，使用已存在目录: ", capture_out)

    tile_out = args.tile_output
    if not args.skip_split:
        tile_out = step_split(args, capture_out)
    else:
        print("[分割] 跳过，使用目录: ", tile_out)

    step_label(args, tile_out)

    dataset_root = args.dataset_output
    if not args.skip_split_dataset:
        dataset_root = step_dataset_split(args, tile_out)
    else:
        print("[拆分] 跳过，使用目录: ", dataset_root)

    step_balance(args, dataset_root)

    new_best = None
    base_model = None
    if not args.skip_train:
        new_best, base_model = step_train(args)
    else:
        print("[训练] 跳过，需手动指定新权重文件")
        new_best = input("请输入新权重路径(best.pt): ").strip()
        base_model = select_base_model(args)

    if not args.skip_eval and new_best and os.path.exists(new_best):
        r_a, r_b = step_eval(args, base_model, new_best)
        should_replace = not args.no_replace
        if args.no_replace:
            print('[替换] 已启用 --no_replace，不进行权重替换')
        elif args.replace_only_if_better and r_a and r_b and r_a.get('top1') is not None and r_b.get('top1') is not None:
            should_replace = r_b['top1'] >= r_a['top1']
            print(f"[替换] 条件替换(--replace_only_if_better): {'满足' if should_replace else '不满足'} (base={r_a['top1']:.3f}, new={r_b['top1']:.3f})")
        else:
            print('[替换] 未启用 --replace_only_if_better，评估后将直接替换')
        if should_replace:
            backup_and_replace(args, new_best)
        else:
            print('[替换] 未进行替换')
    else:
        reason = []
        if args.skip_eval:
            reason.append('--skip_eval')
        if not new_best:
            reason.append('新权重路径为空')
        elif not os.path.exists(new_best):
            reason.append('新权重文件不存在')
        msg = '、'.join(reason) if reason else '未知原因'
        print(f"[评估] 跳过评估({msg})")
        if args.no_replace:
            print('[替换] 已启用 --no_replace，不进行权重替换')
        elif new_best and os.path.exists(new_best):
            print('[替换] 评估被跳过，但检测到新权重，直接替换')
            backup_and_replace(args, new_best)
        else:
            print('[替换] 未进行替换（无新权重）')

    print("\n流水线完成。")


if __name__ == '__main__':
    raise SystemExit(main())