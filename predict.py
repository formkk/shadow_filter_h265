import shutil
import numpy as np
import os
import cv2
import subprocess
from ultralytics import YOLO

import argparse
import tempfile
import time

parser = argparse.ArgumentParser(description='处理视频文件并进行预测')
parser.add_argument('--video_path', type=str, help='视频文件路径')
parser.add_argument('--output_path', type=str, default='output_video.mp4', help='输出视频路径')
args = parser.parse_args()

model_path = './best.pt'
if os.path.exists(model_path):
    model = YOLO(model_path)
else:
    print(f"警告: 模型文件 '{model_path}' 不存在")
    model = None

mode = 'inference/exp'
imgsz=224

temp_frame_dir = tempfile.mkdtemp()

def extract_frames_from_video(video_path, output_dir):
    """从视频中提取帧并保存到指定目录"""
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"无法打开视频文件: {video_path}")
        return False
    
    fps = cap.get(cv2.CAP_PROP_FPS)
    frame_count = 0
    
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        
        frame_name = f"frame_{frame_count:06d}.png"
        frame_path = os.path.join(output_dir, frame_name)
        cv2.imwrite(frame_path, frame)
        frame_count += 1
        
        if frame_count % 100 == 0:
            print(f"已提取 {frame_count} 帧")
    
    cap.release()
    print(f"视频帧提取完成，共提取 {frame_count} 帧")
    return fps

if model is not None:
    if args.video_path:
        if not os.path.exists(args.video_path):
            print(f"错误: 视频文件 '{args.video_path}' 不存在")
        else:
            fps = extract_frames_from_video(args.video_path, temp_frame_dir)
            if fps:
                root = temp_frame_dir
                
                if os.path.exists(root):
                    names = os.listdir(root)
                    names.sort()
                    
                    processed_frames = []
                    
                    for name in names:
                        
                        sd = './split_im/'
                        if os.path.exists(sd):
                            shutil.rmtree(sd)
                        os.makedirs(sd, exist_ok=True)

                        idn,format_ = os.path.splitext(name)
                        source = os.path.join(root, name)

                        if format_.lower() in ['.jpg', '.jpeg', '.png', '.bmp']:
                            im = cv2.imread(source)
                            if im is not None:
                                h,w,_ = im.shape
                                nh = int(np.ceil(h/imgsz)*imgsz)
                                nw = int(np.ceil(w/imgsz)*imgsz)
                                re_im = cv2.resize(im.copy(), (nw, nh))
                                print(f"处理图像: {name}, 调整后大小: {re_im.shape}")

                                gh = nh//imgsz
                                gw = nw//imgsz
                                print(f"分割为 {gh}x{gw} 块")
                                
                                for i in range(gh):
                                    for j in range(gw):
                                        cim = re_im[i*imgsz:(i+1)*imgsz, j*imgsz:(j+1)*imgsz]
                                        cv2.imwrite(f"{sd}/{idn}_{i}_{j}{format_}", cim)

                                split_files = os.listdir(sd)
                                
                                results = model.predict(
                                    source=sd,
                                    imgsz=imgsz,
                                )

                                pred_labels = []
                                if results is not None:
                                    for result in results:
                                        if hasattr(result, 'probs') and result.probs is not None:
                                            pred_labels.append(result.probs.top1)

                                flag = False if 0 in pred_labels else True
                                print(f"图像 {name} 预测结果: {'通过' if flag else '检测到目标'}")
                                
                                try:
                                    save_dir = model.predictor.save_dir/'select_im'
                                    if flag:
                                        os.makedirs(save_dir, exist_ok=True)
                                        cv2.imwrite(f'{save_dir}/{name}', im)

                                    for i in os.listdir(sd):
                                        os.remove(os.path.join(sd, i))
                                except Exception as e:
                                    print(f"保存结果时出错: {str(e)}")
                                
                                if flag:
                                    processed_frames.append(os.path.join(model.predictor.save_dir/'select_im', name))
                else:
                    print(f"无法读取图像: {source}")
            else:
                print(f"跳过非图像文件: {name}")
            
            if processed_frames:
                print(f"开始合成视频，共 {len(processed_frames)} 帧")
                
                first_frame = cv2.imread(processed_frames[0])
                height, width, _ = first_frame.shape
                
                fourcc = cv2.VideoWriter_fourcc(*'mp4v')
                out = cv2.VideoWriter(args.output_path, fourcc, fps, (width, height))
                if not out.isOpened():
                    raise RuntimeError("无法创建视频写入器")
                print("使用OpenCV创建MPEG-4格式视频")
                
                for frame_path in processed_frames:
                    frame = cv2.imread(frame_path)
                    out.write(frame)
                
                out.release()
                print(f"视频合成完成，已保存至 {args.output_path}")
                
                try:
                    print("使用系统ffmpeg转换为H.264格式...")
                    temp_output = args.output_path + '.h264.mp4'
                    
                    cmd = [
                        '/usr/bin/ffmpeg', '-y', '-i', args.output_path,
                        '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
                        '-profile:v', 'baseline', '-level', '3.0',
                        '-an', temp_output
                    ]
                    
                    result = subprocess.run(cmd, capture_output=True, text=True)
                    if result.returncode == 0:
                        os.replace(temp_output, args.output_path)
                        print("使用系统ffmpeg转换为H.264格式")
                    else:
                        print(f"ffmpeg转换失败: {result.stderr}")
                        if os.path.exists(temp_output):
                            os.remove(temp_output)
                        print("继续使用MPEG-4格式")
                except Exception as e:
                    print(f"ffmpeg转换失败，保留MPEG-4格式: {str(e)}")
                    if os.path.exists(temp_output):
                        os.remove(temp_output)
            else:
                print("没有通过预测的帧可供合成视频")
            
            shutil.rmtree(temp_frame_dir)
    else:
        root = "captured_images"
        if os.path.exists(root):
            names = os.listdir(root)
            for name in names:
                
                sd = './split_im/'
                if os.path.exists(sd):
                    shutil.rmtree(sd)
                os.makedirs(sd, exist_ok=True)

                idn,format_ = os.path.splitext(name)
                source = os.path.join(root, name)

                if format_.lower() in ['.jpg', '.jpeg', '.png', '.bmp']:
                    im = cv2.imread(source)
                    if im is not None:
                        h,w,_ = im.shape
                        nh = int(np.ceil(h/imgsz)*imgsz)
                        nw = int(np.ceil(w/imgsz)*imgsz)
                        re_im = cv2.resize(im.copy(), (nw, nh))
                        print(f"处理图像: {name}, 调整后大小: {re_im.shape}")

                        gh = nh//imgsz
                        gw = nw//imgsz
                        print(f"分割为 {gh}x{gw} 块")
                        
                        for i in range(gh):
                            for j in range(gw):
                                cim = re_im[i*imgsz:(i+1)*imgsz, j*imgsz:(j+1)*imgsz]
                                cv2.imwrite(f"{sd}/{idn}_{i}_{j}{format_}", cim)

                        split_files = os.listdir(sd)
                        
                        results = model.predict(
                            source=sd,
                            imgsz=imgsz,
                        )

                        pred_labels = []
                        if results is not None:
                            for result in results:
                                if hasattr(result, 'probs') and result.probs is not None:
                                    pred_labels.append(result.probs.top1)

                        flag = False if 0 in pred_labels else True
                        print(f"图像 {name} 预测结果: {'通过' if flag else '检测到目标'}")
                        
                        try:
                            save_dir = model.predictor.save_dir/'select_im'
                            if flag:
                                os.makedirs(save_dir, exist_ok=True)
                                cv2.imwrite(f'{save_dir}/{name}', im)

                            for i in os.listdir(sd):
                                os.remove(os.path.join(sd, i))
                        except Exception as e:
                            print(f"保存结果时出错: {str(e)}")
                    else:
                        print(f"无法读取图像: {source}")
                else:
                    print(f"跳过非图像文件: {name}")
        else:
            print(f"错误: 目录 '{root}' 不存在")
else:
    print("无法继续处理，模型未加载")
