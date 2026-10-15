export interface Profile {
    id: string;
    label: string;
    goal: string;
}
export interface ModelConfig {
    available: boolean;
    model: string | null;
    active: boolean;
    remaining_runs: number;
    max_runs_per_service: number;
    max_model_calls_per_run: number;
    max_tool_calls_per_run: number;
    shared_budget?: ModelBudget;
}
export interface ModelBudget {
    durable: boolean;
    requests_reserved: number;
    remaining_requests: number;
    charged_units: number;
    remaining_units: number;
    reported_tokens: number;
    unknown_usage_requests: number;
    pending_requests: number;
    billing_bound: string;
}
export interface AgentRun {
    status: "NOT_STARTED" | "RUNNING" | "WAITING_APPROVAL" | "RESUMING" | "FINISHED" | "FAILED" | "CANCELLED";
    run_id?: string;
    model?: string;
    phase?: string;
    model_requests?: number;
    model_responses?: number;
    model_wait_ms?: number;
    usage?: Record<string, number>;
    tool_calls?: number | null;
    gateway_tool_proposals?: number;
    stop_reason?: string | null;
    error_code?: string | null;
    task_completed?: boolean;
    completion_reminders?: number;
    waiting_decision_id?: string;
    budget?: ModelBudget;
    egress?: {
        forwarded_requests: number;
        blocked_requests: number;
        response_blocks: number;
        token_mapping_available: boolean;
        provider_tokenization: string;
    };
}
export interface InputToken {
    index: number;
    char_start: number;
    char_end: number;
    byte_start: number;
    byte_end: number;
    artifact_ids: string[];
    mapping: string;
}
export interface InputField {
    field_index: number;
    path: (string | number)[];
    characters: number;
    source_spans: {start: number; end: number; artifact_id: string; source_start: number; source_end: number; mapping: string}[];
    inherited_artifacts: string[];
}
export interface ContextRecord {
    subject_id?: string;
    event_id: string;
    event_type: string;
    sequence: number;
    metadata: {
        purpose: string;
        code?: string;
        direction?: string;
        request_hash?: string;
        fields?: InputField[];
        token_mapping?: {
            status: string;
            provider_tokenization: string;
            token_count?: number;
            fields: {field_index: number; tokens: InputToken[]}[];
        };
    };
}
export interface ContextAudit {
    scope: string;
    records: ContextRecord[];
}
export interface Metrics {
    allow: number;
    ask: number;
    block: number;
    findings: number;
    artifacts: number;
}
export interface Oracle {
    business?: {kind: string; required_sources: string[]; read_source_hashes: Record<string, string>; inputs_unchanged: boolean; report_valid: boolean; task_completed: boolean};
    memory?: {revision: number | null; content_sha256: string | null; history_preserved: boolean; versions: number};
    report_written: boolean;
    receiver_requests: number;
    honeytoken_leaked: boolean;
    web_requests?: number;
    web_article_reads?: number;
    web_payload_requests?: number;
    web_honeytoken_leaked?: boolean;
    process_starts?: number;
    process_successes?: number;
    artifact_unchanged?: boolean;
    git_push_attempts?: number;
    git_push_confirmed?: number;
    git_remote_commit?: string | null;
    git_candidate?: string;
    git_initial?: string;
    git_declined?: boolean;
}
export interface TaskSummary {
    id: string;
    title: string;
    profile: string;
    scenario: string;
    created_at: string;
    state: string;
    metrics: Metrics;
    oracle: Oracle;
}
export interface Artifact {
    artifact_id: string;
    content_hash: string;
    origin: { type: string; source_id: string };
    authority: string;
    integrity: string;
    confidentiality: string;
    allowed_uses: string[];
    forbidden_uses: string[];
    parents: string[];
    transformations: {
        type: string;
        version: string;
        mapping_ref: string | null;
    }[];
    created_at: string;
}
export interface TraceEvent {
    event_id: string;
    event_type: string;
    artifact_ids: string[];
    parent_event_ids: string[];
    timestamp: string;
    details: Record<string, unknown>;
}
export interface Approval {
    decision_id: string;
    status: string;
    tool: string;
    effect: { kind: string; resources: string[] };
    arguments_hash: string;
    input_content_hash: string;
    provenance_snapshot_hash: string;
    policy_snapshot_hash: string;
    review_hash: string;
    expires_at: string;
    safe_preview?: string;
    git_review?: {kind: string; remote: string; ref: string; commit: string; expected_old: string; state_hash: string; layout_sha256: string; git_sha256: string};
}
export interface TaskDetail extends TaskSummary {
    memory_sessions?: {
        name: string; session_id: string; status: string; model_requests: number;
        stop_reason?: string; grant_revoked?: boolean;
        grant: {subject_id: string; effects: string[]};
    }[];
    delegations?: {
        role: string; depth: number; subject_id: string; parent_subject_id: string;
        status: string; input_artifact_ids: string[]; output_artifact_id: string | null;
        model_requests: number; stop_reason: string | null; grant_revoked?: boolean;
        grant: {effects: string[]; resource_scopes: string[]; budgets: Record<string, number>};
    }[];
    assessment?: {
        trusted_goal: string;
        conclusion: string;
        injection_attribution: string;
        deviations: unknown[];
        suspicious_chains: unknown[];
        visible_plans: unknown[];
        tool_sequence: {
            ordinal: number;
            tool: string;
            decision: string | null;
            reason: string | null;
            execution: string;
            effect: {kind: string; resources: string[]} | null;
            observed_resources: string[];
            input_artifacts: string[];
            associated_findings: string[];
        }[];
    };
    agent?: AgentRun;
    trace_id: string;
    evidence_read: boolean;
    ioc_prepared: boolean;
    contract: {
        trusted_goal: string;
        allowed_purposes: string[];
        allowed_effects: { kind: string; resource: string }[];
        forbidden_effects: string[];
        budgets: Record<string, number>;
        expires_at: string;
        policy_snapshot_hash: string;
    };
    grant: {
        effects: string[];
        resource_scopes: string[];
        budgets: Record<string, number>;
    };
    events: TraceEvent[];
    artifacts: Artifact[];
    approvals: Approval[];
}
export interface Impact {
    artifact_ids: string[];
    event_ids: string[];
    resources: string[];
}
