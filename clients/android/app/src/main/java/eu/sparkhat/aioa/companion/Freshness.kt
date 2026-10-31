package eu.sparkhat.aioa.companion

/** Pure lifecycle rule shared by the ViewModel and JVM contract tests. */
data class Freshness(val generation: Long = 0, val state: String = "STALE") {
    fun invalidate(reason: String = "STALE") = Freshness(generation+1,reason)
    fun accept(epoch: Long): Freshness = if (epoch == generation) copy(state="FRESH") else this
    fun canStop(taskState: String) = state == "FRESH" && taskState in setOf("PREVIEWED","RUNNING","LIVE_PENDING_AUTHORIZATION")
}
