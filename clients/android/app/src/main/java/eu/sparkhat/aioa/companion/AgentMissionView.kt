package eu.sparkhat.aioa.companion

import kotlinx.serialization.json.*

enum class AgentState {
    AGENT_PENDING, AGENT_APPROVED, AGENT_RUNNING, AGENT_COMPLETED,
    AGENT_FAILED, AGENT_UNKNOWN, AGENT_STOPPED
}

/** Typed additive view after MobileClient has verified the signed observation. */
data class AgentMissionView(
    val taskId: String, val state: AgentState, val taskDigest: String,
    val files: JsonObject, val diff: JsonObject, val steps: JsonArray,
    val tests: JsonObject, val installPlan: JsonObject, val git: JsonObject,
    val receipt: JsonObject?, val providerId: String, val modelId: String
) {
    val needsHostApproval get() = state == AgentState.AGENT_PENDING
    companion object {
        val taskPattern = Regex("agent-[0-9a-f]{32}")
        private val deniedPermissions = setOf("run","approve","native_execute","install","github_write","meta_spend")
        fun decode(data: JsonObject, source: String, capsule: String, ownerScope: String): AgentMissionView {
            require(Wire.text(data,"schema") == "aioa.mobile.mission-view.v2" &&
                taskPattern.matches(Wire.text(data,"task_id")) && Wire.hex64.matches(Wire.text(data,"task_digest")) &&
                Wire.text(data,"source_sha") == source && Wire.text(data,"capsule_digest") == capsule &&
                Wire.text(data,"owner_scope_digest") == ownerScope && Wire.text(data,"owner_authority") == "NOT_BOUND" &&
                Wire.text(data,"mode") == "OFFLINE_FIXTURE" && !Wire.flag(data,"live_verified") &&
                !Wire.flag(data,"verified") && !Wire.flag(data,"can_run"))
            val permissions = data.getValue("permissions").jsonObject
            require(permissions.keys == deniedPermissions && permissions.keys.all { !Wire.flag(permissions,it) })
            val provider = Wire.text(data,"provider_id"); val model = Wire.text(data,"model_id")
            require(provider == "meta_model_api" && model == "muse-spark-1.3")
            val state = AgentState.valueOf(Wire.text(data,"state"))
            val files = data.getValue("files").jsonObject
            require(files.size <= 8)
            files.forEach { (name,value) ->
                require(Regex("[A-Za-z0-9][A-Za-z0-9_.-]{0,63}").matches(name))
                val file = value.jsonObject; val text = Wire.text(file,"text").toByteArray(Charsets.UTF_8)
                require(text.size in 1..8192 && Wire.integer(file,"bytes") == text.size.toLong() &&
                    Wire.text(file,"sha256") == Wire.sha(text))
            }
            val receipt = data["receipt"]?.takeUnless { it == JsonNull }?.jsonObject
            if (state == AgentState.AGENT_COMPLETED) require(receipt != null)
            if (receipt != null) {
                require(state == AgentState.AGENT_COMPLETED && Wire.flag(receipt,"local_readback_verified") &&
                    !Wire.flag(receipt,"live_verified") && Wire.text(receipt,"mode") == "OFFLINE_FIXTURE" &&
                    Wire.text(receipt,"task_id") == Wire.text(data,"task_id") &&
                    Wire.text(receipt,"task_digest") == Wire.text(data,"task_digest") &&
                    Wire.text(receipt,"source_sha") == source && Wire.text(receipt,"capsule_digest") == capsule &&
                    Wire.text(receipt,"operation_digest") == "sha256:"+Wire.sha(Wire.canonical(data.getValue("operation").jsonObject)))
            }
            val steps = data.getValue("steps").jsonArray
            require(steps.size <= 16)
            return AgentMissionView(Wire.text(data,"task_id"),state,Wire.text(data,"task_digest"),
                files,data.getValue("diff").jsonObject,steps,data.getValue("tests").jsonObject,
                data.getValue("install_plan").jsonObject,data.getValue("git").jsonObject,receipt,provider,model)
        }
    }
}
