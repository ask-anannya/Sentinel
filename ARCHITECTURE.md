# Sentinel — Architecture Diagram

## High-Level System Architecture

```mermaid
graph TB
    subgraph User["👤 Compliance Engineer"]
        Browser["Web Browser"]
    end

    subgraph Frontend["Frontend — React + Vite + Tailwind v4"]
        direction TB
        App["App.jsx — Router + Sidebar"]
        Dashboard["Dashboard.jsx"]
        ViolationsPage["Violations.jsx"]
        AuditTrailPage["AuditTrail.jsx"]
        CompScore["ComplianceScore.jsx"]
        VCard["ViolationCard.jsx"]
        RModal["RemediationModal.jsx"]
        ScanStat["ScanStatus.jsx"]
    end

    subgraph Backend["Backend — FastAPI + Python"]
        direction TB
        API["main.py — FastAPI Routes"]
        Orch["orchestrator.py — Scan Orchestration"]
        AP["agent_pool.py — Nova Act Agent Pool"]
        VE["violation_engine.py — Violation Detection"]
        RE["remediation_engine.py — Remediation Execution"]
        NC["nova_client.py — Bedrock Wrapper"]
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
    end

    Browser -->|"REST API calls"| API
    App --> Dashboard & ViolationsPage & AuditTrailPage
    Dashboard --> CompScore & ScanStat
    ViolationsPage --> VCard & RModal

    API -->|"POST /api/scan/trigger"| Orch
    API -->|"POST /api/violations/:id/approve"| RE
    API -->|"GET /api/compliance-score"| VE
    API -->|"GET /api/reports/export"| NC
    API -->|"CRUD operations"| DB

    Sched -->|"Interval trigger (24h)"| Orch
    Orch -->|"1. scan_all_tools()"| AP
    Orch -->|"2. analyze_violations()"| VE

    AP -->|"NovaAct + Workflow context"| NovaAct
    NovaAct -->|"Playwright browser automation"| HR & IT & Proc

    VE -->|"detect_violations()"| NC
    VE -->|"Loads seed data"| SeedData
    VE -->|"insert_violations()"| DB

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
    participant DB as SQLite Database

    User->>FE: Click "Run Scan"
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
    
    FE->>API: GET /api/scan/{id}/status
    API-->>FE: {status: completed, violations_found: N}
    FE->>API: GET /api/violations
    API-->>FE: ViolationCard data
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
        sched["scheduler.py"]
    end

    subgraph Data Layer
        db["database.py"]
        csv["employees.csv"]
        json["role_policies.json"]
    end

    subgraph External
        nova["Nova Act SDK"]
        bedrock["AWS Bedrock"]
        sqlite["SQLite"]
    end

    main --> orch & ve & re & nc & db & sched
    sched --> orch
    orch --> ap & ve & db
    ap --> nova
    ve --> nc & db
    ve --> csv & json
    re --> nova & db & ap
    nc --> bedrock
    db --> sqlite
```

---

## API Endpoint Map

| Method | Endpoint | Handler | Description |
|--------|----------|---------|-------------|
| `POST` | `/api/scan/trigger` | [trigger_scan()](file:///d:/Amazon/sentinel/backend/main.py#112-140) | Starts background scan, returns `scan_id` |
| `GET` | `/api/scan/{scan_id}/status` | [get_scan_status()](file:///d:/Amazon/sentinel/backend/main.py#183-190) | Poll scan progress |
| `GET` | `/api/violations` | [list_violations()](file:///d:/Amazon/sentinel/backend/main.py#197-212) | Filter by severity/tool/status |
| `GET` | `/api/violations/{id}` | [get_violation()](file:///d:/Amazon/sentinel/backend/database.py#176-186) | Single violation detail |
| `POST` | `/api/violations/{id}/approve` | [approve_remediation()](file:///d:/Amazon/sentinel/backend/main.py#223-247) | Trigger Nova Act remediation |
| `POST` | `/api/violations/{id}/dismiss` | [dismiss_violation()](file:///d:/Amazon/sentinel/backend/main.py#273-311) | Dismiss with reason |
| `GET` | `/api/audit-trail` | [get_audit_trail()](file:///d:/Amazon/sentinel/backend/database.py#227-237) | Full event history |
| `GET` | `/api/compliance-score` | [get_compliance_score()](file:///d:/Amazon/sentinel/backend/main.py#329-333) | Score + severity breakdown |
| `GET` | `/api/reports/export` | [export_report()](file:///d:/Amazon/sentinel/backend/main.py#459-485) | PDF download via Nova 2 Lite |
| `GET` | `/health` | [health()](file:///d:/Amazon/sentinel/backend/main.py#492-495) | Health check |

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
        Bedrock["Bedrock"]
    end

    FE_Service -->|REST| BE_Service
    BE_Service -->|IAM Auth| NovaAct
    BE_Service -->|IAM Auth| Bedrock
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
