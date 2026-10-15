<script setup lang="ts">
import { computed, ref, onMounted, onBeforeUnmount } from "vue";
import type {
    Approval,
    Artifact,
    Impact,
    Profile,
    TaskDetail,
    TaskSummary,
    TraceEvent,
    ModelConfig,
    ContextAudit,
} from "./types";

const credential = ref(""),
    token = ref(""),
    connected = ref(false),
    profiles = ref<Profile[]>([]),
    tasks = ref<TaskSummary[]>([]);
const detail = ref<TaskDetail | null>(null),
    busy = ref(false),
    error = ref(""),
    notice = ref("");
const title = ref("告警处置与安全恢复"),
    profile = ref("report"),
    scenario = ref("injected");
const tab = ref("trace"),
    selected = ref<Artifact | null>(null),
    impact = ref<Impact | null>(null);
const policy = ref<{ snapshot_hash: string; dsl: string } | null>(null);
const modelConfig = ref<ModelConfig | null>(null);
const features = ref({ context_audit: false, scoped_user_input: false, model_approval: false, web_report: false, artifact_verify: false, git_delivery: false, delegated_report: false, memory_cycle: false, structured_workflows: false });
const businessProfiles = ['event-timeline', 'issue-triage', 'attachment-audit', 'knowledge-reconcile'];
const userMessage = ref("");
const contextAudit = ref<ContextAudit | null>(null);
const selectedRequestId = ref("");
const selectedInputField = ref(0);
const contextRequests = computed(() => contextAudit.value?.records.filter(r => r.event_type === "MODEL_REQUEST_CHECKED") ?? []);
const currentContext = computed(() => contextRequests.value.find(r => r.event_id === selectedRequestId.value) ?? contextRequests.value.at(-1));
const contextFields = computed(() => currentContext.value?.metadata.fields?.filter(f => ["content", "arguments", "description"].includes(String(f.path.at(-1)))) ?? []);
const currentInputField = computed(() => contextFields.value.find(f => f.field_index === selectedInputField.value) ?? contextFields.value[0]);
const inputTokens = computed(() => currentContext.value?.metadata.token_mapping?.fields.find(f => f.field_index === currentInputField.value?.field_index)?.tokens ?? []);
const agentRunning = computed(() => ["RUNNING", "WAITING_APPROVAL", "RESUMING"].includes(detail.value?.agent?.status ?? ""));
const modelTaskLocked = computed(
    () => !!detail.value?.agent && detail.value.agent.status !== "NOT_STARTED",
);
const canStartAgent = computed(
    () =>
        modelConfig.value?.available &&
        !modelConfig.value.active &&
        modelConfig.value.remaining_runs > 0 &&
        (!modelConfig.value.shared_budget || (modelConfig.value.shared_budget.remaining_requests > 0 && modelConfig.value.shared_budget.remaining_units > 0)) &&
        detail.value !== null &&
        (detail.value?.profile === "report" || (features.value.model_approval && detail.value?.profile === "ioc-transfer") || (features.value.web_report && detail.value?.profile === "web-report") || (features.value.artifact_verify && detail.value?.profile === "artifact-verify") || (features.value.git_delivery && ['git-review', 'git-publish'].includes(detail.value?.profile ?? '')) || (features.value.delegated_report && detail.value?.profile === 'delegated-report') || (features.value.memory_cycle && detail.value?.profile.startsWith('memory-')) || (features.value.structured_workflows && businessProfiles.includes(detail.value?.profile ?? ''))) &&
        (detail.value.agent?.status ?? "NOT_STARTED") === "NOT_STARTED" &&
        !detail.value.evidence_read &&
        detail.value.metrics.allow +
            detail.value.metrics.block +
            detail.value.metrics.ask ===
            0,
);
const agentLabels: Record<string, string> = {
    NOT_STARTED: "未运行",
    RUNNING: "运行中",
    WAITING_APPROVAL: "等待操作者审批",
    RESUMING: "恢复运行",
    FINISHED: "模型循环已结束",
    FAILED: "运行失败",
    CANCELLED: "已取消",
};
let refreshTimer: ReturnType<typeof setInterval> | undefined;
onMounted(() => {
    refreshTimer = setInterval(() => {
        if (connected.value && agentRunning.value && !busy.value)
            void run(refresh);
    }, 1200);
});
onBeforeUnmount(() => {
    if (refreshTimer) clearInterval(refreshTimer);
});
const short = (value: string) => (value ? value.slice(-10) : "—");
const labels: Record<string, string> = {
    TOOL_REGISTERED: "工具注册",
    TOOL_PROPOSED: "工具提议",
    EXECUTION_RESULT: "执行结果",
    RESOURCE_READ: "资源读取",
    CONTENT_NORMALIZED: "内容规范化",
    CONTENT_SUMMARIZED: "内容派生",
    MODEL_EXPOSED: "来源暴露登记",
    COMMIT_CHECKED: "提交核验",
    TOOL_CALL_DECIDED: "工具决策",
    TOOL_CALL_REQUESTED: "工具请求",
    TOOL_CALL_EXECUTED: "工具执行",
    DETECTION_FINDING: "注入告警",
    ARTIFACT_CREATED: "来源登记",
    RESOURCE_AFFECTED: "资源影响",
    APPROVAL_RECORDED: "审批记录",
    MODEL_OUTPUT_CREATED: "内容派生",
    USER_MESSAGE: "用户消息登记",
    CONTEXT_REGISTERED: "候选上下文登记",
    MODEL_REQUEST_CHECKED: "模型输入检查",
    MODEL_RESPONSE_CHECKED: "模型回应检查",
    MODEL_EGRESS_BLOCKED: "模型出口阻断",
};
const statusLabels: Record<string, string> = {
    PENDING: "待审批",
    APPROVED: "已批准 · 待提交",
    CONSUMED: "已执行",
    REJECTED: "已拒绝",
    EXPIRED: "已过期",
    FAILED: "执行失败",
};
const assessmentLabels: Record<string, string> = {
    TASK_DEVIATION_OBSERVED: "发现任务偏离",
    EXECUTION_RESULT_REQUIRES_VERIFICATION: "执行结果需要核验",
    SUSPICIOUS_CONTEXT_WITHOUT_PROVEN_TOOL_DEVIATION: "存在可疑上下文，尚无已证实的工具偏离",
    ACTION_REJECTED_WITHOUT_SEMANTIC_EVIDENCE: "动作被拒绝，缺少语义偏离证据",
    NO_RECORDED_TASK_DEVIATION: "当前记录未发现任务偏离",
};
const executionLabels: Record<string, string> = {
    NOT_EXECUTED: "未执行",
    CONFIRMED: "工具返回确认",
    UNKNOWN: "结果不明",
};
const currentProfile = computed(() =>
    profiles.value.find((p) => p.id === detail.value?.profile),
);
const pendingCount = computed(
    () =>
        detail.value?.approvals.filter((a) =>
            ["PENDING", "APPROVED"].includes(a.status),
        ).length ?? 0,
);
async function api<T>(
    path: string,
    method = "GET",
    body?: unknown,
): Promise<T> {
    const response = await fetch("/operator/v1" + path, {
        method,
        headers: {
            Authorization: "Bearer " + token.value,
            ...(body === undefined
                ? {}
                : { "Content-Type": "application/json" }),
        },
        ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    });
    const result = await response.json();
    if (!response.ok) {
        if (response.status === 401) {
            logout();
        }
        throw new Error(
            typeof result.detail === "string"
                ? result.detail
                : "请求参数不符合接口要求",
        );
    }
    return result as T;
}
async function run(work: () => Promise<void>) {
    if (busy.value) return;
    busy.value = true;
    error.value = "";
    notice.value = "";
    try {
        await work();
    } catch (e) {
        error.value = e instanceof Error ? e.message : "连接失败";
    } finally {
        busy.value = false;
    }
}
async function list() {
    tasks.value = (await api<{ tasks: TaskSummary[] }>("/tasks")).tasks;
}
async function refresh() {
    if (detail.value)
        detail.value = await api<TaskDetail>("/tasks/" + detail.value.id);
    await list();
    modelConfig.value =
        (await api<{ model?: ModelConfig }>("/session")).model ?? null;
    if (selected.value && detail.value)
        impact.value = await api<Impact>(
            `/tasks/${detail.value.id}/impact/${selected.value.artifact_id}`,
        );
    if (tab.value === "input" && features.value.context_audit) await refreshContexts();
}
async function refreshContexts() {
    if (!detail.value || !features.value.context_audit) return;
    contextAudit.value = await api<ContextAudit>(`/tasks/${detail.value.id}/contexts`);
    if (!contextRequests.value.some(r => r.event_id === selectedRequestId.value)) {
        selectedRequestId.value = contextRequests.value.at(-1)?.event_id ?? "";
        resetInputField();
    }
}
function resetInputField() {
    selectedInputField.value = (contextFields.value.find(f => f.source_spans.length > 0) ?? contextFields.value[0])?.field_index ?? 0;
}
function inputView() {
    void run(async () => { tab.value = "input"; await refreshContexts(); });
}
function inspectInputSource(identifier: string) {
    const source = detail.value?.artifacts.find(a => a.artifact_id === identifier);
    if (source) { tab.value = "graph"; inspect(source); }
}
function login() {
    void run(async () => {
        token.value = credential.value.trim();
        credential.value = "";
        const session = await api<{ profiles: Profile[]; model?: ModelConfig; features?: typeof features.value }>(
            "/session",
        );
        profiles.value = session.profiles;
        modelConfig.value = session.model ?? null;
        features.value = { context_audit: false, scoped_user_input: false, model_approval: false, web_report: false, artifact_verify: false, git_delivery: false, delegated_report: false, memory_cycle: false, structured_workflows: false, ...session.features };
        policy.value = await api("/policy");
        await list();
        connected.value = true;
    });
}
function logout() {
    connected.value = false;
    token.value = "";
    credential.value = "";
    tasks.value = [];
    detail.value = null;
    selected.value = null;
    impact.value = null;
    policy.value = null;
    modelConfig.value = null;
    contextAudit.value = null;
    userMessage.value = "";
    error.value = "";
}
function create() {
    void run(async () => {
        if (scenario.value === 'quoted' && !businessProfiles.includes(profile.value)) scenario.value = 'injected';
        detail.value = await api("/tasks", "POST", {
            title: title.value,
            profile: profile.value,
            scenario: scenario.value,
            ...(features.value.scoped_user_input && profile.value === "report" && userMessage.value.length > 0 ? {user_message: userMessage.value} : {}),
        });
        selected.value = null;
        impact.value = null;
        contextAudit.value = null;
        selectedRequestId.value = "";
        tab.value = "trace";
        await list();
        notice.value = "任务已创建，真实 MCP 会话与授权契约已就绪。";
    });
}
function choose(id: string) {
    void run(async () => {
        detail.value = await api("/tasks/" + id);
        selected.value = null;
        impact.value = null;
        contextAudit.value = null;
        selectedRequestId.value = "";
        if (tab.value === "input") await refreshContexts();
    });
}
function action(operation: string) {
    void run(async () => {
        const result = await api<{ decision?: string; code?: string }>(
            "/tasks/" + detail.value!.id + "/actions",
            "POST",
            { operation },
        );
        notice.value =
            [result.decision, result.code].filter(Boolean).join(" · ") ||
            "操作完成";
        await refresh();
    });
}
function agentCommand(operation: "start" | "cancel") {
    void run(async () => {
        await api(`/tasks/${detail.value!.id}/agent/${operation}`, "POST");
        await refresh();
        notice.value =
            operation === "start"
                ? "模型任务已启动，工具调用经过安全网关。"
                : "任务已取消；实际副作用请核对 Oracle 与 Trace。";
    });
}
function approve(item: Approval, operation: string) {
    void run(async () => {
        const result = await api<{ code?: string; ok?: boolean }>(
            `/tasks/${detail.value!.id}/approvals/${item.decision_id}/${operation}`,
            "POST",
            { review_hash: item.review_hash },
        );
        notice.value =
            result.code || (result.ok ? "审批操作已记录" : "审批未通过");
        await refresh();
    });
}
function closeTask() {
    void run(async () => {
        await api("/tasks/" + detail.value!.id, "DELETE");
        detail.value = null;
        contextAudit.value = null;
        selected.value = null;
        impact.value = null;
        await list();
        notice.value = "任务已关闭，临时工作区已清理。";
    });
}
function exportTask() {
    void run(async () => {
        const data = await api(`/tasks/${detail.value!.id}/export`);
        const url = URL.createObjectURL(
            new Blob([JSON.stringify(data, null, 2)], {
                type: "application/json",
            }),
        );
        const anchor = document.createElement("a");
        anchor.href = url;
        anchor.download = `sujie-trace-${detail.value!.id}.json`;
        anchor.click();
        URL.revokeObjectURL(url);
        notice.value =
            "脱敏证据已导出，包含契约、审批指纹、来源、决策和 Oracle。";
    });
}
function inspect(item: Artifact) {
    void run(async () => {
        selected.value = item;
        impact.value = await api(
            `/tasks/${detail.value!.id}/impact/${item.artifact_id}`,
        );
    });
}
function eventText(event: TraceEvent) {
    return JSON.stringify(event.details, null, 2);
}
const graph = computed(() => {
    const artifacts = detail.value?.artifacts ?? [];
    const levels = new Map<string, number>();
    for (const item of artifacts)
        levels.set(
            item.artifact_id,
            Math.max(-1, ...item.parents.map((id) => levels.get(id) ?? -1)) + 1,
        );
    const rows = new Map<number, number>();
    const nodes = artifacts.map((item) => {
        const level = levels.get(item.artifact_id)!;
        const row = rows.get(level) ?? 0;
        rows.set(level, row + 1);
        return { item, x: 24 + level * 228, y: 30 + row * 105 };
    });
    const byId = new Map(nodes.map((n) => [n.item.artifact_id, n]));
    const edges = nodes.flatMap((n) =>
        n.item.parents
            .map((id) => {
                const parent = byId.get(id);
                return parent
                    ? {
                          id: id + n.item.artifact_id,
                          x1: parent.x + 198,
                          y1: parent.y + 34,
                          x2: n.x,
                          y2: n.y + 34,
                      }
                    : null;
            })
            .filter((e) => e !== null),
    );
    return {
        nodes,
        edges,
        width: Math.max(700, ...nodes.map((n) => n.x + 230)),
        height: Math.max(220, ...nodes.map((n) => n.y + 110)),
    };
});
</script>

<template>
    <div v-if="!connected" class="login-shell">
        <section class="login-story">
            <div class="brand">
                <span class="brand-icon">溯</span
                ><span>溯界 <small>SUJIE</small></span>
            </div>
            <p class="eyebrow">AGENT RUNTIME SECURITY</p>
            <h1>让每一次工具调用<br />都有可信边界。</h1>
            <p class="story-text">
                从任务契约到真实副作用，追踪不可信内容的传播，审查外发动作，保留可核查的决策证据。
            </p>
            <div class="boundary">
                <span>任务契约</span><b>→</b><span>权限网关</span><b>→</b
                ><span>实际效果</span>
            </div>
            <p class="range-note">封闭本地演示 · 合成数据 · 真实 stdio MCP</p>
        </section>
        <section class="login-card">
            <p class="eyebrow">OPERATOR ACCESS</p>
            <h2>进入操作者控制台</h2>
            <p>使用本次启动生成的本机凭据。凭据仅保留在当前页面内存。</p>
            <form @submit.prevent="login">
                <label for="credential">操作者凭据</label
                ><input
                    id="credential"
                    v-model="credential"
                    type="password"
                    autocomplete="off"
                    placeholder="粘贴 operator-token.txt 中的凭据"
                    required
                /><button class="primary wide" :disabled="busy">
                    {{ busy ? "正在连接…" : "连接控制面" }} <span>↗</span>
                </button>
            </form>
            <p v-if="error" class="error" role="alert">{{ error }}</p>
            <div class="login-foot">
                凭据文件：<code>sujie/.control-runtime/operator-token.txt</code
                ><br />任务采用临时工作区，服务关闭后不保留。
            </div>
        </section>
    </div>
    <div v-else class="workspace">
        <aside class="sidebar">
            <div class="brand">
                <span class="brand-icon">溯</span
                ><span>溯界 <small>SUJIE</small></span>
            </div>
            <div class="sidebar-label">
                任务工作区 <span>{{ tasks.length }}/8</span>
            </div>
            <button
                v-for="task in tasks"
                :key="task.id"
                class="task-nav"
                :class="{ active: detail?.id === task.id }"
                :disabled="busy"
                @click="choose(task.id)"
            >
                <strong>{{ task.title }}</strong
                ><small
                    >{{
                        task.scenario === "injected" ? "注入证据" : task.scenario === "quoted" ? "合法原文引用" : "正常证据"
                    }}
                    · {{ task.metrics.block }} 次阻断</small
                >
            </button>
            <p v-if="!tasks.length" class="empty-side">
                尚无任务。创建一个契约限定的任务，开始观察决策链。
            </p>
            <form class="create-form" @submit.prevent="create">
                <h3>创建任务</h3>
                <label for="title">任务名称</label
                ><input
                    id="title"
                    v-model="title"
                    maxlength="80"
                    required
                /><label for="profile">授权模板</label
                ><select id="profile" v-model="profile">
                    <option v-for="p in profiles" :key="p.id" :value="p.id">
                        {{ p.label }}
                    </option></select
                ><label for="scenario">证据场景</label
                ><select id="scenario" v-model="scenario">
                    <option value="injected">含提示注入</option>
                    <option value="clean">正常证据</option>
                    <option v-if="businessProfiles.includes(profile)" value="quoted">合法引用危险原文</option></select
                ><template v-if="features.scoped_user_input && profile === 'report' && modelConfig?.available">
                    <label for="user-message">用户补充（可选）</label>
                    <textarea id="user-message" v-model="userMessage" maxlength="4096" rows="3" placeholder="补充分析要求；运行模型任务时生效"></textarea>
                    <small class="input-note">补充消息遵循当前任务授权范围。</small>
                </template><button
                    class="primary wide"
                    :disabled="busy || tasks.length >= 8"
                >
                    {{ busy ? "处理中…" : "创建并连接 MCP" }}
                </button>
            </form>
            <div class="sidebar-bottom">
                <span class="live-dot"></span> 独立操作者入口<button
                    class="quiet light"
                    :disabled="busy"
                    @click="logout"
                >
                    退出
                </button>
            </div>
        </aside>
        <main>
            <header class="topbar">
                <span
                    >安全运行工作台 <b>/</b>
                    {{ currentProfile?.label ?? "任务总览" }}</span
                ><span class="mode">LOCAL · SEALED RANGE</span>
            </header>
            <div class="main-content">
                <div class="page-heading">
                    <div>
                        <p class="eyebrow">CONTROL / TRACE / APPROVAL</p>
                        <h1>{{ detail?.title ?? "从一个受限任务开始" }}</h1>
                        <p>
                            {{
                                detail?.contract.trusted_goal ??
                                "创建任务后，可检查真实 MCP 决策、动作绑定审批与来源传播。"
                            }}
                        </p>
                    </div>
                    <div v-if="detail" class="action-row">
                        <button
                            class="secondary"
                            :disabled="busy"
                            @click="exportTask"
                        >
                            导出脱敏证据 ↓
                        </button>
                        <button
                            class="secondary"
                            :disabled="busy"
                            @click="run(refresh)"
                        >
                            刷新状态 ↻
                        </button>
                    </div>
                </div>
                <div v-if="error" class="error banner" role="alert">
                    {{ error }}
                </div>
                <div v-if="notice" class="notice banner" role="status">
                    {{ notice }}
                </div>
                <template v-if="detail">
                    <section class="metric-grid">
                        <article>
                            <span>允许执行</span
                            ><strong>{{ detail.metrics.allow }}</strong
                            ><small>ALLOW</small>
                        </article>
                        <article>
                            <span>待审动作记录</span
                            ><strong>{{ detail.metrics.ask }}</strong
                            ><small>ASK · 当前待处理 {{ pendingCount }}</small>
                        </article>
                        <article>
                            <span>已阻断动作</span
                            ><strong>{{ detail.metrics.block }}</strong
                            ><small>BLOCK</small>
                        </article>
                        <article>
                            <span>检测发现</span
                            ><strong>{{ detail.metrics.findings }}</strong
                            ><small
                                >{{
                                    detail.metrics.artifacts
                                }}
                                个来源节点</small
                            >
                        </article>
                    </section>
                    <section class="contract card">
                        <div class="section-head">
                            <h2>任务授权边界</h2>
                            <span class="badge">固定契约 · ACTIVE</span>
                        </div>
                        <div class="contract-grid">
                            <div>
                                <span class="field-label">允许副作用</span>
                                <ul>
                                    <li
                                        v-for="effect in detail.contract
                                            .allowed_effects"
                                        :key="effect.kind + effect.resource"
                                    >
                                        <b>{{ effect.kind }}</b
                                        ><code>{{ effect.resource }}</code>
                                    </li>
                                </ul>
                            </div>
                            <div>
                                <span class="field-label">明确禁止</span>
                                <div class="tags">
                                    <span
                                        v-for="effect in detail.contract
                                            .forbidden_effects"
                                        :key="effect"
                                        >{{ effect }}</span
                                    >
                                </div>
                                <p class="meta">
                                    预算：工具
                                    {{ detail.contract.budgets.tool_calls }} /
                                    网络
                                    {{ detail.contract.budgets.network_calls }}
                                    / 子 Agent
                                    {{ detail.contract.budgets.subagents }}
                                </p>
                                <p class="meta">
                                    截止
                                    {{
                                        new Date(
                                            detail.contract.expires_at,
                                        ).toLocaleString()
                                    }}
                                </p>
                            </div>
                        </div>
                        <details>
                            <summary>查看 Grant 与策略快照</summary>
                            <pre>{{
                                JSON.stringify(detail.grant, null, 2)
                            }}</pre>
                            <code class="hash">{{
                                detail.contract.policy_snapshot_hash
                            }}</code>
                        </details>
                    </section>
                    <section v-if="detail.oracle.business" class="card">
                        <h2>多源业务核查</h2>
                        <p class="caption">分别核对实际读取、报告事实与原始资料状态。</p>
                        <p class="meta">已读取 {{ Object.keys(detail.oracle.business.read_source_hashes).length }} / {{ detail.oracle.business.required_sources.length }} 项资料 · 原资料{{ detail.oracle.business.inputs_unchanged ? '保持原样' : '发生变化' }} · 报告{{ detail.oracle.business.report_valid ? '核对通过' : '尚未通过核对' }}</p>
                    </section>
                    <section class="actions card">
                        <div class="section-head">
                            <h2>自主模型任务</h2>
                            <span class="badge">{{
                                agentLabels[
                                    detail.agent?.status ?? "NOT_STARTED"
                                ]
                            }}</span>
                        </div>
                        <p class="meta" v-if="modelConfig?.available">
                            {{ modelConfig.model }} · 每会话主循环最多
                            {{ modelConfig.max_model_calls_per_run }} 次模型请求
                            /
                            {{ modelConfig.max_tool_calls_per_run }} 次工具调用
                            · 本机服务剩余
                            {{ modelConfig.remaining_runs }} 次启动机会
                        </p>
                        <p class="meta" v-else>
                            尚未配置模型。启动服务时指定百炼凭据文件后可运行。
                        </p>
                        <p class="meta" v-if="modelConfig?.shared_budget">
                            共享模型预算：剩余{{ modelConfig.shared_budget.remaining_requests }}次后端调用；
                            {{ modelConfig.shared_budget.durable ? "跨重启保留" : "当前进程" }}。
                            未知用量请求{{ modelConfig.shared_budget.unknown_usage_requests }}次，本地预留费用不等于云端账单。
                        </p>
                        <div class="action-row">
                            <button
                                class="primary"
                                :disabled="busy || !canStartAgent"
                                @click="agentCommand('start')"
                            >
                                运行模型任务</button
                            ><button
                                class="secondary danger"
                                :disabled="busy || !agentRunning"
                                @click="agentCommand('cancel')"
                            >
                                取消模型任务
                            </button>
                        </div>
                        <p class="caption">
                            使用全新任务运行模型，状态自动更新。子循环独立计数，与主循环共享任务及服务预算；固定动作演示请另建任务。
                        </p>
                        <div
                            v-if="
                                detail.agent &&
                                detail.agent.status !== 'NOT_STARTED'
                            "
                            class="oracle"
                        >
                            <span
                                >主循环请求 / 返回
                                {{ detail.agent.model_requests ?? 0 }} /
                                {{ detail.agent.model_responses ?? 0 }}</span
                            >
                            <span
                                >主循环已返回 Token 用量
                                {{
                                    detail.agent.usage?.total_tokens ?? "—"
                                }}</span
                            >
                            <span
                                :class="{ passed: detail.agent.task_completed }"
                                >关键事实任务
                                {{
                                    detail.agent.task_completed
                                        ? "完成"
                                        : "未确认完成"
                                }}</span
                            >
                        </div>
                        <p
                            v-if="agentRunning"
                            class="meta model-status"
                            role="status"
                        >
                            {{
                                detail.agent?.status === "WAITING_APPROVAL"
                                    ? "已暂停副作用，请在动作审批中批准并提交，或拒绝。"
                                    : detail.agent?.phase === "MODEL_WAIT"
                                    ? "正在等待模型响应…"
                                    : "网关正在处理模型工具提议…"
                            }}
                        </p>
                        <p
                            v-if="
                                detail.agent?.stop_reason ||
                                detail.agent?.error_code
                            "
                            class="meta model-status"
                        >
                            停止原因：{{
                                detail.agent.error_code ??
                                detail.agent.stop_reason
                            }}
                        </p>
                    </section>
                    <section v-if="detail.delegations?.length" class="card">
                        <h2>实际子 Agent 链</h2>
                        <p class="caption">独立上下文与受限工具；同一可信 Host 内运行。任务预算包含所有层级调用。</p>
                        <article v-for="node in detail.delegations" :key="node.subject_id" class="source-detail">
                            <h3>{{ node.depth === 1 ? '子 Agent' : '孙 Agent' }} · {{ node.role }} · {{ node.status }}</h3>
                            <dl class="bindings">
                                <dt>主体 / 父主体</dt><dd>{{ node.subject_id }} / {{ node.parent_subject_id }}</dd>
                                <dt>权限</dt><dd>{{ node.grant.effects.join(', ') }}</dd>
                                <dt>资源范围</dt><dd>{{ node.grant.resource_scopes.join(', ') }}</dd>
                                <dt>输入来源</dt><dd>{{ node.input_artifact_ids.join(', ') }}</dd>
                                <dt>输出来源</dt><dd>{{ node.output_artifact_id || '尚无已接受输出' }}</dd>
                                <dt>已发模型请求</dt><dd>{{ node.model_requests }} · {{ node.grant_revoked ? '子授权已撤销' : '运行中' }}</dd>
                                <dt>停止原因</dt><dd>{{ node.stop_reason || '—' }}</dd>
                            </dl>
                        </article>
                    </section>
                    <section v-if="detail.memory_sessions?.length" class="card">
                        <h2>跨会话记忆证据</h2>
                        <p class="caption">归档与核对使用独立合同、模型上下文和MCP连接，共享任务预算；记忆内容保持数据身份。</p>
                        <p class="meta" v-if="detail.oracle.memory">实际版本 {{ detail.oracle.memory.revision ?? '未知' }} · 历史原文{{ detail.oracle.memory.history_preserved ? '已核对' : '尚未确认' }}</p>
                        <article v-for="node in detail.memory_sessions" :key="node.session_id" class="source-detail">
                            <h3>{{ node.name === 'capture' ? '会话一 · 原文归档' : '会话二 · 版本核对' }} · {{ node.status }}</h3>
                            <dl class="bindings">
                                <dt>会话 / 主体</dt><dd>{{ node.session_id }} / {{ node.grant.subject_id }}</dd>
                                <dt>允许效果</dt><dd>{{ node.grant.effects.join(', ') }}</dd>
                                <dt>模型请求</dt><dd>{{ node.model_requests }} · {{ node.grant_revoked ? '授权已撤销' : '运行中' }}</dd>
                                <dt>停止原因</dt><dd>{{ node.stop_reason || '—' }}</dd>
                            </dl>
                        </article>
                    </section>
                    <section class="actions card">
                        <div class="section-head">
                            <h2>受控工作流</h2>
                            <span class="caption"
                                >{{ detail.profile === 'web-report' ? '网页任务由智能体读取与生成报告' : detail.profile === 'artifact-verify' ? '智能体核对清单与构件摘要' : detail.profile.startsWith('git-') ? '智能体检视与受限审批发布' : detail.profile === 'delegated-report' ? '主Agent→复核Agent→基线核验Agent' : detail.profile.startsWith('memory-') ? '原文归档→新会话核对→版本状态验证' : businessProfiles.includes(detail.profile) ? '智能体读取多源资料、核查规则并保存报告' : '固定动作演示 · 调用真实网关' }}</span
                            >
                        </div>
                        <div v-if="['report', 'ioc-transfer'].includes(detail.profile)" class="action-row">
                            <button
                                class="primary"
                                :disabled="busy || modelTaskLocked"
                                @click="action('read_evidence')"
                            >
                                ① 读取证据</button
                            ><button
                                class="secondary"
                                :disabled="
                                    busy ||
                                    modelTaskLocked ||
                                    !detail.evidence_read
                                "
                                @click="action('write_report')"
                            >
                                ② 生成本地报告</button
                            ><template v-if="detail.profile === 'ioc-transfer'"
                                ><button
                                    class="secondary"
                                    :disabled="
                                        busy ||
                                        modelTaskLocked ||
                                        !detail.evidence_read
                                    "
                                    @click="action('prepare_ioc')"
                                >
                                    ③ 提取公开 IOC</button
                                ><button
                                    class="secondary"
                                    :disabled="
                                        busy ||
                                        modelTaskLocked ||
                                        !detail.ioc_prepared
                                    "
                                    @click="action('request_ioc_transfer')"
                                >
                                    ④ 请求审批外发
                                </button></template
                            >
                        </div>
                        <div v-if="['report', 'ioc-transfer'].includes(detail.profile)" class="probe-row">
                            <span>攻击路径验证</span
                            ><button
                                class="quiet danger"
                                :disabled="
                                    busy ||
                                    modelTaskLocked ||
                                    !detail.evidence_read
                                "
                                @click="action('probe_private')"
                            >
                                尝试读取私密文件</button
                            ><button
                                class="quiet danger"
                                :disabled="
                                    busy ||
                                    modelTaskLocked ||
                                    !detail.evidence_read
                                "
                                @click="action('probe_egress')"
                            >
                                尝试外发原始证据
                            </button>
                        </div>
                        <div class="oracle">
                            <template v-if="detail.profile.startsWith('git-')">
                                <span>推送尝试 {{ detail.oracle.git_push_attempts ?? 0 }}</span>
                                <span>确认变更 {{ detail.oracle.git_push_confirmed ?? 0 }}</span>
                                <span>远端提交 {{ short(detail.oracle.git_remote_commit ?? '') }}</span>
                            </template>
                            <template v-if="detail.profile === 'artifact-verify'">
                                <span>实际进程启动 {{ detail.oracle.process_starts ?? 0 }}</span>
                                <span>核验执行成功 {{ detail.oracle.process_successes ?? 0 }}</span>
                                <span :class="detail.oracle.artifact_unchanged ? 'passed' : 'failed'">构件保持原值 {{ detail.oracle.artifact_unchanged ? '是' : '否' }}</span>
                            </template>
                            <template v-if="detail.profile === 'web-report'">
                                <span>网页实际读取 {{ detail.oracle.web_article_reads ?? 0 }}</span>
                                <span>携带数据的网络请求 {{ detail.oracle.web_payload_requests ?? 0 }}</span>
                                <span :class="detail.oracle.web_honeytoken_leaked ? 'failed' : 'passed'">网络合成蜜标泄漏 {{ detail.oracle.web_honeytoken_leaked ? '是' : '否' }}</span>
                            </template>
                            <span
                                :class="{
                                    passed: detail.oracle.report_written,
                                }"
                                >报告落盘
                                {{
                                    detail.oracle.report_written
                                        ? "已完成"
                                        : "未执行"
                                }}</span
                            ><span
                                >接收端实际请求
                                {{ detail.oracle.receiver_requests }}</span
                            ><span
                                :class="
                                    detail.oracle.honeytoken_leaked
                                        ? 'failed'
                                        : 'passed'
                                "
                                >合成蜜标泄漏
                                {{
                                    detail.oracle.honeytoken_leaked
                                        ? "是"
                                        : "否"
                                }}</span
                            >
                        </div>
                    </section>
                    <nav class="tabs" aria-label="任务证据视图">
                        <button v-if="features.context_audit" :class="{active: tab === 'input'}" @click="inputView">模型输入来源</button>
                        <button
                            :class="{ active: tab === 'trace' }"
                            @click="tab = 'trace'"
                        >
                            决策时序
                            <span>{{ detail.events.length }}</span></button
                        ><button
                            :class="{ active: tab === 'graph' }"
                            @click="tab = 'graph'"
                        >
                            来源与影响
                            <span>{{ detail.artifacts.length }}</span></button
                        ><button
                            :class="{ active: tab === 'approvals' }"
                            @click="tab = 'approvals'"
                        >
                            动作审批 <span>{{ pendingCount }}</span></button
                        ><button v-if="detail.assessment" :class="{ active: tab === 'assessment' }" @click="tab = 'assessment'">任务级研判</button><button
                            :class="{ active: tab === 'policy' }"
                            @click="tab = 'policy'"
                        >
                            策略快照
                        </button>
                    </nav>
                    <section v-if="tab === 'input'" class="card input-panel">
                        <div class="section-head"><h2>模型输入区间与来源</h2><span class="badge">本地区间</span></div>
                        <p class="caption">按实际API文本字段记录字符、UTF-8字节与本地token区间。云模型内部token和聊天模板未知；字面匹配、父来源继承与未绑定区间分别标记。</p>
                        <p v-if="!contextRequests.length" class="empty">尚无通过出口检查的模型请求。运行模型任务后可查看输入来源。</p>
                        <div v-else>
                            <div class="input-selectors">
                                <label>请求快照<select v-model="selectedRequestId" @change="resetInputField"><option v-for="record in contextRequests" :key="record.event_id" :value="record.event_id">#{{ record.sequence }} · {{ record.metadata.purpose }} · {{ short(record.subject_id || '') }}</option></select></label>
                                <label>文本字段<select v-model="selectedInputField"><option v-for="field in contextFields" :key="field.field_index" :value="field.field_index">{{ field.path.join('.') }} · {{ field.characters }}字符</option></select></label>
                            </div>
                            <p class="meta">请求摘要 {{ currentContext?.metadata.request_hash }} · {{ currentContext?.metadata.token_mapping?.status }}</p>
                            <p v-if="!inputTokens.length" class="caption">当前仅有字符区间；本地token映射不可用或该字段为空。</p>
                            <div class="token-table-wrap" v-else>
                                <table class="token-table"><thead><tr><th>本地token</th><th>字符区间</th><th>UTF-8字节</th><th>映射类型</th><th>关联来源</th></tr></thead><tbody>
                                    <tr v-for="item in inputTokens.slice(0, 200)" :key="item.index"><td>{{ item.index }}</td><td>[{{ item.char_start }}, {{ item.char_end }})</td><td>[{{ item.byte_start }}, {{ item.byte_end }})</td><td>{{ item.mapping }}</td><td><button v-for="source in item.artifact_ids" :key="source" class="quiet" @click="inspectInputSource(source)">{{ short(source) }}</button><span v-if="!item.artifact_ids.length">未绑定</span></td></tr>
                                </tbody></table>
                            </div>
                            <p class="caption">显示前{{ Math.min(200, inputTokens.length) }}/{{ inputTokens.length }}个token；完整区间包含在脱敏导出中，不包含token文本或ID。</p>
                            <details><summary>字符来源片段与保守父集合</summary><pre>{{ JSON.stringify(currentInputField, null, 2) }}</pre></details>
                        </div>
                        <div v-for="blocked in contextAudit?.records.filter(r => r.event_type === 'MODEL_EGRESS_BLOCKED')" :key="blocked.event_id" class="error banner">{{ blocked.metadata.purpose }} · {{ blocked.metadata.direction }} · {{ blocked.metadata.code }}</div>
                    </section>
                    <section v-else-if="tab === 'assessment' && detail.assessment" class="card input-panel">
                        <div class="section-head"><h2>意图、提议序列与实际执行</h2><span class="badge">{{ assessmentLabels[detail.assessment.conclusion] ?? detail.assessment.conclusion }}</span></div>
                        <p>{{ detail.assessment.trusted_goal }}</p>
                        <p class="caption">依据可信合同、全量已记录工具提议及执行结果。上下文关联不等于攻击因果证明；可见计划仅指模型公开工具提议，未读取隐藏思维。</p>
                        <div class="token-table-wrap">
                            <table class="token-table"><thead><tr><th>序号</th><th>工具与效果</th><th>决策</th><th>执行证据</th><th>实际影响</th></tr></thead><tbody>
                                <tr v-for="step in detail.assessment.tool_sequence" :key="step.ordinal"><td>{{ step.ordinal }}</td><td>{{ step.tool }}<br>{{ step.effect?.kind ?? '参数未形成有效动作' }}</td><td>{{ step.decision ?? '尚未裁决' }}<br>{{ step.reason }}</td><td>{{ executionLabels[step.execution] ?? step.execution }}</td><td>{{ step.observed_resources.join(', ') || '无已记录副作用' }}</td></tr>
                            </tbody></table>
                        </div>
                        <p class="caption">执行结果不明时，资源列表不能证明未发生影响；应结合接收端与资源状态核验。</p>
                        <details><summary>偏离依据与多步关联</summary><pre>{{ JSON.stringify({ deviations: detail.assessment.deviations, chains: detail.assessment.suspicious_chains, visible_plans: detail.assessment.visible_plans }, null, 2) }}</pre></details>
                    </section>
                    <section v-else-if="tab === 'trace'" class="card trace-panel">
                        <div class="section-head">
                            <h2>可核查的运行记录</h2>
                            <code class="caption"
                                >Trace {{ short(detail.trace_id) }}</code
                            >
                        </div>
                        <p v-if="!detail.events.length" class="empty">
                            执行“读取证据”后，运行记录将显示在这里。
                        </p>
                        <ol class="timeline">
                            <li
                                v-for="(event, index) in detail.events"
                                :key="event.event_id"
                            >
                                <span class="event-index">{{
                                    String(index + 1).padStart(2, "0")
                                }}</span>
                                <div>
                                    <div class="event-title">
                                        <strong>{{
                                            labels[event.event_type] ??
                                            event.event_type
                                        }}</strong
                                        ><span
                                            v-if="event.details.decision"
                                            class="badge"
                                            :class="
                                                String(
                                                    event.details.decision,
                                                ).toLowerCase()
                                            "
                                            >{{ event.details.decision }}</span
                                        ><code>{{
                                            short(event.event_id)
                                        }}</code>
                                    </div>
                                    <p v-if="event.details.tool" class="meta">
                                        {{ event.details.tool }}
                                        <span v-if="event.details.reason"
                                            >· {{ event.details.reason }}</span
                                        >
                                    </p>
                                    <details>
                                        <summary>决策详情与关联</summary>
                                        <pre>{{ eventText(event) }}</pre>
                                        <p class="meta">
                                            来源节点：{{
                                                event.artifact_ids
                                                    .map(short)
                                                    .join(", ") || "—"
                                            }}
                                        </p>
                                        <p class="meta">
                                            前序事件：{{
                                                event.parent_event_ids
                                                    .map(short)
                                                    .join(", ") || "—"
                                            }}
                                        </p>
                                    </details>
                                </div>
                            </li>
                        </ol>
                    </section>
                    <section
                        v-else-if="tab === 'graph'"
                        class="card graph-panel"
                    >
                        <div class="section-head">
                            <h2>来源传播与实际影响</h2>
                            <span class="caption"
                                >点击节点，查看后继来源及资源影响</span
                            >
                        </div>
                        <p v-if="!detail.artifacts.length" class="empty">
                            读取证据后，来源图将自动生成。
                        </p>
                        <div v-else class="graph-scroll">
                            <svg
                                :viewBox="`0 0 ${graph.width} ${graph.height}`"
                                :width="graph.width"
                                :height="graph.height"
                                role="group"
                                aria-label="来源传播有向图"
                            >
                                <defs>
                                    <marker
                                        id="arrow"
                                        viewBox="0 0 10 10"
                                        refX="9"
                                        refY="5"
                                        markerWidth="5"
                                        markerHeight="5"
                                        orient="auto-start-reverse"
                                    >
                                        <path
                                            d="M 0 0 L 10 5 L 0 10 z"
                                            fill="#a6c8b5"
                                        />
                                    </marker>
                                </defs>
                                <line
                                    v-for="edge in graph.edges"
                                    :key="edge.id"
                                    :x1="edge.x1"
                                    :y1="edge.y1"
                                    :x2="edge.x2"
                                    :y2="edge.y2"
                                    class="graph-edge"
                                    marker-end="url(#arrow)"
                                />
                                <g
                                    v-for="node in graph.nodes"
                                    :key="node.item.artifact_id"
                                    class="graph-node"
                                    :class="{
                                        selected:
                                            selected?.artifact_id ===
                                            node.item.artifact_id,
                                        affected: impact?.artifact_ids.includes(
                                            node.item.artifact_id,
                                        ),
                                    }"
                                    role="button"
                                    tabindex="0"
                                    :aria-label="`查看来源 ${short(node.item.artifact_id)}`"
                                    @click="inspect(node.item)"
                                    @keydown.enter.prevent="inspect(node.item)"
                                    @keydown.space.prevent="inspect(node.item)"
                                >
                                    <rect
                                        :x="node.x"
                                        :y="node.y"
                                        width="198"
                                        height="72"
                                        rx="9"
                                    />
                                    <text :x="node.x + 12" :y="node.y + 23">
                                        {{
                                            node.item.transformations
                                                .map((t) => t.type)
                                                .join(" / ") ||
                                            node.item.origin.type
                                        }}
                                    </text>
                                    <text
                                        :x="node.x + 12"
                                        :y="node.y + 43"
                                        class="graph-id"
                                    >
                                        {{ short(node.item.artifact_id) }}
                                    </text>
                                    <text
                                        :x="node.x + 12"
                                        :y="node.y + 60"
                                        class="graph-id"
                                    >
                                        {{
                                            node.item.forbidden_uses.includes(
                                                "TRANSFER",
                                            )
                                                ? "TRANSFER 禁止"
                                                : "用途见来源详情"
                                        }}
                                    </text>
                                </g>
                            </svg>
                        </div>
                        <div v-if="selected" class="source-detail">
                            <h3>来源 {{ short(selected.artifact_id) }}</h3>
                            <p>
                                <b>{{ selected.origin.type }}</b> ·
                                {{ selected.origin.source_id }}
                            </p>
                            <div class="tags">
                                <span
                                    v-for="use in selected.forbidden_uses"
                                    :key="use"
                                    >禁止 {{ use }}</span
                                >
                            </div>
                            <code class="hash">{{
                                selected.content_hash
                            }}</code>
                            <p class="meta">
                                {{ impact?.artifact_ids.length }}
                                个后继节点（含自身） ·
                                {{ impact?.event_ids.length }} 个关联事件
                            </p>
                            <h4>实际影响资源</h4>
                            <ul v-if="impact?.resources.length">
                                <li
                                    v-for="resource in impact.resources"
                                    :key="resource"
                                >
                                    <code>{{ resource }}</code>
                                </li>
                            </ul>
                            <p v-else class="meta">尚无记录到的资源副作用。</p>
                        </div>
                    </section>
                    <section
                        v-else-if="tab === 'approvals'"
                        class="approval-panel"
                    >
                        <article
                            v-for="item in detail.approvals"
                            :key="item.decision_id"
                            class="card approval-card"
                        >
                            <div class="section-head">
                                <h2>
                                    {{ item.effect.kind }}
                                    <small>{{ short(item.decision_id) }}</small>
                                </h2>
                                <span
                                    class="badge"
                                    :class="item.status.toLowerCase()"
                                    >{{ statusLabels[item.status] }}</span
                                >
                            </div>
                            <p class="meta">
                                {{ item.tool }} →
                                {{ item.effect.resources.join(", ") }}
                            </p>
                            <div
                                v-if="item.safe_preview"
                                class="review-preview"
                            >
                                <span class="field-label"
                                    >绑定输入 · 公开 IPv4 IOC</span
                                >
                                <pre>{{ item.safe_preview }}</pre>
                            </div>
                            <div v-if="item.git_review" class="review-preview">
                                <span class="field-label">封闭本机 Git · 待审批操作</span>
                                <dl class="bindings">
                                    <dt>远端与分支</dt><dd>{{ item.git_review.remote }} → {{ item.git_review.ref }}</dd>
                                    <dt>待发布提交</dt><dd>{{ item.git_review.commit }}</dd>
                                    <dt>审批绑定的远端旧值</dt><dd>{{ item.git_review.expected_old || '分支尚不存在' }}</dd>
                                    <dt>对象与配置快照</dt><dd>{{ item.git_review.state_hash }}</dd>
                                </dl>
                            </div>
                            <dl class="bindings">
                                <dt>参数指纹</dt>
                                <dd>{{ item.arguments_hash }}</dd>
                                <dt>输入指纹</dt>
                                <dd>{{ item.input_content_hash }}</dd>
                                <dt>来源快照</dt>
                                <dd>{{ item.provenance_snapshot_hash }}</dd>
                                <dt>策略快照</dt>
                                <dd>{{ item.policy_snapshot_hash }}</dd>
                                <dt>审批截止</dt>
                                <dd>
                                    {{
                                        new Date(
                                            item.expires_at,
                                        ).toLocaleString()
                                    }}
                                </dd>
                            </dl>
                            <div class="action-row">
                                <button
                                    class="primary"
                                    :disabled="
                                        busy || item.status !== 'PENDING'
                                    "
                                    @click="approve(item, 'approve')"
                                >
                                    批准此动作</button
                                ><button
                                    class="secondary danger"
                                    :disabled="
                                        busy ||
                                        !['PENDING', 'APPROVED'].includes(
                                            item.status,
                                        )
                                    "
                                    @click="approve(item, 'reject')"
                                >
                                    拒绝</button
                                ><button
                                    class="secondary"
                                    :disabled="
                                        busy || item.status !== 'APPROVED'
                                    "
                                    @click="approve(item, 'commit')"
                                >
                                    提交已批准动作
                                </button>
                            </div>
                            <p class="caption">
                                审批仅绑定以上动作。提交时，网关再次核对授权与快照。
                            </p>
                        </article>
                        <div v-if="!detail.approvals.length" class="card empty">
                            暂无可审批动作。公开 IOC 通报和 Git 发布模板可发起审批；硬阻断动作不能通过审批放行。
                        </div>
                    </section>
                    <section v-else class="card">
                        <div class="section-head">
                            <h2>当前策略</h2>
                            <span class="badge">只读快照</span>
                        </div>
                        <code class="hash">{{ policy?.snapshot_hash }}</code>
                        <pre class="policy-dsl">{{ policy?.dsl }}</pre>
                    </section>
                    <footer class="task-footer">
                        <span
                            >临时任务 · 合成证据 · 真实 MCP 与受限模型循环</span
                        ><button
                            class="quiet danger"
                            :disabled="busy"
                            @click="closeTask"
                        >
                            关闭任务并清理工作区
                        </button>
                    </footer>
                </template>
                <section v-else class="welcome card">
                    <span class="welcome-symbol">⌁</span>
                    <h2>授权先于执行，证据贯穿全程。</h2>
                    <p>
                        左侧选择任务模板。先读取资料，再核对真实效果与安全恢复；公开
                        IOC 通报和 Git 发布支持审批、一次性提交及模型续跑。
                    </p>
                    <div class="welcome-grid">
                        <div>
                            <b>01 / 契约</b>
                            <p>明确目的、资源、效果与预算</p>
                        </div>
                        <div>
                            <b>02 / 防御</b>
                            <p>观察允许、待审和阻断的真实决策</p>
                        </div>
                        <div>
                            <b>03 / 证据</b>
                            <p>核对来源、影响与接收端请求</p>
                        </div>
                    </div>
                </section>
            </div>
        </main>
    </div>
</template>
