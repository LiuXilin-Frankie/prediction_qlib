import numpy as np
import torch
import time

def benchmark_triu_indices(sizes=[100, 1000, 5000, 10000, 20000, 30000, 50000, 70000]):
    results = []
    
    # 检查GPU是否可用
    device_cpu = torch.device('cpu')
    device_gpu = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    has_gpu = torch.cuda.is_available()
    
    for n in sizes:
        # NumPy 测试
        start = time.time()
        indices_np = np.triu_indices(n, k=1)
        np_time = time.time() - start
        
        # PyTorch CPU 测试
        start = time.time()
        indices_torch_cpu = torch.triu_indices(n, n, offset=1, device=device_cpu)
        torch_cpu_time = time.time() - start
        
        # PyTorch GPU 测试 (如果可用)
        torch_gpu_time = None

        results.append({
            'size': n,
            'numpy_time': np_time,
            'torch_cpu_time': torch_cpu_time,
            'torch_gpu_time': torch_gpu_time,
            'cpu_speedup': np_time / torch_cpu_time,
            'gpu_speedup': np_time / torch_gpu_time if torch_gpu_time else None
        })
        
        # 打印当前结果
        print(f"Size: {n}")
        print(f"  NumPy time: {np_time:.6f}s")
        print(f"  PyTorch CPU time: {torch_cpu_time:.6f}s (Speedup: {np_time/torch_cpu_time:.2f}x)")
        if torch_gpu_time:
            print(f"  PyTorch GPU time: {torch_gpu_time:.6f}s (Speedup: {np_time/torch_gpu_time:.2f}x)")
        print()
        
    return results

# 运行测试
results = benchmark_triu_indices()