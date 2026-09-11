# STEP 7 — Discord Integration Run Guide

Discord는 Agent Workflow Studio의 원격 interaction adapter입니다. Agent/Workflow 설정은 Local UI에서 유지하고, Discord에서는 Session/Run 실행과 상태/HITL/Follow-up만 수행합니다.

## 1. Prerequisites

FastAPI backend와 Discord bot process는 같은 로컬 데이터 디렉터리(`AWS2_DATA_DIR`)를 사용해야 합니다. Discord Channel/Thread ↔ WorkflowSession mapping은 같은 `domain.sqlite`의 `external_thread_links`에 저장됩니다.

Discord Developer Portal에서 Bot을 생성하고 서버에 초대합니다. Slash command 사용을 위해 bot/application command 권한을 포함해 초대하고, 이 구현은 message-content privileged intent를 요구하지 않습니다.

## 2. Environment

```bash
export OPENAI_API_KEY="..."
export DISCORD_BOT_TOKEN="..."
export AWS2_DATA_DIR="data"
export AWS2_API_BASE_URL="http://127.0.0.1:8000"

# 필요 범위만 허용. 쉼표로 여러 ID 지정 가능.
export DISCORD_ALLOWED_GUILD_IDS="123456789"
export DISCORD_ALLOWED_USER_IDS="123456789"
export DISCORD_ALLOWED_CHANNEL_IDS="123456789"
```

`DISCORD_BOT_TOKEN`과 `OPENAI_API_KEY`는 환경변수로만 전달하며 DB/Git에 저장하지 않습니다.

보안을 위해 기본값은 **allowlist 필수**입니다. `DISCORD_ALLOWED_GUILD_IDS`, `DISCORD_ALLOWED_USER_IDS`, `DISCORD_ALLOWED_CHANNEL_IDS` 중 하나 이상을 설정해야 Bot이 시작됩니다. 개발용으로만 제한 없이 실행하려면 의도를 명시적으로 드러내기 위해 `DISCORD_ALLOW_UNLISTED=true`를 별도로 설정해야 합니다.

## 3. Start services

Terminal 1:

```bash
uvicorn agent_workflow_studio.api.app:app --app-dir src --host 127.0.0.1 --port 8000
```

Terminal 2:

```bash
python scripts/run_discord_bot.py
```

## 4. Commands

```text
/aws_start workflow_id:<id> prompt:<request> [title:<title>]
/aws_status
/aws_reply answer:<answer>
/aws_resume
/aws_followup message:<request> [attachment1] [attachment2] [attachment3]
```

- `/aws_start`: 새 WorkflowSession과 Initial Run을 생성하고 현재 Discord Channel/Thread에 연결합니다.
- `/aws_status`: 연결된 Session의 최신 Run 상태를 조회합니다.
- `/aws_reply`: 최신 Run이 `WAITING_FOR_USER`일 때 답변하고 같은 Run/thread를 Resume합니다.
- `/aws_resume`: 최신 Run이 `PAUSED`일 때 오류 checkpoint에서 수동 Resume합니다.
- `/aws_followup`: 최신 Run이 `COMPLETED`일 때 새 Continuation Run을 만듭니다. Discord attachment는 FastAPI multipart attachment로 전달되며 permanent Agent RAG로 자동 승격되지 않습니다.

완료 결과가 Discord 메시지 길이에 비해 길면 앞부분 preview와 전체 Markdown 파일을 함께 보냅니다.

## 5. Local smoke test without Discord credentials

```bash
python scripts/manual_discord_smoke_test.py
```

이 smoke test는 Discord Gateway에 접속하지 않고 다음 adapter semantics를 검증합니다.

```text
Channel mapping → Initial Run → WAITING_FOR_USER
→ same Run reply/resume
→ COMPLETED
→ Follow-up + attachment
→ new Continuation Run
→ SQLite reopen 후 Channel ↔ Session mapping 복구
```

실제 서버에서의 최종 manual validation은 사용자의 Discord Bot Token 및 서버/채널 ID가 준비된 뒤 수행합니다.
