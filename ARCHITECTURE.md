# Urban Sentinel — Multi-Agent System Architecture

Diagrams for the LangGraph-based intelligence layer in `urban_sentinel/`.

## 1. Layered component view

```mermaid
flowchart TB
    subgraph IFACE["Interface layer — urban_sentinel/api"]
        MAIN["main.py<br/>create_app / run"]
        R_INT["intelligence.py<br/>POST /analyze/{id}<br/>GET /workflows/{id}"]
        R_INC["incidents.py<br/>/hypotheses /cascade<br/>/recommendations /review"]
        DEPS["deps.py<br/>get_service<br/>require_reviewer"]
    end

    subgraph ORCH["Orchestration layer — urban_sentinel/intelligence"]
        SVC["IntelligenceService<br/>service.py<br/>enqueue / run / record_review"]
        TRIG["triggers.py<br/>should_run_intelligence<br/>needs_signal_agent<br/>association_is_ambiguous"]
        WF["IntelligenceWorkflow<br/>workflow.py<br/>StateGraph + MemorySaver"]
        RT["IntelligenceRuntime<br/>runtime.py<br/>DI container"]
        STATE["IntelligenceState<br/>state.py<br/>TypedDict shared state"]
    end

    subgraph AGENTS["Agent layer — intelligence/agents"]
        A1["signal_intelligence<br/>signal.py"]
        A2["incident_fusion<br/>fusion.py"]
        A3["causal_cascade<br/>causal.py"]
        A4["impact_response<br/>impact.py"]
    end

    subgraph CROSS["Cross-cutting"]
        VAL["validation.py<br/>validate_signal / fusion<br/>hypothesis / scenario / recommendation"]
        CACHE["cache.py<br/>AnalysisCache (TTL)"]
        LLMP["llm.py<br/>LLMClient Protocol"]
        EXC["exceptions.py<br/>InvalidAgentOutput<br/>LlmTimeoutError<br/>ConcurrentUpdateError<br/>GraphUnavailableError"]
        LOG["core/logging.py<br/>log_event"]
    end

    subgraph DATA["Persistence layer — repositories/"]
        OPS["OperationalRepository<br/>authoritative store"]
        GRAPH_P["GraphRepository<br/>Protocol"]
        NEO["Neo4jGraphRepository"]
        IMEM["InMemoryGraphRepository"]
    end

    subgraph EXTERNAL["External / optional"]
        OPENAI["OpenAI API"]
        ANTH["Anthropic API"]
        NULLM["NullLLM<br/>deterministic-v1"]
        DB[("Neo4j<br/>infrastructure graph")]
    end

    MAIN --> R_INT
    MAIN --> R_INC
    R_INT --> DEPS
    R_INC --> DEPS
    DEPS --> SVC

    SVC --> TRIG
    SVC --> WF
    SVC -.builds.-> RT
    WF --> RT
    WF <--> STATE

    WF --> A1
    WF --> A2
    WF --> A3
    WF --> A4

    WF --> VAL
    WF --> CACHE
    WF --> EXC
    WF -.log_event.-> LOG

    RT --> OPS
    RT --> GRAPH_P
    GRAPH_P -.implemented by.-> NEO
    GRAPH_P -.implemented by.-> IMEM

    LLMP -.NullLLM.-> NULLM
    LLMP -.OpenAILLM.-> OPENAI
    LLMP -.AnthropicLLM.-> ANTH
    RT --> LLMP
    RT -.-> OPS
    RT -.-> GRAPH_P
    RT -.-> LLMP
    RT -.-> CACHE

    NEO --> DB
```

## 2. Workflow state machine

Conditional routing implemented in `_after_retrieve`, `_after_signal`, `_after_persist_assoc`
(`workflow.py:151-168`).

```mermaid
flowchart TB
    START((START)) --> V["validate_input"]
    V --> R["retrieve_context"]
    R -->|"cache_hit"| PR["persist_results"]
    R -->|"skip_signal + skip_fusion"| PA["persist_association"]
    R -->|"skip_signal only"| IF["incident_fusion"]
    R -->|"run signal"| SI["signal_intelligence"]
    SI -->|"skip_fusion"| PA
    SI --> IF
    IF --> PA
    PA -->|"scope includes CAUSAL"| CC["causal_cascade"]
    PA -->|"scope excludes CAUSAL"| IR["impact_response"]
    CC --> IR
    IR --> VO["validate_outputs"]
    VO --> PR
    PR --> CO["consolidate"]
    CO --> ENDV((END))

    classDef gate fill:#fff3cd,stroke:#b8860b,color:#222
    class R,SI,PA gate
```

Routing rules:

| From | Condition | To |
| --- | --- | --- |
| `retrieve_context` | `cache_hit` | `persist_results` |
| `retrieve_context` | `skip_signal and skip_fusion` | `persist_association` |
| `retrieve_context` | `skip_signal` | `incident_fusion` |
| `retrieve_context` | default | `signal_intelligence` |
| `signal_intelligence` | `skip_fusion` | `persist_association` |
| `persist_association` | `reanalysis_scope` contains `CAUSAL` | `causal_cascade` |
| `persist_association` | otherwise | `impact_response` |

## 3. Agent call envelope

Every LLM-backed agent shares the same guarded envelope implemented by
`IntelligenceWorkflow._with_retries` (`workflow.py:223-252`). Deterministic
fallbacks make the system run fully offline.

```mermaid
flowchart LR
    N["Agent node"] --> AV{"llm.available?"}
    AV -->|false| FB["deterministic_* fallback"]
    AV -->|true| CALL["complete_json<br/>system + user + Pydantic schema"]
    CALL --> TIM{"timed out?"}
    TIM -->|yes| FB
    TIM -->|no| VLD{"schema valid?<br/>IDs known?"}
    VLD -->|no| RTY{"retries &lt;= llm_max_retries?"}
    RTY -->|yes| CALL
    RTY -->|no| FB
    VLD -->|yes| OK["LLM output accepted"]
    FB --> RUN["_record_run → AgentRun"]
    OK --> RUN
    RUN --> ERR["status = DEGRADED<br/>if graph_degraded or llm_degraded"]

    classDef fbstyle fill:#d1ecf1,stroke:#0c5460,color:#222
    classDef errstyle fill:#f8d7da,stroke:#721c24,color:#222
    class FB fbstyle
    class ERR errstyle
```

The same envelope runs a second time inside `validate_outputs` (`workflow.py:626`),
which re-validates every persisted artifact against known event / incident / asset /
action IDs before anything is written.

## 4. Full run sequence

```mermaid
sequenceDiagram
    autonumber
    participant C as API client
    participant S as IntelligenceService
    participant W as IntelligenceWorkflow
    participant G as GraphRepository
    participant O as OperationalRepository
    participant L as LLMClient
    participant K as AnalysisCache

    C->>S: analyze(incident_id, scope)
    S->>O: create_workflow(workflow_id)
    S->>S: should_run_intelligence() ?
    alt no material change / anomaly / ambiguity
        S->>O: mark COMPLETED with skip reason
        S-->>C: workflow_id
    else run
        S->>W: ainvoke(payload, workflow_id)
        par parallel evidence fetch
            W->>G: get_incident_evidence
        and
            W->>G: get_incident_graph
        and
            W->>G: get_incident_hypotheses
        and
            W->>G: get_scenarios
        and
            W->>G: get_cascade_paths(max_depth)
        end
        G-->>W: evidence + cascade paths
        Note over G,W: GraphUnavailableError ⇒ graph_degraded,<br/>evidence is NOT fabricated
        W->>K: fingerprint + get(cache_key)
        alt cache hit and not material_change
            K-->>W: cached artifacts; skip signal + fusion
        end
        W->>L: signal agent (JSON)
        L-->>W: SignalAnalysis | deterministic_signal
        loop per trigger event
            W->>L: fusion agent (JSON)
            L-->>W: FusionDecision | deterministic_fusion
        end
        W->>O: attach_events(expected_version)
        O-->>W: ConcurrentUpdateError ⇒ review_required
        W->>G: link_event_to_incident
        W->>L: causal agent (JSON)
        L-->>W: CausalAnalysis | deterministic_causal
        W->>L: impact agent (JSON)
        L-->>W: ImpactAnalysis | deterministic_impact
        W->>W: validate_outputs — re-check all IDs
        W->>O: replace_hypotheses / scenarios / recommendations
        W->>G: upsert_hypothesis / scenario / agent_run
        W->>K: put(cache_key, artifacts)
        W->>O: save_workflow(final state)
        W-->>S: IntelligenceState
        S-->>C: workflow_id (status pollable)
    end
```

## 5. Degradation and status semantics

`consolidate` (`workflow.py:704-716`) resolves the terminal status.

```mermaid
stateDiagram-v2
    [*] --> RUNNING
    RUNNING --> COMPLETED : no errors, no review
    RUNNING --> REVIEW_REQUIRED : review_required
    RUNNING --> DEGRADED : graph_degraded or llm_degraded
    RUNNING --> FAILED : errors and not degraded
    RUNNING --> FAILED : workflow_timeout_seconds exceeded
    COMPLETED --> [*]
    REVIEW_REQUIRED --> [*]
    DEGRADED --> [*]
    FAILED --> [*]
```

Design invariants visible in these diagrams:

- The graph is **evidence only**. `link_event_to_incident` never invents asset edges, and a Neo4j outage yields empty evidence rather than fabricated evidence.
- The operational repository is authoritative for association, not the fusion agent.
- Confidence stays decomposed — event validity, association score, hypothesis support, severity, and cascade score are never collapsed into one number.
- `impact_response` ranks catalogue actions only; it never computes safety-critical scores and never dispatches. Human approval stays outside the graph.