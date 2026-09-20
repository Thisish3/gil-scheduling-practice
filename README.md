# GIL vs 진짜 병렬 — LangGraph의 ThreadPoolExecutor 실측

LangGraph의 실제 소스([`pregel/_executor.py`](https://github.com/langchain-ai/langgraph/blob/main/libs/langgraph/langgraph/pregel/_executor.py))를
직접 읽어보니 super-step의 "병렬 노드 실행"이 docstring에 명시된 대로
**"Uses a thread pool executor to delegate tasks to separate threads"** — 즉 Python
`ThreadPoolExecutor`로 구현돼 있다. CPython의 GIL(Global Interpreter Lock) 때문에
이게 CPU-bound 작업에서 진짜 멀티코어 병렬이 맞는지 직접 측정했다.

## 결과 (실측, 8코어 머신)

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

- **CPU-bound**: 8코어인데 ThreadPoolExecutor는 겨우 1.36배 — GIL이 파이썬 바이트코드
  실행을 직렬화하기 때문에 스레드를 늘려도 진짜 병렬 계산이 안 됨. (완전히 1.0배가
  아닌 이유: CPython이 주기적으로 GIL을 다른 스레드에 양보하기 때문에 약간의 인터리빙
  이득은 있음.) ProcessPoolExecutor는 각 프로세스가 독립된 인터프리터+GIL을 가지므로
  4.63배까지 나옴(완전한 8배가 아닌 건 프로세스 생성/피클링 오버헤드).
- **I/O-bound**: `time.sleep`(네트워크 대기 흉내) 동안은 GIL이 풀리므로 스레드가
  거의 이상적으로(7.89x) 동작함.

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
