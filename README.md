# GPt-api-test
## 사용 프롬포트
AI agent 생성 promt
GOAL : 내가 Linear work flow를 수행할 수 있는 대시보드를 Steamlit으로 만들려고 해.
Boundary : 다음 조건을 만족 시켜줘
 ChatGPT api_key는 내가 웹페이지 내에서 직접 입력할 수 있게 해줘.
 웹페이지 내에서, 나는 LLM 에이전트를 만들 수 있고, 그 에이전트를 linear workflow로 편집 할 수 있어야 해.
LLM 에이전트는 기본적으로 system prompt까지 내가 지정해서 만들어 세팅하고, 이후 수행할 때는 linear workflow가 만들어진 후, 내가 user prompt를 넣는 방식이야.
Linear work flow는 앞선 에이전트의 Output을 뒤의 에이전트의 input으로 받되, 추가 프롬포트가 있으면, 뒤의 에이전트도 추가 프롬포트 편집이 가능해야 해.
각 에이전트에게는 선택적으로 RAG 기능이 있어야 하고, 참조할 파일은 내가 Drag and drop으로 추가할 수 있어야 해.
.py 파일과, requirement.txt 파일을 다운 받을 수 있게 해줘. 최종적으로는 streamlit community cloud를 통해 배포할 수 있도록.
