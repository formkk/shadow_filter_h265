#!/usr/bin/env python3
"""
系统级优化脚本 - 自动配置系统参数以获得最佳AI处理性能
"""

import os
import sys
import subprocess
import psutil
import torch
import platform
from pathlib import Path

class SystemOptimizer:
    """系统优化器"""
    
    def __init__(self):
        self.optimizations_applied = []
        self.warnings = []
        self.system_info = self._get_system_info()
    
    def _get_system_info(self):
        """获取系统信息"""
        info = {
            'platform': platform.system(),
            'cpu_count': psutil.cpu_count(),
            'memory_gb': psutil.virtual_memory().total / (1024**3),
            'cuda_available': torch.cuda.is_available(),
            'gpu_count': torch.cuda.device_count() if torch.cuda.is_available() else 0
        }
        
        if info['cuda_available']:
            info['gpu_names'] = [torch.cuda.get_device_name(i) for i in range(info['gpu_count'])]
            info['cuda_version'] = torch.version.cuda
        
        return info
    
    def print_system_info(self):
        """打印系统信息"""
        print("=== 系统信息 ===")
        print(f"操作系统: {self.system_info['platform']}")
        print(f"CPU核心数: {self.system_info['cpu_count']}")
        print(f"内存大小: {self.system_info['memory_gb']:.1f} GB")
        print(f"CUDA可用: {self.system_info['cuda_available']}")
        
        if self.system_info['cuda_available']:
            print(f"GPU数量: {self.system_info['gpu_count']}")
            print(f"CUDA版本: {self.system_info['cuda_version']}")
            for i, name in enumerate(self.system_info['gpu_names']):
                print(f"  GPU {i}: {name}")
        print()
    
    def optimize_opencv_settings(self):
        """优化OpenCV设置"""
        print("优化OpenCV设置...")
        
        import cv2
        
        optimal_threads = min(4, self.system_info['cpu_count'] // 2)
        cv2.setNumThreads(optimal_threads)
        self.optimizations_applied.append(f"OpenCV线程数设置为: {optimal_threads}")
        
        cv2.setUseOptimized(True)
        self.optimizations_applied.append("启用OpenCV优化")
        
        print(f"  ✓ OpenCV线程数: {optimal_threads}")
        print(f"  ✓ OpenCV优化: 已启用")
    
    def optimize_pytorch_settings(self):
        """优化PyTorch设置"""
        print("优化PyTorch设置...")
        
        if self.system_info['cuda_available']:
            torch.backends.cudnn.benchmark = True
            torch.backends.cudnn.deterministic = False
            self.optimizations_applied.append("启用cuDNN benchmark")
            print("  ✓ cuDNN benchmark: 已启用")
            
            try:
                for i in range(self.system_info['gpu_count']):
                    with torch.cuda.device(i):
                        dummy_tensor = torch.randn(1, 3, 224, 224).cuda()
                        del dummy_tensor
                        torch.cuda.empty_cache()
                self.optimizations_applied.append("GPU预热完成")
                print("  ✓ GPU预热: 完成")
            except Exception as e:
                self.warnings.append(f"GPU预热失败: {e}")
                print(f"  ⚠ GPU预热失败: {e}")
        
        optimal_threads = min(4, self.system_info['cpu_count'])
        torch.set_num_threads(optimal_threads)
        self.optimizations_applied.append(f"PyTorch线程数设置为: {optimal_threads}")
        print(f"  ✓ PyTorch线程数: {optimal_threads}")
    
    def optimize_process_priority(self):
        """优化进程优先级"""
        print("优化进程优先级...")
        
        try:
            if self.system_info['platform'] == 'Linux':
                current_nice = os.nice(0)
                try:
                    os.nice(-10)
                    new_nice = os.nice(0)
                    self.optimizations_applied.append(f"进程优先级提升: nice值从 {current_nice} 改为 {new_nice}")
                    print(f"  ✓ 进程优先级: nice值设置为 {new_nice}")
                except PermissionError:
                    self.warnings.append("无权限设置进程优先级，需要sudo权限")
                    print("  ⚠ 无权限设置进程优先级")
            
            elif self.system_info['platform'] == 'Windows':
                try:
                    import psutil
                    p = psutil.Process()
                    p.nice(psutil.HIGH_PRIORITY_CLASS)
                    self.optimizations_applied.append("Windows进程优先级设置为HIGH")
                    print("  ✓ Windows进程优先级: HIGH")
                except Exception as e:
                    self.warnings.append(f"Windows优先级设置失败: {e}")
                    print(f"  ⚠ Windows优先级设置失败: {e}")
        
        except Exception as e:
            self.warnings.append(f"进程优先级优化失败: {e}")
            print(f"  ⚠ 进程优先级优化失败: {e}")
    
    def optimize_memory_settings(self):
        """优化内存设置"""
        print("优化内存设置...")
        
        memory_optimizations = {
            'OMP_NUM_THREADS': str(min(4, self.system_info['cpu_count'])),
            'MKL_NUM_THREADS': str(min(4, self.system_info['cpu_count'])),
            'NUMEXPR_NUM_THREADS': str(min(4, self.system_info['cpu_count'])),
        }
        
        for key, value in memory_optimizations.items():
            os.environ[key] = value
            self.optimizations_applied.append(f"环境变量 {key} = {value}")
            print(f"  ✓ {key}: {value}")
        
        if self.system_info['cuda_available']:
            os.environ['CUDA_LAUNCH_BLOCKING'] = '0'
            self.optimizations_applied.append("CUDA异步执行: 已启用")
            print("  ✓ CUDA异步执行: 已启用")
    
    def check_dependencies(self):
        """检查依赖项"""
        print("检查依赖项...")
        
        required_packages = [
            'torch', 'torchvision', 'ultralytics', 'opencv-python',
            'numpy', 'psutil', 'GPUtil'
        ]
        
        missing_packages = []
        for package in required_packages:
            try:
                __import__(package.replace('-', '_'))
                print(f"  ✓ {package}: 已安装")
            except ImportError:
                missing_packages.append(package)
                print(f"  ✗ {package}: 未安装")
        
        if missing_packages:
            self.warnings.append(f"缺少依赖包: {', '.join(missing_packages)}")
            print(f"\n请安装缺少的包:")
            print(f"pip install {' '.join(missing_packages)}")
    
    def generate_optimization_script(self):
        """生成优化脚本"""
        script_content = '''#!/usr/bin/env python3
"""
自动生成的系统优化脚本
在运行AI处理程序前执行此脚本以获得最佳性能
"""

import os
import cv2
import torch

def apply_optimizations():
    """应用系统优化"""
    print("应用系统优化...")
    
    cv2.setNumThreads(4)
    cv2.setUseOptimized(True)
    
    if torch.cuda.is_available():
        torch.backends.cudnn.benchmark = True
        torch.backends.cudnn.deterministic = False
        
        for i in range(torch.cuda.device_count()):
            with torch.cuda.device(i):
                dummy = torch.randn(1, 3, 224, 224).cuda()
                del dummy
                torch.cuda.empty_cache()
    
    torch.set_num_threads(4)
    
    os.environ['OMP_NUM_THREADS'] = '4'
    os.environ['MKL_NUM_THREADS'] = '4'
    os.environ['NUMEXPR_NUM_THREADS'] = '4'
    os.environ['CUDA_LAUNCH_BLOCKING'] = '0'
    
    try:
        os.nice(-10)
    except PermissionError:
        pass
    
    print("系统优化完成!")

if __name__ == "__main__":
    apply_optimizations()
'''
        
        script_path = Path("apply_optimizations.py")
        with open(script_path, 'w', encoding='utf-8') as f:
            f.write(script_content)
        
        if self.system_info['platform'] != 'Windows':
            os.chmod(script_path, 0o755)
        
        self.optimizations_applied.append(f"生成优化脚本: {script_path}")
        print(f"  ✓ 优化脚本已生成: {script_path}")
    
    def run_system_benchmark(self):
        """运行系统基准测试"""
        print("运行系统基准测试...")
        
        import time
        start_time = time.time()
        
        result = sum(i * i for i in range(1000000))
        cpu_time = time.time() - start_time
        
        print(f"  CPU基准测试: {cpu_time:.3f}秒")
        
        if self.system_info['cuda_available']:
            start_time = time.time()
            
            with torch.cuda.device(0):
                a = torch.randn(1000, 1000).cuda()
                b = torch.randn(1000, 1000).cuda()
                c = torch.matmul(a, b)
                torch.cuda.synchronize()
            
            gpu_time = time.time() - start_time
            print(f"  GPU基准测试: {gpu_time:.3f}秒")
        
        import numpy as np
        start_time = time.time()
        
        arrays = [np.random.rand(1000, 1000) for _ in range(10)]
        result = np.sum(arrays, axis=0)
        
        memory_time = time.time() - start_time
        print(f"  内存基准测试: {memory_time:.3f}秒")
    
    def print_optimization_summary(self):
        """打印优化总结"""
        print("\n" + "="*60)
        print("系统优化总结")
        print("="*60)
        
        print(f"应用的优化 ({len(self.optimizations_applied)}):")
        for i, opt in enumerate(self.optimizations_applied, 1):
            print(f"  {i}. {opt}")
        
        if self.warnings:
            print(f"\n警告 ({len(self.warnings)}):")
            for i, warning in enumerate(self.warnings, 1):
                print(f"  {i}. {warning}")
        
        print(f"\n建议:")
        print("  1. 运行 'python apply_optimizations.py' 在每次启动AI程序前")
        print("  2. 监控GPU/CPU使用率，根据需要调整线程数")
        print("  3. 如果内存不足，减少批处理大小")
        print("  4. 定期清理GPU内存缓存")
        
        if self.system_info['platform'] == 'Linux':
            print("  5. 考虑使用 'sudo' 运行以获得更高权限")


def main():
    """主函数"""
    print("系统优化器 - 为AI处理优化系统配置")
    print("="*50)
    
    optimizer = SystemOptimizer()
    
    optimizer.print_system_info()
    
    optimizer.check_dependencies()
    print()
    
    optimizer.optimize_opencv_settings()
    print()
    
    optimizer.optimize_pytorch_settings()
    print()
    
    optimizer.optimize_process_priority()
    print()
    
    optimizer.optimize_memory_settings()
    print()
    
    optimizer.generate_optimization_script()
    print()
    
    optimizer.run_system_benchmark()
    
    optimizer.print_optimization_summary()


if __name__ == "__main__":
    main()