# Sentinel — Architecture Diagram

## High-Level System Architecture

```mermaid
graph TB
    subgraph User["👤 Compliance Engineer"]
        Browser["Web Browser + Microphone"]
    end

    subgraph Frontend["Frontend — React + Vite + Tailwind v4"]
        direction TB
        App["App.jsx — Router + Sidebar + VoiceAssistantProvider"]
        Dashboard["Dashboard.jsx"]
        ViolationsPage["Violations.jsx"]
        AuditTrailPage["AuditTrail.jsx"]
        CompScore["ComplianceScore.jsx"]
        VCard["ViolationCard.jsx"]
        RModal["RemediationModal.jsx"]
        ScanStat["ScanStatus.jsx"]
        VA["VoiceAssistant.jsx"]
        AB["AudioBriefing.jsx"]
        Splash["SentinelSplash.jsx"]
        AAF["AgentActivityFeed.jsx"]
    end

    subgraph Backend["Backend — FastAPI + Python"]
        direction TB
        API["main.py — FastAPI Routes + WebSocket"]
        Orch["orchestrator.py — Scan Orchestration"]
        AP["agent_pool.py — Nova Act Agent Pool"]
        VE["violation_engine.py — Violation Detection"]
        RE["remediation_engine.py — Remediation Execution"]
        NC["nova_client.py — Bedrock Wrapper (Nova 2 Lite)"]
        NST["nova_sonic_tts.py — Sonic TTS (Audio Briefings)"]
        VAS["voice_assistant.py — Sonic Voice Session"]
        BG["briefing_generator.py — Post-scan Briefing"]
        EB["event_bus.py — In-process Pub/Sub"]
        Sched["scheduler.py — APScheduler"]
        DB["database.py — SQLite Layer"]
        SQLite[("sentinel.db")]
        SeedData["data/ — employees.csv + role_policies.json"]
    end

    subgraph LegacyTools["Legacy Tool Simulators — Flask"]
        HR["HRMS v3.1 — PeopleSoft Style<br/>:5001"]
        IT["IT Admin Console v2.4 — ServiceNow Style<br/>:5002"]
        Proc["Procurement Portal v1.8 — SAP Style<br/>:5003"]
    end

    subgraph AWS["AWS Cloud Services"]
        NovaAct["Amazon Nova Act<br/>Browser Automation SDK"]
        Bedrock["AWS Bedrock<br/>Nova 2 Lite (amazon.nova-lite-v1:0)"]
        NovaSonic["AWS Bedrock<br/>Nova 2 Sonic (amazon.nova-2-sonic-v1:0)"]
    end

    Browser -->|"REST API calls"| API
    Browser -->|"WebSocket (PCM audio)"| API
    App --> Dashboard & ViolationsPage & AuditTrailPage
    App -->|"persists across navigation"| VA
    Dashboard --> CompScore & ScanStat & AB & Splash & AAF
    ViolationsPage --> VCard & RModal

    API -->|"POST /api/scan/trigger"| Orch
    API -->|"POST /api/violations/:id/approve"| RE
    API -->|"GET /api/compliance-score"| VE
    API -->|"GET /api/reports/export"| NC
    API -->|"WS /api/voice-session"| VAS
    API -->|"CRUD operations"| DB
    API -->|"publishes scan events"| EB

    Sched -->|"Interval trigger (24h)"| Orch
    Orch -->|"1. scan_all_tools()"| AP
    Orch -->|"2. analyze_violations()"| VE
    Orch -->|"3. generate_briefing()"| BG

    AP -->|"NovaAct + Workflow context"| NovaAct
    NovaAct -->|"Playwright browser automation"| HR & IT & Proc

    VE -->|"detect_violations()"| NC
    VE -->|"Loads seed data"| SeedData
    VE -->|"insert_violations()"| DB

    BG -->|"synthesise speech"| NST
    NST -->|"HTTP/2 bidirectional stream"| NovaSonic

    VAS -->|"HTTP/2 bidirectional stream<br/>(aws-sdk-bedrock-runtime Smithy SDK)"| NovaSonic
    VAS -->|"tool calls → DB queries"| DB

    RE -->|"NovaAct login + remediate"| NovaAct
    RE -->|"Audit trail + status update"| DB

    NC -->|"boto3 invoke_model()"| Bedrock
    DB -->|"sqlite3"| SQLite

    Orch -->|"create/update scan records"| DB
```

---

## Data Flow: Compliance Scan Lifecycle

```mermaid
sequenceDiagram
    actor User as Compliance Engineer
    participant FE as React Frontend
    participant API as FastAPI (main.py)
    participant Orch as Orchestrator
    participant AP as Agent Pool
    participant NA as Nova Act SDK
    participant LT as Legacy Tools (Flask)
    participant VE as Violation Engine
    participant NC as Nova Client
    participant BR as AWS Bedrock (Nova 2 Lite)
    participant BG as Briefing Generator
    participant NST as Nova Sonic TTS
    participant DB as SQLite Database

    User->>FE: Click "Run Scan" (or voice command)
    FE->>API: POST /api/scan/trigger
    API->>DB: create_scan(status: running)
    API-->>FE: {scan_id} (immediate)

    Note over FE: Polls GET /api/scan/{id}/status every 3s

    API->>Orch: BackgroundTask: run_scan()
    Orch->>AP: scan_all_tools()

    par Parallel browser sessions (ThreadPoolExecutor)
        AP->>NA: NovaAct(hr-portal/login, headless=True)
        NA->>LT: Login + navigate + extract users
        LT-->>NA: HTML tables
        NA-->>AP: ExtractedUser[] + screenshot
    and
        AP->>NA: NovaAct(it-admin/login)
        NA->>LT: Login + navigate + extract users
        LT-->>NA: HTML tables
        NA-->>AP: ExtractedUser[] + screenshot
    and
        AP->>NA: NovaAct(procurement/login)
        NA->>LT: Login + navigate + extract users
        LT-->>NA: HTML tables
        NA-->>AP: ExtractedUser[] + screenshot
    end

    AP-->>Orch: Combined scan_results[]
    Orch->>VE: analyze_violations(scan_results)
    VE->>VE: Load employees.csv + role_policies.json

    loop For each tool's users
        VE->>NC: detect_violations(users, hr_data, policies)
        NC->>BR: invoke_model(violation detection prompt)
        BR-->>NC: JSON violations[]
        NC-->>VE: parsed violations
    end

    VE->>DB: insert_violations(all_violations)
    VE-->>Orch: violations[]
    Orch->>DB: update_scan(status: completed)
    Orch->>BG: generate_briefing(scan_results)
    BG->>NST: synthesise_speech(summary_text)
    NST-->>FE: WAV audio → AudioBriefing plays in-browser

    FE->>API: GET /api/scan/{id}/status
    API-->>FE: {status: completed, violations_found: N}
    FE->>API: GET /api/violations
    API-->>FE: ViolationCard data
```

---

## Data Flow: Voice Assistant Session

```mermaid
sequenceDiagram
    actor User as Compliance Engineer
    participant FE as React Frontend (VoiceAssistant.jsx)
    participant WS as WebSocket (/api/voice-session)
    participant VA as voice_assistant.py
    participant NS as AWS Bedrock (Nova 2 Sonic)
    participant DB as SQLite / violation_engine

    User->>FE: Grants microphone (SentinelSplash)
    FE->>WS: Connect WebSocket
    WS->>VA: VoiceSession.run(websocket)
    VA->>NS: sessionStart + promptStart + system prompt + tools
    NS-->>VA: Greeting audio chunks
    VA-->>FE: PCM binary frames → AudioContext plays

    loop Continuous conversation
        User->>FE: Speaks (PCM from ScriptProcessor)
        FE->>WS: Binary PCM frames
        WS->>VA: audioInput events → Nova Sonic
        NS-->>VA: textOutput (transcript, debug only)
        NS-->>VA: audioOutput (speech chunks)
        VA-->>FE: PCM binary → queued playback

        opt Tool call requested
            NS-->>VA: toolUse event + contentEnd(TOOL)
            VA->>VA: _execute_tool(name, id, content)
            alt runComplianceScan
                VA->>WS: on_action("scan_started", {scan_id})
                WS-->>FE: {type: "action", action: "scan_started"}
            else getComplianceScore
                VA->>DB: violation_engine.calculate_compliance_score()
            else getViolations
                VA->>DB: database.get_violations()
            else generateReport
                VA->>WS: on_action("generate_report", {})
                WS-->>FE: {type: "action", action: "generate_report", url: "/api/reports/export"}
            end
            VA->>NS: contentStart(TOOL) + toolResult + contentEnd
            NS-->>VA: Spoken summary of tool result
        end
    end

    User->>FE: Closes voice assistant
    FE->>WS: disconnect
    VA->>NS: contentEnd + promptEnd + sessionEnd
```

---

## Data Flow: Remediation Execution

```mermaid
sequenceDiagram
    actor User as Compliance Engineer
    participant FE as React Frontend
    participant API as FastAPI
    participant RE as Remediation Engine
    participant NA as Nova Act SDK
    participant LT as Legacy Tool
    participant DB as SQLite Database

    User->>FE: Click "Remediate" on violation
    FE->>FE: Show RemediationModal with steps preview
    User->>FE: Click "Confirm & Execute"
    FE->>API: POST /api/violations/{id}/approve {approved_by}
    API->>DB: update_violation_status(remediating)
    API-->>FE: {message: "Remediation started"}

    API->>RE: BackgroundTask: execute_remediation()
    RE->>NA: NovaAct(tool_url/login, headless=True)
    NA->>LT: Login with admin credentials
    RE->>NA: act(REMEDIATION_INSTRUCTIONS for violation_type)
    NA->>LT: Navigate → Find user → Disable/Downgrade
    NA->>NA: page.screenshot() → confirmation evidence
    NA-->>RE: Success + screenshot_path

    RE->>DB: update_violation_status(resolved)
    RE->>DB: insert_audit_entry(action, screenshot, approver)

    FE->>API: GET /api/violations/{id}
    API-->>FE: {status: resolved, screenshot_path}
```

---

## Module Dependency Graph

```mermaid
graph LR
    subgraph API Layer
        main["main.py"]
    end

    subgraph Core Logic
        orch["orchestrator.py"]
        ap["agent_pool.py"]
        ve["violation_engine.py"]
        re["remediation_engine.py"]
        nc["nova_client.py"]
        nst["nova_sonic_tts.py"]
        vas["voice_assistant.py"]
        bg["briefing_generator.py"]
        eb["event_bus.py"]
        sched["scheduler.py"]
    end

    subgraph Data Layer
        db["database.py"]
        csv["employees.csv"]
        json["role_policies.json"]
    end

    subgraph External
        nova["Nova Act SDK"]
        bedrock["AWS Bedrock (Nova 2 Lite)"]
        sonic["AWS Bedrock (Nova 2 Sonic)"]
        sqlite["SQLite"]
    end

    main --> orch & ve & re & nc & db & sched & vas & eb
    sched --> orch
    orch --> ap & ve & db & bg
    ap --> nova
    ve --> nc & db
    ve --> csv & json
    re --> nova & db
    nc --> bedrock
    bg --> nst
    nst --> sonic
    vas --> sonic
    vas --> db & ve
    db --> sqlite
```

---

## API Endpoint Map

| Method | Endpoint | Handler | Description |
|--------|----------|---------|-------------|
| `POST` | `/api/scan/trigger` | `trigger_scan()` | Starts background scan, returns `scan_id` |
| `GET` | `/api/scan/{scan_id}/status` | `get_scan_status()` | Poll scan progress |
| `GET` | `/api/violations` | `list_violations()` | Filter by severity/tool/status |
| `GET` | `/api/violations/{id}` | `get_violation()` | Single violation detail |
| `POST` | `/api/violations/{id}/approve` | `approve_remediation()` | Trigger Nova Act remediation |
| `POST` | `/api/violations/{id}/dismiss` | `dismiss_violation()` | Dismiss with reason |
| `GET` | `/api/audit-trail` | `get_audit_trail()` | Full event history |
| `GET` | `/api/compliance-score` | `get_compliance_score()` | Score + severity breakdown |
| `GET` | `/api/reports/export` | `export_report()` | PDF download via Nova 2 Lite |
| `WS` | `/api/voice-session` | `voice_session()` | Nova 2 Sonic bidirectional voice stream |
| `GET` | `/health` | `health()` | Health check |

---

## Database Schema

```mermaid
erDiagram
    SCANS {
        text scan_id PK
        text status
        text message
        int violations_found
        text started_at
        text completed_at
    }

    VIOLATIONS {
        text violation_id PK
        text scan_id FK
        text tool_name
        text username
        text full_name
        text department
        text role
        text violation_type
        text severity
        int severity_score
        text evidence
        text soc2_control
        text screenshot_path
        text status
        text detected_at
        text resolved_by
        text resolved_at
        text dismiss_reason
    }

    AUDIT_TRAIL {
        text entry_id PK
        text event_type
        text violation_id FK
        text scan_id FK
        text actor
        text action
        text result
        text screenshot_path
        text timestamp
        text details
    }

    SCANS ||--o{ VIOLATIONS : "produces"
    SCANS ||--o{ AUDIT_TRAIL : "logs"
    VIOLATIONS ||--o{ AUDIT_TRAIL : "tracks"
```

---

## Deployment Topology (Railway)

```mermaid
graph TB
    subgraph Railway["Railway Platform"]
        direction TB
        FE_Service["Frontend Service<br/>npm run preview :5173"]
        BE_Service["Backend Service<br/>uvicorn main:app :$PORT"]
        HR_Service["HR Portal Service<br/>Flask :5001"]
        IT_Service["IT Admin Service<br/>Flask :5002"]
        Proc_Service["Procurement Service<br/>Flask :5003"]
    end

    subgraph AWS["AWS"]
        IAM["IAM Credentials<br/>(env vars)"]
        NovaAct["Nova Act"]
        Bedrock["Bedrock (Nova 2 Lite)"]
        NovaSonic["Bedrock (Nova 2 Sonic)"]
    end

    FE_Service -->|REST + WebSocket| BE_Service
    BE_Service -->|IAM Auth| NovaAct
    BE_Service -->|IAM Auth| Bedrock
    BE_Service -->|IAM Auth| NovaSonic
    NovaAct -->|Headless Playwright| HR_Service & IT_Service & Proc_Service
    IAM -.->|AWS_ACCESS_KEY_ID<br/>AWS_SECRET_ACCESS_KEY| BE_Service
```

---

## Violation Types & Severity

| Type | Severity | Score | SOC2 Control | Detection Logic |
|------|----------|-------|--------------|-----------------|
| `ACCESS_VIOLATION` | CRITICAL | 95 | CC6.2 | TERMINATED in HR but active in tool |
| `INACTIVE_ADMIN` | HIGH | 75 | CC6.1 | Admin, last login >90 days ago |
| `SHARED_ACCOUNT` | HIGH | 70 | CC6.3 | Username matches shared patterns + has admin |
| `PERMISSION_CREEP` | MEDIUM | 50 | CC6.3 | Never-admin role but has admin access |
