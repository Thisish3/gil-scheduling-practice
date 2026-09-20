"""
LangGraph의 BackgroundExecutor가 실제로 ThreadPoolExecutor를 쓴다는 걸 소스에서 확인했다
(langgraph/pregel/_executor.py: "Uses a thread pool executor to delegate tasks to
separate threads."). 그렇다면 노드 함수가 CPU-bound일 때 "병렬 실행"이 진짜 멀티코어를
쓰는지, 아니면 GIL 때문에 동시성일 뿐인지 직접 측정한다.

비교 대상:
  1. 순차 실행 (baseline)
  2. ThreadPoolExecutor (LangGraph가 실제로 쓰는 것과 동일한 메커니즘)
  3. ProcessPoolExecutor (진짜 멀티코어 병렬)

워크로드: 순수 CPU-bound(요청 검증/스키마 체크 같은 걸 흉내낸 합성 연산) vs
I/O-bound(LLM API 호출을 흉내낸 time.sleep, GIL이 풀리는 경우)
"""

import time
import os
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor

N_TASKS = 8  # os.cpu_count()와 맞춤


def cpu_bound_task(n: int) -> int:
    """순수 CPU 연산 -- LangGraph 노드가 파이썬 로직만 돌리는 경우를 흉내냄."""
    total = 0
    for i in range(20_000_000):
        total += i * i % 7
    return total


def io_bound_task(n: int) -> float:
    """LLM API 호출처럼 네트워크 대기가 있는 경우를 흉내냄 (GIL 풀림)."""
    time.sleep(0.3)
    return n


def run_sequential(fn, n_tasks):
    t0 = time.perf_counter()
    for i in range(n_tasks):
        fn(i)
    return time.perf_counter() - t0


def run_threadpool(fn, n_tasks):
    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=n_tasks) as ex:
        list(ex.map(fn, range(n_tasks)))
    return time.perf_counter() - t0


def run_processpool(fn, n_tasks):
    t0 = time.perf_counter()
    with ProcessPoolExecutor(max_workers=n_tasks) as ex:
        list(ex.map(fn, range(n_tasks)))
    return time.perf_counter() - t0


if __name__ == "__main__":
    print(f"CPU 코어 수: {os.cpu_count()}, 태스크 수: {N_TASKS}\n")

    print("=== 1. CPU-bound 워크로드 (LangGraph 노드가 순수 파이썬 로직을 돌리는 경우) ===")
    t_seq = run_sequential(cpu_bound_task, N_TASKS)
    t_thread = run_threadpool(cpu_bound_task, N_TASKS)
    t_proc = run_processpool(cpu_bound_task, N_TASKS)
    print(f"순차 실행:            {t_seq:6.2f}s")
    print(f"ThreadPoolExecutor:   {t_thread:6.2f}s  (순차 대비 {t_seq/t_thread:.2f}x)  <- LangGraph가 쓰는 것과 동일한 메커니즘")
    print(f"ProcessPoolExecutor:  {t_proc:6.2f}s  (순차 대비 {t_seq/t_proc:.2f}x)  <- 진짜 멀티코어 병렬")

    print("\n=== 2. I/O-bound 워크로드 (LLM API 호출처럼 대기가 있는 경우) ===")
    t_seq2 = run_sequential(io_bound_task, N_TASKS)
    t_thread2 = run_threadpool(io_bound_task, N_TASKS)
    print(f"순차 실행:            {t_seq2:6.2f}s")
    print(f"ThreadPoolExecutor:   {t_thread2:6.2f}s  (순차 대비 {t_seq2/t_thread2:.2f}x)  <- 여기서는 스레드가 잘 먹힘(GIL이 sleep 동안 풀림)")
