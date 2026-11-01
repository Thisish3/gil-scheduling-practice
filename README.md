# GIL vs 진짜 병렬 — LangGraph의 ThreadPoolExecutor 실측

LangGraph의 실제 소스([`pregel/_executor.py`](https://github.com/langchain-ai/langgraph/blob/main/libs/langgraph/langgraph/pregel/_executor.py))를
직접 읽어보니 super-step의 "병렬 노드 실행"이 docstring에 명시된 대로
**"Uses a thread pool executor to delegate tasks to separate threads"** — 즉 Python
`ThreadPoolExecutor`로 구현돼 있다. CPython의 GIL(Global Interpreter Lock) 때문에
이게 CPU-bound 작업에서 진짜 멀티코어 병렬이 맞는지 직접 측정했다.

## 결과

### 재측정 (Apple M2 8코어 = 성능 4 + 효율 4, CPython 3.12.2, 3회)

| 워크로드 | 방식 | 1회 | 2회 | 3회 | 중앙값 |
|---|---|---|---|---|---|
| CPU-bound | 순차 | 13.87s | 14.12s | 14.09s | |
| CPU-bound | ThreadPoolExecutor | 1.05x | 1.10x | 1.09x | **1.09x** |
| CPU-bound | ProcessPoolExecutor | 2.79x | 4.74x | 3.68x | **3.68x** |
| I/O-bound | 순차 | 2.42s | 2.43s | 2.44s | |
| I/O-bound | ThreadPoolExecutor | 7.94x | 7.93x | 8.01x | **7.94x** |

### 첫 측정 (다른 8코어 머신, 1회)

```
=== 1. CPU-bound 워크로드 (노드가 순수 파이썬 로직만 도는 경우) ===
순차 실행:             32.49s
ThreadPoolExecutor:    23.96s  (순차 대비 1.36x)  <- LangGraph가 쓰는 것과 동일한 메커니즘
ProcessPoolExecutor:    7.01s  (순차 대비 4.63x)  <- 진짜 멀티코어 병렬

=== 2. I/O-bound 워크로드 (LLM API 호출처럼 대기가 있는 경우) ===
순차 실행:              2.43s
ThreadPoolExecutor:     0.31s  (순차 대비 7.89x)  <- 여기서는 스레드가 잘 먹힘
```

## 해석

- **CPU-bound**: 재측정에서 ThreadPoolExecutor는 1.05~1.10배로 순차와 거의 같았다.
  GIL이 파이썬 바이트코드 실행을 한 번에 한 스레드로 묶기 때문이다. 다만 실행 순서를
  바꿔 4번 더 재도(스레드 먼저 1.02·1.07배, 순차 먼저 1.09·1.04배) 스레드 쪽이 매번
  조금 빨라서, 순서 때문에 생긴 차이는 아니었다. 이 2~9% 차이의 원인은 확인하지 못했다.
  바이트코드가 병렬로 돈 것은 아니다(그랬다면 몇 배가 나왔어야 한다). 첫 측정의 1.36배는
  다른 머신에서 1회 잰 값이라 같은 조건으로 재현하지 못했다.
- ProcessPoolExecutor는 프로세스마다 인터프리터와 GIL이 따로 있어 실제로 병렬로 돈다.
  다만 8배에 못 미치고 회차마다 2.79~4.74배로 흔들렸다. 확인한 것:
  - 풀 생성 + 빈 작업 8개: 0.11~0.13초(전체 약 4초의 3%)라 생성 비용이 원인은 아니다.
  - worker 4개, 작업 8개: 2.63·2.88·2.86배(이상치 4배), worker 8개: 3.38·3.11·3.02배.
  - 정확한 원인은 확인하지 못했다.
- Colab(vCPU 2개 = 물리 코어 1개, 공유 VM)에서도 재 봤지만, 같은 순차 실행이 9.64초와 4.77초로
  흔들리고 worker 1개가 1.38배로 나오는 등 CPU 측정이 불안정해 결론에 쓰지 않았다.
- **I/O-bound**: `time.sleep`(네트워크 대기 흉내) 동안은 GIL이 풀리므로 스레드가
  거의 이상적으로(7.94배) 동작한다.

## 실전 의미

LangGraph 노드가 대부분 **"LLM API를 호출하고 기다리는" I/O-bound 작업**이라면
ThreadPoolExecutor로 충분하다 — 실제로 에이전트 노드 대부분이 이 패턴. 하지만 노드
안에서 무거운 순수 CPU 연산(스키마 검증, 대량 파싱, 로컬 후처리 등)을 돌린다면
"병렬 실행"이라는 이름과 달리 멀티코어 이득을 거의 못 본다 — 그런 경우엔 별도로
`ProcessPoolExecutor`나 외부 프로세스로 빼야 진짜 병렬화됨.

## 재현 방법
```bash
python3 gil_vs_multiprocess.py
```
